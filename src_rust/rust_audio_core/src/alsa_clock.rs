/// ALSA-hardware-backed GStreamer clock — frame-counting design.
///
/// # Design
///
/// The ALSA mmap writer thread calls [`AlsaHwClockFeed::anchor`] once when
/// the first frames are committed (i.e. when `snd_pcm_start` is imminent),
/// then calls [`AlsaHwClockFeed::advance`] after every successful
/// `snd_pcm_mmap_commit()`.
///
/// ## Push clock (default)
///
/// The clock time is computed as:
///
/// ```text
/// hw_time_ns = anchor_ns + total_frames * 1_000_000_000 / rate
/// ```
///
/// where `anchor_ns` is the `CLOCK_MONOTONIC` value recorded at the start of
/// playback and `total_frames` is the running count of PCM frames committed to
/// the device since that anchor.
///
/// This is a **purely feed-forward, jitter-free** clock.  It never reads
/// `snd_pcm_status()`, so there is no delay-measurement feedback loop that
/// could destabilise the pipeline at low latencies.  The clock advances at
/// exactly 1 ns per sample-period because frame counting is integer arithmetic
/// locked to the hardware sample rate.
///
/// ## Pull clock (Level 3)
///
/// When [`ClockMode::Pull`] is selected the clock calibrates the *actual* USB
/// frame rate via sliding-window linear regression on ISO completion timestamps,
/// then returns:
///
/// ```text
/// pull_ns = pull_anchor_ns
///         + (total_frames − pull_anchor_frames) × ns_per_frame_calibrated
///         − buffer_depth_ns
/// ```
///
/// During the calibration warm-up period (< `CALIBRATOR_MIN_POINTS` ISO
/// completions) the pull clock transparently falls back to the push formula.
///
/// Before the first anchor arrives (pre-playback, after seeks, …) both modes
/// fall back to a plain `CLOCK_MONOTONIC` reading so the clock always returns
/// a valid, monotonically increasing time.
///
/// # Thread safety
///
/// [`AlsaHwClockFeed`] is `Send + Sync`.  The hot-path atomics are written by
/// the ISO OUT callback thread (push: one `fetch_add`; pull: one
/// `record_iso()` behind a lock that is taken at 125 Hz) and read by
/// GStreamer's streaming threads.
use std::collections::VecDeque;
use std::sync::OnceLock;
use std::sync::{
    atomic::{AtomicBool, AtomicU32, AtomicU64, AtomicU8, Ordering},
    Arc, Mutex,
};

use gst::glib;
use gst::prelude::*;
use gst::subclass::prelude::*;
use gstreamer as gst;

// ---------------------------------------------------------------------------
// Clock mode
// ---------------------------------------------------------------------------

/// Selects the timing strategy for [`AlsaHwClockFeed::hw_now_ns`].
#[repr(u8)]
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ClockMode {
    /// Push: `anchor_ns + total_frames × 1e9 / nominal_rate`.
    Push = 0,
    /// Pull: ISO-completion regression + buffer-depth compensation.
    Pull = 1,
}

// ---------------------------------------------------------------------------
// Rate calibrator (used by Pull mode)
// ---------------------------------------------------------------------------

/// Sliding-window least-squares calibrator for the actual USB frame rate.
///
/// Records `(iso_completion_ts_ns, cumulative_frames)` pairs from the ISO OUT
/// callback thread.  Once [`CALIBRATOR_MIN_POINTS`] points are accumulated it
/// publishes a calibrated `ns_per_frame` value via
/// [`AlsaHwClockFeed::record_iso`].
///
/// The window slides: once full, the oldest point is evicted and the running
/// sums are updated in O(1).
const CALIBRATOR_WINDOW: usize = 128; // ~1 s at 8 ms/callback
const CALIBRATOR_MIN_POINTS: usize = 32; // ~256 ms warm-up

#[derive(Debug)]
struct RateCalibrator {
    window: VecDeque<(u64, u64)>, // (ts_ns, cumulative_frames)
    /// Offset subtracted from timestamps for numerical stability.
    base_ns: u64,
    /// Offset subtracted from frame counts for numerical stability.
    base_frames: u64,
    // Running sums for O(1) regression updates.
    n: f64,
    sum_x: f64,  // Σ(ts − base_ns)
    sum_y: f64,  // Σ(frames − base_frames)
    sum_xx: f64, // Σ(ts − base_ns)²
    sum_xy: f64, // Σ(ts − base_ns) × (frames − base_frames)
}

impl Default for RateCalibrator {
    fn default() -> Self {
        Self {
            window: VecDeque::with_capacity(CALIBRATOR_WINDOW + 1),
            base_ns: 0,
            base_frames: 0,
            n: 0.0,
            sum_x: 0.0,
            sum_y: 0.0,
            sum_xx: 0.0,
            sum_xy: 0.0,
        }
    }
}

impl RateCalibrator {
    fn reset(&mut self) {
        *self = Self::default();
    }

    /// Add one ISO completion sample.
    fn push(&mut self, ts_ns: u64, cum_frames: u64) {
        // Set base on first point.
        if self.window.is_empty() {
            self.base_ns = ts_ns;
            self.base_frames = cum_frames;
        }

        let x = (ts_ns - self.base_ns) as f64;
        let y = (cum_frames - self.base_frames) as f64;

        // Evict oldest point if window is full.
        if self.window.len() >= CALIBRATOR_WINDOW {
            let (old_ts, old_frames) = self.window.pop_front().unwrap();
            let ox = (old_ts - self.base_ns) as f64;
            let oy = (old_frames - self.base_frames) as f64;
            self.n -= 1.0;
            self.sum_x -= ox;
            self.sum_y -= oy;
            self.sum_xx -= ox * ox;
            self.sum_xy -= ox * oy;
        }

        self.window.push_back((ts_ns, cum_frames));
        self.n += 1.0;
        self.sum_x += x;
        self.sum_y += y;
        self.sum_xx += x * x;
        self.sum_xy += x * y;
    }

    /// Returns calibrated nanoseconds-per-frame × 2³² (fixed-point), or `0`
    /// if there are not enough points yet or the regression is degenerate.
    fn ns_per_frame_fp32(&self) -> u64 {
        if self.window.len() < CALIBRATOR_MIN_POINTS {
            return 0;
        }
        let n = self.n;
        let denom = n * self.sum_xx - self.sum_x * self.sum_x;
        if denom.abs() < 1.0 {
            return 0;
        }
        // slope = frames / ns (frames per nanosecond)
        let slope = (n * self.sum_xy - self.sum_x * self.sum_y) / denom;
        if slope <= 0.0 {
            return 0;
        }
        let ns_per_frame = 1.0 / slope;
        let fp32 = ns_per_frame * (1u64 << 32) as f64;
        if !(1.0..=u64::MAX as f64).contains(&fp32) {
            return 0;
        }
        fp32 as u64
    }
}

// ---------------------------------------------------------------------------
// Shared feed (writer thread → clock)
// ---------------------------------------------------------------------------

/// Lock-free state published by the audio output thread.
///
/// Supports two timing modes; see the module-level doc for details.
#[derive(Debug)]
pub struct AlsaHwClockFeed {
    // ── Push clock fields ───────────────────────────────────────────────────
    /// `CLOCK_MONOTONIC` nanoseconds at the start of playback (first commit).
    anchor_ns: AtomicU64,
    /// Total PCM frames committed since the anchor was set.
    total_frames: AtomicU64,
    /// Negotiated sample rate (frames per second).
    pub(crate) rate: AtomicU32,
    /// True once `anchor()` has been called and the feed is ready.
    valid: AtomicBool,

    // ── Pull clock fields ────────────────────────────────────────────────────
    /// Active clock mode (0 = Push, 1 = Pull).
    mode: AtomicU8,
    /// Write-ahead depth of the ISO transfer ring in nanoseconds.
    /// Approximately 128 ms for the standard 16-transfer × 8 ms ring.
    pub(crate) buffer_depth_ns: AtomicU64,
    /// ISO completion timestamp (ns) of the calibration anchor.
    pull_anchor_ns: AtomicU64,
    /// `total_frames` value at the calibration anchor.
    pull_anchor_frames: AtomicU64,
    /// Calibrated nanoseconds-per-frame × 2³² (fixed-point).
    pull_ns_per_frame_fp32: AtomicU64,
    /// True once the calibrator has published its first result.
    pull_ready: AtomicBool,
    /// Calibrated nanoseconds-per-frame × 2³² (fixed-point), always updated
    /// regardless of clock mode.  Used by RateAdapter to correct for device
    /// crystal offset on SOF-synchronized devices that don't send UAC2 feedback.
    /// Zero means "not calibrated yet".  Valid in both Pull and Push modes.
    device_rate_fp32: AtomicU64,
    /// Rate calibrator — updated by the ISO OUT callback thread.
    calibrator: Mutex<RateCalibrator>,
}

impl Default for AlsaHwClockFeed {
    fn default() -> Self {
        Self {
            anchor_ns: AtomicU64::new(0),
            total_frames: AtomicU64::new(0),
            rate: AtomicU32::new(0),
            valid: AtomicBool::new(false),
            mode: AtomicU8::new(ClockMode::Push as u8),
            buffer_depth_ns: AtomicU64::new(128_000_000), // 128 ms fallback
            pull_anchor_ns: AtomicU64::new(0),
            pull_anchor_frames: AtomicU64::new(0),
            pull_ns_per_frame_fp32: AtomicU64::new(0),
            pull_ready: AtomicBool::new(false),
            device_rate_fp32: AtomicU64::new(0),
            calibrator: Mutex::new(RateCalibrator::default()),
        }
    }
}

impl AlsaHwClockFeed {
    // ── Push clock interface ─────────────────────────────────────────────────

    /// Called once when playback starts (before or at the first commit).
    ///
    /// Resets both the push and pull calibration state so a new session begins
    /// cleanly.
    pub fn anchor(&self, anchor_ns: u64, rate: u32) {
        self.anchor_ns.store(anchor_ns, Ordering::Relaxed);
        self.total_frames.store(0, Ordering::Relaxed);
        self.rate.store(rate, Ordering::Relaxed);

        // Reset pull state so the new session re-calibrates from scratch.
        self.pull_ready.store(false, Ordering::Relaxed);
        self.pull_anchor_ns.store(0, Ordering::Relaxed);
        self.pull_anchor_frames.store(0, Ordering::Relaxed);
        self.pull_ns_per_frame_fp32.store(0, Ordering::Relaxed);
        self.device_rate_fp32.store(0, Ordering::Relaxed);
        if let Ok(mut cal) = self.calibrator.try_lock() {
            cal.reset();
        }

        // Release fence: all stores above become visible before valid = true.
        self.valid.store(true, Ordering::Release);
    }

    /// Called after every successful commit of `frames` PCM frames to the
    /// output device (ALSA mmap commit or ISO OUT transfer packet).
    pub fn advance(&self, frames: u64) {
        self.total_frames.fetch_add(frames, Ordering::Relaxed);
    }

    /// Invalidate: called when the device closes (rate change, seek, …).
    pub fn invalidate(&self) {
        self.valid.store(false, Ordering::Release);
    }

    // ── Pull clock interface ─────────────────────────────────────────────────

    /// Set the active clock mode.
    ///
    /// Can be called at any time; takes effect on the next [`hw_now_ns`] call.
    ///
    /// Switching **into** [`ClockMode::Pull`] resets the calibrator and clears
    /// `pull_ready` so the transition logic in [`record_iso`] fires again,
    /// giving a seamless, jitter-free handoff from the push clock.
    ///
    /// Switching **into** [`ClockMode::Push`] takes effect immediately; the
    /// push formula needs no warm-up.
    /// Current clock mode.
    pub fn mode(&self) -> ClockMode {
        if self.mode.load(Ordering::Relaxed) == ClockMode::Pull as u8 {
            ClockMode::Pull
        } else {
            ClockMode::Push
        }
    }

    pub fn set_mode(&self, mode: ClockMode) {
        let old_raw = self.mode.swap(mode as u8, Ordering::Relaxed);
        if mode == ClockMode::Pull && old_raw != ClockMode::Pull as u8 {
            // Reset so record_iso warms up fresh and applies the seamless
            // anchor adjustment when pull_ready first becomes true.
            self.pull_ready.store(false, Ordering::Relaxed);
            if let Ok(mut cal) = self.calibrator.try_lock() {
                cal.reset();
            }
        }
    }

    /// Set the write-ahead buffer depth of the ISO transfer ring.
    ///
    /// This value is subtracted from the write position in Pull mode to obtain
    /// the estimated *play* position.  Should be set once per device open,
    /// before the ISO ring starts.
    pub fn set_buffer_depth_ns(&self, ns: u64) {
        self.buffer_depth_ns.store(ns, Ordering::Relaxed);
    }

    /// Record one ISO OUT transfer completion for rate calibration.
    ///
    /// Called from the libusb event thread (inside `iso_out_callback`) once
    /// per transfer completion (~125 Hz for 8 ms transfers).
    ///
    /// Always calibrates the device crystal rate (stored in `device_rate_fp32`)
    /// so the RateAdapter can correct for SOF-synchronized devices in both Pull
    /// and Push clock modes.  Pull clock anchor/formula updates are gated on
    /// Pull mode being active.
    pub fn record_iso(&self, ts_ns: u64) {
        let in_pull_mode = self.mode.load(Ordering::Relaxed) == ClockMode::Pull as u8;
        let cum_frames = self.total_frames.load(Ordering::Relaxed);
        let mut cal = self.calibrator.lock().unwrap_or_else(|e| e.into_inner());
        cal.push(ts_ns, cum_frames);
        let fp32 = cal.ns_per_frame_fp32();
        if fp32 > 0 {
            // Always publish for RateAdapter use (both Pull and Push modes).
            self.device_rate_fp32.store(fp32, Ordering::Relaxed);

            if !in_pull_mode {
                return;
            }
            let was_ready = self.pull_ready.load(Ordering::Relaxed);

            // Publish anchor from the latest window point.
            // On the very first activation (!was_ready) we adjust pull_anchor_ns
            // so the pull clock is continuous with the push clock — avoiding the
            // 128 ms backwards jump that would stall GStreamer delivery.
            //
            // Push value at transition: push_anchor_ns + anchor_frames × 1e9/rate
            // We need:  pull_anchor_ns − buffer_depth_ns  =  push_value
            // ⟹  pull_anchor_ns = push_anchor_ns
            //                    + anchor_frames × 1e9 / rate
            //                    + buffer_depth_ns
            //
            // All stores must complete BEFORE pull_ready is released so the
            // reader thread never sees a stale pull_anchor_ns.
            if let Some(&(anchor_ts, anchor_frames)) = cal.window.back() {
                // On first activation: compute a seamless anchor so the pull clock
        // is continuous with the push clock (no backwards jump).
        // On subsequent calls: anchor is NEVER updated — only ns_per_frame
        // changes.  This eliminates the triple-atomic race where GStreamer
        // could read a mismatched (new anchor_ns, old anchor_frames) pair
        // and compute a clock value that jumps by ~8 ms.
        if !was_ready {
            let final_anchor_ns = {
                let rate = self.rate.load(Ordering::Relaxed) as u64;
                if rate > 0 {
                    let push_base = self.anchor_ns.load(Ordering::Relaxed);
                    let buffer_depth = self.buffer_depth_ns.load(Ordering::Relaxed);
                    let push_now = push_base
                        .saturating_add(anchor_frames.saturating_mul(1_000_000_000) / rate);
                    push_now.saturating_add(buffer_depth)
                } else {
                    anchor_ts
                }
            };
            self.pull_anchor_ns
                .store(final_anchor_ns, Ordering::Relaxed);
            self.pull_anchor_frames
                .store(anchor_frames, Ordering::Relaxed);
        }
        // (else: anchor_ns and anchor_frames stay fixed forever)
            }
            self.pull_ns_per_frame_fp32.store(fp32, Ordering::Relaxed);
            // Release fence: all stores above become visible before pull_ready.
            self.pull_ready.store(true, Ordering::Release);

            if !was_ready {
                let ns_per_frame = fp32 as f64 / (1u64 << 32) as f64;
                let calibrated_rate = 1_000_000_000.0 / ns_per_frame;
                let nominal_rate = self.rate.load(Ordering::Relaxed);
                let ppm =
                    (calibrated_rate - nominal_rate as f64) / nominal_rate as f64 * 1_000_000.0;
                let buffer_ms = self.buffer_depth_ns.load(Ordering::Relaxed) / 1_000_000;
                eprintln!(
                    "pull-clock: ACTIVE calibrated_rate={:.3} Hz nominal={} ppm={:+.1} buffer_depth={}ms n_points={}",
                    calibrated_rate, nominal_rate, ppm, buffer_ms, cal.window.len()
                );
            }
        }
    }

    /// Calibrated device sample rate in Hz, derived from ISO OUT timestamps.
    ///
    /// Valid in both Pull and Push clock modes once enough ISO completions have
    /// been recorded (~1 second).  Returns `None` until calibration converges.
    ///
    /// Used by `RateAdapter` to correct for SOF-synchronized devices whose
    /// crystal runs slightly faster or slower than the nominal rate.  Without
    /// this correction the device FIFO drifts at a rate equal to the crystal
    /// offset (typically 1–5 samples/second), causing a glitch after ~2 minutes.
    pub fn calibrated_rate_hz(&self) -> Option<f64> {
        let fp32 = self.device_rate_fp32.load(Ordering::Relaxed);
        if fp32 == 0 {
            return None;
        }
        let ns_per_frame = fp32 as f64 / (1u64 << 32) as f64;
        Some(1_000_000_000.0 / ns_per_frame)
    }

    // ── Shared read path ─────────────────────────────────────────────────────

    /// Estimate of the hardware playback position as `CLOCK_MONOTONIC` ns.
    ///
    /// Returns `None` if the feed has not been anchored yet.
    pub fn hw_now_ns(&self) -> Option<u64> {
        // Acquire: ensures we see consistent anchor/rate after valid = true.
        if !self.valid.load(Ordering::Acquire) {
            return None;
        }

        // ── Pull mode ──────────────────────────────────────────────────────
        if self.mode.load(Ordering::Relaxed) == ClockMode::Pull as u8
            && self.pull_ready.load(Ordering::Acquire)
        {
            let anchor_ns = self.pull_anchor_ns.load(Ordering::Relaxed);
            let anchor_frames = self.pull_anchor_frames.load(Ordering::Relaxed);
            let total_frames = self.total_frames.load(Ordering::Relaxed);
            let ns_per_fp32 = self.pull_ns_per_frame_fp32.load(Ordering::Relaxed);
            let buffer_depth = self.buffer_depth_ns.load(Ordering::Relaxed);

            let elapsed_frames = total_frames.saturating_sub(anchor_frames);
            // Fixed-point multiply: (frames × ns_per_frame_fp32) >> 32
            let elapsed_ns = ((elapsed_frames as u128 * ns_per_fp32 as u128) >> 32) as u64;
            let write_ns = anchor_ns.saturating_add(elapsed_ns);
            return Some(write_ns.saturating_sub(buffer_depth));
        }

        // ── Push mode (default / pull warm-up fallback) ────────────────────
        let anchor_ns = self.anchor_ns.load(Ordering::Relaxed);
        let total_frames = self.total_frames.load(Ordering::Relaxed);
        let rate = self.rate.load(Ordering::Relaxed) as u64;
        if rate == 0 {
            return None;
        }
        // Integer arithmetic: no floating-point, no jitter.
        let elapsed_ns = total_frames.saturating_mul(1_000_000_000) / rate;
        Some(anchor_ns.saturating_add(elapsed_ns))
    }
}

// ---------------------------------------------------------------------------
// GObject subclass implementation
// ---------------------------------------------------------------------------

mod imp {
    use super::*;

    #[derive(Default)]
    pub struct AlsaHwClock {
        /// Set once during construction; never changed afterwards.
        pub feed: OnceLock<Arc<AlsaHwClockFeed>>,
    }

    // SAFETY: AlsaHwClockFeed is Send+Sync (atomics + Mutex).
    unsafe impl Send for AlsaHwClock {}
    unsafe impl Sync for AlsaHwClock {}

    #[glib::object_subclass]
    impl ObjectSubclass for AlsaHwClock {
        const NAME: &'static str = "AlsaHwClock";
        type Type = super::AlsaHwClock;
        type ParentType = gst::SystemClock;
    }

    impl ObjectImpl for AlsaHwClock {}
    impl GstObjectImpl for AlsaHwClock {}
    impl gst::subclass::prelude::SystemClockImpl for AlsaHwClock {}

    impl ClockImpl for AlsaHwClock {
        /// Override the internal time source with the hardware playback position.
        ///
        /// In Push mode: returns `anchor_ns + total_frames × 1e9 / rate` (zero
        /// jitter, integer arithmetic).  In Pull mode: returns the regression-
        /// calibrated play position once warmed up.  Falls back to the parent
        /// `SystemClock` (plain `CLOCK_MONOTONIC`) when the feed is not yet
        /// anchored.
        fn internal_time(&self) -> gst::ClockTime {
            if let Some(feed) = self.feed.get() {
                if let Some(hw_ns) = feed.hw_now_ns() {
                    return gst::ClockTime::from_nseconds(hw_ns);
                }
            }
            self.parent_internal_time()
        }
    }
}

// ---------------------------------------------------------------------------
// Public GObject wrapper
// ---------------------------------------------------------------------------

glib::wrapper! {
    /// GStreamer clock whose internal time tracks committed PCM frame count.
    pub struct AlsaHwClock(ObjectSubclass<imp::AlsaHwClock>)
        @extends gst::SystemClock, gst::Clock, gst::Object;
}

impl AlsaHwClock {
    pub fn new(feed: Arc<AlsaHwClockFeed>) -> Self {
        let clock: Self = glib::Object::new();
        clock.imp().feed.set(feed).ok();
        // Use CLOCK_MONOTONIC as the base so times are compatible with the
        // hardware timestamp domain (which is also CLOCK_MONOTONIC).
        clock.set_clock_type(gst::ClockType::Monotonic);
        clock
    }
}
