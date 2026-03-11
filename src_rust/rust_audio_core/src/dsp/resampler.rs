use gst::prelude::*;
use gstreamer as gst;

#[derive(Clone, Debug, PartialEq)]
pub struct ResamplerConfig {
    pub enabled: bool,
    pub target_rate: u32, // 0 = passthrough
    pub quality: i32,     // 0 (fastest) .. 10 (best)
}

impl Default for ResamplerConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            target_rate: 0,
            quality: 10,
        }
    }
}

impl ResamplerConfig {
    pub fn is_active(&self) -> bool {
        self.enabled && self.target_rate > 0
    }

    pub fn set_enabled(&mut self, enabled: bool) {
        self.enabled = enabled;
    }

    pub fn set_target_rate(&mut self, rate: u32) {
        self.target_rate = rate;
    }

    pub fn set_quality(&mut self, quality: i32) {
        self.quality = quality.clamp(0, 10);
    }
}

#[derive(Debug)]
pub struct ResamplerNode {
    bin: gst::Bin,
    resample: gst::Element,
    capsfilter: gst::Element,
}

impl ResamplerNode {
    pub fn new() -> Result<Self, String> {
        let bin = gst::Bin::new();

        let resample = gst::ElementFactory::make("audioresample")
            .name("rust-dsp-resampler")
            .build()
            .map_err(|e| format!("audioresample unavailable: {e}"))?;

        let capsfilter = gst::ElementFactory::make("capsfilter")
            .name("rust-dsp-resampler-caps")
            .build()
            .map_err(|e| format!("capsfilter unavailable: {e}"))?;

        // Start with ANY caps (passthrough)
        capsfilter.set_property("caps", &gst::Caps::new_any());

        bin.add(&resample)
            .map_err(|_| "failed to add resampler element".to_string())?;
        bin.add(&capsfilter)
            .map_err(|_| "failed to add resampler capsfilter".to_string())?;

        resample
            .link(&capsfilter)
            .map_err(|_| "failed to link resampler -> capsfilter".to_string())?;

        let sink_pad = resample
            .static_pad("sink")
            .ok_or("resampler missing sink pad")?;
        let src_pad = capsfilter
            .static_pad("src")
            .ok_or("resampler capsfilter missing src pad")?;

        let ghost_sink = gst::GhostPad::with_target(&sink_pad)
            .map_err(|_| "failed to create resampler ghost sink".to_string())?;
        let ghost_src = gst::GhostPad::with_target(&src_pad)
            .map_err(|_| "failed to create resampler ghost src".to_string())?;

        bin.add_pad(&ghost_sink)
            .map_err(|_| "failed to add resampler ghost sink".to_string())?;
        bin.add_pad(&ghost_src)
            .map_err(|_| "failed to add resampler ghost src".to_string())?;

        Ok(Self { bin, resample, capsfilter })
    }

    pub fn element(&self) -> &gst::Element {
        self.bin.upcast_ref()
    }

    pub fn apply_config(&mut self, config: &ResamplerConfig) -> Result<(), String> {
        // Apply quality to the audioresample element
        for p in self.resample.list_properties() {
            if p.name() == "quality" {
                let _ = self.resample.set_property("quality", config.quality);
                break;
            }
        }

        let caps = if config.is_active() {
            gst::Caps::builder("audio/x-raw")
                .field("rate", config.target_rate as i32)
                .build()
        } else {
            gst::Caps::new_any()
        };
        self.capsfilter.set_property("caps", &caps);
        Ok(())
    }
}
