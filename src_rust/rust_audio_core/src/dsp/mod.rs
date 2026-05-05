mod convolver;
mod limiter;
pub mod lufs;
mod lv2;
mod peq;
mod resampler;
mod tape;
mod tube;
mod widener;

pub use convolver::ConvolverConfig;
pub use limiter::LimiterConfig;
pub use lufs::LufsValues;
pub use lv2::{lv2_scan_plugins, Lv2SlotConfig};
pub use peq::{PeqConfig, PEQ_BAND_COUNT};
pub use resampler::ResamplerConfig;
pub use tape::TapeConfig;
pub use tube::TubeConfig;
pub use widener::WidenerConfig;

// Pure-Rust DSP states for native transport (no GStreamer dependency).
pub(crate) use convolver::ConvolverState;
pub(crate) use limiter::LimiterState;
pub(crate) use peq::PeqState;
pub(crate) use tape::TapeState;
pub(crate) use tube::TubeState;
pub(crate) use widener::WidenerState;

pub(crate) const SPECTRUM_ACTIVE_BANDS_DEFAULT: u32 = 512;
/// Spectrum-frame emit cadence shared with native_transport's
/// SpectrumPcmProcessor. Originally matched GStreamer's `spectrum` element
/// interval; kept the same so V2 produces frames at a well-tested rate.
pub(crate) const SPECTRUM_ACTIVE_INTERVAL_NS: u64 = 16_000_000;

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
        self.lv2_slots
            .push(Lv2SlotConfig::new(slot_id.clone(), uri));
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

    pub fn has_native_transport_processing(&self) -> bool {
        self.enabled
            && (self.peq.is_active()
                || self.convolver.is_active()
                || self.tape.is_active()
                || self.tube.is_active()
                || self.widener.is_active()
                || self.limiter.is_active())
    }

    pub fn has_native_transport_unsupported_processing(&self) -> bool {
        self.enabled
            && (self.resampler.is_active() || self.lv2_slots.iter().any(Lv2SlotConfig::is_active))
    }

    pub fn native_transport_unsupported_modules(&self) -> Vec<&'static str> {
        if !self.enabled {
            return Vec::new();
        }
        let mut modules = Vec::new();
        if self.resampler.is_active() {
            modules.push("resampler");
        }
        if self.lv2_slots.iter().any(Lv2SlotConfig::is_active) {
            modules.push("lv2");
        }
        modules
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
);


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
