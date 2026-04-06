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
use std::sync::{Arc, Mutex};

use gstreamer as gst;
use libusb1_sys::{
    libusb_alloc_transfer, libusb_cancel_transfer, libusb_device_handle, libusb_fill_iso_transfer,
    libusb_free_transfer, libusb_set_iso_packet_lengths, libusb_submit_transfer, libusb_transfer,
};

use rusb::UsbContext as _;

use crate::alsa_clock::{AlsaHwClock, AlsaHwClockFeed};

use super::borrowed_queue::BorrowedBufferQueue;
use super::descriptor::UacVersion;
use super::device::{enumerate_usb_audio_devices, OpenUsbDevice, UacAltProfile, UsbAudioDevice};
use super::feedback::{parse_feedback_uac1, parse_feedback_uac2};
use super::queue::FrameQueue;
use super::source::TransferSource;
use super::transfer::{IsoTransferRing, RingState};

// ---------------------------------------------------------------------------
// UsbAudioSink
// ---------------------------------------------------------------------------

pub enum PushBufferError {
    Full(gst::Buffer),
    MapFailed(gst::Buffer),
}

enum ProducerQueue {
    Bytes(Arc<FrameQueue>),
    Borrowed(Arc<BorrowedBufferQueue>),
}

impl ProducerQueue {
    fn bytes() -> Self {
        Self::Bytes(FrameQueue::new())
    }

    fn borrowed() -> Self {
        Self::Borrowed(BorrowedBufferQueue::new(FrameQueue::capacity_bytes()))
    }

    fn transfer_source(&self) -> Arc<dyn TransferSource> {
        match self {
            Self::Bytes(queue) => queue.clone(),
            Self::Borrowed(queue) => queue.clone(),
        }
    }

    fn kind_name(&self) -> &'static str {
        match self {
            Self::Bytes(queue) => queue.kind_name(),
            Self::Borrowed(queue) => queue.kind_name(),
        }
    }

    fn available_read(&self) -> usize {
        match self {
            Self::Bytes(queue) => queue.available_read(),
            Self::Borrowed(queue) => queue.available_read(),
        }
    }

    fn available_write(&self) -> usize {
        match self {
            Self::Bytes(queue) => queue.available_write(),
            Self::Borrowed(queue) => queue.available_write(),
        }
    }

    fn set_frame_bytes(&self, frame_bytes: usize) {
        if let Self::Bytes(queue) = self {
            queue.set_frame_bytes(frame_bytes);
        }
    }

    fn push_bytes(&self, data: &[u8]) -> usize {
        match self {
            Self::Bytes(queue) => queue.push(data),
            Self::Borrowed(_) => 0,
        }
    }

    fn push_buffer(&self, buffer: gst::Buffer) -> Result<(), PushBufferError> {
        match self {
            Self::Bytes(_) => Err(PushBufferError::MapFailed(buffer)),
            Self::Borrowed(queue) => queue.push_buffer(buffer).map_err(PushBufferError::Full),
        }
    }

    fn supports_borrowed_buffers(&self) -> bool {
        matches!(self, Self::Borrowed(_))
    }
}

/// An active USB audio output session.
///
/// Holds all live resources for one playback session.  Drop (or `stop()`) to
/// tear down the transfer ring and release the USB interface.
pub struct UsbAudioSink {
    /// Producer-side queue implementation used by the pusher thread.
    queue: ProducerQueue,
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
    /// `true` once the ISO ring and feedback endpoint have been armed.
    started: bool,
    /// Open USB device handle + claimed interface. Dropped last.
    _open_dev: Arc<Mutex<OpenUsbDevice>>,
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

    pub fn queued_bytes(&self) -> usize {
        self.queue.available_read()
    }

    pub fn queue_available_write(&self) -> usize {
        self.queue.available_write()
    }

    pub fn source_kind(&self) -> &'static str {
        self.queue.kind_name()
    }

    pub fn supports_borrowed_buffers(&self) -> bool {
        self.queue.supports_borrowed_buffers()
    }

    pub fn push_bytes(&self, data: &[u8]) -> usize {
        self.queue.push_bytes(data)
    }

    pub fn push_buffer(&self, buffer: gst::Buffer) -> Result<(), PushBufferError> {
        self.queue.push_buffer(buffer)
    }

    /// Mark the device to skip interface release on drop.  When set, the USB
    /// interface stays claimed after the sink is dropped, preventing the
    /// kernel driver (snd-usb-audio) from re-attaching and locking the device
    /// to 48 kHz.  Use this before dropping the sink on track switches.
    pub fn set_skip_release_on_drop(&mut self, skip: bool) {
        if let Ok(mut open_dev) = self._open_dev.lock() {
            open_dev.skip_release_on_drop = skip;
        }
    }

    /// Shared access to the opened USB device for non-RT control-plane work.
    pub fn control_device(&self) -> Arc<Mutex<OpenUsbDevice>> {
        Arc::clone(&self._open_dev)
    }

    /// Start the ISO ring and feedback endpoint if they are not already running.
    pub fn ensure_started(&mut self) -> Result<(), String> {
        if self.started {
            return Ok(());
        }
        // Anchor only when the ring is about to start.  This keeps the shared
        // clock on CLOCK_MONOTONIC while the pusher thread is still pre-filling
        // the queue directly, avoiding a frozen custom clock during deferred
        // startup.
        let anchor_ns = clock_monotonic_ns();
        self.feed.anchor(anchor_ns, self.actual_rate);
        self.ring.start()?;

        let (dev_handle_raw, feedback_ep, uac_version, is_high_speed) = {
            let open_dev = self._open_dev.lock().unwrap_or_else(|e| e.into_inner());
            (
                open_dev.handle.as_raw(),
                open_dev.active_alt.as_ref().and_then(|alt| alt.feedback_ep),
                open_dev.dev.uac_version,
                open_dev.dev.is_high_speed,
            )
        };
        let feedback = feedback_ep
            .map(|ep| {
                FeedbackReader::new(
                    dev_handle_raw,
                    ep,
                    Arc::clone(&self.state),
                    uac_version,
                    is_high_speed,
                )
                .and_then(|mut fr| {
                    fr.start()?;
                    Ok(fr)
                })
            })
            .transpose()?;

        if let Some(ref fb) = feedback {
            self.ring.feedback_xfer = Some(fb.transfer);
        }
        self._feedback = feedback;
        self.started = true;
        Ok(())
    }

    /// `true` once the deferred ISO ring start has completed.
    pub fn is_started(&self) -> bool {
        self.started
    }

    /// Query the hardware volume range from the device's Feature Unit.
    ///
    /// Returns `(min_raw, max_raw, res_raw)` in 1/256 dB, or `None`.
    pub fn get_hw_volume_range(&self) -> Option<(i16, i16, i16)> {
        self._open_dev.lock().ok()?.get_hw_volume_range()
    }

    /// Read the current hardware volume (1/256 dB).
    pub fn get_hw_volume(&self) -> Option<i16> {
        self._open_dev.lock().ok()?.get_hw_volume()
    }

    /// Set the hardware volume (1/256 dB).
    pub fn set_hw_volume(&self, value_raw: i16) -> Result<(), String> {
        self._open_dev
            .lock()
            .map_err(|_| "hardware volume device lock poisoned".to_string())?
            .set_hw_volume(value_raw)
    }

    /// `true` if the device has a Feature Unit with volume control.
    pub fn has_hw_volume(&self) -> bool {
        self._open_dev
            .lock()
            .ok()
            .map(|open_dev| {
                open_dev
                    .dev
                    .feature_unit
                    .as_ref()
                    .map_or(false, |fu| fu.has_volume)
            })
            .unwrap_or(false)
    }

    pub fn hw_volume_channels(&self) -> Vec<u8> {
        self._open_dev
            .lock()
            .ok()
            .map(|open_dev| open_dev.hw_volume_channels())
            .unwrap_or_default()
    }

    pub fn get_hw_volume_ch(&self, channel_index: usize) -> Option<i16> {
        self._open_dev.lock().ok()?.get_hw_volume_ch(channel_index)
    }

    pub fn set_hw_volume_ch(&self, channel_index: usize, value_raw: i16) -> Result<(), String> {
        self._open_dev
            .lock()
            .map_err(|_| "hardware volume device lock poisoned".to_string())?
            .set_hw_volume_ch(channel_index, value_raw)
    }

    pub fn device_name(&self) -> String {
        self._open_dev
            .lock()
            .ok()
            .map(|open_dev| open_dev.device_name())
            .unwrap_or_default()
    }
}

impl UsbAudioSink {
    fn build_ring_state(
        queue: &ProducerQueue,
        feed: &Arc<AlsaHwClockFeed>,
        actual_rate: u32,
        alt: &super::descriptor::UacStreamAlt,
        is_high_speed: bool,
    ) -> Arc<RingState> {
        let bytes_per_sample = if alt.subframe_size > 0 {
            alt.subframe_size as usize
        } else {
            (alt.bit_depth as usize + 7) / 8
        };
        queue.set_frame_bytes(alt.channels as usize * bytes_per_sample);
        let packets_per_sec = iso_packets_per_sec(is_high_speed, alt.out_ep_interval);
        RingState::new(
            queue.transfer_source(),
            actual_rate,
            bytes_per_sample,
            alt.channels as usize,
            alt.max_packet as usize,
            packets_per_sec,
            alt.feedback_ep.is_some(),
            alt.format == super::descriptor::UacFormat::Float32,
            Arc::clone(feed),
        )
    }

    fn open_and_configure(
        device_id: &str,
        rate: u32,
        bit_depth: u8,
        preferred_profile: Option<UacAltProfile>,
    ) -> Result<(UsbAudioDevice, OpenUsbDevice, super::descriptor::UacStreamAlt), String> {
        let dev = find_device_by_id(device_id)
            .ok_or_else(|| format!("USB audio device '{}' not found", device_id))?;
        let mut open_dev = OpenUsbDevice::open(&dev)?;
        let alt = open_dev
            .best_alt_for_profile(rate, bit_depth, preferred_profile)
            .ok_or_else(|| {
                format!(
                    "no alt-setting for rate={} bit_depth={} on '{}'",
                    rate, bit_depth, device_id
                )
            })?
            .clone();
        open_dev.configure(&alt, rate)?;
        Ok((dev, open_dev, alt))
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
        let (dev, open_dev, alt) = Self::open_and_configure(device_id, rate, bit_depth, None)?;
        let queue = ProducerQueue::bytes();
        let feed = Arc::new(AlsaHwClockFeed::default());
        let clock = AlsaHwClock::new(Arc::clone(&feed));
        let actual_rate = open_dev.active_rate;
        eprintln!(
            "usb-audio: sink::open device={} requested_rate={} actual_rate={} bit_depth={} channels={}",
            device_id, rate, actual_rate, bit_depth, alt.channels
        );

        let dev_handle_raw = open_dev.handle.as_raw();
        let ctx_raw = open_dev.handle.context().as_raw();
        let state = Self::build_ring_state(&queue, &feed, actual_rate, &alt, dev.is_high_speed);

        let anchor_ns = clock_monotonic_ns();
        feed.anchor(anchor_ns, actual_rate);

        let mut ring =
            IsoTransferRing::new(dev_handle_raw, ctx_raw, alt.out_ep, Arc::clone(&state))?;
        ring.start()?;

        // 8. Start UAC 2.0 feedback reader (optional).
        let feedback = alt
            .feedback_ep
            .map(|ep| {
                FeedbackReader::new(
                    dev_handle_raw,
                    ep,
                    Arc::clone(&state),
                    dev.uac_version,
                    dev.is_high_speed,
                )
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
                started: true,
                _open_dev: Arc::new(Mutex::new(open_dev)),
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
    /// `prefill` (when provided) is pushed into the queue before the ISO ring
    /// is started so the first submitted transfers can carry real audio rather
    /// than startup silence.  The caller must still call [`ensure_started`] to
    /// anchor the clock and arm the ISO ring once enough audio has accumulated.
    pub fn open_with_feed(
        device_id: &str,
        rate: u32,
        bit_depth: u8,
        feed: Arc<AlsaHwClockFeed>,
        prefill: Option<&[u8]>,
        preferred_profile: Option<UacAltProfile>,
        borrow_direct_buffers: bool,
    ) -> Result<Self, String> {
        let queue = if borrow_direct_buffers {
            ProducerQueue::borrowed()
        } else {
            ProducerQueue::bytes()
        };

        if let Some(data) = prefill.filter(|data| !data.is_empty()) {
            let written = queue.push_bytes(data);
            if written < data.len() {
                eprintln!(
                    "usb-audio: startup prefill truncated {} -> {} bytes",
                    data.len(),
                    written
                );
            }
        }

        let (dev, open_dev, alt) =
            Self::open_and_configure(device_id, rate, bit_depth, preferred_profile)?;
        let actual_rate = open_dev.active_rate;
        eprintln!(
            "usb-audio: sink::open_with_feed device={} requested_rate={} actual_rate={} bit_depth={} channels={} feedback_ep={:?}",
            device_id, rate, actual_rate, bit_depth, alt.channels, alt.feedback_ep
        );
        eprintln!(
            "usb-audio: producer queue kind={} borrowed={}",
            queue.kind_name(),
            queue.supports_borrowed_buffers(),
        );

        let dev_handle_raw = open_dev.handle.as_raw();
        let ctx_raw = open_dev.handle.context().as_raw();
        let state = Self::build_ring_state(&queue, &feed, actual_rate, &alt, dev.is_high_speed);
        // Keep the feed invalid until ensure_started() arms the ring.  This lets
        // GStreamer's clock fall back to CLOCK_MONOTONIC during queue prefill.
        feed.invalidate();

        let ring = IsoTransferRing::new(dev_handle_raw, ctx_raw, alt.out_ep, Arc::clone(&state))?;

        Ok(UsbAudioSink {
            queue,
            feed,
            state,
            actual_rate,
            ring,
            _feedback: None,
            started: false,
            _open_dev: Arc::new(Mutex::new(open_dev)),
        })
    }

    /// Reconfigure the sink for a new sample rate **without releasing the USB
    /// device**.  This keeps the kernel driver detached so the system cannot
    /// reclaim the device (and lock it to 48 kHz) during track switches.
    ///
    /// Steps: stop ISO ring → clear queue → reconfigure alt-setting + rate →
    /// push prefill → create new ring + feedback → start.
    pub fn reconfigure(
        &mut self,
        rate: u32,
        bit_depth: u8,
        prefill: Option<&[u8]>,
    ) -> Result<(), String> {
        // 1. Stop ring FIRST — this cancels all ISO OUT transfers AND the
        //    feedback IN transfer, then joins the event thread.  Only after
        //    the event thread has fully exited is it safe to free transfers.
        self.ring.stop();
        // 2. Drop feedback reader (frees its libusb_transfer).  Safe now
        //    because the event thread is no longer running.
        self._feedback = None;
        // 3. Free ring's libusb transfer objects while the context is
        //    quiescent.  This prevents the later `self.ring = ring` drop
        //    from freeing them while the NEW event thread is running.
        self.ring.free_transfers();

        // 2. Clear the old queue and create a fresh one.
        let queue = ProducerQueue::bytes();

        if let Some(data) = prefill.filter(|d| !d.is_empty()) {
            let written = queue.push_bytes(data);
            if written < data.len() {
                eprintln!(
                    "usb-audio: reconfigure prefill truncated {} -> {} bytes",
                    data.len(),
                    written
                );
            }
        }

        // 3. Reconfigure device (alt-setting + rate) — reuses claimed interface.
        let (alt, actual_rate, dev_handle_raw, ctx_raw, uac_version, is_high_speed) = {
            let mut open_dev = self._open_dev.lock().unwrap_or_else(|e| e.into_inner());
            let alt = open_dev
                .best_alt(rate, bit_depth)
                .ok_or_else(|| {
                    format!(
                        "no alt-setting for rate={} bit_depth={} on reconfigure",
                        rate, bit_depth
                    )
                })?
                .clone();
            open_dev.configure(&alt, rate)?;
            (
                alt,
                open_dev.active_rate,
                open_dev.handle.as_raw(),
                open_dev.handle.context().as_raw(),
                open_dev.dev.uac_version,
                open_dev.dev.is_high_speed,
            )
        };
        eprintln!(
            "usb-audio: reconfigure requested_rate={} actual_rate={} bit_depth={} channels={}",
            rate, actual_rate, bit_depth, alt.channels
        );
        let state = Self::build_ring_state(&queue, &self.feed, actual_rate, &alt, is_high_speed);

        // 6. Anchor clock and start new ring.
        let anchor_ns = clock_monotonic_ns();
        self.feed.anchor(anchor_ns, actual_rate);

        let mut ring =
            IsoTransferRing::new(dev_handle_raw, ctx_raw, alt.out_ep, Arc::clone(&state))?;
        ring.start()?;

        // 7. Feedback reader.
        let feedback = alt
            .feedback_ep
            .map(|ep| {
                FeedbackReader::new(
                    dev_handle_raw,
                    ep,
                    Arc::clone(&state),
                    uac_version,
                    is_high_speed,
                )
                .and_then(|mut fr| {
                    fr.start()?;
                    Ok(fr)
                })
            })
            .transpose()?;

        if let Some(ref fb) = feedback {
            ring.feedback_xfer = Some(fb.transfer);
        }

        // 8. Swap in new state.
        self.queue = queue;
        self.state = state;
        self.actual_rate = actual_rate;
        self.ring = ring;
        self._feedback = feedback;
        self.started = true;

        Ok(())
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
    is_high_speed: bool,
    ep: u8,
    /// EMA accumulator for feedback smoothing.
    /// `None` until the first feedback packet arrives.
    ema: Option<i64>,
    /// EMA divisor chosen so the smoothing window stays reasonable across
    /// full-speed and high-speed feedback rates.
    ema_divisor: i64,
    callbacks: u64,
    parse_failures: u64,
    rejected_outliers: u64,
    /// Consecutive rejected feedback packets.  When this exceeds
    /// `CONSECUTIVE_REJECT_THRESHOLD` the stale EMA value is cleared from
    /// `feedback_ms` so `fill_transfer` falls back to the calibrated
    /// clock rate — preventing device-side FIFO overflow from a stale
    /// (slightly too-high) feedback value.
    consecutive_rejects: u64,
    /// Discard feedback until this monotonic timestamp to give the DAC PLL a
    /// fixed wall-clock settle window after a rate / alt-setting switch.
    settle_until_ns: u64,
    /// Number of feedback packets discarded during the settle window.
    settle_discards: u32,
}

/// PLL settle window after opening / reconfiguring the device.
const PLL_SETTLE_NS: u64 = 20_000_000;

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
/// Parses the feedback value, applies an EMA to smooth quantisation
/// noise from the device's fixed-point feedback format, and updates
/// `RingState::feedback_ms`.  Then resubmits unless `state.stop` is set.
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
            ctx.ep, status, ctx.callbacks,
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
        std::slice::from_raw_parts((*transfer).buffer as *const u8, pkt_configured_len.min(16))
    };
    // For ISO IN transfers libusb reports the real payload length per packet in
    // iso_packet_desc[i].actual_length.  The top-level transfer.actual_length
    // may remain zero even when packet payload is present.
    let payload_len = if pkt_actual_len > 0 {
        pkt_actual_len.min(pkt_configured_len)
    } else {
        transfer_len.min(pkt_configured_len)
    };
    let buf = unsafe { std::slice::from_raw_parts((*transfer).buffer as *const u8, payload_len) };
    let ms = match ctx.uac_version {
        UacVersion::V2 => parse_feedback_uac2(buf, ctx.state.packets_per_sec),
        UacVersion::V1 => parse_feedback_uac1(buf, ctx.is_high_speed),
    };
    if let Some(raw) = ms {
        let raw_rate_hz = feedback_rate_hz(raw, ctx.state.packets_per_sec);
        let nominal_rate_hz = ctx.state.rate as f64;
        let nominal_ms = ctx.state.rate as i64 * 1_000_000 / ctx.state.packets_per_sec as i64;

        // Hard reject completely implausible values first.
        let lo_hard = nominal_ms * 9 / 10;
        let hi_hard = nominal_ms * 11 / 10;
        let rejected = raw < lo_hard || raw > hi_hard;
        if rejected {
            let raw_ppm = if nominal_rate_hz > 0.0 {
                (raw_rate_hz - nominal_rate_hz) / nominal_rate_hz * 1_000_000.0
            } else {
                0.0
            };
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
            if clock_monotonic_ns() < ctx.settle_until_ns {
                ctx.settle_discards = ctx.settle_discards.saturating_add(1);
                if ctx.settle_discards <= 4 {
                    eprintln!(
                        "usb-audio: PLL settling, discarding feedback {:.2}Hz (discard #{})",
                        raw_rate_hz, ctx.settle_discards
                    );
                }
            } else {
                let first_valid = ctx.ema.is_none();
                let smoothed = match ctx.ema {
                    None => raw,
                    Some(prev) => prev + (raw - prev) / ctx.ema_divisor,
                };
                ctx.ema = Some(smoothed);
                if first_valid || ctx.callbacks <= 1 {
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
        is_high_speed: bool,
    ) -> Result<Self, String> {
        // UAC 2.0 feedback: 4 bytes (Q16.16); UAC 1.0 HS also uses 4 bytes.
        let buf_len: usize = match uac_version {
            UacVersion::V2 => 4,
            UacVersion::V1 if is_high_speed => 4,
            UacVersion::V1 => 3,
        };
        let mut buf = vec![0u8; buf_len];
        let ema_divisor = if is_high_speed { 128 } else { 16 };
        let settle_until_ns = clock_monotonic_ns().saturating_add(PLL_SETTLE_NS);

        let ctx_box = Box::new(FeedbackCtx {
            state,
            uac_version,
            is_high_speed,
            ep,
            ema: None,
            ema_divisor,
            callbacks: 0,
            parse_failures: 0,
            rejected_outliers: 0,
            consecutive_rejects: 0,
            settle_until_ns,
            settle_discards: 0,
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
            self._ctx.ep, self._ctx.uac_version,
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
        let state = RingState::new(queue, 48_000, 4, 2, 192, 8_000, false, false, feed);
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
        let state = RingState::new(queue, 48_000, 4, 2, 192, 8_000, false, false, feed);
        state.feedback_in_flight.store(true, Ordering::Release);

        handle_feedback_resubmit_failure(&state, libusb1_sys::constants::LIBUSB_ERROR_BUSY);

        assert!(!state.feedback_in_flight.load(Ordering::Acquire));
        assert!(!state.error.load(Ordering::Acquire));
        assert!(!state.stop.load(Ordering::Acquire));
    }
}
