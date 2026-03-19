//! UAC 2.0 feedback endpoint reader and sample-rate adapter.
//!
//! # Feedback format
//!
//! UAC 2.0 High-Speed devices send a 4-byte Q16.16 fixed-point value on the
//! feedback IN endpoint every `2^(10-P)` microframes, where P is the endpoint's
//! `bRefresh` field.  The value represents the actual DAC clock rate in
//! **samples per microframe** (1 microframe = 125 µs).
//!
//! To convert to **samples per 1 ms frame** (our ISO packet granularity):
//! ```text
//! samples_per_ms = (feedback_raw / 2^16) * 8    // 8 microframes per ms
//! ```
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
//! accumulator += feedback_millisamples   // e.g. 44100000 for 44.1 kHz
//! n = accumulator / 1_000_000           // integer samples this packet
//! accumulator -= n * 1_000_000
//! ```
//!
//! Without feedback input the adapter returns the `nominal` rate (rate/1000),
//! which gives exactly the right average for synchronous and adaptive DACs.

/// Accumulator-based per-packet sample counter.
///
/// Resolves the fractional-samples-per-frame problem for 44.1 kHz family rates
/// (e.g. 44100 Hz → alternating 44/45 samples per 1 ms ISO packet) without
/// floating-point arithmetic in the RT path.
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
}

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
        }
    }

    /// Reset the adapter to a new sample rate (e.g. after a format change).
    pub fn reset(&mut self, rate: u32) {
        self.accumulator = 0;
        self.nominal_millisamples = (rate as i64 * 1_000_000) / self.packets_per_sec as i64;
    }

    /// Return the number of samples to put in the current ISO packet, then
    /// advance the accumulator.
    ///
    /// If `feedback_millisamples` is `None` (no feedback received yet or
    /// device is synchronous/adaptive), the nominal rate is used.
    ///
    /// Returns at least 1 sample to prevent zero-length ISO packets.
    pub fn samples_this_packet(&mut self, feedback_millisamples: Option<i64>) -> u32 {
        let delta = feedback_millisamples.unwrap_or(self.nominal_millisamples);
        self.accumulator += delta;
        let n = (self.accumulator / 1_000_000).max(1) as i64;
        self.accumulator -= n * 1_000_000;
        n as u32
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
/// Converts microframe rate to per-1ms-frame rate and returns millisamples:
/// `result / 1_000_000` = samples per 1 ms ISO packet.
pub fn parse_feedback_uac2(buf: &[u8]) -> Option<i64> {
    if buf.len() < 4 {
        return None;
    }
    let raw = u32::from_le_bytes([buf[0], buf[1], buf[2], buf[3]]) as i64;
    // Q16.16 samples/microframe → samples/ms: multiply by 8 (8 µf per ms)
    // millisamples = raw * 8 * 1_000_000 / (1 << 16)
    let millisamples = raw * 8 * 1_000_000 / (1 << 16);
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
}
