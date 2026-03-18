//! ISO transfer ring for USB Audio output.
//!
//! # Design
//!
//! Maintains N=16 in-flight isochronous OUT transfers, each carrying P=8 ISO
//! packets (covering 8 ms of audio).  All transfers are submitted at startup;
//! when one completes its callback immediately refills the buffer from
//! [`FrameQueue`] and resubmits — forming a self-sustaining "always full" ring.
//!
//! If the queue is empty the callback fills with silence, preventing USB
//! underruns at the cost of a small glitch.  The clock feed is advanced by the
//! actual sample count written per ISO packet.
//!
//! # Safety model
//!
//! `RingState` is kept in an `Arc`.  Each transfer's `user_data` stores the raw
//! pointer from `Arc::as_ptr` (not `into_raw`).  The Arc is owned by
//! `IsoTransferRing`, guaranteeing validity for the lifetime of any callback.
//! The stop sequence sets `stop = true`, cancels all transfers, then joins the
//! event thread before dropping the Arc.

use std::os::raw::{c_int, c_uchar, c_uint};
use std::sync::atomic::{AtomicBool, AtomicI32, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};

use libusb1_sys::{
    libusb_alloc_transfer, libusb_cancel_transfer, libusb_context, libusb_device_handle,
    libusb_fill_iso_transfer, libusb_free_transfer, libusb_handle_events_timeout,
    libusb_set_iso_packet_lengths, libusb_submit_transfer, libusb_transfer,
};

use crate::alsa_clock::AlsaHwClockFeed;

use super::feedback::RateAdapter;
use super::queue::FrameQueue;

// ---------------------------------------------------------------------------
// Ring parameters
// ---------------------------------------------------------------------------

/// Number of concurrent in-flight transfers.
const N_TRANSFERS: usize = 16;
/// ISO packets per transfer — each packet = 1 ms of audio.
const N_PACKETS: usize = 8;

// ---------------------------------------------------------------------------
// Shared state (Arc, accessed from both event thread and main thread)
// ---------------------------------------------------------------------------

pub struct RingState {
    pub queue: Arc<FrameQueue>,
    pub stop: AtomicBool,
    /// Guards `RateAdapter` — only the event thread calls `samples_this_packet`
    /// in the hot path; main thread resets on format change.
    pub rate_adapter: Mutex<RateAdapter>,
    /// Latest feedback value in millisamples (updated from feedback callback).
    pub feedback_ms: Mutex<Option<i64>>,
    /// Bytes per audio sample (e.g. 4 for S32LE, 3 for S24_3LE).
    pub bytes_per_sample: usize,
    /// Number of audio channels.
    pub channels: usize,
    /// `wMaxPacketSize` from the ISO OUT endpoint descriptor.
    pub max_packet: usize,
    /// Transfers that have been submitted but not yet completed.
    pub in_flight: AtomicI32,
    /// Frame-counting clock feed (shared with GStreamer pipeline).
    pub clock_feed: Arc<AlsaHwClockFeed>,
}

impl RingState {
    pub fn new(
        queue: Arc<FrameQueue>,
        rate: u32,
        bytes_per_sample: usize,
        channels: usize,
        max_packet: usize,
        clock_feed: Arc<AlsaHwClockFeed>,
    ) -> Arc<Self> {
        Arc::new(Self {
            queue,
            stop: AtomicBool::new(false),
            rate_adapter: Mutex::new(RateAdapter::new(rate)),
            feedback_ms: Mutex::new(None),
            bytes_per_sample,
            channels,
            max_packet,
            in_flight: AtomicI32::new(0),
            clock_feed,
        })
    }
}

// ---------------------------------------------------------------------------
// ISO OUT callback (called by libusb event thread)
// ---------------------------------------------------------------------------

/// Fill the transfer buffer from [`FrameQueue`], setting each ISO packet's
/// `length` field to the computed sample count for this packet.
///
/// Silence (zeros) is used for any bytes not available in the queue.
///
/// # Safety
///
/// Caller must guarantee `transfer` and `state` are valid and aligned.
unsafe fn fill_transfer(state: &RingState, transfer: *mut libusb_transfer) {
    let n_packets = (*transfer).num_iso_packets as usize;
    let buf_base = (*transfer).buffer as *mut u8;
    let buf_len = ((*transfer).length) as usize;

    // Set all packet slots to max_packet first (libusb needs this for buffer
    // addressing), then override individual lengths below.
    libusb_set_iso_packet_lengths(transfer, state.max_packet as c_uint);

    let feedback = *state.feedback_ms.lock().unwrap_or_else(|e| e.into_inner());
    let mut adapter = state.rate_adapter.lock().unwrap_or_else(|e| e.into_inner());

    let mut offset = 0usize;
    for i in 0..n_packets {
        let samples = adapter.samples_this_packet(feedback) as usize;
        let packet_bytes = (samples * state.channels * state.bytes_per_sample)
            .min(state.max_packet)
            .min(buf_len.saturating_sub(offset));

        // Set actual packet length in the ISO descriptor
        let pkt = (*transfer)
            .iso_packet_desc
            .as_mut_ptr()
            .add(i);
        (*pkt).length = packet_bytes as c_uint;

        // Fill from queue; silence-pad anything missing
        let pkt_buf = std::slice::from_raw_parts_mut(buf_base.add(offset), state.max_packet);
        let got = state.queue.pop(&mut pkt_buf[..packet_bytes]);
        if got < packet_bytes {
            pkt_buf[got..packet_bytes].fill(0);
        }

        // Advance clock by actual samples written
        state.clock_feed.advance(samples as u64);

        offset += state.max_packet;
    }
    drop(adapter);
}

/// libusb ISO OUT transfer completion callback.
extern "system" fn iso_out_callback(transfer: *mut libusb_transfer) {
    // SAFETY: user_data == Arc::as_ptr(&state); valid while IsoTransferRing alive.
    let state = unsafe { &*((*transfer).user_data as *const RingState) };

    state.in_flight.fetch_sub(1, Ordering::AcqRel);

    if state.stop.load(Ordering::Acquire) {
        // Stop requested — do not resubmit.  Event thread will exit once
        // in_flight reaches zero.
        return;
    }

    // Refill the buffer regardless of transfer status (STALL → silence keeps
    // the endpoint alive; don't let the ring go empty).
    unsafe { fill_transfer(state, transfer) };

    let rc = unsafe { libusb_submit_transfer(transfer) };
    if rc == 0 {
        state.in_flight.fetch_add(1, Ordering::AcqRel);
    }
    // On submit failure, in_flight stays decremented; the ring self-heals if
    // other transfers are still running, or stop() will clean up.
}

// ---------------------------------------------------------------------------
// IsoTransferRing
// ---------------------------------------------------------------------------

/// Manages N isochronous OUT transfers in a self-sustaining callback loop.
///
/// # Ownership
///
/// Owns the transfer structs and their backing buffers.  The raw pointers are
/// valid for exactly the lifetime of this struct; the event thread is joined
/// in [`stop`] / [`Drop`] before any deallocation.
pub struct IsoTransferRing {
    transfers: Vec<*mut libusb_transfer>,
    /// Backing PCM buffers — must stay alive while transfers are in flight.
    _bufs: Vec<Vec<u8>>,
    pub state: Arc<RingState>,
    /// Raw libusb context pointer (borrowed from the DeviceHandle's context).
    ctx_raw: *mut libusb_context,
    event_thread: Option<JoinHandle<()>>,
}

// SAFETY: All raw pointers are valid for the struct's lifetime.
// The event thread is always joined before drop.
unsafe impl Send for IsoTransferRing {}
unsafe impl Sync for IsoTransferRing {}

impl IsoTransferRing {
    /// Allocate N=16 transfers and their buffers.
    ///
    /// Does **not** submit them yet — call [`start`] to begin playback.
    ///
    /// # Arguments
    ///
    /// * `dev_handle_raw` — `DeviceHandle::as_raw()`
    /// * `ctx_raw` — `handle.context().as_raw()` — must outlive this struct
    /// * `ep` — ISO OUT endpoint address
    /// * `state` — shared ring state
    pub fn new(
        dev_handle_raw: *mut libusb_device_handle,
        ctx_raw: *mut libusb_context,
        ep: u8,
        state: Arc<RingState>,
    ) -> Result<Self, String> {
        let buf_size = N_PACKETS * state.max_packet;
        let state_ptr = Arc::as_ptr(&state) as *mut std::ffi::c_void;

        let mut transfers = Vec::with_capacity(N_TRANSFERS);
        let mut bufs = Vec::with_capacity(N_TRANSFERS);

        for _ in 0..N_TRANSFERS {
            let mut buf: Vec<u8> = vec![0u8; buf_size];

            let xfer = unsafe { libusb_alloc_transfer(N_PACKETS as c_int) };
            if xfer.is_null() {
                // Free any already-allocated transfers before returning
                for t in &transfers {
                    unsafe { libusb_free_transfer(*t) };
                }
                return Err("libusb_alloc_transfer failed (out of memory)".into());
            }

            unsafe {
                libusb_fill_iso_transfer(
                    xfer,
                    dev_handle_raw,
                    ep as c_uchar,
                    buf.as_mut_ptr() as *mut c_uchar,
                    buf_size as c_int,
                    N_PACKETS as c_int,
                    iso_out_callback,
                    state_ptr,
                    0, // timeout = 0 (no timeout)
                );
                libusb_set_iso_packet_lengths(xfer, state.max_packet as c_uint);
            }

            transfers.push(xfer);
            bufs.push(buf);
        }

        Ok(Self {
            transfers,
            _bufs: bufs,
            state,
            ctx_raw,
            event_thread: None,
        })
    }

    /// Submit all transfers and spawn the libusb event loop thread.
    pub fn start(&mut self) -> Result<(), String> {
        self.state.stop.store(false, Ordering::SeqCst);
        self.state.in_flight.store(0, Ordering::SeqCst);

        // Fill all transfer buffers before first submission
        for &xfer in &self.transfers {
            unsafe { fill_transfer(&self.state, xfer) };
        }

        // Submit all transfers
        for &xfer in &self.transfers {
            let rc = unsafe { libusb_submit_transfer(xfer) };
            if rc == 0 {
                self.state.in_flight.fetch_add(1, Ordering::AcqRel);
            }
        }

        // Spawn event loop thread.
        // Cast the raw context pointer to usize so the closure captures a
        // Send type; libusb contexts are thread-safe per the libusb docs.
        let ctx_addr = self.ctx_raw as usize;
        let state = Arc::clone(&self.state);
        let handle = thread::Builder::new()
            .name("usb-iso-events".into())
            .spawn(move || {
                let ctx = ctx_addr as *mut libusb_context;
                let tv = libc::timeval { tv_sec: 0, tv_usec: 1_000 }; // 1 ms
                while !state.stop.load(Ordering::Acquire)
                    || state.in_flight.load(Ordering::Acquire) > 0
                {
                    unsafe {
                        libusb_handle_events_timeout(ctx, &tv);
                    }
                }
            })
            .map_err(|e| format!("spawn usb-iso-events thread: {}", e))?;

        self.event_thread = Some(handle);
        Ok(())
    }

    /// Stop the transfer ring gracefully.
    ///
    /// 1. Sets `stop = true` (callbacks will not resubmit)
    /// 2. Cancels all in-flight transfers
    /// 3. Waits for the event thread to drain and exit
    pub fn stop(&mut self) {
        self.state.stop.store(true, Ordering::SeqCst);

        for &xfer in &self.transfers {
            unsafe { libusb_cancel_transfer(xfer) };
        }

        if let Some(t) = self.event_thread.take() {
            let _ = t.join();
        }
    }
}

impl Drop for IsoTransferRing {
    fn drop(&mut self) {
        self.stop();
        for &xfer in &self.transfers {
            unsafe { libusb_free_transfer(xfer) };
        }
    }
}
