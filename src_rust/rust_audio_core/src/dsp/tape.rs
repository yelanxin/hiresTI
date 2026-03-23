use gst::prelude::*;
use gst::PadProbeReturn;
use gst::PadProbeType;
use gstreamer as gst;
use std::f64::consts::PI;
use std::sync::{Arc, Mutex};

// ── Config ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, PartialEq)]
pub struct TapeConfig {
    pub enabled: bool,
    /// 0–100: saturation / harmonic distortion amount.
    pub drive: i32,
    /// 0–100: high-frequency presence (0 = dark, 100 = bright/open).
    pub tone: i32,
    /// 0–100: low-frequency shelf boost warmth.
    pub warmth: i32,
}

impl Default for TapeConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            drive: 30,
            tone: 60,
            warmth: 40,
        }
    }
}

impl TapeConfig {
    pub fn is_active(&self) -> bool {
        self.enabled
    }
    pub fn set_enabled(&mut self, v: bool) {
        self.enabled = v;
    }
    pub fn set_drive(&mut self, v: i32) {
        self.drive = v.clamp(0, 100);
    }
    pub fn set_tone(&mut self, v: i32) {
        self.tone = v.clamp(0, 100);
    }
    pub fn set_warmth(&mut self, v: i32) {
        self.warmth = v.clamp(0, 100);
    }
}

// ── Biquad (transposed direct form II) ───────────────────────────────────────

#[derive(Debug, Clone)]
struct Biquad {
    b0: f64,
    b1: f64,
    b2: f64,
    a1: f64,
    a2: f64,
    z1: f64,
    z2: f64,
}

impl Default for Biquad {
    fn default() -> Self {
        // Identity (pass-through).
        Self {
            b0: 1.0,
            b1: 0.0,
            b2: 0.0,
            a1: 0.0,
            a2: 0.0,
            z1: 0.0,
            z2: 0.0,
        }
    }
}

impl Biquad {
    #[inline]
    fn process(&mut self, x: f64) -> f64 {
        let y = self.b0 * x + self.z1;
        self.z1 = self.b1 * x - self.a1 * y + self.z2;
        self.z2 = self.b2 * x - self.a2 * y;
        y
    }

    /// First-order RC low-pass. `fc` in Hz, `sr` in Hz.
    fn lowpass_1st(fc: f64, sr: f64) -> Self {
        let a = (-2.0 * PI * fc / sr).exp();
        Self {
            b0: 1.0 - a,
            a1: -a,
            ..Default::default()
        }
    }

    /// Second-order low-shelf (Audio EQ Cookbook, shelf-slope S = 1).
    /// `gain_db` > 0 = boost. Returns identity if gain is negligible.
    fn low_shelf(fc: f64, gain_db: f64, sr: f64) -> Self {
        if gain_db.abs() < 0.05 {
            return Self::default();
        }
        let a = 10f64.powf(gain_db / 40.0);
        let w0 = 2.0 * PI * fc / sr;
        let cos_w0 = w0.cos();
        // alpha for S=1: sin(w0)/sqrt(2)
        let alpha = w0.sin() / std::f64::consts::SQRT_2;
        let sqrt_a = a.sqrt();

        let b0 = a * ((a + 1.0) - (a - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha);
        let b1 = 2.0 * a * ((a - 1.0) - (a + 1.0) * cos_w0);
        let b2 = a * ((a + 1.0) - (a - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha);
        let a0 = (a + 1.0) + (a - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha;
        let a1 = -2.0 * ((a - 1.0) + (a + 1.0) * cos_w0);
        let a2 = (a + 1.0) + (a - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha;

        Self {
            b0: b0 / a0,
            b1: b1 / a0,
            b2: b2 / a0,
            a1: a1 / a0,
            a2: a2 / a0,
            ..Default::default()
        }
    }
}

// ── Saturation ────────────────────────────────────────────────────────────────

/// Tape-style soft clipper.
///
/// Uses tanh with a slight asymmetric bias to generate even-order harmonics
/// (characteristic of magnetic hysteresis). Naturally compresses transients
/// more than sustained material (tape-like dynamic behaviour).
#[inline]
fn tape_saturate(x: f64, drive: f64) -> f64 {
    if drive < 1e-6 {
        return x;
    }
    // Pre-gain: 1× at drive=0, 4× at drive=1.
    let k = 1.0 + drive * 3.0;
    // Small fixed bias adds 2nd-harmonic character without audible DC.
    let bias = drive * 0.03;
    let y = (k * x + bias).tanh() - bias.tanh();
    // Divide by k to restore approximate unity gain for small signals.
    y / k
}

// ── State (per-stream) ────────────────────────────────────────────────────────

#[derive(Debug)]
struct TapeState {
    enabled: bool,
    drive: f64,
    tone: f64,
    warmth: f64,
    stream_rate: u32,
    /// One low-shelf filter per channel (up to 2 ch).
    lf: [Biquad; 2],
    /// One HF roll-off filter per channel.
    hf: [Biquad; 2],
}

impl TapeState {
    fn new() -> Self {
        let mut s = Self {
            enabled: false,
            drive: 0.30,
            tone: 0.60,
            warmth: 0.40,
            stream_rate: 44100,
            lf: [Biquad::default(), Biquad::default()],
            hf: [Biquad::default(), Biquad::default()],
        };
        s.rebuild_filters();
        s
    }

    fn rebuild_filters(&mut self) {
        let sr = self.stream_rate.max(8000) as f64;
        // HF roll-off: tone=0 → 6 kHz, tone=1 → 18 kHz.
        let hf_fc = (6_000.0 + self.tone * 12_000.0).min(sr * 0.45);
        // Warmth shelf: 0 dB at warmth=0, +4 dB at warmth=1, centred at 200 Hz.
        let lf_gain_db = self.warmth * 4.0;

        for ch in 0..2 {
            self.hf[ch] = Biquad::lowpass_1st(hf_fc, sr);
            self.lf[ch] = Biquad::low_shelf(200.0, lf_gain_db, sr);
        }
    }

    fn update_rate(&mut self, rate: u32) {
        if rate == 0 || rate == self.stream_rate {
            return;
        }
        self.stream_rate = rate;
        self.rebuild_filters();
    }

    fn apply_config(&mut self, config: &TapeConfig) {
        self.enabled = config.enabled;
        self.drive = config.drive as f64 / 100.0;
        self.tone = config.tone as f64 / 100.0;
        self.warmth = config.warmth as f64 / 100.0;
        self.rebuild_filters();
    }

    fn process(&mut self, samples: &mut [f64], channels: usize) {
        if !self.enabled || channels == 0 || samples.is_empty() {
            return;
        }
        let frames = samples.len() / channels;
        let drive = self.drive;

        for f in 0..frames {
            for ch in 0..channels.min(2) {
                let idx = f * channels + ch;
                let x = samples[idx];
                // 1. Low-shelf warmth boost (pre-saturation).
                let x = self.lf[ch].process(x);
                // 2. Tape saturation (harmonic distortion).
                let x = tape_saturate(x, drive);
                // 3. HF roll-off (tape bandwidth limiting).
                let x = self.hf[ch].process(x);
                samples[idx] = x;
            }
        }
    }
}

// ── GStreamer node ────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct TapeNode {
    bin: gst::Bin,
    state: Arc<Mutex<TapeState>>,
}

impl TapeNode {
    pub fn new() -> Result<Self, String> {
        let bin = gst::Bin::new();

        let identity = gst::ElementFactory::make("identity")
            .name("rust-dsp-tape")
            .build()
            .map_err(|e| format!("identity (tape) unavailable: {e}"))?;

        bin.add(&identity)
            .map_err(|_| "failed to add tape identity".to_string())?;

        let state = Arc::new(Mutex::new(TapeState::new()));

        // Pad probe on the sink pad (before identity copies the buffer).
        let sink_pad = identity
            .static_pad("sink")
            .ok_or("tape identity missing sink pad")?;

        let state_probe = Arc::clone(&state);
        sink_pad.add_probe(PadProbeType::BUFFER, move |pad, info| {
            let Some(gst::PadProbeData::Buffer(ref mut buf)) = info.data else {
                return PadProbeReturn::Ok;
            };
            // Detect stream sample rate from caps.
            if let Some(caps) = pad.current_caps() {
                if let Some(s) = caps.structure(0) {
                    if let Ok(rate) = s.get::<i32>("rate") {
                        if let Ok(mut st) = state_probe.lock() {
                            st.update_rate(rate as u32);
                        }
                    }
                }
            }
            let buf = buf.make_mut();
            let Ok(mut map) = buf.map_writable() else {
                return PadProbeReturn::Ok;
            };
            let bytes: &mut [u8] = map.as_mut_slice();
            if bytes.len() < 8 || bytes.len() % 8 != 0 {
                return PadProbeReturn::Ok;
            }
            // Reinterpret as f64 samples (pipeline runs F64LE after in_convert).
            let samples: &mut [f64] = unsafe {
                std::slice::from_raw_parts_mut(bytes.as_mut_ptr() as *mut f64, bytes.len() / 8)
            };
            // Get channel count from caps.
            let channels = if let Some(caps) = pad.current_caps() {
                caps.structure(0)
                    .and_then(|s| s.get::<i32>("channels").ok())
                    .unwrap_or(2) as usize
            } else {
                2
            };
            if let Ok(mut st) = state_probe.lock() {
                st.process(samples, channels);
            }
            PadProbeReturn::Ok
        });

        let sink_pad = identity.static_pad("sink").ok_or("tape missing sink pad")?;
        let src_pad = identity.static_pad("src").ok_or("tape missing src pad")?;

        let ghost_sink = gst::GhostPad::with_target(&sink_pad)
            .map_err(|_| "failed to create tape ghost sink".to_string())?;
        let ghost_src = gst::GhostPad::with_target(&src_pad)
            .map_err(|_| "failed to create tape ghost src".to_string())?;

        bin.add_pad(&ghost_sink)
            .map_err(|_| "failed to add tape ghost sink".to_string())?;
        bin.add_pad(&ghost_src)
            .map_err(|_| "failed to add tape ghost src".to_string())?;

        Ok(Self { bin, state })
    }

    pub fn element(&self) -> &gst::Element {
        self.bin.upcast_ref()
    }

    pub fn apply_config(&mut self, config: &TapeConfig) -> Result<(), String> {
        if let Ok(mut st) = self.state.lock() {
            st.apply_config(config);
        }
        Ok(())
    }
}
