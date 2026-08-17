use std::collections::{HashMap, VecDeque};
use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_double, c_int, c_uint, c_void};
use std::path::Path;
use std::ptr;
use std::sync::atomic::Ordering;

mod alsa_clock;
mod alsa_pcm;
mod dsp;
#[allow(dead_code)]
mod native_transport;
pub mod usb_audio;

#[cfg(test)]
use alsa_pcm::{AlsaCtx, AlsaHandle};
use dsp::{DspGraphConfig, LufsValues, PEQ_BAND_COUNT, SPECTRUM_ACTIVE_BANDS_DEFAULT};

const SPECTRUM_BANDS_MAX: usize = 4096;
const SPECTRUM_RING_CAP: usize = 512;

const ALSA_MMAP_RT_PRIORITY_DEFAULT: i32 = 60;

fn new_spectrum_ring_values() -> Vec<[f32; SPECTRUM_BANDS_MAX]> {
    vec![[0.0; SPECTRUM_BANDS_MAX]; SPECTRUM_RING_CAP]
}

fn new_spectrum_ring_len() -> Vec<u16> {
    vec![0; SPECTRUM_RING_CAP]
}

fn new_spectrum_ring_pos_s() -> Vec<f64> {
    vec![0.0; SPECTRUM_RING_CAP]
}

fn new_spectrum_ring_seq() -> Vec<u64> {
    vec![0; SPECTRUM_RING_CAP]
}

fn normalized_driver_label(driver: &str) -> String {
    driver
        .trim()
        .replace('（', "(")
        .replace('）', ")")
        .to_ascii_lowercase()
        .replace(' ', "")
}

fn driver_is_alsa_auto(driver: &str) -> bool {
    matches!(
        normalized_driver_label(driver).as_str(),
        "alsa" | "alsa(auto)"
    )
}

fn driver_is_alsa_mmap(driver: &str) -> bool {
    matches!(
        normalized_driver_label(driver).as_str(),
        "alsa_mmap" | "alsa(mmap)"
    )
}

fn driver_is_alsa_family(driver: &str) -> bool {
    driver_is_alsa_auto(driver) || driver_is_alsa_mmap(driver)
}

/// True when the user explicitly picks the ALSA→PipeWire bridge as the
/// output. We treat this as a thin shared-mixer driver: always routes
/// through `snd_pcm_open("pipewire")`, never exclusive, never tries to
/// follow the source sample rate (PipeWire's own resampler handles that).
fn driver_is_pipewire(driver: &str) -> bool {
    matches!(normalized_driver_label(driver).as_str(), "pipewire")
}

/// True for any driver routed through V2 native_transport's ALSA backend:
/// Auto(Default), ALSA(auto), ALSA(mmap), and PipeWire (via ALSA bridge).
fn driver_routes_via_native_alsa(driver: &str) -> bool {
    let norm = normalized_driver_label(driver);
    norm.is_empty()
        || norm.starts_with("auto")
        || driver_is_alsa_family(driver)
        || driver_is_pipewire(driver)
}


// ---------------------------------------------------------------------------
// USB output format helpers
// ---------------------------------------------------------------------------

/// Return `true` when `driver` selects the native USB Rawlink v2 transport.
fn driver_is_usb_rawlink_v2(driver: &str) -> bool {
    let norm = normalized_driver_label(driver);
    matches!(norm.as_str(), "usb_rawlink_v2" | "usbrawlinkv2")
        || norm.starts_with("usb_rawlink_v2(")
        || norm.starts_with("usbrawlinkv2(")
}

/// True for any driver whose audio path goes through V2 native_transport
/// (USB Rawlink v2 or any ALSA family driver). All currently supported
/// drivers satisfy this — set_output_tuned rejects anything else.
fn driver_uses_native_transport(driver: &str) -> bool {
    driver_is_usb_rawlink_v2(driver) || driver_routes_via_native_alsa(driver)
}

fn native_transport_format_depth(fmt: native_transport::PcmSampleFormat) -> Option<i32> {
    use native_transport::PcmSampleFormat::*;
    Some(match fmt {
        S16LE => 16,
        S24_3LE | S24LE => 24,
        S32LE | F32LE => 32,
        F64LE => 64,
    })
}

struct UsbRuntimeInfo {
    rate: u32,
    bit_depth: u8,
    device_name: String,
}

fn active_usb_runtime_info(engine: &Engine) -> Option<UsbRuntimeInfo> {
    let runtime = engine.native_transport.runtime_info()?;
    Some(UsbRuntimeInfo {
        rate: runtime.feed.rate.load(Ordering::Relaxed),
        bit_depth: runtime.bit_depth,
        device_name: runtime.device_name,
    })
}

fn active_usb_hw_volume_supported(engine: &Engine) -> bool {
    engine.native_transport.hw_volume_supported()
}

fn active_usb_hw_volume_range(engine: &Engine) -> Option<(i32, i32, i32)> {
    engine.native_transport.hw_volume_range()
}

fn active_usb_hw_volume_channels(engine: &Engine) -> Option<Vec<u8>> {
    engine.native_transport.hw_volume_channels()
}

fn active_usb_hw_volume_get_ch(engine: &Engine, idx: usize) -> Option<i32> {
    engine.native_transport.hw_volume_get_ch(idx)
}

fn active_usb_hw_volume_set_all(engine: &mut Engine, value_raw: i32) -> bool {
    engine.native_transport.hw_volume_set_all(value_raw)
}

fn active_usb_hw_volume_set_ch(engine: &mut Engine, idx: usize, value_raw: i32) -> bool {
    engine.native_transport.hw_volume_set_ch(idx, value_raw)
}

/// Map a GStreamer format preference string to a bit depth.
///
/// Returns `0` for "auto" / unrecognised, meaning "use the device's native
/// depth".
fn preferred_format_to_bit_depth(preferred: &str) -> u8 {
    match preferred.trim().to_ascii_uppercase().as_str() {
        "S16LE" | "S16BE" | "U16LE" | "U16BE" => 16,
        "S24LE" | "S24BE" | "S24_3LE" | "S24_3BE" => 24,
        "S32LE" | "S32BE" | "F32LE" | "F32BE" => 32,
        _ => 0,
    }
}


// ---------------------------------------------------------------------------

type EventCallback = extern "C" fn(c_int, *const c_char, *mut c_void);
const EVT_STATE: c_int = 1;
const EVT_ERROR: c_int = 2;
const EVT_EOS: c_int = 3;
const EVT_TAG: c_int = 4;

fn json_escape(v: &str) -> String {
    let mut out = String::with_capacity(v.len() + 8);
    for ch in v.chars() {
        match ch {
            '\"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c.is_control() => out.push(' '),
            c => out.push(c),
        }
    }
    out
}

#[derive(Debug)]
pub struct Engine {
    dsp_config: DspGraphConfig,
    uri: String,
    last_error: Option<String>,
    event_cb: Option<EventCallback>,
    event_user_data: *mut c_void,
    pitch_semitones: f64,
    spectrum_seq: u64,
    spectrum_pos_s: f64,
    spectrum_vals: [f32; SPECTRUM_BANDS_MAX],
    spectrum_left_vals: [f32; SPECTRUM_BANDS_MAX],
    spectrum_right_vals: [f32; SPECTRUM_BANDS_MAX],
    spectrum_len: usize,
    spectrum_ring_vals: Vec<[f32; SPECTRUM_BANDS_MAX]>,
    spectrum_ring_left_vals: Vec<[f32; SPECTRUM_BANDS_MAX]>,
    spectrum_ring_right_vals: Vec<[f32; SPECTRUM_BANDS_MAX]>,
    spectrum_ring_len: Vec<u16>,
    spectrum_ring_pos_s: Vec<f64>,
    spectrum_ring_seq: Vec<u64>,
    spectrum_ring_write: usize,
    spectrum_ring_count: usize,
    /// Smoothed delta (ms) between spectrum endtime and query_position.
    /// Positive means spectrum is ahead of the sink's consumption point.
    /// Used by `probe_latency` for USB rawlink delay compensation.
    spectrum_lead_ms: f64,
    /// Holding queue for native transport spectrum frames.  Frames are held
    /// until the playback position catches up to the frame's decode-time
    /// `pos_s`, matching GStreamer's clock-synchronized delivery behaviour.
    native_spectrum_pending: VecDeque<native_transport::SpectrumFrame>,
    native_levels_pending: VecDeque<dsp::lufs::LevelFrame>,
    /// Latest released meter levels: [peak_l, rms_l, peak_r, rms_r] dBFS.
    current_levels: [f32; 4],
    /// Wall-clock smoothing for the ALSA-family fallback release clock:
    /// decoded_frame_count advances in slab quanta (~93 ms for FLAC), so
    /// between slabs the clock is extrapolated with monotonic time to keep
    /// 20 ms frame releases flowing instead of bursting per slab.
    fallback_clock_base_pos: f64,
    fallback_clock_base_at: Option<std::time::Instant>,
    /// Guards against emitting multiple EOS events for a single native transport track.
    native_eos_emitted: bool,
    fmt_probe_tick: u64,
    last_codec: String,
    last_bitrate: i32,
    last_rate: i32,
    last_depth: i32,
    source_rate: i32,
    source_depth: i32,
    preferred_output_format: String,
    spectrum_enabled: bool,
    spectrum_stereo_enabled: bool,
    spectrum_active_bands: u32,
    /// USB output config for native transport (V2). Populated when the V2
    /// driver is selected and consumed when a track is loaded.
    native_usb_config: Option<usb_audio::UsbRawSinkConfig>,
    /// ALSA mmap output config for native transport (V2). Populated when the
    /// alsa_mmap driver is selected; consumed when a track is loaded so V2
    /// can drive the ALSA mmap sink directly without going through GStreamer.
    native_alsa_config: Option<native_transport::AlsaOutputConfig>,
    #[allow(dead_code)]
    native_transport: native_transport::NativeTransportController,
    /// USB rawlink clock alignment: 0 = push (default), 1 = pull (Level 3).
    usb_clock_mode: u8,
    output_mmap_realtime_priority: i32,
    output_driver: String,
    output_device: Option<String>,
    output_buffer_us: i32,
    output_latency_us: i32,
    output_exclusive: bool,
}

impl Engine {
    fn parse_depth_from_format(fmt: &str) -> Option<i32> {
        let up = fmt.to_ascii_uppercase();
        if up.contains("S24_32") {
            return Some(24);
        }
        let mut digits = String::new();
        for ch in up.chars() {
            if ch.is_ascii_digit() {
                digits.push(ch);
            } else if !digits.is_empty() {
                break;
            }
        }
        if digits.is_empty() {
            return None;
        }
        digits.parse::<i32>().ok().filter(|v| *v > 0)
    }

    fn query_output_format(&self) -> (Option<i32>, Option<i32>) {
        // USB rawlink V2: read negotiated rate/depth from the ISO ring runtime.
        if let Some(runtime) = self.native_transport.runtime_info() {
            let rate = runtime.feed.rate.load(Ordering::Relaxed) as i32;
            let depth = runtime.bit_depth as i32;
            let rate = if rate > 0 { Some(rate) } else { None };
            let depth = if depth > 0 { Some(depth) } else { None };
            if rate.is_some() || depth.is_some() {
                return (rate, depth);
            }
        }
        // ALSA family: derive from native_transport's decoded stream spec.
        let snap = self.native_transport.snapshot();
        if let Some(spec) = snap.stream_spec.as_ref() {
            let rate = if spec.sample_rate > 0 {
                Some(spec.sample_rate as i32)
            } else {
                None
            };
            let depth = native_transport_format_depth(spec.format);
            return (rate, depth);
        }
        (None, None)
    }

    /// Update Engine's cached source/output format fields from a native_transport
    /// EVT_TAG payload (format: `key=value;key=value;…`). The event is also
    /// forwarded to the FFI consumer in drain_native_transport_events; this
    /// only updates internal state used by JSON readouts and position tracking.
    fn absorb_native_tag_event(&mut self, msg: &str) {
        for part in msg.split(';') {
            let Some((key, value)) = part.split_once('=') else {
                continue;
            };
            let key = key.trim();
            let value = value.trim();
            if value.is_empty() {
                continue;
            }
            match key {
                "codec" => {
                    if value != self.last_codec {
                        self.last_codec = value.to_string();
                    }
                }
                "bitrate" => {
                    if let Ok(v) = value.parse::<i32>() {
                        if v > 0 {
                            self.last_bitrate = v;
                        }
                    }
                }
                "rate" => {
                    if let Ok(v) = value.parse::<i32>() {
                        if v > 0 {
                            self.last_rate = v;
                        }
                    }
                }
                "depth" => {
                    if let Ok(v) = value.parse::<i32>() {
                        if v > 0 {
                            self.last_depth = v;
                        }
                    }
                }
                "source_rate" => {
                    if let Ok(v) = value.parse::<i32>() {
                        if v > 0 {
                            self.source_rate = v;
                        }
                    }
                }
                "source_depth" => {
                    if let Ok(v) = value.parse::<i32>() {
                        if v > 0 {
                            self.source_depth = v;
                        }
                    }
                }
                _ => {}
            }
        }
    }

    fn maybe_emit_tag_update(
        &mut self,
        codec: Option<String>,
        bitrate: Option<i32>,
        rate: Option<i32>,
        depth: Option<i32>,
    ) {
        let mut changed = false;
        if let Some(c) = codec {
            if !c.is_empty() && c != self.last_codec {
                self.last_codec = c;
                changed = true;
            }
        }
        if let Some(br) = bitrate {
            if br > 0 && br != self.last_bitrate {
                self.last_bitrate = br;
                changed = true;
            }
        }
        if let Some(r) = rate {
            if r > 0 && r != self.last_rate {
                self.last_rate = r;
                changed = true;
            }
        }
        if let Some(d) = depth {
            if d > 0 && d != self.last_depth {
                self.last_depth = d;
                changed = true;
            }
        }
        if !changed {
            return;
        }
        let mut parts: Vec<String> = Vec::new();
        if !self.last_codec.is_empty() {
            parts.push(format!("codec={}", self.last_codec));
        }
        if self.last_bitrate > 0 {
            parts.push(format!("bitrate={}", self.last_bitrate));
        }
        if self.last_rate > 0 {
            parts.push(format!("rate={}", self.last_rate));
        }
        if self.last_depth > 0 {
            parts.push(format!("depth={}", self.last_depth));
        }
        // Always include parsed source format alongside the output format so the
        // UI can display the original media resolution (e.g. 24-bit/96kHz) rather
        // than the internal pipeline container format (e.g. S32LE = 32-bit).
        if self.source_rate > 0 {
            parts.push(format!("source_rate={}", self.source_rate));
        }
        if self.source_depth > 0 {
            parts.push(format!("source_depth={}", self.source_depth));
        }
        if !parts.is_empty() {
            self.emit_event(EVT_TAG, &parts.join(";"));
        }
    }

    fn reset_spectrum_timeline(&mut self) {
        self.spectrum_pos_s = 0.0;
        self.spectrum_lead_ms = 0.0;
        self.spectrum_len = 0;
        self.native_spectrum_pending.clear();
        self.native_levels_pending.clear();
        // Discard frames the decode thread produced before the seek/reset.
        let _ = self.native_transport.take_level_frames();
        self.current_levels = [dsp::lufs::LEVEL_DISPLAY_FLOOR_DB; 4];
        self.spectrum_ring_write = 0;
        self.spectrum_ring_count = 0;
        self.spectrum_vals = [0.0; SPECTRUM_BANDS_MAX];
        self.spectrum_left_vals = [0.0; SPECTRUM_BANDS_MAX];
        self.spectrum_right_vals = [0.0; SPECTRUM_BANDS_MAX];
        self.spectrum_ring_vals = new_spectrum_ring_values();
        self.spectrum_ring_left_vals = new_spectrum_ring_values();
        self.spectrum_ring_right_vals = new_spectrum_ring_values();
        self.spectrum_ring_len = new_spectrum_ring_len();
        self.spectrum_ring_pos_s = new_spectrum_ring_pos_s();
        self.spectrum_ring_seq = new_spectrum_ring_seq();
        // Reset LUFS accumulators so integrated / LRA restart on each new track.
        // V2 native_transport's LufsPcmProcessor handles the reset internally
        // when load() resets per-track state.
    }

    fn set_spectrum_filter_enabled(&mut self, enabled: bool) {
        self.spectrum_enabled = enabled;
        if !enabled {
            self.reset_spectrum_timeline();
        }
        let _ = self.sync_audio_filter_graph();
    }

    fn set_spectrum_stereo_enabled(&mut self, enabled: bool) {
        self.spectrum_stereo_enabled = enabled;
        let _ = self.sync_audio_filter_graph();
    }

    fn set_spectrum_active_bands(&mut self, bands: u32) {
        self.spectrum_active_bands = bands.clamp(2, SPECTRUM_BANDS_MAX as u32);
        self.native_transport.set_spectrum_bands(self.spectrum_active_bands);
        let _ = self.sync_audio_filter_graph();
    }

    /// Hot-push the current DSP config to V2 native_transport. Name is kept
    /// to minimise churn at the ~40 setter call sites that invoke it after a
    /// config change.
    fn sync_audio_filter_graph(&mut self) -> Result<(), String> {
        let _ = self.native_transport.update_dsp_config(&self.dsp_config);
        Ok(())
    }

    fn refresh_audio_filter_graph(&mut self) -> Result<(), String> {
        self.sync_audio_filter_graph()
    }

    fn rebuild_audio_filter_graph(&mut self) -> Result<(), String> {
        self.sync_audio_filter_graph()
    }

    fn set_peq_band_gain(&mut self, band_index: usize, gain_db: f64) -> c_int {
        let clamped = match self.dsp_config.peq.set_band_gain(band_index, gain_db) {
            Ok(value) => value,
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                return -2;
            }
        };
        match self.sync_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(
                    EVT_STATE,
                    &format!(
                        "dsp-peq band={} gain_db={:.2} active={}",
                        band_index,
                        clamped,
                        self.dsp_config.has_active_processing()
                    ),
                );
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -3
            }
        }
    }

    fn reset_peq(&mut self) -> c_int {
        self.dsp_config.peq.reset();
        match self.sync_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, "dsp-peq reset");
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_dsp_master_enabled(&mut self, enabled: bool) -> c_int {
        let previous_config = self.dsp_config.clone();
        self.dsp_config.enabled = enabled;
        match self.rebuild_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(
                    EVT_STATE,
                    &format!(
                        "dsp-master enabled={} active={}",
                        self.dsp_config.enabled,
                        self.dsp_config.has_active_processing()
                    ),
                );
                0
            }
            Err(err) => {
                self.dsp_config = previous_config;
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_dsp_order(&mut self, order_csv: &str) -> c_int {
        let previous_config = self.dsp_config.clone();
        let ids: Vec<&str> = order_csv
            .split(',')
            .map(|value| value.trim())
            .filter(|value| !value.is_empty())
            .collect();
        self.dsp_config.set_order_from_ids(&ids);
        match self.rebuild_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(
                    EVT_STATE,
                    &format!("dsp-order {}", self.dsp_config.order_ids().join(",")),
                );
                0
            }
            Err(err) => {
                self.dsp_config = previous_config;
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_peq_enabled(&mut self, enabled: bool) -> c_int {
        self.dsp_config.peq.set_enabled(enabled);
        match self.sync_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(
                    EVT_STATE,
                    &format!(
                        "dsp-peq enabled={} active={}",
                        self.dsp_config.peq.enabled,
                        self.dsp_config.has_active_processing()
                    ),
                );
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_convolver_enabled(&mut self, enabled: bool) -> c_int {
        self.dsp_config.convolver.set_enabled(enabled);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(
                    EVT_STATE,
                    &format!(
                        "dsp-convolver enabled={} active={} taps={}",
                        self.dsp_config.convolver.enabled,
                        self.dsp_config.has_active_processing(),
                        self.dsp_config.convolver.tap_count()
                    ),
                );
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_convolver_mix(&mut self, mix: f64) -> c_int {
        let clamped = self.dsp_config.convolver.set_mix(mix);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-convolver mix={:.3}", clamped));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_convolver_pre_delay(&mut self, ms: f64) -> c_int {
        let clamped = self.dsp_config.convolver.set_pre_delay_ms(ms);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(
                    EVT_STATE,
                    &format!("dsp-convolver pre_delay_ms={:.1}", clamped),
                );
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_limiter_enabled(&mut self, enabled: bool) -> c_int {
        self.dsp_config.limiter.set_enabled(enabled);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(
                    EVT_STATE,
                    &format!(
                        "dsp-limiter enabled={} active={} threshold={:.3} ratio={:.2}",
                        self.dsp_config.limiter.enabled,
                        self.dsp_config.has_active_processing(),
                        self.dsp_config.limiter.threshold,
                        self.dsp_config.limiter.ratio
                    ),
                );
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_limiter_threshold(&mut self, threshold: f64) -> c_int {
        let clamped = self.dsp_config.limiter.set_threshold(threshold);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-limiter threshold={:.3}", clamped));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_limiter_ratio(&mut self, ratio: f64) -> c_int {
        let clamped = self.dsp_config.limiter.set_ratio(ratio);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-limiter ratio={:.2}", clamped));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_resampler_enabled(&mut self, enabled: bool) -> c_int {
        self.dsp_config.resampler.set_enabled(enabled);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-resampler enabled={enabled}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_resampler_target_rate(&mut self, rate: u32) -> c_int {
        self.dsp_config.resampler.set_target_rate(rate);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-resampler target_rate={rate}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_resampler_quality(&mut self, quality: i32) -> c_int {
        self.dsp_config.resampler.set_quality(quality);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-resampler quality={quality}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_tape_enabled(&mut self, enabled: bool) -> c_int {
        self.dsp_config.tape.set_enabled(enabled);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-tape enabled={enabled}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_tape_drive(&mut self, drive: i32) -> c_int {
        self.dsp_config.tape.set_drive(drive);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-tape drive={drive}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_tape_tone(&mut self, tone: i32) -> c_int {
        self.dsp_config.tape.set_tone(tone);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-tape tone={tone}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_tape_warmth(&mut self, warmth: i32) -> c_int {
        self.dsp_config.tape.set_warmth(warmth);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-tape warmth={warmth}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_tube_enabled(&mut self, enabled: bool) -> c_int {
        self.dsp_config.tube.set_enabled(enabled);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-tube enabled={enabled}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_tube_drive(&mut self, drive: i32) -> c_int {
        self.dsp_config.tube.set_drive(drive);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-tube drive={drive}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_tube_bias(&mut self, bias: i32) -> c_int {
        self.dsp_config.tube.set_bias(bias);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-tube bias={bias}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_tube_sag(&mut self, sag: i32) -> c_int {
        self.dsp_config.tube.set_sag(sag);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-tube sag={sag}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_tube_air(&mut self, air: i32) -> c_int {
        self.dsp_config.tube.set_air(air);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-tube air={air}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_widener_enabled(&mut self, enabled: bool) -> c_int {
        self.dsp_config.widener.set_enabled(enabled);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-widener enabled={enabled}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_widener_width(&mut self, width: i32) -> c_int {
        self.dsp_config.widener.set_width(width);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-widener width={width}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_widener_bass_mono_freq(&mut self, freq: i32) -> c_int {
        self.dsp_config.widener.set_bass_mono_freq(freq);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-widener bass_mono_freq={freq}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn set_widener_bass_mono_amount(&mut self, amount: i32) -> c_int {
        self.dsp_config.widener.set_bass_mono_amount(amount);
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, &format!("dsp-widener bass_mono_amount={amount}"));
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn load_convolver_ir(&mut self, path: &str) -> c_int {
        let mut updated = self.dsp_config.convolver.clone();
        if let Err(err) = updated.load_from_file(path) {
            self.set_error(err.clone());
            self.emit_event(EVT_ERROR, &err);
            return -2;
        }
        self.dsp_config.convolver = updated;
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(
                    EVT_STATE,
                    &format!(
                        "dsp-convolver load path={} taps={}",
                        self.dsp_config.convolver.impulse_path,
                        self.dsp_config.convolver.tap_count()
                    ),
                );
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -3
            }
        }
    }

    fn clear_convolver_ir(&mut self) -> c_int {
        self.dsp_config.convolver.clear();
        match self.refresh_audio_filter_graph() {
            Ok(()) => {
                self.emit_event(EVT_STATE, "dsp-convolver cleared");
                0
            }
            Err(err) => {
                self.set_error(err.clone());
                self.emit_event(EVT_ERROR, &err);
                -2
            }
        }
    }

    fn new() -> Result<Self, String> {
        let dsp_config = DspGraphConfig::default();
        let spectrum_enabled = false;

        Ok(Self {
            dsp_config,
            uri: String::new(),
            last_error: None,
            event_cb: None,
            event_user_data: ptr::null_mut(),
            pitch_semitones: 0.0,
            spectrum_seq: 0,
            spectrum_pos_s: 0.0,
            spectrum_vals: [0.0; SPECTRUM_BANDS_MAX],
            spectrum_left_vals: [0.0; SPECTRUM_BANDS_MAX],
            spectrum_right_vals: [0.0; SPECTRUM_BANDS_MAX],
            spectrum_len: 0,
            spectrum_ring_vals: new_spectrum_ring_values(),
            spectrum_ring_left_vals: new_spectrum_ring_values(),
            spectrum_ring_right_vals: new_spectrum_ring_values(),
            spectrum_ring_len: new_spectrum_ring_len(),
            spectrum_ring_pos_s: new_spectrum_ring_pos_s(),
            spectrum_ring_seq: new_spectrum_ring_seq(),
            spectrum_ring_write: 0,
            spectrum_ring_count: 0,
            spectrum_lead_ms: 0.0,
            native_spectrum_pending: VecDeque::new(),
            native_levels_pending: VecDeque::new(),
            current_levels: [dsp::lufs::LEVEL_DISPLAY_FLOOR_DB; 4],
            fallback_clock_base_pos: 0.0,
            fallback_clock_base_at: None,
            native_eos_emitted: false,
            fmt_probe_tick: 0,
            last_codec: String::new(),
            last_bitrate: 0,
            last_rate: 0,
            last_depth: 0,
            source_rate: 0,
            source_depth: 0,
            preferred_output_format: String::new(),
            spectrum_enabled,
            spectrum_stereo_enabled: false,
            spectrum_active_bands: SPECTRUM_ACTIVE_BANDS_DEFAULT,
            native_usb_config: None,
            native_alsa_config: None,
            native_transport: native_transport::NativeTransportController::new(),
            usb_clock_mode: 0,
            output_mmap_realtime_priority: ALSA_MMAP_RT_PRIORITY_DEFAULT,
            output_driver: String::new(),
            output_device: None,
            output_buffer_us: 100_000,
            output_latency_us: 10_000,
            output_exclusive: false,
        })
    }

    fn set_error(&mut self, msg: impl Into<String>) {
        self.last_error = Some(msg.into());
    }

    fn emit_event(&self, evt: c_int, msg: &str) {
        if let Some(cb) = self.event_cb {
            if let Ok(cmsg) = CString::new(msg) {
                cb(evt, cmsg.as_ptr(), self.event_user_data);
            } else {
                cb(evt, ptr::null(), self.event_user_data);
            }
        }
    }

    fn maybe_load_native_transport_for_uri(&mut self, uri: &str) {
        let is_v2_usb = driver_is_usb_rawlink_v2(&self.output_driver);
        let is_native_alsa = driver_routes_via_native_alsa(&self.output_driver);
        if !(is_v2_usb || is_native_alsa) {
            let _ = self.native_transport.stop();
            return;
        }
        let source = match native_transport::NativeTransportSource::from_tidal_uri(uri) {
            Ok(source) => source,
            Err(err) => {
                self.emit_event(EVT_STATE, &format!("native-transport skipped: {err}"));
                return;
            }
        };
        let summary = format!(
            "native-transport load source={:?} locator={}",
            source.kind(),
            source.locator()
        );
        let dsp_active = self.dsp_config.has_native_transport_processing();
        let unsupported = if self
            .dsp_config
            .has_native_transport_unsupported_processing()
        {
            self.dsp_config.native_transport_unsupported_modules()
        } else {
            Vec::new()
        };
        if !unsupported.is_empty() {
            self.emit_event(
                EVT_STATE,
                &format!(
                    "native-transport dsp unsupported skipped modules={}",
                    unsupported.join(",")
                ),
            );
        }
        let output_target = if is_v2_usb {
            self.native_usb_config
                .clone()
                .map(native_transport::NativeOutputTarget::Usb)
        } else if is_native_alsa {
            self.native_alsa_config
                .clone()
                .map(native_transport::NativeOutputTarget::Alsa)
        } else {
            None
        };
        eprintln!(
            "[native-transport] load: dsp_active={} bit_perfect={} output_target={} master={} peq={} conv={} tape={} tube={} wid={} lim={} resamp={}",
            dsp_active, !dsp_active, output_target.is_some(),
            self.dsp_config.enabled,
            self.dsp_config.peq.is_active(),
            self.dsp_config.convolver.is_active(),
            self.dsp_config.tape.is_active(),
            self.dsp_config.tube.is_active(),
            self.dsp_config.widener.is_active(),
            self.dsp_config.limiter.is_active(),
            self.dsp_config.resampler.is_active(),
        );
        let request = native_transport::NativeTransportLoadRequest {
            source,
            target_driver: self.output_driver.clone(),
            bit_perfect: !dsp_active,
            output_target,
            dsp_config: if dsp_active { Some(self.dsp_config.clone()) } else { None },
        };
        self.native_eos_emitted = false;
        match self.native_transport.load(request) {
            Ok(()) => self.emit_event(EVT_STATE, &summary),
            Err(err) => self.emit_event(EVT_ERROR, &format!("native-transport load failed: {err}")),
        }
    }

    fn drain_native_transport_events(&mut self) {
        for (evt, msg) in self.native_transport.take_events() {
            if evt == EVT_ERROR {
                self.set_error(msg.clone());
            }
            if evt == EVT_TAG {
                self.absorb_native_tag_event(&msg);
            }
            self.emit_event(evt, &msg);
        }
        // Playback clock used to release position-stamped frames (spectrum
        // and meter levels alike). Only USB Rawlink publishes runtime_info
        // with a hardware clock; the ALSA-family drivers (ALSA, PipeWire
        // bridge) never fill it, so fall back to the decode clock — the same
        // one rac_get_position reports for those drivers. Without the
        // fallback the gate never opens and every frame is held until the
        // safety valve drops it.
        let snap = self.native_transport.snapshot();
        let seek_off = snap.seek_offset_s;
        let hw_clock = self.native_transport.runtime_info().is_some();
        let playback_pos_s = if let Some(rt) = self.native_transport.runtime_info() {
            seek_off + rt.feed.playback_elapsed_s().unwrap_or(0.0)
        } else {
            let rate = snap
                .stream_spec
                .as_ref()
                .map(|s| s.sample_rate as f64)
                .unwrap_or(0.0);
            let raw = if rate > 0.0 {
                seek_off + snap.decoded_frame_count as f64 / rate
            } else {
                seek_off
            };
            // decoded_frame_count moves in slab quanta; smooth it with
            // monotonic time so the release gate ticks continuously.
            let now = std::time::Instant::now();
            let playing = snap.state == native_transport::NativeTransportState::Playing;
            if !playing {
                self.fallback_clock_base_pos = raw;
                self.fallback_clock_base_at = None;
                raw
            } else {
                if raw > self.fallback_clock_base_pos + 1e-9
                    || raw < self.fallback_clock_base_pos - 0.5
                {
                    self.fallback_clock_base_pos = raw;
                    self.fallback_clock_base_at = Some(now);
                }
                let extra = self
                    .fallback_clock_base_at
                    .map(|t| now.duration_since(t).as_secs_f64())
                    .unwrap_or(0.0)
                    .min(0.25);
                self.fallback_clock_base_pos + extra
            }
        };

        if self.spectrum_enabled {
            // Enqueue newly arrived frames from the decode thread.
            for frame in self.native_transport.take_spectrum_frames() {
                self.native_spectrum_pending.push_back(frame);
            }
            // Release frames whose decode-time pos_s has been reached by the
            // playback clock.  This replicates GStreamer's clock-synchronized
            // spectrum delivery: frames are held until the audio actually plays.
            while let Some(frame) = self.native_spectrum_pending.front() {
                if frame.pos_s > playback_pos_s + 0.02 {
                    break; // not yet — hold for next pump cycle
                }
                let frame = self.native_spectrum_pending.pop_front().unwrap();
                let n = (frame.bands as usize).min(SPECTRUM_BANDS_MAX);
                self.push_spectrum_ring(&*frame.mono, &*frame.left, &*frame.right, n, frame.pos_s);
            }
            // Safety valve: cap pending queue to ~2s of frames to prevent
            // unbounded growth if playback stalls.
            while self.native_spectrum_pending.len() > 120 {
                self.native_spectrum_pending.pop_front();
            }
        } else {
            self.native_spectrum_pending.clear();
        }

        // Meter level frames go through the same playback-clock gate so the
        // bars move at their 16 ms production cadence aligned to what is
        // audible — the decode thread hands them over in slab-sized bursts.
        //
        // On the ALSA-family fallback the "playback" clock IS the decode
        // front, so every frame stamp is already behind it and the gate
        // would pass whole slabs at once. Hold those frames by the rough
        // output-pipeline depth (ALSA buffer + queued slabs) so they
        // trickle out at production cadence near the audible time. The USB
        // hardware clock genuinely lags decode, so it needs no offset.
        let level_release_pos = if hw_clock {
            playback_pos_s
        } else {
            (playback_pos_s - 0.30).max(0.0)
        };
        for frame in self.native_transport.take_level_frames() {
            self.native_levels_pending.push_back(frame);
        }
        while let Some(frame) = self.native_levels_pending.front() {
            if frame.pos_s > level_release_pos + 0.02 {
                break;
            }
            let frame = self.native_levels_pending.pop_front().unwrap();
            self.current_levels = [frame.peak_l, frame.rms_l, frame.peak_r, frame.rms_r];
        }
        while self.native_levels_pending.len() > 600 {
            self.native_levels_pending.pop_front();
        }

        // Detect end-of-stream for native transport: decode worker finished
        // (decode_completed=true, runtime cleared) → emit EOS so Python
        // triggers next-track.
        if !self.native_eos_emitted
            && driver_uses_native_transport(&self.output_driver)
        {
            let snap = self.native_transport.snapshot();
            if snap.decode_completed && snap.decoded_frame_count > 0 {
                self.native_eos_emitted = true;
                eprintln!("native-transport EOS: decoded_frames={}", snap.decoded_frame_count);
                self.emit_event(EVT_EOS, "native-transport-eos");
            }
        }
    }

    fn push_spectrum_ring(
        &mut self,
        mono: &[f32; SPECTRUM_BANDS_MAX],
        left: &[f32; SPECTRUM_BANDS_MAX],
        right: &[f32; SPECTRUM_BANDS_MAX],
        n: usize,
        frame_pos_s: f64,
    ) {
        if n == 0 {
            return;
        }
        // Backward-seek detection: reset ring if position jumps backward.
        if self.spectrum_len > 0 && frame_pos_s.is_finite() && frame_pos_s >= 0.0 {
            let prev_pos_s = self.spectrum_pos_s;
            if prev_pos_s.is_finite() && frame_pos_s < (prev_pos_s - 0.25) {
                self.reset_spectrum_timeline();
            }
        }
        self.spectrum_pos_s = frame_pos_s;
        self.spectrum_vals[..n].copy_from_slice(&mono[..n]);
        self.spectrum_left_vals[..n].copy_from_slice(&left[..n]);
        self.spectrum_right_vals[..n].copy_from_slice(&right[..n]);
        self.spectrum_len = n;
        self.spectrum_seq = self.spectrum_seq.wrapping_add(1);
        let ridx = self.spectrum_ring_write;
        self.spectrum_ring_vals[ridx] = [0.0; SPECTRUM_BANDS_MAX];
        self.spectrum_ring_left_vals[ridx] = [0.0; SPECTRUM_BANDS_MAX];
        self.spectrum_ring_right_vals[ridx] = [0.0; SPECTRUM_BANDS_MAX];
        self.spectrum_ring_vals[ridx][..n].copy_from_slice(&mono[..n]);
        self.spectrum_ring_left_vals[ridx][..n].copy_from_slice(&left[..n]);
        self.spectrum_ring_right_vals[ridx][..n].copy_from_slice(&right[..n]);
        self.spectrum_ring_len[ridx] = n as u16;
        self.spectrum_ring_pos_s[ridx] = frame_pos_s;
        self.spectrum_ring_seq[ridx] = self.spectrum_seq;
        self.spectrum_ring_write = (self.spectrum_ring_write + 1) % SPECTRUM_RING_CAP;
        self.spectrum_ring_count = (self.spectrum_ring_count + 1).min(SPECTRUM_RING_CAP);
    }

    fn pump_events(&mut self) -> c_int {
        self.drain_native_transport_events();
        // Periodic format-probe fallback: native_transport emits EVT_TAG once
        // per track (handled in drain), but we still poll for late-arriving
        // negotiated rate/depth (e.g. ALSA mmap session that hadn't published
        // its stream_spec at decode-start time).
        self.fmt_probe_tick = self.fmt_probe_tick.wrapping_add(1);
        if self.fmt_probe_tick % 10 == 0 {
            let (rate, depth) = self.query_output_format();
            self.maybe_emit_tag_update(None, None, rate, depth);
        }
        0
    }

    fn set_output_tuned(
        &mut self,
        driver: &str,
        device: Option<&str>,
        buffer_us: i32,
        latency_us: i32,
        exclusive: bool,
    ) -> c_int {
        let had_v2_usb = driver_is_usb_rawlink_v2(&self.output_driver);
        if had_v2_usb {
            let _ = self.native_transport.stop_and_release();
        } else {
            let _ = self.native_transport.stop();
        }
        // After releasing a USB rawlink session, snd-usb-audio re-attaches
        // asynchronously.  libusb_release_interface() returns before the kernel
        // driver finishes its probe and creates the ALSA device nodes.  Without
        // this wait, switching to an ALSA/auto driver immediately after rawlink
        // finds no ALSA device.  300 ms is enough for snd-usb-audio to complete
        // its initialisation on all tested hardware.
        if had_v2_usb {
            std::thread::sleep(std::time::Duration::from_millis(300));
        }

        if let Err(err) = self.sync_audio_filter_graph() {
            self.set_error(format!("audio-filter setup failed: {err}"));
            self.emit_event(EVT_ERROR, &format!("audio-filter setup failed: {err}"));
        }
        self.emit_event(
            EVT_STATE,
            if self.spectrum_enabled {
                "spectrum-path=enabled"
            } else {
                "spectrum-path=disabled"
            },
        );
        let resolved_device = device
            .map(|d| d.trim().to_string())
            .filter(|d| !d.is_empty());
        let device_norm = resolved_device.as_deref();

        // V2 native_transport routes audio through ALSA (Auto / ALSA(auto) /
        // ALSA(mmap)) or libusb (USB rawlink v2). Auto and ALSA(auto) default
        // to the ALSA `default` device (which goes through the PipeWire /
        // PulseAudio ALSA bridge on most desktops); ALSA(mmap) defaults to
        // `hw:0,0` because users picking mmap typically want raw hardware.
        let route_via_native_alsa = driver_routes_via_native_alsa(driver);
        let route_via_native_usb = driver_is_usb_rawlink_v2(driver);

        if !route_via_native_alsa && !route_via_native_usb {
            self.set_error(format!("unsupported driver: {driver}"));
            self.emit_event(EVT_ERROR, &format!("unsupported driver: {driver}"));
            return -14;
        }

        self.output_driver = driver.to_string();
        self.output_device = resolved_device.clone();
        self.output_buffer_us = buffer_us;
        self.output_latency_us = latency_us;
        self.output_exclusive = exclusive;

        // Pre-claim the USB device for native transport (v2) so PipeWire
        // cannot reclaim it before the first track starts playing.
        if route_via_native_usb {
            let pref_depth = preferred_format_to_bit_depth(&self.preferred_output_format);
            let device_id = device_norm.unwrap_or("");
            match usb_audio::raw_config::build_usb_raw_sink_config(
                device_id,
                pref_depth,
                self.usb_clock_mode,
            ) {
                Ok(build) => {
                    let cfg = build.config;
                    let _ = self.native_transport.claim_device(
                        &cfg.device_id,
                        cfg.bit_depth,
                        cfg.alt_profile,
                    );
                    self.native_usb_config = Some(cfg);
                }
                Err(err) => {
                    self.emit_event(
                        EVT_STATE,
                        &format!("native-transport config build failed: {err}"),
                    );
                    self.native_usb_config = None;
                }
            }
        } else {
            self.native_usb_config = None;
            // Already released by stop_and_release() at the top of
            // set_output_tuned — no extra release_device() needed.
        }

        if route_via_native_alsa {
            let is_pw = driver_is_pipewire(driver);
            let default_device = if is_pw {
                "pipewire"
            } else if driver_is_alsa_mmap(driver) {
                "hw:0,0"
            } else {
                "default"
            };
            // PipeWire driver is intentionally non-bit-perfect: PipeWire's
            // graph does its own resampling, so exclusive (hw:) access
            // would defeat the purpose. Always force exclusive=false here.
            let effective_exclusive = exclusive && !is_pw;
            if is_pw {
                self.output_exclusive = false;
            }
            let chosen_device = device_norm.unwrap_or(default_device).to_string();
            // PipeWire driver: enumerated sinks come back as bare PipeWire
            // node names (e.g. `alsa_output.usb-FIIO_KA13-01.analog-stereo`).
            // Translate to the ALSA pipewire-plugin's NODE arg so snd_pcm_open
            // routes to the chosen sink instead of the session default.
            // Plain "pipewire" or any explicit "pipewire:..." string is
            // passed through unchanged. (The installed pipewire-alsa plugin
            // advertises args as `SERVER NODE EXCLUSIVE ROLE RATE FORMAT
            // CHANNELS …` — not PLAYBACK_NODE, which is the protocol-pulse
            // variant in some forks.)
            let final_device = if is_pw
                && chosen_device != "pipewire"
                && !chosen_device.starts_with("pipewire:")
            {
                format!("pipewire:NODE={}", chosen_device)
            } else {
                chosen_device
            };
            // The ALSA latency dropdown only applies to direct ALSA(auto)/
            // (mmap) hardware paths. Auto(Default) and PipeWire both route
            // through PipeWire's ALSA bridge, where periods below the
            // PipeWire quantum (~21 ms at 48 kHz) cause continuous
            // underruns and silent playback. Pin those drivers to the
            // 100 ms / 10 ms defaults regardless of the saved
            // ALSA-only profile so the bridge gets a buffer it can honor.
            let auto_default = normalized_driver_label(driver).starts_with("auto");
            let routes_via_pw_bridge = is_pw || auto_default;
            let effective_buffer_us = if routes_via_pw_bridge {
                100_000
            } else if buffer_us > 0 {
                buffer_us as u32
            } else {
                100_000
            };
            let effective_latency_us = if routes_via_pw_bridge {
                10_000
            } else if latency_us > 0 {
                latency_us as u32
            } else {
                10_000
            };
            self.native_alsa_config = Some(native_transport::AlsaOutputConfig {
                device: final_device,
                buffer_us: effective_buffer_us,
                latency_us: effective_latency_us,
                realtime_priority: self.output_mmap_realtime_priority,
                preferred_format: self.preferred_output_format.clone(),
                exclusive: effective_exclusive,
            });
        } else {
            self.native_alsa_config = None;
        }

        self.emit_event(
            EVT_STATE,
            &format!(
                "output-switched driver={driver} device={}",
                device_norm.unwrap_or("default")
            ),
        );
        0
    }

    fn set_output(&mut self, driver: &str, device: Option<&str>) -> c_int {
        self.set_output_tuned(driver, device, 100_000, 10_000, false)
    }

    fn set_mmap_realtime_priority(&mut self, priority: i32) -> c_int {
        self.output_mmap_realtime_priority = priority.max(0);
        0
    }
}

fn read_running_alsa_hw_params() -> (Option<i32>, Option<i32>) {
    let mut out_rate: Option<i32> = None;
    let mut out_depth: Option<i32> = None;
    let Ok(cards) = std::fs::read_dir("/proc/asound") else {
        return (None, None);
    };
    for c in cards.flatten() {
        let card_name = c.file_name().to_string_lossy().to_string();
        if !card_name.starts_with("card") {
            continue;
        }
        let card_path = c.path();
        let Ok(pcms) = std::fs::read_dir(&card_path) else {
            continue;
        };
        for p in pcms.flatten() {
            let pcm_name = p.file_name().to_string_lossy().to_string();
            if !(pcm_name.starts_with("pcm") && pcm_name.contains('p')) {
                continue;
            }
            let pcm_path = p.path();
            let Ok(subs) = std::fs::read_dir(&pcm_path) else {
                continue;
            };
            for s in subs.flatten() {
                let sub_name = s.file_name().to_string_lossy().to_string();
                if !sub_name.starts_with("sub") {
                    continue;
                }
                let status_path = s.path().join("status");
                let hw_path = s.path().join("hw_params");
                let Ok(status_txt) = std::fs::read_to_string(&status_path) else {
                    continue;
                };
                if !status_txt.to_ascii_uppercase().contains("RUNNING") {
                    continue;
                }
                let Ok(hw_txt) = std::fs::read_to_string(&hw_path) else {
                    continue;
                };
                for ln in hw_txt.lines() {
                    let t = ln.trim();
                    if let Some(rest) = t.strip_prefix("format:") {
                        if let Some(d) = Engine::parse_depth_from_format(rest.trim()) {
                            out_depth = Some(d);
                        }
                    } else if let Some(rest) = t.strip_prefix("rate:") {
                        let tok = rest.trim().split_whitespace().next().unwrap_or("");
                        if let Ok(r) = tok.parse::<i32>() {
                            if r > 0 {
                                out_rate = Some(r);
                            }
                        }
                    }
                }
                if out_rate.is_some() || out_depth.is_some() {
                    return (out_rate, out_depth);
                }
            }
        }
    }
    (out_rate, out_depth)
}

#[no_mangle]
pub extern "C" fn rac_get_spectrum_frame(
    ptr: *const Engine,
    out_vals: *mut f32,
    max_len: c_int,
    out_len: *mut c_int,
    out_pos_s: *mut c_double,
    out_seq: *mut u64,
) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if out_vals.is_null() || out_len.is_null() || out_pos_s.is_null() || out_seq.is_null() {
        return -2;
    }
    let max_n = if max_len <= 0 {
        0usize
    } else {
        max_len as usize
    };
    let n = engine
        .spectrum_len
        .min(max_n)
        .min(engine.spectrum_vals.len());
    if n == 0 {
        unsafe {
            *out_len = 0;
            *out_pos_s = engine.spectrum_pos_s;
            *out_seq = engine.spectrum_seq;
        }
        return 0;
    }
    unsafe {
        ptr::copy_nonoverlapping(engine.spectrum_vals.as_ptr(), out_vals, n);
        *out_len = n as c_int;
        *out_pos_s = engine.spectrum_pos_s;
        *out_seq = engine.spectrum_seq;
    }
    0
}

/// Retrieve the latest K-weighted LUFS values and dynamic range from the DSP meter.
///
/// All five output pointers must be non-null.  Values are f32:
///   - `out_m`   : Momentary LUFS  (~400 ms).    f32::NEG_INFINITY when unavailable.
///   - `out_s`   : Short-term LUFS (~3 s).       f32::NEG_INFINITY when unavailable.
///   - `out_i`   : Integrated LUFS (gated).      f32::NEG_INFINITY when unavailable.
///   - `out_lra` : Loudness Range  (~30 s LU).   0.0 when unavailable.
///   - `out_dr`  : Dynamic Range   (~4 s, dBFS). 0.0 when unavailable.
///
/// Returns 0 on success, −1 if the engine pointer is null, −2 if any output pointer is null.
#[no_mangle]
pub extern "C" fn rac_get_lufs(
    ptr: *const Engine,
    out_m: *mut f32,
    out_s: *mut f32,
    out_i: *mut f32,
    out_lra: *mut f32,
    out_dr: *mut f32,
) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if out_m.is_null()
        || out_s.is_null()
        || out_i.is_null()
        || out_lra.is_null()
        || out_dr.is_null()
    {
        return -2;
    }
    let vals: LufsValues = engine.native_transport.lufs_values();
    unsafe {
        *out_m = vals.momentary;
        *out_s = vals.short_term;
        *out_i = vals.integrated;
        *out_lra = vals.lra;
        *out_dr = vals.dr;
    }
    0
}

/// Per-channel time-domain meter levels (dBFS): true sample peak and RMS
/// for L and R, PPM-ballistic on a 16 ms cadence and released against the
/// playback clock (see drain_native_transport_events). Separate from
/// rac_get_lufs so older callers keep their ABI. Values at or below -100
/// mean silence/unavailable.
#[no_mangle]
pub extern "C" fn rac_get_levels(
    ptr: *const Engine,
    out_peak_l: *mut f32,
    out_rms_l: *mut f32,
    out_peak_r: *mut f32,
    out_rms_r: *mut f32,
) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if out_peak_l.is_null() || out_rms_l.is_null() || out_peak_r.is_null() || out_rms_r.is_null() {
        return -2;
    }
    let [peak_l, rms_l, peak_r, rms_r] = engine.current_levels;
    unsafe {
        *out_peak_l = peak_l;
        *out_rms_l = rms_l;
        *out_peak_r = peak_r;
        *out_rms_r = rms_r;
    }
    0
}

#[no_mangle]
pub extern "C" fn rac_get_spectrum_frames_since(
    ptr: *const Engine,
    since_seq: u64,
    out_vals: *mut f32,
    max_frames: c_int,
    max_bands: c_int,
    out_frames: *mut c_int,
    out_lens: *mut c_int,
    out_pos_s: *mut c_double,
    out_seq: *mut u64,
) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if out_vals.is_null()
        || out_frames.is_null()
        || out_lens.is_null()
        || out_pos_s.is_null()
        || out_seq.is_null()
    {
        return -2;
    }
    let max_f = if max_frames <= 0 {
        0usize
    } else {
        max_frames as usize
    };
    let max_b = if max_bands <= 0 {
        0usize
    } else {
        max_bands as usize
    };
    if max_f == 0 || max_b == 0 {
        unsafe {
            *out_frames = 0;
        }
        return 0;
    }

    let oldest = if engine.spectrum_ring_count < SPECTRUM_RING_CAP {
        0usize
    } else {
        engine.spectrum_ring_write
    };

    let mut written = 0usize;
    for j in 0..engine.spectrum_ring_count {
        let idx = (oldest + j) % SPECTRUM_RING_CAP;
        let seq = engine.spectrum_ring_seq[idx];
        if seq <= since_seq {
            continue;
        }
        if written >= max_f {
            break;
        }
        let len = (engine.spectrum_ring_len[idx] as usize)
            .min(max_b)
            .min(SPECTRUM_BANDS_MAX);
        let base = written * max_b;
        unsafe {
            ptr::copy_nonoverlapping(
                engine.spectrum_ring_vals[idx].as_ptr(),
                out_vals.add(base),
                len,
            );
            *out_lens.add(written) = len as c_int;
            *out_pos_s.add(written) = engine.spectrum_ring_pos_s[idx];
            *out_seq.add(written) = seq;
        }
        written += 1;
    }

    unsafe {
        *out_frames = written as c_int;
    }
    0
}

#[no_mangle]
pub extern "C" fn rac_get_stereo_spectrum_frames_since(
    ptr: *const Engine,
    since_seq: u64,
    out_mono_vals: *mut f32,
    out_left_vals: *mut f32,
    out_right_vals: *mut f32,
    max_frames: c_int,
    max_bands: c_int,
    out_frames: *mut c_int,
    out_lens: *mut c_int,
    out_pos_s: *mut c_double,
    out_seq: *mut u64,
) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if out_mono_vals.is_null()
        || out_left_vals.is_null()
        || out_right_vals.is_null()
        || out_frames.is_null()
        || out_lens.is_null()
        || out_pos_s.is_null()
        || out_seq.is_null()
    {
        return -2;
    }
    let max_f = if max_frames <= 0 {
        0usize
    } else {
        max_frames as usize
    };
    let max_b = if max_bands <= 0 {
        0usize
    } else {
        max_bands as usize
    };
    if max_f == 0 || max_b == 0 {
        unsafe {
            *out_frames = 0;
        }
        return 0;
    }

    let oldest = if engine.spectrum_ring_count < SPECTRUM_RING_CAP {
        0usize
    } else {
        engine.spectrum_ring_write
    };

    let mut written = 0usize;
    for j in 0..engine.spectrum_ring_count {
        let idx = (oldest + j) % SPECTRUM_RING_CAP;
        let seq = engine.spectrum_ring_seq[idx];
        if seq <= since_seq {
            continue;
        }
        if written >= max_f {
            break;
        }
        let len = (engine.spectrum_ring_len[idx] as usize)
            .min(max_b)
            .min(SPECTRUM_BANDS_MAX);
        let base = written * max_b;
        unsafe {
            ptr::copy_nonoverlapping(
                engine.spectrum_ring_vals[idx].as_ptr(),
                out_mono_vals.add(base),
                len,
            );
            ptr::copy_nonoverlapping(
                engine.spectrum_ring_left_vals[idx].as_ptr(),
                out_left_vals.add(base),
                len,
            );
            ptr::copy_nonoverlapping(
                engine.spectrum_ring_right_vals[idx].as_ptr(),
                out_right_vals.add(base),
                len,
            );
            *out_lens.add(written) = len as c_int;
            *out_pos_s.add(written) = engine.spectrum_ring_pos_s[idx];
            *out_seq.add(written) = seq;
        }
        written += 1;
    }

    unsafe {
        *out_frames = written as c_int;
    }
    0
}

#[no_mangle]
pub extern "C" fn rac_set_spectrum_enabled(ptr: *mut Engine, enabled: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_spectrum_filter_enabled(enabled != 0);
    if !engine.spectrum_enabled {
        engine.spectrum_len = 0;
        engine.spectrum_ring_count = 0;
    }
    0
}

#[no_mangle]
pub extern "C" fn rac_set_spectrum_stereo_enabled(ptr: *mut Engine, enabled: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_spectrum_stereo_enabled(enabled != 0);
    0
}

#[no_mangle]
pub extern "C" fn rac_set_spectrum_active_bands(ptr: *mut Engine, bands: c_uint) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_spectrum_active_bands(bands as u32);
    0
}


fn parse_alsa_card_labels(content: &str) -> HashMap<String, String> {
    let mut out = HashMap::new();
    for raw in content.lines() {
        let line = raw.trim_start();
        if line.is_empty() {
            continue;
        }
        let first = line.split_whitespace().next().unwrap_or("");
        if !first.chars().all(|c| c.is_ascii_digit()) {
            continue;
        }
        let idx = first.to_string();
        let dash_pos = match line.rfind(" - ") {
            Some(v) => v,
            None => continue,
        };
        let label = line[(dash_pos + 3)..].trim();
        if label.is_empty() {
            continue;
        }
        out.insert(idx, label.to_string());
    }
    out
}

fn parse_alsa_playback_pcm_index(entry_name: &str) -> Option<String> {
    if !(entry_name.starts_with("pcm") && entry_name.ends_with('p')) {
        return None;
    }
    let middle = &entry_name[3..(entry_name.len() - 1)];
    if middle.is_empty() || !middle.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    Some(middle.to_string())
}

fn parse_alsa_hw_device_id(device_id: &str) -> Option<(String, Option<String>)> {
    let trimmed = device_id.trim();
    let rest = trimmed.strip_prefix("hw:")?;
    let mut parts = rest.split(',');
    let card_idx = parts.next()?.trim();
    if card_idx.is_empty() || !card_idx.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let pcm_idx = parts
        .next()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty() && v.chars().all(|c| c.is_ascii_digit()));
    Some((card_idx.to_string(), pcm_idx))
}

fn parse_alsa_playback_formats_from_stream_text(content: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut in_playback = false;
    for raw in content.lines() {
        let line = raw.trim();
        if line.eq_ignore_ascii_case("Playback:") {
            in_playback = true;
            continue;
        }
        if line.eq_ignore_ascii_case("Capture:") {
            in_playback = false;
            continue;
        }
        if !in_playback {
            continue;
        }
        if let Some(rest) = line.strip_prefix("Format:") {
            let fmt = rest.trim().to_ascii_uppercase();
            if !fmt.is_empty() {
                out.push(fmt);
            }
        }
    }
    out.sort();
    out.dedup();
    out
}

fn read_alsa_card_playback_formats_from_proc_root(proc_root: &Path, card_idx: &str) -> Vec<String> {
    let mut out = Vec::new();
    let card_path = proc_root.join(format!("card{card_idx}"));
    let Ok(entries) = std::fs::read_dir(card_path) else {
        return out;
    };
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().to_string();
        if !(name.starts_with("stream") && name[6..].chars().all(|c| c.is_ascii_digit())) {
            continue;
        }
        let Ok(content) = std::fs::read_to_string(entry.path()) else {
            continue;
        };
        out.extend(parse_alsa_playback_formats_from_stream_text(&content));
    }
    out.sort();
    out.dedup();
    out
}

fn gst_output_format_from_playback_format(playback_format: &str) -> Option<&'static str> {
    match playback_format.trim().to_ascii_uppercase().as_str() {
        "S16_LE" | "S16LE" => Some("S16LE"),
        "S24_LE" | "S24LE" | "S24_3LE" => Some("S24LE"),
        "S24_32_LE" | "S24_32LE" => Some("S24_32LE"),
        "S32_LE" | "S32LE" => Some("S32LE"),
        _ => None,
    }
}

fn supported_output_formats_from_playback_formats(formats: &[String]) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for fmt in formats {
        let Some(mapped) = gst_output_format_from_playback_format(fmt) else {
            continue;
        };
        if !out.iter().any(|v| v == mapped) {
            out.push(mapped.to_string());
        }
    }
    out
}

fn supported_output_depths_from_formats(formats: &[String]) -> Vec<i32> {
    let mut out: Vec<i32> = Vec::new();
    for fmt in formats {
        let Some(depth) = Engine::parse_depth_from_format(fmt) else {
            continue;
        };
        if !out.iter().any(|v| *v == depth) {
            out.push(depth);
        }
    }
    out.sort_unstable();
    out
}

fn read_alsa_pcm_label(info_path: &Path) -> Option<String> {
    let Ok(content) = std::fs::read_to_string(info_path) else {
        return None;
    };
    for raw in content.lines() {
        let line = raw.trim();
        if let Some(rest) = line.strip_prefix("name:") {
            let label = rest.trim();
            if !label.is_empty() {
                return Some(label.to_string());
            }
        }
    }
    None
}

fn format_alsa_playback_label(
    card_label: &str,
    card_idx: &str,
    pcm_idx: &str,
    pcm_label: Option<&str>,
) -> String {
    match pcm_label.map(|v| v.trim()).filter(|v| !v.is_empty()) {
        Some(label) if !label.eq_ignore_ascii_case(card_label) => {
            format!("{card_label} / {label} (hw:{card_idx},{pcm_idx})")
        }
        _ => format!("{card_label} (PCM {pcm_idx}, Card {card_idx})"),
    }
}

fn list_alsa_cards_from_proc_root(proc_root: &Path) -> Vec<(String, Option<String>)> {
    let card_labels = std::fs::read_to_string(proc_root.join("cards"))
        .ok()
        .map(|v| parse_alsa_card_labels(&v))
        .unwrap_or_default();
    let mut out: Vec<(String, Option<String>)> = Vec::new();
    let Ok(entries) = std::fs::read_dir(proc_root) else {
        return out;
    };
    for entry in entries.flatten() {
        let entry_name = entry.file_name().to_string_lossy().to_string();
        let Some(card_idx) = entry_name
            .strip_prefix("card")
            .filter(|v| !v.is_empty() && v.chars().all(|c| c.is_ascii_digit()))
        else {
            continue;
        };
        let card_idx = card_idx.to_string();
        let card_label = card_labels
            .get(&card_idx)
            .cloned()
            .unwrap_or_else(|| format!("ALSA Card {card_idx}"));
        let Ok(pcms) = std::fs::read_dir(entry.path()) else {
            continue;
        };
        for pcm in pcms.flatten() {
            let pcm_entry = pcm.file_name().to_string_lossy().to_string();
            let Some(pcm_idx) = parse_alsa_playback_pcm_index(&pcm_entry) else {
                continue;
            };
            let pcm_info_path = pcm.path().join("info");
            let pcm_label = read_alsa_pcm_label(&pcm_info_path);
            let friendly =
                format_alsa_playback_label(&card_label, &card_idx, &pcm_idx, pcm_label.as_deref());
            let hw_id = format!("hw:{card_idx},{pcm_idx}");
            out.push((friendly, Some(hw_id)));
        }
        // Cards with no PCM playback subdevices are excluded — they are
        // mid-initialization (e.g. snd-usb-audio re-attaching after USB rawlink
        // release).  The card will appear correctly once the driver finishes probing.
    }
    if out.is_empty() {
        // Last-resort fallback: no PCM devices found anywhere.  Use card names
        // from /proc/asound/cards so the user has something to try.
        for (idx, label) in card_labels {
            let friendly = format!("{label} (Card {idx})");
            let hw_id = format!("hw:{idx},0");
            out.push((friendly, Some(hw_id)));
        }
    }
    out.sort_by_key(|(name, dev)| {
        let hay = format!(
            "{} {}",
            name.to_ascii_uppercase(),
            dev.clone().unwrap_or_default().to_ascii_uppercase()
        );
        (
            if hay.contains("USB") { 0 } else { 1 },
            name.to_ascii_uppercase(),
            dev.clone().unwrap_or_default(),
        )
    });
    out.dedup_by(|a, b| a.1 == b.1);
    out
}

fn list_alsa_cards() -> Vec<(String, Option<String>)> {
    list_alsa_cards_from_proc_root(Path::new("/proc/asound"))
}

/// Enumerate USB audio devices for the USB Rawlink driver device picker.
///
/// Returns `(display_name, Some("usb:VVVV:PPPP"))` or
/// `(display_name, Some("usb:VVVV:PPPP:SERIAL"))` when a serial number is
/// available (to disambiguate two identical DACs on the same machine).
fn list_usb_rawlink_devices() -> Vec<(String, Option<String>)> {
    usb_audio::device::enumerate_usb_audio_devices()
        .into_iter()
        .map(|dev| {
            let id = dev.id();
            // `name` falls back to "VVVV:PPPP" when the product string
            // descriptor is unavailable.  Detect that case and show a
            // more descriptive label.
            let is_fallback_name = dev.name.chars().all(|c| c.is_ascii_hexdigit() || c == ':');
            let base_name = if is_fallback_name {
                format!("USB Audio Device ({})", dev.name)
            } else {
                dev.name.clone()
            };
            let label = if let Some(ref serial) = dev.serial {
                format!("{} [{}]", base_name, serial)
            } else {
                base_name
            };
            (label, Some(id))
        })
        .collect()
}

/// Enumerate PipeWire sinks via the pactl pulse-compat tool.
///
/// device_id is the raw sink name (e.g. `alsa_output.usb-FIIO_KA13-01.analog-stereo`);
/// set_output_tuned converts it to the ALSA pipewire-plugin form
/// `pipewire:PLAYBACK_NODE=<name>` when opening the PCM. When pactl is
/// unavailable or returns nothing, fall back to a single Default entry
/// so the dropdown is never empty.
fn list_pipewire_sinks() -> Vec<(String, Option<String>)> {
    let default_entry = || {
        vec![(
            "Default PipeWire Sink".to_string(),
            Some("pipewire".to_string()),
        )]
    };
    let output = match std::process::Command::new("pactl")
        .arg("list")
        .arg("sinks")
        .output()
    {
        Ok(o) if o.status.success() => o,
        _ => return default_entry(),
    };
    let text = match String::from_utf8(output.stdout) {
        Ok(t) => t,
        Err(_) => return default_entry(),
    };

    let mut sinks: Vec<(String, String)> = Vec::new();
    let mut cur_name: Option<String> = None;
    let mut cur_desc: Option<String> = None;
    let flush = |sinks: &mut Vec<(String, String)>,
                 name: &mut Option<String>,
                 desc: &mut Option<String>| {
        if let Some(n) = name.take() {
            let label = desc
                .take()
                .filter(|d| !d.is_empty())
                .unwrap_or_else(|| n.clone());
            sinks.push((label, n));
        } else {
            *desc = None;
        }
    };
    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("Sink #") {
            flush(&mut sinks, &mut cur_name, &mut cur_desc);
        } else if let Some(rest) = trimmed.strip_prefix("Name:") {
            cur_name = Some(rest.trim().to_string());
        } else if let Some(rest) = trimmed.strip_prefix("Description:") {
            cur_desc = Some(rest.trim().to_string());
        }
    }
    flush(&mut sinks, &mut cur_name, &mut cur_desc);

    if sinks.is_empty() {
        return default_entry();
    }

    let mut out: Vec<(String, Option<String>)> = Vec::with_capacity(sinks.len() + 1);
    out.push((
        "Default PipeWire Sink".to_string(),
        Some("pipewire".to_string()),
    ));
    for (label, name) in sinks {
        out.push((label, Some(name)));
    }
    out
}

fn devices_for_driver(driver: &str) -> Vec<(String, Option<String>)> {
    let d = normalized_driver_label(driver);
    if d == "auto(default)" || d == "auto" {
        return vec![("Default Output".to_string(), None)];
    }
    if driver_is_pipewire(driver) {
        return list_pipewire_sinks();
    }
    if driver_is_alsa_family(driver) {
        return list_alsa_cards();
    }
    if driver_is_usb_rawlink_v2(driver) {
        return list_usb_rawlink_devices();
    }
    Vec::new()
}

fn supported_output_formats_for_driver_device(
    driver: &str,
    device_id: Option<&str>,
) -> Vec<String> {
    let drv = normalized_driver_label(driver);
    let dev = device_id.unwrap_or("").trim();
    if dev.is_empty() {
        return Vec::new();
    }

    let _ = drv;
    let alsa_card_idx = if driver_is_alsa_family(driver) {
        parse_alsa_hw_device_id(dev).map(|(card_idx, _)| card_idx)
    } else {
        None
    };

    let Some(card_idx) = alsa_card_idx else {
        return Vec::new();
    };
    let playback_formats =
        read_alsa_card_playback_formats_from_proc_root(Path::new("/proc/asound"), &card_idx);
    supported_output_formats_from_playback_formats(&playback_formats)
}


fn as_mut_engine<'a>(ptr: *mut Engine) -> Option<&'a mut Engine> {
    if ptr.is_null() {
        None
    } else {
        // SAFETY: Caller owns pointer returned by rac_new.
        Some(unsafe { &mut *ptr })
    }
}

fn as_engine<'a>(ptr: *const Engine) -> Option<&'a Engine> {
    if ptr.is_null() {
        None
    } else {
        // SAFETY: Caller owns pointer returned by rac_new.
        Some(unsafe { &*ptr })
    }
}

#[no_mangle]
pub extern "C" fn rac_new() -> *mut Engine {
    match Engine::new() {
        Ok(e) => Box::into_raw(Box::new(e)),
        Err(_) => ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "C" fn rac_free(ptr: *mut Engine) {
    if ptr.is_null() {
        return;
    }
    // SAFETY: Pointer was allocated by Box::into_raw in rac_new.
    unsafe {
        drop(Box::from_raw(ptr));
    }
}

#[no_mangle]
pub extern "C" fn rac_set_uri(ptr: *mut Engine, uri: *const c_char) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if uri.is_null() {
        engine.set_error("rac_set_uri: null uri");
        return -2;
    }

    // SAFETY: uri is expected to be valid nul-terminated string from caller.
    let c_uri = unsafe { CStr::from_ptr(uri) };
    let s = match c_uri.to_str() {
        Ok(v) => v,
        Err(_) => {
            engine.set_error("rac_set_uri: invalid utf-8");
            engine.emit_event(EVT_ERROR, "rac_set_uri: invalid utf-8");
            return -3;
        }
    };

    engine.uri = s.to_string();
    engine.maybe_load_native_transport_for_uri(s);
    engine.reset_spectrum_timeline();
    engine.last_codec.clear();
    engine.last_bitrate = 0;
    engine.last_rate = 0;
    engine.last_depth = 0;
    engine.source_rate = 0;
    engine.source_depth = 0;
    0
}

#[no_mangle]
pub extern "C" fn rac_play(ptr: *mut Engine) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if engine.uri.is_empty() {
        engine.set_error("rac_play: empty uri");
        engine.emit_event(EVT_ERROR, "rac_play: empty uri");
        return -2;
    }
    match engine.native_transport.play() {
        Ok(()) => {
            engine.emit_event(EVT_STATE, "Playing");
            0
        }
        Err(err) => {
            engine.set_error(format!("native transport play failed: {err}"));
            engine.emit_event(EVT_ERROR, &format!("native transport play failed: {err}"));
            -4
        }
    }
}

#[no_mangle]
pub extern "C" fn rac_pause(ptr: *mut Engine) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    match engine.native_transport.pause() {
        Ok(()) => {
            engine.emit_event(EVT_STATE, "Paused");
            0
        }
        Err(err) => {
            engine.set_error(format!("native transport pause failed: {err}"));
            engine.emit_event(EVT_ERROR, &format!("native transport pause failed: {err}"));
            -4
        }
    }
}

#[no_mangle]
pub extern "C" fn rac_stop(ptr: *mut Engine) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.reset_spectrum_timeline();
    match engine.native_transport.stop() {
        Ok(()) => {
            engine.emit_event(EVT_STATE, "Null");
            0
        }
        Err(err) => {
            engine.set_error(format!("native transport stop failed: {err}"));
            engine.emit_event(EVT_ERROR, &format!("native transport stop failed: {err}"));
            -4
        }
    }
}

#[no_mangle]
pub extern "C" fn rac_release_output(ptr: *mut Engine) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    let had_v2_usb = driver_is_usb_rawlink_v2(&engine.output_driver);
    engine.reset_spectrum_timeline();
    if had_v2_usb {
        let _ = engine.native_transport.stop_and_release();
    } else {
        let _ = engine.native_transport.stop();
    }
    if had_v2_usb {
        std::thread::sleep(std::time::Duration::from_millis(350));
    }
    engine.emit_event(EVT_STATE, "output-released");
    0
}

#[no_mangle]
pub extern "C" fn rac_seek(ptr: *mut Engine, pos_s: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    let clamped = if pos_s.is_finite() {
        pos_s.max(0.0)
    } else {
        0.0
    };

    let ms = (clamped * 1000.0) as u64;
    match engine.native_transport.seek_ms(ms) {
        Ok(()) => {
            engine.reset_spectrum_timeline();
            0
        }
        Err(err) => {
            engine.set_error(&err);
            engine.emit_event(EVT_ERROR, &err);
            -3
        }
    }
}

#[no_mangle]
pub extern "C" fn rac_set_volume(ptr: *mut Engine, vol: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    let v = if vol.is_finite() {
        vol.clamp(0.0, 1.5)
    } else {
        1.0
    };
    engine.native_transport.set_volume(v as f32);
    0
}

// ---------------------------------------------------------------------------
// Hardware volume (USB Feature Unit)
// ---------------------------------------------------------------------------

/// Returns 1 if the current USB sink supports hardware volume, 0 otherwise.
#[no_mangle]
pub extern "C" fn rac_usb_hw_volume_supported(ptr: *const Engine) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return 0;
    };
    if active_usb_hw_volume_supported(engine) { 1 } else { 0 }
}

/// Query the hardware volume range (1/256 dB units).
///
/// On success writes `min`, `max`, `res` and returns 0.
/// Returns -1 if no USB sink or no hardware volume support.
#[no_mangle]
pub extern "C" fn rac_usb_hw_volume_get_range(
    ptr: *const Engine,
    min_out: *mut c_int,
    max_out: *mut c_int,
    res_out: *mut c_int,
) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if min_out.is_null() || max_out.is_null() || res_out.is_null() {
        return -2;
    }
    if let Some((min, max, res)) = active_usb_hw_volume_range(engine) {
        unsafe {
            *min_out = min;
            *max_out = max;
            *res_out = res;
        }
        return 0;
    }
    -1
}

/// Set the hardware volume on ALL channels.  `value_raw` is in 1/256 dB units.
///
/// The value is stored in atomics and applied by the volume worker thread on
/// its next loop iteration (~10 ms latency).
#[no_mangle]
pub extern "C" fn rac_usb_hw_volume_set(ptr: *mut Engine, value_raw: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if active_usb_hw_volume_set_all(engine, value_raw) { 0 } else { -1 }
}

/// Read the last observed hardware volume current value (1/256 dB units).
///
/// Returns channel 0 (master if present, otherwise left).
/// Writes the value to `*value_out`. Returns -3 when the current value is not
/// yet known (for example before the USB sink has opened).
#[no_mangle]
pub extern "C" fn rac_usb_hw_volume_get(ptr: *const Engine, value_out: *mut c_int) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if value_out.is_null() {
        return -2;
    }
    if let Some(v) = active_usb_hw_volume_get_ch(engine, 0) {
        unsafe {
            *value_out = v;
        }
        return 0;
    }
    if active_usb_hw_volume_supported(engine) { -3 } else { -1 }
}

/// Query the number of hardware volume channels and their UAC channel indices.
///
/// Writes up to `max_count` channel IDs into `channels_out` and the actual
/// count into `count_out`.  Returns 0 on success, -1 if no USB sink.
/// Channel semantics: 0 = master, 1 = left, 2 = right (UAC standard).
#[no_mangle]
pub extern "C" fn rac_usb_hw_volume_channels(
    ptr: *const Engine,
    channels_out: *mut u8,
    max_count: c_int,
    count_out: *mut c_int,
) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    let Some(chs) = active_usb_hw_volume_channels(engine) else { return -1; };
    if !count_out.is_null() {
        unsafe { *count_out = chs.len() as c_int; }
    }
    if !channels_out.is_null() && max_count > 0 {
        let n = std::cmp::min(chs.len(), max_count as usize);
        unsafe {
            std::ptr::copy_nonoverlapping(chs.as_ptr(), channels_out, n);
        }
    }
    0
}

/// Set hardware volume for a single channel by index (0-based into the
/// channel list returned by `rac_usb_hw_volume_channels`).
/// `value_raw` is in 1/256 dB units.
#[no_mangle]
pub extern "C" fn rac_usb_hw_volume_set_ch(
    ptr: *mut Engine,
    channel_index: c_int,
    value_raw: c_int,
) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    let idx = channel_index as usize;
    let Some(chs) = active_usb_hw_volume_channels(engine) else { return -1; };
    if idx >= chs.len() || idx >= 3 {
        return -2;
    }
    if active_usb_hw_volume_set_ch(engine, idx, value_raw) { 0 } else { -2 }
}

/// Read the last observed hardware volume for a single channel by index.
/// `channel_index` is 0-based into the channel list.
/// Returns -3 when the value is not yet known.
#[no_mangle]
pub extern "C" fn rac_usb_hw_volume_get_ch(
    ptr: *const Engine,
    channel_index: c_int,
    value_out: *mut c_int,
) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    let idx = channel_index as usize;
    if value_out.is_null() {
        return -2;
    }
    let Some(chs) = active_usb_hw_volume_channels(engine) else { return -1; };
    if idx >= chs.len() || idx >= 3 {
        return -2;
    }
    if let Some(v) = active_usb_hw_volume_get_ch(engine, idx) {
        unsafe {
            *value_out = v;
        }
        return 0;
    }
    -3
}

#[no_mangle]
pub extern "C" fn rac_get_position(ptr: *const Engine, pos_out: *mut c_double) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if pos_out.is_null() {
        return -2;
    }

    // After EOS but before next track loads, return 0 so the UI doesn't
    // show stale position from the finished track.
    let pos = if engine.native_eos_emitted {
        0.0
    } else {
        let snap = engine.native_transport.snapshot();
        let seek_offset = snap.seek_offset_s;
        // Use the USB write-head for transport progress so the UI keeps
        // moving even while the stricter play-head estimate is waiting for
        // the in-flight ISO ring to drain. ALSA mmap path doesn't populate
        // runtime info, so it falls through to the decoded-frame-count branch.
        if let Some(runtime) = engine.native_transport.runtime_info() {
            let write_pos = runtime.feed.write_elapsed_s().unwrap_or(0.0);
            if write_pos > 0.0 || snap.state != native_transport::NativeTransportState::Playing {
                seek_offset + write_pos
            } else {
                let rate = snap
                    .stream_spec
                    .as_ref()
                    .map(|s| s.sample_rate as f64)
                    .unwrap_or(0.0);
                if rate > 0.0 && snap.decoded_frame_count > 0 {
                    seek_offset + snap.decoded_frame_count as f64 / rate
                } else {
                    seek_offset
                }
            }
        } else {
            let rate = snap
                .stream_spec
                .as_ref()
                .map(|s| s.sample_rate as f64)
                .unwrap_or(0.0);
            if rate > 0.0 {
                seek_offset + snap.decoded_frame_count as f64 / rate
            } else {
                seek_offset
            }
        }
    };

    // SAFETY: pos_out is a valid output pointer from caller.
    unsafe {
        *pos_out = pos;
    }
    0
}

#[no_mangle]
pub extern "C" fn rac_get_duration(ptr: *const Engine, dur_out: *mut c_double) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if dur_out.is_null() {
        return -2;
    }

    let dur = if engine.native_eos_emitted {
        0.0
    } else {
        engine.native_transport.snapshot().duration_s.unwrap_or(0.0)
    };

    // SAFETY: dur_out is a valid output pointer from caller.
    unsafe {
        *dur_out = dur;
    }
    0
}

fn probe_latency(engine: &Engine) -> (f64, &'static str) {
    // USB rawlink V2: estimate from the ISO transfer ring depth. Pre-anchor
    // (first samples not yet on the wire) and post-anchor share this estimate.
    if active_usb_runtime_info(engine).is_some() {
        let ring_ms =
            (usb_audio::transfer::N_TRANSFERS * usb_audio::transfer::N_PACKETS_TARGET_MS) as f64;
        return (ring_ms / 1000.0, "usb-rawlink-ring-fallback");
    }
    // ALSA family: native_transport does not surface its mmap buffer depth
    // here yet; report 0 so callers know latency is unknown.
    (0.0, "none")
}

#[no_mangle]
pub extern "C" fn rac_get_latency(ptr: *const Engine, lat_out: *mut c_double) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if lat_out.is_null() {
        return -2;
    }
    let (latency_s, _src) = probe_latency(engine);

    unsafe {
        *lat_out = if latency_s.is_finite() && latency_s > 0.0 {
            latency_s
        } else {
            0.0
        };
    }
    0
}

#[no_mangle]
pub extern "C" fn rac_get_latency_probe_json(ptr: *const Engine) -> *mut c_char {
    let Some(engine) = as_engine(ptr) else {
        return ptr::null_mut();
    };
    let (latency_s, src) = probe_latency(engine);
    let s = format!(
        "{{\"latency_s\":{},\"source\":\"{}\"}}",
        if latency_s.is_finite() && latency_s > 0.0 {
            latency_s
        } else {
            0.0
        },
        src
    );
    match CString::new(s) {
        Ok(c) => c.into_raw(),
        Err(_) => ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "C" fn rac_is_playing(ptr: *const Engine) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return 0;
    };
    if engine.native_transport.snapshot().state == native_transport::NativeTransportState::Playing
    {
        1
    } else {
        0
    }
}

#[no_mangle]
pub extern "C" fn rac_get_last_error(ptr: *const Engine) -> *mut c_char {
    let Some(engine) = as_engine(ptr) else {
        return ptr::null_mut();
    };
    let msg = engine.last_error.as_deref().unwrap_or("");
    match CString::new(msg) {
        Ok(s) => s.into_raw(),
        Err(_) => ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "C" fn rac_free_string(s: *mut c_char) {
    if s.is_null() {
        return;
    }
    // SAFETY: s was allocated by CString::into_raw in this library.
    unsafe {
        let _ = CString::from_raw(s);
    }
}

/// Enumerate USB Audio Class devices visible to the current user.
///
/// Returns a JSON array (UTF-8, null-terminated).  Caller must free the
/// returned pointer with `rac_free_string`.  Returns `null` on allocation
/// failure (extremely unlikely).
///
/// Each element:
/// ```json
/// {
///   "id":           "usb:1234:5678",
///   "name":         "FiiO DAC",
///   "serial":       "A0B1C2",      // or null
///   "vendor_id":    0x1234,
///   "product_id":   0x5678,
///   "bus":          1,
///   "address":      3,
///   "uac_version":  2,
///   "ctrl_iface":   0,
///   "stream_iface": 1,
///   "alts": [
///     {
///       "alt": 1,
///       "format": "PCM",
///       "bit_depth": 32,
///       "channels": 2,
///       "sample_rates": [44100, 48000, 88200, 96000, 176400, 192000],
///       "out_ep": 1,
///       "feedback_ep": 129,    // or null
///       "max_packet": 392
///     }
///   ]
/// }
/// ```
#[no_mangle]
pub extern "C" fn rac_list_usb_audio_devices() -> *mut c_char {
    use usb_audio::descriptor::UacFormat;
    use usb_audio::descriptor::UacVersion;
    use usb_audio::device::enumerate_usb_audio_devices;

    let devices = enumerate_usb_audio_devices();
    let mut json = String::from("[");

    for (i, dev) in devices.iter().enumerate() {
        if i > 0 {
            json.push(',');
        }

        // Serialize alts array
        let alts_json: String = dev
            .alts
            .iter()
            .enumerate()
            .map(|(j, alt)| {
                let sep = if j > 0 { "," } else { "" };
                let fmt = match alt.format {
                    UacFormat::Pcm => "PCM",
                    UacFormat::Pcm8 => "PCM8",
                    UacFormat::Float32 => "FLOAT32",
                    UacFormat::Unknown => "UNKNOWN",
                };
                let rates: String = alt
                    .sample_rates
                    .iter()
                    .map(|r| r.to_string())
                    .collect::<Vec<_>>()
                    .join(",");
                let fb = alt
                    .feedback_ep
                    .map(|e| e.to_string())
                    .unwrap_or_else(|| "null".to_string());
                format!(
                    r#"{sep}{{"alt":{alt},"format":"{fmt}","bit_depth":{bd},"channels":{ch},"sample_rates":[{rates}],"out_ep":{out},"feedback_ep":{fb},"max_packet":{mp}}}"#,
                    sep = sep,
                    alt = alt.alt_setting,
                    fmt = fmt,
                    bd = alt.bit_depth,
                    ch = alt.channels,
                    rates = rates,
                    out = alt.out_ep,
                    fb = fb,
                    mp = alt.max_packet,
                )
            })
            .collect();

        let serial_json = dev
            .serial
            .as_deref()
            .map(|s| format!("\"{}\"", s.replace('"', "\\\"")))
            .unwrap_or_else(|| "null".to_string());

        let ver = match dev.uac_version {
            UacVersion::V1 => 1,
            UacVersion::V2 => 2,
        };

        json.push_str(&format!(
            concat!(
                r#"{{"id":"{id}","name":"{name}","serial":{serial},"#,
                r#""vendor_id":{vid},"product_id":{pid},"bus":{bus},"address":{addr},"#,
                r#""uac_version":{ver},"ctrl_iface":{ci},"stream_iface":{si},"alts":[{alts}]}}"#,
            ),
            id = dev.id(),
            name = dev.name.replace('"', "\\\""),
            serial = serial_json,
            vid = dev.vendor_id,
            pid = dev.product_id,
            bus = dev.bus,
            addr = dev.address,
            ver = ver,
            ci = dev.ctrl_iface,
            si = dev.stream_iface,
            alts = alts_json,
        ));
    }

    json.push(']');
    match CString::new(json) {
        Ok(c) => c.into_raw(),
        Err(_) => ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "C" fn rac_set_event_callback(
    ptr: *mut Engine,
    cb: Option<EventCallback>,
    user_data: *mut c_void,
) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.event_cb = cb;
    engine.event_user_data = user_data;
    0
}

#[no_mangle]
pub extern "C" fn rac_pump_events(ptr: *mut Engine) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.pump_events()
}

#[no_mangle]
pub extern "C" fn rac_set_output(
    ptr: *mut Engine,
    driver: *const c_char,
    device: *const c_char,
) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if driver.is_null() {
        engine.set_error("rac_set_output: null driver");
        engine.emit_event(EVT_ERROR, "rac_set_output: null driver");
        return -2;
    }

    // SAFETY: caller provides nul-terminated strings.
    let drv = unsafe { CStr::from_ptr(driver) };
    let drv_str = match drv.to_str() {
        Ok(s) => s,
        Err(_) => {
            engine.set_error("rac_set_output: invalid driver utf-8");
            engine.emit_event(EVT_ERROR, "rac_set_output: invalid driver utf-8");
            return -3;
        }
    };

    let dev_opt = if device.is_null() {
        None
    } else {
        // SAFETY: caller provides nul-terminated strings.
        let d = unsafe { CStr::from_ptr(device) };
        d.to_str().ok()
    };

    engine.set_output(drv_str, dev_opt)
}

#[no_mangle]
pub extern "C" fn rac_set_output_tuned(
    ptr: *mut Engine,
    driver: *const c_char,
    device: *const c_char,
    buffer_us: c_int,
    latency_us: c_int,
    exclusive: c_int,
) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if driver.is_null() {
        engine.set_error("rac_set_output_tuned: null driver");
        engine.emit_event(EVT_ERROR, "rac_set_output_tuned: null driver");
        return -2;
    }

    let drv = unsafe { CStr::from_ptr(driver) };
    let drv_str = match drv.to_str() {
        Ok(s) => s,
        Err(_) => {
            engine.set_error("rac_set_output_tuned: invalid driver utf-8");
            engine.emit_event(EVT_ERROR, "rac_set_output_tuned: invalid driver utf-8");
            return -3;
        }
    };

    let dev_opt = if device.is_null() {
        None
    } else {
        let d = unsafe { CStr::from_ptr(device) };
        d.to_str().ok()
    };

    engine.set_output_tuned(drv_str, dev_opt, buffer_us, latency_us, exclusive != 0)
}

#[no_mangle]
pub extern "C" fn rac_set_mmap_realtime_priority(ptr: *mut Engine, priority: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_mmap_realtime_priority(priority)
}

/// USB rawlink clock mode constants for [`rac_set_usb_clock_mode`].
pub const RAC_USB_CLOCK_PUSH: c_int = 0;
pub const RAC_USB_CLOCK_PULL: c_int = 1;

/// Set the USB rawlink clock alignment mode.
///
/// - `RAC_USB_CLOCK_PUSH` (0): push clock — `anchor_ns + frames/rate`.
///   Zero-jitter integer arithmetic; the clock tracks the write position.
/// - `RAC_USB_CLOCK_PULL` (1): pull clock (Level 3) — ISO completion
///   regression + buffer-depth compensation.  Reports the estimated *play*
///   position.  Requires ~256 ms of ISO callbacks to warm up; falls back to
///   push during warm-up.
///
/// Takes effect immediately for a live USB session and is also re-applied on
/// the next lazy device open (track start or rate change).
/// Returns 0 on success, -1 if `ptr` is null, -2 if `mode` is unknown.
#[no_mangle]
pub extern "C" fn rac_set_usb_clock_mode(ptr: *mut Engine, mode: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    let _clock_mode = match mode {
        RAC_USB_CLOCK_PUSH => alsa_clock::ClockMode::Push,
        RAC_USB_CLOCK_PULL => alsa_clock::ClockMode::Pull,
        _ => return -2,
    };
    engine.usb_clock_mode = mode as u8;
    0
}

#[no_mangle]
pub extern "C" fn rac_set_preferred_output_format(
    ptr: *mut Engine,
    format_name: *const c_char,
) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if format_name.is_null() {
        engine.preferred_output_format.clear();
        return 0;
    }
    let fmt = unsafe { CStr::from_ptr(format_name) };
    match fmt.to_str() {
        Ok(s) => {
            engine.preferred_output_format = s.trim().to_ascii_uppercase();
            0
        }
        Err(_) => {
            engine.set_error("rac_set_preferred_output_format: invalid utf-8");
            engine.emit_event(EVT_ERROR, "rac_set_preferred_output_format: invalid utf-8");
            -2
        }
    }
}

#[no_mangle]
pub extern "C" fn rac_set_peq_band_gain(
    ptr: *mut Engine,
    band_index: c_int,
    gain_db: c_double,
) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if !gain_db.is_finite() {
        engine.set_error("rac_set_peq_band_gain: non-finite value");
        engine.emit_event(EVT_ERROR, "rac_set_peq_band_gain: non-finite value");
        return -2;
    }
    if band_index < 0 || (band_index as usize) >= PEQ_BAND_COUNT {
        engine.set_error("rac_set_peq_band_gain: band index out of range");
        engine.emit_event(EVT_ERROR, "rac_set_peq_band_gain: band index out of range");
        return -3;
    }
    engine.set_peq_band_gain(band_index as usize, gain_db)
}

#[no_mangle]
pub extern "C" fn rac_reset_peq(ptr: *mut Engine) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.reset_peq()
}

#[no_mangle]
pub extern "C" fn rac_set_dsp_enabled(ptr: *mut Engine, enabled: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_dsp_master_enabled(enabled != 0)
}

#[no_mangle]
pub extern "C" fn rac_set_dsp_order(ptr: *mut Engine, order_csv: *const c_char) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if order_csv.is_null() {
        engine.set_error("rac_set_dsp_order: null order");
        engine.emit_event(EVT_ERROR, "rac_set_dsp_order: null order");
        return -2;
    }
    match unsafe { CStr::from_ptr(order_csv) }.to_str() {
        Ok(value) => engine.set_dsp_order(value),
        Err(_) => {
            engine.set_error("rac_set_dsp_order: invalid utf-8");
            engine.emit_event(EVT_ERROR, "rac_set_dsp_order: invalid utf-8");
            -3
        }
    }
}

#[no_mangle]
pub extern "C" fn rac_set_peq_enabled(ptr: *mut Engine, enabled: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_peq_enabled(enabled != 0)
}

#[no_mangle]
pub extern "C" fn rac_set_convolver_enabled(ptr: *mut Engine, enabled: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_convolver_enabled(enabled != 0)
}

#[no_mangle]
pub extern "C" fn rac_set_convolver_mix(ptr: *mut Engine, mix: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if !mix.is_finite() {
        engine.set_error("rac_set_convolver_mix: non-finite value");
        engine.emit_event(EVT_ERROR, "rac_set_convolver_mix: non-finite value");
        return -2;
    }
    engine.set_convolver_mix(mix)
}

#[no_mangle]
pub extern "C" fn rac_set_convolver_pre_delay(ptr: *mut Engine, ms: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if !ms.is_finite() {
        engine.set_error("rac_set_convolver_pre_delay: non-finite value");
        engine.emit_event(EVT_ERROR, "rac_set_convolver_pre_delay: non-finite value");
        return -2;
    }
    engine.set_convolver_pre_delay(ms)
}

#[no_mangle]
pub extern "C" fn rac_set_limiter_enabled(ptr: *mut Engine, enabled: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_limiter_enabled(enabled != 0)
}

#[no_mangle]
pub extern "C" fn rac_set_limiter_threshold(ptr: *mut Engine, threshold: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if !threshold.is_finite() {
        engine.set_error("rac_set_limiter_threshold: non-finite value");
        engine.emit_event(EVT_ERROR, "rac_set_limiter_threshold: non-finite value");
        return -2;
    }
    engine.set_limiter_threshold(threshold)
}

#[no_mangle]
pub extern "C" fn rac_set_limiter_ratio(ptr: *mut Engine, ratio: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if !ratio.is_finite() {
        engine.set_error("rac_set_limiter_ratio: non-finite value");
        engine.emit_event(EVT_ERROR, "rac_set_limiter_ratio: non-finite value");
        return -2;
    }
    engine.set_limiter_ratio(ratio)
}

#[no_mangle]
pub extern "C" fn rac_set_resampler_enabled(ptr: *mut Engine, enabled: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_resampler_enabled(enabled != 0)
}

#[no_mangle]
pub extern "C" fn rac_set_resampler_target_rate(ptr: *mut Engine, rate: c_uint) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_resampler_target_rate(rate)
}

#[no_mangle]
pub extern "C" fn rac_set_resampler_quality(ptr: *mut Engine, quality: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_resampler_quality(quality)
}

#[no_mangle]
pub extern "C" fn rac_set_tape_enabled(ptr: *mut Engine, enabled: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_tape_enabled(enabled != 0)
}

#[no_mangle]
pub extern "C" fn rac_set_tape_drive(ptr: *mut Engine, drive: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_tape_drive(drive)
}

#[no_mangle]
pub extern "C" fn rac_set_tape_tone(ptr: *mut Engine, tone: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_tape_tone(tone)
}

#[no_mangle]
pub extern "C" fn rac_set_tape_warmth(ptr: *mut Engine, warmth: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_tape_warmth(warmth)
}

#[no_mangle]
pub extern "C" fn rac_set_tube_enabled(ptr: *mut Engine, enabled: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_tube_enabled(enabled != 0)
}

#[no_mangle]
pub extern "C" fn rac_set_tube_drive(ptr: *mut Engine, drive: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_tube_drive(drive)
}

#[no_mangle]
pub extern "C" fn rac_set_tube_bias(ptr: *mut Engine, bias: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_tube_bias(bias)
}

#[no_mangle]
pub extern "C" fn rac_set_tube_sag(ptr: *mut Engine, sag: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_tube_sag(sag)
}

#[no_mangle]
pub extern "C" fn rac_set_tube_air(ptr: *mut Engine, air: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_tube_air(air)
}

#[no_mangle]
pub extern "C" fn rac_set_widener_enabled(ptr: *mut Engine, enabled: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_widener_enabled(enabled != 0)
}

#[no_mangle]
pub extern "C" fn rac_set_widener_width(ptr: *mut Engine, width: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_widener_width(width)
}

#[no_mangle]
pub extern "C" fn rac_set_widener_bass_mono_freq(ptr: *mut Engine, freq: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_widener_bass_mono_freq(freq)
}

#[no_mangle]
pub extern "C" fn rac_set_widener_bass_mono_amount(ptr: *mut Engine, amount: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_widener_bass_mono_amount(amount)
}

#[no_mangle]
pub extern "C" fn rac_load_convolver_ir(ptr: *mut Engine, path: *const c_char) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if path.is_null() {
        engine.set_error("rac_load_convolver_ir: null path");
        engine.emit_event(EVT_ERROR, "rac_load_convolver_ir: null path");
        return -2;
    }
    match unsafe { CStr::from_ptr(path) }.to_str() {
        Ok(value) => engine.load_convolver_ir(value),
        Err(_) => {
            engine.set_error("rac_load_convolver_ir: invalid utf-8");
            engine.emit_event(EVT_ERROR, "rac_load_convolver_ir: invalid utf-8");
            -3
        }
    }
}

#[no_mangle]
pub extern "C" fn rac_clear_convolver_ir(ptr: *mut Engine) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.clear_convolver_ir()
}

#[no_mangle]
pub extern "C" fn rac_set_speed(ptr: *mut Engine, speed: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if !speed.is_finite() {
        engine.set_error("rac_set_speed: non-finite value");
        engine.emit_event(EVT_ERROR, "rac_set_speed: non-finite value");
        return -2;
    }
    let _ = speed; // API kept for compatibility; disabled in HiFi mode.
    engine.emit_event(EVT_STATE, "playback-rate request ignored (hifi-locked)");
    0
}

#[no_mangle]
pub extern "C" fn rac_set_pitch(ptr: *mut Engine, semitones: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if !semitones.is_finite() {
        engine.set_error("rac_set_pitch: non-finite value");
        engine.emit_event(EVT_ERROR, "rac_set_pitch: non-finite value");
        return -2;
    }
    engine.pitch_semitones = 0.0;
    let _ = semitones; // API kept for compatibility; disabled in HiFi mode.
    engine.emit_event(EVT_STATE, "pitch request ignored (hifi-locked)");
    0
}

#[no_mangle]
pub extern "C" fn rac_list_devices(ptr: *mut Engine, driver: *const c_char) -> *mut c_char {
    let Some(engine) = as_mut_engine(ptr) else {
        return ptr::null_mut();
    };
    if driver.is_null() {
        engine.set_error("rac_list_devices: null driver");
        return ptr::null_mut();
    }
    // SAFETY: caller provides nul-terminated string.
    let drv_c = unsafe { CStr::from_ptr(driver) };
    let drv_str = match drv_c.to_str() {
        Ok(s) => s,
        Err(_) => {
            engine.set_error("rac_list_devices: invalid driver utf-8");
            return ptr::null_mut();
        }
    };

    let devices = devices_for_driver(drv_str);
    let mut s = String::from("[");
    for (i, (name, dev_id)) in devices.into_iter().enumerate() {
        if i > 0 {
            s.push(',');
        }
        let supported_formats =
            supported_output_formats_for_driver_device(drv_str, dev_id.as_deref());
        let supported_bit_depths = supported_output_depths_from_formats(&supported_formats);
        s.push_str("{\"name\":\"");
        s.push_str(&json_escape(&name));
        s.push_str("\",\"device_id\":");
        match dev_id {
            Some(v) => {
                s.push('"');
                s.push_str(&json_escape(&v));
                s.push('"');
            }
            None => s.push_str("null"),
        }
        s.push_str(",\"supported_formats\":[");
        for (fmt_idx, fmt) in supported_formats.iter().enumerate() {
            if fmt_idx > 0 {
                s.push(',');
            }
            s.push('"');
            s.push_str(&json_escape(fmt));
            s.push('"');
        }
        s.push(']');
        s.push_str(",\"supported_bit_depths\":[");
        for (depth_idx, depth) in supported_bit_depths.iter().enumerate() {
            if depth_idx > 0 {
                s.push(',');
            }
            s.push_str(&depth.to_string());
        }
        s.push(']');
        s.push('}');
    }
    s.push(']');

    match CString::new(s) {
        Ok(c) => c.into_raw(),
        Err(_) => ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "C" fn rac_get_runtime_snapshot(ptr: *const Engine) -> *mut c_char {
    let Some(engine) = as_engine(ptr) else {
        return ptr::null_mut();
    };
    let (session_rate, session_depth) = engine.query_output_format();
    let (hw_rate, hw_depth) = read_running_alsa_hw_params();
    let mut s = String::from("{");
    s.push_str("\"output\":{");
    s.push_str(&format!(
        "\"session_rate\":{},\"session_depth\":{},\"hardware_rate\":{},\"hardware_depth\":{}",
        session_rate.unwrap_or(0),
        session_depth.unwrap_or(0),
        hw_rate.unwrap_or(0),
        hw_depth.unwrap_or(0),
    ));
    s.push_str("},");
    s.push_str("\"mmap_thread\":null,");

    // USB rawlink runtime info (for signal-path display).
    s.push_str("\"usb_rawlink\":");
    if let Some(info) = active_usb_runtime_info(engine) {
        let usb_rate = info.rate;
        let usb_depth = info.bit_depth as u32;
        // ISO ring latency = N_TRANSFERS × N_PACKETS_TARGET_MS.
        // This is the physical write-ahead regardless of clock mode
        // (buffer_depth_ns is 0 in Pull mode for clock math, not latency).
        let usb_latency_ms =
            (usb_audio::transfer::N_TRANSFERS * usb_audio::transfer::N_PACKETS_TARGET_MS) as f64;
        s.push_str(&format!(
            "{{\"rate\":{},\"depth\":{},\"latency_ms\":{:.1},\"device_name\":\"{}\"}}",
            usb_rate,
            usb_depth,
            usb_latency_ms,
            json_escape(&info.device_name),
        ));
    } else {
        s.push_str("null");
    }
    s.push(',');

    s.push_str("\"source\":{");
    let source_rate = if engine.source_rate > 0 {
        engine.source_rate
    } else if engine.last_rate > 0 {
        engine.last_rate
    } else if session_rate.unwrap_or(0) > 0 {
        session_rate.unwrap_or(0)
    } else {
        0
    };
    let source_depth = if engine.source_depth > 0 {
        engine.source_depth
    } else if engine.last_depth > 0 {
        engine.last_depth
    } else if session_depth.unwrap_or(0) > 0 {
        session_depth.unwrap_or(0)
    } else {
        0
    };
    s.push_str("\"codec\":\"");
    s.push_str(&json_escape(&engine.last_codec));
    s.push_str("\",");
    s.push_str(&format!(
        "\"bitrate\":{},\"rate\":{},\"depth\":{}",
        engine.last_bitrate.max(0),
        source_rate.max(0),
        source_depth.max(0),
    ));
    s.push_str("}}");

    match CString::new(s) {
        Ok(c) => c.into_raw(),
        Err(_) => ptr::null_mut(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::time::{SystemTime, UNIX_EPOCH};

    struct TempProcRoot {
        path: PathBuf,
    }

    impl TempProcRoot {
        fn new(name: &str) -> Self {
            let unique = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0);
            let path = std::env::temp_dir().join(format!(
                "rust_audio_core_{name}_{}_{}",
                std::process::id(),
                unique
            ));
            fs::create_dir_all(&path).expect("create temp proc root");
            Self { path }
        }

        fn path(&self) -> &Path {
            &self.path
        }

        fn write(&self, rel: &str, content: &str) {
            let path = self.path.join(rel);
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent).expect("create temp proc parent");
            }
            fs::write(path, content).expect("write temp proc file");
        }
    }

    impl Drop for TempProcRoot {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.path);
        }
    }


    #[test]
    fn alsa_mmap_recover_from_xrun_requires_restart() {
        let mut ctx = AlsaCtx {
            pcm: AlsaHandle(std::ptr::null_mut()),
            period_frames: 480,
            buffer_frames: 1920,
            frame_bytes: 8,
            rate: 48_000,
            primed_frames: 1440,
            started: true,
            start_fail_count: 2,
            format_label: "S32_LE",
            anchored: false,
            feed: None,
            access_mode: crate::alsa_pcm::AlsaAccessMode::Mmap,
        };

        assert!(AlsaCtx::recover_requires_restart(-libc::EPIPE));
        ctx.reset_start_sequence();

        assert_eq!(ctx.primed_frames, 0);
        assert!(!ctx.started);
        assert_eq!(ctx.start_fail_count, 0);
    }

    #[test]
    fn alsa_mmap_recover_from_interrupt_keeps_running_state() {
        assert!(!AlsaCtx::recover_requires_restart(-libc::EINTR));
    }

    #[test]
    fn peq_config_enables_processing_when_any_band_moves() {
        let mut config = dsp::PeqConfig::default();
        assert!(config.is_flat());
        assert!(!config.is_active());

        let gain = config.set_band_gain(3, 4.5).expect("set band gain");

        assert_eq!(gain, 4.5);
        assert!(!config.is_flat());
        assert!(config.is_active());

        config.reset();
        assert!(config.is_flat());
        assert!(!config.is_active());
    }

    #[test]
    fn dsp_graph_config_requires_master_and_active_node() {
        let mut config = DspGraphConfig::default();
        assert!(!config.has_active_processing());

        let _ = config.peq.set_band_gain(0, 3.0);
        assert!(config.has_active_processing());

        config.enabled = false;
        assert!(!config.has_active_processing());
        assert!(!config.effective_peq_config().enabled);

        config.enabled = true;
        assert!(config.has_active_processing());
        assert!(config.effective_peq_config().enabled);
    }

    #[test]
    fn alsa_enum_uses_real_playback_pcm_indices() {
        let proc_root = TempProcRoot::new("alsa_pcm_enum");
        proc_root.write("cards", " 2 [USB            ]: USB-Audio - Fancy DAC\n");
        proc_root.write(
            "card2/pcm7p/info",
            "card: 2\ndevice: 7\nname: USB Audio Output\nsubdevices_count: 1\n",
        );

        let devices = list_alsa_cards_from_proc_root(proc_root.path());

        assert_eq!(
            devices,
            vec![(
                "Fancy DAC / USB Audio Output (hw:2,7)".to_string(),
                Some("hw:2,7".to_string()),
            )]
        );
    }

    #[test]
    fn alsa_enum_falls_back_to_card_zero_when_pcm_dirs_missing() {
        let proc_root = TempProcRoot::new("alsa_card_fallback");
        proc_root.write("cards", " 1 [PCH            ]: HDA-Intel - HDA Intel PCH\n");
        fs::create_dir_all(proc_root.path().join("card1")).expect("create fallback card dir");

        let devices = list_alsa_cards_from_proc_root(proc_root.path());

        assert_eq!(
            devices,
            vec![(
                "HDA Intel PCH (Card 1)".to_string(),
                Some("hw:1,0".to_string()),
            )]
        );
    }

    #[test]
    fn alsa_stream_parser_reads_playback_formats_only() {
        let text = r#"MUSILAND Monitor 09 at usb-0000:00:14.0-2, high speed : USB Audio

Playback:
  Status: Stop
  Interface 1
    Altset 1
    Format: S32_LE
    Channels: 2

Capture:
  Status: Stop
  Interface 2
    Altset 1
    Format: S16_LE
"#;

        let formats = parse_alsa_playback_formats_from_stream_text(text);

        assert_eq!(formats, vec!["S32_LE".to_string()]);
    }

    #[test]
    fn supported_output_formats_map_known_alsa_formats() {
        let formats = supported_output_formats_from_playback_formats(&vec![
            "S16_LE".to_string(),
            "S24_3LE".to_string(),
            "S24_32_LE".to_string(),
            "S32_LE".to_string(),
        ]);

        assert_eq!(
            formats,
            vec![
                "S16LE".to_string(),
                "S24LE".to_string(),
                "S24_32LE".to_string(),
                "S32LE".to_string(),
            ]
        );
    }

    #[test]
    fn supported_output_depths_dedupe_container_formats() {
        let depths = supported_output_depths_from_formats(&vec![
            "S24LE".to_string(),
            "S24_32LE".to_string(),
            "S16LE".to_string(),
            "S32LE".to_string(),
        ]);

        assert_eq!(depths, vec![16, 24, 32]);
    }

}
