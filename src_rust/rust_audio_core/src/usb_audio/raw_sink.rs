use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use std::sync::OnceLock;

use glib::subclass::prelude::*;
use gst::prelude::*;
use gst::subclass::prelude::*;
use gst_base::subclass::prelude::*;
use gstreamer as gst;
use gstreamer_base as gst_base;

use crate::alsa_clock::ClockMode;
use crate::alsa_clock::{AlsaHwClock, AlsaHwClockFeed};
use crate::usb_audio::transfer;

use super::queue::FrameQueue;
use super::raw_config::UsbRawSinkConfig;
use super::sink::{PushBufferError, UsbAudioSink};

struct RuntimeState {
    config: Option<UsbRawSinkConfig>,
    negotiated_rate: u32,
    session: Option<UsbAudioSink>,
    has_opened_once: bool,
}

impl Default for RuntimeState {
    fn default() -> Self {
        Self {
            config: None,
            negotiated_rate: 0,
            session: None,
            has_opened_once: false,
        }
    }
}

fn desired_raw_caps(cfg: &UsbRawSinkConfig) -> gst::Caps {
    gst::Caps::builder("audio/x-raw")
        .field("format", cfg.gst_format.as_str())
        .field("layout", "interleaved")
        .field("channels", cfg.channels as i32)
        .build()
}

mod imp {
    use super::*;

    pub struct UsbRawSink {
        pub(super) state: Mutex<RuntimeState>,
        pub(super) unlocked: AtomicBool,
        pub(super) feed: Arc<AlsaHwClockFeed>,
        pub(super) anchor_stream_pos_ns: AtomicU64,
        pub(super) spectrum_reset_after_open: AtomicBool,
        pub(super) events: Mutex<VecDeque<(i32, String)>>,
        pub(super) keep_claimed_on_next_stop: AtomicBool,
    }

    impl Default for UsbRawSink {
        fn default() -> Self {
            Self {
                state: Mutex::new(RuntimeState::default()),
                unlocked: AtomicBool::new(false),
                feed: Arc::new(AlsaHwClockFeed::default()),
                anchor_stream_pos_ns: AtomicU64::new(0),
                spectrum_reset_after_open: AtomicBool::new(false),
                events: Mutex::new(VecDeque::new()),
                keep_claimed_on_next_stop: AtomicBool::new(false),
            }
        }
    }

    #[glib::object_subclass]
    impl ObjectSubclass for UsbRawSink {
        const NAME: &'static str = "HiresTiUsbRawSink";
        type Type = super::UsbRawSink;
        type ParentType = gst_base::BaseSink;
    }

    impl ObjectImpl for UsbRawSink {}
    impl GstObjectImpl for UsbRawSink {}
    impl ElementImpl for UsbRawSink {
        fn metadata() -> Option<&'static gst::subclass::ElementMetadata> {
            static ELEMENT_METADATA: OnceLock<gst::subclass::ElementMetadata> = OnceLock::new();
            Some(ELEMENT_METADATA.get_or_init(|| {
                gst::subclass::ElementMetadata::new(
                    "USB Raw Sink",
                    "Sink/Audio",
                    "Experimental custom USB rawlink sink",
                    "OpenAI",
                )
            }))
        }

        fn pad_templates() -> &'static [gst::PadTemplate] {
            static PAD_TEMPLATES: OnceLock<Vec<gst::PadTemplate>> = OnceLock::new();
            PAD_TEMPLATES.get_or_init(|| {
                vec![
                    gst::PadTemplate::new(
                        "sink",
                        gst::PadDirection::Sink,
                        gst::PadPresence::Always,
                        &gst::Caps::new_any(),
                    )
                    .expect("usbrawsink sink pad template"),
                ]
            })
        }
    }

    impl BaseSinkImpl for UsbRawSink {
        fn start(&self) -> Result<(), gst::ErrorMessage> {
            self.unlocked.store(false, Ordering::Release);
            if let Ok(mut state) = self.state.lock() {
                self.obj().clear_session_locked(&mut state, "start");
            }
            Ok(())
        }

        fn stop(&self) -> Result<(), gst::ErrorMessage> {
            self.unlocked.store(false, Ordering::Release);
            if let Ok(mut state) = self.state.lock() {
                if self.keep_claimed_on_next_stop.swap(false, Ordering::AcqRel) {
                    if let Some(ref mut session) = state.session {
                        session.set_skip_release_on_drop(true);
                        eprintln!("usb-rawsink: stop -> keep USB interface claimed");
                    }
                }
                self.obj().clear_session_locked(&mut state, "stop");
            }
            Ok(())
        }

        fn event(&self, event: gst::Event) -> bool {
            match event.view() {
                gst::EventView::FlushStart(..)
                | gst::EventView::Eos(..)
                | gst::EventView::StreamStart(..) => {
                    if let Ok(mut state) = self.state.lock() {
                        self.obj()
                            .clear_session_locked(&mut state, &format!("event {:?}", event.type_()));
                    }
                }
                _ => {}
            }
            self.parent_event(event)
        }

        fn set_caps(&self, caps: &gst::Caps) -> Result<(), gst::LoggableError> {
            if let Ok(state) = self.state.lock() {
                if let Some(ref cfg) = state.config {
                    let expected = desired_raw_caps(cfg);
                    if !caps.can_intersect(&expected) {
                        return Err(gst::loggable_error!(
                            gst::CAT_RUST,
                            "usbrawsink negotiated unsupported caps: got={} expected={}",
                            caps,
                            expected,
                        ));
                    }
                }
            }
            let rate = caps
                .structure(0)
                .and_then(|s| s.get::<i32>("rate").ok())
                .unwrap_or(0)
                .max(0) as u32;
            if let Ok(mut state) = self.state.lock() {
                state.negotiated_rate = rate;
                if let Some(ref session) = state.session {
                    if session.actual_rate != rate && rate > 0 {
                        eprintln!(
                            "usb-rawsink: caps changed {} -> {}; reopening on next render",
                            session.actual_rate, rate
                        );
                        state.session = None;
                        self.obj()
                            .queue_event(crate::EVT_STATE, format!("usb-rawsink caps-change rate={rate}"));
                    }
                }
            }
            Ok(())
        }

        fn caps(&self, filter: Option<&gst::Caps>) -> Option<gst::Caps> {
            let state = self.state.lock().ok()?;
            let cfg = state.config.as_ref()?;
            let caps = desired_raw_caps(cfg);
            Some(match filter {
                Some(filter) => filter.intersect(&caps),
                None => caps,
            })
        }

        fn propose_allocation(
            &self,
            query: &mut gst::query::Allocation,
        ) -> Result<(), gst::LoggableError> {
            let (caps_opt, _need_pool) = query.get();
            let Some(caps) = caps_opt else {
                return Ok(());
            };
            let caps_log = format!("{}", caps);
            let caps_owned = caps.to_owned();
            let st = match caps.structure(0) {
                Some(st) if st.name() == "audio/x-raw" => st,
                _ => return Ok(()),
            };
            let rate = st.get::<i32>("rate").ok().unwrap_or(0).max(1) as u32;
            let channels = st.get::<i32>("channels").ok().unwrap_or(0).max(1) as u32;
            let format = st.get::<&str>("format").ok().unwrap_or("S32LE");
            let bps = match format {
                "S16LE" | "S16BE" | "U16LE" | "U16BE" => 2,
                "S24_3LE" | "S24_3BE" => 3,
                _ => 4,
            } as u32;
            let frame_bytes = channels.saturating_mul(bps).max(1);
            let bytes_per_ms = rate.saturating_mul(frame_bytes) / 1000;
            let size = bytes_per_ms
                .saturating_mul(750)
                .clamp(64 * 1024, 256 * 1024)
                .saturating_div(frame_bytes)
                .saturating_mul(frame_bytes)
                .max(frame_bytes);

            let pool = gst::BufferPool::new();
            let mut config = pool.config();
            config.set_params(Some(&caps_owned), size, 2, 4);
            if pool.set_config(config).is_ok() {
                if query.allocation_pools().is_empty() {
                    query.add_allocation_pool(Some(&pool), size, 2, 4);
                } else {
                    query.set_nth_allocation_pool(0, Some(&pool), size, 2, 4);
                }
                eprintln!(
                    "usb-rawsink: propose-allocation caps={} pool_size={} min=2 max=4",
                    caps_log, size,
                );
            }

            Ok(())
        }

        fn render(&self, buffer: &gst::Buffer) -> Result<gst::FlowSuccess, gst::FlowError> {
            if self.unlocked.load(Ordering::Acquire) {
                return Err(gst::FlowError::Flushing);
            }

            let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
            let cfg = state.config.clone().ok_or(gst::FlowError::Error)?;
            let rate = state.negotiated_rate.max(1);

            if state.session.is_none() && self.anchor_stream_pos_ns.load(Ordering::Acquire) == 0 {
                let pts_ns = buffer.pts().map(|p| p.nseconds()).unwrap_or(0);
                self.anchor_stream_pos_ns.store(pts_ns, Ordering::Release);
            }

            if state.session.is_none() {
                let session = UsbAudioSink::open_with_feed(
                    &cfg.device_id,
                    rate,
                    cfg.bit_depth,
                    Arc::clone(&self.feed),
                    None,
                    Some(cfg.alt_profile),
                    true,
                )
                .map_err(|_| gst::FlowError::Error)?;
                let pps = session.state.packets_per_sec as usize;
                let n_pkts = (transfer::N_PACKETS_TARGET_MS * pps / 1000).max(8);
                let ring_buf_ns =
                    (transfer::N_TRANSFERS * n_pkts) as u64 * 1_000_000_000 / pps as u64;
                let clock_mode = match cfg.clock_mode {
                    1 => ClockMode::Pull,
                    _ => ClockMode::Push,
                };
                let buf_ns = if clock_mode == ClockMode::Pull {
                    0
                } else {
                    ring_buf_ns
                };
                self.feed.set_buffer_depth_ns(buf_ns);
                self.feed.set_mode(clock_mode);
                eprintln!(
                    "usb-rawsink: opened rate={} source_kind={} borrowed={} clock_mode={:?} ring_buf_ns={} buf_ns={}",
                    session.actual_rate,
                    session.source_kind(),
                    session.supports_borrowed_buffers(),
                    clock_mode,
                    ring_buf_ns,
                    buf_ns,
                );
                self.obj().queue_event(
                    crate::EVT_STATE,
                    format!(
                        "usb-rawsink opened rate={} clock_mode={:?}",
                        session.actual_rate, clock_mode
                    ),
                );
                if state.has_opened_once {
                    self.spectrum_reset_after_open.store(true, Ordering::Release);
                }
                state.has_opened_once = true;
                state.session = Some(session);
            }

            let session = state.session.as_mut().ok_or(gst::FlowError::Error)?;
            let mut pending = buffer.to_owned();
            let mut retries = 0u32;
            loop {
                if self.unlocked.load(Ordering::Acquire) {
                    return Err(gst::FlowError::Flushing);
                }
                match session.push_buffer(pending) {
                    Ok(()) => break,
                    Err(PushBufferError::Full(buf)) => pending = buf,
                    Err(PushBufferError::MapFailed(_buf)) => return Err(gst::FlowError::Error),
                }
                retries = retries.saturating_add(1);
                if retries <= 4 {
                    std::hint::spin_loop();
                } else if retries <= 12 {
                    std::thread::yield_now();
                } else {
                    std::thread::sleep(Duration::from_micros(250));
                }
            }

            let bytes_per_sample = match cfg.gst_format.as_str() {
                "S16LE" | "S16BE" | "U16LE" | "U16BE" => 2,
                "S24_3LE" | "S24_3BE" => 3,
                _ => 4,
            };
            let target_prefill = (rate as u128
                * cfg.channels as u128
                * bytes_per_sample as u128
                * (transfer::N_TRANSFERS * transfer::N_PACKETS_TARGET_MS * 2) as u128
                / 1000)
                .min(FrameQueue::capacity_bytes() as u128) as usize;
            if !session.is_started() && session.queued_bytes() >= target_prefill {
                eprintln!(
                    "usb-rawsink: prefill ready queued={} target={}; starting ring",
                    session.queued_bytes(),
                    target_prefill,
                );
                self.obj().queue_event(
                    crate::EVT_STATE,
                    format!(
                        "usb-rawsink prefill queued={} target={}",
                        session.queued_bytes(),
                        target_prefill
                    ),
                );
                session.ensure_started().map_err(|_| gst::FlowError::Error)?;
            }

            Ok(gst::FlowSuccess::Ok)
        }

        fn unlock(&self) -> Result<(), gst::ErrorMessage> {
            self.unlocked.store(true, Ordering::Release);
            Ok(())
        }

        fn unlock_stop(&self) -> Result<(), gst::ErrorMessage> {
            self.unlocked.store(false, Ordering::Release);
            Ok(())
        }
    }
}

glib::wrapper! {
    pub struct UsbRawSink(ObjectSubclass<imp::UsbRawSink>) @extends gst_base::BaseSink, gst::Element, gst::Object;
}

impl UsbRawSink {
    fn clear_session_locked(&self, state: &mut RuntimeState, reason: &str) {
        let had_session = state.session.is_some();
        if had_session {
            eprintln!("usb-rawsink: dropping session ({reason})");
        }
        state.session = None;
        self.imp().feed.invalidate();
        self.imp().anchor_stream_pos_ns.store(0, Ordering::Release);
        if had_session {
            self.queue_event(crate::EVT_STATE, format!("usb-rawsink session-drop reason={reason}"));
        }
    }

    fn queue_event(&self, evt: i32, msg: String) {
        if let Ok(mut events) = self.imp().events.lock() {
            if events.len() >= 32 {
                events.pop_front();
            }
            events.push_back((evt, msg));
        }
    }

    pub fn new(name: Option<&str>, config: UsbRawSinkConfig) -> Self {
        let sink: Self = glib::Object::builder().property("name", name).build();
        if let Ok(mut state) = sink.imp().state.lock() {
            state.config = Some(config);
        }
        sink
    }

    pub fn config(&self) -> Option<UsbRawSinkConfig> {
        self.imp()
            .state
            .lock()
            .ok()
            .and_then(|state| state.config.clone())
    }

    pub fn reset_session(&self, reason: &str) {
        if let Ok(mut state) = self.imp().state.lock() {
            self.clear_session_locked(&mut state, reason);
        }
    }

    pub fn prepare_track_switch(&self) {
        self.imp()
            .keep_claimed_on_next_stop
            .store(true, Ordering::Release);
    }

    pub fn reset_session_keep_claimed(&self, reason: &str) {
        if let Ok(mut state) = self.imp().state.lock() {
            if let Some(ref mut session) = state.session {
                session.set_skip_release_on_drop(true);
            }
            self.clear_session_locked(&mut state, reason);
        }
    }

    pub fn take_events(&self) -> Vec<(i32, String)> {
        match self.imp().events.lock() {
            Ok(mut events) => events.drain(..).collect(),
            Err(_) => Vec::new(),
        }
    }

    pub fn take_spectrum_reset_after_open(&self) -> bool {
        self.imp()
            .spectrum_reset_after_open
            .swap(false, Ordering::Acquire)
    }

    pub fn clock(&self) -> AlsaHwClock {
        AlsaHwClock::new(Arc::clone(&self.imp().feed))
    }

    pub fn set_clock_mode(&self, mode: u8) {
        if let Ok(mut state) = self.imp().state.lock() {
            if let Some(ref mut cfg) = state.config {
                cfg.clock_mode = mode;
            }
            if let Some(ref session) = state.session {
                let pps = session.state.packets_per_sec as usize;
                let n_pkts = (transfer::N_PACKETS_TARGET_MS * pps / 1000).max(8);
                let ring_buf_ns =
                    (transfer::N_TRANSFERS * n_pkts) as u64 * 1_000_000_000 / pps as u64;
                let clock_mode = match mode {
                    1 => ClockMode::Pull,
                    _ => ClockMode::Push,
                };
                let buf_ns = if clock_mode == ClockMode::Pull {
                    0
                } else {
                    ring_buf_ns
                };
                self.imp().feed.set_buffer_depth_ns(buf_ns);
                self.imp().feed.set_mode(clock_mode);
                eprintln!(
                    "usb-rawsink: clock mode updated live -> {:?} ring_buf_ns={} buf_ns={}",
                    clock_mode, ring_buf_ns, buf_ns,
                );
            }
        }
    }

    pub fn runtime_rate(&self) -> u32 {
        self.imp().feed.rate.load(Ordering::Relaxed)
    }

    pub fn runtime_total_frames(&self) -> u64 {
        self.imp().feed.total_frames.load(Ordering::Relaxed)
    }

    pub fn runtime_anchor_stream_pos_ns(&self) -> u64 {
        self.imp().anchor_stream_pos_ns.load(Ordering::Acquire)
    }

    pub fn runtime_bit_depth(&self) -> u8 {
        self.imp()
            .state
            .lock()
            .ok()
            .and_then(|state| state.config.as_ref().map(|cfg| cfg.bit_depth))
            .unwrap_or(0)
    }

    pub fn runtime_device_name(&self) -> String {
        self.imp()
            .state
            .lock()
            .ok()
            .and_then(|state| state.session.as_ref().map(|session| session.device_name()))
            .unwrap_or_else(|| {
                self.imp()
                    .state
                    .lock()
                    .ok()
                    .and_then(|state| state.config.as_ref().map(|cfg| cfg.device_id.clone()))
                    .unwrap_or_default()
            })
    }

    pub fn hw_volume_supported(&self) -> bool {
        self.imp()
            .state
            .lock()
            .ok()
            .and_then(|state| state.session.as_ref().map(|session| session.has_hw_volume()))
            .unwrap_or(false)
    }

    pub fn hw_volume_get_range(&self) -> Option<(i32, i32, i32)> {
        let state = self.imp().state.lock().ok()?;
        let session = state.session.as_ref()?;
        session
            .get_hw_volume_range()
            .map(|(min, max, res)| (min as i32, max as i32, res as i32))
    }

    pub fn hw_volume_channels(&self) -> Vec<u8> {
        self.imp()
            .state
            .lock()
            .ok()
            .and_then(|state| state.session.as_ref().map(|session| session.hw_volume_channels()))
            .unwrap_or_default()
    }

    pub fn hw_volume_get_ch(&self, idx: usize) -> Option<i32> {
        let state = self.imp().state.lock().ok()?;
        let session = state.session.as_ref()?;
        session.get_hw_volume_ch(idx).map(|v| v as i32)
    }

    pub fn hw_volume_set_ch(&self, idx: usize, value_raw: i32) -> bool {
        let state = match self.imp().state.lock() {
            Ok(state) => state,
            Err(_) => return false,
        };
        let Some(session) = state.session.as_ref() else {
            return false;
        };
        session.set_hw_volume_ch(idx, value_raw as i16).is_ok()
    }

    pub fn hw_volume_set_all(&self, value_raw: i32) -> bool {
        let state = match self.imp().state.lock() {
            Ok(state) => state,
            Err(_) => return false,
        };
        let Some(session) = state.session.as_ref() else {
            return false;
        };
        session.set_hw_volume(value_raw as i16).is_ok()
    }
}
