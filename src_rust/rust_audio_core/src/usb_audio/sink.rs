//! `UsbAudioSink` — top-level orchestration for USB audio output.
//!
//! # Lifecycle
//!
//! ```text
//! UsbAudioSink::open(device_id, rate, bit_depth)
//!   → find device → open handle → configure alt/rate
//!   → create FrameQueue + AlsaHwClockFeed
//!   → build RingState → start IsoTransferRing
//!   → start FeedbackReader (UAC 2.0 only)
//!   → return (UsbAudioSink, AlsaHwClock)
//! ```
//!
//! The caller pushes PCM bytes into [`UsbAudioSink::queue`] via the GStreamer
//! appsink; the `IsoTransferRing` drains the queue in its callback loop.
//!
//! Drop order is significant — fields are dropped top-to-bottom in declaration
//! order:
//! 1. `_feedback` — cancel feedback ISO IN transfer
//! 2. `_ring`     — stop ISO OUT ring + join event thread
//! 3. `_open_dev` — release USB interface / device handle
//!
//! # FeedbackReader
//!
//! For UAC 2.0 asynchronous devices the DAC sends the actual sample rate back
//! on a dedicated ISO IN endpoint every `2^(10−P)` microframes.  A single
//! always-resubmitting transfer reads these packets; the parsed value is stored
//! in `RingState::feedback_ms` where the ISO OUT callback consumes it.

use std::os::raw::{c_int, c_uchar, c_uint, c_void};
use std::sync::atomic::Ordering;
use std::sync::Arc;

use libusb1_sys::{
    libusb_alloc_transfer, libusb_cancel_transfer, libusb_device_handle,
    libusb_fill_iso_transfer, libusb_free_transfer, libusb_set_iso_packet_lengths,
    libusb_submit_transfer, libusb_transfer,
};

use rusb::UsbContext as _;

use crate::alsa_clock::{AlsaHwClock, AlsaHwClockFeed};

use super::descriptor::UacVersion;
use super::device::{enumerate_usb_audio_devices, OpenUsbDevice, UsbAudioDevice};
use super::feedback::{parse_feedback_uac1, parse_feedback_uac2};
use super::queue::FrameQueue;
use super::transfer::{IsoTransferRing, RingState};

// ---------------------------------------------------------------------------
// UsbAudioSink
// ---------------------------------------------------------------------------

/// An active USB audio output session.
///
/// Holds all live resources for one playback session.  Drop (or `stop()`) to
/// tear down the transfer ring and release the USB interface.
pub struct UsbAudioSink {
    /// PCM byte queue — push encoded audio here from the GStreamer appsink.
    pub queue: Arc<FrameQueue>,
    /// Frame-counting clock feed — expose to GStreamer as `AlsaHwClock`.
    pub feed: Arc<AlsaHwClockFeed>,
    /// Shared transfer state — exposes `error` and `xruns` counters.
    pub state: Arc<RingState>,
    /// ISO IN feedback reader (UAC 2.0 only). Dropped before `ring`.
    _feedback: Option<FeedbackReader>,
    /// ISO OUT transfer ring + event thread. Dropped before `_open_dev`.
    ring: IsoTransferRing,
    /// Open USB device handle + claimed interface. Dropped last.
    _open_dev: OpenUsbDevice,
}

impl UsbAudioSink {
    /// `true` if a fatal USB transfer error (device disconnect) was detected.
    pub fn has_error(&self) -> bool {
        self.state.error.load(std::sync::atomic::Ordering::Acquire)
    }

    /// Total ISO packets filled with silence due to an empty queue (underruns).
    /// Each unit represents 1 ms of silence.
    pub fn xrun_count(&self) -> u64 {
        self.state.xruns.load(std::sync::atomic::Ordering::Relaxed)
    }
}

impl UsbAudioSink {
    /// Open a USB Audio device and start the isochronous transfer ring.
    ///
    /// # Arguments
    ///
    /// * `device_id`  — `"usb:VVVV:PPPP"` or `"usb:VVVV:PPPP:SERIAL"`
    /// * `rate`       — desired sample rate in Hz (e.g. 44100, 48000, 96000)
    /// * `bit_depth`  — desired bit depth (16, 24, or 32)
    ///
    /// Returns `(Self, AlsaHwClock)`.  Pass the clock to
    /// `pipeline.use_clock(Some(&clock))` so GStreamer paces the pipeline with
    /// the USB frame counter.
    pub fn open(
        device_id: &str,
        rate: u32,
        bit_depth: u8,
    ) -> Result<(Self, AlsaHwClock), String> {
        // 1. Enumerate to find the requested device.
        let dev = find_device_by_id(device_id)
            .ok_or_else(|| format!("USB audio device '{}' not found", device_id))?;

        // 2. Allocate the SPSC frame queue.
        let queue = FrameQueue::new();

        // 3. Create frame-counting clock feed + GStreamer clock.
        let feed = Arc::new(AlsaHwClockFeed::default());
        let clock = AlsaHwClock::new(Arc::clone(&feed));

        // 4. Open the device handle and configure the best alt-setting.
        let mut open_dev = OpenUsbDevice::open(&dev)?;

        let alt = open_dev
            .best_alt(rate, bit_depth)
            .ok_or_else(|| {
                format!(
                    "no alt-setting for rate={} bit_depth={} on '{}'",
                    rate, bit_depth, device_id
                )
            })?
            .clone();

        open_dev.configure(&alt, rate)?;

        // 5. Obtain raw libusb handles (valid for the lifetime of open_dev).
        let dev_handle_raw = open_dev.handle.as_raw();
        let ctx_raw = open_dev.handle.context().as_raw();

        // 6. Build shared ring state.
        //    Use bSubFrameSize/bSubSlotSize for the exact wire byte count:
        //    S24_3LE → subframe_size=3; S24LE (32-bit container) → 4; S32LE/F32LE → 4.
        let bytes_per_sample = if alt.subframe_size > 0 {
            alt.subframe_size as usize
        } else {
            (alt.bit_depth as usize + 7) / 8
        };
        let state = RingState::new(
            Arc::clone(&queue),
            rate,
            bytes_per_sample,
            alt.channels as usize,
            alt.max_packet as usize,
            Arc::clone(&feed),
        );

        // 7. Create and start the ISO OUT transfer ring.
        //    Anchor the clock immediately before the first transfer is submitted
        //    so the clock epoch aligns with the start of audio output.
        let anchor_ns = clock_monotonic_ns();
        feed.anchor(anchor_ns, rate);

        let mut ring =
            IsoTransferRing::new(dev_handle_raw, ctx_raw, alt.out_ep, Arc::clone(&state))?;
        ring.start()?;

        // 8. Start UAC 2.0 feedback reader (optional).
        let feedback = alt
            .feedback_ep
            .map(|ep| {
                FeedbackReader::new(dev_handle_raw, ep, Arc::clone(&state), dev.uac_version)
                    .and_then(|mut fr| {
                        fr.start()?;
                        Ok(fr)
                    })
            })
            .transpose()?;

        Ok((
            UsbAudioSink {
                queue,
                feed,
                state,
                _feedback: feedback,
                ring,
                _open_dev: open_dev,
            },
            clock,
        ))
    }
}

// ---------------------------------------------------------------------------
// Device lookup helpers
// ---------------------------------------------------------------------------

/// Find a device in the live enumeration by its string ID.
fn find_device_by_id(device_id: &str) -> Option<UsbAudioDevice> {
    // Expected format: "usb:VVVV:PPPP" or "usb:VVVV:PPPP:SERIAL"
    let parts: Vec<&str> = device_id.splitn(4, ':').collect();
    if parts.len() < 3 || parts[0] != "usb" {
        return None;
    }
    let vid = u16::from_str_radix(parts[1], 16).ok()?;
    let pid = u16::from_str_radix(parts[2], 16).ok()?;
    let serial: Option<&str> = parts.get(3).copied();

    enumerate_usb_audio_devices().into_iter().find(|d| {
        d.vendor_id == vid
            && d.product_id == pid
            && (serial.is_none() || d.serial.as_deref() == serial)
    })
}

/// Read `CLOCK_MONOTONIC` as nanoseconds via libc.
fn clock_monotonic_ns() -> u64 {
    let mut ts = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    // SAFETY: valid pointer, valid clock ID.
    unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut ts) };
    ts.tv_sec as u64 * 1_000_000_000 + ts.tv_nsec as u64
}

// ---------------------------------------------------------------------------
// FeedbackReader — UAC 2.0 ISO IN feedback consumer
// ---------------------------------------------------------------------------

/// Context stored as `user_data` in the feedback libusb transfer.
///
/// Boxed and kept alive by `FeedbackReader::_ctx` for the transfer lifetime.
struct FeedbackCtx {
    state: Arc<RingState>,
    uac_version: UacVersion,
}

/// libusb ISO IN completion callback for the feedback endpoint.
///
/// Parses the feedback value and updates `RingState::feedback_ms`, then
/// resubmits the transfer unless `state.stop` is set.
extern "system" fn feedback_in_callback(transfer: *mut libusb_transfer) {
    // SAFETY: user_data == &FeedbackCtx; valid while FeedbackReader alive.
    let ctx = unsafe { &*((*transfer).user_data as *const FeedbackCtx) };

    if ctx.state.stop.load(Ordering::Acquire) {
        return; // Stop requested — do not resubmit.
    }

    // Parse only completed packets.
    if unsafe { (*transfer).status } == libusb1_sys::constants::LIBUSB_TRANSFER_COMPLETED {
        let len = unsafe { (*transfer).actual_length } as usize;
        let buf = unsafe {
            std::slice::from_raw_parts((*transfer).buffer as *const u8, len)
        };
        let ms = match ctx.uac_version {
            UacVersion::V2 => parse_feedback_uac2(buf),
            UacVersion::V1 => parse_feedback_uac1(buf),
        };
        if let Some(v) = ms {
            if let Ok(mut lock) = ctx.state.feedback_ms.lock() {
                *lock = Some(v);
            }
        }
    }

    // Resubmit for the next feedback packet.
    unsafe { libusb_submit_transfer(transfer) };
}

/// Manages a single always-resubmitting ISO IN transfer on the feedback
/// endpoint.  The completed event is handled by the `IsoTransferRing`'s
/// `usb-iso-events` thread (shared libusb context).
pub struct FeedbackReader {
    transfer: *mut libusb_transfer,
    /// PCM buffer backing the transfer (must outlive it).
    _buf: Vec<u8>,
    /// Keeps `FeedbackCtx` alive for the duration of the transfer.
    _ctx: Box<FeedbackCtx>,
}

// SAFETY: raw pointers are valid for the struct's lifetime;
// the event thread is joined (by IsoTransferRing) before drop.
unsafe impl Send for FeedbackReader {}

impl FeedbackReader {
    /// Allocate the feedback transfer (does **not** submit it yet).
    pub fn new(
        dev_handle_raw: *mut libusb_device_handle,
        ep: u8,
        state: Arc<RingState>,
        uac_version: UacVersion,
    ) -> Result<Self, String> {
        // UAC 2.0 feedback: 4 bytes (Q16.16); UAC 1.0: 3 bytes (Q10.14).
        let buf_len: usize = match uac_version {
            UacVersion::V2 => 4,
            UacVersion::V1 => 3,
        };
        let mut buf = vec![0u8; buf_len];

        let ctx_box = Box::new(FeedbackCtx { state, uac_version });
        let ctx_ptr = ctx_box.as_ref() as *const FeedbackCtx as *mut c_void;

        let xfer = unsafe { libusb_alloc_transfer(1) };
        if xfer.is_null() {
            return Err("libusb_alloc_transfer failed for feedback endpoint".into());
        }

        unsafe {
            libusb_fill_iso_transfer(
                xfer,
                dev_handle_raw,
                ep as c_uchar,
                buf.as_mut_ptr() as *mut c_uchar,
                buf_len as c_int,
                1, // 1 ISO packet
                feedback_in_callback,
                ctx_ptr,
                0, // no timeout
            );
            libusb_set_iso_packet_lengths(xfer, buf_len as c_uint);
        }

        Ok(FeedbackReader {
            transfer: xfer,
            _buf: buf,
            _ctx: ctx_box,
        })
    }

    /// Submit the transfer for the first time.
    pub fn start(&mut self) -> Result<(), String> {
        let rc = unsafe { libusb_submit_transfer(self.transfer) };
        if rc != 0 {
            return Err(format!("submit feedback ISO IN transfer: rc={}", rc));
        }
        Ok(())
    }

    fn cancel(&self) {
        unsafe { libusb_cancel_transfer(self.transfer) };
    }
}

impl Drop for FeedbackReader {
    fn drop(&mut self) {
        self.cancel();
        // The event thread (owned by IsoTransferRing, dropped after us) will
        // drain the cancelled transfer before exiting.
        unsafe { libusb_free_transfer(self.transfer) };
    }
}
