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
