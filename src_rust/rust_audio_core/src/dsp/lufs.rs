/// K-weighted LUFS meter (EBU R128 / ITU-R BS.1770-4).
///
/// Processing chain per sample:
///   1. Stage-1 biquad  — high-shelf pre-filter (+4 dB, f0 ≈ 1682 Hz)
///   2. Stage-2 biquad  — RLB high-pass filter  (f0 ≈ 38 Hz)
///   3. Accumulate mean-square power into 100 ms blocks
///   4. Blocks feed ring buffers for M (400 ms), S (3 s), I (gated all-time)
///      and LRA (95th − 10th percentile of S history, 30 s window)
///
/// Filter coefficients are derived via bilinear transform from the analog
/// prototype defined in ITU-R BS.1770-4, Annex 1, so they are correct at
/// any sample rate (44.1, 48, 88.2, 96, 192 kHz, etc.).
use std::collections::VecDeque;

// ---------------------------------------------------------------------------
// K-weighting biquad coefficients
// ---------------------------------------------------------------------------

/// Maximum channels supported by the fixed-size filter state arrays.
const MAX_CHANNELS: usize = 8;

/// Direct-form II transposed biquad coefficients.
/// Transfer function: H(z) = (b0 + b1·z⁻¹ + b2·z⁻²) / (1 + a1·z⁻¹ + a2·z⁻²)
#[derive(Clone, Copy, Debug)]
struct BiquadCoeffs {
    b0: f64,
    b1: f64,
    b2: f64,
    a1: f64,
    a2: f64,
}

impl BiquadCoeffs {
    /// Stage 1: high-shelf pre-filter.
    /// Compensates for the acoustic effect of the head above ~1.7 kHz.
    fn k_stage1(rate: f64) -> Self {
        // Analog prototype parameters (BS.1770-4, Annex 1, Table 1)
        let db: f64 = 3.999_843_853_973_347;
        let f0: f64 = 1_681.974_450_955_533;
        let q: f64 = 0.707_175_236_955_419_6;

        let k = (std::f64::consts::PI * f0 / rate).tan();
        let vh = 10.0_f64.powf(db / 20.0);
        let vb = vh.sqrt();
        let a0 = 1.0 + k / q + k * k;

        Self {
            b0: (vh + vb * k / q + k * k) / a0,
            b1: 2.0 * (k * k - vh) / a0,
            b2: (vh - vb * k / q + k * k) / a0,
            a1: 2.0 * (k * k - 1.0) / a0,
            a2: (1.0 - k / q + k * k) / a0,
        }
    }

    /// Stage 2: RLB high-pass weighting filter.
    /// Attenuates bass content below ~38 Hz to prevent low-frequency bias.
    fn k_stage2(rate: f64) -> Self {
        // Analog prototype parameters (BS.1770-4, Annex 1, Table 2)
        let f0: f64 = 38.135_470_876_024_44;
        let q: f64 = 0.500_327_037_323_877_3;

        let k = (std::f64::consts::PI * f0 / rate).tan();
        let a0 = 1.0 + k / q + k * k;

        Self {
            b0: 1.0 / a0,
            b1: -2.0 / a0,
            b2: 1.0 / a0,
            a1: 2.0 * (k * k - 1.0) / a0,
            a2: (1.0 - k / q + k * k) / a0,
        }
    }
}

// ---------------------------------------------------------------------------
// Per-channel biquad state
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Default, Debug)]
struct BiquadState {
    x1: f64,
    x2: f64,
    y1: f64,
    y2: f64,
}

impl BiquadState {
    #[inline]
    fn process(&mut self, x: f64, c: &BiquadCoeffs) -> f64 {
        let y = c.b0 * x + c.b1 * self.x1 + c.b2 * self.x2 - c.a1 * self.y1 - c.a2 * self.y2;
        self.x2 = self.x1;
        self.x1 = x;
        self.y2 = self.y1;
        self.y1 = y;
        y
    }
}

// ---------------------------------------------------------------------------
// LUFS display values (shared with the main thread)
// ---------------------------------------------------------------------------

const NEG_INF: f64 = -70.0;

/// Loudness values polled by the Python UI thread.
#[repr(C)]
#[derive(Clone, Debug)]
pub struct LufsValues {
    /// Momentary LUFS  (≈400 ms window).  f32::NEG_INFINITY when unavailable.
    pub momentary: f32,
    /// Short-term LUFS (≈3 s window).    f32::NEG_INFINITY when unavailable.
    pub short_term: f32,
    /// Integrated LUFS (gated, all-time). f32::NEG_INFINITY when unavailable.
    pub integrated: f32,
    /// Loudness Range LU (≈30 s history). 0.0 when unavailable.
    pub lra: f32,
    /// Dynamic Range = peak_dBFS − rms_dBFS over ≈4 s window. 0.0 when unavailable.
    pub dr: f32,
}

/// Display floor for the meter levels (dBFS). Finite so the smoothing
/// math stays well-defined; anything at or below this reads as silence.
pub const LEVEL_DISPLAY_FLOOR_DB: f32 = -100.0;

/// One ~16 ms display sub-block of per-channel meter levels, already
/// ballistic (instant peak attack, 60 dB/s fall; fast-attack RMS) and
/// stamped with the track-absolute position of its last sample. The
/// engine holds these until the playback clock reaches `pos_s`, so the
/// meter shows what is audible, not what was just decoded — and slab-
/// granular decoding no longer collapses several sub-blocks into one
/// visible update.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct LevelFrame {
    pub pos_s: f64,
    pub peak_l: f32,
    pub rms_l: f32,
    pub peak_r: f32,
    pub rms_r: f32,
}

/// Payload behind the shared LUFS mutex: latest measurement values plus
/// the queue of position-stamped display frames awaiting release.
#[derive(Debug, Default)]
pub struct LufsShared {
    pub values: LufsValues,
    pub level_frames: VecDeque<LevelFrame>,
}

/// Cap on queued display frames (~65 s at 16 ms) — decode normally runs
/// less than a couple of seconds ahead of playback; this is a safety
/// valve, not a working depth.
pub const LEVEL_FRAME_QUEUE_CAP: usize = 4096;

impl Default for LufsValues {
    fn default() -> Self {
        Self {
            momentary: f32::NEG_INFINITY,
            short_term: f32::NEG_INFINITY,
            integrated: f32::NEG_INFINITY,
            lra: 0.0,
            dr: 0.0,
        }
    }
}

// ---------------------------------------------------------------------------
// Internal processing state
// ---------------------------------------------------------------------------

/// 100 ms blocks — a good trade-off between resolution and memory.
/// Block count per window: M = 4 (400 ms), S = 30 (3 s), LRA = 300 (30 s).
/// DR accumulates over the whole track (no cap), like Integrated LUFS.
const M_BLOCKS: usize = 4;
const S_BLOCKS: usize = 30;
const LRA_BLOCKS: usize = 300;

/// Absolute gating threshold (BS.1770-4 §3.6).
const GATE_ABS_LUFS: f64 = -70.0;

#[allow(dead_code)]
pub(crate) struct LufsState {
    sample_rate: u32,
    channels: usize,

    // K-weighting filter state: fixed-size arrays avoid heap indirection and
    // let the compiler unroll/vectorize the inner channel loop.
    filt1: [BiquadState; MAX_CHANNELS],
    filt2: [BiquadState; MAX_CHANNELS],
    coeffs1: BiquadCoeffs,
    coeffs2: BiquadCoeffs,

    // Current 100 ms block accumulator (K-weighted, for LUFS)
    block_sum: f64, // sum of (y_L² + y_R²) per frame
    block_count: usize,
    block_target: usize, // frames per 100 ms block

    // Current 100 ms block accumulator (unweighted, for DR)
    block_peak: f64,      // max |sample| in current block
    block_power_sum: f64, // sum of sample² across all channels

    // Per-channel (L/R) display sub-block accumulators for the meter bars.
    // ~16 ms (matching the spectrum frame cadence) so the bars react like
    // a hardware PPM, decoupled from the
    // 100 ms measurement blocks (shrinking those would change LUFS/DR
    // semantics).
    ch_peak: [f64; 2],      // max |sample| per channel in current sub-block
    ch_power_sum: [f64; 2], // sum of sample² per channel
    disp_count: usize,      // frames in the current sub-block
    disp_target: usize,     // frames per ~16 ms sub-block
    // Smoothed display state (ballistics applied per sub-block)
    disp_rms_db: [f32; 2],
    disp_peak_db: [f32; 2],
    // Track-absolute position stamping for display frames
    start_offset_s: f64, // seek target of this decode run (0 for track start)
    total_frames: u64,   // frames processed since configure/reset
    // Finished display frames awaiting hand-off to the shared queue
    pending_level_frames: Vec<LevelFrame>,

    // Ring buffers of per-block LUFS values
    m_buf: VecDeque<f64>,   // last M_BLOCKS  blocks
    s_buf: VecDeque<f64>,   // last S_BLOCKS  blocks
    lra_buf: VecDeque<f64>, // last LRA_BLOCKS blocks

    // Integrated loudness gated accumulator
    int_lin_sum: f64,
    int_count: u64,

    // Whole-track DR accumulators (reset on track change, like Integrated LUFS)
    dr_peak_sq_sum: f64, // Σ(block_peak²) over all blocks
    dr_power_sum: f64,   // Σ(block_mean_power) over all blocks
    dr_block_count: u64, // number of blocks with signal

    // Cached display values (written by audio thread, read by main thread)
    pub values: LufsValues,
}

impl LufsState {
    pub(crate) fn new() -> Self {
        let rate = 48_000u32;
        let channels = 2usize;
        Self {
            sample_rate: rate,
            channels,
            filt1: [BiquadState::default(); MAX_CHANNELS],
            filt2: [BiquadState::default(); MAX_CHANNELS],
            coeffs1: BiquadCoeffs::k_stage1(rate as f64),
            coeffs2: BiquadCoeffs::k_stage2(rate as f64),
            block_sum: 0.0,
            block_count: 0,
            block_target: rate as usize / 10, // 100 ms
            block_peak: 0.0,
            block_power_sum: 0.0,
            ch_peak: [0.0; 2],
            ch_power_sum: [0.0; 2],
            disp_count: 0,
            disp_target: rate as usize * 16 / 1000, // 16 ms
            disp_rms_db: [LEVEL_DISPLAY_FLOOR_DB; 2],
            disp_peak_db: [LEVEL_DISPLAY_FLOOR_DB; 2],
            start_offset_s: 0.0,
            total_frames: 0,
            pending_level_frames: Vec::new(),
            m_buf: VecDeque::new(),
            s_buf: VecDeque::new(),
            lra_buf: VecDeque::new(),
            int_lin_sum: 0.0,
            int_count: 0,
            dr_peak_sq_sum: 0.0,
            dr_power_sum: 0.0,
            dr_block_count: 0,
            values: LufsValues::default(),
        }
    }

    pub(crate) fn update_rate_channels(&mut self, rate: u32, channels: usize) {
        if rate == self.sample_rate && channels == self.channels {
            return;
        }
        self.sample_rate = rate;
        self.channels = channels;
        self.coeffs1 = BiquadCoeffs::k_stage1(rate as f64);
        self.coeffs2 = BiquadCoeffs::k_stage2(rate as f64);
        self.filt1 = [BiquadState::default(); MAX_CHANNELS];
        self.filt2 = [BiquadState::default(); MAX_CHANNELS];
        self.block_target = (rate as usize).max(1) / 10;
        self.disp_target = ((rate as usize).max(1) * 16 / 1000).max(1);
        // Flush the in-progress block so we don't mix old and new rates.
        self.block_sum = 0.0;
        self.block_count = 0;
        self.block_peak = 0.0;
        self.block_power_sum = 0.0;
        self.ch_peak = [0.0; 2];
        self.ch_power_sum = [0.0; 2];
        self.disp_count = 0;
    }

    /// Process a slice of interleaved F64LE samples (read-only tap).
    pub(crate) fn process(&mut self, samples: &[f64]) {
        let ch = self.channels.min(MAX_CHANNELS);
        if ch == 0 || samples.is_empty() {
            return;
        }
        let frames = samples.len() / self.channels;
        // Copy coefficients (both are Copy) so the inner loop only borrows
        // self.filt1/filt2 and the scalar accumulators — no aliasing with coeffs.
        let coeffs1 = self.coeffs1;
        let coeffs2 = self.coeffs2;

        for i in 0..frames {
            let base = i * self.channels;
            // K-weight each channel, accumulate sum of squares (BS.1770 eq.)
            let mut sum_sq = 0.0f64;
            for c in 0..ch {
                let x = samples[base + c];
                let y1 = self.filt1[c].process(x, &coeffs1);
                let y2 = self.filt2[c].process(y1, &coeffs2);
                sum_sq += y2 * y2;
                // Unweighted: track peak and power for DR
                let ax = x.abs();
                if ax > self.block_peak {
                    self.block_peak = ax;
                }
                self.block_power_sum += x * x;
                // Per-channel levels for the meter bars (first two channels)
                if c < 2 {
                    if ax > self.ch_peak[c] {
                        self.ch_peak[c] = ax;
                    }
                    self.ch_power_sum[c] += x * x;
                }
            }
            self.block_sum += sum_sq;
            self.block_count += 1;
            self.disp_count += 1;
            self.total_frames += 1;

            if self.disp_count >= self.disp_target.max(1) {
                self.flush_display_block();
            }
            if self.block_count >= self.block_target {
                self.flush_block();
            }
        }
    }

    /// Set the track-absolute time of the first frame this decode run will
    /// process (the seek target). Survives clear()/reset() — it describes
    /// the run, not the accumulator state.
    pub(crate) fn set_start_offset(&mut self, start_offset_s: f64) {
        self.start_offset_s = start_offset_s;
    }

    /// Hand off finished display frames (called by the processor while it
    /// already holds the shared lock).
    pub(crate) fn drain_level_frames(&mut self) -> std::vec::Drain<'_, LevelFrame> {
        self.pending_level_frames.drain(..)
    }

    /// Flush the ~16 ms display sub-block: apply PPM-style ballistics and
    /// publish the per-channel meter levels. Kept separate from
    /// flush_block() so display responsiveness never touches the LUFS/DR
    /// measurement chain.
    fn flush_display_block(&mut self) {
        if self.disp_count == 0 {
            return;
        }
        let n = self.disp_count as f64;
        let ch = self.channels.min(2).max(1);
        for c in 0..ch {
            let raw_peak = if self.ch_peak[c] > 1e-10 {
                (20.0 * self.ch_peak[c].log10()) as f32
            } else {
                LEVEL_DISPLAY_FLOOR_DB
            };
            let mean = self.ch_power_sum[c] / n;
            let raw_rms = if mean > 0.0 {
                (10.0 * mean.log10()) as f32
            } else {
                LEVEL_DISPLAY_FLOOR_DB
            };
            // RMS: fast attack, moderate release (per 16 ms step; same
            // time constants as the original 0.6/0.35 per 20 ms).
            let alpha = if raw_rms > self.disp_rms_db[c] { 0.52 } else { 0.29 };
            self.disp_rms_db[c] += alpha * (raw_rms - self.disp_rms_db[c]);
            // Peak: instant attack, 0.96 dB per 16 ms fall (= 60 dB/s).
            if raw_peak > self.disp_peak_db[c] {
                self.disp_peak_db[c] = raw_peak;
            } else {
                self.disp_peak_db[c] = (self.disp_peak_db[c] - 0.96)
                    .max(raw_peak)
                    .max(LEVEL_DISPLAY_FLOOR_DB);
            }
        }
        let (peak_r, rms_r) = if self.channels >= 2 {
            (self.disp_peak_db[1], self.disp_rms_db[1])
        } else {
            (self.disp_peak_db[0], self.disp_rms_db[0])
        };
        let pos_s = if self.sample_rate > 0 {
            self.start_offset_s + self.total_frames as f64 / self.sample_rate as f64
        } else {
            self.start_offset_s
        };
        self.pending_level_frames.push(LevelFrame {
            pos_s,
            peak_l: self.disp_peak_db[0],
            rms_l: self.disp_rms_db[0],
            peak_r,
            rms_r,
        });
        self.ch_peak = [0.0; 2];
        self.ch_power_sum = [0.0; 2];
        self.disp_count = 0;
    }

    fn flush_block(&mut self) {
        if self.block_count == 0 {
            return;
        }
        // mean_sq = (1/N) · Σ(y_L² + y_R²) — summed, not averaged, over channels
        let mean_sq = self.block_sum / self.block_count as f64;
        // BS.1770 loudness formula: L = -0.691 + 10·log₁₀(mean_sq)
        let block_lufs = if mean_sq > 0.0 {
            -0.691 + 10.0 * mean_sq.log10()
        } else {
            NEG_INF
        };

        // Flush DR accumulators for this block
        let block_peak = self.block_peak;
        let block_power = if self.block_count > 0 {
            self.block_power_sum / (self.block_count * self.channels.max(1)) as f64
        } else {
            0.0
        };

        self.block_sum = 0.0;
        self.block_count = 0;
        self.block_peak = 0.0;
        self.block_power_sum = 0.0;

        // Feed ring buffers
        push_capped(&mut self.m_buf, block_lufs, M_BLOCKS);
        push_capped(&mut self.s_buf, block_lufs, S_BLOCKS);
        push_capped(&mut self.lra_buf, block_lufs, LRA_BLOCKS);

        // DR: accumulate peak² and mean power over the whole track.
        // RMS-of-peaks method (Pleasurize Music Foundation DR meter standard).
        if block_peak > 0.0 && block_power > 0.0 {
            self.dr_peak_sq_sum += block_peak * block_peak;
            self.dr_power_sum += block_power;
            self.dr_block_count += 1;
        }

        // Integrated: absolute gate
        if block_lufs > GATE_ABS_LUFS {
            // Convert back to linear power for accumulation
            self.int_lin_sum += 10.0_f64.powf((block_lufs + 0.691) / 10.0);
            self.int_count += 1;
        }

        // Recompute display values
        self.values.momentary = power_mean_lufs(&self.m_buf) as f32;
        self.values.short_term = power_mean_lufs(&self.s_buf) as f32;
        self.values.integrated = if self.int_count > 0 {
            let mean = self.int_lin_sum / self.int_count as f64;
            (-0.691 + 10.0 * mean.log10()) as f32
        } else {
            f32::NEG_INFINITY
        };
        self.values.lra = compute_lra(&self.lra_buf) as f32;
        self.values.dr =
            compute_dr(self.dr_peak_sq_sum, self.dr_power_sum, self.dr_block_count) as f32;
    }

    pub(crate) fn reset(&mut self) {
        self.filt1 = [BiquadState::default(); MAX_CHANNELS];
        self.filt2 = [BiquadState::default(); MAX_CHANNELS];
        self.block_sum = 0.0;
        self.block_count = 0;
        self.block_peak = 0.0;
        self.block_power_sum = 0.0;
        self.ch_peak = [0.0; 2];
        self.ch_power_sum = [0.0; 2];
        self.disp_count = 0;
        self.disp_rms_db = [LEVEL_DISPLAY_FLOOR_DB; 2];
        self.disp_peak_db = [LEVEL_DISPLAY_FLOOR_DB; 2];
        self.total_frames = 0;
        self.pending_level_frames.clear();
        self.m_buf.clear();
        self.s_buf.clear();
        self.lra_buf.clear();
        self.int_lin_sum = 0.0;
        self.int_count = 0;
        self.dr_peak_sq_sum = 0.0;
        self.dr_power_sum = 0.0;
        self.dr_block_count = 0;
        self.values = LufsValues::default();
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn push_capped(buf: &mut VecDeque<f64>, val: f64, cap: usize) {
    buf.push_back(val);
    while buf.len() > cap {
        buf.pop_front();
    }
}

/// Power-domain mean of a ring buffer of per-block LUFS values.
/// L = -0.691 + 10·log₁₀( mean(10^((l_i + 0.691)/10)) )
fn power_mean_lufs(buf: &VecDeque<f64>) -> f64 {
    let valid: Vec<f64> = buf.iter().copied().filter(|&v| v > NEG_INF).collect();
    if valid.is_empty() {
        return f64::NEG_INFINITY;
    }
    let lin_sum: f64 = valid
        .iter()
        .map(|&v| 10.0_f64.powf((v + 0.691) / 10.0))
        .sum();
    let mean = lin_sum / valid.len() as f64;
    if mean > 0.0 {
        -0.691 + 10.0 * mean.log10()
    } else {
        f64::NEG_INFINITY
    }
}

/// DR = 10·log₁₀(mean_peak²) − 10·log₁₀(mean_power)
///
/// Whole-track accumulation (like Integrated LUFS), reset on track change.
/// Matches the Pleasurize Music Foundation DR meter standard (RMS-of-peaks).
fn compute_dr(peak_sq_sum: f64, power_sum: f64, block_count: u64) -> f64 {
    if block_count < 4 {
        return 0.0;
    }
    let mean_peak_sq = peak_sq_sum / block_count as f64;
    let mean_power = power_sum / block_count as f64;
    if mean_peak_sq <= 0.0 || mean_power <= 0.0 {
        return 0.0;
    }
    (10.0 * mean_peak_sq.log10() - 10.0 * mean_power.log10()).max(0.0)
}

/// LRA = 95th − 10th percentile of per-block S values.
fn compute_lra(buf: &VecDeque<f64>) -> f64 {
    let mut vals: Vec<f64> = buf.iter().copied().filter(|&v| v > NEG_INF).collect();
    if vals.len() < 10 {
        return 0.0;
    }
    vals.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = vals.len();
    let lo = vals[(n as f64 * 0.10) as usize];
    let hi = vals[((n as f64 * 0.95) as usize).min(n - 1)];
    (hi - lo).max(0.0)
}


#[cfg(test)]
mod tests {
    use super::*;

    fn feed_blocks(state: &mut LufsState, frames: &[(f64, f64)]) {
        let mut interleaved = Vec::with_capacity(frames.len() * 2);
        for (l, r) in frames {
            interleaved.push(*l);
            interleaved.push(*r);
        }
        state.process(&interleaved);
    }

    // A full-scale square wave has peak 0 dBFS and RMS 0 dBFS; the meter
    // levels must read true, not FFT-normalized. Peak attack is instant;
    // RMS attacks at α=0.6 per 20 ms sub-block, so 200 ms converges it.
    #[test]
    fn per_channel_levels_read_true_dbfs() {
        let mut state = LufsState::new();
        state.update_rate_channels(48_000, 2);
        // 200 ms: L = ±1.0 square (0 dBFS peak, 0 dBFS RMS),
        //         R = ±0.5 square (-6.02 dBFS peak and RMS).
        let frames: Vec<(f64, f64)> = (0..9600)
            .map(|i| {
                let s = if i % 2 == 0 { 1.0 } else { -1.0 };
                (s, s * 0.5)
            })
            .collect();
        feed_blocks(&mut state, &frames);

        let f = *state.pending_level_frames.last().expect("frames");
        assert!((f.peak_l - 0.0).abs() < 0.1, "peak_l={}", f.peak_l);
        assert!((f.rms_l - 0.0).abs() < 0.1, "rms_l={}", f.rms_l);
        assert!((f.peak_r + 6.02).abs() < 0.1, "peak_r={}", f.peak_r);
        assert!((f.rms_r + 6.02).abs() < 0.1, "rms_r={}", f.rms_r);
    }

    // 16 ms display cadence (matching the spectrum frame cadence) with
    // track-absolute position stamps: every sub-block yields one frame, so
    // slab-granular decoding can no longer collapse several updates into one.
    #[test]
    fn display_frames_are_stamped_at_sixteen_ms_cadence() {
        let mut state = LufsState::new();
        state.update_rate_channels(48_000, 2);
        state.set_start_offset(42.0);
        let frames: Vec<(f64, f64)> = (0..9600).map(|_| (0.5, -0.5)).collect();
        feed_blocks(&mut state, &frames);

        let stamps: Vec<f64> = state.pending_level_frames.iter().map(|f| f.pos_s).collect();
        assert_eq!(stamps.len(), 12, "200 ms should yield 12 complete sub-blocks");
        assert!((stamps[0] - 42.016).abs() < 1e-9, "first={}", stamps[0]);
        assert!((stamps[11] - 42.192).abs() < 1e-9, "last={}", stamps[11]);
        assert!(stamps.windows(2).all(|w| w[1] > w[0]));
    }

    #[test]
    fn peak_falls_at_sixty_db_per_second() {
        let mut state = LufsState::new();
        state.update_rate_channels(48_000, 2);
        // 100 ms full-scale square → peak at 0 dBFS.
        let loud: Vec<(f64, f64)> = (0..4800)
            .map(|i| { let s = if i % 2 == 0 { 1.0 } else { -1.0 }; (s, s) })
            .collect();
        feed_blocks(&mut state, &loud);
        assert!((state.pending_level_frames.last().unwrap().peak_l - 0.0).abs() < 0.1);
        // 100 ms of loud = 6.25 sub-blocks, so the first "silent" sub-block
        // still contains 192 loud frames and holds the peak at 0 dB; the
        // remaining 11 pure-silence sub-blocks fall 11 × 0.96 = −10.56 dB.
        let quiet: Vec<(f64, f64)> = (0..9600).map(|_| (0.0, 0.0)).collect();
        feed_blocks(&mut state, &quiet);
        let last = state.pending_level_frames.last().unwrap().peak_l;
        assert!((last + 10.56).abs() < 0.1, "peak_l={last}");
    }

    #[test]
    fn reset_clears_pending_frames_but_keeps_start_offset() {
        let mut state = LufsState::new();
        state.update_rate_channels(48_000, 2);
        state.set_start_offset(7.5);
        let frames: Vec<(f64, f64)> = (0..4800).map(|_| (0.5, 0.5)).collect();
        feed_blocks(&mut state, &frames);
        assert!(!state.pending_level_frames.is_empty());
        state.reset();
        assert!(state.pending_level_frames.is_empty());
        feed_blocks(&mut state, &frames);
        assert!((state.pending_level_frames[0].pos_s - 7.516).abs() < 1e-9);
    }

    #[test]
    fn mono_mirrors_left_into_right() {
        let mut state = LufsState::new();
        state.update_rate_channels(48_000, 1);
        let samples: Vec<f64> = (0..4800).map(|i| if i % 2 == 0 { 0.25 } else { -0.25 }).collect();
        state.process(&samples);
        let f = *state.pending_level_frames.last().expect("frames");
        assert!(f.peak_r > LEVEL_DISPLAY_FLOOR_DB);
        assert_eq!(f.peak_l, f.peak_r);
        assert_eq!(f.rms_l, f.rms_r);
    }
}
