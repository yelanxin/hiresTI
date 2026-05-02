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

use std::collections::BTreeMap;
use std::os::raw::{c_int, c_uchar, c_uint};
use std::sync::atomic::{AtomicBool, AtomicI32, AtomicI64, AtomicU32, AtomicU64, Ordering};
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
        let rc = libc::pthread_setschedparam(libc::pthread_self(), libc::SCHED_FIFO, &param);
        if rc == 0 {
            eprintln!(
                "usb-audio: iso-events thread SCHED_FIFO priority={}",
                priority
            );
        } else {
            eprintln!(
                "usb-audio: iso-events thread SCHED_FIFO priority={} failed errno={}",
                priority, rc
            );
        }
    }
}

/// Read `CLOCK_MONOTONIC` as nanoseconds.
pub fn clock_monotonic_ns() -> u64 {
    let mut ts = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut ts) };
    ts.tv_sec as u64 * 1_000_000_000 + ts.tv_nsec as u64
}

use crate::alsa_clock::AlsaHwClockFeed;

use super::feedback::{RateAdapter, DRIFT_BUMP_PPB};
use super::source::TransferSource;

// ---------------------------------------------------------------------------
// Ring parameters
// ---------------------------------------------------------------------------

/// Number of concurrent in-flight transfers.
///
/// Ring depth = `N_TRANSFERS * N_PACKETS_TARGET_MS` ms (192 ms at the current
/// values).  Matches oxidac, which plays the same FLAC on the same FiiO DAC
/// click-free under V2.  Earlier hiresTI dropped to 16 to keep
/// `target_prefill` below the V1 GstAppsink natural startup buffer (~185 ms
/// with appsink max-buffers=8), but the V1 force-start fallback
/// (`min_prefill = target_prefill / 2 ≈ 96 ms`) covers that case, and the
/// extra in-flight depth gives the device's audio FIFO substantially more
/// headroom to absorb sporadic xHCI scheduling slips and device-side PLL
/// adjustments without the FIFO ever briefly running dry — the most plausible
/// remaining mechanism for the V2 96 kHz clicks.
pub const N_TRANSFERS: usize = 24;
/// Target audio duration covered by one transfer, in milliseconds.
/// Each transfer holds `N_PACKETS_TARGET_MS * packets_per_sec / 1000` ISO packets.
/// 1ms/FS device (1000 pkt/s) → 8 packets; 125µs/HS device (8000 pkt/s) → 64 packets.
pub const N_PACKETS_TARGET_MS: usize = 8;
/// Maximum packets a transfer can contain with the current ring parameters.
const MAX_PACKETS_PER_TRANSFER: usize = N_PACKETS_TARGET_MS * 8_000 / 1_000;

#[derive(Default)]
struct CompletionTracker {
    next_submit_seq: u64,
    next_release_seq: u64,
    completed: BTreeMap<u64, usize>,
}

impl CompletionTracker {
    fn assign_submit_seq(&mut self) -> u64 {
        let seq = self.next_submit_seq;
        self.next_submit_seq = self.next_submit_seq.saturating_add(1);
        seq
    }

    fn record_completion(&mut self, queue: &dyn TransferSource, seq: u64, bytes: usize) {
        if bytes == 0 {
            return;
        }
        self.completed.insert(seq, bytes);
        while let Some(released) = self.completed.remove(&self.next_release_seq) {
            queue.release_reserved(released);
            self.next_release_seq = self.next_release_seq.saturating_add(1);
        }
    }
}

struct TransferCtx {
    state: Arc<RingState>,
    slot: usize,
    scratch_ptr: *mut u8,
    queued_bytes: usize,
    submit_seq: u64,
}

// ---------------------------------------------------------------------------
// Shared state (Arc, accessed from both event thread and main thread)
// ---------------------------------------------------------------------------

/// Target duration of the click-suppression fade ramp, in milliseconds.
/// The actual sample count is computed from `state.rate` at use site so
/// the audible window stays constant across sample rates — a fixed
/// sample count (e.g. 96) shrinks to ~1 ms at 96 kHz / ~0.5 ms at 192 kHz,
/// which is too short to mask a hard step on FiiO USB DACs.  5 ms is the
/// value the lydex Android player uses for the same purpose; long enough
/// that the residual ramp endpoint is well below the noise floor (1/N for
/// N≥220 is ≤-46 dBFS) without eating audible amounts of program material.
const XRUN_FADE_MS: u32 = 5;

#[inline]
fn xrun_fade_samples(rate_hz: u32) -> u32 {
    // 5 ms @ rate = rate * 5 / 1000.  Cap at 1024 to keep the ramp from
    // dominating a single transfer at unusually high rates (≥204.8 kHz).
    let n = rate_hz.saturating_mul(XRUN_FADE_MS) / 1000;
    n.clamp(64, 1024)
}

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
    pub queue: Arc<dyn TransferSource>,
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
    /// `(xrun_fade_samples(rate) - remaining) / xrun_fade_samples(rate)`.
    /// Only accessed from the ISO event thread — no contention.
    pub fadein_remaining: AtomicU32,
    /// Sample rate in Hz.
    pub rate: u32,
    /// Bytes per audio sample (e.g. 4 for S32LE, 3 for S24_3LE).
    pub bytes_per_sample: usize,
    /// `true` when 4-byte samples are IEEE754 float instead of signed integer.
    pub sample_is_float: bool,
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
    /// Count of feedback IN packets where parse_feedback_uac2 returned None
    /// (zero-length payload or truncated buf).  Two distinct causes share
    /// this counter — `pkt_status==COMPLETED && pkt_actual==0` is a device
    /// ZLP (firmware/PLL stall, no rate ready); `pkt_status==ERROR` is a
    /// wire/host-stack issue.  feedback_in_callback increments this from
    /// the libusb event thread, telemetry_line reads it on the decode
    /// worker thread; no eprintln on the event thread.
    pub feedback_parse_fails: AtomicU64,
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
    /// Snapshot of `RateAdapter::drift_correction_ppb` mirrored from the
    /// libusb event thread.  Updated under the rate_adapter lock at the end
    /// of every `fill_transfer` so it captures both `bump_drift` (in the
    /// bad_pkts handler) and `decay_drift` (called from
    /// `samples_this_packet` every DRIFT_DECAY_INTERVAL_SECS).  Read by the
    /// non-RT v2-poll snapshot thread without locking — a stale value (1
    /// transfer = 8 ms behind) is fine for a 1-Hz human-readable diagnostic.
    /// Existence of this mirror is purely diagnostic; the authoritative
    /// drift value still lives inside RateAdapter.
    pub drift_correction_ppb: AtomicI64,

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
    /// Counter for ISO OUT short-packet events: device accepted fewer bytes
    /// than the host submitted in this transfer.  Increments once per affected
    /// transfer (not per packet).  An audible "lost samples" symptom even if
    /// `xruns` stays at 0, since the missing bytes are simply gone from the
    /// device's playback timeline.
    pub usb_short_pkt_log_count: AtomicU64,
    /// Maximum callback latency (µs) — time spent inside `iso_out_callback`
    /// from entry to post-resubmit.  Reset by the pusher thread after each
    /// diagnostic snapshot.  A high value indicates the event thread was
    /// delayed (lock contention, preemption) and may have caused a gap in
    /// the ISO schedule.
    pub callback_max_us: AtomicU64,
    /// Set to true once the queue has delivered at least one full packet.
    /// Before this, startup silence is expected and must not count as xrun.
    pub primed: AtomicBool,
    /// Submit path telemetry: queue-backed direct leases (no queue→transfer copy).
    pub direct_queue_submits: AtomicU64,
    /// Fallback count when the queue wrapped and a direct contiguous lease was
    /// not possible.
    pub direct_queue_wrap_fallbacks: AtomicU64,
    /// Fallback count when there was not enough queued audio to lease a full
    /// transfer directly and scratch-copy + silence padding was required.
    pub direct_queue_underrun_fallbacks: AtomicU64,
    /// Duration in milliseconds of the most recent appsink `try-pull-sample`
    /// call.  Updated by the pusher thread after every pull.  Read by the
    /// fallback-underrun logger so each underrun line shows whether upstream
    /// was slow or healthy when the queue ran dry.
    pub last_pull_ms: AtomicU64,
    /// Monotonic timestamp (ns) when the most recent appsink pull completed.
    /// Zero before the first pull.  Lets the fallback-underrun logger compute
    /// "last pull was Xms ago" — if X is large, the pusher is idle/blocked.
    pub last_pull_at_ns: AtomicU64,
    /// Monotonic timestamp (ns) of the most recent successful push into the
    /// FrameQueue.  Updated by `UsbAudioSink::push_bytes` whenever a non-zero
    /// number of bytes was accepted by the queue.  Zero before the first push.
    /// The fallback-underrun logger reports "last push was Xms ago" — large
    /// values pinpoint a stalled producer (decoder hung, HTTP read blocked,
    /// thread preempted) rather than a downstream issue.
    ///
    /// Distinct from `last_pull_*`: pull tracks the V1 GstAppsink pusher
    /// thread's `try-pull-sample` latency; push tracks how recently the
    /// queue actually accepted bytes — the only signal that works on the V2
    /// native_transport path (which has no pull loop).
    pub last_push_at_ns: AtomicU64,
    /// Bytes accepted by the queue on the most recent successful push call.
    /// Zero before the first push.
    pub last_push_size: AtomicU64,
    /// Running total of bytes the producer has pushed into the queue.
    /// Polled by the fallback-underrun logger to derive a recent push rate.
    pub total_pushed_bytes: AtomicU64,
    completion_tracker: Mutex<CompletionTracker>,
}

impl RingState {
    pub fn new(
        queue: Arc<dyn TransferSource>,
        rate: u32,
        bytes_per_sample: usize,
        channels: usize,
        max_packet: usize,
        packets_per_sec: u32,
        has_feedback_ep: bool,
        sample_is_float: bool,
        clock_feed: Arc<AlsaHwClockFeed>,
    ) -> Arc<Self> {
        eprintln!(
            "usb-audio: RingState rate={} ch={} bps={} max_packet={} packets_per_sec={} feedback_ep={} source={}",
            rate,
            channels,
            bytes_per_sample,
            max_packet,
            packets_per_sec,
            has_feedback_ep,
            queue.kind_name(),
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
            sample_is_float,
            channels,
            max_packet,
            packets_per_sec,
            in_flight: AtomicI32::new(0),
            clock_feed,
            error: AtomicBool::new(false),
            xruns: AtomicU64::new(0),
            bytes_drained_total: AtomicU64::new(0),
            usb_pkt_errors: AtomicU64::new(0),
            feedback_parse_fails: AtomicU64::new(0),
            calibrated_ms: AtomicU64::new(0),
            feedback_in_flight: AtomicBool::new(false),
            drift_window_start_ns: AtomicU64::new(0),
            drift_window_count: AtomicU32::new(0),
            drift_correction_ppb: AtomicI64::new(0),
            last_completion_ns: AtomicU64::new(0),
            iso_jitter_events: AtomicU64::new(0),
            iso_interval_max_us: AtomicU64::new(0),
            iso_interval_min_us: AtomicU64::new(u64::MAX),
            usb_short_pkt_log_count: AtomicU64::new(0),
            callback_max_us: AtomicU64::new(0),
            primed: AtomicBool::new(false),
            direct_queue_submits: AtomicU64::new(0),
            direct_queue_wrap_fallbacks: AtomicU64::new(0),
            direct_queue_underrun_fallbacks: AtomicU64::new(0),
            last_pull_ms: AtomicU64::new(0),
            last_pull_at_ns: AtomicU64::new(0),
            last_push_at_ns: AtomicU64::new(0),
            last_push_size: AtomicU64::new(0),
            total_pushed_bytes: AtomicU64::new(0),
            completion_tracker: Mutex::new(CompletionTracker::default()),
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
fn apply_fadein_frame(
    frame: &mut [u8],
    bytes_per_sample: usize,
    sample_is_float: bool,
    pos: u32,
    total: u32,
) {
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
                if sample_is_float {
                    let gain = pos as f32 / total as f32;
                    let val = f32::from_le_bytes([
                        sample_bytes[0],
                        sample_bytes[1],
                        sample_bytes[2],
                        sample_bytes[3],
                    ]);
                    sample_bytes.copy_from_slice(&(val * gain).to_le_bytes());
                } else {
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
            }
            _ => {} // Unknown format — skip fade, pass through unchanged.
        }
    }
}

/// Apply a linear fade-out to the last `fade_frames` frames inside
/// `audio[..audio_bytes]`, ramping from full scale at the start of the
/// fade region down to near-silence at `audio[audio_bytes]`.  The trailing
/// silence pad after `audio_bytes` is then a smooth continuation rather
/// than a step from the last good sample to zero.
#[inline]
fn apply_fadeout_tail(
    audio: &mut [u8],
    audio_bytes: usize,
    bytes_per_sample: usize,
    sample_is_float: bool,
    channels: usize,
    fade_frames: usize,
) {
    let frame_bytes = channels * bytes_per_sample;
    if frame_bytes == 0 || fade_frames == 0 || audio_bytes == 0 {
        return;
    }
    let total_frames = audio_bytes / frame_bytes;
    let n = fade_frames.min(total_frames);
    if n == 0 {
        return;
    }
    let start = (total_frames - n) * frame_bytes;
    for i in 0..n {
        let frame_off = start + i * frame_bytes;
        // pos counts down from `n` to 1 across the ramp; gain = pos / n
        // (1.0 at the start of the fade, ~1/n at the last frame).
        let pos = (n - i) as u32;
        apply_fadein_frame(
            &mut audio[frame_off..frame_off + frame_bytes],
            bytes_per_sample,
            sample_is_float,
            pos,
            n as u32,
        );
    }
}

unsafe fn transfer_ctx<'a>(transfer: *mut libusb_transfer) -> &'a mut TransferCtx {
    &mut *((*transfer).user_data as *mut TransferCtx)
}

unsafe fn mark_transfer_submitted(ctx: &mut TransferCtx) {
    if ctx.queued_bytes == 0 {
        ctx.submit_seq = 0;
        return;
    }
    let mut tracker = ctx
        .state
        .completion_tracker
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    ctx.submit_seq = tracker.assign_submit_seq();
}

fn release_completed_transfer_bytes(ctx: &mut TransferCtx) {
    if ctx.queued_bytes == 0 {
        return;
    }
    let mut tracker = ctx
        .state
        .completion_tracker
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    tracker.record_completion(ctx.state.queue.as_ref(), ctx.submit_seq, ctx.queued_bytes);
    ctx.queued_bytes = 0;
}

fn queue_direct_log(_count: u64, _slot: usize, _bytes: usize) {
    // Intentional no-op.  Counter `direct_queue_submits` is bumped at the
    // call site; that's the diagnostic record.  Earlier this function did a
    // throttled `eprintln!` from inside `iso_out_callback`, but every such
    // print runs on the libusb event thread (SCHED_FIFO 70) which also drives
    // ISO OUT completions: a stderr lock + pipe write can stall the thread
    // long enough to delay the next OUT completion past its 0.125 ms
    // microframe budget — a missed slot becomes an audible click.  Surface
    // the count via the v2-poll snapshot (read on a non-RT thread) instead.
}

fn queue_fallback_log(
    _state: &RingState,
    _label: &str,
    _count: u64,
    _slot: usize,
    _total_bytes: usize,
    _assign_avail: usize,
) {
    // Intentional no-op.  Counters `direct_queue_wrap_fallbacks` /
    // `direct_queue_underrun_fallbacks` are bumped at the call site and
    // surface via the v2-poll snapshot.  See the matching note in
    // `queue_direct_log` for why we don't `eprintln!` from the event thread.
}

/// Prepare the next transfer payload from [`FrameQueue`], setting each ISO
/// packet's `length` field to the computed sample count for this packet.
///
/// Fast path: when enough contiguous queued data is available, libusb points
/// directly at the queue backing store and no queue→transfer copy occurs.
/// Wrap-around and underrun cases fall back to the scratch transfer buffer.
///
/// # Safety
///
/// Caller must guarantee `transfer` is valid and its `user_data` points to a
/// live [`TransferCtx`].
unsafe fn fill_transfer(transfer: *mut libusb_transfer) {
    let ctx = transfer_ctx(transfer);
    let state = &ctx.state;
    let n_packets = (*transfer).num_iso_packets as usize;

    debug_assert!(n_packets <= MAX_PACKETS_PER_TRANSFER);

    let mut feedback = *state.feedback_ms.lock().unwrap_or_else(|e| e.into_inner());
    let ignore_feedback = usb_audio_ignore_feedback_enabled();
    if ignore_feedback {
        feedback = None;
    }
    let mut adapter = state.rate_adapter.lock().unwrap_or_else(|e| e.into_inner());
    if feedback.is_none() && (ignore_feedback || !state.has_feedback_ep) {
        let calibrated_fp32 = state
            .clock_feed
            .calibrated_rate_hz()
            .map(|rate_hz| rate_hz * 1_000_000.0 / state.packets_per_sec as f64);
        if let Some(calibrated_ms) = calibrated_fp32 {
            let clamped = calibrated_ms
                .round()
                .clamp(i64::MIN as f64, i64::MAX as f64) as i64;
            state
                .calibrated_ms
                .store(clamped.max(0) as u64, Ordering::Relaxed);
            if clamped > 0 {
                feedback = Some(clamped);
            }
        }
    }

    let frame_bytes = state.channels * state.bytes_per_sample;
    let mut packet_bytes = [0usize; MAX_PACKETS_PER_TRANSFER];
    let mut total_bytes = 0usize;
    let mut total_frames: u64 = 0;
    for i in 0..n_packets {
        let samples = adapter.samples_this_packet(feedback) as usize;
        let bytes = (samples * frame_bytes).min(state.max_packet);
        packet_bytes[i] = bytes;
        total_bytes += bytes;
        total_frames += (if frame_bytes > 0 { bytes / frame_bytes } else { samples }) as u64;
    }
    // Mirror current drift to the diagnostic atomic before releasing the
    // lock; captures both `bump_drift` (called from this thread's bad_pkts
    // handler) and `decay_drift` (called inside `samples_this_packet`).
    state
        .drift_correction_ppb
        .store(adapter.drift_correction_ppb(), Ordering::Relaxed);
    drop(adapter);

    let assign_avail = state.queue.available_assign();
    let mut fadein_rem = state.fadein_remaining.load(Ordering::Relaxed);
    let mut fadein_armed = false;
    let mut xrun_packets: u64 = 0;
    let mut queued_bytes = 0usize;

    let mut active_buf_base = ctx.scratch_ptr;
    let use_direct = if total_bytes > 0 && assign_avail >= total_bytes {
        match state.queue.reserve_direct_contiguous(total_bytes) {
            Some(ptr) => {
                let count = state.direct_queue_submits.fetch_add(1, Ordering::Relaxed) + 1;
                queue_direct_log(count, ctx.slot, total_bytes);
                active_buf_base = ptr;
                queued_bytes = total_bytes;
                true
            }
            None => {
                let count = state
                    .direct_queue_wrap_fallbacks
                    .fetch_add(1, Ordering::Relaxed)
                    + 1;
                queue_fallback_log(state, "wrap", count, ctx.slot, total_bytes, assign_avail);
                false
            }
        }
    } else {
        let count = state
            .direct_queue_underrun_fallbacks
            .fetch_add(1, Ordering::Relaxed)
            + 1;
        queue_fallback_log(state, "underrun", count, ctx.slot, total_bytes, assign_avail);
        false
    };

    (*transfer).buffer = active_buf_base as *mut c_uchar;
    (*transfer).length = total_bytes as c_int;

    let mut offset = 0usize;
    for i in 0..n_packets {
        let bytes = packet_bytes[i];
        let pkt = (*transfer).iso_packet_desc.as_mut_ptr().add(i);
        (*pkt).length = bytes as c_uint;

        let pkt_buf = std::slice::from_raw_parts_mut(active_buf_base.add(offset), bytes);
        let got = if use_direct {
            bytes
        } else {
            let got = state.queue.reserve_copy_into(pkt_buf);
            queued_bytes = queued_bytes.saturating_add(got);
            if got < bytes {
                if got > 0 && state.primed.load(Ordering::Relaxed) {
                    apply_fadeout_tail(
                        pkt_buf,
                        got,
                        state.bytes_per_sample,
                        state.sample_is_float,
                        state.channels,
                        xrun_fade_samples(state.rate) as usize,
                    );
                }
                pkt_buf[got..].fill(0);
                if state.primed.load(Ordering::Relaxed) {
                    xrun_packets += 1;
                    fadein_armed = true;
                }
            } else if bytes > 0 {
                state.primed.store(true, Ordering::Relaxed);
            }
            got
        };

        if use_direct && bytes > 0 {
            state.primed.store(true, Ordering::Relaxed);
        }

        if fadein_rem > 0 && got > 0 && frame_bytes > 0 {
            let ramp_total = xrun_fade_samples(state.rate);
            let n_frames = got / frame_bytes;
            for f in 0..n_frames {
                let pos = ramp_total.saturating_sub(fadein_rem);
                let frame_start = f * frame_bytes;
                apply_fadein_frame(
                    &mut pkt_buf[frame_start..frame_start + frame_bytes],
                    state.bytes_per_sample,
                    state.sample_is_float,
                    pos,
                    ramp_total,
                );
                fadein_rem = fadein_rem.saturating_sub(1);
                if fadein_rem == 0 {
                    break;
                }
            }
        }

        offset += bytes;
    }

    if fadein_armed {
        fadein_rem = xrun_fade_samples(state.rate);
    }
    state.fadein_remaining.store(fadein_rem, Ordering::Relaxed);

    if total_bytes > 0 {
        state
            .bytes_drained_total
            .fetch_add(total_bytes as u64, Ordering::Relaxed);
    }
    if xrun_packets > 0 {
        state.xruns.fetch_add(xrun_packets, Ordering::Relaxed);
    }
    if total_frames > 0 {
        state.clock_feed.advance(total_frames);
    }

    ctx.queued_bytes = queued_bytes;
}

/// libusb ISO OUT transfer completion callback.
extern "system" fn iso_out_callback(transfer: *mut libusb_transfer) {
    let cb_entry_ns = clock_monotonic_ns();

    // SAFETY: user_data points to a TransferCtx owned by IsoTransferRing.
    let ctx = unsafe { transfer_ctx(transfer) };
    let state_arc = Arc::clone(&ctx.state);

    // Release queue-backed bytes from the completed transfer before preparing
    // the next submission.  Ordered release is handled by CompletionTracker.
    release_completed_transfer_bytes(ctx);
    let state = state_arc.as_ref();

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
        // Counter only — see ISO jitter / parse-fail comments below.
        // Visible in v2-snapshot via `usb_short_pkt_log_count` if needed
        // later; today we just keep it for diagnostics on a non-RT thread.
        state
            .usb_short_pkt_log_count
            .fetch_add(1, Ordering::Relaxed);
    }
    if bad_pkts > 0 {
        let total_errors_before = state.usb_pkt_errors.fetch_add(bad_pkts, Ordering::Relaxed);

        // If the host-side FrameQueue has plenty of data, bad ISO packets
        // *can* indicate the device FIFO underflowed — its crystal faster
        // than the USB SOF-derived delivery rate — and bumping host rate
        // up by +2 ppm per confirmed window is the textbook compensation.
        //
        // BUT: this is only safe when the device has a feedback endpoint.
        // The bump is one-directional (+); it assumes "errors mean
        // underflow."  On devices with NO feedback endpoint at all
        // (`has_feedback_ep=false`, e.g. MOTU M4 in synchronous mode),
        // bad_pkts can equally mean device FIFO *overflowed* — host SOF
        // faster than device crystal — and bumping host higher then makes
        // it worse, producing more bad_pkts, producing more bumps.  This
        // is a positive-feedback runaway: the click-period halves with
        // every bump until drift saturates at ±100 ppm and noise repeats
        // many times per second (reported by 4-ch DAC users as
        // "noise tempo accelerating with track time").
        //
        // So restrict the bump to the originally-intended scenario:
        // device DOES have a feedback EP, but we haven't received a valid
        // value yet (early settling, transient ZLP storm).  Without a
        // feedback EP at all, leave drift at 0 and let the device's own
        // PLL absorb the small static rate offset.
        //
        // Hysteresis: ≥ 2 errors within a 1-second window, to filter
        // sporadic EMI / USB hub glitches.
        let queue_bytes = state.queue.available_read();
        let frame_bytes = state.channels * state.bytes_per_sample;
        // "Healthy" threshold: ≥ 20 ms of audio in the queue.
        let healthy_bytes = state.rate as usize * frame_bytes * 20 / 1000;
        let feedback = *state.feedback_ms.lock().unwrap_or_else(|e| e.into_inner());
        if queue_bytes >= healthy_bytes && feedback.is_none() && state.has_feedback_ep {
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
                    // Bump drift but DO NOT eprintln from event thread.
                    let mut adapter = state.rate_adapter.lock().unwrap_or_else(|e| e.into_inner());
                    adapter.bump_drift(DRIFT_BUMP_PPB);
                    state.drift_window_start_ns.store(0, Ordering::Relaxed);
                    state.drift_window_count.store(0, Ordering::Relaxed);
                }
            }
        }
        let _ = total_errors_before;
    }

    // ── ISO completion jitter measurement ──────────────────────────────
    // Each transfer covers ~8 ms of audio.  Flag outliers > 25% deviation
    // (so 8 ms ± 2 ms instead of ± 4 ms) — small xHCI scheduling slips of
    // 3-6 ms are below an audible "click" but enough to cause the "very
    // small pause" the user reports on 96 kHz, so we want to see those.
    {
        let now_ns = clock_monotonic_ns();
        let prev_ns = state.last_completion_ns.swap(now_ns, Ordering::Relaxed);
        if prev_ns != 0 {
            let delta_ns = now_ns.saturating_sub(prev_ns);
            let delta_us = delta_ns / 1_000;
            // Expected interval: n_packets * 1_000_000 / packets_per_sec µs
            // For 64 packets @ 8000 pkt/s = 8000 µs (8 ms)
            let expected_us = n_pkt as u64 * 1_000_000 / state.packets_per_sec as u64;
            let threshold_lo = expected_us * 3 / 4; // -25% (e.g. 6 ms for 8 ms expected)
            let threshold_hi = expected_us * 5 / 4; // +25% (e.g. 10 ms for 8 ms expected)

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
                // Counter only.  v2-snapshot exposes the cumulative
                // `jitter=N` field plus the windowed iso=[min..max] range,
                // so a per-event eprintln on the event thread isn't
                // needed — and would itself cause the click it'd be
                // logging by blocking on stderr long enough to delay the
                // next OUT completion past its microframe budget.
                state.iso_jitter_events.fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    // Refill the transfer buffer with fresh audio from the queue and resubmit.
    unsafe { fill_transfer(transfer) };

    // Record ISO completion timestamp for rate calibration.
    // Called after fill_transfer so total_frames reflects the just-written batch.
    state.clock_feed.record_iso(clock_monotonic_ns());

    let rc = unsafe { libusb_submit_transfer(transfer) };
    if rc == 0 {
        unsafe { mark_transfer_submitted(ctx) };
        state.in_flight.fetch_add(1, Ordering::AcqRel);
    } else if rc == libusb1_sys::constants::LIBUSB_ERROR_NO_DEVICE {
        state.queue.cancel_reserved(ctx.queued_bytes);
        ctx.queued_bytes = 0;
        // Submit failed because device is gone — same as NO_DEVICE above.
        state.error.store(true, Ordering::Release);
        state.stop.store(true, Ordering::Release);
    } else {
        state.queue.cancel_reserved(ctx.queued_bytes);
        ctx.queued_bytes = 0;
    }
    // Other submit failures: in_flight stays decremented; the ring self-heals
    // if other transfers are still running, or stop() will clean up.

    // ── Callback latency measurement ─────────────────────────────────────
    let cb_elapsed_us = clock_monotonic_ns().saturating_sub(cb_entry_ns) / 1_000;
    let prev_max = state.callback_max_us.load(Ordering::Relaxed);
    if cb_elapsed_us > prev_max {
        state
            .callback_max_us
            .store(cb_elapsed_us, Ordering::Relaxed);
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
    /// Per-transfer callback context (slot metadata + completion ordering).
    _ctxs: Vec<Box<TransferCtx>>,
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
    fn spawn_event_thread(&mut self) -> Result<(), String> {
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
                // With the current in-flight buffer depth this latency is safe.
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

    /// Allocate N transfers and their buffers.
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
        eprintln!(
            "usb-audio: IsoTransferRing n_transfers={} n_packets={} buf_size={} bytes ({} ms/transfer)",
            N_TRANSFERS, n_packets, buf_size,
            n_packets * 1000 / state.packets_per_sec as usize,
        );

        let mut transfers = Vec::with_capacity(N_TRANSFERS);
        let mut bufs = Vec::with_capacity(N_TRANSFERS);
        let mut ctxs = Vec::with_capacity(N_TRANSFERS);

        for slot in 0..N_TRANSFERS {
            let mut buf: Vec<u8> = vec![0u8; buf_size];
            let scratch_ptr = buf.as_mut_ptr();

            let xfer = unsafe { libusb_alloc_transfer(n_packets as c_int) };
            if xfer.is_null() {
                // Free any already-allocated transfers before returning
                for t in &transfers {
                    unsafe { libusb_free_transfer(*t) };
                }
                return Err("libusb_alloc_transfer failed (out of memory)".into());
            }

            let ctx = Box::new(TransferCtx {
                state: Arc::clone(&state),
                slot,
                scratch_ptr,
                queued_bytes: 0,
                submit_seq: 0,
            });
            let ctx_ptr = ctx.as_ref() as *const TransferCtx as *mut std::ffi::c_void;

            unsafe {
                libusb_fill_iso_transfer(
                    xfer,
                    dev_handle_raw,
                    ep as c_uchar,
                    buf.as_mut_ptr() as *mut c_uchar,
                    buf_size as c_int,
                    n_packets as c_int,
                    iso_out_callback,
                    ctx_ptr,
                    0, // timeout = 0 (no timeout)
                );
                libusb_set_iso_packet_lengths(xfer, state.max_packet as c_uint);
            }

            transfers.push(xfer);
            bufs.push(buf);
            ctxs.push(ctx);
        }

        Ok(Self {
            transfers,
            _bufs: bufs,
            _ctxs: ctxs,
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
        // Fade in the first ~5 ms from silence: track-start click was audible
        // whenever the audio file's sample 0 was non-zero (most music begins
        // above the noise floor), since the device output sat at 0 V before
        // the ring submitted its first packet.  Same ramp length used after
        // mid-stream underruns; sample count scales with the active rate.
        self.state
            .fadein_remaining
            .store(xrun_fade_samples(self.state.rate), Ordering::Relaxed);

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
            if bytes_per_ms > 0 {
                queue_at_start / bytes_per_ms
            } else {
                0
            },
            ring_needs,
            if bytes_per_ms > 0 {
                ring_needs / bytes_per_ms
            } else {
                0
            },
            self.transfers.len(),
        );

        // Fill all transfer buffers before first submission
        for &xfer in &self.transfers {
            unsafe { fill_transfer(xfer) };
        }

        self.spawn_event_thread()?;

        let mut submitted = 0usize;
        let mut submit_err: Option<c_int> = None;
        for &xfer in &self.transfers {
            let rc = unsafe { libusb_submit_transfer(xfer) };
            if rc == 0 {
                unsafe { mark_transfer_submitted(transfer_ctx(xfer)) };
                self.state.in_flight.fetch_add(1, Ordering::AcqRel);
                submitted += 1;
            } else {
                let ctx = unsafe { transfer_ctx(xfer) };
                self.state.queue.cancel_reserved(ctx.queued_bytes);
                ctx.queued_bytes = 0;
                submit_err = Some(rc);
                break;
            }
        }
        if let Some(rc) = submit_err {
            self.state.stop.store(true, Ordering::SeqCst);
            for &xfer in &self.transfers {
                unsafe { libusb_cancel_transfer(xfer) };
            }
            if let Some(t) = self.event_thread.take() {
                let _ = t.join();
            }
            return Err(format!(
                "submit ISO OUT transfer failed rc={} after arming {}/{} transfers",
                rc,
                submitted,
                self.transfers.len(),
            ));
        }
        if submitted == 0 {
            self.state.stop.store(true, Ordering::SeqCst);
            if let Some(t) = self.event_thread.take() {
                let _ = t.join();
            }
            return Err("no ISO OUT transfers were submitted".into());
        }
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
        self._ctxs.clear();
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
