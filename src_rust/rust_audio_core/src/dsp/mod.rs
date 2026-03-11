use gst::prelude::*;
use gstreamer as gst;
use std::collections::HashMap;

mod convolver;
mod limiter;
mod lv2;
mod peq;
mod resampler;
mod tape;
mod tube;
mod widener;

pub use convolver::{ConvolverConfig, ConvolverNode};
pub use limiter::{LimiterConfig, LimiterNode};
pub use lv2::{Lv2Node, Lv2SlotConfig, lv2_scan_plugins};
pub use peq::{PeqConfig, PeqNode, PEQ_BAND_COUNT};
pub use resampler::{ResamplerConfig, ResamplerNode};
pub use tape::{TapeConfig, TapeNode};
pub use tube::{TubeConfig, TubeNode};
pub use widener::{WidenerConfig, WidenerNode};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum DspReorderableModule {
    Peq,
    Convolver,
    Tape,
    Tube,
    Widener,
}

impl DspReorderableModule {
    pub fn id(&self) -> &'static str {
        match self {
            Self::Peq => "peq",
            Self::Convolver => "convolver",
            Self::Tape => "tape",
            Self::Tube => "tube",
            Self::Widener => "widener",
        }
    }

    pub fn from_id(value: &str) -> Option<Self> {
        match value.trim() {
            "peq" => Some(Self::Peq),
            "convolver" => Some(Self::Convolver),
            "tape" => Some(Self::Tape),
            "tube" => Some(Self::Tube),
            "widener" => Some(Self::Widener),
            _ => None,
        }
    }

    pub fn default_order() -> Vec<Self> {
        vec![
            Self::Peq,
            Self::Convolver,
            Self::Tape,
            Self::Tube,
            Self::Widener,
        ]
    }
}

/// A single entry in the DSP processing order.
/// Built-in modules are identified by their fixed ID; LV2 slots by a unique
/// slot_id string (always prefixed with `"lv2_"`).
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum DspOrderEntry {
    Builtin(DspReorderableModule),
    Lv2Slot(String),
}

impl DspOrderEntry {
    pub fn id(&self) -> &str {
        match self {
            Self::Builtin(m) => m.id(),
            Self::Lv2Slot(id) => id.as_str(),
        }
    }

    pub fn from_id(value: &str) -> Option<Self> {
        let v = value.trim();
        if let Some(m) = DspReorderableModule::from_id(v) {
            Some(Self::Builtin(m))
        } else if v.starts_with("lv2_") {
            Some(Self::Lv2Slot(v.to_string()))
        } else {
            None
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct DspGraphConfig {
    pub enabled: bool,
    pub order: Vec<DspOrderEntry>,
    pub peq: PeqConfig,
    pub convolver: ConvolverConfig,
    pub tape: TapeConfig,
    pub tube: TubeConfig,
    pub widener: WidenerConfig,
    pub limiter: LimiterConfig,
    pub resampler: ResamplerConfig,
    pub lv2_slots: Vec<Lv2SlotConfig>,
    lv2_slot_counter: usize,
}

impl Default for DspGraphConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            order: DspReorderableModule::default_order()
                .into_iter()
                .map(DspOrderEntry::Builtin)
                .collect(),
            peq: PeqConfig::default(),
            convolver: ConvolverConfig::default(),
            tape: TapeConfig::default(),
            tube: TubeConfig::default(),
            widener: WidenerConfig::default(),
            limiter: LimiterConfig::default(),
            resampler: ResamplerConfig::default(),
            lv2_slots: Vec::new(),
            lv2_slot_counter: 0,
        }
    }
}

impl DspGraphConfig {
    /// Return a de-duplicated order ensuring all built-in modules appear exactly
    /// once. LV2 slot entries are kept as-is (deduplicated) but never
    /// auto-appended — they must be explicitly present.
    pub fn sanitized_order(order: &[DspOrderEntry]) -> Vec<DspOrderEntry> {
        let mut seen_builtins = std::collections::HashSet::new();
        let mut seen_lv2 = std::collections::HashSet::new();
        let mut out: Vec<DspOrderEntry> = Vec::new();

        for entry in order {
            match entry {
                DspOrderEntry::Builtin(m) => {
                    if seen_builtins.insert(*m) {
                        out.push(DspOrderEntry::Builtin(*m));
                    }
                }
                DspOrderEntry::Lv2Slot(id) => {
                    if seen_lv2.insert(id.clone()) {
                        out.push(DspOrderEntry::Lv2Slot(id.clone()));
                    }
                }
            }
        }
        // Append any missing built-in modules at the end.
        for module in DspReorderableModule::default_order() {
            if seen_builtins.insert(module) {
                out.push(DspOrderEntry::Builtin(module));
            }
        }
        out
    }

    pub fn set_order_from_ids(&mut self, ids: &[&str]) {
        let parsed: Vec<DspOrderEntry> = ids
            .iter()
            .filter_map(|&value| DspOrderEntry::from_id(value))
            .collect();
        self.order = Self::sanitized_order(&parsed);
    }

    pub fn order_ids(&self) -> Vec<String> {
        Self::sanitized_order(&self.order)
            .into_iter()
            .map(|entry| entry.id().to_string())
            .collect()
    }

    // ── LV2 slot management ────────────────────────────────────────────────

    pub fn lv2_slot(&self, slot_id: &str) -> Option<&Lv2SlotConfig> {
        self.lv2_slots.iter().find(|s| s.slot_id == slot_id)
    }

    pub fn lv2_slot_mut(&mut self, slot_id: &str) -> Option<&mut Lv2SlotConfig> {
        self.lv2_slots.iter_mut().find(|s| s.slot_id == slot_id)
    }

    /// Add a new LV2 plugin slot. Returns the generated slot_id.
    pub fn add_lv2_slot(&mut self, uri: &str) -> String {
        let slot_id = format!("lv2_{}", self.lv2_slot_counter);
        self.lv2_slot_counter += 1;
        self.lv2_slots.push(Lv2SlotConfig::new(slot_id.clone(), uri));
        self.order.push(DspOrderEntry::Lv2Slot(slot_id.clone()));
        slot_id
    }

    /// Restore a slot with a specific slot_id (used during startup). Does NOT
    /// modify the order (caller must have already set the order via
    /// `set_order_from_ids`). Skips if a slot with that ID already exists.
    pub fn restore_lv2_slot(&mut self, slot_id: &str, uri: &str) {
        if self.lv2_slots.iter().any(|s| s.slot_id == slot_id) {
            return;
        }
        let config = Lv2SlotConfig::new(slot_id, uri);
        self.lv2_slots.push(config);
        // Keep counter consistent.
        if let Some(n) = slot_id
            .strip_prefix("lv2_")
            .and_then(|s| s.parse::<usize>().ok())
        {
            if n >= self.lv2_slot_counter {
                self.lv2_slot_counter = n + 1;
            }
        }
    }

    pub fn remove_lv2_slot(&mut self, slot_id: &str) {
        self.lv2_slots.retain(|s| s.slot_id != slot_id);
        self.order
            .retain(|e| !matches!(e, DspOrderEntry::Lv2Slot(id) if id == slot_id));
    }

    pub fn has_active_processing(&self) -> bool {
        self.enabled
            && (self.peq.is_active()
                || self.convolver.is_active()
                || self.tape.is_active()
                || self.tube.is_active()
                || self.widener.is_active()
                || self.limiter.is_active()
                || self.resampler.is_active()
                || self.lv2_slots.iter().any(Lv2SlotConfig::is_active))
    }

    pub fn effective_lv2_slots(&self) -> Vec<Lv2SlotConfig> {
        self.lv2_slots
            .iter()
            .cloned()
            .map(|mut slot| {
                if !self.enabled {
                    slot.set_enabled(false);
                }
                slot
            })
            .collect()
    }
}

// Generate `effective_X_config()` methods for DspGraphConfig: each clones the
// field and disables it when the master DSP switch is off.  Adding a new module
// requires only one new invocation instead of a full copy-pasted method.
macro_rules! impl_effective_config {
    ($( $fn_name:ident, $field:ident, $ty:ty );* $(;)?) => {
        impl DspGraphConfig {
            $(
                pub fn $fn_name(&self) -> $ty {
                    let mut cfg = self.$field.clone();
                    if !self.enabled {
                        cfg.set_enabled(false);
                    }
                    cfg
                }
            )*
        }
    };
}
impl_effective_config!(
    effective_peq_config,       peq,       PeqConfig;
    effective_convolver_config, convolver, ConvolverConfig;
    effective_limiter_config,   limiter,   LimiterConfig;
    effective_tape_config,      tape,      TapeConfig;
    effective_tube_config,      tube,      TubeConfig;
    effective_widener_config,   widener,   WidenerConfig;
    effective_resampler_config, resampler, ResamplerConfig;
);

#[derive(Debug)]
pub struct DspGraphRuntime {
    bin: gst::Bin,
    peq: Option<PeqNode>,
    convolver: Option<ConvolverNode>,
    tape: Option<TapeNode>,
    tube: Option<TubeNode>,
    widener: Option<WidenerNode>,
    limiter: Option<LimiterNode>,
    resampler: Option<ResamplerNode>,
    lv2_slots: HashMap<String, Lv2Node>,
    spectrum: Option<gst::Element>,
}

impl DspGraphRuntime {
    pub fn build(config: &DspGraphConfig) -> Result<Self, String> {
        let bin = gst::Bin::new();
        let internal_caps = gst::Caps::builder("audio/x-raw")
            .field("format", "F64LE")
            .field("layout", "interleaved")
            .build();

        let in_convert = gst::ElementFactory::make("audioconvert")
            .name("rust-dsp-in-convert")
            .build()
            .map_err(|e| format!("audioconvert unavailable: {e}"))?;
        let in_capsfilter = gst::ElementFactory::make("capsfilter")
            .name("rust-dsp-in-caps")
            .build()
            .map_err(|e| format!("capsfilter unavailable: {e}"))?;
        in_capsfilter.set_property("caps", &internal_caps);
        let out_convert = gst::ElementFactory::make("audioconvert")
            .name("rust-dsp-out-convert")
            .build()
            .map_err(|e| format!("audioconvert unavailable: {e}"))?;
        let out_capsfilter = gst::ElementFactory::make("capsfilter")
            .name("rust-dsp-out-caps")
            .build()
            .map_err(|e| format!("capsfilter unavailable: {e}"))?;
        out_capsfilter.set_property("caps", &internal_caps);

        let peq = match PeqNode::new() {
            Ok(mut node) => {
                node.apply_config(&config.peq)?;
                Some(node)
            }
            Err(err) if !config.has_active_processing() => None,
            Err(err) => return Err(err),
        };
        let convolver = match ConvolverNode::new() {
            Ok(mut node) => {
                node.apply_config(&config.effective_convolver_config())?;
                Some(node)
            }
            Err(err) if !config.convolver.is_active() => None,
            Err(err) => return Err(err),
        };
        let tape = match TapeNode::new() {
            Ok(mut node) => {
                node.apply_config(&config.effective_tape_config())?;
                Some(node)
            }
            Err(err) if !config.tape.is_active() => None,
            Err(err) => return Err(err),
        };
        let tube = match TubeNode::new() {
            Ok(mut node) => {
                node.apply_config(&config.effective_tube_config())?;
                Some(node)
            }
            Err(err) if !config.tube.is_active() => None,
            Err(err) => return Err(err),
        };
        let widener = match WidenerNode::new() {
            Ok(mut node) => {
                node.apply_config(&config.effective_widener_config())?;
                Some(node)
            }
            Err(err) if !config.widener.is_active() => None,
            Err(err) => return Err(err),
        };
        let limiter = match LimiterNode::new() {
            Ok(mut node) => {
                node.apply_config(&config.effective_limiter_config())?;
                Some(node)
            }
            Err(err) if !config.limiter.is_active() => None,
            Err(err) => return Err(err),
        };
        let resampler = match ResamplerNode::new() {
            Ok(mut node) => {
                node.apply_config(&config.effective_resampler_config())?;
                Some(node)
            }
            Err(err) if !config.resampler.is_active() => None,
            Err(err) => return Err(err),
        };

        let spectrum = Self::build_spectrum_element()?;

        // Refresh the GStreamer registry once per graph build so that newly
        // installed LV2 plugins are visible.  Calling this once here (rather than
        // once per Lv2Node::new) avoids redundant filesystem scans when multiple
        // LV2 slots are active, and keeps the main-loop blocking time short.
        let active_lv2_slots: Vec<_> = config
            .effective_lv2_slots()
            .into_iter()
            .filter(|s| s.is_active())
            .collect();
        if !active_lv2_slots.is_empty() {
            crate::dsp::lv2::refresh_gstreamer_registry();
        }

        // Detect URI → factory-name collisions before attempting to load.
        // Two different URIs can produce the same GStreamer factory name (all
        // non-alphanumeric chars become '-'), causing one plugin to silently fail.
        {
            let mut seen: HashMap<String, &str> = HashMap::new();
            for slot in &active_lv2_slots {
                let factory = crate::dsp::lv2::uri_to_gst_factory_name(&slot.uri);
                if let Some(prev_uri) = seen.get(&factory) {
                    eprintln!(
                        "[dsp] lv2 factory-name collision: '{}' and '{}' both map to '{}'; \
                         one plugin will fail to load",
                        prev_uri, slot.uri, factory
                    );
                } else {
                    seen.insert(factory, &slot.uri);
                }
            }
        }

        // Build LV2 nodes only for enabled slots. Some plugins do not implement
        // bypass/passthrough reliably, so a disabled slot must be excluded from
        // the live DSP chain rather than left in place with a best-effort bypass.
        let mut lv2_slots: HashMap<String, Lv2Node> = HashMap::new();
        for slot_config in active_lv2_slots.iter() {
            match Lv2Node::new(slot_config) {
                Ok(node) => {
                    lv2_slots.insert(slot_config.slot_id.clone(), node);
                }
                Err(e) => {
                    eprintln!("[dsp] lv2 slot {} failed to load: {e}", slot_config.slot_id);
                    // Non-fatal: skip this slot rather than failing the whole graph.
                }
            }
        }

        bin.add(&in_convert)
            .map_err(|_| "failed to add dsp input convert".to_string())?;
        bin.add(&in_capsfilter)
            .map_err(|_| "failed to add dsp input caps".to_string())?;
        if let Some(ref node) = peq {
            bin.add(node.element())
                .map_err(|_| "failed to add dsp peq".to_string())?;
        }
        if let Some(ref node) = convolver {
            bin.add(node.element())
                .map_err(|_| "failed to add dsp convolver".to_string())?;
        }
        if let Some(ref node) = tape {
            bin.add(node.element())
                .map_err(|_| "failed to add dsp tape".to_string())?;
        }
        if let Some(ref node) = tube {
            bin.add(node.element())
                .map_err(|_| "failed to add dsp tube".to_string())?;
        }
        if let Some(ref node) = widener {
            bin.add(node.element())
                .map_err(|_| "failed to add dsp widener".to_string())?;
        }
        if let Some(ref node) = limiter {
            bin.add(node.element())
                .map_err(|_| "failed to add dsp limiter".to_string())?;
        }
        if let Some(ref node) = resampler {
            bin.add(node.element())
                .map_err(|_| "failed to add dsp resampler".to_string())?;
        }
        for (slot_id, node) in &lv2_slots {
            bin.add(&node.element())
                .map_err(|_| format!("failed to add lv2 slot {slot_id}"))?;
        }
        if let Some(ref spectrum_elem) = spectrum {
            bin.add(spectrum_elem)
                .map_err(|_| "failed to add dsp spectrum".to_string())?;
        }
        bin.add(&out_capsfilter)
            .map_err(|_| "failed to add dsp output caps".to_string())?;
        bin.add(&out_convert)
            .map_err(|_| "failed to add dsp output convert".to_string())?;

        let mut chain: Vec<gst::Element> = vec![in_convert.clone(), in_capsfilter.clone()];
        for entry in DspGraphConfig::sanitized_order(&config.order) {
            match entry {
                DspOrderEntry::Builtin(DspReorderableModule::Peq) => {
                    if let Some(ref node) = peq {
                        chain.push(node.element().clone());
                    }
                }
                DspOrderEntry::Builtin(DspReorderableModule::Convolver) => {
                    if let Some(ref node) = convolver {
                        chain.push(node.element().clone());
                    }
                }
                DspOrderEntry::Builtin(DspReorderableModule::Tape) => {
                    if let Some(ref node) = tape {
                        chain.push(node.element().clone());
                    }
                }
                DspOrderEntry::Builtin(DspReorderableModule::Tube) => {
                    if let Some(ref node) = tube {
                        chain.push(node.element().clone());
                    }
                }
                DspOrderEntry::Builtin(DspReorderableModule::Widener) => {
                    if let Some(ref node) = widener {
                        chain.push(node.element().clone());
                    }
                }
                DspOrderEntry::Lv2Slot(ref slot_id) => {
                    if let Some(node) = lv2_slots.get(slot_id) {
                        chain.push(node.element());
                    }
                }
            }
        }
        if let Some(ref node) = limiter {
            chain.push(node.element().clone());
        }
        if let Some(ref spectrum_elem) = spectrum {
            chain.push(spectrum_elem.clone());
        }
        // Keep the analyzer tap before the output resampler so FFT bin spacing
        // follows the decoded/DSP-processed content bandwidth rather than the
        // post-upsampling Nyquist range. Otherwise high-rate resampling makes
        // the same musical content collapse toward the left side of the graph.
        if let Some(ref node) = resampler {
            chain.push(node.element().clone());
        }
        chain.push(out_capsfilter.clone());
        chain.push(out_convert.clone());

        for pair in chain.windows(2) {
            if pair[0].link(&pair[1]).is_err() {
                return Err(format!(
                    "failed to link dsp graph: {} -> {}",
                    pair[0].name(),
                    pair[1].name()
                ));
            }
        }

        let sink_pad = chain
            .first()
            .and_then(|elem| elem.static_pad("sink"))
            .ok_or_else(|| "dsp graph missing sink pad".to_string())?;
        let src_pad = chain
            .last()
            .and_then(|elem| elem.static_pad("src"))
            .ok_or_else(|| "dsp graph missing src pad".to_string())?;
        let ghost_sink = gst::GhostPad::with_target(&sink_pad)
            .map_err(|_| "failed to create dsp ghost sink pad".to_string())?;
        let ghost_src = gst::GhostPad::with_target(&src_pad)
            .map_err(|_| "failed to create dsp ghost src pad".to_string())?;
        bin.add_pad(&ghost_sink)
            .map_err(|_| "failed to add dsp ghost sink pad".to_string())?;
        bin.add_pad(&ghost_src)
            .map_err(|_| "failed to add dsp ghost src pad".to_string())?;

        Ok(Self {
            bin,
            peq,
            convolver,
            tape,
            tube,
            widener,
            limiter,
            resampler,
            lv2_slots,
            spectrum,
        })
    }

    pub fn bin_element(&self) -> gst::Element {
        self.bin.clone().upcast()
    }

    pub fn apply_config(&mut self, config: &DspGraphConfig) -> Result<(), String> {
        if let Some(ref mut peq) = self.peq {
            peq.apply_config(&config.effective_peq_config())?;
        } else if config.effective_peq_config().is_active() {
            return Err("dsp peq unavailable".to_string());
        }
        if let Some(ref mut convolver) = self.convolver {
            convolver.apply_config(&config.effective_convolver_config())?;
        } else if config.effective_convolver_config().is_active() {
            return Err("dsp convolver unavailable".to_string());
        }
        if let Some(ref mut tape) = self.tape {
            tape.apply_config(&config.effective_tape_config())?;
        } else if config.effective_tape_config().is_active() {
            return Err("dsp tape unavailable".to_string());
        }
        if let Some(ref mut limiter) = self.limiter {
            limiter.apply_config(&config.effective_limiter_config())?;
        } else if config.effective_limiter_config().is_active() {
            return Err("dsp limiter unavailable".to_string());
        }
        if let Some(ref mut tube) = self.tube {
            tube.apply_config(&config.effective_tube_config())?;
        } else if config.effective_tube_config().is_active() {
            return Err("dsp tube unavailable".to_string());
        }
        if let Some(ref mut widener) = self.widener {
            widener.apply_config(&config.effective_widener_config())?;
        } else if config.effective_widener_config().is_active() {
            return Err("dsp widener unavailable".to_string());
        }
        if let Some(ref mut resampler) = self.resampler {
            resampler.apply_config(&config.effective_resampler_config())?;
        } else if config.effective_resampler_config().is_active() {
            return Err("dsp resampler unavailable".to_string());
        }
        // Hot-update LV2 port values for currently active nodes. Slot
        // enable/disable rebuilds the graph, so inactive slots are absent here
        // by design and their stored values will be applied on next enable.
        for slot_config in &config.effective_lv2_slots() {
            if let Some(node) = self.lv2_slots.get(&slot_config.slot_id) {
                node.apply_config(slot_config);
            }
        }
        Ok(())
    }

    pub fn set_spectrum_messages_enabled(&self, enabled: bool) {
        let Some(ref spectrum) = self.spectrum else {
            return;
        };
        let mut updated = false;
        for p in spectrum.list_properties() {
            let pn = p.name();
            if pn == "message" {
                let _ = spectrum.set_property("message", enabled);
                updated = true;
                break;
            }
            if pn == "post-messages" {
                let _ = spectrum.set_property("post-messages", enabled);
                updated = true;
                break;
            }
        }
        if !updated && enabled {
            eprintln!("[dsp] spectrum element lacks message/post-messages property");
        }
    }

    fn build_spectrum_element() -> Result<Option<gst::Element>, String> {
        let spectrum = match gst::ElementFactory::make("spectrum")
            .name("rust-spectrum")
            .build()
        {
            Ok(elem) => elem,
            Err(_) => return Ok(None),
        };
        for p in spectrum.list_properties() {
            let pn = p.name();
            if pn == "bands" {
                spectrum.set_property_from_str("bands", "96");
            } else if pn == "multi-channel" {
                let _ = spectrum.set_property("multi-channel", true);
            } else if pn == "interval" {
                spectrum.set_property_from_str("interval", "16000000");
            }
        }
        Ok(Some(spectrum))
    }
}

#[cfg(test)]
mod tests {
    use super::{DspGraphConfig, DspOrderEntry, DspReorderableModule};

    #[test]
    fn sanitized_order_deduplicates_and_appends_missing_modules() {
        let order = DspGraphConfig::sanitized_order(&[
            DspOrderEntry::Builtin(DspReorderableModule::Tube),
            DspOrderEntry::Builtin(DspReorderableModule::Peq),
            DspOrderEntry::Builtin(DspReorderableModule::Tube),
        ]);
        assert_eq!(
            order,
            vec![
                DspOrderEntry::Builtin(DspReorderableModule::Tube),
                DspOrderEntry::Builtin(DspReorderableModule::Peq),
                DspOrderEntry::Builtin(DspReorderableModule::Convolver),
                DspOrderEntry::Builtin(DspReorderableModule::Tape),
                DspOrderEntry::Builtin(DspReorderableModule::Widener),
            ]
        );
    }

    #[test]
    fn set_order_from_ids_ignores_unknown_values() {
        let mut config = DspGraphConfig::default();
        config.set_order_from_ids(&["widener", "bogus", "peq"]);
        assert_eq!(
            config.order_ids(),
            vec!["widener", "peq", "convolver", "tape", "tube"]
        );
    }

    #[test]
    fn lv2_slots_in_order() {
        let mut config = DspGraphConfig::default();
        config.set_order_from_ids(&["peq", "lv2_0", "tape"]);
        config.restore_lv2_slot("lv2_0", "http://example.com/plugin");
        let ids = config.order_ids();
        assert!(ids.contains(&"lv2_0".to_string()));
        let lv2_pos = ids.iter().position(|s| s == "lv2_0").unwrap();
        let peq_pos = ids.iter().position(|s| s == "peq").unwrap();
        let tape_pos = ids.iter().position(|s| s == "tape").unwrap();
        assert!(peq_pos < lv2_pos && lv2_pos < tape_pos);
    }

    #[test]
    fn disabled_lv2_slot_does_not_count_as_active_processing() {
        let mut config = DspGraphConfig::default();
        config.restore_lv2_slot("lv2_0", "http://example.com/plugin");
        assert!(config.has_active_processing());

        config.lv2_slot_mut("lv2_0").unwrap().set_enabled(false);
        assert!(!config.has_active_processing());
    }
}
