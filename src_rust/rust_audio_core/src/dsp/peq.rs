use gst::glib;
use gst::prelude::*;
use gstreamer as gst;
use std::f64::consts::PI;

pub const PEQ_BAND_COUNT: usize = 10;

const PEQ_MIN_GAIN_DB: f64 = -24.0;
const PEQ_MAX_GAIN_DB: f64 = 12.0;
const PEQ_CENTER_FREQS_HZ: [f64; PEQ_BAND_COUNT] = [
    30.0, 60.0, 120.0, 240.0, 480.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0,
];

#[derive(Clone, Debug, PartialEq)]
pub struct PeqConfig {
    pub enabled: bool,
    pub band_gains_db: [f64; PEQ_BAND_COUNT],
}

impl Default for PeqConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            band_gains_db: [0.0; PEQ_BAND_COUNT],
        }
    }
}

impl PeqConfig {
    pub fn set_enabled(&mut self, enabled: bool) {
        self.enabled = enabled;
    }

    pub fn is_flat(&self) -> bool {
        self.band_gains_db.iter().all(|gain| gain.abs() < 0.001)
    }

    pub fn is_active(&self) -> bool {
        self.enabled && !self.is_flat()
    }

    pub fn set_band_gain(&mut self, band_index: usize, gain_db: f64) -> Result<f64, String> {
        if band_index >= PEQ_BAND_COUNT {
            return Err(format!("peq band index out of range: {band_index}"));
        }
        let clamped = gain_db.clamp(PEQ_MIN_GAIN_DB, PEQ_MAX_GAIN_DB);
        self.band_gains_db[band_index] = clamped;
        self.enabled = !self.is_flat();
        Ok(clamped)
    }

    pub fn reset(&mut self) {
        self.enabled = false;
        self.band_gains_db = [0.0; PEQ_BAND_COUNT];
    }
}

pub struct PeqNode {
    element: gst::Element,
    band_objects: Vec<glib::Object>,
}

impl std::fmt::Debug for PeqNode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "PeqNode(bands={})", self.band_objects.len())
    }
}

impl PeqNode {
    pub fn new() -> Result<Self, String> {
        let element = gst::ElementFactory::make("equalizer-nbands")
            .name("rust-dsp-peq")
            .build()
            .map_err(|e| format!("equalizer-nbands unavailable: {e}"))?;
        element.set_property("num-bands", PEQ_BAND_COUNT as u32);
        let child_proxy = element
            .clone()
            .dynamic_cast::<gst::ChildProxy>()
            .map_err(|_| "equalizer-nbands does not implement ChildProxy".to_string())?;

        let mut band_objects = Vec::with_capacity(PEQ_BAND_COUNT);
        for idx in 0..PEQ_BAND_COUNT {
            let Some(band) = child_proxy.child_by_index(idx as u32) else {
                return Err(format!("equalizer-nbands missing band child {idx}"));
            };
            band_objects.push(band);
        }

        let mut node = Self {
            element,
            band_objects,
        };
        node.configure_band_layout()?;
        node.reset()?;
        Ok(node)
    }

    pub fn element(&self) -> &gst::Element {
        &self.element
    }

    pub fn apply_config(&mut self, config: &PeqConfig) -> Result<(), String> {
        if !config.enabled {
            return self.reset();
        }
        for (idx, gain) in config.band_gains_db.iter().enumerate() {
            self.set_band_gain(idx, *gain)?;
        }
        Ok(())
    }

    pub fn reset(&mut self) -> Result<(), String> {
        for idx in 0..self.band_objects.len() {
            self.set_band_gain(idx, 0.0)?;
        }
        Ok(())
    }

    pub fn set_band_gain(&mut self, band_index: usize, gain_db: f64) -> Result<(), String> {
        let Some(band) = self.band_objects.get(band_index) else {
            return Err(format!("peq band index out of range: {band_index}"));
        };
        band.set_property("gain", gain_db.clamp(PEQ_MIN_GAIN_DB, PEQ_MAX_GAIN_DB));
        Ok(())
    }

    fn configure_band_layout(&mut self) -> Result<(), String> {
        for (idx, band) in self.band_objects.iter().enumerate() {
            let freq = PEQ_CENTER_FREQS_HZ[idx];
            let lower = if idx == 0 {
                freq / 2.0_f64.sqrt()
            } else {
                (PEQ_CENTER_FREQS_HZ[idx - 1] * freq).sqrt()
            };
            let upper = if idx + 1 >= PEQ_CENTER_FREQS_HZ.len() {
                freq * 2.0_f64.sqrt()
            } else {
                (freq * PEQ_CENTER_FREQS_HZ[idx + 1]).sqrt()
            };
            let bandwidth = (upper - lower).max(1.0);
            band.set_property("freq", freq);
            band.set_property("bandwidth", bandwidth);
        }
        Ok(())
    }
}

// ── Pure-Rust PEQ state (for native transport, no GStreamer dependency) ──────

/// Per-channel biquad filter state for one EQ band.
#[derive(Debug, Clone)]
struct PeqBiquad {
    b0: f64,
    b1: f64,
    b2: f64,
    a1: f64,
    a2: f64,
    z1: f64,
    z2: f64,
}

impl Default for PeqBiquad {
    fn default() -> Self {
        Self { b0: 1.0, b1: 0.0, b2: 0.0, a1: 0.0, a2: 0.0, z1: 0.0, z2: 0.0 }
    }
}

impl PeqBiquad {
    #[inline]
    fn process(&mut self, x: f64) -> f64 {
        let y = self.b0 * x + self.z1;
        self.z1 = self.b1 * x - self.a1 * y + self.z2;
        self.z2 = self.b2 * x - self.a2 * y;
        y
    }

    /// Peaking EQ filter (Audio EQ Cookbook).
    /// `fc` = center freq, `gain_db` = boost/cut, `bw_hz` = bandwidth in Hz.
    fn peaking(fc: f64, gain_db: f64, bw_hz: f64, sr: f64) -> Self {
        if gain_db.abs() < 0.001 || sr <= 0.0 {
            return Self::default();
        }
        let a = 10f64.powf(gain_db / 40.0);
        let w0 = 2.0 * PI * fc / sr;
        let cos_w0 = w0.cos();
        let sin_w0 = w0.sin();
        // Q from bandwidth: Q = fc / bw
        let q = (fc / bw_hz.max(1.0)).max(0.1);
        let alpha = sin_w0 / (2.0 * q);

        let b0 = 1.0 + alpha * a;
        let b1 = -2.0 * cos_w0;
        let b2 = 1.0 - alpha * a;
        let a0 = 1.0 + alpha / a;
        let a1 = -2.0 * cos_w0;
        let a2 = 1.0 - alpha / a;

        Self {
            b0: b0 / a0,
            b1: b1 / a0,
            b2: b2 / a0,
            a1: a1 / a0,
            a2: a2 / a0,
            z1: 0.0,
            z2: 0.0,
        }
    }
}

/// Pure-Rust parametric EQ state: 10-band peaking EQ with per-channel biquads.
#[derive(Debug)]
pub(crate) struct PeqState {
    enabled: bool,
    gains_db: [f64; PEQ_BAND_COUNT],
    stream_rate: u32,
    /// filters[band][channel]
    filters: [[PeqBiquad; 2]; PEQ_BAND_COUNT],
}

impl PeqState {
    pub(crate) fn new() -> Self {
        Self {
            enabled: false,
            gains_db: [0.0; PEQ_BAND_COUNT],
            stream_rate: 44_100,
            filters: std::array::from_fn(|_| [PeqBiquad::default(), PeqBiquad::default()]),
        }
    }

    fn bandwidth_for_band(idx: usize) -> f64 {
        let freq = PEQ_CENTER_FREQS_HZ[idx];
        let lower = if idx == 0 {
            freq / 2.0_f64.sqrt()
        } else {
            (PEQ_CENTER_FREQS_HZ[idx - 1] * freq).sqrt()
        };
        let upper = if idx + 1 >= PEQ_BAND_COUNT {
            freq * 2.0_f64.sqrt()
        } else {
            (freq * PEQ_CENTER_FREQS_HZ[idx + 1]).sqrt()
        };
        (upper - lower).max(1.0)
    }

    fn rebuild_filters(&mut self) {
        let sr = self.stream_rate.max(8_000) as f64;
        for (band_idx, gain_db) in self.gains_db.iter().enumerate() {
            let fc = PEQ_CENTER_FREQS_HZ[band_idx];
            if fc >= sr * 0.45 {
                // Above Nyquist safety margin — bypass this band.
                for ch in 0..2 {
                    self.filters[band_idx][ch] = PeqBiquad::default();
                }
                continue;
            }
            let bw = Self::bandwidth_for_band(band_idx);
            let coeffs = PeqBiquad::peaking(fc, *gain_db, bw, sr);
            for ch in 0..2 {
                // Preserve delay-line state to avoid clicks on live updates.
                let z1 = self.filters[band_idx][ch].z1;
                let z2 = self.filters[band_idx][ch].z2;
                self.filters[band_idx][ch] = coeffs.clone();
                self.filters[band_idx][ch].z1 = z1;
                self.filters[band_idx][ch].z2 = z2;
            }
        }
    }

    pub(crate) fn update_rate(&mut self, rate: u32) {
        if rate == 0 || rate == self.stream_rate {
            return;
        }
        self.stream_rate = rate;
        self.rebuild_filters();
    }

    pub(crate) fn apply_config(&mut self, config: &PeqConfig) {
        self.enabled = config.enabled && !config.is_flat();
        self.gains_db = config.band_gains_db;
        self.rebuild_filters();
    }

    pub(crate) fn process(&mut self, samples: &mut [f64], channels: usize) {
        if !self.enabled || channels == 0 || samples.is_empty() {
            return;
        }
        let frames = samples.len() / channels;
        for frame_idx in 0..frames {
            for ch in 0..channels.min(2) {
                let idx = frame_idx * channels + ch;
                let mut x = samples[idx];
                for band in 0..PEQ_BAND_COUNT {
                    x = self.filters[band][ch].process(x);
                }
                samples[idx] = x;
            }
        }
    }
}
