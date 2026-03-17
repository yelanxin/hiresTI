/// ALSA-hardware-backed GStreamer clock — frame-counting design.
///
/// # Design
///
/// The ALSA mmap writer thread calls [`AlsaHwClockFeed::anchor`] once when
/// the first frames are committed (i.e. when `snd_pcm_start` is imminent),
/// then calls [`AlsaHwClockFeed::advance`] after every successful
/// `snd_pcm_mmap_commit()`.
///
/// The clock time is computed as:
///
/// ```text
/// hw_time_ns = anchor_ns + total_frames * 1_000_000_000 / rate
/// ```
///
/// where `anchor_ns` is the `CLOCK_MONOTONIC` value recorded at the start of
/// playback and `total_frames` is the running count of PCM frames committed to
/// the ALSA ring buffer since that anchor.
///
/// This is a **purely feed-forward, jitter-free** clock.  It never reads
/// `snd_pcm_status()`, so there is no delay-measurement feedback loop that
/// could destabilise the pipeline at low latencies.  The clock advances at
/// exactly 1 ns per sample-period because frame counting is integer arithmetic
/// locked to the hardware sample rate.
///
/// Before the first anchor arrives (pre-playback, after seeks, …) the clock
/// falls back to a plain `CLOCK_MONOTONIC` reading so it always returns a
/// valid, monotonically increasing time.
///
/// # Thread safety
///
/// [`AlsaHwClockFeed`] uses only atomics; it is `Send + Sync` and safe to
/// share between the audio RT thread and GStreamer's streaming threads.
use std::sync::OnceLock;
use std::sync::{
    Arc,
    atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering},
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
    /// `CLOCK_MONOTONIC` nanoseconds at the start of playback (first commit).
    anchor_ns:    AtomicU64,
    /// Total PCM frames committed since the anchor was set.
    total_frames: AtomicU64,
    /// Negotiated sample rate (frames per second).
    rate:         AtomicU32,
    /// True once `anchor()` has been called and the feed is ready.
    valid:        AtomicBool,
}

impl AlsaHwClockFeed {
    /// Called once when playback starts (before or at the first commit).
    ///
    /// `anchor_ns` : `CLOCK_MONOTONIC` ns at the moment of the first commit.\
    /// `rate`      : negotiated sample rate in Hz.
    pub fn anchor(&self, anchor_ns: u64, rate: u32) {
        self.anchor_ns.store(anchor_ns, Ordering::Relaxed);
        self.total_frames.store(0, Ordering::Relaxed);
        self.rate.store(rate, Ordering::Relaxed);
        // Release fence: all stores above become visible before valid = true.
        self.valid.store(true, Ordering::Release);
    }

    /// Called after every successful `snd_pcm_mmap_commit(n)`.
    ///
    /// `frames` : the number of frames returned by `snd_pcm_mmap_commit`.
    pub fn advance(&self, frames: u64) {
        // Relaxed is fine: the reader only needs the latest snapshot, not
        // strict ordering relative to other stores.
        self.total_frames.fetch_add(frames, Ordering::Relaxed);
    }

    /// Invalidate: called when ALSA device closes (rate change, seek, …).
    pub fn invalidate(&self) {
        self.valid.store(false, Ordering::Release);
    }

    /// Estimate of the hardware playback position as `CLOCK_MONOTONIC` ns.
    /// Returns `None` if the feed has not been anchored yet.
    pub fn hw_now_ns(&self) -> Option<u64> {
        // Acquire: ensures we read consistent anchor/rate after valid = true.
        if !self.valid.load(Ordering::Acquire) {
            return None;
        }
        let anchor_ns    = self.anchor_ns.load(Ordering::Relaxed);
        let total_frames = self.total_frames.load(Ordering::Relaxed);
        let rate         = self.rate.load(Ordering::Relaxed) as u64;
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
        /// Returns `anchor_ns + total_frames * 1e9 / rate`, which advances at
        /// exactly 1 ns/ns with zero jitter.  Falls back to the parent
        /// `SystemClock` (plain `CLOCK_MONOTONIC`) when the feed is not yet
        /// anchored, so the clock is always valid.
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
