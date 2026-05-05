use super::format_util::{
    bits_per_sample_to_pcm_format, bytes_per_sample, pcm_format_from_gst_format,
    pcm_format_to_bit_depth, sample_to_f32, write_f32_as, write_i24_le,
};
use super::processor::{
    LufsPcmProcessor, PcmProcessorChain, PcmSampleFormat, PcmSlab, PcmStreamSpec, SharedLufsValues,
    SharedVolume, SpectrumFrame, SpectrumPcmProcessor, VolumePcmProcessor,
};
use super::source::{
    inspect_mpd_manifest, MpdManifestInfo, NativeDecoderKind, NativeTransportSource,
    NativeTransportSourceKind,
};
use super::output::NativeOutputTarget;
use crate::alsa_clock::{AlsaHwClockFeed, ClockMode};
use crate::usb_audio::{
    self, OpenUsbDevice, QueueMode, UacAltProfile, UsbAudioSink, UsbRawSinkConfig,
};
use crossbeam_channel::{unbounded, Receiver, Sender};
use std::collections::{HashSet, VecDeque};
use std::fs;
use std::io::{Cursor, Read, Seek, SeekFrom};
use std::sync::atomic::{AtomicBool, AtomicI32, AtomicU32, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread;
use std::time::Instant;
use symphonia::core::audio::{AudioBuffer, AudioBufferRef, Signal};
use symphonia::core::codecs::{
    CodecType, DecoderOptions, CODEC_TYPE_AAC, CODEC_TYPE_ALAC, CODEC_TYPE_FLAC, CODEC_TYPE_NULL,
};
use symphonia::core::conv::IntoSample;
use symphonia::core::errors::Error as SymphoniaError;
use symphonia::core::formats::{FormatOptions, SeekMode, SeekTo};
use symphonia::core::io::{
    MediaSource, MediaSourceStream, MediaSourceStreamOptions, ReadOnlySource,
};
use symphonia::core::meta::MetadataOptions;
use symphonia::core::probe::Hint;
use symphonia::core::sample::{i24, Sample};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NativeTransportState {
    Idle,
    Loading,
    Ready,
    Playing,
    Paused,
    Stopped,
    Error,
    Shutdown,
}

#[derive(Debug, Clone, PartialEq)]
pub struct NativeTransportLoadRequest {
    pub source: NativeTransportSource,
    pub target_driver: String,
    pub bit_perfect: bool,
    pub output_target: Option<NativeOutputTarget>,
    pub dsp_config: Option<crate::dsp::DspGraphConfig>,
}

#[derive(Debug)]
pub enum NativeTransportCommand {
    /// Claim the USB device early to prevent PipeWire from grabbing it.
    /// The device stays claimed until Stop, ReleaseDevice, or Shutdown.
    ClaimDevice {
        device_id: String,
        bit_depth: u8,
        alt_profile: UacAltProfile,
    },
    /// Release a previously claimed device.
    ReleaseDevice,
    /// Stop playback AND release the USB device in one atomic step.
    /// The oneshot sender signals completion so the caller can wait.
    StopAndRelease(std::sync::mpsc::SyncSender<()>),
    Load(NativeTransportLoadRequest),
    Play,
    Pause,
    Stop,
    SeekMs(u64),
    UpdateDspConfig(crate::dsp::DspGraphConfig),
    Shutdown,
}

#[derive(Debug, Clone, PartialEq)]
pub struct NativeTransportSnapshot {
    pub state: NativeTransportState,
    pub generation: u64,
    pub current_track_id: Option<String>,
    pub current_title: Option<String>,
    pub source_kind: Option<NativeTransportSourceKind>,
    pub decoder: Option<NativeDecoderKind>,
    pub bit_perfect: bool,
    pub target_driver: Option<String>,
    pub processor_chain_len: usize,
    pub supports_seek: bool,
    pub duration_s: Option<f64>,
    pub source_locator: Option<String>,
    pub output_configured: bool,
    pub stream_spec: Option<PcmStreamSpec>,
    pub bits_per_sample: Option<u32>,
    pub first_packet_frames: Option<usize>,
    pub decoded_slab_count: u64,
    pub decoded_frame_count: u64,
    pub decoded_byte_count: u64,
    pub decode_worker_running: bool,
    pub decode_completed: bool,
    pub source_summary: Option<String>,
    pub last_error: Option<String>,
    /// Seek offset in seconds — added to DAC clock position to get absolute stream position.
    pub seek_offset_s: f64,
}

impl Default for NativeTransportSnapshot {
    fn default() -> Self {
        Self {
            state: NativeTransportState::Idle,
            generation: 0,
            current_track_id: None,
            current_title: None,
            source_kind: None,
            decoder: None,
            bit_perfect: false,
            target_driver: None,
            processor_chain_len: 0,
            supports_seek: false,
            duration_s: None,
            source_locator: None,
            output_configured: false,
            stream_spec: None,
            bits_per_sample: None,
            first_packet_frames: None,
            decoded_slab_count: 0,
            decoded_frame_count: 0,
            decoded_byte_count: 0,
            decode_worker_running: false,
            decode_completed: false,
            source_summary: None,
            last_error: None,
            seek_offset_s: 0.0,
        }
    }
}

/// Cached hardware volume values (1/256 dB raw), per channel.
/// `i32::MIN` means "not set by user yet — don't touch".
type HwVolCache = [Arc<AtomicI32>; 3];

/// Cached hardware-volume device info, populated at pre-claim time
/// so that hw_volume_supported/range/channels work before playback starts.
#[derive(Clone, Debug, Default)]
struct HwVolInfo {
    supported: bool,
    channels: Vec<u8>,
    min: i32,
    max: i32,
    res: i32,
}

pub struct NativeTransportController {
    tx: Sender<NativeTransportCommand>,
    snapshot: Arc<Mutex<NativeTransportSnapshot>>,
    events: Arc<Mutex<VecDeque<(i32, String)>>>,
    runtime: Arc<Mutex<Option<NativeUsbRuntime>>>,
    hw_vol_info: Arc<Mutex<HwVolInfo>>,
    volume: SharedVolume,
    spectrum_rx: crossbeam_channel::Receiver<SpectrumFrame>,
    spectrum_tx: crossbeam_channel::Sender<SpectrumFrame>,
    spectrum_bands: Arc<AtomicU32>,
    lufs_values: SharedLufsValues,
    hw_vol_cache: HwVolCache,
    join: Option<thread::JoinHandle<()>>,
}

impl std::fmt::Debug for NativeTransportController {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("NativeTransportController")
            .field("snapshot", &self.snapshot())
            .field("worker_running", &self.join.is_some())
            .finish()
    }
}

impl NativeTransportController {
    pub fn new() -> Self {
        let (tx, rx) = unbounded();
        let snapshot = Arc::new(Mutex::new(NativeTransportSnapshot::default()));
        let events = Arc::new(Mutex::new(VecDeque::new()));
        let runtime = Arc::new(Mutex::new(None));
        let volume = SharedVolume::default();
        let (spectrum_tx, spectrum_rx) = crossbeam_channel::bounded(64);
        let spectrum_bands = Arc::new(AtomicU32::new(512));
        let lufs_values: SharedLufsValues = Arc::new(std::sync::Mutex::new(
            crate::dsp::lufs::LufsValues::default(),
        ));
        let hw_vol_cache: HwVolCache = [
            Arc::new(AtomicI32::new(i32::MIN)),
            Arc::new(AtomicI32::new(i32::MIN)),
            Arc::new(AtomicI32::new(i32::MIN)),
        ];
        let hw_vol_info = Arc::new(Mutex::new(HwVolInfo::default()));
        let snapshot_clone = Arc::clone(&snapshot);
        let events_clone = Arc::clone(&events);
        let runtime_clone = Arc::clone(&runtime);
        let hw_vol_info_clone = Arc::clone(&hw_vol_info);
        let volume_clone = volume.clone();
        let spectrum_tx_clone = spectrum_tx.clone();
        let spectrum_bands_clone = Arc::clone(&spectrum_bands);
        let lufs_clone = Arc::clone(&lufs_values);
        let hw_vol_cache_clone: HwVolCache = [
            Arc::clone(&hw_vol_cache[0]),
            Arc::clone(&hw_vol_cache[1]),
            Arc::clone(&hw_vol_cache[2]),
        ];
        let join = thread::spawn(move || {
            transport_worker(
                rx,
                snapshot_clone,
                events_clone,
                runtime_clone,
                hw_vol_info_clone,
                volume_clone,
                spectrum_tx_clone,
                spectrum_bands_clone,
                lufs_clone,
                hw_vol_cache_clone,
            )
        });
        Self {
            tx,
            snapshot,
            events,
            runtime,
            hw_vol_info,
            volume,
            spectrum_rx,
            spectrum_tx,
            spectrum_bands,
            lufs_values,
            hw_vol_cache,
            join: Some(join),
        }
    }

    pub fn submit(&self, cmd: NativeTransportCommand) -> Result<(), String> {
        self.tx
            .send(cmd)
            .map_err(|e| format!("native transport command send failed: {e}"))
    }

    pub fn claim_device(
        &self,
        device_id: &str,
        bit_depth: u8,
        alt_profile: UacAltProfile,
    ) -> Result<(), String> {
        self.submit(NativeTransportCommand::ClaimDevice {
            device_id: device_id.to_string(),
            bit_depth,
            alt_profile,
        })
    }

    pub fn release_device(&self) -> Result<(), String> {
        self.submit(NativeTransportCommand::ReleaseDevice)
    }

    pub fn load(&self, request: NativeTransportLoadRequest) -> Result<(), String> {
        self.submit(NativeTransportCommand::Load(request))
    }

    pub fn play(&self) -> Result<(), String> {
        self.submit(NativeTransportCommand::Play)
    }

    pub fn pause(&self) -> Result<(), String> {
        self.submit(NativeTransportCommand::Pause)
    }

    pub fn stop(&self) -> Result<(), String> {
        self.submit(NativeTransportCommand::Stop)
    }

    /// Stop playback and release the USB device synchronously.
    /// Blocks until the worker thread has fully released the device.
    pub fn stop_and_release(&self) -> Result<(), String> {
        let (tx, rx) = std::sync::mpsc::sync_channel(1);
        self.submit(NativeTransportCommand::StopAndRelease(tx))?;
        rx.recv()
            .map_err(|e| format!("stop_and_release: recv failed: {e}"))
    }

    pub fn seek_ms(&self, position_ms: u64) -> Result<(), String> {
        // Update seek_offset_s immediately so that rac_get_position() returns
        // the target position right away, avoiding the slider-snap-back glitch
        // while the controller thread processes the seek asynchronously.
        if let Ok(mut state) = self.snapshot.lock() {
            state.seek_offset_s = position_ms as f64 / 1000.0;
            state.decoded_frame_count = 0;
        }
        // Reset the clock feed's total_frames so rac_get_position() reads
        // seek_offset_s + 0 instead of seek_offset_s + stale_frames.
        if let Ok(rt) = self.runtime.lock() {
            if let Some(ref info) = *rt {
                info.feed.total_frames.store(0, Ordering::Release);
            }
        }
        self.submit(NativeTransportCommand::SeekMs(position_ms))
    }

    pub fn update_dsp_config(&self, config: &crate::dsp::DspGraphConfig) -> Result<(), String> {
        self.submit(NativeTransportCommand::UpdateDspConfig(config.clone()))
    }

    pub fn set_volume(&self, gain: f32) {
        self.volume.set(gain);
    }

    pub fn set_spectrum_bands(&self, bands: u32) {
        self.spectrum_bands.store(bands, Ordering::Relaxed);
    }

    pub fn take_spectrum_frames(&self) -> Vec<SpectrumFrame> {
        let mut frames = Vec::new();
        while let Ok(frame) = self.spectrum_rx.try_recv() {
            frames.push(frame);
        }
        frames
    }

    pub fn lufs_values(&self) -> crate::dsp::lufs::LufsValues {
        self.lufs_values
            .lock()
            .map(|v| v.clone())
            .unwrap_or_default()
    }

    pub fn snapshot(&self) -> NativeTransportSnapshot {
        self.snapshot
            .lock()
            .map(|state| state.clone())
            .unwrap_or_default()
    }

    pub fn take_events(&self) -> Vec<(i32, String)> {
        match self.events.lock() {
            Ok(mut events) => events.drain(..).collect(),
            Err(_) => Vec::new(),
        }
    }

    pub fn runtime_info(&self) -> Option<NativeUsbRuntime> {
        self.runtime.lock().ok().and_then(|runtime| runtime.clone())
    }

    pub fn hw_volume_supported(&self) -> bool {
        if let Some(runtime) = self.runtime_info() {
            return runtime.hw_volume_supported;
        }
        // Fallback: check cached info from pre-claim.
        self.hw_vol_info
            .lock()
            .ok()
            .map(|i| i.supported)
            .unwrap_or(false)
    }

    pub fn hw_volume_range(&self) -> Option<(i32, i32, i32)> {
        if let Some(runtime) = self.runtime_info() {
            let device = runtime.control_device.lock().ok()?;
            let (min, max, res) = device.get_hw_volume_range()?;
            return Some((min as i32, max as i32, res as i32));
        }
        // Fallback: cached range from pre-claim.
        let info = self.hw_vol_info.lock().ok()?;
        if info.supported {
            Some((info.min, info.max, info.res))
        } else {
            None
        }
    }

    pub fn hw_volume_channels(&self) -> Option<Vec<u8>> {
        if let Some(runtime) = self.runtime_info() {
            if runtime.hw_volume_supported {
                return Some(runtime.hw_volume_channels.clone());
            }
            return None;
        }
        // Fallback: cached channels from pre-claim.
        let info = self.hw_vol_info.lock().ok()?;
        if info.supported {
            Some(info.channels.clone())
        } else {
            None
        }
    }

    pub fn hw_volume_get_ch(&self, idx: usize) -> Option<i32> {
        if let Some(runtime) = self.runtime_info() {
            let device = runtime.control_device.lock().ok()?;
            return device.get_hw_volume_ch(idx).map(|v| v as i32);
        }
        // Before playback, return the cached value from hw_vol_cache
        // (which was populated from the pre-claim volume read events).
        if idx < 3 {
            let v = self.hw_vol_cache[idx].load(Ordering::Relaxed);
            if v != i32::MIN {
                return Some(v);
            }
        }
        None
    }

    pub fn hw_volume_set_all(&self, value_raw: i32) -> bool {
        for c in &self.hw_vol_cache {
            c.store(value_raw, Ordering::Relaxed);
        }
        let Some(runtime) = self.runtime_info() else {
            return false;
        };
        let Ok(device) = runtime.control_device.lock() else {
            return false;
        };
        device.set_hw_volume(value_raw as i16).is_ok()
    }

    pub fn hw_volume_set_ch(&self, idx: usize, value_raw: i32) -> bool {
        if idx < 3 {
            self.hw_vol_cache[idx].store(value_raw, Ordering::Relaxed);
        }
        let Some(runtime) = self.runtime_info() else {
            return false;
        };
        let Ok(device) = runtime.control_device.lock() else {
            return false;
        };
        device.set_hw_volume_ch(idx, value_raw as i16).is_ok()
    }
}

impl Default for NativeTransportController {
    fn default() -> Self {
        Self::new()
    }
}

impl Drop for NativeTransportController {
    fn drop(&mut self) {
        let _ = self.tx.send(NativeTransportCommand::Shutdown);
        if let Some(join) = self.join.take() {
            let _ = join.join();
        }
    }
}

type SharedSessionSlot = Arc<Mutex<Option<UsbAudioSink>>>;

/// Saved config for re-claiming the USB device after a decode worker stops.
#[derive(Clone)]
struct ClaimedDeviceCfg {
    device_id: String,
    bit_depth: u8,
    alt_profile: UacAltProfile,
}

struct DecodeWorkerHandle {
    stop: Arc<AtomicBool>,
    join: thread::JoinHandle<()>,
    session_slot: SharedSessionSlot,
    /// When `false` the decode worker fills the USB queue but does **not** call
    /// `ensure_started()`.  The Play command flips this to `true`, which lets
    /// the next `push_slab_to_usb_output` call arm the ISO ring and begin
    /// audible playback.  This enables "eager decode": the worker can be
    /// spawned at Load time so that HTTP, decoding, and USB prefill happen
    /// *before* the user presses Play, eliminating startup latency.
    auto_start: Arc<AtomicBool>,
}

#[derive(Clone)]
pub struct NativeUsbRuntime {
    pub feed: Arc<AlsaHwClockFeed>,
    pub bit_depth: u8,
    pub device_name: String,
    pub hw_volume_supported: bool,
    pub hw_volume_channels: Vec<u8>,
    pub control_device: Arc<Mutex<OpenUsbDevice>>,
}

fn queue_native_event(
    events: &Arc<Mutex<VecDeque<(i32, String)>>>,
    evt: i32,
    msg: impl Into<String>,
) {
    if let Ok(mut pending) = events.lock() {
        if pending.len() >= 32 {
            pending.pop_front();
        }
        pending.push_back((evt, msg.into()));
    }
}

fn transport_worker(
    rx: Receiver<NativeTransportCommand>,
    snapshot: Arc<Mutex<NativeTransportSnapshot>>,
    events: Arc<Mutex<VecDeque<(i32, String)>>>,
    runtime: Arc<Mutex<Option<NativeUsbRuntime>>>,
    hw_vol_info: Arc<Mutex<HwVolInfo>>,
    volume: SharedVolume,
    spectrum_tx: crossbeam_channel::Sender<SpectrumFrame>,
    spectrum_bands: Arc<AtomicU32>,
    lufs_values: SharedLufsValues,
    hw_vol_cache: HwVolCache,
) {
    let processor_chain_len = PcmProcessorChain::new().len();
    let mut current_source: Option<NativeTransportSource> = None;
    let mut current_output_config: Option<UsbRawSinkConfig> = None;
    let mut current_dsp_config: Option<crate::dsp::DspGraphConfig> = None;
    // Shared slot for hot-updating DSP config in the running decode worker.
    let dsp_config_slot: super::native_dsp::SharedDspConfig = Arc::new(Mutex::new(None));
    let mut decode_worker: Option<DecodeWorkerHandle> = None;
    // Early-claimed USB device handle.  Keeps the kernel driver detached so
    // PipeWire / PulseAudio cannot reclaim the device between track switches
    // or before the first track starts playing.
    let mut claimed_device: Option<OpenUsbDevice> = None;
    let mut claimed_cfg: Option<ClaimedDeviceCfg> = None;
    while let Ok(cmd) = rx.recv() {
        match cmd {
            NativeTransportCommand::ClaimDevice {
                device_id,
                bit_depth,
                alt_profile,
            } => {
                // Release any previous claim.
                claimed_device = None;
                claimed_cfg = Some(ClaimedDeviceCfg {
                    device_id: device_id.clone(),
                    bit_depth,
                    alt_profile,
                });
                let dev = usb_audio::enumerate_usb_audio_devices()
                    .into_iter()
                    .find(|d| d.id() == device_id);
                if let Some(dev) = dev {
                    match OpenUsbDevice::open(&dev) {
                        Ok(mut open_dev) => {
                            // Claim interfaces only — no alt-setting or rate
                            // setting.  This detaches snd-usb-audio and keeps
                            // PipeWire from grabbing the device.  Rate will be
                            // set later in configure() when playback starts.
                            match open_dev.claim_only() {
                                Ok(()) => {
                                    eprintln!(
                                        "native-transport: pre-claimed USB device {}",
                                        device_id
                                    );
                                    // Populate hw-volume info + cache from DAC
                                    // so the UI can query volume before playback.
                                    if let Some(ref fu) = open_dev.dev.feature_unit {
                                        if fu.has_volume {
                                            // Cache range + channels info.
                                            let range = open_dev.get_hw_volume_range();
                                            if let Ok(mut info) = hw_vol_info.lock() {
                                                info.supported = true;
                                                info.channels = fu.channels.clone();
                                                if let Some((mn, mx, rs)) = range {
                                                    info.min = mn as i32;
                                                    info.max = mx as i32;
                                                    info.res = rs as i32;
                                                }
                                            }
                                            // Read + cache per-channel current values.
                                            for (idx, &ch) in fu.channels.iter().enumerate() {
                                                let vol = open_dev.get_hw_volume_ch(idx);
                                                eprintln!(
                                                    "native-transport: pre-claim hw-vol idx={} uac_ch={} value={:?}",
                                                    idx, ch, vol
                                                );
                                                if let Some(v) = vol {
                                                    if idx < 3 {
                                                        hw_vol_cache[idx]
                                                            .store(v as i32, Ordering::Relaxed);
                                                    }
                                                    queue_native_event(
                                                        &events,
                                                        crate::EVT_STATE,
                                                        format!("usb-hw-volume-ch{}={}", ch, v),
                                                    );
                                                }
                                            }
                                        }
                                    }
                                    queue_native_event(
                                        &events,
                                        crate::EVT_STATE,
                                        format!("native-transport device-claimed {}", device_id),
                                    );
                                    // Signal hw-volume readiness so the UI can
                                    // display the actual DAC volume on startup.
                                    queue_native_event(
                                        &events,
                                        crate::EVT_STATE,
                                        "usb-audio configured",
                                    );
                                    claimed_device = Some(open_dev);
                                }
                                Err(e) => {
                                    eprintln!("native-transport: pre-claim failed: {}", e);
                                }
                            }
                        }
                        Err(e) => {
                            eprintln!("native-transport: pre-claim open failed: {}", e);
                        }
                    }
                } else {
                    eprintln!(
                        "native-transport: pre-claim device '{}' not found",
                        device_id
                    );
                }
            }
            NativeTransportCommand::ReleaseDevice => {
                claimed_device = None;
                claimed_cfg = None;
                eprintln!("native-transport: USB device claim released");
            }
            NativeTransportCommand::StopAndRelease(done_tx) => {
                set_native_runtime(&runtime, None);
                let old_sink = stop_decode_worker(&mut decode_worker);
                if let Some(mut sink) = old_sink {
                    sink.set_skip_release_on_drop(true);
                    drop(sink);
                }
                // Release — do NOT reclaim.
                claimed_device = None;
                claimed_cfg = None;
                {
                    let mut state = match snapshot.lock() {
                        Ok(guard) => guard,
                        Err(_) => break,
                    };
                    state.decode_worker_running = false;
                    if state.current_track_id.is_some() {
                        state.state = NativeTransportState::Stopped;
                        queue_native_event(&events, crate::EVT_STATE, "native-transport Stopped");
                    }
                }
                eprintln!("native-transport: stop-and-release complete");
                let _ = done_tx.send(());
            }
            NativeTransportCommand::Load(request) => {
                // Clear runtime FIRST — its control_device Arc keeps the old
                // OpenUsbDevice alive.  Without this, stop_decode_worker's
                // session would keep a lingering Arc preventing extraction.
                set_native_runtime(&runtime, None);

                // Stop old worker and harvest its USB session.  We keep the
                // session alive (not dropped) so the USB handle stays open
                // and the DAC PLL remains locked — dropping the handle would
                // trigger libusb_close → kernel driver reattach → PLL reset
                // → 1-2 seconds of DAC mute on the next track.
                let reuse_session = stop_decode_worker(&mut decode_worker);
                if reuse_session.is_some() {
                    eprintln!("native-transport: load — keeping old USB session for reuse");
                } else if claimed_device.is_none() {
                    // No session to reuse and no pre-claimed handle — reclaim.
                    reclaim_device(&mut claimed_device, &claimed_cfg);
                }

                let plan = request.source.plan();
                {
                    let mut state = match snapshot.lock() {
                        Ok(guard) => guard,
                        Err(_) => break,
                    };
                    state.generation = state.generation.saturating_add(1);
                    state.state = NativeTransportState::Loading;
                    state.current_track_id = Some(request.source.track().track_id.clone());
                    state.current_title = Some(request.source.track().title.clone());
                    state.source_kind = Some(plan.source_kind);
                    state.decoder = Some(plan.decoder);
                    state.bit_perfect = request.bit_perfect;
                    state.target_driver = Some(request.target_driver.clone());
                    state.processor_chain_len = processor_chain_len;
                    state.supports_seek = plan.supports_seek;
                    state.duration_s = None;
                    state.source_locator = Some(request.source.locator().to_string());
                    state.output_configured = request.output_target.is_some();
                    state.stream_spec = None;
                    state.bits_per_sample = None;
                    state.first_packet_frames = None;
                    state.decoded_slab_count = 0;
                    state.decoded_frame_count = 0;
                    state.decoded_byte_count = 0;
                    state.decode_worker_running = false;
                    state.decode_completed = false;
                    state.source_summary = None;
                    state.last_error = None;
                    state.seek_offset_s = 0.0;
                }

                current_source = Some(request.source.clone());
                current_output_config = request
                    .output_target
                    .as_ref()
                    .and_then(|t| t.usb_cfg().cloned());
                current_dsp_config = request.dsp_config.clone();

                // ── Eager decode ─────────────────────────────────────────
                // Instead of opening a separate HTTP connection just to
                // probe stream info, start the decode worker immediately
                // with auto_start=false.  The worker opens HTTP, probes the
                // format, populates the snapshot, opens the USB device, and
                // fills the queue — all *before* the user presses Play.
                // When Play arrives it flips auto_start → true, and the
                // ring starts on the next push with near-zero latency.
                let gen = match snapshot.lock() {
                    Ok(g) => g.generation,
                    Err(_) => break,
                };
                let auto_start = Arc::new(AtomicBool::new(false));
                match start_direct_audio_decode_worker(
                    request.source.clone(),
                    Arc::clone(&snapshot),
                    Arc::clone(&events),
                    request
                        .output_target
                        .as_ref()
                        .and_then(|t| t.usb_cfg().cloned()),
                    Arc::clone(&runtime),
                    gen,
                    None,
                    volume.clone(),
                    spectrum_tx.clone(),
                    Arc::clone(&spectrum_bands),
                    Arc::clone(&lufs_values),
                    hw_vol_cache.clone(),
                    claimed_device.take(),
                    auto_start,
                    reuse_session,
                    current_dsp_config.clone(),
                    Arc::clone(&dsp_config_slot),
                ) {
                    Ok(worker) => {
                        decode_worker = Some(worker);
                        if let Ok(mut state) = snapshot.lock() {
                            state.decode_worker_running = true;
                        }
                        queue_native_event(
                            &events,
                            crate::EVT_STATE,
                            "native-transport eager decode started",
                        );
                    }
                    Err(err) => {
                        reclaim_device(&mut claimed_device, &claimed_cfg);
                        queue_native_event(
                            &events,
                            crate::EVT_ERROR,
                            format!("native-transport eager decode failed: {err}"),
                        );
                        if let Ok(mut state) = snapshot.lock() {
                            state.last_error = Some(err);
                            state.state = NativeTransportState::Error;
                        }
                    }
                }
            }
            NativeTransportCommand::Play => {
                let generation = match snapshot.lock() {
                    Ok(guard) => guard,
                    Err(_) => break,
                }
                .generation;
                if let Some(source) = current_source.clone() {
                    if let Some(ref worker) = decode_worker {
                        // Eager worker from Load is already running — just
                        // flip auto_start so the ring starts on the next push.
                        worker.auto_start.store(true, Ordering::Release);
                    } else {
                        // No eager worker — start a fresh one with auto_start=true.
                        // If we're resuming from Pause, the snapshot still holds
                        // the paused position; pass it as seek_start_ms so the
                        // new decode worker resumes instead of restarting from 0.
                        let resume_pos_ms = current_native_playback_position_ms(&snapshot, &runtime);
                        set_native_runtime(&runtime, None);
                        if resume_pos_ms > 0 {
                            if let Ok(mut state) = snapshot.lock() {
                                state.seek_offset_s = resume_pos_ms as f64 / 1000.0;
                                state.decoded_frame_count = 0;
                            }
                        }
                        let seek_start_ms = if resume_pos_ms > 0 { Some(resume_pos_ms) } else { None };
                        let auto_start = Arc::new(AtomicBool::new(true));
                        match start_direct_audio_decode_worker(
                            source,
                            Arc::clone(&snapshot),
                            Arc::clone(&events),
                            current_output_config.clone(),
                            Arc::clone(&runtime),
                            generation,
                            seek_start_ms,
                            volume.clone(),
                            spectrum_tx.clone(),
                            Arc::clone(&spectrum_bands),
                            Arc::clone(&lufs_values),
                            hw_vol_cache.clone(),
                            claimed_device.take(),
                            auto_start,
                            None, // no reuse_session for Play
                            current_dsp_config.clone(),
                            Arc::clone(&dsp_config_slot),
                        ) {
                            Ok(worker) => {
                                decode_worker = Some(worker);
                                if let Ok(mut state) = snapshot.lock() {
                                    state.decode_worker_running = true;
                                    state.decode_completed = false;
                                    state.last_error = None;
                                }
                            }
                            Err(err) => {
                                // Play failed — re-claim so PipeWire can't grab it.
                                reclaim_device(&mut claimed_device, &claimed_cfg);
                                queue_native_event(
                                    &events,
                                    crate::EVT_ERROR,
                                    format!("native-transport decode worker start failed: {err}"),
                                );
                                if let Ok(mut state) = snapshot.lock() {
                                    state.last_error = Some(err);
                                }
                            }
                        }
                    }
                }
                let mut state = match snapshot.lock() {
                    Ok(guard) => guard,
                    Err(_) => break,
                };
                if state.current_track_id.is_some() {
                    state.state = NativeTransportState::Playing;
                    queue_native_event(&events, crate::EVT_STATE, "native-transport Playing");
                }
            }
            NativeTransportCommand::Pause => {
                // Capture the live play-head position BEFORE tearing down the
                // runtime.  The Play handler later asks for it via the same
                // helper, but by then `runtime` is None and only the
                // `decoded_frame_count / rate` fallback is available — which
                // diverges from real playback time under a network underrun
                // storm (decoder throttled below realtime by slow HTTP reads),
                // and can round to 0, causing resume to restart from segment 1.
                // Stash the authoritative position into seek_offset_s so the
                // Play handler reads it straight out of the snapshot.
                let pause_pos_ms = current_native_playback_position_ms(&snapshot, &runtime);
                set_native_runtime(&runtime, None);
                let old_sink = stop_decode_worker(&mut decode_worker);
                if let Some(mut sink) = old_sink {
                    sink.set_skip_release_on_drop(true);
                    drop(sink);
                }
                let mut state = match snapshot.lock() {
                    Ok(guard) => guard,
                    Err(_) => break,
                };
                state.decode_worker_running = false;
                if pause_pos_ms > 0 {
                    state.seek_offset_s = pause_pos_ms as f64 / 1000.0;
                    state.decoded_frame_count = 0;
                }
                if matches!(
                    state.state,
                    NativeTransportState::Playing | NativeTransportState::Ready
                ) {
                    state.state = NativeTransportState::Paused;
                    queue_native_event(&events, crate::EVT_STATE, "native-transport Paused");
                }
            }
            NativeTransportCommand::Stop => {
                set_native_runtime(&runtime, None);
                // Stop the decode worker but keep the device claimed (don't
                // release + reclaim).  This avoids PLL disturbance on DACs
                // like Monitor 09 that are sensitive to interface cycling.
                // The old sink's OpenUsbDevice is dropped with
                // skip_release_on_drop so libusb_close doesn't reset
                // alt-setting to 0 (PLL stays locked).
                let old_sink = stop_decode_worker(&mut decode_worker);
                if let Some(mut sink) = old_sink {
                    sink.set_skip_release_on_drop(true);
                    drop(sink);
                }
                let mut state = match snapshot.lock() {
                    Ok(guard) => guard,
                    Err(_) => break,
                };
                state.decode_worker_running = false;
                if state.current_track_id.is_some() {
                    state.state = NativeTransportState::Stopped;
                    queue_native_event(&events, crate::EVT_STATE, "native-transport Stopped");
                }
            }
            NativeTransportCommand::SeekMs(position_ms) => {
                let (generation, supports_seek, cur_state) = match snapshot.lock() {
                    Ok(state) => (state.generation, state.supports_seek, state.state),
                    Err(_) => break,
                };
                let can_seek = supports_seek
                    && (cur_state == NativeTransportState::Playing
                        || cur_state == NativeTransportState::Paused);
                if !supports_seek {
                    queue_native_event(
                        &events,
                        crate::EVT_ERROR,
                        "native-transport seek unsupported for current source",
                    );
                    if let Ok(mut state) = snapshot.lock() {
                        state.last_error = Some(
                            "native transport seek unsupported for current source".to_string(),
                        );
                    }
                } else if can_seek {
                    if let Some(source) = current_source.clone() {
                        set_native_runtime(&runtime, None);
                        let seek_reuse_session = stop_decode_worker(&mut decode_worker);
                        if seek_reuse_session.is_none() {
                            // No session to reuse — reclaim device the normal way.
                            reclaim_device(&mut claimed_device, &claimed_cfg);
                        }
                        let handle_for_worker = if seek_reuse_session.is_some() {
                            None // session reuse provides the USB handle
                        } else {
                            claimed_device.take()
                        };

                        // Wait for the USB ring to drain before pushing post-seek
                        // audio. Without this the ring still holds ~200 ms of
                        // pre-seek samples; new audio lands abruptly after them
                        // and the waveform discontinuity is audible as a click.
                        // After draining, the transfer thread's existing
                        // underrun fade-out + silence-pad + fade-in path smooths
                        // the boundary on its own.
                        if let Some(ref session) = seek_reuse_session {
                            let drain_deadline = std::time::Instant::now()
                                + std::time::Duration::from_millis(280);
                            // ~2 ms at 96 kHz/24-bit/stereo. Small enough that the
                            // next ISO callback hits the underrun branch and the
                            // fade-out tail engages cleanly.
                            let drain_target_bytes: usize = 1152;
                            loop {
                                if session.queued_bytes() <= drain_target_bytes {
                                    break;
                                }
                                if std::time::Instant::now() >= drain_deadline {
                                    break;
                                }
                                std::thread::sleep(std::time::Duration::from_millis(2));
                            }
                        }

                        // Reset decoded counters for the new position.
                        if let Ok(mut state) = snapshot.lock() {
                            state.decoded_slab_count = 0;
                            state.decoded_frame_count = 0;
                            state.decoded_byte_count = 0;
                            state.decode_completed = false;
                            state.last_error = None;
                            state.seek_offset_s = position_ms as f64 / 1000.0;
                        }
                        // Seek always starts with auto_start=true (we're already playing).
                        let auto_start = Arc::new(AtomicBool::new(true));
                        match start_direct_audio_decode_worker(
                            source,
                            Arc::clone(&snapshot),
                            Arc::clone(&events),
                            current_output_config.clone(),
                            Arc::clone(&runtime),
                            generation,
                            Some(position_ms),
                            volume.clone(),
                            spectrum_tx.clone(),
                            Arc::clone(&spectrum_bands),
                            Arc::clone(&lufs_values),
                            hw_vol_cache.clone(),
                            handle_for_worker,
                            auto_start,
                            seek_reuse_session,
                            current_dsp_config.clone(),
                            Arc::clone(&dsp_config_slot),
                        ) {
                            Ok(worker) => {
                                decode_worker = Some(worker);
                                if let Ok(mut state) = snapshot.lock() {
                                    state.decode_worker_running = true;
                                }
                            }
                            Err(err) => {
                                // Seek failed — re-claim so PipeWire can't grab it.
                                reclaim_device(&mut claimed_device, &claimed_cfg);
                                queue_native_event(
                                    &events,
                                    crate::EVT_ERROR,
                                    format!("native-transport seek restart failed: {err}"),
                                );
                                if let Ok(mut state) = snapshot.lock() {
                                    state.last_error = Some(err);
                                }
                            }
                        }
                    }
                }
            }
            NativeTransportCommand::UpdateDspConfig(new_cfg) => {
                let previous_native_active = current_dsp_config
                    .as_ref()
                    .map(|cfg| cfg.has_native_transport_processing())
                    .unwrap_or(false);
                let new_native_active = new_cfg.has_native_transport_processing();
                let target_bit_perfect = !new_native_active;
                let unsupported = new_cfg.native_transport_unsupported_modules();
                if !unsupported.is_empty() {
                    queue_native_event(
                        &events,
                        crate::EVT_STATE,
                        format!(
                            "native-transport dsp unsupported skipped modules={}",
                            unsupported.join(",")
                        ),
                    );
                }

                current_dsp_config = if new_native_active {
                    Some(new_cfg.clone())
                } else {
                    None
                };

                let (generation, cur_state, has_track) = match snapshot.lock() {
                    Ok(mut state) => {
                        state.bit_perfect = target_bit_perfect;
                        (
                            state.generation,
                            state.state,
                            state.current_track_id.is_some(),
                        )
                    }
                    Err(_) => break,
                };

                if previous_native_active == new_native_active {
                    if let Ok(mut slot) = dsp_config_slot.lock() {
                        *slot = if new_native_active {
                            Some(new_cfg)
                        } else {
                            None
                        };
                    }
                    continue;
                }

                if !has_track || current_source.is_none() {
                    if let Ok(mut slot) = dsp_config_slot.lock() {
                        *slot = None;
                    }
                    continue;
                }

                let should_restart = decode_worker.is_some()
                    && matches!(
                        cur_state,
                        NativeTransportState::Loading
                            | NativeTransportState::Ready
                            | NativeTransportState::Playing
                    );
                if !should_restart {
                    if let Ok(mut slot) = dsp_config_slot.lock() {
                        *slot = None;
                    }
                    continue;
                }

                let restart_pos_ms = if cur_state == NativeTransportState::Playing {
                    Some(current_native_playback_position_ms(&snapshot, &runtime))
                } else {
                    None
                };
                queue_native_event(
                    &events,
                    crate::EVT_STATE,
                    format!(
                        "native-transport dsp-mode-switch native_active={} bit_perfect={} pos_ms={} state={:?}",
                        new_native_active,
                        target_bit_perfect,
                        restart_pos_ms.unwrap_or(0),
                        cur_state,
                    ),
                );
                eprintln!(
                    "native-transport: dsp mode switch native_active={} bit_perfect={} pos_ms={} state={:?}",
                    new_native_active,
                    target_bit_perfect,
                    restart_pos_ms.unwrap_or(0),
                    cur_state,
                );

                set_native_runtime(&runtime, None);
                let restart_reuse_session = stop_decode_worker(&mut decode_worker);
                if restart_reuse_session.is_none() {
                    reclaim_device(&mut claimed_device, &claimed_cfg);
                }
                let handle_for_worker = if restart_reuse_session.is_some() {
                    None
                } else {
                    claimed_device.take()
                };

                if let Ok(mut state) = snapshot.lock() {
                    state.bit_perfect = target_bit_perfect;
                    state.decoded_slab_count = 0;
                    state.decoded_frame_count = 0;
                    state.decoded_byte_count = 0;
                    state.decode_worker_running = false;
                    state.decode_completed = false;
                    state.last_error = None;
                    if let Some(pos_ms) = restart_pos_ms {
                        state.seek_offset_s = pos_ms as f64 / 1000.0;
                    } else {
                        state.seek_offset_s = 0.0;
                        if cur_state != NativeTransportState::Playing {
                            state.state = NativeTransportState::Loading;
                        }
                    }
                }
                if let Ok(mut slot) = dsp_config_slot.lock() {
                    *slot = None;
                }

                let Some(source) = current_source.clone() else {
                    continue;
                };
                let auto_start =
                    Arc::new(AtomicBool::new(cur_state == NativeTransportState::Playing));
                match start_direct_audio_decode_worker(
                    source,
                    Arc::clone(&snapshot),
                    Arc::clone(&events),
                    current_output_config.clone(),
                    Arc::clone(&runtime),
                    generation,
                    restart_pos_ms,
                    volume.clone(),
                    spectrum_tx.clone(),
                    Arc::clone(&spectrum_bands),
                    Arc::clone(&lufs_values),
                    hw_vol_cache.clone(),
                    handle_for_worker,
                    auto_start,
                    restart_reuse_session,
                    current_dsp_config.clone(),
                    Arc::clone(&dsp_config_slot),
                ) {
                    Ok(worker) => {
                        decode_worker = Some(worker);
                        if let Ok(mut state) = snapshot.lock() {
                            state.decode_worker_running = true;
                        }
                    }
                    Err(err) => {
                        reclaim_device(&mut claimed_device, &claimed_cfg);
                        queue_native_event(
                            &events,
                            crate::EVT_ERROR,
                            format!("native-transport dsp mode restart failed: {err}"),
                        );
                        if let Ok(mut state) = snapshot.lock() {
                            state.last_error = Some(err);
                            state.state = NativeTransportState::Error;
                        }
                    }
                }
            }
            NativeTransportCommand::Shutdown => {
                set_native_runtime(&runtime, None);
                let _old = stop_decode_worker(&mut decode_worker);
                drop(_old);
                claimed_device = None; // release USB claim
                let mut state = match snapshot.lock() {
                    Ok(guard) => guard,
                    Err(_) => break,
                };
                state.state = NativeTransportState::Shutdown;
                break;
            }
        }
    }
    // Final drop of `claimed_device` releases the USB interface on shutdown.
    drop(claimed_device);
}

/// Stop the decode worker and return the parked USB session (if any).
///
/// The caller can drop the session to release the USB interface, or keep it
/// alive to prevent PipeWire from reclaiming the device.
fn stop_decode_worker(worker: &mut Option<DecodeWorkerHandle>) -> Option<UsbAudioSink> {
    if let Some(handle) = worker.take() {
        handle.stop.store(true, Ordering::Release);
        let _ = handle.join.join();
        if let Ok(mut slot) = handle.session_slot.lock() {
            return slot.take();
        }
    }
    None
}

/// Stop the decode worker, drop the old session, and immediately re-claim
/// the USB device to prevent PipeWire from grabbing it.  The re-claim opens
/// a new handle and calls `claim_only()`.
fn stop_and_reclaim(
    worker: &mut Option<DecodeWorkerHandle>,
    claimed_device: &mut Option<OpenUsbDevice>,
    cfg: &Option<ClaimedDeviceCfg>,
) {
    let _old_session = stop_decode_worker(worker);
    // Drop old session — releases its USB handle.
    drop(_old_session);
    // Immediately re-claim with a fresh handle.
    reclaim_device(claimed_device, cfg);
}

/// Open a fresh USB handle and claim_only() to keep the kernel driver detached.
/// Retries a few times if BUSY (lingering Arc from runtime / other handles).
fn reclaim_device(claimed_device: &mut Option<OpenUsbDevice>, cfg: &Option<ClaimedDeviceCfg>) {
    *claimed_device = None;
    let cfg = match cfg {
        Some(c) => c,
        None => return,
    };
    let dev = usb_audio::enumerate_usb_audio_devices()
        .into_iter()
        .find(|d| d.id() == cfg.device_id);
    let dev = match dev {
        Some(d) => d,
        None => {
            eprintln!(
                "native-transport: re-claim device '{}' not found",
                cfg.device_id
            );
            return;
        }
    };
    // Retry claim — a lingering Arc<Mutex<OpenUsbDevice>> from the runtime
    // or another thread may still hold the interface for a few microseconds.
    for attempt in 0..3u32 {
        if attempt > 0 {
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
        match OpenUsbDevice::open(&dev) {
            Ok(mut open_dev) => match open_dev.claim_only() {
                Ok(()) => {
                    eprintln!("native-transport: re-claimed USB device {}", cfg.device_id);
                    *claimed_device = Some(open_dev);
                    return;
                }
                Err(e) => {
                    eprintln!(
                        "native-transport: re-claim attempt {} failed: {}",
                        attempt + 1,
                        e
                    );
                }
            },
            Err(e) => {
                eprintln!(
                    "native-transport: re-claim open attempt {} failed: {}",
                    attempt + 1,
                    e
                );
            }
        }
    }
    eprintln!("native-transport: re-claim gave up after 3 attempts");
}

fn set_native_runtime(
    runtime: &Arc<Mutex<Option<NativeUsbRuntime>>>,
    value: Option<NativeUsbRuntime>,
) {
    if let Ok(mut slot) = runtime.lock() {
        *slot = value;
    }
}

fn current_native_playback_position_ms(
    snapshot: &Arc<Mutex<NativeTransportSnapshot>>,
    runtime: &Arc<Mutex<Option<NativeUsbRuntime>>>,
) -> u64 {
    let (seek_offset_s, decoded_frame_count, fallback_rate) = match snapshot.lock() {
        Ok(state) => (
            state.seek_offset_s,
            state.decoded_frame_count,
            state
                .stream_spec
                .as_ref()
                .map(|spec| spec.sample_rate)
                .unwrap_or(0),
        ),
        Err(_) => (0.0, 0, 0),
    };

    let pos_s = match runtime.lock() {
        Ok(slot) => slot
            .as_ref()
            .and_then(|info| {
                info.feed
                    .write_elapsed_s()
                    .map(|elapsed| seek_offset_s + elapsed)
            })
            .unwrap_or_else(|| {
                if fallback_rate > 0 {
                    seek_offset_s + (decoded_frame_count as f64 / fallback_rate as f64)
                } else {
                    seek_offset_s
                }
            }),
        Err(_) => seek_offset_s,
    };

    (pos_s.max(0.0) * 1000.0).round() as u64
}

fn start_direct_audio_decode_worker(
    source: NativeTransportSource,
    snapshot: Arc<Mutex<NativeTransportSnapshot>>,
    events: Arc<Mutex<VecDeque<(i32, String)>>>,
    output_config: Option<UsbRawSinkConfig>,
    runtime: Arc<Mutex<Option<NativeUsbRuntime>>>,
    generation: u64,
    seek_start_ms: Option<u64>,
    volume: SharedVolume,
    spectrum_tx: crossbeam_channel::Sender<SpectrumFrame>,
    spectrum_bands: Arc<AtomicU32>,
    lufs_values: SharedLufsValues,
    hw_vol_cache: HwVolCache,
    pre_claimed_handle: Option<OpenUsbDevice>,
    auto_start: Arc<AtomicBool>,
    reuse_session: Option<UsbAudioSink>,
    dsp_config: Option<crate::dsp::DspGraphConfig>,
    dsp_config_slot: super::native_dsp::SharedDspConfig,
) -> Result<DecodeWorkerHandle, String> {
    let stop = Arc::new(AtomicBool::new(false));
    let stop_clone = Arc::clone(&stop);
    let session_slot: SharedSessionSlot = Arc::new(Mutex::new(None));
    let session_slot_clone = Arc::clone(&session_slot);
    let auto_start_clone = Arc::clone(&auto_start);
    let join = thread::Builder::new()
        .name("native-transport-direct-audio".to_string())
        .spawn(move || {
            direct_audio_decode_worker(
                stop_clone,
                source,
                snapshot,
                events,
                output_config,
                runtime,
                generation,
                seek_start_ms,
                volume,
                spectrum_tx,
                spectrum_bands,
                lufs_values,
                session_slot_clone,
                hw_vol_cache,
                pre_claimed_handle,
                auto_start_clone,
                reuse_session,
                dsp_config,
                dsp_config_slot,
            )
        })
        .map_err(|e| format!("native transport: failed to spawn decode worker: {e}"))?;
    Ok(DecodeWorkerHandle {
        stop,
        join,
        session_slot,
        auto_start,
    })
}

fn direct_audio_decode_worker(
    stop: Arc<AtomicBool>,
    source: NativeTransportSource,
    snapshot: Arc<Mutex<NativeTransportSnapshot>>,
    events: Arc<Mutex<VecDeque<(i32, String)>>>,
    output_config: Option<UsbRawSinkConfig>,
    runtime: Arc<Mutex<Option<NativeUsbRuntime>>>,
    generation: u64,
    seek_start_ms: Option<u64>,
    volume: SharedVolume,
    spectrum_tx: crossbeam_channel::Sender<SpectrumFrame>,
    spectrum_bands: Arc<AtomicU32>,
    lufs_values: SharedLufsValues,
    session_slot: SharedSessionSlot,
    hw_vol_cache: HwVolCache,
    pre_claimed_handle: Option<OpenUsbDevice>,
    auto_start: Arc<AtomicBool>,
    reuse_session: Option<UsbAudioSink>,
    dsp_config: Option<crate::dsp::DspGraphConfig>,
    dsp_config_slot: super::native_dsp::SharedDspConfig,
) {
    queue_native_event(&events, crate::EVT_STATE, "native-transport decode-start");
    let result = decode_direct_audio_stream(
        &stop,
        &source,
        &snapshot,
        &events,
        output_config,
        &runtime,
        generation,
        seek_start_ms,
        volume,
        spectrum_tx,
        spectrum_bands,
        lufs_values,
        &session_slot,
        &hw_vol_cache,
        pre_claimed_handle,
        &auto_start,
        reuse_session,
        dsp_config,
        dsp_config_slot,
    );
    if let Ok(mut state) = snapshot.lock() {
        if state.generation != generation {
            return;
        }
        state.decode_worker_running = false;
        if stop.load(Ordering::Acquire) {
            return;
        }
        match result {
            Ok(()) => {
                state.decode_completed = true;
                queue_native_event(
                    &events,
                    crate::EVT_STATE,
                    format!(
                        "native-transport decode-complete slabs={} frames={} bytes={}",
                        state.decoded_slab_count,
                        state.decoded_frame_count,
                        state.decoded_byte_count
                    ),
                );
            }
            Err(err) => {
                queue_native_event(
                    &events,
                    crate::EVT_ERROR,
                    format!("native-transport decode error: {err}"),
                );
                state.last_error = Some(err);
            }
        }
    }
    set_native_runtime(&runtime, None);
}

#[derive(Debug, Clone, PartialEq, Default)]
struct SourceProbeResult {
    stream_spec: Option<PcmStreamSpec>,
    bits_per_sample: Option<u32>,
    first_packet_frames: Option<usize>,
    duration_s: Option<f64>,
    source_summary: Option<String>,
    supports_seek: bool,
}

fn probe_loaded_source(source: &NativeTransportSource) -> Result<SourceProbeResult, String> {
    match source {
        NativeTransportSource::TidalDirectMedia { url, .. } => probe_direct_media_source(url),
        NativeTransportSource::TidalMpd { manifest_uri, .. } => inspect_mpd_source(manifest_uri),
    }
}

fn source_probe_hint(source: &NativeTransportSource) -> Option<&'static str> {
    match source {
        NativeTransportSource::TidalDirectMedia { url, .. } => direct_locator_probe_hint(url),
        NativeTransportSource::TidalMpd { .. } => Some("mp4"),
    }
}

fn direct_locator_probe_hint(locator: &str) -> Option<&'static str> {
    let name = locator
        .split('?')
        .next()
        .unwrap_or(locator)
        .rsplit('/')
        .next()
        .unwrap_or(locator)
        .to_ascii_lowercase();
    if name.ends_with(".flac") {
        Some("flac")
    } else if name.ends_with(".m4a") || name.ends_with(".mp4") || name.ends_with(".m4s") {
        Some("mp4")
    } else if name.ends_with(".aac") {
        Some("aac")
    } else if name.ends_with(".wav") {
        Some("wav")
    } else {
        None
    }
}

fn decode_direct_audio_stream(
    stop: &Arc<AtomicBool>,
    source: &NativeTransportSource,
    snapshot: &Arc<Mutex<NativeTransportSnapshot>>,
    events: &Arc<Mutex<VecDeque<(i32, String)>>>,
    output_config: Option<UsbRawSinkConfig>,
    runtime: &Arc<Mutex<Option<NativeUsbRuntime>>>,
    generation: u64,
    seek_start_ms: Option<u64>,
    volume: SharedVolume,
    spectrum_tx: crossbeam_channel::Sender<SpectrumFrame>,
    spectrum_bands: Arc<AtomicU32>,
    lufs_values: SharedLufsValues,
    session_slot: &SharedSessionSlot,
    hw_vol_cache: &HwVolCache,
    pre_claimed_handle: Option<OpenUsbDevice>,
    auto_start: &Arc<AtomicBool>,
    reuse_session: Option<UsbAudioSink>,
    dsp_config: Option<crate::dsp::DspGraphConfig>,
    dsp_config_slot: super::native_dsp::SharedDspConfig,
) -> Result<(), String> {
    let mss = open_source_as_media_source_stream(source, stop)?;
    let mut hint = Hint::new();
    if let Some(extension) = source_probe_hint(source) {
        hint.with_extension(extension);
    }
    let probe = symphonia::default::get_probe()
        .format(
            &hint,
            mss,
            &FormatOptions::default(),
            &MetadataOptions::default(),
        )
        .map_err(|e| format!("native transport: decode open failed: {e}"))?;
    let mut format = probe.format;
    let track = format
        .default_track()
        .filter(|track| track.codec_params.codec != CODEC_TYPE_NULL)
        .cloned()
        .ok_or_else(|| "native transport: no decodable audio track found".to_string())?;
    let track_id = track.id;
    let mut decoder = symphonia::default::get_codecs()
        .make(&track.codec_params, &DecoderOptions::default())
        .map_err(|e| format!("native transport: decoder init failed: {e}"))?;
    let mpd_probe_info = if let NativeTransportSource::TidalMpd { manifest_uri, .. } = source {
        read_locator_to_string(manifest_uri)
            .ok()
            .and_then(|xml| inspect_mpd_manifest(&xml).ok())
    } else {
        None
    };

    // Populate snapshot with stream info discovered from the Symphonia probe.
    // This is especially important for eager-decode (Load-time) workers so the
    // UI gets duration/spec before Play is pressed, replacing the old separate
    // HTTP probe connection.
    {
        if let Ok(mut state) = snapshot.lock() {
            if state.generation == generation {
                state.stream_spec = track.codec_params.channels.map(|ch| {
                    let format = track
                        .codec_params
                        .bits_per_sample
                        .map(bits_per_sample_to_pcm_format)
                        .unwrap_or(PcmSampleFormat::F32LE);
                    PcmStreamSpec {
                        sample_rate: track.codec_params.sample_rate.unwrap_or(0),
                        channels: ch.count(),
                        format,
                    }
                });
                state.bits_per_sample = track.codec_params.bits_per_sample;
                state.duration_s = track
                    .codec_params
                    .n_frames
                    .filter(|n| *n > 0)
                    .and_then(|n| {
                        let rate = track.codec_params.sample_rate.unwrap_or(0) as f64;
                        if rate > 0.0 {
                            Some(n as f64 / rate)
                        } else {
                            None
                        }
                    })
                    .or_else(|| {
                        mpd_probe_info
                            .as_ref()
                            .and_then(|info| info.total_duration_s())
                    });
                if let Some(info) = mpd_probe_info.as_ref() {
                    state.source_summary = Some(format_mpd_source_summary(info));
                }
                let plan_supports_seek = state.supports_seek;
                state.supports_seek = plan_supports_seek;
                if state.state == NativeTransportState::Loading {
                    state.state = NativeTransportState::Ready;
                    queue_native_event(
                        events,
                        crate::EVT_STATE,
                        format!(
                            "native-transport ready (from decode worker) rate={} ch={} bits={}",
                            track.codec_params.sample_rate.unwrap_or(0),
                            track.codec_params.channels.map(|c| c.count()).unwrap_or(0),
                            track.codec_params.bits_per_sample.unwrap_or(0),
                        ),
                    );
                }
            }
        }
    }

    // Emit a TAG event so the Python UI can display tech info (codec,
    // sample rate, bit depth) in the playback bar.
    {
        let codec_name = codec_label(track.codec_params.codec);
        let sr = track.codec_params.sample_rate.unwrap_or(0);
        let bps = track.codec_params.bits_per_sample.unwrap_or(0);
        let mut tag_parts: Vec<String> = Vec::new();
        tag_parts.push(format!("codec={codec_name}"));
        if sr > 0 {
            tag_parts.push(format!("source_rate={sr}"));
            tag_parts.push(format!("rate={sr}"));
        }
        if bps > 0 {
            tag_parts.push(format!("source_depth={bps}"));
            tag_parts.push(format!("depth={bps}"));
        }
        queue_native_event(events, crate::EVT_TAG, tag_parts.join(";"));
    }

    // Seek to the requested position.
    // Try Symphonia seek first (works for seekable sources like local files).
    // Fall back to packet-skip for non-seekable sources (HTTP streams).
    let skip_until_ts: Option<u64> = if let Some(ms) = seek_start_ms {
        let rate = track.codec_params.sample_rate.unwrap_or(44100);
        let ts = (ms as f64 / 1000.0 * rate as f64) as u64;
        match format.seek(SeekMode::Accurate, SeekTo::TimeStamp { ts, track_id }) {
            Ok(_seeked) => {
                decoder.reset();
                None // seek succeeded, no packet-skip needed
            }
            Err(_) => Some(ts), // fall back to packet-skip
        }
    } else {
        None
    };

    let mut processor_chain = PcmProcessorChain::new();
    // Diagnostic: HIRESTI_DISABLE_PROCESSOR_CHAIN=1 produces a passthrough
    // chain identical to oxidac's bit-perfect path (no DSP, no software
    // volume, no spectrum FFT, no LUFS).  Used to isolate whether clicks
    // observed under matching conditions on oxidac arise from the chain
    // (CPU work on the decode worker, FFT allocations, volume rounding)
    // rather than from the USB / DAC side.
    let disable_chain = std::env::var("HIRESTI_DISABLE_PROCESSOR_CHAIN")
        .ok()
        .map(|v| {
            let s = v.trim().to_ascii_lowercase();
            !s.is_empty() && s != "0" && s != "false" && s != "off"
        })
        .unwrap_or(false);
    if disable_chain {
        eprintln!(
            "[native-transport] HIRESTI_DISABLE_PROCESSOR_CHAIN=1 — chain bypassed \
             (no DSP / volume / spectrum / LUFS)"
        );
        let _ = (&volume, &spectrum_tx, &spectrum_bands, &lufs_values, &dsp_config);
    } else {
        // Always insert DspPcmProcessor so DSP can be hot-enabled/disabled mid-track.
        let init_cfg = dsp_config.as_ref().cloned().unwrap_or_default();
        eprintln!(
            "[native-transport] inserting DspPcmProcessor (active={})",
            init_cfg.has_active_processing()
        );
        processor_chain.push(Box::new(super::native_dsp::DspPcmProcessor::new(
            &init_cfg,
            Some(Arc::clone(&dsp_config_slot)),
        )));
        processor_chain.push(Box::new(VolumePcmProcessor::new(volume)));
        processor_chain.push(Box::new(SpectrumPcmProcessor::new(
            spectrum_tx,
            spectrum_bands,
        )));
        processor_chain.push(Box::new(LufsPcmProcessor::new(lufs_values)));
    }
    let mut chain_configured = false;
    let mut output_session: Option<UsbAudioSink> = None;
    let mut reuse_sess = reuse_session;
    let mut pre_handle = pre_claimed_handle;
    let mut reuse_buf: Vec<u8> = Vec::new();
    // Counter-snapshot polling thread: runs on its own non-RT thread, reads
    // only `Arc<RingState>` atomics, no Mutex.  Spawned the first time a USB
    // session is created so we get visibility into xruns/jitter/pkt_errs
    // without adding any work to the decode worker or libusb event thread.
    //
    // The snapshot thread MUST NOT share the worker's `stop` signal: that
    // signal is checked in the worker's exit path (controller.rs:1387) to
    // distinguish "natural EOS, set decode_completed=true and emit EOS"
    // from "user-requested stop, skip EOS".  Setting it from the snapshot
    // teardown clobbers that distinction and breaks auto-advance to the
    // next track.  Use a private `AtomicBool` instead.
    let mut snapshot_join: Option<thread::JoinHandle<()>> = None;
    let snapshot_stop: Arc<AtomicBool> = Arc::new(AtomicBool::new(false));
    // Scratch buffer used to zero-pad stereo (or N-channel) source data
    // out to the device channel count when the DAC has no matching alt
    // setting (e.g., MOTU 4-channel-only audio interfaces fed Tidal
    // stereo).  Reused across iterations to avoid per-packet allocation.
    let mut channel_pad_buf: Vec<u8> = Vec::new();
    let mut channel_pad_logged = false;
    let mut seeking = skip_until_ts.is_some();
    // Bitrate estimation: accumulate compressed bytes and sample count.
    // First two emissions happen quickly (~0.25s apart) so the Python
    // stabilization logic (needs 2 consecutive ±40% readings) can display
    // the value within ~0.5s.  After that, emit every ~2s.
    let stream_rate = track.codec_params.sample_rate.unwrap_or(44100) as u64;
    let mut src_bytes_accum: u64 = 0;
    let mut src_samples_accum: u64 = 0;
    let mut bitrate_emissions: u32 = 0;

    // Stage-timing telemetry: each loop iteration measures next_packet
    // (network/HTTP read), decode (CPU), processor_chain (DSP), and
    // push_slab (queue back-pressure).  Iterations slower than this
    // threshold print a breakdown so we can pinpoint stall causes from
    // user logs without needing a tracer.
    //
    // The threshold scales with packet duration so steady-state backpressure
    // (decoder paced to playback rate, push_ms ≈ pkt_dur_ms) doesn't get
    // flagged.  Only iterations that take materially longer than the audio
    // they produced are interesting.
    const SLOW_ITER_FLOOR_MS: u128 = 50;
    const SLOW_ITER_PKT_DUR_MULT: u128 = 2;
    let mut slow_iter_count: u64 = 0;
    let result = (|| -> Result<(), String> {
        loop {
            if stop.load(Ordering::Acquire) || !snapshot_generation_matches(snapshot, generation) {
                return Ok(());
            }
            let iter_start = Instant::now();
            let read_start = iter_start;
            let packet = match format.next_packet() {
                Ok(packet) => packet,
                Err(SymphoniaError::IoError(err))
                    if err.kind() == std::io::ErrorKind::UnexpectedEof =>
                {
                    return Ok(());
                }
                Err(err) => return Err(format!("native transport: packet read failed: {err}")),
            };
            let read_ms = read_start.elapsed().as_millis();
            if packet.track_id() != track_id {
                continue;
            }
            // Packet-skip seek: discard packets until we reach the target timestamp.
            if seeking {
                if let Some(target_ts) = skip_until_ts {
                    let pkt_ts = packet.ts();
                    let pkt_dur = packet.dur();
                    if pkt_ts + pkt_dur < target_ts {
                        // Still before target — skip without decoding.
                        continue;
                    }
                }
                seeking = false;
                decoder.reset();
            }
            // Track compressed packet size for bitrate estimation.
            let pkt_compressed_bytes = packet.buf().len() as u64;
            let pkt_dur_samples = packet.dur();
            let decode_start = Instant::now();
            let decoded = decoder
                .decode(&packet)
                .map_err(|e| format!("native transport: decode failed: {e}"))?;
            let decode_ms = decode_start.elapsed().as_millis();
            src_bytes_accum += pkt_compressed_bytes;
            src_samples_accum += pkt_dur_samples;
            // First 2 emissions at ~0.25s for fast UI display, then every ~2s.
            let interval = if bitrate_emissions < 2 {
                stream_rate / 4
            } else {
                stream_rate * 2
            };
            if src_samples_accum >= interval {
                let bitrate_bps = src_bytes_accum * 8 * stream_rate / src_samples_accum;
                queue_native_event(events, crate::EVT_TAG, format!("bitrate={bitrate_bps}"));
                src_bytes_accum = 0;
                src_samples_accum = 0;
                bitrate_emissions += 1;
            }
            // Bit-perfect: keep the decoded slab in the source's native PCM
            // format whenever the device has an alt-setting at that depth, so
            // no width promotion happens (16-bit FLAC stays S16LE on the
            // wire, etc.).  When the device only exposes wider alts (e.g.
            // Topping Monitor 09 is 32-bit-only), promote to the device's
            // chosen `cfg.bit_depth` so slab stride matches what the alt
            // expects — feeding S16LE bytes into a 32-bit alt re-aligns
            // every frame and produces white noise.
            //
            // Lossy codecs (AAC, MP3) leave `bits_per_sample` unset because
            // they decode to internal f32. We let the slab stay F32LE through
            // the processor chain (so the spectrum/LUFS analyzers see correct
            // float samples) and convert to wire format right before USB push.
            let target_format = if let Some(ref cfg) = output_config {
                track.codec_params.bits_per_sample.map(|src_bits| {
                    let target = pick_target_bit_depth(
                        src_bits as u8,
                        &cfg.supported_bit_depths,
                        cfg.bit_depth,
                    );
                    if target == cfg.bit_depth {
                        // Device-pref path: honor the alt's exact subframe
                        // layout (S24_3LE vs S24LE etc.) via cfg.gst_format.
                        pcm_format_from_gst_format(&cfg.gst_format)
                            .unwrap_or_else(|_| bits_per_sample_to_pcm_format(target as u32))
                    } else {
                        // Pass-through path: canonical layout for that depth.
                        bits_per_sample_to_pcm_format(target as u32)
                    }
                })
            } else {
                track
                    .codec_params
                    .bits_per_sample
                    .map(bits_per_sample_to_pcm_format)
            };
            let process_start = Instant::now();
            let mut slab = audio_buffer_ref_to_slab(decoded, target_format, &mut reuse_buf)?;
            if !chain_configured {
                processor_chain.configure(&slab.spec)?;
                chain_configured = true;
            }
            slab = processor_chain.process(slab)?;
            let process_ms = process_start.elapsed().as_millis();
            // Lossy decoders (AAC, MP3) leave the slab in F32LE so the
            // spectrum/LUFS analyzers see correct float samples. Convert to
            // the device's wire format here, after the chain, so the USB
            // ring stride matches what the alt-setting expects (otherwise
            // the float bytes get re-aligned every frame → white noise).
            if let Some(ref cfg) = output_config {
                if let Ok(wire_format) = pcm_format_from_gst_format(&cfg.gst_format) {
                    if slab.spec.format != wire_format {
                        slab = convert_slab_to_wire_format(slab, wire_format)?;
                    }
                }
            }
            record_decoded_slab(snapshot, generation, &slab);
            if let Some(ref cfg) = output_config {
                let src_ch = slab.spec.channels;
                let dst_ch = cfg.channels as usize;
                if src_ch > dst_ch {
                    // Downmix is not supported in this path — refuse loudly
                    // rather than silently dropping rear channels.
                    return Err(format!(
                        "native transport: channel mismatch decoded={} configured={} (downmix unsupported)",
                        src_ch, dst_ch
                    ));
                }
                if output_session.is_none() {
                    let session = if let Some(mut old) = reuse_sess.take() {
                        let old_rate = old.actual_rate;
                        // The slab's format already reflects the device-aware
                        // target bit depth (see target_format above) — pass
                        // it straight to prepare_for_reuse so the alt-setting
                        // and ring stride match. Using cfg.bit_depth here
                        // would freeze us at the Auto-pick depth and miss
                        // per-track changes (24→16 on a 24-bit-capable DAC).
                        let source_bit_depth = pcm_format_to_bit_depth(slab.spec.format);
                        if old_rate == slab.spec.sample_rate {
                            eprintln!(
                                "native-transport: reusing USB session (same rate={} src_bits={})",
                                old_rate, source_bit_depth
                            );
                        } else {
                            eprintln!(
                                "native-transport: rate change {}→{}, reconfiguring live USB session (src_bits={})",
                                old_rate, slab.spec.sample_rate, source_bit_depth
                            );
                        }
                        match old.prepare_for_reuse(slab.spec.sample_rate, source_bit_depth) {
                            Ok(()) => {
                                let clock_mode = configure_session_feed(&old, cfg);
                                queue_native_event(
                                    events,
                                    crate::EVT_STATE,
                                    format!(
                                        "native-transport usb-reused rate={} previous_rate={} device={} clock_mode={:?}",
                                        old.actual_rate, old_rate, cfg.device_id, clock_mode
                                    ),
                                );
                                old
                            }
                            Err(err) => {
                                eprintln!(
                                    "native-transport: live USB reconfigure {}→{} failed: {}; reopening",
                                    old_rate, slab.spec.sample_rate, err
                                );
                                drop(old);
                                let (s, _runtime_info) = open_native_usb_output(
                                    cfg,
                                    &slab.spec,
                                    events,
                                    pre_handle.take(),
                                )?;
                                s
                            }
                        }
                    } else {
                        let (s, _runtime_info) =
                            open_native_usb_output(cfg, &slab.spec, events, pre_handle.take())?;
                        s
                    };
                    // Restore cached hardware volume values.
                    restore_hw_vol_cache(&session, hw_vol_cache);
                    // Build runtime info for the (possibly reused) session.
                    let runtime_info = NativeUsbRuntime {
                        feed: Arc::clone(&session.feed),
                        bit_depth: cfg.bit_depth,
                        device_name: session.device_name(),
                        hw_volume_supported: session.has_hw_volume(),
                        hw_volume_channels: session.hw_volume_channels(),
                        control_device: session.control_device(),
                    };
                    set_native_runtime(runtime, Some(runtime_info));
                    output_session = Some(session);
                    // Notify Python layer that USB audio is configured so
                    // the hw-volume UI can sync with the actual DAC state.
                    queue_native_event(events, crate::EVT_STATE, "usb-audio configured");
                    // v2-poll snapshot: opt-in via HIRESTI_V2_POLL=1 so
                    // the once-per-second telemetry line doesn't drown out
                    // segment-open and HTTP-version diagnostics during
                    // network-layer debugging.  Set the env var to bring
                    // the line back when investigating drift / xruns.
                    let v2_poll_enabled = std::env::var("HIRESTI_V2_POLL")
                        .ok()
                        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
                        .unwrap_or(false);
                    if v2_poll_enabled && snapshot_join.is_none() {
                        let snap_state =
                            Arc::clone(&output_session.as_ref().unwrap().state);
                        let snap_stop = Arc::clone(&snapshot_stop);
                        snapshot_join = thread::Builder::new()
                            .name("native-transport-snapshot".to_string())
                            .spawn(move || {
                                while !snap_stop.load(Ordering::Acquire) {
                                    thread::sleep(std::time::Duration::from_secs(1));
                                    if snap_stop.load(Ordering::Acquire) {
                                        break;
                                    }
                                    eprintln!(
                                        "native-transport: {}",
                                        UsbAudioSink::snapshot_from_state(&snap_state)
                                    );
                                }
                            })
                            .ok();
                    }
                }
                // Zero-pad upmix: when the device has more channels than
                // the source (e.g., MOTU 4-channel-only interface, stereo
                // Tidal track), interleave silence into the trailing
                // channels so frames stay aligned and the front L/R pair
                // carries the original signal.
                let push_data: &[u8] = if src_ch < dst_ch {
                    let bytes_per_sample = match cfg.gst_format.as_str() {
                        "S16LE" | "S16BE" | "U16LE" | "U16BE" => 2usize,
                        "S24_3LE" | "S24_3BE" => 3usize,
                        _ => 4usize,
                    };
                    let src_frame_bytes = src_ch * bytes_per_sample;
                    let dst_frame_bytes = dst_ch * bytes_per_sample;
                    let n_frames = slab.data.len() / src_frame_bytes.max(1);
                    channel_pad_buf.clear();
                    channel_pad_buf.resize(n_frames * dst_frame_bytes, 0);
                    for f in 0..n_frames {
                        let s_off = f * src_frame_bytes;
                        let d_off = f * dst_frame_bytes;
                        channel_pad_buf[d_off..d_off + src_frame_bytes]
                            .copy_from_slice(&slab.data[s_off..s_off + src_frame_bytes]);
                    }
                    if !channel_pad_logged {
                        eprintln!(
                            "native-transport: channel zero-pad active src_ch={} -> dst_ch={} \
                             bytes_per_sample={} (front {} channels carry the source signal, \
                             trailing {} channels are silence)",
                            src_ch,
                            dst_ch,
                            bytes_per_sample,
                            src_ch,
                            dst_ch - src_ch,
                        );
                        queue_native_event(
                            events,
                            crate::EVT_STATE,
                            format!(
                                "native-transport channel-pad src={} dst={}",
                                src_ch, dst_ch
                            ),
                        );
                        channel_pad_logged = true;
                    }
                    &channel_pad_buf
                } else {
                    &slab.data
                };

                let push_start = Instant::now();
                push_slab_to_usb_output(
                    output_session
                        .as_mut()
                        .expect("output session just created"),
                    cfg,
                    slab.spec.sample_rate,
                    push_data,
                    events,
                    auto_start,
                    stop,
                )?;
                if stop.load(Ordering::Acquire) {
                    return Ok(());
                }
                let push_ms = push_start.elapsed().as_millis();
                let total_ms = iter_start.elapsed().as_millis();
                let pkt_dur_ms = if slab.spec.sample_rate > 0 {
                    (pkt_dur_samples as u128 * 1000) / slab.spec.sample_rate as u128
                } else {
                    0
                };
                let slow_threshold_ms = SLOW_ITER_FLOOR_MS
                    .max(pkt_dur_ms.saturating_mul(SLOW_ITER_PKT_DUR_MULT));
                if total_ms > slow_threshold_ms {
                    slow_iter_count = slow_iter_count.saturating_add(1);
                    // Throttle: log first 8, then every 64th to keep noise bounded
                    // during sustained stalls without losing the steady-state count.
                    if slow_iter_count <= 8 || slow_iter_count % 64 == 0 {
                        eprintln!(
                            "native-transport: slow decode iter #{} total={}ms \
                             read={}ms decode={}ms process={}ms push={}ms \
                             pkt_bytes={} pkt_samples={}",
                            slow_iter_count,
                            total_ms,
                            read_ms,
                            decode_ms,
                            process_ms,
                            push_ms,
                            pkt_compressed_bytes,
                            pkt_dur_samples,
                        );
                    }
                }
            }
            // Reclaim the data buffer for reuse in next iteration.
            reuse_buf = slab.data;
        }
    })();

    // Stop the snapshot polling thread (non-RT diagnostic) before parking
    // the session.  Use the snapshot's *private* stop signal — sharing the
    // worker's `stop` signal here would be observed by the worker-exit path
    // at controller.rs:1387 as "user-requested stop", suppressing the
    // `decode_completed = true` write that the lib.rs EOS detector polls
    // for, breaking auto-advance to the next track.
    if let Some(handle) = snapshot_join.take() {
        snapshot_stop.store(true, Ordering::Release);
        let _ = handle.join();
    }

    // Park the USB session in the shared slot so the transport_worker can
    // keep the interface claimed between track switches.
    // Prefer the active output_session; fall back to the unused reuse_sess
    // (happens when decode fails before the first slab opens a session).
    let session_to_park = output_session.take().or(reuse_sess.take());
    if let Some(session) = session_to_park {
        if let Ok(mut slot) = session_slot.lock() {
            *slot = Some(session);
        }
    }

    result
}

/// Apply cached hardware volume values to a newly opened USB session.
fn restore_hw_vol_cache(session: &UsbAudioSink, cache: &HwVolCache) {
    if !session.has_hw_volume() {
        return;
    }
    let channels = session.hw_volume_channels();
    for (idx, ch_cache) in cache.iter().enumerate() {
        let val = ch_cache.load(Ordering::Relaxed);
        if val == i32::MIN || idx >= channels.len() {
            continue;
        }
        match session.set_hw_volume_ch(idx, val as i16) {
            Ok(()) => eprintln!(
                "native-transport: restored hw-volume ch={} val={}",
                idx, val
            ),
            Err(e) => eprintln!(
                "native-transport: hw-volume restore ch={} failed: {}",
                idx, e
            ),
        }
    }
}

fn open_native_usb_output(
    cfg: &UsbRawSinkConfig,
    stream_spec: &PcmStreamSpec,
    events: &Arc<Mutex<VecDeque<(i32, String)>>>,
    pre_claimed_handle: Option<OpenUsbDevice>,
) -> Result<(UsbAudioSink, NativeUsbRuntime), String> {
    let feed = Arc::new(AlsaHwClockFeed::default());

    // Bit-perfect: pick the alt-setting matching the source's bit depth, not
    // the device's highest available.  cfg.bit_depth was chosen at device-open
    // time from the user's "preferred output format" setting (highest bit
    // depth in Auto mode), which doesn't know the per-track source format —
    // mismatching it here would force the iso ring to read the slab bytes
    // with the wrong stride and produce white noise.
    let source_bit_depth = pcm_format_to_bit_depth(stream_spec.format);

    // Drop the cached preferred_profile when the source bit depth differs
    // from the device-open-time choice — `best_alt_for_profile` scopes to the
    // profile first (channels + format + subframe + bit_depth) and only
    // falls back to a fresh search when *no* candidate matches the profile.
    // A 16-bit source with a 24-bit-packed cached profile would still match
    // the 24-bit alt and ignore our bit_depth override, putting us back in
    // the noise-on-format-mismatch state.
    let preferred_profile = if source_bit_depth == cfg.bit_depth {
        Some(cfg.alt_profile)
    } else {
        None
    };

    // If we have a pre-claimed handle, use it directly — the interface is
    // already claimed so configure() will just set alt-setting + rate.
    if let Some(handle) = pre_claimed_handle {
        eprintln!(
            "native-transport: opening USB output with pre-claimed handle (rate={} src_bits={} cfg_bits={})",
            stream_spec.sample_rate, source_bit_depth, cfg.bit_depth
        );
        let session = UsbAudioSink::open_with_handle(
            handle,
            stream_spec.sample_rate,
            source_bit_depth,
            Arc::clone(&feed),
            preferred_profile,
            QueueMode::Bytes,
        )?;
        let pps = session.state.packets_per_sec as usize;
        let n_pkts = (usb_audio::transfer::N_PACKETS_TARGET_MS * pps / 1000).max(8);
        let ring_buf_ns =
            (usb_audio::transfer::N_TRANSFERS * n_pkts) as u64 * 1_000_000_000 / pps as u64;
        let clock_mode = match cfg.clock_mode {
            1 => ClockMode::Pull,
            _ => ClockMode::Push,
        };
        let buf_ns = if clock_mode == ClockMode::Pull {
            0
        } else {
            ring_buf_ns
        };
        session.feed.set_buffer_depth_ns(buf_ns);
        session.feed.set_mode(clock_mode);
        queue_native_event(
            events,
            crate::EVT_STATE,
            format!(
                "native-transport usb-opened rate={} device={} clock_mode={:?} (pre-claimed)",
                session.actual_rate, cfg.device_id, clock_mode
            ),
        );
        let runtime = NativeUsbRuntime {
            feed: Arc::clone(&session.feed),
            bit_depth: cfg.bit_depth,
            device_name: session.device_name(),
            hw_volume_supported: session.has_hw_volume(),
            hw_volume_channels: session.hw_volume_channels(),
            control_device: session.control_device(),
        };
        return Ok((session, runtime));
    }

    // No pre-claimed handle — open from scratch with retries.
    // Retry up to 3 times with increasing delays — some DACs need PLL settle
    // time after kernel driver detach before accepting rate changes.
    const MAX_RETRIES: u32 = 3;
    const RETRY_DELAYS_MS: [u64; 3] = [300, 500, 1000];
    let mut last_err = String::new();
    let mut session_result: Option<UsbAudioSink> = None;
    for attempt in 0..MAX_RETRIES {
        match UsbAudioSink::open_with_feed_mode(
            &cfg.device_id,
            stream_spec.sample_rate,
            source_bit_depth,
            Arc::clone(&feed),
            None,
            preferred_profile,
            QueueMode::Bytes,
        ) {
            Ok(s) => {
                if attempt > 0 {
                    eprintln!("native-transport: USB open succeeded on retry #{}", attempt);
                }
                session_result = Some(s);
                break;
            }
            Err(e) => {
                last_err = e;
                if attempt + 1 < MAX_RETRIES {
                    let delay = RETRY_DELAYS_MS[attempt as usize];
                    eprintln!(
                        "native-transport: USB open failed (attempt {}), retrying in {}ms: {}",
                        attempt + 1,
                        delay,
                        last_err
                    );
                    queue_native_event(
                        events,
                        crate::EVT_STATE,
                        format!(
                            "native-transport rate-setting failed, retrying ({}/{})",
                            attempt + 1,
                            MAX_RETRIES
                        ),
                    );
                    std::thread::sleep(std::time::Duration::from_millis(delay));
                }
            }
        }
    }
    let session = session_result.ok_or_else(|| {
        queue_native_event(
            events,
            crate::EVT_ERROR,
            format!(
                "native-transport USB rate-setting failed after {} retries: {}",
                MAX_RETRIES, last_err
            ),
        );
        format!(
            "native-transport: USB open failed after {} retries: {}",
            MAX_RETRIES, last_err
        )
    })?;
    let pps = session.state.packets_per_sec as usize;
    let n_pkts = (usb_audio::transfer::N_PACKETS_TARGET_MS * pps / 1000).max(8);
    let ring_buf_ns =
        (usb_audio::transfer::N_TRANSFERS * n_pkts) as u64 * 1_000_000_000 / pps as u64;
    let clock_mode = match cfg.clock_mode {
        1 => ClockMode::Pull,
        _ => ClockMode::Push,
    };
    let buf_ns = if clock_mode == ClockMode::Pull {
        0
    } else {
        ring_buf_ns
    };
    session.feed.set_buffer_depth_ns(buf_ns);
    session.feed.set_mode(clock_mode);
    queue_native_event(
        events,
        crate::EVT_STATE,
        format!(
            "native-transport usb-opened rate={} device={} clock_mode={:?}",
            session.actual_rate, cfg.device_id, clock_mode
        ),
    );
    let runtime = NativeUsbRuntime {
        feed: Arc::clone(&session.feed),
        bit_depth: cfg.bit_depth,
        device_name: session.device_name(),
        hw_volume_supported: session.has_hw_volume(),
        hw_volume_channels: session.hw_volume_channels(),
        control_device: session.control_device(),
    };
    Ok((session, runtime))
}

fn configure_session_feed(session: &UsbAudioSink, cfg: &UsbRawSinkConfig) -> ClockMode {
    let pps = session.state.packets_per_sec as usize;
    let n_pkts = (usb_audio::transfer::N_PACKETS_TARGET_MS * pps / 1000).max(8);
    let ring_buf_ns =
        (usb_audio::transfer::N_TRANSFERS * n_pkts) as u64 * 1_000_000_000 / pps as u64;
    let clock_mode = match cfg.clock_mode {
        1 => ClockMode::Pull,
        _ => ClockMode::Push,
    };
    let buf_ns = if clock_mode == ClockMode::Pull {
        0
    } else {
        ring_buf_ns
    };
    session.feed.set_buffer_depth_ns(buf_ns);
    session.feed.set_mode(clock_mode);
    clock_mode
}

fn push_slab_to_usb_output(
    session: &mut UsbAudioSink,
    cfg: &UsbRawSinkConfig,
    sample_rate: u32,
    data: &[u8],
    events: &Arc<Mutex<VecDeque<(i32, String)>>>,
    auto_start: &AtomicBool,
    stop: &Arc<AtomicBool>,
) -> Result<(), String> {
    let mut offset = 0usize;
    while offset < data.len() {
        // After suspend/resume the USB consumer may be wedged (iso transfers
        // never complete because the device dropped during sleep), so the
        // queue stays full and `push_bytes` returns 0 indefinitely.  Without
        // a stop check the worker spins here forever and shutdown / `rac_free`
        // hangs waiting on the join.  Bail out promptly when stop is signalled.
        if stop.load(Ordering::Acquire) {
            return Ok(());
        }
        let written = session.push_bytes(&data[offset..]);
        if written > 0 {
            offset += written;
        } else {
            // Queue full and ring not started — if auto_start was just enabled
            // (by a Play command), start the ring so it drains the queue.
            if !session.is_started() && auto_start.load(Ordering::Acquire) {
                queue_native_event(
                    events,
                    crate::EVT_STATE,
                    format!(
                        "native-transport usb-prefill (queue-full fast-start) queued={}",
                        session.queued_bytes(),
                    ),
                );
                session.ensure_started()?;
                continue; // retry push now that ring is draining
            }
            std::thread::yield_now();
            std::thread::sleep(std::time::Duration::from_micros(250));
        }
    }

    let bytes_per_sample = match cfg.gst_format.as_str() {
        "S16LE" | "S16BE" | "U16LE" | "U16BE" => 2usize,
        "S24_3LE" | "S24_3BE" => 3usize,
        _ => 4usize,
    };
    let target_prefill = (sample_rate as u128
        * cfg.channels as u128
        * bytes_per_sample as u128
        * (usb_audio::transfer::N_TRANSFERS * usb_audio::transfer::N_PACKETS_TARGET_MS * 2) as u128
        / 1000)
        .min(usb_audio::FrameQueue::capacity_bytes() as u128) as usize;

    if !session.is_started()
        && session.queued_bytes() >= target_prefill
        && auto_start.load(Ordering::Acquire)
    {
        queue_native_event(
            events,
            crate::EVT_STATE,
            format!(
                "native-transport usb-prefill queued={} target={}",
                session.queued_bytes(),
                target_prefill
            ),
        );
        session.ensure_started()?;
    } else if session.is_started() {
        // Low watermark monitoring: warn when queue drops below 50ms of audio.
        let low_watermark =
            (sample_rate as usize * cfg.channels as usize * bytes_per_sample * 50) / 1000;
        let queued = session.queued_bytes();
        if queued < low_watermark && queued > 0 {
            queue_native_event(
                events,
                crate::EVT_STATE,
                format!(
                    "native-transport queue-low queued={} watermark={} ({:.0}ms remaining)",
                    queued,
                    low_watermark,
                    queued as f64 * 1000.0
                        / (sample_rate as f64 * cfg.channels as f64 * bytes_per_sample as f64),
                ),
            );
        }
    }

    Ok(())
}

fn record_decoded_slab(
    snapshot: &Arc<Mutex<NativeTransportSnapshot>>,
    generation: u64,
    slab: &PcmSlab,
) {
    if let Ok(mut state) = snapshot.lock() {
        if state.generation != generation {
            return;
        }
        state.decoded_slab_count = state.decoded_slab_count.saturating_add(1);
        state.decoded_frame_count = state.decoded_frame_count.saturating_add(slab.frames as u64);
        state.decoded_byte_count = state
            .decoded_byte_count
            .saturating_add(slab.data.len() as u64);
        state.stream_spec = Some(slab.spec.clone());
    }
}

fn snapshot_generation_matches(
    snapshot: &Arc<Mutex<NativeTransportSnapshot>>,
    generation: u64,
) -> bool {
    snapshot
        .lock()
        .map(|state| state.generation == generation)
        .unwrap_or(false)
}

fn inspect_mpd_source(locator: &str) -> Result<SourceProbeResult, String> {
    let xml = read_locator_to_string(locator)?;
    let info = inspect_mpd_manifest(&xml)?;
    let duration_s = info.total_duration_s();
    Ok(SourceProbeResult {
        source_summary: Some(format_mpd_source_summary(&info)),
        duration_s,
        supports_seek: false,
        ..Default::default()
    })
}

fn format_mpd_source_summary(info: &MpdManifestInfo) -> String {
    let mut parts = vec![format!("mpd representations={}", info.representation_count)];
    let duration_s = info.total_duration_s();
    if let Some(rate) = info.first_audio_sampling_rate {
        parts.push(format!("rate={rate}"));
    }
    if let Some(mime) = info.first_mime_type.as_ref() {
        parts.push(format!("mime={mime}"));
    }
    if let Some(codecs) = info.first_codecs.as_ref() {
        parts.push(format!("codecs={codecs}"));
    }
    if let Some(init) = info.first_initialization.as_ref() {
        parts.push(format!("init={init}"));
    }
    if let Some(media) = info.first_media_template.as_ref() {
        parts.push(format!("media={media}"));
    }
    if let Some(base_url) = info.first_base_url.as_ref() {
        parts.push(format!("base={base_url}"));
    }
    if let Some(count) = info.first_segment_count {
        parts.push(format!("segments={count}"));
    }
    if let Some(d) = duration_s {
        parts.push(format!("duration_s={d:.3}"));
    }
    parts.join(" ")
}

fn probe_direct_media_source(locator: &str) -> Result<SourceProbeResult, String> {
    let mss = open_locator_as_probe_stream(locator)?;
    let mut hint = Hint::new();
    if let Some(extension) = direct_locator_probe_hint(locator) {
        hint.with_extension(extension);
    }
    let probe = symphonia::default::get_probe()
        .format(
            &hint,
            mss,
            &FormatOptions::default(),
            &MetadataOptions::default(),
        )
        .map_err(|e| format!("native transport: audio probe failed: {e}"))?;
    let mut format = probe.format;
    let track = format
        .default_track()
        .filter(|track| track.codec_params.codec != CODEC_TYPE_NULL)
        .cloned()
        .ok_or_else(|| "native transport: no decodable audio track found".to_string())?;
    let track_id = track.id;
    let mut decoder = symphonia::default::get_codecs()
        .make(&track.codec_params, &DecoderOptions::default())
        .map_err(|e| format!("native transport: decoder init failed: {e}"))?;

    let mut stream_spec = track.codec_params.channels.map(|channels| PcmStreamSpec {
        sample_rate: track.codec_params.sample_rate.unwrap_or_default(),
        channels: channels.count(),
        format: bits_per_sample_to_pcm_format(track.codec_params.bits_per_sample.unwrap_or(32)),
    });
    let mut first_packet_frames = None;

    loop {
        match format.next_packet() {
            Ok(packet) => {
                if packet.track_id() != track_id {
                    continue;
                }
                let decoded = decoder
                    .decode(&packet)
                    .map_err(|e| format!("native transport: audio decode probe failed: {e}"))?;
                first_packet_frames = Some(decoded.frames());
                let decoded_spec = decoded.spec();
                stream_spec = Some(PcmStreamSpec {
                    sample_rate: decoded_spec.rate,
                    channels: decoded_spec.channels.count(),
                    format: audio_buffer_ref_format(&decoded),
                });
                break;
            }
            Err(SymphoniaError::IoError(err))
                if err.kind() == std::io::ErrorKind::UnexpectedEof =>
            {
                break;
            }
            Err(err) => return Err(format!("native transport: packet read failed: {err}")),
        }
    }

    let bits_per_sample = track.codec_params.bits_per_sample;
    let duration_s = track.codec_params.n_frames.and_then(|n| {
        let rate = track.codec_params.sample_rate.unwrap_or(0) as f64;
        if rate > 0.0 {
            Some(n as f64 / rate)
        } else {
            None
        }
    });
    let summary = stream_spec.as_ref().map(|spec| {
        format!(
            "direct-audio codec={} rate={} channels={} format={:?} bits={}",
            codec_label(track.codec_params.codec),
            spec.sample_rate,
            spec.channels,
            spec.format,
            bits_per_sample.unwrap_or_default()
        )
    });

    Ok(SourceProbeResult {
        stream_spec,
        bits_per_sample,
        first_packet_frames,
        duration_s,
        source_summary: summary,
        supports_seek: true,
    })
}

fn codec_label(codec: CodecType) -> &'static str {
    match codec {
        CODEC_TYPE_FLAC => "FLAC",
        CODEC_TYPE_AAC => "AAC",
        CODEC_TYPE_ALAC => "ALAC",
        _ => "PCM",
    }
}

/// Pick the on-the-wire bit depth for the current source.
///
/// Prefer pass-through (target = source) when the device has an alt-setting
/// at the source's bit depth.  Otherwise promote to the smallest supported
/// depth ≥ source (e.g. 16-bit FLAC on a 32-bit-only Topping Monitor 09 → 32);
/// if no alt is wider, fall back to the device's default (`cfg.bit_depth`).
///
/// `supported` may be empty for legacy/non-tuned configs — in that case we
/// fall back to `cfg_bit_depth` to match the pre-Monitor-09 behavior.
fn pick_target_bit_depth(source_bit_depth: u8, supported: &[u8], cfg_bit_depth: u8) -> u8 {
    if supported.is_empty() {
        return cfg_bit_depth;
    }
    if supported.contains(&source_bit_depth) {
        return source_bit_depth;
    }
    if let Some(&promoted) = supported.iter().filter(|&&d| d > source_bit_depth).min() {
        return promoted;
    }
    cfg_bit_depth
}

fn audio_buffer_ref_format(buffer: &AudioBufferRef<'_>) -> PcmSampleFormat {
    match buffer {
        AudioBufferRef::S16(_) => PcmSampleFormat::S16LE,
        AudioBufferRef::S24(_) => PcmSampleFormat::S24_3LE,
        AudioBufferRef::S32(_) => PcmSampleFormat::S32LE,
        AudioBufferRef::F32(_) => PcmSampleFormat::F32LE,
        AudioBufferRef::F64(_) => PcmSampleFormat::F64LE,
        AudioBufferRef::U8(_)
        | AudioBufferRef::U16(_)
        | AudioBufferRef::U24(_)
        | AudioBufferRef::U32(_)
        | AudioBufferRef::S8(_) => PcmSampleFormat::S32LE,
    }
}

fn audio_buffer_ref_to_slab(
    buffer: AudioBufferRef<'_>,
    target_format: Option<PcmSampleFormat>,
    reuse_buf: &mut Vec<u8>,
) -> Result<PcmSlab, String> {
    let frames = buffer.frames();
    let output_format = target_format.unwrap_or_else(|| audio_buffer_ref_format(&buffer));
    let spec = PcmStreamSpec {
        sample_rate: buffer.spec().rate,
        channels: buffer.spec().channels.count(),
        format: output_format,
    };
    match output_format {
        PcmSampleFormat::S16LE => match buffer {
            AudioBufferRef::U8(buf) => interleave_into(&buf, 2, reuse_buf, |sample, out| {
                let value: i16 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::U16(buf) => interleave_into(&buf, 2, reuse_buf, |sample, out| {
                let value: i16 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::U24(buf) => interleave_into(&buf, 2, reuse_buf, |sample, out| {
                let value: i16 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::U32(buf) => interleave_into(&buf, 2, reuse_buf, |sample, out| {
                let value: i16 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S8(buf) => interleave_into(&buf, 2, reuse_buf, |sample, out| {
                let value: i16 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S16(buf) => interleave_into(&buf, 2, reuse_buf, |sample, out| {
                out.extend_from_slice(&sample.to_le_bytes());
            }),
            AudioBufferRef::S24(buf) => interleave_into(&buf, 2, reuse_buf, |sample, out| {
                let value: i16 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S32(buf) => interleave_into(&buf, 2, reuse_buf, |sample, out| {
                let value: i16 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::F32(buf) => interleave_into(&buf, 2, reuse_buf, |sample, out| {
                let value: i16 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::F64(buf) => interleave_into(&buf, 2, reuse_buf, |sample, out| {
                let value: i16 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
        },
        // S24_3LE: convert through Symphonia's `i24` so the source value lands
        // in the right magnitude.  Going via `i32` and truncating to the low
        // 3 bytes corrupts every sample whose source bit depth ≠ 24:
        // Symphonia's `i16 → i32` is `(s as i32) << 16`, putting the data in
        // bits 16-31 — `write_i24_le` then writes bytes 0-2 (all zero or
        // sign-junk) and produces white noise on the wire.  `i24` is in
        // 24-bit range (-2^23 .. 2^23-1) regardless of source, so taking its
        // inner i32 directly into the 3-byte LE layout is correct.
        PcmSampleFormat::S24_3LE => match buffer {
            AudioBufferRef::U8(buf) => interleave_into(&buf, 3, reuse_buf, |sample, out| {
                let value: i24 = sample.into_sample();
                write_i24_le(value.inner(), out);
            }),
            AudioBufferRef::U16(buf) => interleave_into(&buf, 3, reuse_buf, |sample, out| {
                let value: i24 = sample.into_sample();
                write_i24_le(value.inner(), out);
            }),
            AudioBufferRef::U24(buf) => interleave_into(&buf, 3, reuse_buf, |sample, out| {
                let value: i24 = sample.into_sample();
                write_i24_le(value.inner(), out);
            }),
            AudioBufferRef::U32(buf) => interleave_into(&buf, 3, reuse_buf, |sample, out| {
                let value: i24 = sample.into_sample();
                write_i24_le(value.inner(), out);
            }),
            AudioBufferRef::S8(buf) => interleave_into(&buf, 3, reuse_buf, |sample, out| {
                let value: i24 = sample.into_sample();
                write_i24_le(value.inner(), out);
            }),
            AudioBufferRef::S16(buf) => interleave_into(&buf, 3, reuse_buf, |sample, out| {
                let value: i24 = sample.into_sample();
                write_i24_le(value.inner(), out);
            }),
            AudioBufferRef::S24(buf) => interleave_into(&buf, 3, reuse_buf, |sample, out| {
                // Already in i24 range — `sample.0` is the inner i32.
                write_i24_le(sample.0, out);
            }),
            AudioBufferRef::S32(buf) => interleave_into(&buf, 3, reuse_buf, |sample, out| {
                let value: i24 = sample.into_sample();
                write_i24_le(value.inner(), out);
            }),
            AudioBufferRef::F32(buf) => interleave_into(&buf, 3, reuse_buf, |sample, out| {
                let value: i24 = sample.into_sample();
                write_i24_le(value.inner(), out);
            }),
            AudioBufferRef::F64(buf) => interleave_into(&buf, 3, reuse_buf, |sample, out| {
                let value: i24 = sample.into_sample();
                write_i24_le(value.inner(), out);
            }),
        },
        PcmSampleFormat::S24LE | PcmSampleFormat::S32LE => match buffer {
            AudioBufferRef::U8(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: i32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::U16(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: i32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::U24(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: i32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::U32(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: i32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S8(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: i32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S16(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: i32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S24(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: i32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S32(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                out.extend_from_slice(&sample.to_le_bytes());
            }),
            AudioBufferRef::F32(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: i32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::F64(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: i32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
        },
        PcmSampleFormat::F32LE => match buffer {
            AudioBufferRef::U8(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: f32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::U16(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: f32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::U24(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: f32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::U32(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: f32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S8(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: f32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S16(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: f32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S24(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: f32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S32(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: f32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::F32(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                out.extend_from_slice(&sample.to_le_bytes());
            }),
            AudioBufferRef::F64(buf) => interleave_into(&buf, 4, reuse_buf, |sample, out| {
                let value: f32 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
        },
        PcmSampleFormat::F64LE => match buffer {
            AudioBufferRef::U8(buf) => interleave_into(&buf, 8, reuse_buf, |sample, out| {
                let value: f64 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::U16(buf) => interleave_into(&buf, 8, reuse_buf, |sample, out| {
                let value: f64 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::U24(buf) => interleave_into(&buf, 8, reuse_buf, |sample, out| {
                let value: f64 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::U32(buf) => interleave_into(&buf, 8, reuse_buf, |sample, out| {
                let value: f64 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S8(buf) => interleave_into(&buf, 8, reuse_buf, |sample, out| {
                let value: f64 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S16(buf) => interleave_into(&buf, 8, reuse_buf, |sample, out| {
                let value: f64 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S24(buf) => interleave_into(&buf, 8, reuse_buf, |sample, out| {
                let value: f64 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::S32(buf) => interleave_into(&buf, 8, reuse_buf, |sample, out| {
                let value: f64 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::F32(buf) => interleave_into(&buf, 8, reuse_buf, |sample, out| {
                let value: f64 = sample.into_sample();
                out.extend_from_slice(&value.to_le_bytes());
            }),
            AudioBufferRef::F64(buf) => interleave_into(&buf, 8, reuse_buf, |sample, out| {
                out.extend_from_slice(&sample.to_le_bytes());
            }),
        },
    };
    // Take ownership of the interleaved data; `reuse_buf` is left empty but retains
    // its allocation so the caller can pass it in again next iteration.
    let data = std::mem::take(reuse_buf);
    Ok(PcmSlab { spec, frames, data })
}

fn interleave_into<T, F>(
    buffer: &AudioBuffer<T>,
    bytes_per_sample: usize,
    out: &mut Vec<u8>,
    mut write_sample: F,
) where
    T: Copy + Sample,
    F: FnMut(T, &mut Vec<u8>),
{
    let frames = buffer.frames();
    let channels = buffer.spec().channels.count();
    out.clear();
    out.reserve(frames * channels * bytes_per_sample);
    for frame_idx in 0..frames {
        for ch in 0..channels {
            let sample = buffer.chan(ch)[frame_idx];
            write_sample(sample, out);
        }
    }
}

/// Convert a slab's PCM payload from `slab.spec.format` to `dst_format` and
/// return a new slab carrying the converted bytes.  Used by the native
/// transport to keep the processor chain in float for lossy-codec sources
/// while still pushing wire-format bytes into the USB ring.
fn convert_slab_to_wire_format(
    mut slab: PcmSlab,
    dst_format: PcmSampleFormat,
) -> Result<PcmSlab, String> {
    if slab.spec.format == dst_format {
        return Ok(slab);
    }
    let src_format = slab.spec.format;
    let src_bytes = bytes_per_sample(src_format);
    let dst_bytes = bytes_per_sample(dst_format);
    let n_samples = slab.data.len() / src_bytes;
    let mut out = Vec::with_capacity(n_samples * dst_bytes);
    for chunk in slab.data.chunks_exact(src_bytes) {
        let v = sample_to_f32(chunk, src_format);
        write_f32_as(v, dst_format, &mut out);
    }
    slab.data = out;
    slab.spec.format = dst_format;
    Ok(slab)
}

/// Download buffer capacity (number of channel slots).  Each slot holds one
/// `reader.read()` worth of bytes — typically 1.5–8 KiB on slow paths,
/// up to 32 KiB on fast ones.  At 256 slots × ~4 KiB average → ~1 MiB
/// runway, enough to absorb the 200–700 ms CDN setup hitches the 96 kHz
/// user has been reporting; brief 5+ second segment-open stalls (also
/// observed) still bottom out the channel, but those need segment-level
/// prefetch on top of buffer size to hide.
const DOWNLOAD_CHANNEL_CAP: usize = 256;
const DOWNLOAD_CHUNK_SIZE: usize = 32 * 1024;

/// Shared isahc HttpClient for all native_transport HTTP calls.
/// isahc wraps libcurl + nghttp2, which gives us HTTP/2 via mature C-layer
/// flow control and connection cache without the tokio-runtime jump that
/// `reqwest::blocking` requires for every body read.  The `reqwest`
/// experiment in 1.9.5 beta2 confirmed h2 negotiation against Tidal CDN
/// and dropped per-segment `setup_ms` from ~160 ms to ~25 ms, but body
/// delivery stalled after ~0.4 s (likely h2 stream-window starvation
/// caused by the single-thread blocking runtime serializing concurrent
/// reads of overlapping segment Responses).  libcurl's `multi` interface
/// has handled exactly this pattern since 2014; nghttp2 manages WINDOW_-
/// UPDATE timing autonomously.
fn http_client() -> &'static isahc::HttpClient {
    static CLIENT: OnceLock<isahc::HttpClient> = OnceLock::new();
    CLIENT.get_or_init(|| {
        use isahc::config::{Configurable, VersionNegotiation};
        isahc::HttpClient::builder()
            .version_negotiation(VersionNegotiation::latest_compatible())
            .connection_cache_size(8)
            .build()
            .expect("native-transport: isahc client build failed")
    })
}

/// A `Read` adapter backed by a crossbeam channel.
/// The I/O thread sends `Vec<u8>` chunks; the decode thread reads from this.
struct ChannelReader {
    rx: crossbeam_channel::Receiver<Vec<u8>>,
    buf: Vec<u8>,
    pos: usize,
}

impl ChannelReader {
    fn new(rx: crossbeam_channel::Receiver<Vec<u8>>) -> Self {
        Self {
            rx,
            buf: Vec::new(),
            pos: 0,
        }
    }
}

impl Read for ChannelReader {
    fn read(&mut self, dst: &mut [u8]) -> std::io::Result<usize> {
        loop {
            // Drain current buffer first.
            if self.pos < self.buf.len() {
                let n = dst.len().min(self.buf.len() - self.pos);
                dst[..n].copy_from_slice(&self.buf[self.pos..self.pos + n]);
                self.pos += n;
                return Ok(n);
            }
            // Fetch next chunk from channel.
            match self.rx.recv() {
                Ok(chunk) => {
                    self.buf = chunk;
                    self.pos = 0;
                    // Empty chunk signals EOF from the I/O thread.
                    if self.buf.is_empty() {
                        return Ok(0);
                    }
                }
                Err(_) => return Ok(0), // Channel closed = EOF.
            }
        }
    }
}

/// Spawn an I/O thread that downloads from `reader` and sends chunks
/// via the returned channel. The `stop` flag requests early termination.
fn spawn_download_thread(
    mut reader: Box<dyn std::io::Read + Send>,
    stop: Arc<AtomicBool>,
) -> crossbeam_channel::Receiver<Vec<u8>> {
    let (tx, rx) = crossbeam_channel::bounded(DOWNLOAD_CHANNEL_CAP);
    eprintln!(
        "native-transport: prefetch thread starting (chunk={} cap={} max~{}KiB)",
        DOWNLOAD_CHUNK_SIZE,
        DOWNLOAD_CHANNEL_CAP,
        DOWNLOAD_CHANNEL_CAP * DOWNLOAD_CHUNK_SIZE / 1024,
    );
    thread::Builder::new()
        .name("native-transport-download".to_string())
        .spawn(move || {
            // Forward each TCP read straight through.  Earlier we batched up
            // to DOWNLOAD_CHUNK_SIZE before sending, intending to grow the
            // effective channel buffer from ~96 KiB (64 × MSS) to ~2 MiB.
            // On a slow CDN that becomes head-of-line blocking: the decoder
            // gets nothing for the 300–600 ms it takes to accumulate 32 KiB
            // and underruns immediately.  On a healthy CDN, reader.read()
            // already returns large blocks (kernel TCP coalescing), so
            // skipping the aggregation costs nothing there but keeps small
            // reads flowing on jittery networks.
            let mut buf = vec![0u8; DOWNLOAD_CHUNK_SIZE];
            loop {
                if stop.load(Ordering::Relaxed) {
                    return;
                }
                match reader.read(&mut buf) {
                    Ok(0) => {
                        let _ = tx.send(Vec::new());
                        return;
                    }
                    Ok(n) => {
                        if tx.send(buf[..n].to_vec()).is_err() {
                            return; // Receiver dropped.
                        }
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                    Err(_) => {
                        let _ = tx.send(Vec::new());
                        return;
                    }
                }
            }
        })
        .expect("native transport: failed to spawn download thread");
    rx
}

/// Extract the host (`host:port` if present) from an http/https locator,
/// returning `None` for file:// / unknown schemes.
fn extract_http_host(locator: &str) -> Option<String> {
    let rest = if let Some(r) = locator.strip_prefix("https://") {
        r
    } else if let Some(r) = locator.strip_prefix("http://") {
        r
    } else {
        return None;
    };
    let host_end = rest
        .find(|c: char| c == '/' || c == '?' || c == '#')
        .unwrap_or(rest.len());
    let host = &rest[..host_end];
    if host.is_empty() {
        None
    } else {
        Some(host.to_string())
    }
}

/// Log each CDN host the native transport touches, once per process.
/// Helps diagnose "why does this player struggle on the same connection
/// other Tidal clients handle fine" by exposing actual edge routing
/// (e.g., Tidal's own `*.audio.tidal.com`, CloudFront-fronted
/// `sp-*-cf.audio.tidal.com`, Akamai, etc.) without leaking the signed
/// query string of any particular segment.
fn log_cdn_host_once(locator: &str) {
    static SEEN: OnceLock<Mutex<HashSet<String>>> = OnceLock::new();
    let Some(host) = extract_http_host(locator) else {
        return;
    };
    let set = SEEN.get_or_init(|| Mutex::new(HashSet::new()));
    if let Ok(mut guard) = set.lock() {
        if guard.insert(host.clone()) {
            eprintln!("native-transport: streaming from CDN host {}", host);
        }
    }
}

/// Log the negotiated HTTP version per (host, version) pair, once each.
/// Confirms whether ALPN actually upgraded to h2 against the Tidal CDN.
fn log_http_version_once(host: &str, version: http::Version) {
    static SEEN: OnceLock<Mutex<HashSet<(String, String)>>> = OnceLock::new();
    let v = format!("{:?}", version);
    let set = SEEN.get_or_init(|| Mutex::new(HashSet::new()));
    if let Ok(mut guard) = set.lock() {
        if guard.insert((host.to_string(), v.clone())) {
            eprintln!("native-transport: negotiated {} to {}", v, host);
        }
    }
}

/// Open a stream for short-lived probing (no download thread).
fn open_locator_as_probe_stream(locator: &str) -> Result<MediaSourceStream, String> {
    let source: Box<dyn MediaSource> = if let Some(path) = file_uri_to_path(locator) {
        Box::new(
            fs::File::open(path).map_err(|e| format!("native transport: file open failed: {e}"))?,
        )
    } else if locator.starts_with("http://") || locator.starts_with("https://") {
        log_cdn_host_once(locator);
        let response = http_client()
            .get(locator)
            .map_err(|e| format!("native transport: HTTP open failed: {e}"))?;
        if !response.status().is_success() {
            return Err(format!(
                "native transport: HTTP error {}",
                response.status()
            ));
        }
        Box::new(ReadOnlySource::new(response.into_body()))
    } else {
        return Err(format!("native transport: unsupported locator '{locator}'"));
    };
    Ok(MediaSourceStream::new(
        source,
        MediaSourceStreamOptions::default(),
    ))
}

fn open_locator_as_media_source_stream(
    locator: &str,
    stop: &Arc<AtomicBool>,
) -> Result<MediaSourceStream, String> {
    let source: Box<dyn MediaSource> = if let Some(path) = file_uri_to_path(locator) {
        // Local files: no I/O thread needed, direct read is fine.
        Box::new(
            fs::File::open(path).map_err(|e| format!("native transport: file open failed: {e}"))?,
        )
    } else if locator.starts_with("http://") || locator.starts_with("https://") {
        log_cdn_host_once(locator);
        let response = http_client()
            .get(locator)
            .map_err(|e| format!("native transport: HTTP open failed: {e}"))?;
        if !response.status().is_success() {
            return Err(format!(
                "native transport: HTTP error {}",
                response.status()
            ));
        }
        let rx = spawn_download_thread(Box::new(response.into_body()), Arc::clone(stop));
        Box::new(ReadOnlySource::new(ChannelReader::new(rx)))
    } else {
        return Err(format!("native transport: unsupported locator '{locator}'"));
    };
    Ok(MediaSourceStream::new(
        source,
        MediaSourceStreamOptions::default(),
    ))
}

fn open_source_as_media_source_stream(
    source: &NativeTransportSource,
    stop: &Arc<AtomicBool>,
) -> Result<MediaSourceStream, String> {
    match source {
        NativeTransportSource::TidalDirectMedia { url, .. } => {
            open_locator_as_media_source_stream(url, stop)
        }
        NativeTransportSource::TidalMpd { manifest_uri, .. } => {
            let xml = read_locator_to_string(manifest_uri)?;
            let info = inspect_mpd_manifest(&xml)?;
            let sequence = build_mpd_segment_sequence(manifest_uri, &info)?;
            // Wrap the serial segment reader in the same background-fetch
            // channel pipeline used for TidalDirectMedia.  Without this,
            // every Symphonia read for a DASH source blocked on the next
            // ureq::get(segment).call() — turning HTTP setup latency and
            // CDN jitter into queue-side underruns once the upfront ring
            // prefill drained (observed at ~160-500ms per ~42ms-of-audio
            // packet on weak Tidal connections, with occasional 5+ second
            // stalls).  A bg thread now drains SegmentSequenceReader into
            // a bounded crossbeam channel (64 × 32KiB ≈ 2MiB ≈ 5-6 s of
            // compressed FLAC), letting the decoder pull from local
            // memory while HTTP work happens in parallel.
            let segment_reader: Box<dyn std::io::Read + Send> =
                Box::new(SegmentSequenceReader::new(sequence));
            let rx = spawn_download_thread(segment_reader, Arc::clone(stop));
            let source: Box<dyn MediaSource> =
                Box::new(ReadOnlySource::new(ChannelReader::new(rx)));
            Ok(MediaSourceStream::new(
                source,
                MediaSourceStreamOptions::default(),
            ))
        }
    }
}

fn read_locator_to_string(locator: &str) -> Result<String, String> {
    let mut text = String::new();
    if let Some(path) = file_uri_to_path(locator) {
        fs::File::open(path)
            .and_then(|mut file| file.read_to_string(&mut text))
            .map_err(|e| format!("native transport: manifest read failed: {e}"))?;
    } else if locator.starts_with("http://") || locator.starts_with("https://") {
        log_cdn_host_once(locator);
        let mut response = http_client()
            .get(locator)
            .map_err(|e| format!("native transport: manifest fetch failed: {e}"))?;
        if !response.status().is_success() {
            return Err(format!(
                "native transport: manifest HTTP error {}",
                response.status()
            ));
        }
        response
            .body_mut()
            .read_to_string(&mut text)
            .map_err(|e| format!("native transport: manifest body read failed: {e}"))?;
    } else {
        return Err(format!(
            "native transport: unsupported manifest locator '{locator}'"
        ));
    }
    Ok(text)
}

fn file_uri_to_path(locator: &str) -> Option<&str> {
    locator.strip_prefix("file://")
}

fn build_mpd_segment_sequence(
    manifest_locator: &str,
    info: &MpdManifestInfo,
) -> Result<Vec<String>, String> {
    let Some(init) = info.first_initialization.as_deref() else {
        if let Some(base_url) = info.first_base_url.as_deref() {
            return Ok(vec![resolve_locator(manifest_locator, base_url)]);
        }
        return Err("native transport: MPD missing initialization template".to_string());
    };
    let Some(media) = info.first_media_template.as_deref() else {
        if let Some(base_url) = info.first_base_url.as_deref() {
            return Ok(vec![resolve_locator(manifest_locator, base_url)]);
        }
        return Err("native transport: MPD missing media template".to_string());
    };
    let rep = info.first_representation_id.as_deref().unwrap_or("0");
    let start_number = info.first_start_number.unwrap_or(1);
    let segment_count = info.first_segment_count.unwrap_or(0);
    let segment_base = info
        .first_base_url
        .as_deref()
        .map(|base| resolve_locator(manifest_locator, base))
        .unwrap_or_else(|| manifest_locator.to_string());
    let mut out = Vec::with_capacity(segment_count.saturating_add(1) as usize);
    out.push(resolve_locator(
        &segment_base,
        &replace_representation_id(init, rep),
    ));
    for idx in 0..segment_count {
        let number = start_number.saturating_add(idx);
        let media_name = replace_representation_id(media, rep);
        let media_name = replace_number_token(&media_name, number)?;
        out.push(resolve_locator(&segment_base, &media_name));
    }
    Ok(out)
}

fn resolve_locator(base: &str, value: &str) -> String {
    if value.starts_with("http://") || value.starts_with("https://") || value.starts_with("file://")
    {
        return value.to_string();
    }
    if let Some(path) = file_uri_to_path(base) {
        let base_path = std::path::Path::new(path);
        let dir = base_path
            .parent()
            .unwrap_or_else(|| std::path::Path::new("/"));
        return format!("file://{}", dir.join(value).display());
    }
    if let Some((prefix, _)) = base.rsplit_once('/') {
        return format!("{prefix}/{value}");
    }
    value.to_string()
}

fn replace_representation_id(template: &str, representation_id: &str) -> String {
    template.replace("$RepresentationID$", representation_id)
}

fn replace_number_token(template: &str, number: u64) -> Result<String, String> {
    if let Some(start) = template.find("$Number") {
        let rest = &template[start + "$Number".len()..];
        if let Some(end) = rest.find('$') {
            let token = &rest[..end];
            let formatted = if token.is_empty() {
                number.to_string()
            } else if let Some(width_text) =
                token.strip_prefix("%0").and_then(|t| t.strip_suffix('d'))
            {
                let width = width_text
                    .parse::<usize>()
                    .map_err(|e| format!("native transport: invalid Number format token: {e}"))?;
                format!("{number:0width$}")
            } else {
                return Err(format!(
                    "native transport: unsupported Number token '${token}$'"
                ));
            };
            let whole = &template[start..start + "$Number".len() + end + 1];
            return Ok(template.replacen(whole, &formatted, 1));
        }
    }
    Ok(template.to_string())
}

/// (setup_ms, total_ms, fully-downloaded body bytes) — what each parallel
/// prefetch worker sends back when it finishes.
type SegmentDownloadResult = std::io::Result<(u128, u128, Vec<u8>)>;

/// One in-flight segment download.  The worker thread is reading the body
/// to a local `Vec<u8>` and will deposit it on `rx` when done — so by the
/// time the consumer pops this entry, the bytes are fully buffered in
/// memory and serving them is just a `Cursor::read`.
struct PendingSegment {
    index: usize,
    rx: crossbeam_channel::Receiver<SegmentDownloadResult>,
}

/// Default parallel prefetch depth.  Tidal CDN tends to deliver each
/// HTTP/2 stream at roughly real-time per stream, so a 1-deep prefetch
/// can never accumulate more than ~1 segment of compressed-FLAC head-room
/// even on a 100 Mbps link.  Opening 4 streams concurrently lets the
/// h2 connection multiplex their bodies — combined throughput becomes
/// link-limited, not per-stream-limited, and the downstream chunk
/// channel actually fills with several seconds of buffered audio that
/// can absorb a 5–10 s network blip without underrunning the decoder.
const PARALLEL_PREFETCH_DEFAULT: usize = 4;

fn parallel_prefetch_depth() -> usize {
    std::env::var("HIRESTI_PREFETCH_DEPTH")
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
        .filter(|&n| (1..=16).contains(&n))
        .unwrap_or(PARALLEL_PREFETCH_DEFAULT)
}

struct SegmentSequenceReader {
    segments: Vec<String>,
    /// Cursor over the in-memory body of the segment currently being
    /// served to the decoder.  None between segments / before the first.
    current_reader: Option<Box<dyn Read + Send + 'static>>,
    /// FIFO of in-flight segment downloads.  Each entry is a worker
    /// thread reading the full body into memory; HTTP/2 multiplexes the
    /// streams over a single TCP connection.
    pending: VecDeque<PendingSegment>,
    /// Index of the next segment to dispatch a worker for.
    next_to_schedule: usize,
    /// Configured parallelism (cached at construction so env override
    /// is read once).
    prefetch_depth: usize,
    bytes_in_current: u64,
    last_setup_ms: u128,
}

impl SegmentSequenceReader {
    fn new(segments: Vec<String>) -> Self {
        let depth = parallel_prefetch_depth();
        eprintln!(
            "native-transport: SegmentSequenceReader segments={} parallel_prefetch={}",
            segments.len(),
            depth,
        );
        Self {
            segments,
            current_reader: None,
            pending: VecDeque::with_capacity(depth),
            next_to_schedule: 0,
            prefetch_depth: depth,
            bytes_in_current: 0,
            last_setup_ms: 0,
        }
    }

    /// Top up the in-flight worker pool to `prefetch_depth` while there
    /// are still un-dispatched segments.  Cheap when nothing changes.
    fn maintain_pending(&mut self) {
        while self.pending.len() < self.prefetch_depth
            && self.next_to_schedule < self.segments.len()
        {
            let idx = self.next_to_schedule;
            self.next_to_schedule += 1;
            self.spawn_prefetch(idx);
        }
    }

    fn spawn_prefetch(&mut self, idx: usize) {
        let locator = self.segments[idx].clone();
        let total = self.segments.len();
        let (tx, rx) = crossbeam_channel::bounded(1);
        thread::Builder::new()
            .name(format!("native-transport-prefetch-{}", idx + 1))
            .spawn(move || {
                let started = Instant::now();
                let result = (|| -> std::io::Result<(u128, u128, Vec<u8>)> {
                    let mut reader = open_segment_reader(&locator)?;
                    let setup_ms = started.elapsed().as_millis();
                    let mut buf = Vec::with_capacity(1_500_000);
                    reader.read_to_end(&mut buf)?;
                    let total_ms = started.elapsed().as_millis();
                    Ok((setup_ms, total_ms, buf))
                })();
                if let Err(ref e) = result {
                    eprintln!(
                        "native-transport: segment #{}/{} prefetch failed err={}",
                        idx + 1,
                        total,
                        e
                    );
                }
                let _ = tx.send(result);
            })
            .ok();
        self.pending.push_back(PendingSegment { index: idx, rx });
    }

    fn ensure_reader(&mut self) -> Result<bool, std::io::Error> {
        while self.current_reader.is_none() {
            // Top up worker pool first so the parallelism budget is full
            // by the time we wait on the next segment.
            self.maintain_pending();

            let Some(pending) = self.pending.pop_front() else {
                // No more segments scheduled and none in flight → EOS.
                return Ok(false);
            };

            let wait_start = Instant::now();
            let result = pending.rx.recv().map_err(|_| {
                std::io::Error::new(
                    std::io::ErrorKind::Other,
                    "segment prefetch worker dropped before producing bytes",
                )
            })?;
            let (setup_ms, total_ms, body) = result?;
            let wait_ms = wait_start.elapsed().as_millis();
            // wait_ms ≈ 0 → worker finished ahead of demand (good).
            // wait_ms ≈ total_ms → consumer outran the worker pool;
            // bump HIRESTI_PREFETCH_DEPTH or accept network is slower
            // than playback.
            eprintln!(
                "native-transport: segment #{}/{} ready setup={}ms total={}ms (consumer wait={}ms) body_bytes={} prev_bytes={} pending_after_pop={}",
                pending.index + 1,
                self.segments.len(),
                setup_ms,
                total_ms,
                wait_ms,
                body.len(),
                self.bytes_in_current,
                self.pending.len(),
            );

            self.bytes_in_current = 0;
            self.last_setup_ms = setup_ms;
            self.current_reader = Some(Box::new(Cursor::new(body)));

            // Pop drained one slot — schedule the replacement before we
            // return so workers stay saturated even during short reads.
            self.maintain_pending();
        }
        Ok(true)
    }
}

impl Read for SegmentSequenceReader {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        loop {
            if !self.ensure_reader()? {
                return Ok(0);
            }
            let Some(reader) = self.current_reader.as_mut() else {
                continue;
            };
            let n = reader.read(buf)?;
            if n > 0 {
                self.bytes_in_current = self.bytes_in_current.saturating_add(n as u64);
                return Ok(n);
            }
            self.current_reader = None;
        }
    }
}

impl Seek for SegmentSequenceReader {
    fn seek(&mut self, _pos: SeekFrom) -> std::io::Result<u64> {
        Err(std::io::Error::new(
            std::io::ErrorKind::Other,
            "segment sequence does not support seeking",
        ))
    }
}

fn open_segment_reader(
    locator: &str,
) -> Result<Box<dyn Read + Send + 'static>, std::io::Error> {
    if let Some(path) = file_uri_to_path(locator) {
        return Ok(Box::new(fs::File::open(path)?));
    }
    if locator.starts_with("http://") || locator.starts_with("https://") {
        log_cdn_host_once(locator);
        let response = http_client()
            .get(locator)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, format!("{e}")))?;
        if !response.status().is_success() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::Other,
                format!("HTTP error {}", response.status()),
            ));
        }
        if let Some(host) = extract_http_host(locator) {
            log_http_version_once(&host, response.version());
        }
        return Ok(Box::new(response.into_body()));
    }
    Err(std::io::Error::new(
        std::io::ErrorKind::InvalidInput,
        format!("unsupported segment locator '{locator}'"),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::native_transport::source::{NativeTransportSource, TidalTrackContext};
    use std::process::Command;
    use std::thread;
    use std::time::{Duration, Instant};

    fn wait_until(
        controller: &NativeTransportController,
        predicate: impl Fn(&NativeTransportSnapshot) -> bool,
    ) {
        let deadline = Instant::now() + Duration::from_millis(250);
        loop {
            let snapshot = controller.snapshot();
            if predicate(&snapshot) {
                return;
            }
            assert!(
                Instant::now() < deadline,
                "timed out waiting for transport state: {:?}",
                snapshot
            );
            thread::sleep(Duration::from_millis(5));
        }
    }

    fn generate_flac_fixture(path: &str) {
        let status = Command::new("ffmpeg")
            .args([
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=0.02",
                "-ac",
                "2",
                path,
            ])
            .status()
            .expect("ffmpeg must be available to generate the FLAC fixture");
        assert!(status.success(), "ffmpeg failed to generate FLAC fixture");
    }

    fn generate_aac_m4a_fixture(path: &str) {
        let status = Command::new("ffmpeg")
            .args([
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=660:duration=0.05",
                "-ac",
                "2",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                path,
            ])
            .status()
            .expect("ffmpeg must be available to generate the AAC fixture");
        assert!(status.success(), "ffmpeg failed to generate AAC fixture");
    }

    fn generate_dash_fixture(dir: &str) -> String {
        std::fs::create_dir_all(dir).unwrap();
        let mpd_path = format!("{dir}/out.mpd");
        let status = Command::new("ffmpeg")
            .args([
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1",
                "-ac",
                "2",
                "-c:a",
                "flac",
                "-f",
                "dash",
                &mpd_path,
            ])
            .status()
            .expect("ffmpeg must be available to generate the DASH fixture");
        assert!(status.success(), "ffmpeg failed to generate DASH fixture");
        mpd_path
    }

    fn generate_aac_dash_fixture(dir: &str) -> String {
        std::fs::create_dir_all(dir).unwrap();
        let mpd_path = format!("{dir}/out.mpd");
        let status = Command::new("ffmpeg")
            .args([
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=880:duration=1",
                "-ac",
                "2",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-f",
                "dash",
                &mpd_path,
            ])
            .status()
            .expect("ffmpeg must be available to generate the AAC DASH fixture");
        assert!(
            status.success(),
            "ffmpeg failed to generate AAC DASH fixture"
        );
        mpd_path
    }

    #[test]
    fn load_transitions_transport_to_ready() {
        let flac_path = "/tmp/native-transport-test.flac";
        generate_flac_fixture(flac_path);
        let controller = NativeTransportController::new();
        let request = NativeTransportLoadRequest {
            source: NativeTransportSource::TidalDirectMedia {
                url: format!("file://{flac_path}"),
                track: TidalTrackContext {
                    track_id: "123".to_string(),
                    title: "Track".to_string(),
                    quality_label: "LOSSLESS".to_string(),
                },
            },
            target_driver: "USB Rawlink v2".to_string(),
            bit_perfect: true,
            output_target: None,
            dsp_config: None,
        };
        controller.load(request).unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Ready
        });
        let snapshot = controller.snapshot();
        assert_eq!(snapshot.current_track_id.as_deref(), Some("123"));
        assert_eq!(snapshot.decoder, Some(NativeDecoderKind::SymphoniaAudio));
        assert_eq!(
            snapshot.stream_spec.as_ref().map(|spec| spec.sample_rate),
            Some(44100)
        );
        assert!(snapshot.supports_seek);
        let _ = std::fs::remove_file(flac_path);
    }

    #[test]
    fn play_pause_stop_roundtrip_updates_state() {
        let dash_dir = "/tmp/native-transport-roundtrip";
        let mpd_path = generate_dash_fixture(dash_dir);
        let controller = NativeTransportController::new();
        let request = NativeTransportLoadRequest {
            source: NativeTransportSource::TidalMpd {
                manifest_uri: format!("file://{mpd_path}"),
                track: TidalTrackContext {
                    track_id: "456".to_string(),
                    title: "Manifest Track".to_string(),
                    quality_label: "HI_RES_LOSSLESS".to_string(),
                },
            },
            target_driver: "USB Rawlink v2".to_string(),
            bit_perfect: true,
            output_target: None,
            dsp_config: None,
        };
        controller.load(request).unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Ready
        });
        controller.play().unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Playing
        });
        controller.pause().unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Paused
        });
        controller.stop().unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Stopped
        });
        let _ = std::fs::remove_dir_all(dash_dir);
    }

    #[test]
    fn direct_media_play_decodes_pcm_slabs() {
        let flac_path = "/tmp/native-transport-play.flac";
        generate_flac_fixture(flac_path);
        let controller = NativeTransportController::new();
        let request = NativeTransportLoadRequest {
            source: NativeTransportSource::TidalDirectMedia {
                url: format!("file://{flac_path}"),
                track: TidalTrackContext {
                    track_id: "901".to_string(),
                    title: "Decode Track".to_string(),
                    quality_label: "LOSSLESS".to_string(),
                },
            },
            target_driver: "USB Rawlink v2".to_string(),
            bit_perfect: true,
            output_target: None,
            dsp_config: None,
        };
        controller.load(request).unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Ready
        });
        controller.play().unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Playing
        });
        wait_until(&controller, |snapshot| snapshot.decoded_slab_count > 0);
        wait_until(&controller, |snapshot| snapshot.decode_completed);
        let snapshot = controller.snapshot();
        assert!(snapshot.decoded_frame_count > 0);
        assert!(snapshot.decoded_byte_count > 0);
        assert!(!snapshot.decode_worker_running);
        let _ = std::fs::remove_file(flac_path);
    }

    #[test]
    fn direct_aac_m4a_play_decodes_pcm_slabs() {
        let m4a_path = "/tmp/native-transport-play.m4a";
        generate_aac_m4a_fixture(m4a_path);
        let controller = NativeTransportController::new();
        let request = NativeTransportLoadRequest {
            source: NativeTransportSource::TidalDirectMedia {
                url: format!("file://{m4a_path}"),
                track: TidalTrackContext {
                    track_id: "903".to_string(),
                    title: "AAC Decode Track".to_string(),
                    quality_label: "HIGH".to_string(),
                },
            },
            target_driver: "USB Rawlink v2".to_string(),
            bit_perfect: true,
            output_target: None,
            dsp_config: None,
        };
        controller.load(request).unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Ready
        });
        controller.play().unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Playing
        });
        wait_until(&controller, |snapshot| snapshot.decoded_slab_count > 0);
        wait_until(&controller, |snapshot| snapshot.decode_completed);
        let snapshot = controller.snapshot();
        assert!(snapshot.decoded_frame_count > 0);
        assert!(snapshot.decoded_byte_count > 0);
        assert_eq!(
            snapshot.stream_spec.as_ref().map(|spec| spec.sample_rate),
            Some(44100)
        );
        let events = controller.take_events();
        assert!(events
            .iter()
            .any(|(evt, msg)| *evt == crate::EVT_TAG && msg.contains("codec=AAC")));
        let _ = std::fs::remove_file(m4a_path);
    }

    #[test]
    fn mpd_play_decodes_pcm_slabs() {
        let dash_dir = "/tmp/native-transport-dash";
        let mpd_path = generate_dash_fixture(dash_dir);
        let controller = NativeTransportController::new();
        let request = NativeTransportLoadRequest {
            source: NativeTransportSource::TidalMpd {
                manifest_uri: format!("file://{mpd_path}"),
                track: TidalTrackContext {
                    track_id: "902".to_string(),
                    title: "Dash Decode".to_string(),
                    quality_label: "HI_RES_LOSSLESS".to_string(),
                },
            },
            target_driver: "USB Rawlink v2".to_string(),
            bit_perfect: true,
            output_target: None,
            dsp_config: None,
        };
        controller.load(request).unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Ready
        });
        controller.play().unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Playing
        });
        wait_until(&controller, |snapshot| snapshot.decoded_slab_count > 0);
        wait_until(&controller, |snapshot| snapshot.decode_completed);
        let snapshot = controller.snapshot();
        assert!(snapshot.decoded_frame_count > 0);
        assert!(snapshot.decoded_byte_count > 0);
        let _ = std::fs::remove_dir_all(dash_dir);
    }

    #[test]
    fn aac_mpd_play_decodes_pcm_slabs() {
        let dash_dir = "/tmp/native-transport-aac-dash";
        let mpd_path = generate_aac_dash_fixture(dash_dir);
        let controller = NativeTransportController::new();
        let request = NativeTransportLoadRequest {
            source: NativeTransportSource::TidalMpd {
                manifest_uri: format!("file://{mpd_path}"),
                track: TidalTrackContext {
                    track_id: "904".to_string(),
                    title: "AAC Dash Decode".to_string(),
                    quality_label: "HIGH".to_string(),
                },
            },
            target_driver: "USB Rawlink v2".to_string(),
            bit_perfect: true,
            output_target: None,
            dsp_config: None,
        };
        controller.load(request).unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Ready
        });
        controller.play().unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Playing
        });
        wait_until(&controller, |snapshot| snapshot.decoded_slab_count > 0);
        wait_until(&controller, |snapshot| snapshot.decode_completed);
        let snapshot = controller.snapshot();
        assert!(snapshot.decoded_frame_count > 0);
        assert!(snapshot.decoded_byte_count > 0);
        let events = controller.take_events();
        assert!(events
            .iter()
            .any(|(evt, msg)| *evt == crate::EVT_TAG && msg.contains("codec=AAC")));
        let _ = std::fs::remove_dir_all(dash_dir);
    }

    #[test]
    fn load_mpd_sets_summary_from_manifest_probe() {
        let dash_dir = "/tmp/native-transport-summary";
        let mpd_path = generate_dash_fixture(dash_dir);
        let controller = NativeTransportController::new();
        let request = NativeTransportLoadRequest {
            source: NativeTransportSource::TidalMpd {
                manifest_uri: format!("file://{mpd_path}"),
                track: TidalTrackContext {
                    track_id: "789".to_string(),
                    title: "Manifest Probe".to_string(),
                    quality_label: "HI_RES_LOSSLESS".to_string(),
                },
            },
            target_driver: "USB Rawlink v2".to_string(),
            bit_perfect: true,
            output_target: None,
            dsp_config: None,
        };
        controller.load(request).unwrap();
        wait_until(&controller, |snapshot| {
            snapshot.state == NativeTransportState::Ready
        });
        let snapshot = controller.snapshot();
        assert!(snapshot
            .source_summary
            .as_deref()
            .unwrap_or_default()
            .contains("mpd representations=1"));
        let _ = std::fs::remove_dir_all(dash_dir);
    }
}
