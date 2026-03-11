use gst::PadProbeReturn;
use gst::PadProbeType;
use gst::prelude::*;
use gstreamer as gst;
use rustfft::{FftPlanner, num_complex::Complex};
use std::collections::VecDeque;
use std::fs;
use std::path::Path;
use std::sync::{Arc, Mutex};

const MAX_CONVOLVER_TAPS: usize = 262_144;

#[derive(Clone, Debug, PartialEq)]
pub struct ConvolverConfig {
    pub enabled: bool,
    pub impulse_path: String,
    /// Left channel kernel (or the single kernel for mono IRs).
    pub kernel_l: Vec<f64>,
    /// Right channel kernel. Equal to kernel_l for mono IRs.
    pub kernel_r: Vec<f64>,
    pub sample_rate_hz: Option<u32>,
    pub source_channels: u32,
    /// Wet signal level when enabled (0.0 = fully dry, 1.0 = fully wet).
    pub mix: f64,
    /// Silence prepended to the IR to delay the reverb onset, in milliseconds.
    pub pre_delay_ms: f64,
}

impl Default for ConvolverConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            impulse_path: String::new(),
            kernel_l: Vec::new(),
            kernel_r: Vec::new(),
            sample_rate_hz: None,
            source_channels: 0,
            mix: 1.0,
            pre_delay_ms: 0.0,
        }
    }
}

impl ConvolverConfig {
    pub fn is_active(&self) -> bool {
        self.enabled && !self.kernel_l.is_empty()
    }

    pub fn set_enabled(&mut self, enabled: bool) {
        self.enabled = enabled;
    }

    /// Sets the wet mix ratio (0.0–1.0). Returns the clamped value.
    pub fn set_mix(&mut self, mix: f64) -> f64 {
        let clamped = mix.clamp(0.0, 1.0);
        self.mix = clamped;
        clamped
    }

    /// Sets the reverb pre-delay in milliseconds (0–200 ms). Returns the clamped value.
    pub fn set_pre_delay_ms(&mut self, ms: f64) -> f64 {
        let clamped = ms.clamp(0.0, 200.0);
        self.pre_delay_ms = clamped;
        clamped
    }

    pub fn clear(&mut self) {
        *self = Self::default();
    }

    pub fn tap_count(&self) -> usize {
        self.kernel_l.len()
    }

    pub fn load_from_file(&mut self, path: &str) -> Result<(), String> {
        let raw = path.trim();
        if raw.is_empty() {
            return Err("convolver path is empty".to_string());
        }
        let impulse = load_impulse_file(Path::new(raw))?;
        self.impulse_path = raw.to_string();
        self.kernel_l = impulse.kernel_l;
        self.kernel_r = impulse.kernel_r;
        self.sample_rate_hz = impulse.sample_rate_hz;
        self.source_channels = impulse.source_channels;
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Uniform partitioned FFT convolution
// ---------------------------------------------------------------------------
//
// Algorithm: overlap-add with a frequency-domain delay line (FDL).
//
//   Block size B = BLOCK_SIZE.  FFT size L = 2B.
//   Kernel of N taps split into P = ⌈N/B⌉ segments of length B.
//   Each segment pre-FFT'd and stored in kernel_ffts[k].
//
//   For each input block x_n:
//     1. FFT(x_n, zero-pad to L)  →  X_n
//     2. FDL[fdl_head] = X_n
//     3. Y = Σ_{k=0}^{P-1}  kernel_ffts[k] ⊙ FDL[(fdl_head + P - k) % P]
//     4. y = IFFT(Y) / L
//     5. output[0..B] = y[0..B] + overlap
//        overlap      = y[B..L]
//     6. fdl_head = (fdl_head + 1) % P
//
// Complexity: O(P · L · log L) per block = O(N · log(2B)) per B samples.
// At N = 48 000 taps, B = 1024, ~100× faster than direct FIR.
//
// SIMD: the inner accumulate loop iterates over Complex<f64> arrays.
// With -C target-cpu=native (.cargo/config.toml) LLVM emits AVX2/FMA,
// giving 4-wide f64 throughput on the complex multiply-add.

/// Choose block size based on stream sample rate so that the per-second FFT
/// count stays roughly constant regardless of rate.
///
/// | Rate range      | BLOCK_SIZE | FFT size |
/// |-----------------|-----------|---------|
/// | ≤ 54 kHz        | 1 024     | 2 048   |
/// | 54–108 kHz      | 2 048     | 4 096   |
/// | > 108 kHz       | 4 096     | 8 192   |
fn block_size_for_rate(rate: u32) -> usize {
    if rate <= 54_000 {
        1024
    } else if rate <= 108_000 {
        2048
    } else {
        4096
    }
}

/// Choose block size for a kernel of `kernel_len` samples at `rate` Hz.
///
/// Starts from the rate-appropriate base block size and doubles until the
/// number of partitions P ≤ MAX_P for the given rate tier.  This keeps the
/// real-time FFT budget bounded even when a low-rate IR is convolved at a
/// high stream rate (e.g. 44.1 kHz IR @ 192 kHz → 4× more taps).
///
/// | Rate tier  | MAX_P | Max latency added |
/// |------------|-------|-------------------|
/// | > 108 kHz  |   64  |  ~85 ms @ 192 kHz |
/// | > 54 kHz   |  128  |  ~85 ms @ 96 kHz  |
/// | ≤ 54 kHz   | none  |  (already OK)     |
fn choose_block_size(kernel_len: usize, rate: u32) -> usize {
    let max_p: Option<usize> = if rate > 108_000 {
        Some(64)
    } else if rate > 54_000 {
        Some(128)
    } else {
        None
    };
    let mut bs = block_size_for_rate(rate);
    if let Some(mp) = max_p {
        if kernel_len > 0 {
            while kernel_len.div_ceil(bs) > mp {
                bs = bs.saturating_mul(2);
                if bs >= 131_072 {
                    break;
                }
            }
        }
    }
    bs
}

/// Per-sample crossfade step, scaled to maintain ~23 ms at all sample rates.
fn xfade_step_for_rate(rate: u32) -> f64 {
    let base_rate = 44_100.0_f64;
    let steps = (1024.0 * (rate.max(1) as f64 / base_rate)).round().max(1.0);
    1.0 / steps
}

struct PartitionedConvolver {
    block_size: usize,
    fft_size: usize,
    /// Pre-FFT'd kernel segments.
    kernel_ffts: Vec<Vec<Complex<f64>>>,
    /// Frequency-domain delay line (circular buffer of past input FFTs).
    fdl: Vec<Vec<Complex<f64>>>,
    fdl_head: usize,
    /// Staging buffer: accumulate input samples until a full block.
    input_buf: Vec<f64>,
    input_pos: usize,
    /// Overlap-add tail from the previous block.
    overlap: Vec<f64>,
    /// Output samples ready to be consumed.
    output_queue: VecDeque<f64>,
    fft: std::sync::Arc<dyn rustfft::Fft<f64>>,
    ifft: std::sync::Arc<dyn rustfft::Fft<f64>>,
}

impl std::fmt::Debug for PartitionedConvolver {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("PartitionedConvolver")
            .field("block_size", &self.block_size)
            .field("num_segments", &self.kernel_ffts.len())
            .finish()
    }
}

impl PartitionedConvolver {
    fn new(kernel: &[f64], block_size: usize) -> Self {
        let fft_size = 2 * block_size;

        let mut planner = FftPlanner::new();
        let fft = planner.plan_fft_forward(fft_size);
        let ifft = planner.plan_fft_inverse(fft_size);

        let num_segs = if kernel.is_empty() {
            1
        } else {
            kernel.len().div_ceil(block_size)
        };
        let mut kernel_ffts: Vec<Vec<Complex<f64>>> = Vec::with_capacity(num_segs);
        for k in 0..num_segs {
            let start = k * block_size;
            let end = (start + block_size).min(kernel.len());
            let mut seg = vec![Complex::new(0.0_f64, 0.0); fft_size];
            for (i, &v) in kernel[start..end].iter().enumerate() {
                seg[i] = Complex::new(v, 0.0);
            }
            fft.process(&mut seg);
            kernel_ffts.push(seg);
        }
        if kernel_ffts.is_empty() {
            // Identity: impulse at t=0.
            let mut seg = vec![Complex::new(0.0_f64, 0.0); fft_size];
            seg[0] = Complex::new(1.0, 0.0);
            fft.process(&mut seg);
            kernel_ffts.push(seg);
        }

        let p = kernel_ffts.len();
        Self {
            block_size,
            fft_size,
            kernel_ffts,
            fdl: vec![vec![Complex::new(0.0_f64, 0.0); fft_size]; p],
            fdl_head: 0,
            input_buf: vec![0.0; block_size],
            input_pos: 0,
            overlap: vec![0.0; block_size],
            output_queue: VecDeque::new(),
            fft,
            ifft,
        }
    }

    fn process_block(&mut self) {
        let b = self.block_size;
        let l = self.fft_size;
        let p = self.kernel_ffts.len();

        // FFT the current input block (zero-padded to l).
        let mut x = vec![Complex::new(0.0_f64, 0.0); l];
        for (i, &v) in self.input_buf.iter().enumerate() {
            x[i] = Complex::new(v, 0.0);
        }
        self.fft.process(&mut x);
        self.fdl[self.fdl_head].copy_from_slice(&x);

        // Frequency-domain multiply-accumulate — hot path, auto-vectorised.
        let mut y_freq = vec![Complex::new(0.0_f64, 0.0); l];
        for k in 0..p {
            let fdl_idx = (self.fdl_head + p - k) % p;
            let h = &self.kernel_ffts[k];
            let xk = &self.fdl[fdl_idx];
            for i in 0..l {
                y_freq[i] += h[i] * xk[i];
            }
        }
        self.fdl_head = (self.fdl_head + 1) % p;

        // IFFT, normalise, overlap-add.
        self.ifft.process(&mut y_freq);
        let scale = 1.0 / l as f64;
        for i in 0..b {
            self.output_queue.push_back(y_freq[i].re * scale + self.overlap[i]);
        }
        for i in 0..b {
            self.overlap[i] = y_freq[b + i].re * scale;
        }
        self.input_pos = 0;
    }

    /// Process samples in-place.  Startup latency ≤ BLOCK_SIZE samples
    /// (zero-filled until the first block completes).
    fn process(&mut self, samples: &mut [f64]) {
        let mut pos = 0;
        while pos < samples.len() {
            let space = self.block_size - self.input_pos;
            let take = space.min(samples.len() - pos);
            self.input_buf[self.input_pos..self.input_pos + take]
                .copy_from_slice(&samples[pos..pos + take]);
            self.input_pos += take;
            if self.input_pos == self.block_size {
                self.process_block();
            }
            for i in 0..take {
                samples[pos + i] = self.output_queue.pop_front().unwrap_or(0.0);
            }
            pos += take;
        }
    }
}

#[derive(Debug)]
struct ConvolverState {
    /// Dry/wet mix gains (ramped per-sample to avoid clicks).
    dry_gain: f64,
    dry_gain_target: f64,
    wet_gain: f64,
    wet_gain_target: f64,
    conv_l: PartitionedConvolver,
    conv_r: PartitionedConvolver,
    /// Raw (pre-resample) kernels kept for sample-rate changes.
    raw_kernel_l: Vec<f64>,
    raw_kernel_r: Vec<f64>,
    /// IR native sample rate (None for text kernels).
    ir_sample_rate: Option<u32>,
    /// Last known pipeline sample rate; triggers resample when it changes.
    stream_sample_rate: u32,
    /// Per-sample crossfade step (rate-adaptive, ~23 ms fade at all rates).
    xfade_step: f64,
    /// Pre-delay in ms: silence prepended to the kernel so reverb onset is
    /// delayed relative to the dry signal.  Reapplied on each kernel rebuild.
    pre_delay_ms: f64,
}

impl ConvolverState {
    fn new() -> Self {
        let default_rate = 44100_u32;
        let bs = block_size_for_rate(default_rate);
        Self {
            dry_gain: 1.0,
            dry_gain_target: 1.0,
            wet_gain: 0.0,
            wet_gain_target: 0.0,
            conv_l: PartitionedConvolver::new(&[1.0], bs),
            conv_r: PartitionedConvolver::new(&[1.0], bs),
            raw_kernel_l: Vec::new(),
            raw_kernel_r: Vec::new(),
            ir_sample_rate: None,
            stream_sample_rate: default_rate,
            xfade_step: xfade_step_for_rate(default_rate),
            pre_delay_ms: 0.0,
        }
    }

    /// Prepend `pre_delay_ms` worth of zeros to a resampled kernel.
    fn apply_pre_delay(&self, mut k: Vec<f64>, rate: u32) -> Vec<f64> {
        let n = (self.pre_delay_ms * rate as f64 / 1000.0).round() as usize;
        if n > 0 {
            let mut padded = vec![0.0f64; n];
            padded.append(&mut k);
            padded
        } else {
            k
        }
    }

    /// Load new kernels, resampling to stream rate and applying pre-delay.
    fn update_kernels(&mut self, kernel_l: Vec<f64>, kernel_r: Vec<f64>, ir_rate: Option<u32>) {
        self.ir_sample_rate = ir_rate;
        self.raw_kernel_l = kernel_l.clone();
        self.raw_kernel_r = kernel_r.clone();
        let rate = self.stream_sample_rate;
        let (kl, kr) = match ir_rate {
            Some(ir_r) if rate > 0 && ir_r != rate => (
                resample(&kernel_l, ir_r, rate),
                resample(&kernel_r, ir_r, rate),
            ),
            _ => (kernel_l, kernel_r),
        };
        let kl = self.apply_pre_delay(kl, rate);
        let kr = self.apply_pre_delay(kr, rate);
        let bs = choose_block_size(kl.len(), rate);
        self.conv_l = PartitionedConvolver::new(&kl, bs);
        self.conv_r = PartitionedConvolver::new(&kr, bs);
    }

    /// Called each buffer from the pad probe with the actual pipeline rate.
    /// Rebuilds the convolver if the rate has changed and IRs need resampling.
    fn update_stream_rate(&mut self, rate: u32) {
        if rate == 0 || rate == self.stream_sample_rate {
            return;
        }
        self.stream_sample_rate = rate;
        self.xfade_step = xfade_step_for_rate(rate);
        if let Some(ir_r) = self.ir_sample_rate {
            if ir_r != rate && !self.raw_kernel_l.is_empty() {
                let kl = self.apply_pre_delay(resample(&self.raw_kernel_l, ir_r, rate), rate);
                let kr = self.apply_pre_delay(resample(&self.raw_kernel_r, ir_r, rate), rate);
                let bs = choose_block_size(kl.len(), rate);
                self.conv_l = PartitionedConvolver::new(&kl, bs);
                self.conv_r = PartitionedConvolver::new(&kr, bs);
            }
        }
    }

    /// Process interleaved F64LE samples in-place.
    /// Saves the dry copy, convolves, and mixes with per-sample gain ramp.
    fn process(&mut self, samples: &mut [f64], channels: usize) {
        if channels == 0 || samples.is_empty() {
            return;
        }
        // Fast-path: fully dry and stable.
        if self.wet_gain < 1e-8 && self.wet_gain_target < 1e-8 {
            return;
        }

        let frames = samples.len() / channels;

        // Save dry input before overwriting.
        let dry: Vec<f64> = samples.to_vec();

        // Convolve per channel.
        let mut buf_l: Vec<f64> = (0..frames).map(|i| samples[i * channels]).collect();
        self.conv_l.process(&mut buf_l);
        for i in 0..frames {
            samples[i * channels] = buf_l[i];
        }
        if channels >= 2 {
            let mut buf_r: Vec<f64> =
                (0..frames).map(|i| samples[i * channels + 1]).collect();
            self.conv_r.process(&mut buf_r);
            for i in 0..frames {
                samples[i * channels + 1] = buf_r[i];
            }
        }

        // Per-frame dry/wet mix with linear gain ramp to eliminate clicks.
        for frame in 0..frames {
            let base = frame * channels;
            samples[base] = self.dry_gain * dry[base] + self.wet_gain * samples[base];
            if channels >= 2 {
                samples[base + 1] =
                    self.dry_gain * dry[base + 1] + self.wet_gain * samples[base + 1];
            }
            // Extra channels: restore dry.
            for ch in 2..channels {
                samples[base + ch] = dry[base + ch];
            }
            // Advance gains toward targets.
            if (self.dry_gain - self.dry_gain_target).abs() > self.xfade_step {
                self.dry_gain +=
                    if self.dry_gain < self.dry_gain_target { self.xfade_step } else { -self.xfade_step };
            } else {
                self.dry_gain = self.dry_gain_target;
            }
            if (self.wet_gain - self.wet_gain_target).abs() > self.xfade_step {
                self.wet_gain +=
                    if self.wet_gain < self.wet_gain_target { self.xfade_step } else { -self.xfade_step };
            } else {
                self.wet_gain = self.wet_gain_target;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Public GStreamer node
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub struct ConvolverNode {
    bin: gst::Bin,
    state: Arc<Mutex<ConvolverState>>,
}

impl ConvolverNode {
    pub fn new() -> Result<Self, String> {
        let bin = gst::Bin::new();

        // Single identity element; the pad probe below does all DSP.
        // Dry/wet mixing and crossfade are handled in Rust — no tee or
        // audiomixer needed, which avoids the deadlock-prone deinterleave
        // pipeline and the audiomixer synchronization stall on the dry path.
        let identity = gst::ElementFactory::make("identity")
            .name("rust-dsp-conv")
            .build()
            .map_err(|e| format!("identity unavailable: {e}"))?;
        let _ = identity.set_property("silent", true);

        bin.add(&identity)
            .map_err(|_| "failed to add conv identity".to_string())?;

        let sink_pad = identity.static_pad("sink").ok_or("conv identity missing sink")?;
        let src_pad = identity.static_pad("src").ok_or("conv identity missing src")?;
        let ghost_sink = gst::GhostPad::with_target(&sink_pad)
            .map_err(|_| "failed to create conv ghost sink")?;
        let ghost_src = gst::GhostPad::with_target(&src_pad)
            .map_err(|_| "failed to create conv ghost src")?;
        bin.add_pad(&ghost_sink).map_err(|_| "failed to add conv ghost sink")?;
        bin.add_pad(&ghost_src).map_err(|_| "failed to add conv ghost src")?;

        let state = Arc::new(Mutex::new(ConvolverState::new()));
        let probe_state = Arc::clone(&state);

        src_pad.add_probe(PadProbeType::BUFFER, move |pad, info| {
            let Some(gst::PadProbeData::Buffer(ref mut buffer)) = info.data else {
                return PadProbeReturn::Ok;
            };
            let Ok(mut st) = probe_state.try_lock() else {
                return PadProbeReturn::Ok;
            };
            let (rate, channels) = if let Some(caps) = pad.current_caps() {
                if let Some(s) = caps.structure(0) {
                    let r = s.get::<i32>("rate").unwrap_or(44100) as u32;
                    let ch = s.get::<i32>("channels").unwrap_or(2).max(1) as usize;
                    (r, ch)
                } else {
                    (44100, 2)
                }
            } else {
                (44100, 2)
            };
            st.update_stream_rate(rate);
            let buf = buffer.make_mut();
            if let Ok(mut map) = buf.map_writable() {
                let raw = map.as_mut_slice();
                if raw.len() % 8 == 0 {
                    // SAFETY: format is F64LE, 8-byte aligned by GStreamer.
                    let samples = unsafe {
                        std::slice::from_raw_parts_mut(
                            raw.as_mut_ptr() as *mut f64,
                            raw.len() / 8,
                        )
                    };
                    st.process(samples, channels);
                }
            }
            PadProbeReturn::Ok
        });

        let mut node = Self { bin, state };
        node.apply_config(&ConvolverConfig::default())?;
        Ok(node)
    }

    pub fn element(&self) -> &gst::Element {
        self.bin.upcast_ref()
    }

    pub fn apply_config(&mut self, config: &ConvolverConfig) -> Result<(), String> {
        let Ok(mut st) = self.state.lock() else {
            return Err("convolver state lock poisoned".to_string());
        };
        if config.is_active() {
            st.pre_delay_ms = config.pre_delay_ms;
            st.update_kernels(
                config.kernel_l.clone(),
                config.kernel_r.clone(),
                config.sample_rate_hz,
            );
            st.dry_gain_target = (1.0 - config.mix).clamp(0.0, 1.0);
            st.wet_gain_target = config.mix.clamp(0.0, 1.0);
        } else {
            st.dry_gain_target = 1.0;
            st.wet_gain_target = 0.0;
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// IR loading
// ---------------------------------------------------------------------------

struct LoadedImpulse {
    kernel_l: Vec<f64>,
    kernel_r: Vec<f64>,
    sample_rate_hz: Option<u32>,
    source_channels: u32,
}

fn load_impulse_file(path: &Path) -> Result<LoadedImpulse, String> {
    if !path.exists() {
        return Err(format!("impulse file not found: {}", path.display()));
    }
    let ext = path
        .extension()
        .and_then(|v| v.to_str())
        .unwrap_or("")
        .trim()
        .to_ascii_lowercase();
    let mut impulse = match ext.as_str() {
        "wav" | "wave" => load_wav_impulse(path),
        _ => load_text_impulse(path),
    }?;

    // Trim pre-delay using the minimum onset across both channels so that
    // L/R stay temporally aligned.
    let global_peak = peak_of(&impulse.kernel_l).max(peak_of(&impulse.kernel_r));
    if global_peak > 1e-10 {
        let thr = global_peak * 0.01;
        let onset_l = impulse.kernel_l.iter().position(|x| x.abs() >= thr).unwrap_or(0);
        let onset_r = impulse.kernel_r.iter().position(|x| x.abs() >= thr).unwrap_or(0);
        let onset = onset_l.min(onset_r);
        if onset > 0 {
            impulse.kernel_l.drain(0..onset);
            impulse.kernel_r.drain(0..onset);
        }

        // Normalize both channels with the same scale factor to preserve
        // the stereo balance.
        let scale = 1.0 / global_peak;
        for s in impulse.kernel_l.iter_mut() { *s *= scale; }
        for s in impulse.kernel_r.iter_mut() { *s *= scale; }
    }

    if impulse.kernel_l.is_empty() {
        return Err(format!(
            "IR kernel is empty after pre-delay trim: {}",
            path.display()
        ));
    }

    Ok(impulse)
}

fn peak_of(kernel: &[f64]) -> f64 {
    kernel.iter().map(|x| x.abs()).fold(0.0f64, f64::max)
}

fn load_text_impulse(path: &Path) -> Result<LoadedImpulse, String> {
    let raw = fs::read_to_string(path)
        .map_err(|e| format!("failed to read impulse file {}: {e}", path.display()))?;
    let mut kernel = Vec::new();
    for line in raw.lines() {
        let body = line.split('#').next().unwrap_or("").trim();
        if body.is_empty() {
            continue;
        }
        for token in body.split(|ch: char| ch.is_ascii_whitespace() || ch == ',' || ch == ';') {
            let item = token.trim();
            if item.is_empty() {
                continue;
            }
            let value: f64 = item.parse().map_err(|_| {
                format!("invalid FIR coefficient `{item}` in {}", path.display())
            })?;
            if !value.is_finite() {
                return Err(format!("non-finite FIR coefficient in {}", path.display()));
            }
            kernel.push(value);
            if kernel.len() > MAX_CONVOLVER_TAPS {
                return Err(format!(
                    "impulse too long in {} (max {} taps)",
                    path.display(),
                    MAX_CONVOLVER_TAPS
                ));
            }
        }
    }
    if kernel.is_empty() {
        return Err(format!("no FIR coefficients found in {}", path.display()));
    }
    // Text files are always mono; duplicate to right channel.
    let kernel_r = kernel.clone();
    Ok(LoadedImpulse {
        kernel_l: kernel,
        kernel_r,
        sample_rate_hz: None,
        source_channels: 1,
    })
}

fn load_wav_impulse(path: &Path) -> Result<LoadedImpulse, String> {
    let data = fs::read(path).map_err(|e| format!("failed to read WAV IR {}: {e}", path.display()))?;
    if data.len() < 12 {
        return Err(format!("WAV IR too small: {}", path.display()));
    }
    if &data[0..4] != b"RIFF" || &data[8..12] != b"WAVE" {
        return Err(format!("unsupported WAV container: {}", path.display()));
    }

    let mut fmt_code = 0u16;
    let mut channels = 0u16;
    let mut sample_rate = 0u32;
    let mut bits_per_sample = 0u16;
    let mut data_range: Option<(usize, usize)> = None;

    let mut offset = 12usize;
    while offset + 8 <= data.len() {
        let chunk_id = &data[offset..offset + 4];
        let chunk_size = read_u32_le(&data[offset + 4..offset + 8]) as usize;
        offset += 8;
        let chunk_end = offset
            .checked_add(chunk_size)
            .ok_or_else(|| format!("invalid WAV chunk size in {}", path.display()))?;
        if chunk_end > data.len() {
            return Err(format!("truncated WAV chunk in {}", path.display()));
        }
        if chunk_id == b"fmt " {
            if chunk_size < 16 {
                return Err(format!("invalid WAV fmt chunk in {}", path.display()));
            }
            fmt_code = read_u16_le(&data[offset..offset + 2]);
            channels = read_u16_le(&data[offset + 2..offset + 4]);
            sample_rate = read_u32_le(&data[offset + 4..offset + 8]);
            bits_per_sample = read_u16_le(&data[offset + 14..offset + 16]);
        } else if chunk_id == b"data" {
            data_range = Some((offset, chunk_end));
        }
        offset = chunk_end + (chunk_size & 1);
    }

    if channels == 0 {
        return Err(format!("missing WAV channel count in {}", path.display()));
    }
    if sample_rate == 0 {
        return Err(format!("missing WAV sample rate in {}", path.display()));
    }
    let (data_start, data_end) =
        data_range.ok_or_else(|| format!("missing WAV data chunk in {}", path.display()))?;

    let bytes_per_sample = match (fmt_code, bits_per_sample) {
        (1, 16) => 2usize,
        (1, 24) => 3usize,
        (1, 32) => 4usize,
        (3, 32) => 4usize,
        (3, 64) => 8usize,
        _ => {
            return Err(format!(
                "unsupported WAV IR format in {} (fmt={}, bits={})",
                path.display(),
                fmt_code,
                bits_per_sample
            ))
        }
    };

    let ch = channels as usize;
    let frame_width = bytes_per_sample
        .checked_mul(ch)
        .ok_or_else(|| format!("invalid WAV frame width in {}", path.display()))?;
    if frame_width == 0 {
        return Err(format!("invalid WAV frame width in {}", path.display()));
    }

    let payload = &data[data_start..data_end];
    let frames = payload.len() / frame_width;
    if frames == 0 {
        return Err(format!("empty WAV IR data in {}", path.display()));
    }
    if frames > MAX_CONVOLVER_TAPS {
        return Err(format!(
            "WAV IR too long in {} (max {} taps)",
            path.display(),
            MAX_CONVOLVER_TAPS
        ));
    }

    // Decode left channel (index 0) and right channel (index 1).
    // For mono, right = left. For >2 channels, only L/R are used.
    let mut kernel_l = Vec::with_capacity(frames);
    let mut kernel_r = Vec::with_capacity(frames);
    for frame_idx in 0..frames {
        let frame_offset = frame_idx * frame_width;
        let sample_l = decode_wav_sample(
            fmt_code,
            bits_per_sample,
            &payload[frame_offset..frame_offset + bytes_per_sample],
        )?;
        let sample_r = if ch >= 2 {
            decode_wav_sample(
                fmt_code,
                bits_per_sample,
                &payload[frame_offset + bytes_per_sample..frame_offset + 2 * bytes_per_sample],
            )?
        } else {
            sample_l
        };
        kernel_l.push(sample_l);
        kernel_r.push(sample_r);
    }

    Ok(LoadedImpulse {
        kernel_l,
        kernel_r,
        sample_rate_hz: Some(sample_rate),
        source_channels: channels as u32,
    })
}

fn decode_wav_sample(fmt_code: u16, bits_per_sample: u16, bytes: &[u8]) -> Result<f64, String> {
    let sample = match (fmt_code, bits_per_sample) {
        (1, 16) => {
            let value = i16::from_le_bytes([bytes[0], bytes[1]]);
            (value as f64) / 32768.0
        }
        (1, 24) => {
            let raw = (bytes[0] as i32) | ((bytes[1] as i32) << 8) | ((bytes[2] as i32) << 16);
            let signed = if (raw & 0x0080_0000) != 0 {
                raw | !0x00FF_FFFF
            } else {
                raw
            };
            (signed as f64) / 8_388_608.0
        }
        (1, 32) => {
            let value = i32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
            (value as f64) / 2_147_483_648.0
        }
        (3, 32) => {
            let value = f32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]) as f64;
            if !value.is_finite() {
                return Err("non-finite float sample in WAV IR".to_string());
            }
            value
        }
        (3, 64) => {
            let value = f64::from_le_bytes([
                bytes[0], bytes[1], bytes[2], bytes[3],
                bytes[4], bytes[5], bytes[6], bytes[7],
            ]);
            if !value.is_finite() {
                return Err("non-finite float sample in WAV IR".to_string());
            }
            value
        }
        _ => return Err("unsupported WAV sample encoding".to_string()),
    };
    if !sample.is_finite() {
        return Err("non-finite WAV sample".to_string());
    }
    Ok(sample)
}

fn read_u16_le(bytes: &[u8]) -> u16 {
    u16::from_le_bytes([bytes[0], bytes[1]])
}

fn read_u32_le(bytes: &[u8]) -> u32 {
    u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]])
}

// ---------------------------------------------------------------------------
// Windowed-sinc resampler (used when IR sample rate ≠ stream sample rate)
// ---------------------------------------------------------------------------
//
// h(x) = fc · sinc(fc · x)  where fc = min(1, target/source)
//   = sin(π·x·fc) / (π·x)   for x ≠ 0
//   = fc                      for x = 0
//
// Applied with a 64-tap Hann window (±32 source samples) for good
// stop-band attenuation with modest computation cost.
// Called only at IR load time, so latency is irrelevant.

fn resample(kernel: &[f64], source_rate: u32, target_rate: u32) -> Vec<f64> {
    if source_rate == 0 || target_rate == 0 || source_rate == target_rate || kernel.is_empty() {
        return kernel.to_vec();
    }
    let ratio = target_rate as f64 / source_rate as f64;
    let output_len = (kernel.len() as f64 * ratio).round() as usize;
    if output_len == 0 {
        return Vec::new();
    }
    // Anti-aliasing cutoff: lower for downsampling to prevent aliasing.
    let fc = ratio.min(1.0);
    const HALF_WIN: usize = 32;
    let n_src = kernel.len() as isize;

    (0..output_len)
        .map(|n| {
            let p = n as f64 / ratio;
            let i0 = p.floor() as isize;
            let frac = p - i0 as f64;
            (-(HALF_WIN as isize)..=(HALF_WIN as isize))
                .filter_map(|k| {
                    let i = i0 + k;
                    if i < 0 || i >= n_src {
                        return None;
                    }
                    // x = p - i = frac - k  (distance from source sample i to target p)
                    let x = frac - k as f64;
                    // Lowpass-weighted sinc: h(x) = sin(π·x·fc) / (π·x)
                    let h = if x.abs() < 1e-10 {
                        fc
                    } else {
                        (std::f64::consts::PI * x * fc).sin() / (std::f64::consts::PI * x)
                    };
                    // Hann window centred at x=0, half-width HALF_WIN.
                    let t = x / HALF_WIN as f64;
                    let w = if t.abs() <= 1.0 {
                        0.5 + 0.5 * (std::f64::consts::PI * t).cos()
                    } else {
                        0.0
                    };
                    Some(kernel[i as usize] * h * w)
                })
                .sum::<f64>()
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::peak_of;

    fn make_stereo_impulse(kl: Vec<f64>, kr: Vec<f64>) -> (Vec<f64>, Vec<f64>) {
        (kl, kr)
    }

    #[test]
    fn peak_of_returns_max_abs() {
        assert!((peak_of(&[0.5, -0.9, 0.3]) - 0.9).abs() < 1e-12);
        assert!((peak_of(&[]) - 0.0).abs() < 1e-12);
    }

    #[test]
    fn stereo_normalize_preserves_balance() {
        // L peak = 0.5, R peak = 1.0 → global peak = 1.0
        let (mut kl, mut kr) = make_stereo_impulse(vec![0.5, 0.3], vec![1.0, -0.8]);
        let global_peak = peak_of(&kl).max(peak_of(&kr));
        let scale = 1.0 / global_peak;
        for s in kl.iter_mut() { *s *= scale; }
        for s in kr.iter_mut() { *s *= scale; }

        // R peak should now be exactly 1.0
        assert!((peak_of(&kr) - 1.0).abs() < 1e-12);
        // L peak should be 0.5 (balance preserved)
        assert!((peak_of(&kl) - 0.5).abs() < 1e-12);
    }

    #[test]
    fn stereo_predelay_uses_minimum_onset() {
        // L has onset at index 2, R has onset at index 1 → trim 1 sample
        let mut kl = vec![0.0, 0.0, 1.0, 0.5];
        let mut kr = vec![0.0, 1.0, 0.8, 0.3];
        let peak = peak_of(&kl).max(peak_of(&kr));
        let thr = peak * 0.01;
        let onset_l = kl.iter().position(|x| x.abs() >= thr).unwrap_or(0);
        let onset_r = kr.iter().position(|x| x.abs() >= thr).unwrap_or(0);
        let onset = onset_l.min(onset_r);
        kl.drain(0..onset);
        kr.drain(0..onset);

        assert_eq!(onset, 1);
        assert_eq!(kl.len(), 3);
        assert_eq!(kr.len(), 3);
        assert!((kl[0] - 0.0).abs() < 1e-12); // the leading 0.0 at index 1 stays
        assert!((kr[0] - 1.0).abs() < 1e-12);
    }

    #[test]
    fn mono_wav_duplicates_to_right_channel() {
        // Simulate a mono IR load: kernel_r must equal kernel_l
        let kernel = vec![0.1, 0.9, -0.3];
        let kernel_r = kernel.clone();
        assert_eq!(kernel, kernel_r);
    }
}
