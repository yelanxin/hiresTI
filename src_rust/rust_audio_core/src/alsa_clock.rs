/// ALSA-hardware-backed GStreamer clock.
///
/// # Design
///
/// The ALSA mmap writer thread calls [`AlsaHwClockFeed::update`] after every
/// `snd_pcm_mmap_commit()`.  Each update records:
///   - `sys_ts_ns` — `CLOCK_MONOTONIC` nanoseconds at the moment
///     `snd_pcm_status()` was called.
///   - `delay_frames` — `snd_pcm_status_get_delay()`: frames committed to the
///     ALSA ring buffer but not yet consumed by the DAC.
///   - `rate` — negotiated sample rate.
///
/// From these three values the clock computes the DAC's current playback
/// position on every `get_internal_time()` call:
///
/// ```text
/// delay_ns   = delay_frames * 1_000_000_000 / rate
/// hw_now_ns  = CLOCK_MONOTONIC() − delay_ns
/// ```
///
/// The insight: `CLOCK_MONOTONIC − delay_ns` is constant (≈ output latency)
/// between updates and advances at exactly 1 ns/ns because the live monotonic
/// clock supplies the "time since last status" term automatically.
///
/// Before the first ALSA status arrives (pre-playback, during seeks, …) the
/// clock falls back to a plain `CLOCK_MONOTONIC` reading, so it always returns
/// a valid, monotonically increasing time.
///
/// # Thread safety
///
/// [`AlsaHwClockFeed`] uses only atomics; it is `Send + Sync` and safe to
/// share between the audio RT thread and GStreamer's streaming threads.
/// The clock object itself is a GObject and follows GStreamer's usual rules.
use std::sync::OnceLock;
use std::sync::{
    Arc,
    atomic::{AtomicBool, AtomicI64, AtomicU32, AtomicU64, Ordering},
};

use gstreamer as gst;
use gst::glib;
use gst::prelude::*;
use gst::subclass::prelude::*;

// ---------------------------------------------------------------------------
// Shared feed (writer thread → clock)
// ---------------------------------------------------------------------------

/// Lock-free state published by the ALSA mmap writer thread.
#[derive(Debug, Default)]
pub struct AlsaHwClockFeed {
    sys_ts_ns:    AtomicU64,
    delay_frames: AtomicI64,
    rate:         AtomicU32,
    valid:        AtomicBool,
}

impl AlsaHwClockFeed {
    /// Called from the writer thread after each `snd_pcm_mmap_commit()`.
    ///
    /// `sys_ts_ns`    : `CLOCK_MONOTONIC` ns when `snd_pcm_status()` was polled.
    /// `delay_frames` : frames buffered in ALSA but not yet played.
    /// `rate`         : negotiated sample rate.
    pub fn update(&self, sys_ts_ns: u64, delay_frames: i64, rate: u32) {
        self.sys_ts_ns.store(sys_ts_ns,       Ordering::Relaxed);
        self.delay_frames.store(delay_frames, Ordering::Relaxed);
        self.rate.store(rate,                 Ordering::Relaxed);
        // Release fence: all stores above become visible before valid=true.
        self.valid.store(true, Ordering::Release);
    }

    /// Invalidate: called when ALSA device closes (rate change, seek, …).
    pub fn invalidate(&self) {
        self.valid.store(false, Ordering::Release);
    }

    /// Estimate of the hardware playback position as `CLOCK_MONOTONIC` ns.
    /// Returns `None` if no valid status has been published yet.
    pub fn hw_now_ns(&self) -> Option<u64> {
        // Acquire: ensures we read consistent delay/rate after seeing valid=true.
        if !self.valid.load(Ordering::Acquire) {
            return None;
        }
        let delay_frames = self.delay_frames.load(Ordering::Relaxed);
        let rate         = self.rate.load(Ordering::Relaxed) as u64;
        if rate == 0 {
            return None;
        }
        let delay_ns = if delay_frames > 0 {
            (delay_frames as u64).saturating_mul(1_000_000_000) / rate
        } else {
            0
        };
        // CLOCK_MONOTONIC − output_latency = hardware playback position.
        Some(monotonic_ns().saturating_sub(delay_ns))
    }
}

#[inline]
fn monotonic_ns() -> u64 {
    let mut ts = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut ts) };
    ts.tv_sec as u64 * 1_000_000_000 + ts.tv_nsec as u64
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

    // SAFETY: AlsaHwClockFeed is Send+Sync (atomics only).
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
        /// When ALSA has provided a valid status snapshot the function returns
        /// `CLOCK_MONOTONIC − output_latency`, which advances at exactly 1 ns/ns
        /// and represents where the DAC needle is right now.
        ///
        /// When the feed is not yet valid (pre-playback, device closed, …) the
        /// call delegates to the parent `SystemClock`, which returns a plain
        /// `CLOCK_MONOTONIC` reading.  This guarantees the clock is always
        /// monotonically increasing and never stalls the pipeline.
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
    /// GStreamer clock whose internal time tracks the ALSA DAC playback position.
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
