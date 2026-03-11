use gst::PadProbeReturn;
use gst::PadProbeType;
use gst::prelude::*;
use gstreamer as gst;
use std::f64::consts::PI;
use std::sync::{Arc, Mutex};

#[derive(Clone, Debug, PartialEq)]
pub struct TubeConfig {
    pub enabled: bool,
    pub drive: i32,
    pub bias: i32,
    pub sag: i32,
    pub air: i32,
}

impl Default for TubeConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            drive: 28,
            bias: 55,
            sag: 18,
            air: 52,
        }
    }
}

impl TubeConfig {
    pub fn is_active(&self) -> bool {
        self.enabled
    }
    pub fn set_enabled(&mut self, value: bool) { self.enabled = value; }
    pub fn set_drive(&mut self, value: i32) { self.drive = value.clamp(0, 100); }
    pub fn set_bias(&mut self, value: i32) { self.bias = value.clamp(0, 100); }
    pub fn set_sag(&mut self, value: i32) { self.sag = value.clamp(0, 100); }
    pub fn set_air(&mut self, value: i32) { self.air = value.clamp(0, 100); }
}

#[derive(Debug, Clone)]
struct Biquad {
    b0: f64, b1: f64, b2: f64,
    a1: f64, a2: f64,
    z1: f64, z2: f64,
}

impl Default for Biquad {
    fn default() -> Self {
        Self { b0: 1.0, b1: 0.0, b2: 0.0, a1: 0.0, a2: 0.0, z1: 0.0, z2: 0.0 }
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

    fn lowpass_1st(fc: f64, sr: f64) -> Self {
        let a = (-2.0 * PI * fc / sr).exp();
        Self { b0: 1.0 - a, a1: -a, ..Default::default() }
    }
}

#[inline]
fn tube_saturate(x: f64, drive: f64, bias: f64) -> f64 {
    if drive < 1e-6 {
        return x;
    }
    let pregain = 1.0 + (drive * 4.0);
    let dc_bias = (bias - 0.5) * 0.18;
    let pos_curve = 1.0 + (bias * 0.9);
    let neg_curve = 1.0 + ((1.0 - bias) * 0.9);
    let y = pregain * x + dc_bias;
    let shaped = if y >= 0.0 {
        (y * pos_curve).tanh() / pos_curve
    } else {
        (y * neg_curve).tanh() / neg_curve
    };
    (shaped - dc_bias.tanh()) / pregain
}

#[derive(Debug)]
struct TubeState {
    enabled: bool,
    drive: f64,
    bias: f64,
    sag: f64,
    air: f64,
    stream_rate: u32,
    env: f64,
    hf: [Biquad; 2],
}

impl TubeState {
    fn new() -> Self {
        let mut state = Self {
            enabled: false,
            drive: 0.28,
            bias: 0.55,
            sag: 0.18,
            air: 0.52,
            stream_rate: 44_100,
            env: 0.0,
            hf: [Biquad::default(), Biquad::default()],
        };
        state.rebuild_filters();
        state
    }

    fn rebuild_filters(&mut self) {
        let sr = self.stream_rate.max(8_000) as f64;
        let fc = (6_500.0 + (self.air * 13_500.0)).min(sr * 0.45);
        for ch in 0..2 {
            let new_filter = Biquad::lowpass_1st(fc, sr);
            // Only update coefficients; preserve z1/z2 to avoid a click
            // from resetting the filter delay lines mid-stream.
            self.hf[ch].b0 = new_filter.b0;
            self.hf[ch].b1 = new_filter.b1;
            self.hf[ch].b2 = new_filter.b2;
            self.hf[ch].a1 = new_filter.a1;
            self.hf[ch].a2 = new_filter.a2;
        }
    }

    fn update_rate(&mut self, rate: u32) {
        if rate == 0 || rate == self.stream_rate {
            return;
        }
        self.stream_rate = rate;
        self.rebuild_filters();
    }

    fn apply_config(&mut self, config: &TubeConfig) {
        let new_air = config.air as f64 / 100.0;
        let needs_filter_rebuild = (new_air - self.air).abs() > 1e-9;
        self.enabled = config.enabled;
        self.drive = config.drive as f64 / 100.0;
        self.bias = config.bias as f64 / 100.0;
        self.sag = config.sag as f64 / 100.0;
        self.air = new_air;
        if needs_filter_rebuild {
            self.rebuild_filters();
        }
    }

    fn process(&mut self, samples: &mut [f64], channels: usize) {
        if !self.enabled || channels == 0 || samples.is_empty() {
            return;
        }
        let frames = samples.len() / channels;
        let attack = 0.18;
        let release = 0.0018;

        for frame_idx in 0..frames {
            let mut peak = 0.0f64;
            for ch in 0..channels.min(2) {
                let idx = frame_idx * channels + ch;
                peak = peak.max(samples[idx].abs());
            }
            if peak > self.env {
                self.env += (peak - self.env) * attack;
            } else {
                self.env += (peak - self.env) * release;
            }
            let sag_depth = self.sag * 0.22;
            let sag_gain = 1.0 - sag_depth * ((self.env - 0.18).max(0.0) / 0.82).min(1.0);

            for ch in 0..channels.min(2) {
                let idx = frame_idx * channels + ch;
                let x = samples[idx] * sag_gain;
                let x = tube_saturate(x, self.drive, self.bias);
                let x = self.hf[ch].process(x);
                samples[idx] = x;
            }
        }
    }
}

#[derive(Debug)]
pub struct TubeNode {
    bin: gst::Bin,
    state: Arc<Mutex<TubeState>>,
}

impl TubeNode {
    pub fn new() -> Result<Self, String> {
        let bin = gst::Bin::new();
        let identity = gst::ElementFactory::make("identity")
            .name("rust-dsp-tube")
            .build()
            .map_err(|e| format!("identity (tube) unavailable: {e}"))?;

        bin.add(&identity)
            .map_err(|_| "failed to add tube identity".to_string())?;

        let state = Arc::new(Mutex::new(TubeState::new()));
        let sink_pad = identity
            .static_pad("sink")
            .ok_or("tube identity missing sink pad")?;

        let state_probe = Arc::clone(&state);
        sink_pad.add_probe(PadProbeType::BUFFER, move |pad, info| {
            let Some(gst::PadProbeData::Buffer(ref mut buf)) = info.data else {
                return PadProbeReturn::Ok;
            };
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
            let samples: &mut [f64] = unsafe {
                std::slice::from_raw_parts_mut(bytes.as_mut_ptr() as *mut f64, bytes.len() / 8)
            };
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

        let sink_pad = identity.static_pad("sink").ok_or("tube missing sink pad")?;
        let src_pad = identity.static_pad("src").ok_or("tube missing src pad")?;
        let ghost_sink = gst::GhostPad::with_target(&sink_pad)
            .map_err(|_| "failed to create tube ghost sink".to_string())?;
        let ghost_src = gst::GhostPad::with_target(&src_pad)
            .map_err(|_| "failed to create tube ghost src".to_string())?;
        bin.add_pad(&ghost_sink)
            .map_err(|_| "failed to add tube ghost sink".to_string())?;
        bin.add_pad(&ghost_src)
            .map_err(|_| "failed to add tube ghost src".to_string())?;

        Ok(Self { bin, state })
    }

    pub fn element(&self) -> &gst::Element {
        self.bin.upcast_ref()
    }

    pub fn apply_config(&mut self, config: &TubeConfig) -> Result<(), String> {
        if let Ok(mut st) = self.state.lock() {
            st.apply_config(config);
        }
        Ok(())
    }
}
