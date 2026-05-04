//! Shared PCM sample-format helpers for the native_transport pipeline.
//!
//! These were previously copied across `controller.rs`, `processor.rs` and
//! `native_dsp.rs` (three near-identical `sample_to_f64` impls, two
//! `sample_to_f32`, three inline `bytes_per_sample` match arms).  Keeping
//! them in one place avoids the conversion drift that hit us during the
//! 1.9.5.4 AAC noise hunt — every byte-layout decision lives in one file.
//!
//! All helpers are `pub(crate)` and zero-cost; the originals were
//! `#[inline]`-able match expressions and stay that way here.

use super::processor::PcmSampleFormat;

/// Full-scale magnitude for f↔i16 PCM mapping (2^15).
///
/// The encoded value range is `[-PCM_S16_SCALE, PCM_S16_SCALE - 1]`
/// (i.e. `[-32768, 32767]`). Keeping the scale as the power-of-two means
/// each conversion direction can choose between full-symmetric (multiply by
/// scale + clamp at scale - 1) or no-clamp (multiply by scale - 1) without
/// a fresh magic number.
pub(crate) const PCM_S16_SCALE: f64 = 32_768.0;
/// Full-scale magnitude for f↔i24 PCM mapping (2^23).
pub(crate) const PCM_S24_SCALE: f64 = 8_388_608.0;
/// Full-scale magnitude for f↔i32 PCM mapping (2^31).
pub(crate) const PCM_S32_SCALE: f64 = 2_147_483_648.0;

/// Number of bytes one sample occupies in `format`.
#[inline]
pub(crate) const fn bytes_per_sample(format: PcmSampleFormat) -> usize {
    match format {
        PcmSampleFormat::S16LE => 2,
        PcmSampleFormat::S24_3LE => 3,
        PcmSampleFormat::S24LE | PcmSampleFormat::S32LE => 4,
        PcmSampleFormat::F32LE => 4,
        PcmSampleFormat::F64LE => 8,
    }
}

/// Map signed integer bit depth to the canonical `PcmSampleFormat` for that
/// depth.  Anything ≤16 → S16LE, exactly 24 → S24_3LE, otherwise S32LE.
#[inline]
pub(crate) fn bits_per_sample_to_pcm_format(bits: u32) -> PcmSampleFormat {
    match bits {
        0..=16 => PcmSampleFormat::S16LE,
        24 => PcmSampleFormat::S24_3LE,
        _ => PcmSampleFormat::S32LE,
    }
}

/// Map a `PcmSampleFormat` to the bit depth the USB sink should request so
/// the iso ring stride matches the slab byte layout.  Float formats round
/// up to 32 since the wire layout is identical to S32LE width.
#[inline]
pub(crate) fn pcm_format_to_bit_depth(format: PcmSampleFormat) -> u8 {
    match format {
        PcmSampleFormat::S16LE => 16,
        PcmSampleFormat::S24_3LE | PcmSampleFormat::S24LE => 24,
        PcmSampleFormat::S32LE | PcmSampleFormat::F32LE | PcmSampleFormat::F64LE => 32,
    }
}

/// Parse a GStreamer-style format string ("S24_3LE", "F32LE", ...) into a
/// `PcmSampleFormat`.  BE variants map to the LE equivalent — the rest of
/// the pipeline is little-endian only.
pub(crate) fn pcm_format_from_gst_format(format: &str) -> Result<PcmSampleFormat, String> {
    match format {
        "S16LE" | "S16BE" | "U16LE" | "U16BE" => Ok(PcmSampleFormat::S16LE),
        "S24_3LE" | "S24_3BE" => Ok(PcmSampleFormat::S24_3LE),
        "S24LE" | "S24BE" => Ok(PcmSampleFormat::S24LE),
        "S32LE" | "S32BE" => Ok(PcmSampleFormat::S32LE),
        "F32LE" | "F32BE" => Ok(PcmSampleFormat::F32LE),
        "F64LE" | "F64BE" => Ok(PcmSampleFormat::F64LE),
        other => Err(format!(
            "native transport: unsupported target gst format '{other}'"
        )),
    }
}

/// Decode one sample's worth of bytes (length ≥ `bytes_per_sample(format)`)
/// to a normalised f32 in [-1.0, 1.0].
#[inline]
pub(crate) fn sample_to_f32(bytes: &[u8], format: PcmSampleFormat) -> f32 {
    match format {
        PcmSampleFormat::S16LE => {
            i16::from_le_bytes([bytes[0], bytes[1]]) as f32 / PCM_S16_SCALE as f32
        }
        PcmSampleFormat::S24_3LE => {
            let raw = (bytes[0] as i32)
                | ((bytes[1] as i32) << 8)
                | ((bytes[2] as i8 as i32) << 16);
            raw as f32 / PCM_S24_SCALE as f32
        }
        PcmSampleFormat::S24LE | PcmSampleFormat::S32LE => {
            i32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]) as f32
                / PCM_S32_SCALE as f32
        }
        PcmSampleFormat::F32LE => {
            f32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]])
        }
        PcmSampleFormat::F64LE => {
            f64::from_le_bytes([
                bytes[0], bytes[1], bytes[2], bytes[3],
                bytes[4], bytes[5], bytes[6], bytes[7],
            ]) as f32
        }
    }
}

/// f64 variant of [`sample_to_f32`] — used by the LUFS meter and DSP graph
/// where double precision matters for filter stability.
#[inline]
pub(crate) fn sample_to_f64(bytes: &[u8], format: PcmSampleFormat) -> f64 {
    match format {
        PcmSampleFormat::S16LE => {
            i16::from_le_bytes([bytes[0], bytes[1]]) as f64 / PCM_S16_SCALE
        }
        PcmSampleFormat::S24_3LE => {
            let raw = (bytes[0] as i32)
                | ((bytes[1] as i32) << 8)
                | ((bytes[2] as i8 as i32) << 16);
            raw as f64 / PCM_S24_SCALE
        }
        PcmSampleFormat::S24LE | PcmSampleFormat::S32LE => {
            i32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]) as f64 / PCM_S32_SCALE
        }
        PcmSampleFormat::F32LE => {
            f32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]) as f64
        }
        PcmSampleFormat::F64LE => {
            f64::from_le_bytes([
                bytes[0], bytes[1], bytes[2], bytes[3],
                bytes[4], bytes[5], bytes[6], bytes[7],
            ])
        }
    }
}

/// Write the low 24 bits of `value` to `out` in little-endian order
/// (matches the S24_3LE wire layout — three bytes, signed).
#[inline]
pub(crate) fn write_i24_le(value: i32, out: &mut Vec<u8>) {
    out.push(value as u8);
    out.push((value >> 8) as u8);
    out.push((value >> 16) as u8);
}

/// Write a single f32 sample (clamped to [-1.0, 1.0]) to `out` encoded as
/// `format`.  The inverse of [`sample_to_f32`] — round-trip is lossy for
/// integer formats but never loses bit-perfect for matched widths.
#[inline]
pub(crate) fn write_f32_as(v: f32, format: PcmSampleFormat, out: &mut Vec<u8>) {
    let v = v.clamp(-1.0, 1.0);
    // Multiply by `SCALE - 1` (max-positive); since `v` is clamped to
    // [-1, 1] this stays inside the integer range without a second clamp.
    match format {
        PcmSampleFormat::S16LE => {
            let s = (v * (PCM_S16_SCALE as f32 - 1.0)).round() as i16;
            out.extend_from_slice(&s.to_le_bytes());
        }
        PcmSampleFormat::S24_3LE => {
            let s = (v * (PCM_S24_SCALE as f32 - 1.0)).round() as i32;
            write_i24_le(s, out);
        }
        PcmSampleFormat::S24LE | PcmSampleFormat::S32LE => {
            let s = (v * (PCM_S32_SCALE as f32 - 1.0)).round() as i32;
            out.extend_from_slice(&s.to_le_bytes());
        }
        PcmSampleFormat::F32LE => {
            out.extend_from_slice(&v.to_le_bytes());
        }
        PcmSampleFormat::F64LE => {
            out.extend_from_slice(&(v as f64).to_le_bytes());
        }
    }
}
