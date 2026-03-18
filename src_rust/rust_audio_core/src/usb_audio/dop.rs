//! DSD over PCM (DoP) encoding — DoP open standard v1.1.
//!
//! # Protocol overview
//!
//! A DoP-capable USB DAC advertises itself as a normal PCM device (e.g.
//! `S24_3LE` at 176 400 Hz for DSD64), but interprets the PCM payload as
//! DoP-encoded DSD.  Each 3-byte PCM "sample" carries:
//!
//! ```text
//! [DSD_byte_lo, DSD_byte_hi, marker]
//! ```
//!
//! where:
//! - `DSD_byte_lo` and `DSD_byte_hi` together carry 16 DSD single-bit samples
//!   (8 per byte, MSB-first per the DSD-over-PCM spec)
//! - `marker` alternates between `0x05` and `0xFA` on successive PCM frames
//!   (frames, not samples — all channels in one frame share the same marker).
//!   A receiver that sees neither `0x05` nor `0xFA` in the marker position
//!   treats the stream as regular PCM.
//!
//! # Rate relationship
//!
//! | DSD mode  | DSD bit rate   | PCM carrier rate  | PCM subframe size |
//! |-----------|---------------|-------------------|-------------------|
//! | DSD64     | 2 822 400 Hz  | 176 400 Hz        | 3 bytes (S24_3LE) |
//! | DSD128    | 5 644 800 Hz  | 352 800 Hz        | 3 bytes (S24_3LE) |
//!
//! # GStreamer interop
//!
//! GStreamer delivers DSD audio as `audio/x-dsd` with:
//! - `rate`     = DSD bit rate per channel (2 822 400 or 5 644 800)
//! - `channels` = channel count
//! - `format`   = `DSDU8` (8 DSD samples packed per byte, LSB-first in GStreamer)
//!
//! The appsink caps should be set to `audio/x-dsd` for DSD input.  The pusher
//! thread then calls [`DopEncoder::encode`] on each buffer before pushing the
//! output into the [`super::queue::FrameQueue`].

// ---------------------------------------------------------------------------
// Rate constants
// ---------------------------------------------------------------------------

/// DSD64 single-bit sample rate (2.8224 MHz).
pub const DSD64_RATE: u32 = 2_822_400;
/// DSD128 single-bit sample rate (5.6448 MHz).
pub const DSD128_RATE: u32 = 5_644_800;

/// Number of DSD single-bit samples carried per PCM frame per channel.
const DSD_SAMPLES_PER_FRAME: u32 = 16;

/// Compute the PCM carrier sample rate for a given DSD bit rate.
///
/// Each PCM frame carries [`DSD_SAMPLES_PER_FRAME`] = 16 DSD samples, so:
/// - DSD64  (2 822 400 Hz) → 176 400 Hz
/// - DSD128 (5 644 800 Hz) → 352 800 Hz
///
/// Returns `None` for unrecognised rates.
pub fn dop_pcm_rate(dsd_rate: u32) -> Option<u32> {
    if dsd_rate % DSD_SAMPLES_PER_FRAME == 0 {
        Some(dsd_rate / DSD_SAMPLES_PER_FRAME)
    } else {
        None
    }
}

/// Return `true` when `rate` is a known DSD bit rate supported by DoP.
pub fn is_dsd_rate(rate: u32) -> bool {
    matches!(rate, DSD64_RATE | DSD128_RATE)
}

// ---------------------------------------------------------------------------
// DopEncoder
// ---------------------------------------------------------------------------

/// Stateful DoP encoder: packs raw DSD bytes into S24_3LE PCM frames.
///
/// Maintains a single marker-byte toggle across successive calls so that the
/// alternation is preserved across GStreamer buffer boundaries.
///
/// # Thread safety
///
/// `DopEncoder` is not `Sync`.  Wrap in a `Mutex` if sharing between threads.
pub struct DopEncoder {
    /// Current marker byte — alternates between `0x05` and `0xFA`.
    marker: u8,
    /// Channel count of the output stream.
    pub channels: usize,
}

impl DopEncoder {
    /// Create a new encoder for an output stream with `channels` channels.
    pub fn new(channels: usize) -> Self {
        Self { marker: 0x05, channels }
    }

    /// Reset the marker sequence (call when the stream is restarted).
    pub fn reset(&mut self) {
        self.marker = 0x05;
    }

    /// Encode a slice of interleaved DSD bytes into DoP S24_3LE PCM frames.
    ///
    /// # Input format
    ///
    /// GStreamer `audio/x-dsd, format=DSDU8`: interleaved bytes, one byte per
    /// channel per 8-sample "super-sample".  For stereo: `L0 R0 L1 R1 …`
    ///
    /// # Output format
    ///
    /// Interleaved S24_3LE: 3 bytes per channel per PCM frame.
    /// Each PCM frame = `channels × 3` bytes.
    /// `[DSD_lo, DSD_hi, marker]` per channel, marker same for all channels in
    /// the frame.
    ///
    /// # Panics
    ///
    /// Does not panic.  If `dsd.len()` is not a multiple of `2 × channels`,
    /// the trailing incomplete frame is silently discarded.
    pub fn encode(&mut self, dsd: &[u8]) -> Vec<u8> {
        // Each PCM frame consumes 2 DSD bytes per channel.
        let frame_dsd_bytes = 2 * self.channels;
        if frame_dsd_bytes == 0 {
            return Vec::new();
        }
        let n_frames = dsd.len() / frame_dsd_bytes;
        let mut out = vec![0u8; n_frames * self.channels * 3];

        for f in 0..n_frames {
            let marker = self.marker;
            for ch in 0..self.channels {
                let src_base = f * frame_dsd_bytes + ch * 2;
                let dst_base = (f * self.channels + ch) * 3;
                out[dst_base]     = dsd[src_base];       // DSD byte 1 (8 samples)
                out[dst_base + 1] = dsd[src_base + 1];   // DSD byte 2 (8 samples)
                out[dst_base + 2] = marker;               // DoP marker
            }
            // Toggle marker after each complete frame.
            self.marker = if self.marker == 0x05 { 0xFA } else { 0x05 };
        }
        out
    }

    /// Detect whether a buffer of S24_3LE data looks like DoP.
    ///
    /// Inspects the marker byte (byte index 2) of the first few PCM samples.
    /// Returns `true` if all checked samples have a marker of `0x05` or `0xFA`.
    ///
    /// Useful for verifying that a device is receiving DoP correctly.
    pub fn detect_dop_marker(pcm_s24_3le: &[u8], channels: usize) -> bool {
        if channels == 0 || pcm_s24_3le.len() < channels * 3 {
            return false;
        }
        let check_frames = (pcm_s24_3le.len() / (channels * 3)).min(8);
        for f in 0..check_frames {
            // Only check the first channel's marker byte per frame.
            let marker_pos = f * channels * 3 + 2;
            match pcm_s24_3le.get(marker_pos) {
                Some(0x05) | Some(0xFA) => {}
                _ => return false,
            }
        }
        true
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dop_pcm_rate_dsd64() {
        assert_eq!(dop_pcm_rate(DSD64_RATE), Some(176_400));
    }

    #[test]
    fn dop_pcm_rate_dsd128() {
        assert_eq!(dop_pcm_rate(DSD128_RATE), Some(352_800));
    }

    #[test]
    fn dop_pcm_rate_unknown() {
        assert_eq!(dop_pcm_rate(44_100), None);
    }

    #[test]
    fn encode_stereo_two_frames() {
        let mut enc = DopEncoder::new(2);
        // 2 channels × 2 DSD bytes/frame × 2 frames = 8 input bytes
        let dsd: Vec<u8> = vec![0xAA, 0xBB, 0xCC, 0xDD, 0x11, 0x22, 0x33, 0x44];
        let out = enc.encode(&dsd);
        // 2 frames × 2 channels × 3 bytes = 12 bytes
        assert_eq!(out.len(), 12);
        // Frame 0, channel 0: [0xAA, 0xBB, 0x05]
        assert_eq!(&out[0..3], &[0xAA, 0xBB, 0x05]);
        // Frame 0, channel 1: [0xCC, 0xDD, 0x05]
        assert_eq!(&out[3..6], &[0xCC, 0xDD, 0x05]);
        // Frame 1, channel 0: [0x11, 0x22, 0xFA]
        assert_eq!(&out[6..9], &[0x11, 0x22, 0xFA]);
        // Frame 1, channel 1: [0x33, 0x44, 0xFA]
        assert_eq!(&out[9..12], &[0x33, 0x44, 0xFA]);
    }

    #[test]
    fn encode_marker_alternates_across_calls() {
        let mut enc = DopEncoder::new(1);
        let dsd = vec![0x01, 0x02]; // 1 frame
        let out1 = enc.encode(&dsd);
        let out2 = enc.encode(&dsd);
        // First call: marker 0x05; second call: marker 0xFA
        assert_eq!(out1[2], 0x05);
        assert_eq!(out2[2], 0xFA);
    }

    #[test]
    fn detect_dop_recognises_valid_stream() {
        let mut enc = DopEncoder::new(2);
        let dsd = vec![0u8; 32]; // 4 frames × 2ch
        let pcm = enc.encode(&dsd);
        assert!(DopEncoder::detect_dop_marker(&pcm, 2));
    }

    #[test]
    fn detect_dop_rejects_plain_pcm() {
        // All-zeros buffer: marker bytes would be 0x00 (neither 0x05 nor 0xFA)
        let plain = vec![0u8; 48];
        assert!(!DopEncoder::detect_dop_marker(&plain, 2));
    }
}
