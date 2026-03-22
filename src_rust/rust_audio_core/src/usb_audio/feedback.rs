//! UAC 2.0 feedback endpoint reader and sample-rate adapter.
//!
//! # Feedback format
//!
//! UAC 2.0 High-Speed devices send a 4-byte Q16.16 fixed-point value on the
//! feedback IN endpoint every `2^(10-P)` microframes, where P is the endpoint's
//! `bRefresh` field.  The value represents the actual DAC clock rate in
//! **samples per microframe** (1 microframe = 125 µs).
//!
//! To convert to **samples per ISO packet**:
//! ```text
//! samples_per_packet = (feedback_raw / 2^16) * microframes_per_packet
//! ```
//! where `microframes_per_packet = 8000 / packets_per_sec`.
//!
//! UAC 1.0 Full-Speed devices send a 3-byte Q10.14 value in
//! **samples per frame** directly (1 frame = 1 ms).
//!
//! # RateAdapter
//!
//! [`RateAdapter`] converts the potentially-fractional feedback rate into an
//! integer sample count per ISO packet using an error accumulator:
//!
//! ```text
//! accumulator += feedback_millisamples   // e.g. 5512500 for 44.1 kHz @ 125 us
//! n = accumulator / 1_000_000           // integer samples this packet
//! accumulator -= n * 1_000_000
//! ```
//!
//! Without feedback input the adapter returns the nominal per-packet rate,
//! which gives exactly the right average for synchronous and adaptive DACs.

/// Accumulator-based per-packet sample counter.
///
/// Resolves the fractional-samples-per-frame problem for 44.1 kHz family rates
/// (e.g. 44100 Hz → alternating 44/45 samples per 1 ms ISO packet) without
/// floating-point arithmetic in the RT path.
///
/// # Adaptive drift correction
///
/// For devices without a UAC feedback endpoint (e.g. FiiO KA13), the device
/// crystal may run slightly faster than the USB host crystal, causing the
/// device FIFO to slowly drain and produce a glitch every ~2 minutes.
///
/// The `drift_correction_ppb` field adds a parts-per-billion bias to the
/// nominal rate.  It is bumped up when device-side USB packet errors occur
/// (indicating FIFO underflow) and slowly decayed back to zero when no
/// errors are seen, preventing FIFO overflow.
pub struct RateAdapter {
    /// Accumulated millisamples (1/1_000_000 sample units).
    accumulator: i64,
    /// Nominal millisamples per packet.
    ///
    /// For 1ms-per-packet (full-speed or HS bInterval=4): `rate * 1000`
    /// For 125µs-per-packet (HS bInterval=1 microframe):  `rate * 125`
    ///
    /// `accumulator / 1_000_000` gives the integer samples per packet.
    nominal_millisamples: i64,
    /// Packet rate in Hz (1000 for 1ms, 8000 for 125µs microframes).
    packets_per_sec: u32,
    /// Additive drift correction in parts-per-billion (ppb).
    /// Positive = deliver slightly more samples (compensate faster device clock).
    /// Clamped to ±100_000 ppb (±100 ppm).
    drift_correction_ppb: i64,
    /// Packets since the last decay step.
    packets_since_decay: u32,
}

/// Decay interval: apply one decay step every this many packets.
/// At 8000 pkt/s (HS microframe) this is once per second.
const DRIFT_DECAY_INTERVAL_PKTS: u32 = 8_000;

/// Amount to decay per step, in ppb.  At 1 step/second this removes
/// 200 ppb/s ≈ 0.2 ppm/s, draining a +2000 ppb bump in ~10 seconds.
const DRIFT_DECAY_STEP_PPB: i64 = 200;

/// Maximum allowed correction magnitude (ppb).  ±100 ppm.
const DRIFT_MAX_PPB: i64 = 100_000;

/// Bump size when a device-side FIFO underflow is inferred, in ppb.
/// +2000 ppb = +2 ppm.  For 44100 Hz this adds ~0.088 samples/s to the
/// delivery rate — enough to slowly refill a small (~10 sample) device
/// FIFO without overflowing it.
pub const DRIFT_BUMP_PPB: i64 = 2_000;

impl RateAdapter {
    /// Create a new adapter for `rate` Hz with the given ISO packet rate.
    ///
    /// `packets_per_sec` is the number of ISO OUT packets delivered per
    /// second by libusb (1000 for full-speed / HS bInterval=4; 8000 for
    /// HS bInterval=1 microframe devices).
    pub fn new(rate: u32, packets_per_sec: u32) -> Self {
        let nominal = (rate as i64 * 1_000_000) / packets_per_sec as i64;
        Self {
            accumulator: 0,
            nominal_millisamples: nominal,
            packets_per_sec,
            drift_correction_ppb: 0,
            packets_since_decay: 0,
        }
    }

    /// Reset the adapter to a new sample rate (e.g. after a format change).
    pub fn reset(&mut self, rate: u32) {
        self.accumulator = 0;
        self.nominal_millisamples = (rate as i64 * 1_000_000) / self.packets_per_sec as i64;
        self.drift_correction_ppb = 0;
        self.packets_since_decay = 0;
    }

    /// Return the number of samples to put in the current ISO packet, then
    /// advance the accumulator.
    ///
    /// If `feedback_millisamples` is `None` (no feedback received yet or
    /// device is synchronous/adaptive), the nominal rate is used.  When no
    /// feedback is available, the adaptive drift correction is applied.
    ///
    /// Returns at least 1 sample to prevent zero-length ISO packets.
    pub fn samples_this_packet(&mut self, feedback_millisamples: Option<i64>) -> u32 {
        let base = feedback_millisamples.unwrap_or(self.nominal_millisamples);
        // Apply drift correction only when running without device feedback.
        let delta = if feedback_millisamples.is_none() && self.drift_correction_ppb != 0 {
            // correction = nominal_ms * ppb / 1_000_000_000
            // To avoid overflow: nominal_ms ≤ ~96_000_000 (96kHz), ppb ≤ 100_000
            // → product ≤ 9.6e12, fits i64 comfortably.
            base + self.nominal_millisamples * self.drift_correction_ppb / 1_000_000_000
        } else {
            base
        };
        self.accumulator += delta;
        let n = (self.accumulator / 1_000_000).max(1) as i64;
        self.accumulator -= n * 1_000_000;

        // Tick decay counter.
        self.packets_since_decay += 1;
        if self.packets_since_decay >= DRIFT_DECAY_INTERVAL_PKTS {
            self.packets_since_decay = 0;
            self.decay_drift();
        }

        n as u32
    }

    /// Bump the drift correction upward (device FIFO underflow detected).
    ///
    /// Called from the ISO callback when USB packet errors occur while the
    /// host-side FrameQueue has plenty of data — indicating the device ran
    /// out of audio in its internal FIFO.
    pub fn bump_drift(&mut self, ppb: i64) {
        self.drift_correction_ppb = (self.drift_correction_ppb + ppb).clamp(-DRIFT_MAX_PPB, DRIFT_MAX_PPB);
    }

    /// Decay the correction toward zero by one step.
    fn decay_drift(&mut self) {
        if self.drift_correction_ppb > 0 {
            self.drift_correction_ppb = (self.drift_correction_ppb - DRIFT_DECAY_STEP_PPB).max(0);
        } else if self.drift_correction_ppb < 0 {
            self.drift_correction_ppb = (self.drift_correction_ppb + DRIFT_DECAY_STEP_PPB).min(0);
        }
    }

    /// Current drift correction in ppb (for diagnostics).
    pub fn drift_correction_ppb(&self) -> i64 {
        self.drift_correction_ppb
    }
}

// ---------------------------------------------------------------------------
// Feedback value parsers
// ---------------------------------------------------------------------------

/// Parse a UAC 1.0 Full-Speed feedback value (3-byte Q10.14, samples/frame).
///
/// Returns the rate in millisamples per packet (× 1 000 000):
/// `result / 1_000_000` = samples per 1 ms ISO packet.
pub fn parse_feedback_uac1(buf: &[u8]) -> Option<i64> {
    if buf.len() < 3 {
        return None;
    }
    // Q10.14: integer bits [23:14], fractional bits [13:0]
    let raw = (buf[0] as u32) | ((buf[1] as u32) << 8) | ((buf[2] as u32) << 16);
    // millisamples = raw * 1_000_000 / (1 << 14)
    let millisamples = (raw as i64) * 1_000_000 / (1 << 14);
    Some(millisamples)
}

/// Parse a UAC 2.0 High-Speed feedback value (4-byte Q16.16, samples/microframe).
///
/// Converts the microframe rate to the current ISO packet period and returns
/// millisamples:
/// `result / 1_000_000` = samples per ISO packet.
pub fn parse_feedback_uac2(buf: &[u8], packets_per_sec: u32) -> Option<i64> {
    if buf.len() < 4 {
        return None;
    }
    if packets_per_sec == 0 || packets_per_sec > 8_000 {
        return None;
    }
    let raw = u32::from_le_bytes([buf[0], buf[1], buf[2], buf[3]]) as i64;
    let microframes_per_packet = (8_000 / packets_per_sec) as i64;
    // Q16.16 samples/microframe -> samples/packet for the active OUT packet
    // period.  Example:
    // - 8000 pkt/s (125 us): multiply by 1
    // - 1000 pkt/s (1 ms):   multiply by 8
    let millisamples = raw * microframes_per_packet * 1_000_000 / (1 << 16);
    Some(millisamples)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rate_adapter_44100_1ms_averages_correctly() {
        let mut ra = RateAdapter::new(44100, 1000);
        // Over 1000 packets (1 second) total = 44100 samples
        let total: u32 = (0..1000).map(|_| ra.samples_this_packet(None)).sum();
        assert_eq!(total, 44100);
    }

    #[test]
    fn rate_adapter_44100_microframe_averages_correctly() {
        let mut ra = RateAdapter::new(44100, 8000);
        // Over 8000 packets (1 second) total = 44100 samples
        let total: u32 = (0..8000).map(|_| ra.samples_this_packet(None)).sum();
        assert_eq!(total, 44100);
    }

    #[test]
    fn rate_adapter_48000_1ms_is_flat() {
        let mut ra = RateAdapter::new(48000, 1000);
        for _ in 0..100 {
            assert_eq!(ra.samples_this_packet(None), 48);
        }
    }

    #[test]
    fn rate_adapter_48000_microframe_is_flat() {
        let mut ra = RateAdapter::new(48000, 8000);
        for _ in 0..100 {
            assert_eq!(ra.samples_this_packet(None), 6);
        }
    }

    #[test]
    fn rate_adapter_96000_1ms_is_flat() {
        let mut ra = RateAdapter::new(96000, 1000);
        for _ in 0..100 {
            assert_eq!(ra.samples_this_packet(None), 96);
        }
    }

    #[test]
    fn parse_feedback_uac2_48000_microframe_packet() {
        let raw = (6u32 << 16).to_le_bytes();
        assert_eq!(parse_feedback_uac2(&raw, 8_000), Some(6_000_000));
    }

    #[test]
    fn parse_feedback_uac2_48000_one_ms_packet() {
        let raw = (6u32 << 16).to_le_bytes();
        assert_eq!(parse_feedback_uac2(&raw, 1_000), Some(48_000_000));
    }

    #[test]
    fn drift_bump_increases_delivery_rate() {
        let mut ra = RateAdapter::new(44100, 8000);
        // Baseline: 44100 samples per 8000 packets.
        let baseline: u32 = (0..8000).map(|_| ra.samples_this_packet(None)).sum();
        assert_eq!(baseline, 44100);

        // Bump +2000 ppb (= +2 ppm).  Over 8000 packets (1 second) this
        // should deliver extra samples.  +2 ppm of 44100 = +0.0882 samples/s.
        // Due to integer accumulation this manifests as 1 extra sample over
        // many seconds.  Run for 80_000 packets (10 seconds) to see the effect.
        ra.reset(44100);
        ra.bump_drift(2_000);
        // Disable decay for this test by running in sub-decay-interval chunks.
        let mut total: u64 = 0;
        for _ in 0..10 {
            // Run 7999 packets (just under the decay interval).
            let chunk: u32 = (0..7999).map(|_| ra.samples_this_packet(None)).sum();
            total += chunk as u64;
            // Reset decay counter to prevent decay from firing.
            ra.packets_since_decay = 0;
        }
        // 79990 packets at nominal 44100/8000 = 44100*79990/8000 = 440_944.875
        // With +2 ppm: 440_944.875 * 1.000002 ≈ 440_945.76 → expect ≥ 440_945
        let nominal_total = 44100u64 * 79990 / 8000; // = 440_944 (truncated)
        assert!(
            total > nominal_total,
            "drift correction should increase total: got {} vs nominal {}",
            total,
            nominal_total,
        );
    }

    #[test]
    fn drift_correction_decays_to_zero() {
        let mut ra = RateAdapter::new(48000, 8000);
        ra.bump_drift(2_000);
        assert_eq!(ra.drift_correction_ppb(), 2_000);

        // Run enough packets to trigger multiple decay steps.
        // Each decay step removes 200 ppb.  2000/200 = 10 steps needed.
        // Each step triggers after 8000 packets → 80_000 packets total.
        for _ in 0..80_000 {
            ra.samples_this_packet(None);
        }
        assert_eq!(ra.drift_correction_ppb(), 0);
    }

    #[test]
    fn drift_correction_clamps_at_max() {
        let mut ra = RateAdapter::new(44100, 8000);
        // Bump way past the limit.
        for _ in 0..200 {
            ra.bump_drift(2_000);
        }
        assert_eq!(ra.drift_correction_ppb(), 100_000); // clamped at 100 ppm
    }

    #[test]
    fn drift_correction_ignored_when_feedback_present() {
        let mut ra = RateAdapter::new(48000, 8000);
        ra.bump_drift(50_000); // +50 ppm

        // With explicit feedback, drift correction should be bypassed.
        // 6_000_000 ms = exactly 6 samples/packet for 48kHz/8000pps.
        let n = ra.samples_this_packet(Some(6_000_000));
        assert_eq!(n, 6);
        // Second call to confirm no accumulation drift.
        let n2 = ra.samples_this_packet(Some(6_000_000));
        assert_eq!(n2, 6);
    }
}
