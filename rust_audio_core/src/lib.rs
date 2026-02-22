use gstreamer as gst;
use pipewire as pw;
use gst::prelude::*;
use pw::{context::Context as PwContext, keys, main_loop::MainLoop as PwMainLoop, metadata::Metadata as PwMetadata, registry::GlobalObject, types::ObjectType};
use std::cell::{Cell, RefCell};
use std::env;
use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_double, c_int, c_void};
use std::ptr;
use std::process::Command;
use std::rc::Rc;
use std::sync::Once;
use std::thread;
use std::time::Duration;

static GST_INIT: Once = Once::new();
static PW_INIT: Once = Once::new();
const SPECTRUM_BANDS_MAX: usize = 128;
const SPECTRUM_RING_CAP: usize = 512;

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
    playbin: gst::Element,
    _audio_filter_bin: Option<gst::Bin>,
    uri: String,
    last_error: Option<String>,
    event_cb: Option<EventCallback>,
    event_user_data: *mut c_void,
    playback_rate: f64,
    pitch_semitones: f64,
    spectrum_seq: u64,
    spectrum_pos_s: f64,
    spectrum_vals: [f32; SPECTRUM_BANDS_MAX],
    spectrum_len: usize,
    spectrum_ring_vals: [[f32; SPECTRUM_BANDS_MAX]; SPECTRUM_RING_CAP],
    spectrum_ring_len: [u16; SPECTRUM_RING_CAP],
    spectrum_ring_pos_s: [f64; SPECTRUM_RING_CAP],
    spectrum_ring_seq: [u64; SPECTRUM_RING_CAP],
    spectrum_ring_write: usize,
    spectrum_ring_count: usize,
    spectrum_seen_msgs: u64,
    spectrum_msg_count: u64,
    element_msg_seen: u64,
    fmt_probe_tick: u64,
    last_codec: String,
    last_bitrate: i32,
    last_rate: i32,
    last_depth: i32,
    source_rate: i32,
    source_depth: i32,
    spectrum_enabled: bool,
}

impl Engine {
    fn ensure_pw_init() {
        PW_INIT.call_once(|| {
            pw::init();
        });
    }

    fn pipewire_set_settings_metadata(key: &str, value: &str, value_type: Option<&str>) -> Result<(), String> {
        Self::ensure_pw_init();
        let result = (|| -> Result<(), String> {
            let mainloop = PwMainLoop::new(None).map_err(|e| format!("pw mainloop: {e}"))?;
            let context = PwContext::new(&mainloop).map_err(|e| format!("pw context: {e}"))?;
            let core = context.connect(None).map_err(|e| format!("pw connect: {e}"))?;
            let registry = core.get_registry().map_err(|e| format!("pw registry: {e}"))?;

            use std::{cell::Cell, rc::Rc};
            let done = Rc::new(Cell::new(false));
            let found_meta_id = Rc::new(Cell::new(u32::MAX));

            let done_clone = done.clone();
            let ml_quit = mainloop.clone();
            let found_clone = found_meta_id.clone();

            let _listener_reg = registry
                .add_listener_local()
                .global(move |global| {
                    if global.type_ != ObjectType::Metadata {
                        return;
                    }
                    let Some(props) = global.props else {
                        return;
                    };
                    let name = props.get("metadata.name");
                    if name == Some("settings") {
                        found_clone.set(global.id);
                    }
                })
                .register();

            let pending = core.sync(0).map_err(|e| format!("pw sync: {e}"))?;
            let _listener_core = core
                .add_listener_local()
                .done(move |id, seq| {
                    if id == pw::core::PW_ID_CORE && seq == pending {
                        done_clone.set(true);
                        ml_quit.quit();
                    }
                })
                .register();

            while !done.get() {
                mainloop.run();
            }

            let meta_id = found_meta_id.get();
            if meta_id == u32::MAX {
                return Err("pw metadata 'settings' not found".to_string());
            }

            let obj = GlobalObject {
                id: meta_id,
                permissions: pw::permissions::PermissionFlags::all(),
                type_: ObjectType::Metadata,
                version: pw::sys::PW_VERSION_METADATA,
                props: Option::<pw::properties::Properties>::None,
            };
            let metadata: PwMetadata = registry.bind(&obj).map_err(|e| format!("pw bind metadata: {e}"))?;
            metadata.set_property(0, key, value_type, Some(value));
            Ok(())
        })();
        result
    }

    fn pipewire_set_clock_force_rate(rate: i32) -> Result<(), String> {
        let value = if rate <= 0 { "0".to_string() } else { rate.to_string() };
        Self::pipewire_set_settings_metadata("clock.force-rate", &value, Some("Spa:Int"))
    }

    fn pipewire_set_clock_allowed_rates_csv(csv: &str) -> Result<(), String> {
        let mut vals: Vec<i32> = Vec::new();
        for p in csv.split(',') {
            let t = p.trim();
            if t.is_empty() {
                continue;
            }
            if let Ok(v) = t.parse::<i32>() {
                if v > 0 {
                    vals.push(v);
                }
            }
        }
        if vals.is_empty() {
            return Err("empty allowed-rates".to_string());
        }
        vals.sort_unstable();
        vals.dedup();
        let arr = format!(
            "[ {} ]",
            vals.iter().map(|v| v.to_string()).collect::<Vec<_>>().join(" ")
        );
        // Keep type empty like `pw-metadata` for array-like values.
        Self::pipewire_set_settings_metadata("clock.allowed-rates", &arr, None)
    }

    fn pipewire_read_settings_metadata() -> Result<(i32, String, i32, i32), String> {
        Self::ensure_pw_init();
        let result = (|| -> Result<(i32, String, i32, i32), String> {
            let mainloop = PwMainLoop::new(None).map_err(|e| format!("pw mainloop: {e}"))?;
            let context = PwContext::new(&mainloop).map_err(|e| format!("pw context: {e}"))?;
            let core = context.connect(None).map_err(|e| format!("pw connect: {e}"))?;
            let registry = core.get_registry().map_err(|e| format!("pw registry: {e}"))?;

            let done = Rc::new(Cell::new(false));
            let found_meta_id = Rc::new(Cell::new(u32::MAX));
            let force_rate = Rc::new(Cell::new(0i32));
            let allowed_raw = Rc::new(RefCell::new(String::new()));
            let clock_quantum = Rc::new(Cell::new(0i32));
            let clock_rate = Rc::new(Cell::new(0i32));

            let done_clone = done.clone();
            let ml_quit = mainloop.clone();
            let found_clone = found_meta_id.clone();

            let _listener_reg = registry
                .add_listener_local()
                .global(move |global| {
                    if global.type_ != ObjectType::Metadata {
                        return;
                    }
                    let Some(props) = global.props else {
                        return;
                    };
                    let name = props.get("metadata.name");
                    if name == Some("settings") {
                        found_clone.set(global.id);
                    }
                })
                .register();

            let pending = core.sync(0).map_err(|e| format!("pw sync: {e}"))?;
            let _listener_core = core
                .add_listener_local()
                .done(move |id, seq| {
                    if id == pw::core::PW_ID_CORE && seq == pending {
                        done_clone.set(true);
                        ml_quit.quit();
                    }
                })
                .register();

            while !done.get() {
                mainloop.run();
            }

            let meta_id = found_meta_id.get();
            if meta_id == u32::MAX {
                return Err("pw metadata 'settings' not found".to_string());
            }

            let obj = GlobalObject {
                id: meta_id,
                permissions: pw::permissions::PermissionFlags::all(),
                type_: ObjectType::Metadata,
                version: pw::sys::PW_VERSION_METADATA,
                props: Option::<pw::properties::Properties>::None,
            };
            let metadata: PwMetadata = registry.bind(&obj).map_err(|e| format!("pw bind metadata: {e}"))?;

            let fr = force_rate.clone();
            let ar = allowed_raw.clone();
            let cq = clock_quantum.clone();
            let cr = clock_rate.clone();
            let _listener_meta = metadata
                .add_listener_local()
                .property(move |_subject, key, _ty, value| {
                    let Some(k) = key else {
                        return 0;
                    };
                    let v = value.unwrap_or("").trim().to_string();
                    if k == "clock.force-rate" {
                        if let Ok(parsed) = v.parse::<i32>() {
                            fr.set(parsed.max(0));
                        }
                    } else if k == "clock.allowed-rates" {
                        *ar.borrow_mut() = v;
                    } else if k == "clock.quantum" {
                        if let Ok(parsed) = v.parse::<i32>() {
                            cq.set(parsed.max(0));
                        }
                    } else if k == "clock.rate" {
                        if let Ok(parsed) = v.parse::<i32>() {
                            cr.set(parsed.max(0));
                        }
                    }
                    0
                })
                .register();

            // Trigger one more sync to flush current metadata properties into listener.
            let done2 = Rc::new(Cell::new(false));
            let done2_clone = done2.clone();
            let ml_quit2 = mainloop.clone();
            let pending2 = core.sync(0).map_err(|e| format!("pw sync2: {e}"))?;
            let _listener_core2 = core
                .add_listener_local()
                .done(move |id, seq| {
                    if id == pw::core::PW_ID_CORE && seq == pending2 {
                        done2_clone.set(true);
                        ml_quit2.quit();
                    }
                })
                .register();
            while !done2.get() {
                mainloop.run();
            }

            let allowed = allowed_raw.borrow().clone();
            Ok((force_rate.get(), allowed, clock_quantum.get(), clock_rate.get()))
        })();
        result
    }

    fn parse_fraction_ms(txt: &str) -> Option<f64> {
        let s = txt.trim();
        if s.is_empty() {
            return None;
        }
        if let Some((a, b)) = s.split_once('/') {
            let num = a.trim().parse::<f64>().ok()?;
            let den = b.trim().parse::<f64>().ok()?;
            if den > 0.0 {
                return Some((num / den) * 1000.0);
            }
            return None;
        }
        let v = s.parse::<f64>().ok()?;
        if v.is_finite() && v >= 0.0 {
            // Fallback: treat plain number as milliseconds.
            return Some(v);
        }
        None
    }

    fn pipewire_query_app_node_latency_ms() -> Option<f64> {
        Self::ensure_pw_init();
        let result = (|| -> Option<f64> {
            let mainloop = PwMainLoop::new(None).ok()?;
            let context = PwContext::new(&mainloop).ok()?;
            let core = context.connect(None).ok()?;
            let registry = core.get_registry().ok()?;

            let done = Rc::new(Cell::new(false));
            let found_ms = Rc::new(Cell::new(-1.0f64));

            let done_clone = done.clone();
            let ml_quit = mainloop.clone();
            let found_clone = found_ms.clone();

            let pid_str = std::process::id().to_string();
            let mut_fallback = Rc::new(Cell::new(-1.0f64));
            let fallback_clone = mut_fallback.clone();
            let _listener_reg = registry
                .add_listener_local()
                .global(move |global| {
                    if global.type_ != ObjectType::Node {
                        return;
                    }
                    let Some(props) = global.props else {
                        return;
                    };
                    let media = props.get(*keys::MEDIA_CLASS).unwrap_or("");
                    // App stream node usually appears as Stream/Output/Audio.
                    if !media.contains("Stream/Output/Audio") {
                        return;
                    }
                    let app_pid = props.get(*keys::APP_PROCESS_ID).unwrap_or("");
                    let app_bin = props.get(*keys::APP_PROCESS_BINARY).unwrap_or("");
                    let app_name = props.get(*keys::APP_NAME).unwrap_or("");
                    let lat = props
                        .get(*keys::NODE_LATENCY)
                        .or_else(|| props.get(*keys::NODE_MAX_LATENCY))
                        .unwrap_or("");
                    if let Some(ms) = Self::parse_fraction_ms(lat) {
                        // Exact match: current process id.
                        if app_pid == pid_str {
                            found_clone.set(ms);
                            return;
                        }
                        // Fallback heuristic for wrapped python runtimes.
                        if app_bin.contains("python") || app_name.to_ascii_lowercase().contains("hiresti") {
                            found_clone.set(ms);
                            return;
                        }
                        // Last fallback: keep first stream latency candidate.
                        if fallback_clone.get() < 0.0 {
                            fallback_clone.set(ms);
                        }
                    }
                })
                .register();

            let pending = core.sync(0).ok()?;
            let _listener_core = core
                .add_listener_local()
                .done(move |id, seq| {
                    if id == pw::core::PW_ID_CORE && seq == pending {
                        done_clone.set(true);
                        ml_quit.quit();
                    }
                })
                .register();

            while !done.get() {
                mainloop.run();
            }

            let v = found_ms.get();
            if v >= 0.0 {
                Some(v)
            } else {
                let fb = mut_fallback.get();
                if fb >= 0.0 { Some(fb) } else { None }
            }
        })();
        result
    }

    fn parse_tag_text_value(text: &str, key: &str) -> Option<String> {
        let lower = text.to_ascii_lowercase();
        let pat = format!("{key}=");
        let pos = lower.find(&pat)?;
        let rest = &text[(pos + pat.len())..];
        let mut out = String::new();
        for ch in rest.chars() {
            if ch == ',' || ch == ';' || ch == '}' || ch == '\n' {
                break;
            }
            out.push(ch);
        }
        let mut v = out.trim().to_string();
        if let Some(idx) = v.find(')') {
            v = v[(idx + 1)..].trim().to_string();
        }
        if v.starts_with('"') && v.ends_with('"') && v.len() >= 2 {
            v = v[1..(v.len() - 1)].to_string();
        }
        if v.is_empty() {
            None
        } else {
            Some(v)
        }
    }

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

    fn parse_source_rate_depth_from_codec_text(codec: &str) -> (Option<i32>, Option<i32>) {
        let low = codec.to_ascii_lowercase();
        let mut rate: Option<i32> = None;
        let mut depth: Option<i32> = None;

        // Example: "FLAC, 44100 Hz, 16-bit"
        if let Some(pos) = low.find("hz") {
            let pre = &low[..pos];
            let mut digits_rev: Vec<char> = Vec::new();
            for ch in pre.chars().rev() {
                if ch.is_ascii_digit() {
                    digits_rev.push(ch);
                } else if !digits_rev.is_empty() {
                    break;
                }
            }
            if !digits_rev.is_empty() {
                let s: String = digits_rev.into_iter().rev().collect();
                if let Ok(v) = s.parse::<i32>() {
                    if v > 0 {
                        rate = Some(v);
                    }
                }
            }
        }

        if let Some(pos) = low.find("-bit").or_else(|| low.find(" bit")) {
            let pre = &low[..pos];
            let mut digits_rev: Vec<char> = Vec::new();
            for ch in pre.chars().rev() {
                if ch.is_ascii_digit() {
                    digits_rev.push(ch);
                } else if !digits_rev.is_empty() {
                    break;
                }
            }
            if !digits_rev.is_empty() {
                let s: String = digits_rev.into_iter().rev().collect();
                if let Ok(v) = s.parse::<i32>() {
                    if v > 0 {
                        depth = Some(v);
                    }
                }
            }
        }

        (rate, depth)
    }

    fn clocktime_to_s(v: gst::ClockTime) -> Option<f64> {
        let ns = v.nseconds();
        if ns == 0 {
            return None;
        }
        Some((ns as f64) / 1_000_000_000.0)
    }

    fn spectrum_time_from_structure(s: &gst::StructureRef) -> Option<(f64, &'static str)> {
        // Prefer endtime/running-time style fields carried by spectrum element
        // over pull-time query_position to avoid clock-domain skew.
        for key in ["endtime", "running-time", "stream-time", "timestamp"] {
            if let Ok(v) = s.get::<gst::ClockTime>(key) {
                if let Some(sec) = Self::clocktime_to_s(v) {
                    return Some((sec, key));
                }
            }
            if let Ok(v) = s.get::<u64>(key) {
                if v > 0 {
                    return Some(((v as f64) / 1_000_000_000.0, key));
                }
            }
            if let Ok(v) = s.get::<i64>(key) {
                if v > 0 {
                    return Some(((v as f64) / 1_000_000_000.0, key));
                }
            }
        }
        None
    }

    fn query_output_format(&self) -> (Option<i32>, Option<i32>) {
        let sink: Option<gst::Element> = self.playbin.property("audio-sink");
        let Some(sink) = sink else {
            return (None, None);
        };
        let Some(pad) = sink.static_pad("sink") else {
            return (None, None);
        };
        let caps = pad.current_caps().or_else(|| pad.allowed_caps());
        let Some(caps) = caps else {
            return (None, None);
        };
        let Some(st) = caps.structure(0) else {
            return (None, None);
        };

        let rate = st.get::<i32>("rate").ok().filter(|v| *v > 0);
        let depth = st
            .get::<String>("format")
            .ok()
            .as_deref()
            .and_then(Self::parse_depth_from_format);
        (rate, depth)
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
        if !parts.is_empty() {
            self.emit_event(EVT_TAG, &parts.join(";"));
        }
    }

    fn setup_spectrum_filter(playbin: &gst::Element) -> Option<gst::Bin> {
        let spectrum = gst::ElementFactory::make("spectrum").name("rust-spectrum").build().ok()?;
        for p in spectrum.list_properties() {
            let pn = p.name();
            if pn == "bands" {
                // Match Python analyzer defaults for similar "liveliness".
                spectrum.set_property_from_str("bands", "64");
            } else if pn == "interval" {
                // Higher temporal density to reduce perceived frame drops.
                spectrum.set_property_from_str("interval", "16000000");
            }
        }
        let mut set_msg = false;
        for p in spectrum.list_properties() {
            let pn = p.name();
            if pn == "message" {
                let _ = spectrum.set_property("message", true);
                set_msg = true;
                break;
            }
            if pn == "post-messages" {
                let _ = spectrum.set_property("post-messages", true);
                set_msg = true;
                break;
            }
        }
        if !set_msg {
            return None;
        }
        let bin = gst::Bin::new();
        if bin.add(&spectrum).is_err() {
            return None;
        }
        let sink_pad = spectrum.static_pad("sink")?;
        let src_pad = spectrum.static_pad("src")?;
        let ghost_sink = gst::GhostPad::with_target(&sink_pad).ok()?;
        let ghost_src = gst::GhostPad::with_target(&src_pad).ok()?;
        if bin.add_pad(&ghost_sink).is_err() || bin.add_pad(&ghost_src).is_err() {
            return None;
        }
        playbin.set_property("audio-filter", &bin);
        Some(bin)
    }

    fn parse_spectrum_structure(&mut self, s: &gst::StructureRef, msg_ts_s: Option<f64>) {
        if !self.spectrum_enabled {
            return;
        }
        let sname = s.name().to_ascii_lowercase();
        if !sname.contains("spectrum") {
            return;
        }
        self.spectrum_seen_msgs = self.spectrum_seen_msgs.wrapping_add(1);
        let text = s.to_string();
        let lower = text.to_ascii_lowercase();
        let Some(kpos) = lower.find("magnitude") else {
            if self.spectrum_seen_msgs % 120 == 0 {
                self.emit_event(
                    EVT_STATE,
                    &format!("spectrum-msgs={} parsed={}", self.spectrum_seen_msgs, self.spectrum_msg_count),
                );
            }
            return;
        };
        let rest = &text[kpos..];
        let mag_only = if let Some(open_pos) = rest.find('{').or_else(|| rest.find('<')) {
            let close_char = if rest.as_bytes().get(open_pos) == Some(&b'{') { '}' } else { '>' };
            if let Some(close_rel) = rest[(open_pos + 1)..].find(close_char) {
                &rest[(open_pos + 1)..(open_pos + 1 + close_rel)]
            } else {
                rest
            }
        } else {
            rest
        };
        let mut tmp = [0.0f32; SPECTRUM_BANDS_MAX];
        let mut n = 0usize;
        // Same numeric extraction contract as Python fallback parser:
        // extract only floats from magnitude payload.
        for part in mag_only.split(|c: char| !(c.is_ascii_digit() || matches!(c, '-' | '+' | '.' | 'e' | 'E'))) {
            if n >= tmp.len() {
                break;
            }
            let t = part.trim();
            if t.is_empty() {
                continue;
            }
            if let Ok(v) = t.parse::<f32>() {
                if !v.is_finite() {
                    continue;
                }
                tmp[n] = v;
                n += 1;
            }
        }
        if n == 0 {
            if self.spectrum_seen_msgs % 120 == 0 {
                self.emit_event(
                    EVT_STATE,
                    &format!("spectrum-msgs={} parsed={}", self.spectrum_seen_msgs, self.spectrum_msg_count),
                );
            }
            return;
        }
        // Prefer spectrum-structure carried timeline. Fallback to message ts, then
        // to pull-time query_position.
        let mut frame_pos_s = self.spectrum_pos_s;
        let mut ts_src = "last";
        if let Some((ts, src)) = Self::spectrum_time_from_structure(s) {
            frame_pos_s = ts;
            ts_src = src;
        } else if let Some(ts) = msg_ts_s {
            if ts.is_finite() && ts >= 0.0 {
                frame_pos_s = ts;
                ts_src = "msg-ts";
            }
        } else if let Some(pos) = self.playbin.query_position::<gst::ClockTime>() {
            frame_pos_s = (pos.nseconds() as f64) / 1_000_000_000.0;
            ts_src = "query-pos";
        }
        self.spectrum_pos_s = frame_pos_s;

        self.spectrum_vals[..n].copy_from_slice(&tmp[..n]);
        self.spectrum_len = n;
        self.spectrum_seq = self.spectrum_seq.wrapping_add(1);
        let ridx = self.spectrum_ring_write;
        self.spectrum_ring_vals[ridx] = [0.0; SPECTRUM_BANDS_MAX];
        self.spectrum_ring_vals[ridx][..n].copy_from_slice(&tmp[..n]);
        self.spectrum_ring_len[ridx] = n as u16;
        self.spectrum_ring_pos_s[ridx] = frame_pos_s;
        self.spectrum_ring_seq[ridx] = self.spectrum_seq;
        self.spectrum_ring_write = (self.spectrum_ring_write + 1) % SPECTRUM_RING_CAP;
        self.spectrum_ring_count = (self.spectrum_ring_count + 1).min(SPECTRUM_RING_CAP);
        self.spectrum_msg_count = self.spectrum_msg_count.wrapping_add(1);
        if self.spectrum_msg_count % 120 == 0 {
            let q_s = self
                .playbin
                .query_position::<gst::ClockTime>()
                .map(|p| (p.nseconds() as f64) / 1_000_000_000.0)
                .unwrap_or(-1.0);
            self.emit_event(
                EVT_STATE,
                &format!(
                    "spectrum-ts src={} frame={:.3}s query={:.3}s delta={:.3}s",
                    ts_src,
                    frame_pos_s,
                    q_s,
                    if q_s >= 0.0 { q_s - frame_pos_s } else { -1.0 }
                ),
            );
        }
        if self.spectrum_msg_count % 120 == 0 {
            self.emit_event(EVT_STATE, &format!("spectrum-frames={}", self.spectrum_msg_count));
        }
    }

    fn new() -> Result<Self, String> {
        GST_INIT.call_once(|| {
            let _ = gst::init();
        });

        let Some(playbin) = gst::ElementFactory::make("playbin").name("rust-audio-player").build().ok() else {
            return Err("failed to create playbin".to_string());
        };

        // Test helper: bypass real audio device to make CI/sandbox verification deterministic.
        if env::var("HIRESTI_RUST_AUDIO_FAKE_SINK")
            .ok()
            .map(|v| matches!(v.as_str(), "1" | "true" | "yes" | "on"))
            .unwrap_or(false)
        {
            if let Some(fake) = gst::ElementFactory::make("fakesink").name("rust-audio-fakesink").build().ok() {
                playbin.set_property("audio-sink", &fake);
            }
        }

        let filter_bin = Self::setup_spectrum_filter(&playbin);

        Ok(Self {
            playbin,
            _audio_filter_bin: filter_bin,
            uri: String::new(),
            last_error: None,
            event_cb: None,
            event_user_data: ptr::null_mut(),
            playback_rate: 1.0,
            pitch_semitones: 0.0,
            spectrum_seq: 0,
            spectrum_pos_s: 0.0,
            spectrum_vals: [0.0; SPECTRUM_BANDS_MAX],
            spectrum_len: 0,
            spectrum_ring_vals: [[0.0; SPECTRUM_BANDS_MAX]; SPECTRUM_RING_CAP],
            spectrum_ring_len: [0; SPECTRUM_RING_CAP],
            spectrum_ring_pos_s: [0.0; SPECTRUM_RING_CAP],
            spectrum_ring_seq: [0; SPECTRUM_RING_CAP],
            spectrum_ring_write: 0,
            spectrum_ring_count: 0,
            spectrum_seen_msgs: 0,
            spectrum_msg_count: 0,
            element_msg_seen: 0,
            fmt_probe_tick: 0,
            last_codec: String::new(),
            last_bitrate: 0,
            last_rate: 0,
            last_depth: 0,
            source_rate: 0,
            source_depth: 0,
            spectrum_enabled: true,
        })
    }

    fn set_error(&mut self, msg: impl Into<String>) {
        self.last_error = Some(msg.into());
    }

    fn set_state(&mut self, state: gst::State) -> c_int {
        match self.playbin.set_state(state) {
            Ok(_) => {
                self.emit_event(EVT_STATE, &format!("{state:?}"));
                0
            }
            Err(e) => {
                self.set_error(format!("set_state failed: {e}"));
                self.emit_event(EVT_ERROR, &format!("set_state failed: {e}"));
                -4
            }
        }
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

    fn pump_events(&mut self) -> c_int {
        let Some(bus) = self.playbin.bus() else {
            return 0;
        };
        let mut count = 0;
        let max_per_tick = 128;
        while let Some(msg) = bus.timed_pop(gst::ClockTime::from_mseconds(0)) {
            count += 1;
            match msg.view() {
                gst::MessageView::Eos(..) => {
                    self.emit_event(EVT_EOS, "eos");
                }
                gst::MessageView::Error(err) => {
                    let text = format!(
                        "{} ({:?})",
                        err.error(),
                        err.debug().unwrap_or_else(|| "no-debug".into())
                    );
                    self.set_error(text.clone());
                    self.emit_event(EVT_ERROR, &text);
                }
                gst::MessageView::StateChanged(sc) => {
                    // Keep only playbin state-change noise.
                    let is_self = msg
                        .src()
                        .map(|s| s.name() == self.playbin.name())
                        .unwrap_or(false);
                    if is_self {
                        self.emit_event(EVT_STATE, &format!("{:?}", sc.current()));
                    }
                }
                gst::MessageView::Element(elm) => {
                    if let Some(st) = elm.structure() {
                        self.element_msg_seen = self.element_msg_seen.wrapping_add(1);
                        if self.element_msg_seen <= 4 || self.element_msg_seen % 240 == 0 {
                            self.emit_event(EVT_STATE, &format!("elem-msg:{}", st.name()));
                        }
                        self.parse_spectrum_structure(st, None);
                    }
                }
                gst::MessageView::Tag(t) => {
                    let text = t.tags().to_string();
                    let codec = Self::parse_tag_text_value(&text, "audio-codec")
                        .or_else(|| Self::parse_tag_text_value(&text, "codec"));
                    let bitrate = Self::parse_tag_text_value(&text, "bitrate")
                        .and_then(|v| v.parse::<i32>().ok())
                        .filter(|v| *v > 0);
                    // Prefer extracting source format directly from full TAG payload.
                    let (tr, td) = Self::parse_source_rate_depth_from_codec_text(&text);
                    if let Some(v) = tr {
                        if v > 0 {
                            self.source_rate = v;
                        }
                    }
                    if let Some(v) = td {
                        if v > 0 {
                            self.source_depth = v;
                        }
                    }
                    if let Some(ref c) = codec {
                        let (sr, sd) = Self::parse_source_rate_depth_from_codec_text(c);
                        if let Some(v) = sr {
                            if v > 0 {
                                self.source_rate = v;
                            }
                        }
                        if let Some(v) = sd {
                            if v > 0 {
                                self.source_depth = v;
                            }
                        }
                    }
                    self.maybe_emit_tag_update(codec, bitrate, None, None);
                }
                _ => {}
            }
            if count >= max_per_tick {
                break;
            }
        }
        self.fmt_probe_tick = self.fmt_probe_tick.wrapping_add(1);
        if self.fmt_probe_tick % 10 == 0 {
            let (rate, depth) = self.query_output_format();
            self.maybe_emit_tag_update(None, None, rate, depth);
        }
        count
    }

    fn set_output_tuned(
        &mut self,
        driver: &str,
        device: Option<&str>,
        buffer_us: i32,
        latency_us: i32,
        exclusive: bool,
    ) -> c_int {
        let cur_state = self.playbin.state(gst::ClockTime::from_mseconds(50)).1;
        let _ = self.playbin.set_state(gst::State::Null);

        let driver_norm = driver.trim().to_lowercase();
        let device_norm = device.map(|d| d.trim()).filter(|d| !d.is_empty());

        let sink = if driver_norm.is_empty() || driver_norm.starts_with("auto") {
            gst::ElementFactory::make("autoaudiosink").name("rust-auto-sink").build().ok()
        } else if driver_norm.contains("pipewire") {
            let s = gst::ElementFactory::make("pipewiresink").name("rust-pw-sink").build().ok();
            match s {
                Some(ref elem) => {
                    if let Some(dev) = device_norm {
                        // Best effort: property presence varies by plugin/runtime.
                        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                            elem.set_property("target-object", dev);
                        }));
                    }
                    let target_buffer_us = if buffer_us > 0 { buffer_us } else { 100_000 };
                    let base_quantum = ((target_buffer_us as f64 / 1_000_000.0) * 48_000.0) as i32;
                    let mut quantum = 1024i32;
                    for p in [256i32, 512, 1024, 2048, 4096, 8192] {
                        if (p - base_quantum).abs() < (quantum - base_quantum).abs() {
                            quantum = p;
                        }
                    }
                    quantum = quantum.clamp(512, 8192);
                    // Do not pin sample-rate in stream properties (e.g. ".../48000"),
                    // otherwise PipeWire may keep stream at 48k and defeat auto rate switching.
                    let latency_node = quantum.to_string();
                    // Keep autoconnect enabled even with explicit target-object.
                    // Some PipeWire/WirePlumber setups may not auto-link when this is false,
                    // resulting in "pipeline running + spectrum active but no audible output".
                    let auto_connect = "true";
                    let props = gst::Structure::builder("props")
                        .field("node.latency", &latency_node)
                        .field("node.autoconnect", &auto_connect)
                        .field("media.role", &"Music")
                        .field("resample.quality", &12i32)
                        .build();
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        elem.set_property("stream-properties", &props);
                    }));
                    self.emit_event(
                        EVT_STATE,
                        &format!(
                            "pipewire-sink configured target={} autoconnect={} latency={}",
                            device_norm.unwrap_or("default"),
                            auto_connect,
                            latency_node
                        ),
                    );
                    s
                }
                None => {
                    self.set_error("pipewiresink unavailable");
                    self.emit_event(EVT_ERROR, "pipewiresink unavailable");
                    return -11;
                }
            }
        } else if driver_norm.contains("pulse") {
            let s = gst::ElementFactory::make("pulsesink").name("rust-pa-sink").build().ok();
            match s {
                Some(ref elem) => {
                    if let Some(dev) = device_norm {
                        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                            elem.set_property("device", dev);
                        }));
                    }
                    let target_buffer = if buffer_us > 0 { buffer_us } else { 100_000 };
                    let target_latency = if latency_us > 0 { latency_us } else { 10_000 };
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        elem.set_property("buffer-time", i64::from(target_buffer));
                    }));
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        elem.set_property("latency-time", i64::from(target_latency));
                    }));
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        elem.set_property("provide-clock", true);
                    }));
                    s
                }
                None => {
                    self.set_error("pulsesink unavailable");
                    self.emit_event(EVT_ERROR, "pulsesink unavailable");
                    return -12;
                }
            }
        } else if driver_norm.contains("alsa") {
            let s = gst::ElementFactory::make("alsasink").name("rust-alsa-sink").build().ok();
            match s {
                Some(ref elem) => {
                    if let Some(dev) = device_norm {
                        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                            elem.set_property("device", dev);
                        }));
                    }
                    let target_buffer = if buffer_us > 0 { buffer_us } else { 100_000 };
                    let target_latency = if latency_us > 0 { latency_us } else { 10_000 };
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        elem.set_property("buffer-time", i64::from(target_buffer));
                    }));
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        elem.set_property("latency-time", i64::from(target_latency));
                    }));
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        elem.set_property("provide-clock", true);
                    }));
                    if exclusive {
                        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                            // `slave-method` is an enum property on GstAlsaSink.
                            // Setting it as integer can panic in Rust bindings
                            // (type mismatch). Use enum nick string instead.
                            if elem.find_property("slave-method").is_some() {
                                elem.set_property_from_str("slave-method", "none");
                            }
                        }));
                    }
                    s
                }
                None => {
                    self.set_error("alsasink unavailable");
                    self.emit_event(EVT_ERROR, "alsasink unavailable");
                    return -13;
                }
            }
        } else {
            self.set_error(format!("unsupported driver: {driver}"));
            self.emit_event(EVT_ERROR, &format!("unsupported driver: {driver}"));
            return -14;
        };

        let Some(sink_elem) = sink else {
            self.set_error("failed to create audio sink");
            self.emit_event(EVT_ERROR, "failed to create audio sink");
            return -15;
        };

        self.playbin.set_property("audio-sink", &sink_elem);
        self.emit_event(
            EVT_STATE,
            &format!("output-switched driver={driver} device={}", device_norm.unwrap_or("default")),
        );

        // Restore runtime state.
        let target = if cur_state == gst::State::Playing {
            gst::State::Playing
        } else if cur_state == gst::State::Paused {
            gst::State::Paused
        } else {
            gst::State::Null
        };
        self.set_state(target)
    }

    fn set_output(&mut self, driver: &str, device: Option<&str>) -> c_int {
        self.set_output_tuned(driver, device, 100_000, 10_000, false)
    }

    fn apply_playback_rate(&mut self) -> c_int {
        // HiFi mode: do not alter transport rate in Rust path.
        self.emit_event(EVT_STATE, "playback-rate=1.000 (hifi-locked)");
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
    let max_n = if max_len <= 0 { 0usize } else { max_len as usize };
    let n = engine.spectrum_len.min(max_n).min(engine.spectrum_vals.len());
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
    if out_vals.is_null() || out_frames.is_null() || out_lens.is_null() || out_pos_s.is_null() || out_seq.is_null() {
        return -2;
    }
    let max_f = if max_frames <= 0 { 0usize } else { max_frames as usize };
    let max_b = if max_bands <= 0 { 0usize } else { max_bands as usize };
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
        let len = (engine.spectrum_ring_len[idx] as usize).min(max_b).min(SPECTRUM_BANDS_MAX);
        let base = written * max_b;
        unsafe {
            ptr::copy_nonoverlapping(engine.spectrum_ring_vals[idx].as_ptr(), out_vals.add(base), len);
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
    engine.spectrum_enabled = enabled != 0;
    if !engine.spectrum_enabled {
        engine.spectrum_len = 0;
        engine.spectrum_ring_count = 0;
    }
    0
}

fn list_pulseaudio_sinks() -> Vec<(String, Option<String>)> {
    let mut out: Vec<(String, Option<String>)> = Vec::new();
    let cmd = Command::new("pactl").args(["list", "sinks"]).output();
    let Ok(res) = cmd else {
        return out;
    };
    if !res.status.success() {
        return out;
    }
    let text = String::from_utf8_lossy(&res.stdout);
    for block in text.split("Sink #") {
        let mut dev_id: Option<String> = None;
        let mut desc: Option<String> = None;
        for raw in block.lines() {
            let line = raw.trim();
            if let Some(rest) = line.strip_prefix("Name:") {
                let n = rest.trim().to_string();
                if !n.is_empty() {
                    dev_id = Some(n);
                }
            } else if let Some(rest) = line.strip_prefix("Description:") {
                let d = rest.trim().to_string();
                if !d.is_empty() {
                    desc = Some(d);
                }
            }
        }
        if let Some(id) = dev_id {
            if id.ends_with(".monitor") {
                continue;
            }
            let name = desc.unwrap_or_else(|| id.clone());
            out.push((name, Some(id)));
        }
    }
    out
}

fn list_pipewire_sinks() -> Vec<(String, Option<String>)> {
    Engine::ensure_pw_init();
    let result = (|| -> Result<Vec<(String, Option<String>)>, String> {
        let mainloop = PwMainLoop::new(None).map_err(|e| format!("pw mainloop: {e}"))?;
        let context = PwContext::new(&mainloop).map_err(|e| format!("pw context: {e}"))?;
        let core = context.connect(None).map_err(|e| format!("pw connect: {e}"))?;
        let registry = core.get_registry().map_err(|e| format!("pw registry: {e}"))?;

        let done = Rc::new(Cell::new(false));
        let sinks: Rc<RefCell<Vec<(String, Option<String>)>>> = Rc::new(RefCell::new(Vec::new()));

        let done_clone = done.clone();
        let loop_clone = mainloop.clone();
        let sinks_clone = sinks.clone();

        let _listener_reg = registry
            .add_listener_local()
            .global(move |global| {
                if global.type_ != ObjectType::Node {
                    return;
                }
                let Some(props) = global.props else {
                    return;
                };
                let media_class = props.get("media.class").unwrap_or("");
                // Only output sink nodes are valid target-object candidates.
                if !media_class.starts_with("Audio/Sink") {
                    return;
                }
                let node_name = props.get("node.name").unwrap_or("");
                // Skip monitor endpoints from sink list.
                if node_name.is_empty() || node_name.contains(".monitor") {
                    return;
                }
                let name = props
                    .get("node.description")
                    .or_else(|| props.get("device.description"))
                    .or_else(|| props.get("node.nick"))
                    .or_else(|| props.get("node.name"))
                    .unwrap_or("Audio Sink")
                    .to_string();
                let dev_id = Some(node_name.to_string());
                sinks_clone.borrow_mut().push((name, dev_id));
            })
            .register();

        let pending = core.sync(0).map_err(|e| format!("pw sync: {e}"))?;
        let _listener_core = core
            .add_listener_local()
            .done(move |id, seq| {
                if id == pw::core::PW_ID_CORE && seq == pending {
                    done_clone.set(true);
                    loop_clone.quit();
                }
            })
            .register();

        while !done.get() {
            mainloop.run();
        }

        let mut out = sinks.borrow().clone();
        out.sort_by_key(|(n, dev)| {
            let hay = format!("{} {}", n.to_ascii_uppercase(), dev.clone().unwrap_or_default().to_ascii_uppercase());
            if hay.contains("USB") {
                0
            } else {
                1
            }
        });
        out.dedup_by(|a, b| a.1 == b.1 && a.0 == b.0);
        Ok(out)
    })();
    result.unwrap_or_default()
}

fn list_alsa_cards() -> Vec<(String, Option<String>)> {
    let mut out: Vec<(String, Option<String>)> = Vec::new();
    let Ok(content) = std::fs::read_to_string("/proc/asound/cards") else {
        return out;
    };
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
        let long_name = line[(dash_pos + 3)..].trim();
        if long_name.is_empty() {
            continue;
        }
        let friendly = format!("{long_name} (Card {idx})");
        let hw_id = format!("hw:{idx},0");
        out.push((friendly, Some(hw_id)));
    }
    out.sort_by_key(|(name, _)| if name.contains("USB") { 0 } else { 1 });
    out
}

fn devices_for_driver(driver: &str) -> Vec<(String, Option<String>)> {
    let d = driver.trim();
    if d == "Auto (Default)" || d.eq_ignore_ascii_case("auto") {
        return vec![("Default Output".to_string(), None)];
    }
    if d == "PipeWire" {
        let mut out = vec![("Default System Output".to_string(), None)];
        // For PipeWire driver, prefer pure PipeWire-discovered targets so target-object is always valid.
        let mut pw_only = list_pipewire_sinks();
        if pw_only.is_empty() {
            // Safety fallback only when PipeWire enumeration is fully unavailable.
            pw_only = list_pulseaudio_sinks();
        }
        out.extend(pw_only);
        return out;
    }
    if d == "PulseAudio" {
        let mut out = vec![("Default System Output".to_string(), None)];
        out.extend(list_pulseaudio_sinks());
        return out;
    }
    if d == "ALSA" {
        return list_alsa_cards();
    }
    Vec::new()
}

fn card_from_pipewire_output_node(device_id: &str) -> Option<String> {
    let dev = device_id.trim();
    if !dev.starts_with("alsa_output.") {
        return None;
    }
    let mut core = dev["alsa_output.".len()..].to_string();
    let suffixes = [
        ".analog-stereo",
        ".pro-output-0",
        ".pro-output-1",
        ".pro-output-2",
        ".pro-output-3",
        ".multichannel-output",
        ".iec958-stereo",
    ];
    for sx in suffixes {
        if core.ends_with(sx) {
            let len = core.len() - sx.len();
            core.truncate(len);
            break;
        }
    }
    if core.is_empty() {
        return None;
    }
    Some(format!("alsa_card.{core}"))
}

fn pactl_card_active_profile(card: &str) -> Option<String> {
    let out = Command::new("pactl").args(["list", "cards"]).output().ok()?;
    if !out.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&out.stdout);
    let mut current_card = String::new();
    for line in text.lines() {
        let s = line.trim();
        if let Some(rest) = s.strip_prefix("Name:") {
            current_card = rest.trim().to_string();
            continue;
        }
        if current_card == card {
            if let Some(rest) = s.strip_prefix("Active Profile:") {
                return Some(rest.trim().to_string());
            }
        }
    }
    None
}

fn pactl_set_card_profile(card: &str, profile: &str) -> Result<(), String> {
    let out = Command::new("pactl")
        .args(["set-card-profile", card, profile])
        .output()
        .map_err(|e| format!("pactl exec failed: {e}"))?;
    if out.status.success() {
        return Ok(());
    }
    Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
}

fn ensure_pipewire_pro_audio_for_device(device_id: &str) -> Result<String, String> {
    let card = card_from_pipewire_output_node(device_id)
        .ok_or_else(|| "unsupported or empty device id".to_string())?;
    if let Some(active) = pactl_card_active_profile(&card) {
        if active == "pro-audio" {
            return Ok(card);
        }
    }
    let mut last_err = String::new();
    for _ in 0..3 {
        if let Err(e) = pactl_set_card_profile(&card, "pro-audio") {
            last_err = e;
        }
        thread::sleep(Duration::from_millis(120));
        if let Some(active) = pactl_card_active_profile(&card) {
            if active == "pro-audio" {
                return Ok(card);
            }
        }
    }
    Err(format!("failed to switch {card} to pro-audio: {last_err}"))
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
        let boxed = Box::from_raw(ptr);
        let _ = boxed.playbin.set_state(gst::State::Null);
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

    let _ = engine.playbin.set_state(gst::State::Null);
    engine.playbin.set_property("uri", s);
    engine.uri = s.to_string();
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
    let rc = engine.set_state(gst::State::Playing);
    if rc == 0 && (engine.playback_rate - 1.0).abs() > f64::EPSILON {
        let _ = engine.apply_playback_rate();
    }
    rc
}

#[no_mangle]
pub extern "C" fn rac_pause(ptr: *mut Engine) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_state(gst::State::Paused)
}

#[no_mangle]
pub extern "C" fn rac_stop(ptr: *mut Engine) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_state(gst::State::Null)
}

#[no_mangle]
pub extern "C" fn rac_seek(ptr: *mut Engine, pos_s: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    let clamped = if pos_s.is_finite() { pos_s.max(0.0) } else { 0.0 };
    let rc = engine.playbin.seek_simple(
        // Keep FLUSH for responsiveness/stability across sinks; UI side handles
        // brief position rebound after flush-seek.
        gst::SeekFlags::FLUSH | gst::SeekFlags::KEY_UNIT,
        gst::ClockTime::from_nseconds((clamped * 1_000_000_000.0) as u64),
    );
    if rc.is_ok() {
        0
    } else {
        engine.set_error("seek failed");
        engine.emit_event(EVT_ERROR, "seek failed");
        -3
    }
}

#[no_mangle]
pub extern "C" fn rac_set_volume(ptr: *mut Engine, vol: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    let v = if vol.is_finite() { vol.clamp(0.0, 1.5) } else { 1.0 };
    engine.playbin.set_property("volume", v);
    0
}

#[no_mangle]
pub extern "C" fn rac_get_position(ptr: *const Engine, pos_out: *mut c_double) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if pos_out.is_null() {
        return -2;
    }

    let pos = match engine.playbin.query_position::<gst::ClockTime>() {
        Some(p) => (p.nseconds() as f64) / 1_000_000_000.0,
        None => 0.0,
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

    let dur = match engine.playbin.query_duration::<gst::ClockTime>() {
        Some(d) => (d.nseconds() as f64) / 1_000_000_000.0,
        None => 0.0,
    };

    // SAFETY: dur_out is a valid output pointer from caller.
    unsafe {
        *dur_out = dur;
    }
    0
}

fn probe_latency(engine: &Engine) -> (f64, &'static str) {
    // Primary path: standard GStreamer latency query.
    let mut q = gst::query::Latency::new();
    if engine.playbin.query(&mut q) {
        let (_live, min_lat, max_lat) = q.result();
        let min_ns = min_lat.nseconds();
        let max_ns = max_lat.map(|v| v.nseconds()).unwrap_or(0);
        // For A/V sync, prefer the effective upper bound when available.
        // Many pipelines (network + decode + queue + sink) report a much more
        // realistic playout delay in max-latency than in min-latency.
        if max_ns > 0 && max_ns < 5_000_000_000 {
            return ((max_ns as f64) / 1_000_000_000.0, "gst-query-max");
        }
        if min_ns > 0 && min_ns < 5_000_000_000 {
            return ((min_ns as f64) / 1_000_000_000.0, "gst-query-min");
        }
    }

    // Fallback: read sink latency/buffer properties when query reports 0.
    let sink: Option<gst::Element> = engine.playbin.property("audio-sink");
    if let Some(sink) = sink {
        if sink.find_property("latency-time").is_some() {
            let v: i64 = sink.property("latency-time");
            if v > 0 {
                return ((v as f64) / 1_000_000.0, "sink-latency-time");
            }
        }
        if sink.find_property("buffer-time").is_some() {
            let v: i64 = sink.property("buffer-time");
            if v > 0 {
                return ((v as f64) / 1_000_000.0, "sink-buffer-time");
            }
        }
    }
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
        *lat_out = if latency_s.is_finite() && latency_s > 0.0 { latency_s } else { 0.0 };
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
        if latency_s.is_finite() && latency_s > 0.0 { latency_s } else { 0.0 },
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
    let (_, state, _) = engine.playbin.state(gst::ClockTime::from_mseconds(50));
    if state == gst::State::Playing {
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

#[no_mangle]
pub extern "C" fn rac_set_event_callback(ptr: *mut Engine, cb: Option<EventCallback>, user_data: *mut c_void) -> c_int {
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
pub extern "C" fn rac_set_output(ptr: *mut Engine, driver: *const c_char, device: *const c_char) -> c_int {
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

    engine.set_output_tuned(
        drv_str,
        dev_opt,
        buffer_us,
        latency_us,
        exclusive != 0,
    )
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
    engine.playback_rate = 1.0;
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
pub extern "C" fn rac_set_pipewire_clock_rate(ptr: *mut Engine, rate: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    match Engine::pipewire_set_clock_force_rate(rate) {
        Ok(()) => {
            engine.emit_event(EVT_STATE, &format!("pipewire clock.force-rate={}", rate));
            0
        }
        Err(e) => {
            engine.set_error(format!("pipewire clock.force-rate failed: {e}"));
            engine.emit_event(EVT_ERROR, &format!("pipewire clock.force-rate failed: {e}"));
            -2
        }
    }
}

#[no_mangle]
pub extern "C" fn rac_set_pipewire_allowed_rates(ptr: *mut Engine, csv: *const c_char) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if csv.is_null() {
        engine.set_error("null allowed-rates csv");
        return -2;
    }
    let csv_s = unsafe { CStr::from_ptr(csv) }.to_string_lossy().to_string();
    match Engine::pipewire_set_clock_allowed_rates_csv(&csv_s) {
        Ok(_) => {
            engine.emit_event(EVT_STATE, &format!("pipewire clock.allowed-rates={}", csv_s));
            0
        }
        Err(e) => {
            engine.set_error(format!("pipewire clock.allowed-rates failed: {e}"));
            engine.emit_event(EVT_ERROR, &format!("pipewire clock.allowed-rates failed: {e}"));
            -3
        }
    }
}

#[no_mangle]
pub extern "C" fn rac_set_pipewire_pro_audio(ptr: *mut Engine, device: *const c_char) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if device.is_null() {
        engine.set_error("null device for pro-audio switch");
        return -2;
    }
    let dev_s = unsafe { CStr::from_ptr(device) }.to_string_lossy().to_string();
    match ensure_pipewire_pro_audio_for_device(&dev_s) {
        Ok(card) => {
            engine.emit_event(EVT_STATE, &format!("pipewire card profile=pro-audio card={card}"));
            0
        }
        Err(e) => {
            engine.set_error(format!("pipewire pro-audio switch failed: {e}"));
            engine.emit_event(EVT_ERROR, &format!("pipewire pro-audio switch failed: {e}"));
            -3
        }
    }
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
    let (pw_force_rate, pw_allowed_raw, pw_quantum, pw_rate) =
        Engine::pipewire_read_settings_metadata().unwrap_or((0, String::new(), 0, 0));
    let mut pw_latency_ms = Engine::pipewire_query_app_node_latency_ms().unwrap_or(-1.0);
    if pw_latency_ms < 0.0 && pw_quantum > 0 && pw_rate > 0 {
        pw_latency_ms = (pw_quantum as f64 / pw_rate as f64) * 1000.0;
    }

    let mut s = String::from("{");
    s.push_str("\"pipewire\":{");
    s.push_str(&format!("\"force_rate\":{},", pw_force_rate.max(0)));
    s.push_str(&format!("\"quantum\":{},\"rate\":{},", pw_quantum.max(0), pw_rate.max(0)));
    s.push_str(&format!("\"latency_ms\":{},", if pw_latency_ms >= 0.0 { pw_latency_ms } else { -1.0 }));
    s.push_str("\"allowed_rates_raw\":\"");
    s.push_str(&json_escape(&pw_allowed_raw));
    s.push_str("\"},");

    s.push_str("\"output\":{");
    s.push_str(&format!(
        "\"session_rate\":{},\"session_depth\":{},\"hardware_rate\":{},\"hardware_depth\":{}",
        session_rate.unwrap_or(0),
        session_depth.unwrap_or(0),
        hw_rate.unwrap_or(0),
        hw_depth.unwrap_or(0),
    ));
    s.push_str("},");
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
