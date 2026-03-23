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
use std::sync::atomic::{AtomicBool, AtomicI32, AtomicU32, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};

use libusb1_sys::{
    libusb_alloc_transfer, libusb_cancel_transfer, libusb_context, libusb_device_handle,
    libusb_fill_iso_transfer, libusb_free_transfer, libusb_handle_events_timeout,
    libusb_set_iso_packet_lengths, libusb_submit_transfer, libusb_transfer,
};

/// Elevate the calling thread to `SCHED_FIFO` at `priority` (Linux only).
/// Logs to stderr; silently ignored on non-Linux or if permission is denied
/// (CAP_SYS_NICE / RLIMIT_RTPRIO required).
fn set_thread_realtime(priority: i32) {
    #[cfg(target_os = "linux")]
    unsafe {
        let param = libc::sched_param {
            sched_priority: priority,
        };
        let rc = libc::pthread_setschedparam(
            libc::pthread_self(),
            libc::SCHED_FIFO,
            &param,
        );
        if rc == 0 {
            eprintln!("usb-audio: iso-events thread SCHED_FIFO priority={}", priority);
        } else {
            eprintln!(
                "usb-audio: iso-events thread SCHED_FIFO priority={} failed errno={}",
                priority, rc
            );
        }
    }
}

/// Read `CLOCK_MONOTONIC` as nanoseconds.
fn clock_monotonic_ns() -> u64 {
    let mut ts = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut ts) };
    ts.tv_sec as u64 * 1_000_000_000 + ts.tv_nsec as u64
}

use crate::alsa_clock::AlsaHwClockFeed;

use super::feedback::{RateAdapter, DRIFT_BUMP_PPB};
use super::queue::FrameQueue;

// ---------------------------------------------------------------------------
// Ring parameters
// ---------------------------------------------------------------------------

/// Number of concurrent in-flight transfers.
pub const N_TRANSFERS: usize = 16;
/// Target audio duration covered by one transfer, in milliseconds.
/// Each transfer holds `N_PACKETS_TARGET_MS * packets_per_sec / 1000` ISO packets.
/// 1ms/FS device (1000 pkt/s) → 8 packets; 125µs/HS device (8000 pkt/s) → 64 packets.
pub const N_PACKETS_TARGET_MS: usize = 8;

// ---------------------------------------------------------------------------
// Shared state (Arc, accessed from both event thread and main thread)
// ---------------------------------------------------------------------------

/// Duration of the linear fade-in ramp after an xrun, in samples.
/// ~2 ms at 48 kHz.  Short enough to be inaudible but long enough to
/// suppress the hard silence→audio transition click.
const XRUN_FADEIN_SAMPLES: u32 = 96;

fn usb_audio_ignore_feedback_enabled() -> bool {
    std::env::var("HIRESTI_USB_IGNORE_FEEDBACK")
        .ok()
        .map(|v| {
            let text = v.trim().to_ascii_lowercase();
            !text.is_empty() && text != "0" && text != "false" && text != "off"
        })
        .unwrap_or(false)
}

pub struct RingState {
    pub queue: Arc<FrameQueue>,
    pub stop: AtomicBool,
    /// Guards `RateAdapter` — only the event thread calls `samples_this_packet`
    /// in the hot path; main thread resets on format change.
    pub rate_adapter: Mutex<RateAdapter>,
    /// Latest feedback value in millisamples (updated from feedback callback).
    pub feedback_ms: Mutex<Option<i64>>,
    /// Whether the device exposes an explicit feedback endpoint.
    pub has_feedback_ep: bool,
    /// Remaining fade-in samples after an xrun recovery.
    /// Decremented in `fill_transfer`; when >0, each sample is scaled by
    /// `(XRUN_FADEIN_SAMPLES - remaining) / XRUN_FADEIN_SAMPLES`.
    /// Only accessed from the ISO event thread — no contention.
    pub fadein_remaining: AtomicU32,
    /// Sample rate in Hz.
    pub rate: u32,
    /// Bytes per audio sample (e.g. 4 for S32LE, 3 for S24_3LE).
    pub bytes_per_sample: usize,
    /// Number of audio channels.
    pub channels: usize,
    /// `wMaxPacketSize` from the ISO OUT endpoint descriptor.
    pub max_packet: usize,
    /// ISO packets delivered per second (1000 for 1ms/FS, 8000 for 125µs/HS).
    pub packets_per_sec: u32,
    /// Transfers that have been submitted but not yet completed.
    pub in_flight: AtomicI32,
    /// Frame-counting clock feed (shared with GStreamer pipeline).
    pub clock_feed: Arc<AlsaHwClockFeed>,
    /// Set to `true` when a fatal transfer error (NO_DEVICE, submit failure
    /// after all transfers exit) is detected.  Polled by the pusher thread to
    /// signal the engine about a disconnect.
    pub error: AtomicBool,
    /// Running count of ISO packets filled with silence because the
    /// [`FrameQueue`] was empty.  Each unit = 1 ms of silence (one ISO
    /// packet).  Polled by the pusher thread for periodic xrun reporting.
    pub xruns: AtomicU64,
    /// Running total of PCM bytes consumed by the ISO OUT ring.
    /// Polled by the pusher thread to measure drain throughput.
    pub bytes_drained_total: AtomicU64,
    /// Count of individual ISO OUT packets that completed with a non-COMPLETED
    /// status (STALL, ERROR, OVERFLOW, etc.).  Each such packet means the device
    /// received no audio for that ~0.125 ms slot — audible as a brief pop.
    /// Distinct from `xruns` (which counts queue underruns, not USB errors).
    pub usb_pkt_errors: AtomicU64,
    /// Calibrated millisamples per ISO packet derived from `AlsaHwClockFeed`.
    ///
    /// Updated by `iso_out_callback` once the rate calibrator has converged.
    /// Used by `fill_transfer` as a fallback when the UAC2 feedback endpoint
    /// produces no data.  Corrects for the device crystal offset on
    /// SOF-synchronized devices (e.g. FiiO KA13) where `feedback_ms` stays
    /// `None` but the device rate differs from nominal by a few ppm, causing
    /// the device FIFO to slowly drain and produce a glitch after ~2 minutes.
    ///
    /// Units: `rate_hz * 1_000_000 / packets_per_sec` (same as `feedback_ms`).
    /// Zero means not calibrated yet; use nominal rate.
    pub calibrated_ms: AtomicU64,
    /// `true` while the ISO IN feedback transfer is in flight.
    /// Set to `true` in `FeedbackReader::start()`; cleared in
    /// `feedback_in_callback` when the transfer stops (stop requested or
    /// non-recoverable status).  The event thread waits for this to become
    /// `false` before exiting so `FeedbackReader::drop()` can safely free
    /// the transfer struct.
    pub feedback_in_flight: AtomicBool,
    /// Monotonic timestamp (ns) of the first USB packet error in the current
    /// hysteresis window.  Zero means no window is open.
    /// Used to require ≥ 2 error events within 1 second before bumping drift
    /// correction — filters out sporadic EMI / USB hub glitches.
    drift_window_start_ns: AtomicU64,
    /// Count of error events within the current hysteresis window.
    drift_window_count: AtomicU32,

    // ── ISO completion jitter tracking ──────────────────────────────────
    /// Monotonic timestamp (ns) of the last ISO OUT transfer completion.
    /// Zero means no completion recorded yet.
    pub last_completion_ns: AtomicU64,
    /// Count of transfer completions where the inter-completion interval
    /// deviated by more than 50% from the expected ~8 ms.
    /// Polled by the pusher thread for the per-second diagnostic log.
    pub iso_jitter_events: AtomicU64,
    /// Maximum observed inter-completion interval (µs) since last diagnostic
    /// snapshot.  Reset to zero by the pusher thread after each log line.
    pub iso_interval_max_us: AtomicU64,
    /// Minimum observed inter-completion interval (µs) since last diagnostic
    /// snapshot.  Reset to u64::MAX by the pusher thread after each log line.
    pub iso_interval_min_us: AtomicU64,
    /// Maximum callback latency (µs) — time spent inside `iso_out_callback`
    /// from entry to post-resubmit.  Reset by the pusher thread after each
    /// diagnostic snapshot.  A high value indicates the event thread was
    /// delayed (lock contention, preemption) and may have caused a gap in
    /// the ISO schedule.
    pub callback_max_us: AtomicU64,
}

impl RingState {
    pub fn new(
        queue: Arc<FrameQueue>,
        rate: u32,
        bytes_per_sample: usize,
        channels: usize,
        max_packet: usize,
        packets_per_sec: u32,
        has_feedback_ep: bool,
        clock_feed: Arc<AlsaHwClockFeed>,
    ) -> Arc<Self> {
        eprintln!(
            "usb-audio: RingState rate={} ch={} bps={} max_packet={} packets_per_sec={} feedback_ep={}",
            rate, channels, bytes_per_sample, max_packet, packets_per_sec, has_feedback_ep
        );

        Arc::new(Self {
            queue,
            stop: AtomicBool::new(false),
            rate_adapter: Mutex::new(RateAdapter::new(rate, packets_per_sec)),
            feedback_ms: Mutex::new(None),
            has_feedback_ep,
            fadein_remaining: AtomicU32::new(0),
            rate,
            bytes_per_sample,
            channels,
            max_packet,
            packets_per_sec,
            in_flight: AtomicI32::new(0),
            clock_feed,
            error: AtomicBool::new(false),
            xruns: AtomicU64::new(0),
            bytes_drained_total: AtomicU64::new(0),
            usb_pkt_errors: AtomicU64::new(0),
            calibrated_ms: AtomicU64::new(0),
            feedback_in_flight: AtomicBool::new(false),
            drift_window_start_ns: AtomicU64::new(0),
            drift_window_count: AtomicU32::new(0),
            last_completion_ns: AtomicU64::new(0),
            iso_jitter_events: AtomicU64::new(0),
            iso_interval_max_us: AtomicU64::new(0),
            iso_interval_min_us: AtomicU64::new(u64::MAX),
            callback_max_us: AtomicU64::new(0),
        })
    }
}

// ---------------------------------------------------------------------------
// ISO OUT callback (called by libusb event thread)
// ---------------------------------------------------------------------------

/// Apply a linear fade-in gain to one interleaved audio frame (all channels).
///
/// `pos` is how far into the ramp we are (0 = silence, `total` = full scale).
/// Handles S16LE, S24_3LE, S24LE/S32LE (little-endian signed integers).
#[inline]
fn apply_fadein_frame(frame: &mut [u8], bytes_per_sample: usize, pos: u32, total: u32) {
    if total == 0 {
        return;
    }
    let n_channels = frame.len() / bytes_per_sample;
    for ch in 0..n_channels {
        let off = ch * bytes_per_sample;
        let sample_bytes = &mut frame[off..off + bytes_per_sample];
        match bytes_per_sample {
            2 => {
                // S16LE
                let val = i16::from_le_bytes([sample_bytes[0], sample_bytes[1]]);
                let scaled = (val as i32 * pos as i32 / total as i32) as i16;
                sample_bytes.copy_from_slice(&scaled.to_le_bytes());
            }
            3 => {
                // S24_3LE — 24-bit signed, sign-extend from bit 23
                let raw = (sample_bytes[0] as i32)
                    | ((sample_bytes[1] as i32) << 8)
                    | ((sample_bytes[2] as i32) << 16);
                let val = if raw & 0x80_0000 != 0 {
                    raw | !0xFF_FFFF // sign-extend
                } else {
                    raw
                };
                let scaled = val * pos as i32 / total as i32;
                sample_bytes[0] = scaled as u8;
                sample_bytes[1] = (scaled >> 8) as u8;
                sample_bytes[2] = (scaled >> 16) as u8;
            }
            4 => {
                // S32LE or F32LE — treat as S32LE (F32LE would need f32 path,
                // but GStreamer typically delivers integer formats to USB sinks).
                let val = i32::from_le_bytes([
                    sample_bytes[0],
                    sample_bytes[1],
                    sample_bytes[2],
                    sample_bytes[3],
                ]);
                // Use i64 to avoid overflow: i32::MAX * 96 fits in i64.
                let scaled = (val as i64 * pos as i64 / total as i64) as i32;
                sample_bytes.copy_from_slice(&scaled.to_le_bytes());
            }
            _ => {} // Unknown format — skip fade, pass through unchanged.
        }
    }
}

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

    let mut feedback = *state.feedback_ms.lock().unwrap_or_else(|e| e.into_inner());
    let ignore_feedback = usb_audio_ignore_feedback_enabled();
    if ignore_feedback {
        feedback = None;
    }
    let mut adapter = state.rate_adapter.lock().unwrap_or_else(|e| e.into_inner());
    if feedback.is_none() && (ignore_feedback || !state.has_feedback_ep) {
        let calibrated_fp32 = state.clock_feed
            .calibrated_rate_hz()
            .map(|rate_hz| rate_hz * 1_000_000.0 / state.packets_per_sec as f64);
        if let Some(calibrated_ms) = calibrated_fp32 {
            let clamped = calibrated_ms
                .round()
                .clamp(i64::MIN as f64, i64::MAX as f64) as i64;
            state.calibrated_ms.store(clamped.max(0) as u64, Ordering::Relaxed);
            if clamped > 0 {
                feedback = Some(clamped);
            }
        }
    }

    let frame_bytes = state.channels * state.bytes_per_sample;

    // ISO packets must be laid out tightly (no gaps) in the transfer buffer.
    // libusb/usbfs computes each packet's start offset as the cumulative sum
    // of the *actual* lengths of all preceding packets — NOT as i * max_packet.
    // Writing at stride=max_packet but using smaller lengths would cause the
    // USB host controller to read from the wrong buffer positions for packets
    // 1..N, producing garbage audio (continuous crackling).
    let mut offset = 0usize;
    let mut total_frames: u64 = 0;
    let mut total_bytes: u64 = 0;
    let mut xrun_packets: u64 = 0;
    let mut fadein_rem = state.fadein_remaining.load(Ordering::Relaxed);
    let mut fadein_armed = false;
    for i in 0..n_packets {
        let samples = adapter.samples_this_packet(feedback) as usize;
        let packet_bytes = (samples * frame_bytes)
            .min(state.max_packet)
            .min(buf_len.saturating_sub(offset));

        // Set actual packet length in the ISO descriptor.
        let pkt = (*transfer).iso_packet_desc.as_mut_ptr().add(i);
        (*pkt).length = packet_bytes as c_uint;

        // Fill from queue; silence-pad anything missing.
        let pkt_buf = std::slice::from_raw_parts_mut(buf_base.add(offset), packet_bytes);
        let got = state.queue.pop(pkt_buf);
        if got < packet_bytes {
            pkt_buf[got..].fill(0);
            xrun_packets += 1;
            // Arm fade-in for the recovery after this xrun.
            fadein_armed = true;
        }

        // Apply fade-in ramp if recovering from an xrun.
        if fadein_rem > 0 && got > 0 && frame_bytes > 0 {
            let ramp_total = XRUN_FADEIN_SAMPLES;
            let n_frames = got / frame_bytes;
            for f in 0..n_frames {
                // Scale: 0 at start of ramp → 1 at end.
                let pos = ramp_total - fadein_rem;
                let frame_start = f * frame_bytes;
                apply_fadein_frame(
                    &mut pkt_buf[frame_start..frame_start + frame_bytes],
                    state.bytes_per_sample,
                    pos,
                    ramp_total,
                );
                fadein_rem = fadein_rem.saturating_sub(1);
                if fadein_rem == 0 {
                    break;
                }
            }
        }

        total_bytes += packet_bytes as u64;

        let actual_samples = if frame_bytes > 0 {
            packet_bytes / frame_bytes
        } else {
            samples
        };
        total_frames += actual_samples as u64;

        // Advance by actual packet bytes so each packet's data immediately
        // follows the previous one (tight packing required by usbfs).
        offset += packet_bytes;
    }
    drop(adapter);

    // If any packet in this transfer had an xrun, arm the fade-in for
    // the *next* transfer (current one already has silence in its tail).
    if fadein_armed {
        fadein_rem = XRUN_FADEIN_SAMPLES;
    }
    state.fadein_remaining.store(fadein_rem, Ordering::Relaxed);

    if xrun_packets > 0 {
        // Xrun logging is intentionally suppressed.  During pause/idle the ISO
        // ring continues draining the (empty) queue until the pusher thread
        // closes the sink, producing thousands of harmless xrun packets.
        // The pusher thread already reports aggregate xrun counts via
        // EVT_STATE "usb-xruns=N", so per-transfer logging is redundant.
        // Uncomment the block below only when debugging queue underruns
        // during active playback.
        //
        // let total_xruns_before = state.xruns.load(Ordering::Relaxed);
        // let bytes_drained = state.bytes_drained_total.load(Ordering::Relaxed);
        // let bytes_per_ms = state.rate as u64 * frame_bytes as u64 / 1000;
        // let ms_drained = if bytes_per_ms > 0 { bytes_drained / bytes_per_ms } else { 0 };
        // let queue_ms    = if bytes_per_ms > 0 { queue_avail_before as u64 / bytes_per_ms } else { 0 };
        // eprintln!(
        //     "usb-audio: xrun transfer={}/{} pkt  queue={} B (~{} ms)  missing={} B  \
        //      feedback={:?} ms  xruns_total={}  playback_ms={}",
        //     xrun_packets, n_packets, queue_avail_before, queue_ms,
        //     xrun_bytes_missing, feedback.map(|v| v / 1000),
        //     total_xruns_before, ms_drained,
        // );
    }

    if total_bytes > 0 {
        state
            .bytes_drained_total
            .fetch_add(total_bytes, Ordering::Relaxed);
    }
    if xrun_packets > 0 {
        state.xruns.fetch_add(xrun_packets, Ordering::Relaxed);
    }
    // Advance the clock once per transfer (batched) instead of once per packet.
    // 8–64 atomic add calls → 1, cutting hot-path overhead ~8–64×.
    if total_frames > 0 {
        state.clock_feed.advance(total_frames);
    }

}

/// libusb ISO OUT transfer completion callback.
extern "system" fn iso_out_callback(transfer: *mut libusb_transfer) {
    let cb_entry_ns = clock_monotonic_ns();

    // SAFETY: user_data == Arc::as_ptr(&state); valid while IsoTransferRing alive.
    let state = unsafe { &*((*transfer).user_data as *const RingState) };

    state.in_flight.fetch_sub(1, Ordering::AcqRel);

    if state.stop.load(Ordering::Acquire) {
        // Stop requested — do not resubmit.  Event thread will exit once
        // in_flight reaches zero.
        return;
    }

    // Detect fatal transfer conditions.
    let status = unsafe { (*transfer).status };
    if status == libusb1_sys::constants::LIBUSB_TRANSFER_NO_DEVICE {
        // Device disconnected.  Set the error flag so the pusher thread can
        // report it to the Engine, then stop the ring.
        state.error.store(true, Ordering::Release);
        state.stop.store(true, Ordering::Release);
        return;
    }

    // Check each individual ISO packet's completion status from the *just-completed*
    // transfer.  For OUT transfers, a per-packet error means that 0.125 ms slot
    // was not delivered to the device — audible as a brief pop without any xrun.
    // Also check for short packets (actual_length < length) which indicate the
    // xHCI did not transmit all bytes — the device would receive truncated audio.
    let n_pkt = unsafe { (*transfer).num_iso_packets } as usize;
    let mut bad_pkts: u64 = 0;
    let mut short_pkts: u64 = 0;
    for i in 0..n_pkt {
        let pkt = unsafe { &*(*transfer).iso_packet_desc.as_ptr().add(i) };
        if pkt.status != libusb1_sys::constants::LIBUSB_TRANSFER_COMPLETED {
            bad_pkts += 1;
        }
        if pkt.actual_length < pkt.length && pkt.length > 0 {
            short_pkts += 1;
        }
    }
    if short_pkts > 0 {
        eprintln!(
            "usb-audio: ISO OUT short packets: {}/{} in this transfer (queue={} B)",
            short_pkts, n_pkt, state.queue.available_read(),
        );
    }
    if bad_pkts > 0 {
        let total_errors_before = state.usb_pkt_errors.fetch_add(bad_pkts, Ordering::Relaxed);

        // If the host-side FrameQueue has plenty of data, bad ISO packets
        // indicate the *device* FIFO underflowed — its crystal is faster
        // than the USB SOF-derived delivery rate.  Bump the adaptive drift
        // correction so we deliver slightly more samples per second.
        //
        // Hysteresis: require ≥ 2 error events within a 1-second window
        // before bumping, to filter sporadic EMI / USB hub glitches.
        let queue_bytes = state.queue.available_read();
        let frame_bytes = state.channels * state.bytes_per_sample;
        // "Healthy" threshold: ≥ 20 ms of audio in the queue.
        let healthy_bytes = state.rate as usize * frame_bytes * 20 / 1000;
        let feedback = *state.feedback_ms.lock().unwrap_or_else(|e| e.into_inner());
        if queue_bytes >= healthy_bytes && feedback.is_none() {
            let now_ns = clock_monotonic_ns();
            let window_start = state.drift_window_start_ns.load(Ordering::Relaxed);
            const WINDOW_NS: u64 = 1_000_000_000; // 1 second
            const MIN_ERRORS: u32 = 2;

            if window_start == 0 || now_ns.saturating_sub(window_start) > WINDOW_NS {
                // Start a new window.
                state.drift_window_start_ns.store(now_ns, Ordering::Relaxed);
                state.drift_window_count.store(1, Ordering::Relaxed);
            } else {
                let count = state.drift_window_count.fetch_add(1, Ordering::Relaxed) + 1;
                if count >= MIN_ERRORS {
                    // Confirmed: repeated errors within window → device FIFO underflow.
                    let mut adapter = state.rate_adapter.lock().unwrap_or_else(|e| e.into_inner());
                    let old_ppb = adapter.drift_correction_ppb();
                    adapter.bump_drift(DRIFT_BUMP_PPB);
                    eprintln!(
                        "usb-audio: device FIFO underflow inferred ({} errors in window) — \
                         drift correction {} → {} ppb  (queue={} B, bad_pkts={}/{})",
                        count,
                        old_ppb,
                        adapter.drift_correction_ppb(),
                        queue_bytes,
                        bad_pkts,
                        n_pkt,
                    );
                    // Reset window after bump.
                    state.drift_window_start_ns.store(0, Ordering::Relaxed);
                    state.drift_window_count.store(0, Ordering::Relaxed);
                }
            }
        } else {
            eprintln!(
                "usb-audio: ISO OUT packet errors: {}/{} bad in this transfer (total={})  \
                 queue={} B  feedback={:?}",
                bad_pkts,
                n_pkt,
                total_errors_before + bad_pkts,
                queue_bytes,
                feedback.map(|v| v / 1000),
            );
        }
    }

    // ── ISO completion jitter measurement ──────────────────────────────
    // Each transfer covers ~8 ms of audio.  Measure inter-completion interval
    // and flag outliers (> 50% deviation from expected).  This detects xHCI
    // scheduling hiccups that could cause device-side FIFO gaps.
    {
        let now_ns = clock_monotonic_ns();
        let prev_ns = state.last_completion_ns.swap(now_ns, Ordering::Relaxed);
        if prev_ns != 0 {
            let delta_ns = now_ns.saturating_sub(prev_ns);
            let delta_us = delta_ns / 1_000;
            // Expected interval: n_packets * 1_000_000 / packets_per_sec µs
            // For 64 packets @ 8000 pkt/s = 8000 µs (8 ms)
            let expected_us = n_pkt as u64 * 1_000_000 / state.packets_per_sec as u64;
            let threshold_lo = expected_us / 2; // 4 ms
            let threshold_hi = expected_us * 3 / 2; // 12 ms

            // Update min/max atomically (best-effort, no CAS loop needed for diagnostics).
            let cur_max = state.iso_interval_max_us.load(Ordering::Relaxed);
            if delta_us > cur_max {
                state.iso_interval_max_us.store(delta_us, Ordering::Relaxed);
            }
            let cur_min = state.iso_interval_min_us.load(Ordering::Relaxed);
            if delta_us < cur_min {
                state.iso_interval_min_us.store(delta_us, Ordering::Relaxed);
            }

            if delta_us < threshold_lo || delta_us > threshold_hi {
                let jitter_count = state.iso_jitter_events.fetch_add(1, Ordering::Relaxed) + 1;
                // Log first 8 jitter events, then every 64th to avoid flooding.
                if jitter_count <= 8 || (jitter_count % 64 == 0) {
                    let queue_bytes = state.queue.available_read();
                    eprintln!(
                        "usb-audio: ISO jitter #{}: interval={}µs expected={}µs (delta={:+}µs) queue={} B",
                        jitter_count,
                        delta_us,
                        expected_us,
                        delta_us as i64 - expected_us as i64,
                        queue_bytes,
                    );
                }
            }
        }
    }

    // Refill the transfer buffer with fresh audio from the queue and resubmit.
    unsafe { fill_transfer(state, transfer) };

    // Record ISO completion timestamp for rate calibration.
    // Called after fill_transfer so total_frames reflects the just-written batch.
    state.clock_feed.record_iso(clock_monotonic_ns());

    let rc = unsafe { libusb_submit_transfer(transfer) };
    if rc == 0 {
        state.in_flight.fetch_add(1, Ordering::AcqRel);
    } else if rc == libusb1_sys::constants::LIBUSB_ERROR_NO_DEVICE {
        // Submit failed because device is gone — same as NO_DEVICE above.
        state.error.store(true, Ordering::Release);
        state.stop.store(true, Ordering::Release);
    }
    // Other submit failures: in_flight stays decremented; the ring self-heals
    // if other transfers are still running, or stop() will clean up.

    // ── Callback latency measurement ─────────────────────────────────────
    let cb_elapsed_us = clock_monotonic_ns().saturating_sub(cb_entry_ns) / 1_000;
    let prev_max = state.callback_max_us.load(Ordering::Relaxed);
    if cb_elapsed_us > prev_max {
        state.callback_max_us.store(cb_elapsed_us, Ordering::Relaxed);
    }
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
    /// Optional ISO IN feedback transfer.  Stored here so `stop()` can cancel
    /// it alongside the OUT transfers, ensuring the event thread processes its
    /// completion callback (and clears `state.feedback_in_flight`) before
    /// exiting.  This prevents `FeedbackReader::drop()` from freeing the
    /// transfer while libusb still holds an internal reference.
    pub feedback_xfer: Option<*mut libusb_transfer>,
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
        // Scale ISO packets per transfer so each transfer covers ~8ms of audio,
        // regardless of whether the device uses 1ms frames or 125µs microframes.
        let n_packets = (N_PACKETS_TARGET_MS * state.packets_per_sec as usize / 1000).max(8);
        let buf_size = n_packets * state.max_packet;
        let state_ptr = Arc::as_ptr(&state) as *mut std::ffi::c_void;

        eprintln!(
            "usb-audio: IsoTransferRing n_transfers={} n_packets={} buf_size={} bytes ({} ms/transfer)",
            N_TRANSFERS, n_packets, buf_size,
            n_packets * 1000 / state.packets_per_sec as usize,
        );

        let mut transfers = Vec::with_capacity(N_TRANSFERS);
        let mut bufs = Vec::with_capacity(N_TRANSFERS);

        for _ in 0..N_TRANSFERS {
            let mut buf: Vec<u8> = vec![0u8; buf_size];

            let xfer = unsafe { libusb_alloc_transfer(n_packets as c_int) };
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
                    n_packets as c_int,
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
            feedback_xfer: None,
        })
    }

    /// Submit all transfers and spawn the libusb event loop thread.
    pub fn start(&mut self) -> Result<(), String> {
        self.state.stop.store(false, Ordering::SeqCst);
        self.state.in_flight.store(0, Ordering::SeqCst);

        let frame_bytes = self.state.channels * self.state.bytes_per_sample;
        let bytes_per_ms = self.state.rate as usize * frame_bytes / 1000;
        let queue_at_start = self.state.queue.available_read();
        // Approximate bytes the ring will drain from the queue at startup:
        // each packet holds ceil(rate/pps) frames × frame_bytes bytes.
        let samples_per_pkt = (self.state.rate as usize / self.state.packets_per_sec as usize) + 1;
        let n_packets = (N_PACKETS_TARGET_MS * self.state.packets_per_sec as usize / 1000).max(8);
        let ring_needs = self.transfers.len() * n_packets * samples_per_pkt * frame_bytes;
        eprintln!(
            "usb-audio: ring start  queue={} B (~{} ms)  ring_needs~{} B (~{} ms)  n_transfers={}",
            queue_at_start,
            if bytes_per_ms > 0 { queue_at_start / bytes_per_ms } else { 0 },
            ring_needs,
            if bytes_per_ms > 0 { ring_needs / bytes_per_ms } else { 0 },
            self.transfers.len(),
        );

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
                // Elevate to SCHED_FIFO so USB ISO callbacks are never preempted
                // by normal-priority threads (Python UI, GStreamer decode, etc.).
                set_thread_realtime(70);
                let ctx = ctx_addr as *mut libusb_context;
                // Use a timeout that matches the transfer duration (~8 ms).
                // Polling at 1 ms would cause ~1000 syscalls/sec but transfers
                // only complete every 8 ms; 8 ms here reduces idle syscalls by ~8×.
                // With 128 ms of in-flight buffer this latency is safe.
                let tv = libc::timeval {
                    tv_sec: 0,
                    tv_usec: 8_000,
                }; // 8 ms
                while !state.stop.load(Ordering::Acquire)
                    || state.in_flight.load(Ordering::Acquire) > 0
                    || state.feedback_in_flight.load(Ordering::Acquire)
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
    /// 2. Cancels the ISO IN feedback transfer (if any) so the event thread
    ///    processes its completion callback and clears `feedback_in_flight`
    /// 3. Cancels all ISO OUT transfers
    /// 4. Waits for the event thread to drain and exit (it checks both
    ///    `in_flight` and `feedback_in_flight` before returning)
    pub fn stop(&mut self) {
        self.state.stop.store(true, Ordering::SeqCst);

        // Cancel the feedback transfer first so the event thread can drain it.
        if let Some(fb) = self.feedback_xfer {
            unsafe { libusb_cancel_transfer(fb) };
        }

        for &xfer in &self.transfers {
            unsafe { libusb_cancel_transfer(xfer) };
        }

        if let Some(t) = self.event_thread.take() {
            let _ = t.join();
        }
    }
}

impl IsoTransferRing {
    /// Free all libusb transfer objects and their backing buffers.  Must be
    /// called AFTER `stop()` (which cancels in-flight transfers and joins
    /// the event thread).  After this call, `drop()` becomes a no-op for
    /// transfers — safe to create a new ring on the same libusb context
    /// without mutex contention.
    pub fn free_transfers(&mut self) {
        for &xfer in &self.transfers {
            unsafe { libusb_free_transfer(xfer) };
        }
        self.transfers.clear();
        self._bufs.clear();
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
