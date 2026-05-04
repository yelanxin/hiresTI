use crossbeam_channel::Sender;
use rustfft::{num_complex::Complex, FftPlanner};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};

use crate::dsp::lufs::{LufsState, LufsValues};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PcmSampleFormat {
    S16LE,
    S24_3LE,
    S24LE,
    S32LE,
    F32LE,
    F64LE,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PcmStreamSpec {
    pub sample_rate: u32,
    pub channels: usize,
    pub format: PcmSampleFormat,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PcmSlab {
    pub spec: PcmStreamSpec,
    pub frames: usize,
    pub data: Vec<u8>,
}

pub trait PcmProcessor: Send {
    fn name(&self) -> &'static str;

    fn configure(&mut self, _spec: &PcmStreamSpec) -> Result<(), String> {
        Ok(())
    }

    fn process(&mut self, slab: PcmSlab) -> Result<PcmSlab, String>;

    fn drain(&mut self) -> Result<Vec<PcmSlab>, String> {
        Ok(Vec::new())
    }
}

#[derive(Debug, Default)]
pub struct PassthroughPcmProcessor;

impl PcmProcessor for PassthroughPcmProcessor {
    fn name(&self) -> &'static str {
        "passthrough"
    }

    fn process(&mut self, slab: PcmSlab) -> Result<PcmSlab, String> {
        Ok(slab)
    }
}

#[derive(Default)]
pub struct PcmProcessorChain {
    processors: Vec<Box<dyn PcmProcessor>>,
}

impl PcmProcessorChain {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn len(&self) -> usize {
        self.processors.len()
    }

    pub fn is_empty(&self) -> bool {
        self.processors.is_empty()
    }

    pub fn push(&mut self, processor: Box<dyn PcmProcessor>) {
        self.processors.push(processor);
    }

    pub fn configure(&mut self, spec: &PcmStreamSpec) -> Result<(), String> {
        for processor in &mut self.processors {
            processor.configure(spec)?;
        }
        Ok(())
    }

    pub fn process(&mut self, mut slab: PcmSlab) -> Result<PcmSlab, String> {
        for processor in &mut self.processors {
            slab = processor.process(slab)?;
        }
        Ok(slab)
    }

    pub fn drain(&mut self) -> Result<Vec<PcmSlab>, String> {
        let mut drained = Vec::new();
        for processor in &mut self.processors {
            drained.extend(processor.drain()?);
        }
        Ok(drained)
    }
}

/// Shared volume knob: stores f32 linear gain as u32 bits for lock-free access.
#[derive(Clone)]
pub struct SharedVolume(Arc<AtomicU32>);

impl SharedVolume {
    pub fn new(initial: f32) -> Self {
        Self(Arc::new(AtomicU32::new(initial.to_bits())))
    }

    pub fn set(&self, gain: f32) {
        self.0.store(gain.to_bits(), Ordering::Relaxed);
    }

    pub fn get(&self) -> f32 {
        f32::from_bits(self.0.load(Ordering::Relaxed))
    }
}

impl Default for SharedVolume {
    fn default() -> Self {
        Self::new(1.0)
    }
}

pub struct VolumePcmProcessor {
    volume: SharedVolume,
}

impl VolumePcmProcessor {
    pub fn new(volume: SharedVolume) -> Self {
        Self { volume }
    }
}

impl PcmProcessor for VolumePcmProcessor {
    fn name(&self) -> &'static str {
        "volume"
    }

    fn process(&mut self, mut slab: PcmSlab) -> Result<PcmSlab, String> {
        let gain = self.volume.get();
        // Skip processing when gain is unity (1.0).
        if (gain - 1.0).abs() < 1e-6 {
            return Ok(slab);
        }
        match slab.spec.format {
            PcmSampleFormat::S16LE => {
                apply_gain_i16(&mut slab.data, gain);
            }
            PcmSampleFormat::S24_3LE => {
                apply_gain_i24_3le(&mut slab.data, gain);
            }
            PcmSampleFormat::S24LE | PcmSampleFormat::S32LE => {
                apply_gain_i32(&mut slab.data, gain);
            }
            PcmSampleFormat::F32LE => {
                apply_gain_f32(&mut slab.data, gain);
            }
            PcmSampleFormat::F64LE => {
                apply_gain_f64(&mut slab.data, gain);
            }
        }
        Ok(slab)
    }
}

fn apply_gain_i16(data: &mut [u8], gain: f32) {
    for chunk in data.chunks_exact_mut(2) {
        let sample = i16::from_le_bytes([chunk[0], chunk[1]]);
        let scaled = (sample as f32 * gain).round().clamp(i16::MIN as f32, i16::MAX as f32) as i16;
        let bytes = scaled.to_le_bytes();
        chunk[0] = bytes[0];
        chunk[1] = bytes[1];
    }
}

fn apply_gain_i24_3le(data: &mut [u8], gain: f32) {
    for chunk in data.chunks_exact_mut(3) {
        let raw = (chunk[0] as i32) | ((chunk[1] as i32) << 8) | ((chunk[2] as i8 as i32) << 16);
        let scaled = (raw as f32 * gain).round().clamp(-8388608.0, 8388607.0) as i32;
        chunk[0] = scaled as u8;
        chunk[1] = (scaled >> 8) as u8;
        chunk[2] = (scaled >> 16) as u8;
    }
}

fn apply_gain_i32(data: &mut [u8], gain: f32) {
    for chunk in data.chunks_exact_mut(4) {
        let sample = i32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
        let scaled = (sample as f64 * gain as f64).round().clamp(i32::MIN as f64, i32::MAX as f64) as i32;
        let bytes = scaled.to_le_bytes();
        chunk.copy_from_slice(&bytes);
    }
}

fn apply_gain_f32(data: &mut [u8], gain: f32) {
    for chunk in data.chunks_exact_mut(4) {
        let sample = f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
        let scaled = sample * gain;
        chunk.copy_from_slice(&scaled.to_le_bytes());
    }
}

fn apply_gain_f64(data: &mut [u8], gain: f32) {
    for chunk in data.chunks_exact_mut(8) {
        let sample = f64::from_le_bytes([
            chunk[0], chunk[1], chunk[2], chunk[3],
            chunk[4], chunk[5], chunk[6], chunk[7],
        ]);
        let scaled = sample * gain as f64;
        chunk.copy_from_slice(&scaled.to_le_bytes());
    }
}

// ---------------------------------------------------------------------------
// Spectrum analysis processor
// ---------------------------------------------------------------------------

/// Maximum number of spectrum bands (matches lib.rs SPECTRUM_BANDS_MAX).
pub const SPECTRUM_BANDS_MAX: usize = 4096;

/// A single spectrum analysis frame, ready for the engine's spectrum ring.
impl std::fmt::Debug for SpectrumFrame {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SpectrumFrame")
            .field("bands", &self.bands)
            .field("pos_s", &self.pos_s)
            .finish_non_exhaustive()
    }
}

pub struct SpectrumFrame {
    pub mono: Box<[f32; SPECTRUM_BANDS_MAX]>,
    pub left: Box<[f32; SPECTRUM_BANDS_MAX]>,
    pub right: Box<[f32; SPECTRUM_BANDS_MAX]>,
    pub bands: u16,
    pub pos_s: f64,
}

/// Spectrum processor: accumulates PCM into a window, runs FFT at a fixed
/// interval (~16ms), and sends `SpectrumFrame`s to the engine via a channel.
pub struct SpectrumPcmProcessor {
    tx: Sender<SpectrumFrame>,
    bands: usize,
    bands_source: Arc<AtomicU32>,
    threshold_db: f32,
    // Per-channel ring buffers (up to 2 channels for stereo).
    window_left: Vec<f32>,
    window_right: Vec<f32>,
    window_pos: usize,
    window_size: usize, // FFT size = bands * 2
    // How many samples we've accumulated since last FFT emit.
    samples_since_emit: usize,
    // How many samples per emit interval (~16ms worth).
    samples_per_interval: usize,
    // Total frames decoded so far (for position tracking).
    total_frames: u64,
    sample_rate: u32,
    channels: usize,
    configured: bool,
}

impl SpectrumPcmProcessor {
    pub fn new(tx: Sender<SpectrumFrame>, bands_source: Arc<AtomicU32>) -> Self {
        let bands = (bands_source.load(Ordering::Relaxed) as usize).clamp(2, SPECTRUM_BANDS_MAX);
        let window_size = bands * 2; // FFT size
        Self {
            tx,
            bands,
            bands_source,
            threshold_db: -80.0,
            window_left: vec![0.0; window_size],
            window_right: vec![0.0; window_size],
            window_pos: 0,
            window_size,
            samples_since_emit: 0,
            samples_per_interval: 0,
            total_frames: 0,
            sample_rate: 0,
            channels: 0,
            configured: false,
        }
    }

    /// Check if bands changed from external source and reconfigure if needed.
    fn sync_bands(&mut self) {
        let new_bands = (self.bands_source.load(Ordering::Relaxed) as usize).clamp(2, SPECTRUM_BANDS_MAX);
        if new_bands != self.bands {
            self.bands = new_bands;
            self.window_size = new_bands * 2;
            self.window_left = vec![0.0; self.window_size];
            self.window_right = vec![0.0; self.window_size];
            self.window_pos = 0;
        }
    }

    fn emit_spectrum(&mut self) {
        let mut planner = FftPlanner::<f32>::new();
        let fft = planner.plan_fft_forward(self.window_size);

        // Apply Hann window and prepare complex buffers.
        let mut buf_left: Vec<Complex<f32>> = Vec::with_capacity(self.window_size);
        let mut buf_right: Vec<Complex<f32>> = Vec::with_capacity(self.window_size);
        for i in 0..self.window_size {
            let idx = (self.window_pos + i) % self.window_size;
            let w = 0.5 * (1.0 - (2.0 * std::f32::consts::PI * i as f32 / self.window_size as f32).cos());
            buf_left.push(Complex { re: self.window_left[idx] * w, im: 0.0 });
            buf_right.push(Complex { re: self.window_right[idx] * w, im: 0.0 });
        }

        fft.process(&mut buf_left);
        fft.process(&mut buf_right);

        let mut mono = Box::new([0.0f32; SPECTRUM_BANDS_MAX]);
        let mut left = Box::new([0.0f32; SPECTRUM_BANDS_MAX]);
        let mut right = Box::new([0.0f32; SPECTRUM_BANDS_MAX]);

        let norm = 1.0 / self.window_size as f32;
        for i in 0..self.bands {
            let mag_l = buf_left[i].norm() * norm;
            let mag_r = buf_right[i].norm() * norm;
            // Convert to dB, clamp to threshold.
            let db_l = if mag_l > 0.0 { 20.0 * mag_l.log10() } else { self.threshold_db };
            let db_r = if mag_r > 0.0 { 20.0 * mag_r.log10() } else { self.threshold_db };
            left[i] = db_l.max(self.threshold_db);
            right[i] = db_r.max(self.threshold_db);
            mono[i] = (left[i] + right[i]) * 0.5;
        }

        let pos_s = if self.sample_rate > 0 {
            self.total_frames as f64 / self.sample_rate as f64
        } else {
            0.0
        };

        let _ = self.tx.try_send(SpectrumFrame {
            mono,
            left,
            right,
            bands: self.bands as u16,
            pos_s,
        });
    }
}

impl PcmProcessor for SpectrumPcmProcessor {
    fn name(&self) -> &'static str {
        "spectrum"
    }

    fn configure(&mut self, spec: &PcmStreamSpec) -> Result<(), String> {
        self.sample_rate = spec.sample_rate;
        self.channels = spec.channels;
        // ~16ms interval to match GStreamer spectrum element.
        self.samples_per_interval = (spec.sample_rate as usize * 16) / 1000;
        self.window_left = vec![0.0; self.window_size];
        self.window_right = vec![0.0; self.window_size];
        self.window_pos = 0;
        self.samples_since_emit = 0;
        self.total_frames = 0;
        self.configured = true;
        Ok(())
    }

    fn process(&mut self, slab: PcmSlab) -> Result<PcmSlab, String> {
        if !self.configured || self.channels == 0 {
            return Ok(slab);
        }
        self.sync_bands();
        // Extract f32 samples per frame from the slab for spectrum analysis.
        let bytes_per_sample = match slab.spec.format {
            PcmSampleFormat::S16LE => 2,
            PcmSampleFormat::S24_3LE => 3,
            PcmSampleFormat::S24LE | PcmSampleFormat::S32LE => 4,
            PcmSampleFormat::F32LE => 4,
            PcmSampleFormat::F64LE => 8,
        };
        let frame_bytes = bytes_per_sample * self.channels;
        let data = &slab.data;

        for frame_start in (0..data.len()).step_by(frame_bytes) {
            if frame_start + frame_bytes > data.len() {
                break;
            }
            // Extract left channel (channel 0) sample as f32.
            let left_sample = sample_to_f32(&data[frame_start..frame_start + bytes_per_sample], slab.spec.format);
            // Extract right channel (channel 1) or duplicate mono.
            let right_sample = if self.channels >= 2 {
                let offset = frame_start + bytes_per_sample;
                sample_to_f32(&data[offset..offset + bytes_per_sample], slab.spec.format)
            } else {
                left_sample
            };

            self.window_left[self.window_pos] = left_sample;
            self.window_right[self.window_pos] = right_sample;
            self.window_pos = (self.window_pos + 1) % self.window_size;
            self.total_frames += 1;
            self.samples_since_emit += 1;

            if self.samples_since_emit >= self.samples_per_interval && self.samples_per_interval > 0 {
                self.emit_spectrum();
                self.samples_since_emit = 0;
            }
        }

        Ok(slab)
    }
}

// ---------------------------------------------------------------------------
// LUFS meter processor
// ---------------------------------------------------------------------------

/// Shared LUFS values: written by LufsPcmProcessor, read by Engine via rac_get_lufs.
pub type SharedLufsValues = Arc<Mutex<LufsValues>>;

pub struct LufsPcmProcessor {
    state: LufsState,
    shared: SharedLufsValues,
    f64_buf: Vec<f64>,
}

impl LufsPcmProcessor {
    pub fn new(shared: SharedLufsValues) -> Self {
        Self {
            state: LufsState::new(),
            shared,
            f64_buf: Vec::new(),
        }
    }
}

impl PcmProcessor for LufsPcmProcessor {
    fn name(&self) -> &'static str {
        "lufs"
    }

    fn configure(&mut self, spec: &PcmStreamSpec) -> Result<(), String> {
        self.state.update_rate_channels(spec.sample_rate, spec.channels);
        self.state.reset();
        Ok(())
    }

    fn process(&mut self, slab: PcmSlab) -> Result<PcmSlab, String> {
        // Convert PCM to interleaved f64 for LufsState::process.
        let bytes_per_sample = match slab.spec.format {
            PcmSampleFormat::S16LE => 2,
            PcmSampleFormat::S24_3LE => 3,
            PcmSampleFormat::S24LE | PcmSampleFormat::S32LE => 4,
            PcmSampleFormat::F32LE => 4,
            PcmSampleFormat::F64LE => 8,
        };
        let total_samples = slab.data.len() / bytes_per_sample;
        self.f64_buf.clear();
        self.f64_buf.reserve(total_samples);
        for chunk in slab.data.chunks_exact(bytes_per_sample) {
            self.f64_buf.push(sample_to_f64(chunk, slab.spec.format));
        }
        self.state.process(&self.f64_buf);
        // Publish latest values (try_lock to avoid blocking the decode thread).
        if let Ok(mut vals) = self.shared.try_lock() {
            *vals = self.state.values.clone();
        }
        Ok(slab)
    }
}

fn sample_to_f64(bytes: &[u8], format: PcmSampleFormat) -> f64 {
    match format {
        PcmSampleFormat::S16LE => {
            let v = i16::from_le_bytes([bytes[0], bytes[1]]);
            v as f64 / 32768.0
        }
        PcmSampleFormat::S24_3LE => {
            let raw = (bytes[0] as i32) | ((bytes[1] as i32) << 8) | ((bytes[2] as i8 as i32) << 16);
            raw as f64 / 8388608.0
        }
        PcmSampleFormat::S24LE | PcmSampleFormat::S32LE => {
            let v = i32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
            v as f64 / 2147483648.0
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

fn sample_to_f32(bytes: &[u8], format: PcmSampleFormat) -> f32 {
    match format {
        PcmSampleFormat::S16LE => {
            let v = i16::from_le_bytes([bytes[0], bytes[1]]);
            v as f32 / 32768.0
        }
        PcmSampleFormat::S24_3LE => {
            let raw = (bytes[0] as i32) | ((bytes[1] as i32) << 8) | ((bytes[2] as i8 as i32) << 16);
            raw as f32 / 8388608.0
        }
        PcmSampleFormat::S24LE | PcmSampleFormat::S32LE => {
            let v = i32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
            v as f32 / 2147483648.0
        }
        PcmSampleFormat::F32LE => {
            f32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]])
        }
        PcmSampleFormat::F64LE => {
            let v = f64::from_le_bytes([
                bytes[0], bytes[1], bytes[2], bytes[3],
                bytes[4], bytes[5], bytes[6], bytes[7],
            ]);
            v as f32
        }
    }
}
