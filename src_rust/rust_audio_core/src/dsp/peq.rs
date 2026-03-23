use gst::glib;
use gst::prelude::*;
use gstreamer as gst;

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
