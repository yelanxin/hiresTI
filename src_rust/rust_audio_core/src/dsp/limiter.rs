/// Release time constant in seconds.
const RELEASE_TIME_S: f64 = 0.100;

// ---------------------------------------------------------------------------
// Internal state (shared between the audio thread probe and apply_config)
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub(crate) struct LimiterState {
    enabled: bool,
    threshold: f64,
    ratio: f64,
    /// Running gain multiplier, 0.0 – 1.0.
    gain: f64,
    /// Per-sample release coefficient: gain recovers toward 1.0 each sample.
    release_coeff: f64,
    sample_rate: u32,
}

impl LimiterState {
    pub(crate) fn new() -> Self {
        // Initialise from `LimiterConfig::default()` so the threshold/ratio
        // defaults live in exactly one place (the public config type).
        let mut state = Self {
            enabled: false,
            threshold: 0.0,
            ratio: 1.0,
            gain: 1.0,
            release_coeff: Self::release_coeff_for(44100),
            sample_rate: 44100,
        };
        state.apply_config(&LimiterConfig::default());
        state.enabled = false;
        state
    }

    pub(crate) fn release_coeff_for(rate: u32) -> f64 {
        let r = rate.max(1) as f64;
        (-1.0_f64 / (r * RELEASE_TIME_S)).exp()
    }

    pub(crate) fn update_sample_rate(&mut self, rate: u32) {
        if rate > 0 && rate != self.sample_rate {
            self.sample_rate = rate;
            self.release_coeff = Self::release_coeff_for(rate);
        }
    }

    pub(crate) fn apply_config(&mut self, config: &LimiterConfig) {
        self.enabled = config.enabled;
        self.threshold = config.threshold.clamp(0.0, 1.0);
        self.ratio = config.ratio.clamp(1.0, 60.0);
        self.gain = 1.0;
    }

    /// Process interleaved F64LE samples in-place.
    pub(crate) fn process(&mut self, samples: &mut [f64], channels: usize) {
        if !self.enabled || channels == 0 || samples.is_empty() {
            return;
        }
        let threshold = self.threshold;
        let ratio = self.ratio.max(1.0);
        let rc = self.release_coeff;
        let frames = samples.len() / channels;

        for i in 0..frames {
            let base = i * channels;

            // Peak magnitude across all channels for this frame.
            let mut peak = 0.0f64;
            for ch in 0..channels {
                let v = samples[base + ch].abs();
                if v > peak {
                    peak = v;
                }
            }

            // Gain required so compressed output stays at or below threshold.
            let required = if peak > threshold {
                let compressed = threshold + (peak - threshold) / ratio;
                compressed / peak
            } else {
                1.0
            };

            // Instantaneous attack: drop gain immediately if needed.
            if required < self.gain {
                self.gain = required;
            }

            // Apply gain.
            for ch in 0..channels {
                samples[base + ch] *= self.gain;
            }

            // Release: exponential recovery toward 1.0.
            if self.gain < 1.0 {
                self.gain = 1.0 - (1.0 - self.gain) * rc;
                if self.gain > 1.0 {
                    self.gain = 1.0;
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Public config type
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, PartialEq)]
pub struct LimiterConfig {
    pub enabled: bool,
    pub threshold: f64,
    pub ratio: f64,
}

impl Default for LimiterConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            threshold: 0.85,
            ratio: 20.0,
        }
    }
}

impl LimiterConfig {
    pub fn is_active(&self) -> bool {
        self.enabled
    }

    pub fn set_enabled(&mut self, enabled: bool) {
        self.enabled = enabled;
    }

    pub fn set_threshold(&mut self, threshold: f64) -> f64 {
        let clamped = threshold.clamp(0.0, 1.0);
        self.threshold = clamped;
        clamped
    }

    pub fn set_ratio(&mut self, ratio: f64) -> f64 {
        let clamped = ratio.clamp(1.0, 60.0);
        self.ratio = clamped;
        clamped
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::{LimiterState, RELEASE_TIME_S};

    fn make_state(threshold: f64, ratio: f64) -> LimiterState {
        let mut st = LimiterState::new();
        st.enabled = true;
        st.threshold = threshold;
        st.ratio = ratio;
        st.release_coeff = LimiterState::release_coeff_for(44100);
        st.gain = 1.0;
        st
    }

    #[test]
    fn disabled_passes_through() {
        let mut st = LimiterState::new();
        st.enabled = false;
        let mut samples = [0.9f64, -0.9f64];
        st.process(&mut samples, 2);
        assert!((samples[0] - 0.9).abs() < 1e-12);
        assert!((samples[1] + 0.9).abs() < 1e-12);
    }

    #[test]
    fn below_threshold_passes_through() {
        let mut st = make_state(0.85, 20.0);
        let mut samples = [0.5f64, -0.5f64];
        st.process(&mut samples, 2);
        assert!((samples[0] - 0.5).abs() < 1e-12);
        assert!((samples[1] + 0.5).abs() < 1e-12);
    }

    #[test]
    fn peak_above_threshold_is_compressed() {
        let threshold = 0.8f64;
        let ratio = 60.0f64;
        let peak = 0.95f64;
        let mut st = make_state(threshold, ratio);
        let mut samples = [peak, peak];
        st.process(&mut samples, 2);
        // With finite ratio the output ceiling is threshold + (peak - threshold) / ratio.
        let ceiling = threshold + (peak - threshold) / ratio;
        for s in &samples {
            assert!(
                s.abs() <= ceiling + 1e-9,
                "sample {s} exceeded ceiling {ceiling}"
            );
        }
    }

    #[test]
    fn gain_recovers_after_release() {
        let rate = 44100u32;
        let mut st = make_state(0.5, 60.0);
        st.release_coeff = LimiterState::release_coeff_for(rate);

        // Trigger gain reduction.
        let mut burst = [0.9f64, 0.9f64];
        st.process(&mut burst, 2);
        assert!(st.gain < 1.0, "gain should have been reduced");

        // Run silence for one release time constant (~63 % recovery expected).
        let recovery_samples = (rate as f64 * RELEASE_TIME_S) as usize;
        let mut silence = vec![0.0f64; recovery_samples * 2];
        st.process(&mut silence, 2);

        // After one τ the remaining deficit should be ≤ 37 % of the initial drop.
        assert!(
            st.gain > 0.6,
            "gain should have recovered substantially: {}",
            st.gain
        );
    }
}
