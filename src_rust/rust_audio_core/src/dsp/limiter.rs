use std::sync::{Arc, Mutex};

use gst::prelude::*;
use gst::PadProbeReturn;
use gst::PadProbeType;
use gstreamer as gst;

/// Release time constant in seconds.
const RELEASE_TIME_S: f64 = 0.100;

// ---------------------------------------------------------------------------
// Internal state (shared between the audio thread probe and apply_config)
// ---------------------------------------------------------------------------

#[derive(Debug)]
struct LimiterState {
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
    fn new() -> Self {
        Self {
            enabled: false,
            threshold: 0.85,
            ratio: 20.0,
            gain: 1.0,
            release_coeff: Self::release_coeff_for(44100),
            sample_rate: 44100,
        }
    }

    fn release_coeff_for(rate: u32) -> f64 {
        let r = rate.max(1) as f64;
        (-1.0_f64 / (r * RELEASE_TIME_S)).exp()
    }

    fn update_sample_rate(&mut self, rate: u32) {
        if rate > 0 && rate != self.sample_rate {
            self.sample_rate = rate;
            self.release_coeff = Self::release_coeff_for(rate);
        }
    }

    /// Process interleaved F64LE samples in-place.
    fn process(&mut self, samples: &mut [f64], channels: usize) {
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
// GStreamer node
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub struct LimiterNode {
    bin: gst::Bin,
    state: Arc<Mutex<LimiterState>>,
}

impl LimiterNode {
    pub fn new() -> Result<Self, String> {
        let bin = gst::Bin::new();

        // `identity` is a passthrough element; we intercept its buffers via a
        // pad probe so we can do in-place DSP without needing a custom element.
        let identity = gst::ElementFactory::make("identity")
            .name("rust-dsp-limiter")
            .build()
            .map_err(|e| format!("identity element unavailable: {e}"))?;
        let _ = identity.set_property("silent", true);

        bin.add(&identity)
            .map_err(|_| "failed to add limiter identity".to_string())?;

        let sink_pad = identity
            .static_pad("sink")
            .ok_or_else(|| "limiter identity missing sink pad".to_string())?;
        let src_pad = identity
            .static_pad("src")
            .ok_or_else(|| "limiter identity missing src pad".to_string())?;

        let ghost_sink = gst::GhostPad::with_target(&sink_pad)
            .map_err(|_| "failed to create limiter ghost sink pad".to_string())?;
        let ghost_src = gst::GhostPad::with_target(&src_pad)
            .map_err(|_| "failed to create limiter ghost src pad".to_string())?;
        bin.add_pad(&ghost_sink)
            .map_err(|_| "failed to add limiter ghost sink pad".to_string())?;
        bin.add_pad(&ghost_src)
            .map_err(|_| "failed to add limiter ghost src pad".to_string())?;

        let state = Arc::new(Mutex::new(LimiterState::new()));
        let probe_state = Arc::clone(&state);

        src_pad.add_probe(PadProbeType::BUFFER, move |pad, info| {
            let Some(gst::PadProbeData::Buffer(ref mut buffer)) = info.data else {
                return PadProbeReturn::Ok;
            };
            // try_lock avoids priority inversion on the audio thread.
            let Ok(mut st) = probe_state.try_lock() else {
                return PadProbeReturn::Ok;
            };

            // Read caps once per buffer to sync sample rate / channel count.
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

            st.update_sample_rate(rate);

            // Map the buffer as writable and process samples in-place.
            let buf = buffer.make_mut();
            if let Ok(mut map) = buf.map_writable() {
                let raw = map.as_mut_slice();
                // DSP chain internal format is F64LE (8 bytes per sample).
                if raw.len() % 8 == 0 {
                    // SAFETY: format is F64LE, pointer is 8-byte aligned by GStreamer.
                    let samples = unsafe {
                        std::slice::from_raw_parts_mut(raw.as_mut_ptr() as *mut f64, raw.len() / 8)
                    };
                    st.process(samples, channels);
                }
            }

            PadProbeReturn::Ok
        });

        let mut node = Self { bin, state };
        node.apply_config(&LimiterConfig::default())?;
        Ok(node)
    }

    pub fn element(&self) -> &gst::Element {
        self.bin.upcast_ref()
    }

    pub fn apply_config(&mut self, config: &LimiterConfig) -> Result<(), String> {
        let Ok(mut st) = self.state.lock() else {
            return Err("limiter state lock poisoned".to_string());
        };
        st.enabled = config.enabled;
        st.threshold = config.threshold.clamp(0.0, 1.0);
        st.ratio = config.ratio.clamp(1.0, 60.0);
        // Reset gain to 1.0 on each config change to avoid stale state.
        st.gain = 1.0;
        Ok(())
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
