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
use std::sync::{Arc, Mutex};

use gst::prelude::*;
use gst::PadProbeReturn;
use gst::PadProbeType;
use gstreamer as gst;

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
struct LufsState {
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
    fn new() -> Self {
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

    fn update_rate_channels(&mut self, rate: u32, channels: usize) {
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
        // Flush the in-progress block so we don't mix old and new rates.
        self.block_sum = 0.0;
        self.block_count = 0;
        self.block_peak = 0.0;
        self.block_power_sum = 0.0;
    }

    /// Process a slice of interleaved F64LE samples (read-only tap).
    fn process(&mut self, samples: &[f64]) {
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
            }
            self.block_sum += sum_sq;
            self.block_count += 1;

            if self.block_count >= self.block_target {
                self.flush_block();
            }
        }
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

    fn reset(&mut self) {
        self.filt1 = [BiquadState::default(); MAX_CHANNELS];
        self.filt2 = [BiquadState::default(); MAX_CHANNELS];
        self.block_sum = 0.0;
        self.block_count = 0;
        self.block_peak = 0.0;
        self.block_power_sum = 0.0;
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

// ---------------------------------------------------------------------------
// GStreamer node (same pattern as LimiterNode)
// ---------------------------------------------------------------------------

impl std::fmt::Debug for LufsNode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("LufsNode").finish_non_exhaustive()
    }
}

pub struct LufsNode {
    bin: gst::Bin,
    state: Arc<Mutex<LufsState>>,
}

impl LufsNode {
    pub fn new() -> Result<Self, String> {
        let bin = gst::Bin::new();

        let identity = gst::ElementFactory::make("identity")
            .name("rust-dsp-lufs")
            .build()
            .map_err(|e| format!("identity element unavailable for lufs meter: {e}"))?;
        let _ = identity.set_property("silent", true);

        bin.add(&identity)
            .map_err(|_| "failed to add lufs identity".to_string())?;

        let sink_pad = identity
            .static_pad("sink")
            .ok_or_else(|| "lufs identity missing sink pad".to_string())?;
        let src_pad = identity
            .static_pad("src")
            .ok_or_else(|| "lufs identity missing src pad".to_string())?;

        let ghost_sink = gst::GhostPad::with_target(&sink_pad)
            .map_err(|_| "failed to create lufs ghost sink pad".to_string())?;
        let ghost_src = gst::GhostPad::with_target(&src_pad)
            .map_err(|_| "failed to create lufs ghost src pad".to_string())?;
        bin.add_pad(&ghost_sink)
            .map_err(|_| "failed to add lufs ghost sink pad".to_string())?;
        bin.add_pad(&ghost_src)
            .map_err(|_| "failed to add lufs ghost src pad".to_string())?;

        let state = Arc::new(Mutex::new(LufsState::new()));
        let probe_state = Arc::clone(&state);

        // Read-only buffer probe: inspect samples without modifying them.
        src_pad.add_probe(PadProbeType::BUFFER, move |pad, info| {
            let Some(gst::PadProbeData::Buffer(ref buffer)) = info.data else {
                return PadProbeReturn::Ok;
            };
            // try_lock avoids priority inversion on the audio thread.
            let Ok(mut st) = probe_state.try_lock() else {
                return PadProbeReturn::Ok;
            };

            // Sync sample rate and channel count from caps.
            let (rate, channels) = if let Some(caps) = pad.current_caps() {
                if let Some(s) = caps.structure(0) {
                    let r = s.get::<i32>("rate").unwrap_or(48_000).max(1) as u32;
                    let ch = s.get::<i32>("channels").unwrap_or(2).max(1) as usize;
                    (r, ch)
                } else {
                    (48_000, 2)
                }
            } else {
                (48_000, 2)
            };

            st.update_rate_channels(rate, channels);

            // Map buffer as readable and process F64LE samples.
            if let Ok(map) = buffer.map_readable() {
                let raw = map.as_slice();
                // DSP internal format is F64LE (8 bytes per sample).
                if raw.len() % 8 == 0 {
                    // SAFETY: format is F64LE, GStreamer guarantees alignment.
                    let samples = unsafe {
                        std::slice::from_raw_parts(raw.as_ptr() as *const f64, raw.len() / 8)
                    };
                    st.process(samples);
                }
            }

            PadProbeReturn::Ok
        });

        Ok(Self { bin, state })
    }

    pub fn element(&self) -> &gst::Element {
        self.bin.upcast_ref()
    }

    /// Read the latest loudness values (non-blocking; returns defaults on lock contention).
    pub fn get_values(&self) -> LufsValues {
        self.state
            .try_lock()
            .map(|st| st.values.clone())
            .unwrap_or_default()
    }

    /// Reset all accumulators (call on track change).
    pub fn reset(&self) {
        if let Ok(mut st) = self.state.lock() {
            st.reset();
        }
    }
}
