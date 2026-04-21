// Pure-Rust DSP processor for native transport (no GStreamer dependency).
//
// Wraps all pure-Rust DSP processing states and implements PcmProcessor so it
// can be inserted into the PcmProcessorChain alongside volume/spectrum/lufs.

use std::sync::{Arc, Mutex};

use crate::dsp::{
    ConvolverState, DspGraphConfig, DspOrderEntry, DspReorderableModule,
    LimiterState, PeqState, TapeState, TubeState, WidenerState,
};
use crate::native_transport::processor::{
    PcmProcessor, PcmSampleFormat, PcmSlab, PcmStreamSpec,
};

/// Shared slot for pushing DSP config updates into a running decode worker.
pub type SharedDspConfig = Arc<Mutex<Option<DspGraphConfig>>>;

/// DspPcmProcessor: runs the full DSP chain on PCM slabs.
///
/// Input slabs can be any supported format; they are converted to interleaved
/// F64LE for processing and converted back to the original format on output.
pub struct DspPcmProcessor {
    config: DspGraphConfig,
    peq: PeqState,
    tape: TapeState,
    tube: TubeState,
    widener: WidenerState,
    limiter: LimiterState,
    convolver: ConvolverState,
    /// Reusable buffer for F64LE samples during processing.
    f64_buf: Vec<f64>,
    channels: usize,
    sample_rate: u32,
    /// Diagnostic: count of non-silent slabs logged.
    diag_logged: u32,
    /// Shared slot: controller writes new config here, process() picks it up.
    pending_config: Option<SharedDspConfig>,
}

impl std::fmt::Debug for DspPcmProcessor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("DspPcmProcessor")
            .field("channels", &self.channels)
            .field("sample_rate", &self.sample_rate)
            .finish()
    }
}

impl DspPcmProcessor {
    pub fn new(config: &DspGraphConfig, pending: Option<SharedDspConfig>) -> Self {
        let mut peq = PeqState::new();
        let mut tape = TapeState::new();
        let mut tube = TubeState::new();
        let mut widener = WidenerState::new();
        let mut limiter = LimiterState::new();
        let mut convolver = ConvolverState::new();

        let eff_peq = config.effective_peq_config();
        let eff_tape = config.effective_tape_config();
        let eff_tube = config.effective_tube_config();
        let eff_widener = config.effective_widener_config();
        let eff_limiter = config.effective_limiter_config();
        let eff_convolver = config.effective_convolver_config();
        eprintln!(
            "[native-dsp] module states: peq={} tape={} tube={} widener={} limiter={} convolver={}",
            eff_peq.is_active(), eff_tape.is_active(), eff_tube.is_active(),
            eff_widener.is_active(), eff_limiter.is_active(), eff_convolver.is_active(),
        );
        eprintln!(
            "[native-dsp] widener cfg: enabled={} width={} bass_mono_freq={} bass_mono_amount={}",
            eff_widener.enabled, eff_widener.width, eff_widener.bass_mono_freq, eff_widener.bass_mono_amount,
        );
        peq.apply_config(&eff_peq);
        tape.apply_config(&eff_tape);
        tube.apply_config(&eff_tube);
        widener.apply_config(&eff_widener);
        limiter.apply_config(&eff_limiter);
        convolver.apply_config(&eff_convolver);

        Self {
            config: config.clone(),
            peq,
            tape,
            tube,
            widener,
            limiter,
            convolver,
            f64_buf: Vec::new(),
            channels: 2,
            sample_rate: 44_100,
            diag_logged: 0,
            pending_config: pending,
        }
    }

    /// Hot-update the DSP configuration (e.g. when the user changes EQ).
    pub fn update_config(&mut self, config: &DspGraphConfig) {
        self.config = config.clone();
        self.peq.apply_config(&config.effective_peq_config());
        self.tape.apply_config(&config.effective_tape_config());
        self.tube.apply_config(&config.effective_tube_config());
        self.widener.apply_config(&config.effective_widener_config());
        self.limiter.apply_config(&config.effective_limiter_config());
        self.convolver.apply_config(&config.effective_convolver_config());
    }

    fn update_rates(&mut self, rate: u32) {
        if rate == 0 || rate == self.sample_rate {
            return;
        }
        self.sample_rate = rate;
        self.peq.update_rate(rate);
        self.tape.update_rate(rate);
        self.tube.update_rate(rate);
        self.widener.update_rate(rate);
        self.limiter.update_sample_rate(rate);
        self.convolver.update_stream_rate(rate);
    }
}

impl PcmProcessor for DspPcmProcessor {
    fn name(&self) -> &'static str {
        "native-dsp"
    }

    fn configure(&mut self, spec: &PcmStreamSpec) -> Result<(), String> {
        self.channels = spec.channels;
        self.update_rates(spec.sample_rate);
        eprintln!(
            "[native-dsp] configure: rate={} ch={} fmt={:?} active={}",
            spec.sample_rate, spec.channels, spec.format,
            self.config.has_native_transport_processing()
        );
        Ok(())
    }

    fn process(&mut self, mut slab: PcmSlab) -> Result<PcmSlab, String> {
        // Check for hot-updated DSP config from the controller.
        let pending_cfg = self.pending_config.as_ref().and_then(|p| {
            p.try_lock().ok().and_then(|mut slot| slot.take())
        });
        if let Some(new_cfg) = pending_cfg {
            eprintln!(
                "[native-dsp] hot-update config: active={}",
                new_cfg.has_native_transport_processing()
            );
            self.update_config(&new_cfg);
        }

        if !self.config.has_native_transport_processing() {
            return Ok(slab);
        }

        let channels = slab.spec.channels;
        let orig_format = slab.spec.format;
        let orig_data_len = slab.data.len();

        // Convert to F64LE.
        let total_samples = pcm_to_f64(&slab.data, orig_format, &mut self.f64_buf);
        if total_samples == 0 {
            return Ok(slab);
        }

        // Snapshot first 8 samples for change detection.
        let mut pre_snapshot = [0.0f64; 8];
        let snap_len = pre_snapshot.len().min(self.f64_buf.len());
        pre_snapshot[..snap_len].copy_from_slice(&self.f64_buf[..snap_len]);

        // Run DSP modules in configured order.
        let order = DspGraphConfig::sanitized_order(&self.config.order);
        for entry in &order {
            match entry {
                DspOrderEntry::Builtin(DspReorderableModule::Peq) => {
                    self.peq.process(&mut self.f64_buf, channels);
                }
                DspOrderEntry::Builtin(DspReorderableModule::Convolver) => {
                    self.convolver.process(&mut self.f64_buf, channels);
                }
                DspOrderEntry::Builtin(DspReorderableModule::Tape) => {
                    self.tape.process(&mut self.f64_buf, channels);
                }
                DspOrderEntry::Builtin(DspReorderableModule::Tube) => {
                    self.tube.process(&mut self.f64_buf, channels);
                }
                DspOrderEntry::Builtin(DspReorderableModule::Widener) => {
                    self.widener.process(&mut self.f64_buf, channels);
                }
                DspOrderEntry::Lv2Slot(_) => {
                    // LV2 plugins are GStreamer-only; skip in native transport.
                }
            }
        }
        // Limiter always runs last (same as GStreamer graph).
        self.limiter.process(&mut self.f64_buf, channels);

        // Log whether DSP changed the audio (first 3 non-silent slabs).
        if self.diag_logged < 3 {
            // Skip all-zero (silent) slabs — they tell us nothing.
            let has_signal = pre_snapshot[..snap_len].iter().any(|&v| v.abs() > 1e-20);
            if has_signal {
                let mut changed = false;
                for i in 0..snap_len {
                    if (self.f64_buf[i] - pre_snapshot[i]).abs() > 1e-15 {
                        changed = true;
                        break;
                    }
                }
                eprintln!(
                    "[native-dsp] slab#{}: samples={} channels={} data_changed={} pre=[{:.6},{:.6},{:.6},{:.6}] post=[{:.6},{:.6},{:.6},{:.6}]",
                    self.diag_logged, total_samples, channels, changed,
                    pre_snapshot[0], pre_snapshot[1], pre_snapshot[2], pre_snapshot[3],
                    self.f64_buf[0], self.f64_buf[1], self.f64_buf[2], self.f64_buf[3],
                );
                self.diag_logged += 1;
            }
        }

        // Convert back to original format.
        f64_to_pcm(&self.f64_buf, orig_format, &mut slab.data);

        if slab.data.len() != orig_data_len {
            eprintln!(
                "[native-dsp] WARNING: data size changed {} → {} (fmt={:?} ch={} samples={})",
                orig_data_len, slab.data.len(), orig_format, channels, total_samples
            );
        }

        Ok(slab)
    }
}

// ── Format conversion helpers ────────────────────────────────────────────────

/// Convert raw PCM bytes to interleaved f64 samples. Returns sample count.
fn pcm_to_f64(data: &[u8], format: PcmSampleFormat, out: &mut Vec<f64>) -> usize {
    let bps = bytes_per_sample(format);
    if bps == 0 || data.len() < bps {
        out.clear();
        return 0;
    }
    let n = data.len() / bps;
    out.clear();
    out.reserve(n);
    for chunk in data.chunks_exact(bps) {
        out.push(sample_to_f64(chunk, format));
    }
    n
}

/// Convert interleaved f64 samples back to raw PCM bytes.
fn f64_to_pcm(samples: &[f64], format: PcmSampleFormat, out: &mut Vec<u8>) {
    let bps = bytes_per_sample(format);
    out.clear();
    out.reserve(samples.len() * bps);
    for &s in samples {
        match format {
            PcmSampleFormat::S16LE => {
                let v = (s * 32768.0).round().clamp(-32768.0, 32767.0) as i16;
                out.extend_from_slice(&v.to_le_bytes());
            }
            PcmSampleFormat::S24_3LE => {
                let v = (s * 8388608.0).round().clamp(-8388608.0, 8388607.0) as i32;
                out.push(v as u8);
                out.push((v >> 8) as u8);
                out.push((v >> 16) as u8);
            }
            PcmSampleFormat::S24LE | PcmSampleFormat::S32LE => {
                let v = (s * 2147483648.0).round().clamp(i32::MIN as f64, i32::MAX as f64) as i32;
                out.extend_from_slice(&v.to_le_bytes());
            }
            PcmSampleFormat::F32LE => {
                out.extend_from_slice(&(s as f32).to_le_bytes());
            }
            PcmSampleFormat::F64LE => {
                out.extend_from_slice(&s.to_le_bytes());
            }
        }
    }
}

fn bytes_per_sample(format: PcmSampleFormat) -> usize {
    match format {
        PcmSampleFormat::S16LE => 2,
        PcmSampleFormat::S24_3LE => 3,
        PcmSampleFormat::S24LE | PcmSampleFormat::S32LE => 4,
        PcmSampleFormat::F32LE => 4,
        PcmSampleFormat::F64LE => 8,
    }
}

fn sample_to_f64(bytes: &[u8], format: PcmSampleFormat) -> f64 {
    match format {
        PcmSampleFormat::S16LE => {
            i16::from_le_bytes([bytes[0], bytes[1]]) as f64 / 32768.0
        }
        PcmSampleFormat::S24_3LE => {
            let raw = (bytes[0] as i32) | ((bytes[1] as i32) << 8) | ((bytes[2] as i8 as i32) << 16);
            raw as f64 / 8388608.0
        }
        PcmSampleFormat::S24LE | PcmSampleFormat::S32LE => {
            i32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]) as f64 / 2147483648.0
        }
        PcmSampleFormat::F32LE => {
            f32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]) as f64
        }
        PcmSampleFormat::F64LE => {
            f64::from_le_bytes([
                bytes[0], bytes[1], bytes[2], bytes[3],
                bytes[4], bytes[5], bytes[6], bytes[7],
            ])
        }
    }
}
