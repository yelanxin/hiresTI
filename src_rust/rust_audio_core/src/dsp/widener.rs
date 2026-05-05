#[derive(Clone, Debug, PartialEq)]
pub struct WidenerConfig {
    pub enabled: bool,
    pub width: i32,
    pub bass_mono_freq: i32,
    pub bass_mono_amount: i32,
}

impl Default for WidenerConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            width: 125,
            bass_mono_freq: 120,
            bass_mono_amount: 100,
        }
    }
}

impl WidenerConfig {
    pub fn is_active(&self) -> bool {
        self.enabled && (self.width != 100 || self.bass_mono_amount > 0)
    }
    pub fn set_enabled(&mut self, value: bool) {
        self.enabled = value;
    }
    pub fn set_width(&mut self, value: i32) {
        self.width = value.clamp(0, 200);
    }
    pub fn set_bass_mono_freq(&mut self, value: i32) {
        self.bass_mono_freq = value.clamp(40, 250);
    }
    pub fn set_bass_mono_amount(&mut self, value: i32) {
        self.bass_mono_amount = value.clamp(0, 100);
    }
}

#[derive(Debug)]
pub(crate) struct WidenerState {
    enabled: bool,
    width: f64,
    bass_mono_freq: f64,
    bass_mono_amount: f64,
    stream_rate: u32,
    side_lp_alpha: f64,
    side_lp_z1: f64,
}

impl WidenerState {
    pub(crate) fn new() -> Self {
        Self {
            enabled: false,
            width: 1.25,
            bass_mono_freq: 120.0,
            bass_mono_amount: 1.0,
            stream_rate: 44_100,
            side_lp_alpha: 0.0,
            side_lp_z1: 0.0,
        }
    }

    fn rebuild_filters(&mut self) {
        let sr = self.stream_rate.max(8_000) as f64;
        let fc = self.bass_mono_freq.clamp(40.0, (sr * 0.45).max(40.0));
        let a = (-2.0 * std::f64::consts::PI * fc / sr).exp();
        self.side_lp_alpha = 1.0 - a;
    }

    pub(crate) fn update_rate(&mut self, rate: u32) {
        if rate == 0 || rate == self.stream_rate {
            return;
        }
        self.stream_rate = rate;
        self.rebuild_filters();
    }

    pub(crate) fn apply_config(&mut self, config: &WidenerConfig) {
        self.enabled = config.enabled;
        self.width = (config.width.clamp(0, 200) as f64) / 100.0;
        self.bass_mono_freq = config.bass_mono_freq.clamp(40, 250) as f64;
        self.bass_mono_amount = (config.bass_mono_amount.clamp(0, 100) as f64) / 100.0;
        self.rebuild_filters();
    }

    pub(crate) fn process(&mut self, samples: &mut [f64], channels: usize) {
        if !self.enabled || channels < 2 || samples.is_empty() {
            return;
        }
        let frames = samples.len() / channels;
        let width = self.width;
        for frame_idx in 0..frames {
            let base = frame_idx * channels;
            let left = samples[base];
            let right = samples[base + 1];
            let mid = 0.5 * (left + right);
            let raw_side = 0.5 * (left - right);
            self.side_lp_z1 += (raw_side - self.side_lp_z1) * self.side_lp_alpha;
            let low_side = self.side_lp_z1;
            let side = (raw_side - (low_side * self.bass_mono_amount)) * width;
            let mut out_l = mid + side;
            let mut out_r = mid - side;
            let peak = out_l.abs().max(out_r.abs());
            if peak > 0.999 {
                let scale = 0.999 / peak;
                out_l *= scale;
                out_r *= scale;
            }
            samples[base] = out_l;
            samples[base + 1] = out_r;
        }
    }
}

