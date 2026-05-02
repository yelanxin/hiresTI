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
    libusb_free_transfer, libusb_handle_events_timeout, libusb_set_iso_packet_lengths,
    libusb_submit_transfer, libusb_transfer,
};

use rusb::UsbContext as _;

use crate::alsa_clock::{AlsaHwClock, AlsaHwClockFeed};

use super::borrowed_queue::BorrowedBufferQueue;
use super::descriptor::UacVersion;
use super::device::{enumerate_usb_audio_devices, OpenUsbDevice, UacAltProfile, UsbAudioDevice};
use super::feedback::{parse_feedback_uac1, parse_feedback_uac2};
use super::owned_buffer_queue::OwnedBufferQueue;
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

pub enum QueueMode {
    Bytes,
    Borrowed,
    Owned,
}

enum ProducerQueue {
    Bytes(Arc<FrameQueue>),
    Borrowed(Arc<BorrowedBufferQueue>),
    Owned(Arc<OwnedBufferQueue>),
}

impl ProducerQueue {
    fn bytes() -> Self {
        Self::Bytes(FrameQueue::new())
    }

    fn borrowed() -> Self {
        Self::Borrowed(BorrowedBufferQueue::new(FrameQueue::capacity_bytes()))
    }

    fn owned() -> Self {
        Self::Owned(OwnedBufferQueue::new(FrameQueue::capacity_bytes()))
    }

    fn transfer_source(&self) -> Arc<dyn TransferSource> {
        match self {
            Self::Bytes(queue) => queue.clone(),
            Self::Borrowed(queue) => queue.clone(),
            Self::Owned(queue) => queue.clone(),
        }
    }

    fn kind_name(&self) -> &'static str {
        match self {
            Self::Bytes(queue) => queue.kind_name(),
            Self::Borrowed(queue) => queue.kind_name(),
            Self::Owned(queue) => queue.kind_name(),
        }
    }

    fn available_read(&self) -> usize {
        match self {
            Self::Bytes(queue) => queue.available_read(),
            Self::Borrowed(queue) => queue.available_read(),
            Self::Owned(queue) => queue.available_read(),
        }
    }

    fn available_write(&self) -> usize {
        match self {
            Self::Bytes(queue) => queue.available_write(),
            Self::Borrowed(queue) => queue.available_write(),
            Self::Owned(queue) => queue.available_write(),
        }
    }

    fn set_frame_bytes(&self, frame_bytes: usize) {
        match self {
            Self::Bytes(queue) => queue.set_frame_bytes(frame_bytes),
            Self::Borrowed(_) | Self::Owned(_) => {}
        }
    }

    fn push_bytes(&self, data: &[u8]) -> usize {
        match self {
            Self::Bytes(queue) => queue.push(data),
            Self::Borrowed(_) | Self::Owned(_) => 0,
        }
    }

    fn push_buffer(&self, buffer: gst::Buffer) -> Result<(), PushBufferError> {
        match self {
            Self::Bytes(_) => Err(PushBufferError::MapFailed(buffer)),
            Self::Borrowed(queue) => queue.push_buffer(buffer).map_err(PushBufferError::Full),
            Self::Owned(_) => Err(PushBufferError::MapFailed(buffer)),
        }
    }

    fn push_owned_bytes(&self, data: Vec<u8>) -> Result<(), Vec<u8>> {
        match self {
            Self::Owned(queue) => queue.push_bytes(data),
            Self::Bytes(_) | Self::Borrowed(_) => Err(data),
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

    /// One-line periodic telemetry snapshot for the V2 native_transport path.
    ///
    /// V1 (GstAppsink pusher) emits `usb-audio: push=…` per second from its
    /// pusher loop in `lib.rs`.  V2 has no equivalent loop because the decode
    /// worker runs in `native_transport::controller`, so the controller calls
    /// this function once per second to surface the same kind of telemetry —
    /// queue depth, in-flight count, feedback rate, ISO jitter min/max, xrun
    /// delta.  Atomically resets the windowed min/max counters after reading
    /// so each line covers exactly the elapsed window.
    ///
    /// `push_bytes_window` is the bytes the producer accepted into the queue
    /// during `secs`; the formatter shows it as a rate.
    pub fn telemetry_line(&self, push_bytes_window: u64, secs: f64) -> String {
        let q_bytes = self.queue.available_read();
        let frame_bytes = self.state.channels * self.state.bytes_per_sample;
        let q_ms = if frame_bytes > 0 && self.state.rate > 0 {
            (q_bytes as u64 * 1000) / (frame_bytes as u64 * self.state.rate as u64)
        } else {
            0
        };
        let xruns = self.state.xruns.load(Ordering::Relaxed);
        let in_flight = self.state.in_flight.load(Ordering::Acquire);
        let feedback_ms = *self
            .state
            .feedback_ms
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        let feedback_hz = feedback_ms.map(|ms| {
            ms as f64 * self.state.packets_per_sec as f64 / 1_000_000.0
        });
        let nominal_hz = self.state.rate as f64;
        let feedback_ppm = feedback_hz.map(|hz| {
            if nominal_hz > 0.0 {
                (hz - nominal_hz) / nominal_hz * 1_000_000.0
            } else {
                0.0
            }
        });
        let iso_min_us = self
            .state
            .iso_interval_min_us
            .swap(u64::MAX, Ordering::Relaxed);
        let iso_max_us = self.state.iso_interval_max_us.swap(0, Ordering::Relaxed);
        let iso_min_display = if iso_min_us == u64::MAX { 0 } else { iso_min_us };
        let cb_max_us = self.state.callback_max_us.swap(0, Ordering::Relaxed);
        let jitter = self.state.iso_jitter_events.load(Ordering::Relaxed);
        let drained = self.state.bytes_drained_total.load(Ordering::Relaxed);
        let pkt_errs = self.state.usb_pkt_errors.load(Ordering::Relaxed);
        let parse_fails = self.state.feedback_parse_fails.load(Ordering::Relaxed);
        format!(
            "v2-snapshot push={:.0} B/s drained={} q={} B ({}ms) xruns={} in_flight={} \
             fb={} pkt_errs={} parse_fails={} iso=[{}..{}µs] jitter={} cb_max={}µs",
            push_bytes_window as f64 / secs.max(1e-6),
            drained,
            q_bytes,
            q_ms,
            xruns,
            in_flight,
            feedback_hz
                .zip(feedback_ppm)
                .map(|(hz, ppm)| format!("{:.3}Hz({:+.1}ppm)", hz, ppm))
                .unwrap_or_else(|| "n/a".to_string()),
            pkt_errs,
            parse_fails,
            iso_min_display,
            iso_max_us,
            jitter,
            cb_max_us,
        )
    }

    pub fn queue_available_write(&self) -> usize {
        self.queue.available_write()
    }

    /// One-line counter snapshot that only touches `Arc<RingState>` atomics —
    /// no Mutex locking, no `&UsbAudioSink` borrow.  Suitable for a polling
    /// thread that runs independently of the decode worker, so emitting it
    /// can never stall decoding.  Fields are a strict subset of
    /// `telemetry_line`: queue depth and feedback_hz are omitted because they
    /// require borrowing the sink (queue) or taking a Mutex (feedback_ms).
    pub fn snapshot_from_state(state: &RingState) -> String {
        let xruns = state.xruns.load(Ordering::Relaxed);
        let in_flight = state.in_flight.load(Ordering::Acquire);
        let iso_min_us = state.iso_interval_min_us.swap(u64::MAX, Ordering::Relaxed);
        let iso_max_us = state.iso_interval_max_us.swap(0, Ordering::Relaxed);
        let iso_min_display = if iso_min_us == u64::MAX { 0 } else { iso_min_us };
        let cb_max_us = state.callback_max_us.swap(0, Ordering::Relaxed);
        let jitter = state.iso_jitter_events.load(Ordering::Relaxed);
        let drained = state.bytes_drained_total.load(Ordering::Relaxed);
        let pkt_errs = state.usb_pkt_errors.load(Ordering::Relaxed);
        let parse_fails = state.feedback_parse_fails.load(Ordering::Relaxed);
        let short_pkts = state.usb_short_pkt_log_count.load(Ordering::Relaxed);
        let dq_under = state
            .direct_queue_underrun_fallbacks
            .load(Ordering::Relaxed);
        let dq_wrap = state.direct_queue_wrap_fallbacks.load(Ordering::Relaxed);
        let drift_ppb = state.drift_correction_ppb.load(Ordering::Relaxed);
        let calibrated_ms = state.calibrated_ms.load(Ordering::Relaxed);
        format!(
            "v2-poll drained={drained} xruns={xruns} in_flight={in_flight} \
             pkt_errs={pkt_errs} parse_fails={parse_fails} short_pkts={short_pkts} \
             dq_under={dq_under} dq_wrap={dq_wrap} \
             drift_ppb={drift_ppb} calibrated_ms={calibrated_ms} \
             iso=[{iso_min_display}..{iso_max_us}µs] jitter={jitter} cb_max={cb_max_us}µs"
        )
    }

    pub fn source_kind(&self) -> &'static str {
        self.queue.kind_name()
    }

    pub fn supports_borrowed_buffers(&self) -> bool {
        self.queue.supports_borrowed_buffers()
    }

    pub fn push_bytes(&self, data: &[u8]) -> usize {
        let written = self.queue.push_bytes(data);
        if written > 0 {
            self.record_push(written);
        }
        written
    }

    pub fn push_owned_bytes(&self, data: Vec<u8>) -> Result<(), Vec<u8>> {
        let len = data.len();
        let result = self.queue.push_owned_bytes(data);
        if result.is_ok() && len > 0 {
            self.record_push(len);
        }
        result
    }

    pub fn push_buffer(&self, buffer: gst::Buffer) -> Result<(), PushBufferError> {
        let len = buffer.size();
        let result = self.queue.push_buffer(buffer);
        if result.is_ok() && len > 0 {
            self.record_push(len);
        }
        result
    }

    /// Update producer-side telemetry on `RingState`.  Read by
    /// `queue_fallback_log` so each underrun line shows when the queue last
    /// accepted bytes.  Also emits a warning if the gap since the previous
    /// push exceeded `PUSH_GAP_WARN_MS` while the ring was already running —
    /// catches the case where the producer is alive but blocked between
    /// pushes (HTTP read stall, decoder thread preempted).
    #[inline]
    fn record_push(&self, bytes: usize) {
        const PUSH_GAP_WARN_MS: u64 = 200;
        let now_ns = clock_monotonic_ns();
        let prev_ns = self
            .state
            .last_push_at_ns
            .swap(now_ns, Ordering::Relaxed);
        if self.started && prev_ns > 0 && now_ns > prev_ns {
            let gap_ms = (now_ns - prev_ns) / 1_000_000;
            if gap_ms >= PUSH_GAP_WARN_MS {
                let queue_read = self.queue.available_read();
                eprintln!(
                    "usb-audio: producer push gap {}ms (size={} queued={} B)",
                    gap_ms, bytes, queue_read
                );
            }
        }
        self.state
            .last_push_size
            .store(bytes as u64, Ordering::Relaxed);
        self.state
            .total_pushed_bytes
            .fetch_add(bytes as u64, Ordering::Relaxed);
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
    ) -> Result<
        (
            UsbAudioDevice,
            OpenUsbDevice,
            super::descriptor::UacStreamAlt,
        ),
        String,
    > {
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

    /// Configure and build a sink from an already-opened (and possibly
    /// pre-claimed) [`OpenUsbDevice`] handle.  This avoids re-opening the
    /// device and ensures no gap where PipeWire could grab the interface.
    fn configure_existing_handle(
        mut open_dev: OpenUsbDevice,
        rate: u32,
        bit_depth: u8,
        preferred_profile: Option<UacAltProfile>,
    ) -> Result<(OpenUsbDevice, super::descriptor::UacStreamAlt), String> {
        let alt = open_dev
            .best_alt_for_profile(rate, bit_depth, preferred_profile)
            .ok_or_else(|| {
                format!(
                    "no alt-setting for rate={} bit_depth={} on pre-claimed handle",
                    rate, bit_depth,
                )
            })?
            .clone();
        open_dev.configure(&alt, rate)?;
        Ok((open_dev, alt))
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
        let mode = if borrow_direct_buffers {
            QueueMode::Borrowed
        } else {
            QueueMode::Bytes
        };
        Self::open_with_feed_mode(
            device_id,
            rate,
            bit_depth,
            feed,
            prefill,
            preferred_profile,
            mode,
        )
    }

    pub fn open_with_feed_mode(
        device_id: &str,
        rate: u32,
        bit_depth: u8,
        feed: Arc<AlsaHwClockFeed>,
        prefill: Option<&[u8]>,
        preferred_profile: Option<UacAltProfile>,
        mode: QueueMode,
    ) -> Result<Self, String> {
        let queue = match mode {
            QueueMode::Bytes => ProducerQueue::bytes(),
            QueueMode::Borrowed => ProducerQueue::borrowed(),
            QueueMode::Owned => ProducerQueue::owned(),
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

    /// Build a sink from an already-opened [`OpenUsbDevice`] handle.
    ///
    /// The handle may have been pre-claimed via [`OpenUsbDevice::claim_only`].
    /// This method calls [`OpenUsbDevice::configure`] on it (which is a no-op
    /// for `claim_interface` since the interface is already claimed) and then
    /// creates the ISO transfer ring.
    pub fn open_with_handle(
        open_dev: OpenUsbDevice,
        rate: u32,
        bit_depth: u8,
        feed: Arc<AlsaHwClockFeed>,
        preferred_profile: Option<UacAltProfile>,
        mode: QueueMode,
    ) -> Result<Self, String> {
        let queue = match mode {
            QueueMode::Bytes => ProducerQueue::bytes(),
            QueueMode::Borrowed => ProducerQueue::borrowed(),
            QueueMode::Owned => ProducerQueue::owned(),
        };

        let (open_dev, alt) =
            Self::configure_existing_handle(open_dev, rate, bit_depth, preferred_profile)?;
        let actual_rate = open_dev.active_rate;
        eprintln!(
            "usb-audio: sink::open_with_handle requested_rate={} actual_rate={} bit_depth={} channels={} feedback_ep={:?}",
            rate, actual_rate, bit_depth, alt.channels, alt.feedback_ep
        );

        let dev_handle_raw = open_dev.handle.as_raw();
        let ctx_raw = open_dev.handle.context().as_raw();
        let state =
            Self::build_ring_state(&queue, &feed, actual_rate, &alt, open_dev.dev.is_high_speed);
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
        // Clear the stale pointer so the old ring's Drop doesn't try to
        // cancel an already-freed transfer (use-after-free).
        self.ring.feedback_xfer = None;
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

    /// Prepare the sink for reuse by a new track **without starting playback**.
    ///
    /// Stops the ISO ring, clears the queue, reconfigures alt-setting + rate if
    /// needed, and creates a fresh transfer ring — but does **not** start it.
    /// The caller is expected to push audio data and then call `ensure_started()`
    /// (or let `push_slab_to_usb_output` handle it via the `auto_start` flag).
    ///
    /// This keeps the USB handle open continuously, preventing the kernel driver
    /// (snd-usb-audio) from reattaching and resetting the DAC PLL.
    pub fn prepare_for_reuse(&mut self, rate: u32, bit_depth: u8) -> Result<(), String> {
        // 1. Stop ring — cancels all ISO transfers, joins event thread.
        self.ring.stop();
        // 2. Drop feedback reader (frees its libusb_transfer).
        self._feedback = None;
        // Clear the stale pointer so the old ring's Drop doesn't try to
        // cancel an already-freed transfer (use-after-free).
        self.ring.feedback_xfer = None;
        // 3. Free ring's libusb transfer objects while context is quiescent.
        self.ring.free_transfers();

        // 4. Fresh queue.
        let queue = ProducerQueue::bytes();

        // 5. Reuse the current alt/rate when possible. Re-issuing SET_CUR or
        // toggling alt=0 on a same-rate track switch can make some DACs mute
        // one channel while their output stage recovers.
        let (alt, actual_rate, dev_handle_raw, ctx_raw, uac_version, is_high_speed, rate_changed) = {
            let mut open_dev = self._open_dev.lock().unwrap_or_else(|e| e.into_inner());
            let reusable_active = open_dev
                .active_alt
                .as_ref()
                .filter(|alt| open_dev.active_rate == rate && alt.bit_depth == bit_depth)
                .cloned();

            let alt = if let Some(alt) = reusable_active {
                eprintln!(
                    "usb-audio: prepare_for_reuse — keeping active alt={} rate={}",
                    alt.alt_setting, rate
                );
                alt
            } else {
                let previous_rate = open_dev.active_rate;
                let rate_change = previous_rate > 0 && previous_rate != rate;

                // For a real rate change, tear down the isochronous endpoint
                // before SET_CUR. This keeps rate switching reliable without
                // closing the libusb handle or letting the kernel reattach.
                if rate_change {
                    let si = open_dev.dev.stream_iface;
                    let _ = open_dev.handle.set_alternate_setting(si, 0);
                    open_dev.active_alt = None;
                    open_dev.active_rate = 0;
                    eprintln!(
                        "usb-audio: prepare_for_reuse — rate change {}→{}, alt reset to 0 (si={})",
                        previous_rate, rate, si
                    );
                }

                let alt = open_dev
                    .best_alt(rate, bit_depth)
                    .ok_or_else(|| {
                        format!(
                            "no alt-setting for rate={} bit_depth={} on prepare_for_reuse",
                            rate, bit_depth
                        )
                    })?
                    .clone();
                open_dev.configure(&alt, rate)?;
                alt
            };

            let actual_rate = open_dev.active_rate;
            let rate_changed =
                actual_rate == rate && self.actual_rate > 0 && self.actual_rate != actual_rate;
            (
                alt,
                actual_rate,
                open_dev.handle.as_raw(),
                open_dev.handle.context().as_raw(),
                open_dev.dev.uac_version,
                open_dev.dev.is_high_speed,
                rate_changed,
            )
        };
        eprintln!(
            "usb-audio: prepare_for_reuse requested_rate={} actual_rate={} bit_depth={} channels={}",
            rate, actual_rate, bit_depth, alt.channels
        );
        let state = Self::build_ring_state(&queue, &self.feed, actual_rate, &alt, is_high_speed);
        self.feed.invalidate();

        if rate_changed {
            wait_for_rate_change_settle(
                dev_handle_raw,
                ctx_raw,
                alt.feedback_ep,
                uac_version,
                is_high_speed,
                state.packets_per_sec,
                actual_rate,
            )?;
        }

        // 6. Create new ring but do NOT start it — deferred start via ensure_started().
        let ring = IsoTransferRing::new(dev_handle_raw, ctx_raw, alt.out_ep, Arc::clone(&state))?;

        // 7. Swap in new state.
        self.queue = queue;
        self.state = state;
        self.actual_rate = actual_rate;
        self.ring = ring;
        self._feedback = None;
        self.started = false;

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

struct RateChangeSettleCtx {
    uac_version: UacVersion,
    is_high_speed: bool,
    packets_per_sec: u32,
    ep: u8,
    target_rate: u32,
    target_ms: i64,
    tolerance_ms: i64,
    stable_needed: u32,
    stable_count: u32,
    callbacks: u64,
    parse_failures: u64,
    last_rate_hz: Option<f64>,
    done: bool,
    in_flight: bool,
    submit_error: Option<c_int>,
}

const RATE_CHANGE_SETTLE_MIN_MS_DEFAULT: u64 = 120;
const RATE_CHANGE_SETTLE_MAX_MS_DEFAULT: u64 = 300;
const RATE_CHANGE_SETTLE_LIMIT_MS: u64 = 1_500;
const RATE_CHANGE_SETTLE_TOLERANCE_PPM: i64 = 1_000;
const RATE_CHANGE_SETTLE_STABLE_COUNT: u32 = 2;

fn env_ms(name: &str, default_ms: u64) -> u64 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.trim().parse::<u64>().ok())
        .map(|ms| ms.min(RATE_CHANGE_SETTLE_LIMIT_MS))
        .unwrap_or(default_ms)
}

fn rate_change_settle_min_ms() -> u64 {
    env_ms(
        "HIRESTI_USB_RATE_CHANGE_SETTLE_MIN_MS",
        RATE_CHANGE_SETTLE_MIN_MS_DEFAULT,
    )
}

fn rate_change_settle_max_ms() -> u64 {
    env_ms(
        "HIRESTI_USB_RATE_CHANGE_SETTLE_MAX_MS",
        RATE_CHANGE_SETTLE_MAX_MS_DEFAULT,
    )
}

extern "system" fn rate_change_settle_feedback_callback(transfer: *mut libusb_transfer) {
    // SAFETY: user_data points to RateChangeSettleCtx owned by
    // wait_for_rate_change_settle(), which drains/cancels the transfer before
    // freeing the context.
    let ctx = unsafe { &mut *((*transfer).user_data as *mut RateChangeSettleCtx) };
    ctx.callbacks = ctx.callbacks.saturating_add(1);
    ctx.in_flight = false;

    let status = unsafe { (*transfer).status };
    if status != libusb1_sys::constants::LIBUSB_TRANSFER_COMPLETED {
        ctx.done = true;
        return;
    }

    let transfer_len = unsafe { (*transfer).actual_length } as usize;
    let pkt_desc = unsafe { &*(*transfer).iso_packet_desc.as_ptr() };
    let pkt_actual_len = pkt_desc.actual_length as usize;
    let pkt_configured_len = pkt_desc.length as usize;
    let raw_storage = unsafe {
        std::slice::from_raw_parts((*transfer).buffer as *const u8, pkt_configured_len.min(16))
    };
    let payload_len = if pkt_actual_len > 0 {
        pkt_actual_len.min(pkt_configured_len)
    } else {
        transfer_len.min(pkt_configured_len)
    };
    let buf = unsafe { std::slice::from_raw_parts((*transfer).buffer as *const u8, payload_len) };
    let ms = match ctx.uac_version {
        UacVersion::V2 => parse_feedback_uac2(buf, ctx.packets_per_sec),
        UacVersion::V1 => parse_feedback_uac1(buf, ctx.is_high_speed),
    };

    if let Some(raw) = ms {
        let rate_hz = feedback_rate_hz(raw, ctx.packets_per_sec);
        ctx.last_rate_hz = Some(rate_hz);
        if (raw - ctx.target_ms).abs() <= ctx.tolerance_ms {
            ctx.stable_count = ctx.stable_count.saturating_add(1);
        } else {
            ctx.stable_count = 0;
        }
        if ctx.callbacks <= 4 || ctx.stable_count >= ctx.stable_needed {
            eprintln!(
                "usb-audio: rate-change settle feedback cb#{} ep=0x{:02x} raw=[{}] rate={:.3}Hz target={}Hz stable={}/{}",
                ctx.callbacks,
                ctx.ep,
                format_feedback_bytes(raw_storage),
                rate_hz,
                ctx.target_rate,
                ctx.stable_count,
                ctx.stable_needed,
            );
        }
        if ctx.stable_count >= ctx.stable_needed {
            ctx.done = true;
            return;
        }
    } else {
        ctx.parse_failures = ctx.parse_failures.saturating_add(1);
        if ctx.parse_failures <= 2 {
            eprintln!(
                "usb-audio: rate-change settle feedback parse failed ep=0x{:02x} cb#{} raw=[{}]",
                ctx.ep,
                ctx.callbacks,
                format_feedback_bytes(raw_storage),
            );
        }
    }

    let rc = unsafe { libusb_submit_transfer(transfer) };
    if rc == 0 {
        ctx.in_flight = true;
    } else {
        ctx.submit_error = Some(rc);
        ctx.done = true;
    }
}

fn wait_for_rate_change_settle(
    dev_handle_raw: *mut libusb_device_handle,
    ctx_raw: *mut libusb1_sys::libusb_context,
    feedback_ep: Option<u8>,
    uac_version: UacVersion,
    is_high_speed: bool,
    packets_per_sec: u32,
    target_rate: u32,
) -> Result<(), String> {
    let max_ms = rate_change_settle_max_ms();
    if max_ms == 0 {
        eprintln!("usb-audio: rate-change settle disabled");
        return Ok(());
    }
    let min_ms = rate_change_settle_min_ms().min(max_ms);
    let Some(ep) = feedback_ep else {
        eprintln!(
            "usb-audio: rate-change settle no feedback ep — fixed {} ms",
            min_ms
        );
        if min_ms > 0 {
            std::thread::sleep(std::time::Duration::from_millis(min_ms));
        }
        return Ok(());
    };

    let buf_len: usize = match uac_version {
        UacVersion::V2 => 4,
        UacVersion::V1 if is_high_speed => 4,
        UacVersion::V1 => 3,
    };
    let mut buf = vec![0u8; buf_len];
    let target_ms = target_rate as i64 * 1_000_000 / packets_per_sec as i64;
    let tolerance_ms = (target_ms * RATE_CHANGE_SETTLE_TOLERANCE_PPM / 1_000_000).max(1);
    let ctx_ptr = Box::into_raw(Box::new(RateChangeSettleCtx {
        uac_version,
        is_high_speed,
        packets_per_sec,
        ep,
        target_rate,
        target_ms,
        tolerance_ms,
        stable_needed: RATE_CHANGE_SETTLE_STABLE_COUNT,
        stable_count: 0,
        callbacks: 0,
        parse_failures: 0,
        last_rate_hz: None,
        done: false,
        in_flight: false,
        submit_error: None,
    }));

    let xfer = unsafe { libusb_alloc_transfer(1) };
    if xfer.is_null() {
        unsafe {
            drop(Box::from_raw(ctx_ptr));
        }
        return Err("libusb_alloc_transfer failed for rate-change settle feedback".into());
    }

    unsafe {
        libusb_fill_iso_transfer(
            xfer,
            dev_handle_raw,
            ep as c_uchar,
            buf.as_mut_ptr() as *mut c_uchar,
            buf_len as c_int,
            1,
            rate_change_settle_feedback_callback,
            ctx_ptr as *mut c_void,
            0,
        );
        libusb_set_iso_packet_lengths(xfer, buf_len as c_uint);
    }

    eprintln!(
        "usb-audio: rate-change settle waiting for feedback target={}Hz min={}ms max={}ms",
        target_rate, min_ms, max_ms,
    );
    unsafe {
        (*ctx_ptr).in_flight = true;
    }
    let submit_rc = unsafe { libusb_submit_transfer(xfer) };
    if submit_rc != 0 {
        unsafe {
            libusb_free_transfer(xfer);
            drop(Box::from_raw(ctx_ptr));
        }
        return Err(format!(
            "submit rate-change settle feedback transfer: rc={}",
            submit_rc
        ));
    }

    let start_ns = clock_monotonic_ns();
    let deadline_ns = start_ns.saturating_add(max_ms.saturating_mul(1_000_000));
    let event_timeout = libc::timeval {
        tv_sec: 0,
        tv_usec: 5_000,
    };
    while clock_monotonic_ns() < deadline_ns {
        unsafe {
            if (*ctx_ptr).done {
                break;
            }
            libusb_handle_events_timeout(ctx_raw, &event_timeout);
        }
    }

    let elapsed_ms = clock_monotonic_ns().saturating_sub(start_ns) / 1_000_000;
    let settled = unsafe { (*ctx_ptr).stable_count >= (*ctx_ptr).stable_needed };
    if settled && elapsed_ms < min_ms {
        std::thread::sleep(std::time::Duration::from_millis(min_ms - elapsed_ms));
    }

    unsafe {
        if (*ctx_ptr).in_flight {
            libusb_cancel_transfer(xfer);
            let cancel_deadline_ns = clock_monotonic_ns().saturating_add(200_000_000);
            while (*ctx_ptr).in_flight && clock_monotonic_ns() < cancel_deadline_ns {
                libusb_handle_events_timeout(ctx_raw, &event_timeout);
            }
        }
    }

    let total_ms = clock_monotonic_ns().saturating_sub(start_ns) / 1_000_000;
    let still_in_flight = unsafe { (*ctx_ptr).in_flight };
    let ctx = unsafe { Box::from_raw(ctx_ptr) };
    if still_in_flight {
        eprintln!(
            "usb-audio: rate-change settle cancel did not drain after {} ms (callbacks={}); leaking settle transfer",
            total_ms, ctx.callbacks,
        );
        std::mem::forget(ctx);
        std::mem::forget(buf);
        return Ok(());
    }
    if settled {
        eprintln!(
            "usb-audio: rate-change settle ready in {} ms (held {} ms, callbacks={})",
            elapsed_ms, total_ms, ctx.callbacks,
        );
    } else {
        eprintln!(
            "usb-audio: rate-change settle timeout after {} ms (callbacks={} last_rate={:?} submit_error={:?})",
            total_ms, ctx.callbacks, ctx.last_rate_hz, ctx.submit_error,
        );
    }
    unsafe {
        libusb_free_transfer(xfer);
    }
    drop(ctx);
    drop(buf);
    Ok(())
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
        // Increment a shared counter the periodic v2-snapshot can read.
        // We deliberately do NOT eprintln here — feedback_in_callback runs on
        // the libusb event thread (SCHED_FIFO 70) which also handles ISO OUT
        // completion callbacks, and any blocking I/O on this thread (stderr
        // lock + pipe write + potential kernel transition, 0.5-5 ms) would
        // delay the next OUT completion past its 0.125 ms microframe budget,
        // causing the host to miss a slot — i.e. the very click we'd be
        // logging would be caused by the act of logging.  All diagnostic
        // visibility for parse failures comes from the v2-snapshot's
        // `parse_fails=N` counter, which is read on a non-RT thread.
        ctx.state
            .feedback_parse_fails
            .fetch_add(1, Ordering::Relaxed);
        let _ = (
            pkt_actual_len,
            pkt_configured_len,
            _pkt_status,
            transfer_len,
            raw_storage,
        );
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
