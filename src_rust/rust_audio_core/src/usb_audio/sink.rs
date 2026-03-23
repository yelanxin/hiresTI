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
//! 1. `ring`      — stop ISO OUT ring: cancels feedback + OUT transfers, joins
//!                  event thread (waits for `feedback_in_flight = false`)
//! 2. `_feedback` — free feedback ISO IN transfer (safe: event thread exited)
//! 3. `_open_dev` — release USB interface / device handle → snd-usb-audio re-attaches
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
    libusb_alloc_transfer, libusb_cancel_transfer, libusb_device_handle, libusb_fill_iso_transfer,
    libusb_free_transfer, libusb_set_iso_packet_lengths, libusb_submit_transfer, libusb_transfer,
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
    /// Actual sample rate negotiated with the device.  May differ from the
    /// requested rate for UAC 2.0 devices with a fixed (non-programmable) clock.
    pub actual_rate: u32,
    /// ISO OUT transfer ring + event thread.
    ///
    /// **Must be dropped before `_feedback`.**  `IsoTransferRing::drop()` calls
    /// `stop()` which cancels the feedback + OUT transfers and joins the event
    /// thread (waiting for `feedback_in_flight = false`).  Only then is it safe
    /// for `_feedback.drop()` to call `libusb_free_transfer()`.
    #[allow(dead_code)]
    ring: IsoTransferRing,
    /// ISO IN feedback reader (UAC 2.0 only).
    /// Dropped **after** `ring` so the transfer is freed only after the event
    /// thread has fully exited.
    _feedback: Option<FeedbackReader>,
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
    pub fn open(device_id: &str, rate: u32, bit_depth: u8) -> Result<(Self, AlsaHwClock), String> {
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

        // Read back the actual negotiated rate.  For UAC 2.0 devices with a
        // fixed clock, configure() may have updated active_rate to the value
        // returned by GET_CUR rather than the requested `rate`.
        let actual_rate = open_dev.active_rate;
        eprintln!(
            "usb-audio: sink::open device={} requested_rate={} actual_rate={} bit_depth={} channels={}",
            device_id, rate, actual_rate, bit_depth, alt.channels
        );

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
        queue.set_frame_bytes(alt.channels as usize * bytes_per_sample);
        let packets_per_sec = iso_packets_per_sec(dev.is_high_speed, alt.out_ep_interval);
        let state = RingState::new(
            Arc::clone(&queue),
            actual_rate,
            bytes_per_sample,
            alt.channels as usize,
            alt.max_packet as usize,
            packets_per_sec,
            alt.feedback_ep.is_some(),
            Arc::clone(&feed),
        );

        // 7. Create and start the ISO OUT transfer ring.
        //    Anchor the clock with the actual device rate so the frame counter
        //    advances at the correct pace.
        let anchor_ns = clock_monotonic_ns();
        feed.anchor(anchor_ns, actual_rate);

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

        // Register feedback transfer with the ring so stop() can cancel it.
        if let Some(ref fb) = feedback {
            ring.feedback_xfer = Some(fb.transfer);
        }

        Ok((
            UsbAudioSink {
                queue,
                feed,
                state,
                actual_rate,
                ring,
                _feedback: feedback,
                _open_dev: open_dev,
            },
            clock,
        ))
    }

    /// Open the USB device using a caller-supplied clock feed.
    ///
    /// Like [`open`] but the caller creates the [`AlsaHwClockFeed`] (and its
    /// paired [`AlsaHwClock`]) before calling this function.  This enables a
    /// **lazy-open** pattern: give GStreamer the clock immediately, then call
    /// this once the negotiated sample rate is known (e.g. on the first PCM
    /// buffer from the appsink).
    ///
    /// The feed is anchored inside this call at the actual negotiated rate.
    ///
    /// `prefill` (when provided) is pushed into the queue before the ISO ring
    /// is started so the first submitted transfers can carry real audio rather
    /// than startup silence.
    pub fn open_with_feed(
        device_id: &str,
        rate: u32,
        bit_depth: u8,
        feed: Arc<AlsaHwClockFeed>,
        prefill: Option<&[u8]>,
    ) -> Result<Self, String> {
        // 1. Find device.
        let dev = find_device_by_id(device_id)
            .ok_or_else(|| format!("USB audio device '{}' not found", device_id))?;

        // 2. Frame queue.
        let queue = FrameQueue::new();

        if let Some(data) = prefill.filter(|data| !data.is_empty()) {
            let written = queue.push(data);
            if written < data.len() {
                eprintln!(
                    "usb-audio: startup prefill truncated {} -> {} bytes",
                    data.len(),
                    written
                );
            }
        }

        // 3. Open device handle and configure.
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

        let actual_rate = open_dev.active_rate;
        eprintln!(
            "usb-audio: sink::open_with_feed device={} requested_rate={} actual_rate={} bit_depth={} channels={} feedback_ep={:?}",
            device_id, rate, actual_rate, bit_depth, alt.channels, alt.feedback_ep
        );

        // 4. Raw handles.
        let dev_handle_raw = open_dev.handle.as_raw();
        let ctx_raw = open_dev.handle.context().as_raw();

        // 5. Ring state.
        let bytes_per_sample = if alt.subframe_size > 0 {
            alt.subframe_size as usize
        } else {
            (alt.bit_depth as usize + 7) / 8
        };
        queue.set_frame_bytes(alt.channels as usize * bytes_per_sample);
        let packets_per_sec = iso_packets_per_sec(dev.is_high_speed, alt.out_ep_interval);
        let state = RingState::new(
            Arc::clone(&queue),
            actual_rate,
            bytes_per_sample,
            alt.channels as usize,
            alt.max_packet as usize,
            packets_per_sec,
            alt.feedback_ep.is_some(),
            Arc::clone(&feed),
        );

        // 6. Anchor the caller's clock feed and start the ring.
        let anchor_ns = clock_monotonic_ns();
        feed.anchor(anchor_ns, actual_rate);

        let mut ring =
            IsoTransferRing::new(dev_handle_raw, ctx_raw, alt.out_ep, Arc::clone(&state))?;
        ring.start()?;

        // 7. Feedback reader (UAC 2.0 only).
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

        // Register feedback transfer with the ring so stop() can cancel it.
        if let Some(ref fb) = feedback {
            ring.feedback_xfer = Some(fb.transfer);
        }

        Ok(UsbAudioSink {
            queue,
            feed,
            state,
            actual_rate,
            ring,
            _feedback: feedback,
            _open_dev: open_dev,
        })
    }
}

// ---------------------------------------------------------------------------
// Device lookup helpers
// ---------------------------------------------------------------------------

/// Compute the number of ISO packets (transfer completions) per second from
/// the endpoint's `bInterval` and the USB bus speed.
///
/// For **High-Speed** (USB 2.0, 480 Mbit/s) isochronous endpoints:
///   interval = 2^(bInterval-1) × 125 µs
///   → bInterval=1 → 8000/s, bInterval=4 → 1000/s, …
///
/// For **Full-Speed** (USB 1.1, 12 Mbit/s) isochronous endpoints:
///   interval = bInterval × 1 ms  (bInterval=1 → 1000/s for typical audio devices)
fn iso_packets_per_sec(is_high_speed: bool, b_interval: u8) -> u32 {
    let b = b_interval.max(1) as u32;
    if is_high_speed {
        // HS: interval in microframes = 2^(bInterval-1); 8000 µf/sec total
        let microframes = 1u32 << (b - 1).min(13);
        8_000 / microframes
    } else {
        // FS: interval in 1ms frames
        1_000 / b
    }
}

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
    let mut ts = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
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
///
/// `ema` holds the exponential moving average of feedback millisamples.
/// It is only ever read/written from the libusb event thread (the single
/// thread that calls `feedback_in_callback`), so no locking is needed.
struct FeedbackCtx {
    state: Arc<RingState>,
    uac_version: UacVersion,
    ep: u8,
    /// EMA accumulator for feedback smoothing (α = 1/16).
    /// `None` until the first feedback packet arrives.
    ema: Option<i64>,
    callbacks: u64,
    parse_failures: u64,
    rejected_outliers: u64,
    /// Consecutive rejected feedback packets.  When this exceeds
    /// `CONSECUTIVE_REJECT_THRESHOLD` the stale EMA value is cleared from
    /// `feedback_ms` so `fill_transfer` falls back to the calibrated
    /// clock rate — preventing device-side FIFO overflow from a stale
    /// (slightly too-high) feedback value.
    consecutive_rejects: u64,
}

/// Mark feedback tracking as stopped.
///
/// When `device_gone` is true, also publish the same fatal-disconnect state the
/// ISO OUT ring uses so the pusher thread can surface the error.
fn stop_feedback_tracking(state: &RingState, device_gone: bool) {
    state.feedback_in_flight.store(false, Ordering::Release);
    if device_gone {
        state.error.store(true, Ordering::Release);
        state.stop.store(true, Ordering::Release);
    }
}

/// Handle a feedback transfer resubmit failure.
///
/// No future callback will arrive after a failed resubmit, so the in-flight
/// flag must be cleared here or `IsoTransferRing::stop()` may wait forever.
fn handle_feedback_resubmit_failure(state: &RingState, rc: c_int) {
    let no_device = rc == libusb1_sys::constants::LIBUSB_ERROR_NO_DEVICE;
    eprintln!(
        "usb-audio: feedback resubmit failed rc={}{}",
        rc,
        if no_device {
            " (device disconnected)"
        } else {
            ""
        }
    );
    stop_feedback_tracking(state, no_device);
}

fn format_feedback_bytes(buf: &[u8]) -> String {
    let mut out = String::new();
    for (idx, byte) in buf.iter().enumerate() {
        if idx > 0 {
            out.push(' ');
        }
        use std::fmt::Write as _;
        let _ = write!(&mut out, "{:02x}", byte);
    }
    out
}

fn feedback_rate_hz(ms: i64, packets_per_sec: u32) -> f64 {
    ms as f64 / 1_000_000.0 * packets_per_sec as f64
}

/// libusb ISO IN completion callback for the feedback endpoint.
///
/// Parses the feedback value, applies a 1/16 EMA to smooth quantisation
/// noise from the device's fixed-point feedback format, and updates
/// `RingState::feedback_ms`.  Then resubmits unless `state.stop` is set.
///
/// # EMA smoothing
///
/// Raw feedback packets carry a Q16.16 (UAC 2.0) or Q10.14 (UAC 1.0)
/// fixed-point value.  Each quantisation step causes an immediate step in
/// the per-packet sample count which the listener can perceive as high-
/// frequency jitter ("hardness").  An exponential moving average with
/// α = 1/16 attenuates steps while still tracking slow crystal drift:
///
/// ```text
/// ema_new = ema_old + (raw - ema_old) / 16
/// ```
///
/// Time constant ≈ 16 × feedback_interval.  For a typical 8 ms feedback
/// period this is ~128 ms — fast enough to follow ppm-level drift,
/// slow enough to suppress packet-to-packet jitter.
extern "system" fn feedback_in_callback(transfer: *mut libusb_transfer) {
    // SAFETY: user_data == &mut FeedbackCtx; valid while FeedbackReader alive.
    // The callback is only ever invoked from the single libusb event thread,
    // so mutable access to `ctx.ema` is safe without additional locking.
    let ctx = unsafe { &mut *((*transfer).user_data as *mut FeedbackCtx) };
    ctx.callbacks = ctx.callbacks.saturating_add(1);

    if ctx.state.stop.load(Ordering::Acquire) {
        // Stop requested — do not resubmit.
        stop_feedback_tracking(&ctx.state, false);
        return;
    }

    let status = unsafe { (*transfer).status };
    if status != libusb1_sys::constants::LIBUSB_TRANSFER_COMPLETED {
        // Non-recoverable status (CANCELLED, NO_DEVICE, etc.) — stop tracking.
        eprintln!(
            "usb-audio: feedback callback ep=0x{:02x} status={} callbacks={}",
            ctx.ep,
            status,
            ctx.callbacks,
        );
        stop_feedback_tracking(
            &ctx.state,
            status == libusb1_sys::constants::LIBUSB_TRANSFER_NO_DEVICE,
        );
        return;
    }

    // Parse only completed packets.  For ISO IN transfers, log both the
    // top-level transfer length and the per-packet descriptor length so we can
    // see whether libusb is reporting payload only via the packet descriptor.
    let transfer_len = unsafe { (*transfer).actual_length } as usize;
    let pkt_desc = unsafe { &*(*transfer).iso_packet_desc.as_ptr() };
    let pkt_actual_len = pkt_desc.actual_length as usize;
    let pkt_configured_len = pkt_desc.length as usize;
    let _pkt_status = pkt_desc.status;
    let raw_storage = unsafe {
        std::slice::from_raw_parts(
            (*transfer).buffer as *const u8,
            pkt_configured_len.min(16),
        )
    };
    // For ISO IN transfers libusb reports the real payload length per packet in
    // iso_packet_desc[i].actual_length.  The top-level transfer.actual_length
    // may remain zero even when packet payload is present.
    let payload_len = if pkt_actual_len > 0 {
        pkt_actual_len.min(pkt_configured_len)
    } else {
        transfer_len.min(pkt_configured_len)
    };
    let buf = unsafe {
        std::slice::from_raw_parts(
            (*transfer).buffer as *const u8,
            payload_len,
        )
    };
    let ms = match ctx.uac_version {
        UacVersion::V2 => parse_feedback_uac2(buf, ctx.state.packets_per_sec),
        UacVersion::V1 => parse_feedback_uac1(buf),
    };
    if let Some(raw) = ms {
        let raw_rate_hz = feedback_rate_hz(raw, ctx.state.packets_per_sec);
        let nominal_rate_hz = ctx.state.rate as f64;
        let raw_ppm = if nominal_rate_hz > 0.0 {
            (raw_rate_hz - nominal_rate_hz) / nominal_rate_hz * 1_000_000.0
        } else {
            0.0
        };
        // USB audio feedback should stay very close to nominal/sample-clock
        // reality. Reject obviously bogus packets (observed as transient 48 kHz
        // or ~44.32 kHz jumps on a 44.1 kHz stream) and keep the previous
        // stable value instead of letting one bad packet perturb pacing.
        const FEEDBACK_SANITY_MAX_PPM: f64 = 1000.0;
        let rejected = nominal_rate_hz > 0.0 && raw_ppm.abs() > FEEDBACK_SANITY_MAX_PPM;
        if rejected {
            ctx.rejected_outliers = ctx.rejected_outliers.saturating_add(1);
            ctx.consecutive_rejects = ctx.consecutive_rejects.saturating_add(1);
            if ctx.rejected_outliers <= 2 || (ctx.rejected_outliers % 4096 == 0) {
                eprintln!(
                    "usb-audio: feedback reject ep=0x{:02x} cb#{} reject#{} consec={} raw=[{}] rate={:.3}Hz ppm={:+.1}",
                    ctx.ep,
                    ctx.callbacks,
                    ctx.rejected_outliers,
                    ctx.consecutive_rejects,
                    format_feedback_bytes(raw_storage),
                    raw_rate_hz,
                    raw_ppm,
                );
            }
            // NOTE: we intentionally keep the stale EMA in feedback_ms.
            // The last good value (~44099.968 Hz) is much closer to the real
            // device consumption rate than nominal (44100 Hz).  Clearing it
            // would cause fill_transfer to use nominal, which over-delivers
            // and makes the queue grow rapidly (~6 ms/s vs ~0.06 ms/s).
        } else {
            ctx.consecutive_rejects = 0;
            // Apply EMA: seed with first value to avoid a slow ramp-up from zero.
            let smoothed = match ctx.ema {
                None => raw,
                Some(prev) => prev + (raw - prev) / 16,
            };
            ctx.ema = Some(smoothed);
            if ctx.callbacks <= 1 {
                let rate_hz = feedback_rate_hz(smoothed, ctx.state.packets_per_sec);
                eprintln!(
                    "usb-audio: feedback ep=0x{:02x} cb#{} raw=[{}] smoothed_ms={} rate={:.3}Hz",
                    ctx.ep,
                    ctx.callbacks,
                    format_feedback_bytes(raw_storage),
                    smoothed,
                    rate_hz,
                );
            }
            if let Ok(mut lock) = ctx.state.feedback_ms.lock() {
                *lock = Some(smoothed);
            }
        }
    } else {
        ctx.parse_failures = ctx.parse_failures.saturating_add(1);
        if ctx.parse_failures <= 2 || (ctx.parse_failures % 4096 == 0) {
            eprintln!(
                "usb-audio: feedback parse failed ep=0x{:02x} cb#{} fail#{} pkt_actual={} raw=[{}]",
                ctx.ep,
                ctx.callbacks,
                ctx.parse_failures,
                pkt_actual_len,
                format_feedback_bytes(raw_storage),
            );
        }
    }

    // Re-check stop before resubmitting to avoid re-arming the transfer after
    // `IsoTransferRing::stop()` has already requested shutdown.
    if ctx.state.stop.load(Ordering::Acquire) {
        stop_feedback_tracking(&ctx.state, false);
        return;
    }

    // Resubmit for the next feedback packet.
    let rc = unsafe { libusb_submit_transfer(transfer) };
    if rc != 0 {
        handle_feedback_resubmit_failure(&ctx.state, rc);
    }
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

        let ctx_box = Box::new(FeedbackCtx {
            state,
            uac_version,
            ep,
            ema: None,
            callbacks: 0,
            parse_failures: 0,
            rejected_outliers: 0,
            consecutive_rejects: 0,
        });
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
        // Mark in-flight BEFORE submitting so the event thread's exit
        // condition sees it immediately.
        self._ctx
            .state
            .feedback_in_flight
            .store(true, Ordering::Release);
        eprintln!(
            "usb-audio: feedback start ep=0x{:02x} uac={:?}",
            self._ctx.ep,
            self._ctx.uac_version,
        );
        let rc = unsafe { libusb_submit_transfer(self.transfer) };
        if rc != 0 {
            self._ctx
                .state
                .feedback_in_flight
                .store(false, Ordering::Release);
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
        // `ring` (IsoTransferRing) drops before us: its `stop()` already
        // cancelled this transfer and joined the event thread, so the
        // callback will never fire again.  `cancel()` here is a no-op
        // safety belt; `libusb_free_transfer` is then safe.
        self.cancel();
        unsafe { libusb_free_transfer(self.transfer) };
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn feedback_resubmit_failure_no_device_marks_disconnect_and_clears_inflight() {
        let queue = FrameQueue::new();
        let feed = Arc::new(AlsaHwClockFeed::default());
        let state = RingState::new(queue, 48_000, 4, 2, 192, 8_000, false, feed);
        state.feedback_in_flight.store(true, Ordering::Release);

        handle_feedback_resubmit_failure(&state, libusb1_sys::constants::LIBUSB_ERROR_NO_DEVICE);

        assert!(!state.feedback_in_flight.load(Ordering::Acquire));
        assert!(state.error.load(Ordering::Acquire));
        assert!(state.stop.load(Ordering::Acquire));
    }

    #[test]
    fn feedback_resubmit_failure_generic_only_clears_inflight() {
        let queue = FrameQueue::new();
        let feed = Arc::new(AlsaHwClockFeed::default());
        let state = RingState::new(queue, 48_000, 4, 2, 192, 8_000, false, feed);
        state.feedback_in_flight.store(true, Ordering::Release);

        handle_feedback_resubmit_failure(&state, libusb1_sys::constants::LIBUSB_ERROR_BUSY);

        assert!(!state.feedback_in_flight.load(Ordering::Acquire));
        assert!(!state.error.load(Ordering::Acquire));
        assert!(!state.stop.load(Ordering::Acquire));
    }
}
