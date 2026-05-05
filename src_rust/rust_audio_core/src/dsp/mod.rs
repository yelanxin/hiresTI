mod convolver;
mod limiter;
pub mod lufs;
mod peq;
mod resampler;
mod tape;
mod tube;
mod widener;

pub use convolver::ConvolverConfig;
pub use limiter::LimiterConfig;
pub use lufs::LufsValues;
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
/// SpectrumPcmProcessor.
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

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum DspOrderEntry {
    Builtin(DspReorderableModule),
}

impl DspOrderEntry {
    pub fn id(&self) -> &str {
        match self {
            Self::Builtin(m) => m.id(),
        }
    }

    pub fn from_id(value: &str) -> Option<Self> {
        DspReorderableModule::from_id(value.trim()).map(Self::Builtin)
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
        }
    }
}

impl DspGraphConfig {
    /// Return a de-duplicated order ensuring all built-in modules appear exactly
    /// once.
    pub fn sanitized_order(order: &[DspOrderEntry]) -> Vec<DspOrderEntry> {
        let mut seen_builtins = std::collections::HashSet::new();
        let mut out: Vec<DspOrderEntry> = Vec::new();

        for entry in order {
            match entry {
                DspOrderEntry::Builtin(m) => {
                    if seen_builtins.insert(*m) {
                        out.push(DspOrderEntry::Builtin(*m));
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

    pub fn has_active_processing(&self) -> bool {
        self.enabled
            && (self.peq.is_active()
                || self.convolver.is_active()
                || self.tape.is_active()
                || self.tube.is_active()
                || self.widener.is_active()
                || self.limiter.is_active()
                || self.resampler.is_active())
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
        self.enabled && self.resampler.is_active()
    }

    pub fn native_transport_unsupported_modules(&self) -> Vec<&'static str> {
        if !self.enabled {
            return Vec::new();
        }
        let mut modules = Vec::new();
        if self.resampler.is_active() {
            modules.push("resampler");
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
}
