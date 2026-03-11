use gst::prelude::*;
use gst::glib;
use gstreamer as gst;
use std::collections::HashMap;

// GstBaseTransform passthrough via raw FFI.  libgstbase-1.0 is always present
// when GStreamer is installed; we link it explicitly in build.rs.
#[link(name = "gstbase-1.0")]
extern "C" {
    fn gst_base_transform_get_type() -> glib::ffi::GType;
    fn gst_base_transform_set_passthrough(
        trans: *mut glib::gobject_ffi::GObject,
        passthrough: glib::ffi::gboolean,
    );
}

/// Try to set GStreamer BaseTransform passthrough mode on `element`.
/// Returns true if the element is a BaseTransform subclass and the call succeeded.
fn try_set_element_passthrough(element: &gst::Element, passthrough: bool) -> bool {
    unsafe {
        let bt_type = gst_base_transform_get_type();
        let instance = element.as_ptr() as *mut glib::gobject_ffi::GTypeInstance;
        if glib::gobject_ffi::g_type_check_instance_is_a(instance, bt_type) == glib::ffi::GFALSE {
            return false;
        }
        gst_base_transform_set_passthrough(
            element.as_ptr() as *mut glib::gobject_ffi::GObject,
            if passthrough { glib::ffi::GTRUE } else { glib::ffi::GFALSE },
        );
        true
    }
}
use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_float, c_uint, c_void};
use std::panic::{catch_unwind, AssertUnwindSafe};

pub fn refresh_gstreamer_registry() {
    let _ = gst::Registry::update();
}

fn host_managed_port_scalar(symbol: &str, enabled: bool) -> f32 {
    if symbol.trim().eq_ignore_ascii_case("bypass") {
        if enabled { 0.0 } else { 1.0 }
    } else if enabled {
        1.0
    } else {
        0.0
    }
}

fn host_managed_port_bool(symbol: &str, enabled: bool) -> bool {
    if symbol.trim().eq_ignore_ascii_case("bypass") {
        !enabled
    } else {
        enabled
    }
}

pub fn is_host_managed_port_symbol(symbol: &str) -> bool {
    matches!(
        symbol.trim().to_ascii_lowercase().as_str(),
        "enabled" | "enable" | "bypass"
    )
}

// ── Config ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, PartialEq)]
pub struct Lv2SlotConfig {
    pub slot_id: String,
    pub uri: String,
    pub enabled: bool,
    /// Control port values keyed by port symbol.
    pub port_values: HashMap<String, f32>,
}

impl Lv2SlotConfig {
    pub fn new(slot_id: impl Into<String>, uri: impl Into<String>) -> Self {
        Self {
            slot_id: slot_id.into(),
            uri: uri.into(),
            enabled: true,
            port_values: HashMap::new(),
        }
    }

    pub fn is_active(&self) -> bool {
        self.enabled
    }

    pub fn set_enabled(&mut self, v: bool) {
        self.enabled = v;
    }

    pub fn set_port_value(&mut self, symbol: impl Into<String>, value: f32) {
        let symbol = symbol.into();
        if is_host_managed_port_symbol(symbol.as_str()) {
            self.port_values.remove(symbol.as_str());
            return;
        }
        self.port_values.insert(symbol, value);
    }
}

// ── URI → GStreamer factory name ──────────────────────────────────────────────

/// Convert an LV2 plugin URI to the GStreamer element factory name.
///
/// GStreamer's LV2 plugin (gst-plugins-bad) registers each plugin as a separate
/// element whose name is the URI with the scheme (`http://`) stripped and all
/// non-alphanumeric characters replaced with `-`.
///
/// Example: `http://lsp-plug.in/plugins/lv2/compressor_stereo`
///          → `lsp-plug-in-plugins-lv2-compressor-stereo`
pub fn uri_to_gst_factory_name(uri: &str) -> String {
    let after_scheme = if let Some(pos) = uri.find("://") {
        &uri[pos + 3..]
    } else {
        uri
    };
    after_scheme
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
        .collect()
}

// ── GStreamer node ────────────────────────────────────────────────────────────
//
// Each LV2 slot is wrapped in a GStreamer Bin:
//
//   [ghost-sink] → audioconvert → lv2_element → audioconvert → [ghost-src]
//
// This lets the main pipeline stay at F64LE while the LV2 element works at
// whatever format it natively supports (usually F32LE).

#[derive(Debug)]
pub struct Lv2Node {
    /// The wrapper bin exposed to the pipeline.
    wrapper: gst::Bin,
    /// The raw LV2 element inside the bin (used for property updates).
    lv2_element: gst::Element,
}

impl Lv2Node {
    pub fn new(config: &Lv2SlotConfig) -> Result<Self, String> {
        let factory_name = uri_to_gst_factory_name(&config.uri);
        let lv2_element = gst::ElementFactory::make(&factory_name)
            .name(format!("rust-dsp-{}", config.slot_id))
            .build()
            .map_err(|e| {
                format!(
                    "LV2 plugin '{}' unavailable as GStreamer element '{}': {e}",
                    config.uri, factory_name
                )
            })?;

        let pre_conv = gst::ElementFactory::make("audioconvert")
            .name(format!("rust-dsp-{}-pre", config.slot_id))
            .build()
            .map_err(|e| format!("audioconvert unavailable: {e}"))?;
        let post_conv = gst::ElementFactory::make("audioconvert")
            .name(format!("rust-dsp-{}-post", config.slot_id))
            .build()
            .map_err(|e| format!("audioconvert unavailable: {e}"))?;

        let bin = gst::Bin::new();
        bin.add(&pre_conv).map_err(|_| "failed to add lv2 pre-convert".to_string())?;
        bin.add(&lv2_element).map_err(|_| "failed to add lv2 element to bin".to_string())?;
        bin.add(&post_conv).map_err(|_| "failed to add lv2 post-convert".to_string())?;
        pre_conv
            .link(&lv2_element)
            .map_err(|_| format!("failed to link pre-conv → lv2 ({})", config.uri))?;
        lv2_element
            .link(&post_conv)
            .map_err(|_| format!("failed to link lv2 → post-conv ({})", config.uri))?;

        let sink_pad = pre_conv
            .static_pad("sink")
            .ok_or_else(|| "lv2 pre-conv has no sink pad".to_string())?;
        let src_pad = post_conv
            .static_pad("src")
            .ok_or_else(|| "lv2 post-conv has no src pad".to_string())?;
        let ghost_sink = gst::GhostPad::with_target(&sink_pad)
            .map_err(|_| "failed to create lv2 bin ghost sink".to_string())?;
        let ghost_src = gst::GhostPad::with_target(&src_pad)
            .map_err(|_| "failed to create lv2 bin ghost src".to_string())?;
        bin.add_pad(&ghost_sink)
            .map_err(|_| "failed to add lv2 bin ghost sink pad".to_string())?;
        bin.add_pad(&ghost_src)
            .map_err(|_| "failed to add lv2 bin ghost src pad".to_string())?;

        let node = Self { wrapper: bin, lv2_element };
        node.apply_config(config);
        Ok(node)
    }

    /// Returns the wrapper bin element for insertion into the parent pipeline.
    pub fn element(&self) -> gst::Element {
        self.wrapper.clone().upcast()
    }

    /// Apply port values from config to the inner LV2 element.
    ///
    /// Uses GStreamer BaseTransform passthrough as the primary bypass mechanism
    /// so the plugin is skipped in the signal chain when disabled, regardless
    /// of whether the plugin implements LV2 port-based bypass.  Port values are
    /// still mirrored to keep plugin state consistent.
    pub fn apply_config(&self, config: &Lv2SlotConfig) {
        // Mirror the slot state into the plugin's own enabled/bypass property
        // when present.  This is set BEFORE the BaseTransform passthrough call
        // so that if the plugin's property setter also calls set_passthrough
        // internally, our final call below wins.
        for host_symbol in ["enabled", "enable", "bypass"] {
            let Some(pspec) = self.lv2_element.find_property(host_symbol) else {
                continue;
            };
            let vtype = pspec.value_type();
            if vtype == bool::static_type() {
                let _ = safe_set_property_bool(
                    &self.lv2_element,
                    pspec.name(),
                    host_managed_port_bool(host_symbol, config.enabled),
                );
            } else if vtype == f32::static_type() {
                let _ = safe_set_property_f32(
                    &self.lv2_element,
                    pspec.name(),
                    &pspec,
                    host_managed_port_scalar(host_symbol, config.enabled),
                );
            } else if vtype == f64::static_type() {
                let _ = safe_set_property_f64(
                    &self.lv2_element,
                    pspec.name(),
                    &pspec,
                    host_managed_port_scalar(host_symbol, config.enabled) as f64,
                );
            } else if vtype == i32::static_type() {
                let _ = safe_set_property_i32(
                    &self.lv2_element,
                    pspec.name(),
                    &pspec,
                    host_managed_port_scalar(host_symbol, config.enabled).round() as i32,
                );
            } else if vtype == u32::static_type() {
                let _ = safe_set_property_u32(
                    &self.lv2_element,
                    pspec.name(),
                    &pspec,
                    host_managed_port_scalar(host_symbol, config.enabled).max(0.0).round() as u32,
                );
            }
        }
        for (symbol, &value) in &config.port_values {
            if is_host_managed_port_symbol(symbol.as_str()) {
                continue;
            }
            let Some((prop_name, pspec)) = resolve_element_property(&self.lv2_element, symbol.as_str()) else {
                continue;
            };
            let vtype = pspec.value_type();
            if vtype == bool::static_type() {
                let _ = safe_set_property_bool(&self.lv2_element, prop_name.as_str(), value != 0.0);
            } else if vtype == f32::static_type() {
                let _ = safe_set_property_f32(&self.lv2_element, prop_name.as_str(), &pspec, value);
            } else if vtype == f64::static_type() {
                let _ = safe_set_property_f64(&self.lv2_element, prop_name.as_str(), &pspec, value as f64);
            } else if vtype == i32::static_type() {
                let _ = safe_set_property_i32(
                    &self.lv2_element,
                    prop_name.as_str(),
                    &pspec,
                    value.round() as i32,
                );
            } else if vtype == u32::static_type() {
                let _ = safe_set_property_u32(
                    &self.lv2_element,
                    prop_name.as_str(),
                    &pspec,
                    value.max(0.0).round() as u32,
                );
            } else if vtype == i64::static_type() {
                let _ = safe_set_property_i64(
                    &self.lv2_element,
                    prop_name.as_str(),
                    &pspec,
                    value.round() as i64,
                );
            } else if vtype == u64::static_type() {
                let _ = safe_set_property_u64(
                    &self.lv2_element,
                    prop_name.as_str(),
                    &pspec,
                    value.max(0.0).round() as u64,
                );
            }
            // Unknown types: skip silently.
        }
        // Primary bypass: GStreamer BaseTransform passthrough.  Called LAST
        // so it always wins over any plugin-internal set_passthrough calls
        // that the property setters above might have triggered.
        try_set_element_passthrough(&self.lv2_element, !config.enabled);
    }
}

fn resolve_element_property(element: &gst::Element, symbol: &str) -> Option<(String, glib::ParamSpec)> {
    if let Some(pspec) = element.find_property(symbol) {
        return Some((pspec.name().to_string(), pspec));
    }
    let dashed = symbol.replace('_', "-");
    element
        .find_property(dashed.as_str())
        .map(|pspec| (pspec.name().to_string(), pspec))
}

fn safe_set_property_bool(element: &gst::Element, name: &str, value: bool) -> bool {
    catch_unwind(AssertUnwindSafe(|| {
        element.set_property(name, value);
    }))
    .is_ok()
}

fn safe_set_property_f32(element: &gst::Element, name: &str, pspec: &glib::ParamSpec, value: f32) -> bool {
    let clamped = pspec
        .downcast_ref::<glib::ParamSpecFloat>()
        .map(|p| value.clamp(p.minimum(), p.maximum()))
        .unwrap_or(value);
    catch_unwind(AssertUnwindSafe(|| {
        element.set_property(name, clamped);
    }))
    .is_ok()
}

fn safe_set_property_f64(element: &gst::Element, name: &str, pspec: &glib::ParamSpec, value: f64) -> bool {
    let clamped = pspec
        .downcast_ref::<glib::ParamSpecDouble>()
        .map(|p| value.clamp(p.minimum(), p.maximum()))
        .unwrap_or(value);
    catch_unwind(AssertUnwindSafe(|| {
        element.set_property(name, clamped);
    }))
    .is_ok()
}

fn safe_set_property_i32(element: &gst::Element, name: &str, pspec: &glib::ParamSpec, value: i32) -> bool {
    if let Some(p) = pspec.downcast_ref::<glib::ParamSpecInt>() {
        let clamped = value.clamp(p.minimum(), p.maximum());
        return catch_unwind(AssertUnwindSafe(|| {
            element.set_property(name, clamped);
        }))
        .is_ok();
    }
    if let Some(p) = pspec.downcast_ref::<glib::ParamSpecEnum>() {
        let enum_class = p.enum_class();
        let fallback = p.default_value_as_i32();
        let chosen = if enum_class.values().iter().any(|v| v.value() == value) {
            value
        } else {
            fallback
        };
        return catch_unwind(AssertUnwindSafe(|| {
            element.set_property(name, chosen);
        }))
        .is_ok();
    }
    catch_unwind(AssertUnwindSafe(|| {
        element.set_property(name, value);
    }))
    .is_ok()
}

fn safe_set_property_u32(element: &gst::Element, name: &str, pspec: &glib::ParamSpec, value: u32) -> bool {
    let clamped = pspec
        .downcast_ref::<glib::ParamSpecUInt>()
        .map(|p| value.clamp(p.minimum(), p.maximum()))
        .unwrap_or(value);
    catch_unwind(AssertUnwindSafe(|| {
        element.set_property(name, clamped);
    }))
    .is_ok()
}

fn safe_set_property_i64(element: &gst::Element, name: &str, pspec: &glib::ParamSpec, value: i64) -> bool {
    let clamped = pspec
        .downcast_ref::<glib::ParamSpecInt64>()
        .map(|p| value.clamp(p.minimum(), p.maximum()))
        .unwrap_or(value);
    catch_unwind(AssertUnwindSafe(|| {
        element.set_property(name, clamped);
    }))
    .is_ok()
}

fn safe_set_property_u64(element: &gst::Element, name: &str, pspec: &glib::ParamSpec, value: u64) -> bool {
    let clamped = pspec
        .downcast_ref::<glib::ParamSpecUInt64>()
        .map(|p| value.clamp(p.minimum(), p.maximum()))
        .unwrap_or(value);
    catch_unwind(AssertUnwindSafe(|| {
        element.set_property(name, clamped);
    }))
    .is_ok()
}

fn gst_property_info(element: &gst::Element, symbol: &str) -> Option<(String, f32, f32, f32, bool, bool)> {
    let (name, pspec) = resolve_element_property(element, symbol)?;
    let vtype = pspec.value_type();
    if vtype == bool::static_type() {
        return Some((name, 0.0, 1.0, 0.0, true, false));
    }
    if let Some(p) = pspec.downcast_ref::<glib::ParamSpecFloat>() {
        return Some((name, p.minimum(), p.maximum(), p.default_value(), false, false));
    }
    if let Some(p) = pspec.downcast_ref::<glib::ParamSpecDouble>() {
        return Some((name, p.minimum() as f32, p.maximum() as f32, p.default_value() as f32, false, false));
    }
    if let Some(p) = pspec.downcast_ref::<glib::ParamSpecInt>() {
        return Some((name, p.minimum() as f32, p.maximum() as f32, p.default_value() as f32, false, true));
    }
    if let Some(p) = pspec.downcast_ref::<glib::ParamSpecUInt>() {
        return Some((name, p.minimum() as f32, p.maximum() as f32, p.default_value() as f32, false, true));
    }
    if let Some(p) = pspec.downcast_ref::<glib::ParamSpecInt64>() {
        return Some((name, p.minimum() as f32, p.maximum() as f32, p.default_value() as f32, false, true));
    }
    if let Some(p) = pspec.downcast_ref::<glib::ParamSpecUInt64>() {
        return Some((name, p.minimum() as f32, p.maximum() as f32, p.default_value() as f32, false, true));
    }
    if let Some(p) = pspec.downcast_ref::<glib::ParamSpecEnum>() {
        let enum_class = p.enum_class();
        let values = enum_class.values();
        let min = values.iter().map(|v| v.value()).min().unwrap_or(0) as f32;
        let max = values.iter().map(|v| v.value()).max().unwrap_or(0) as f32;
        let default = p.default_value_as_i32() as f32;
        return Some((name, min, max, default, false, true));
    }
    None
}

// ── lilv C bindings ───────────────────────────────────────────────────────────

#[allow(non_camel_case_types)]
type LilvWorld = c_void;
type LilvIter = c_void;

extern "C" {
    fn lilv_world_new() -> *mut LilvWorld;
    fn lilv_world_free(world: *mut LilvWorld);
    fn lilv_world_load_all(world: *mut LilvWorld);
    fn lilv_world_get_all_plugins(world: *const LilvWorld) -> *const c_void;

    fn lilv_plugins_size(col: *const c_void) -> c_uint;
    fn lilv_plugins_begin(col: *const c_void) -> *mut LilvIter;
    fn lilv_plugins_next(col: *const c_void, i: *mut LilvIter) -> *mut LilvIter;
    fn lilv_plugins_is_end(col: *const c_void, i: *const LilvIter) -> bool;
    fn lilv_plugins_get(col: *const c_void, i: *const LilvIter) -> *const c_void;

    fn lilv_plugin_get_uri(plugin: *const c_void) -> *const c_void;
    fn lilv_plugin_get_name(plugin: *const c_void) -> *mut c_void;
    fn lilv_plugin_get_num_ports(plugin: *const c_void) -> c_uint;
    fn lilv_plugin_get_port_by_index(plugin: *const c_void, index: c_uint) -> *const c_void;

    fn lilv_port_get_symbol(plugin: *const c_void, port: *const c_void) -> *const c_void;
    fn lilv_port_get_name(plugin: *const c_void, port: *const c_void) -> *mut c_void;
    fn lilv_port_is_a(plugin: *const c_void, port: *const c_void, class: *const c_void) -> bool;
    fn lilv_port_get_range(
        plugin: *const c_void,
        port: *const c_void,
        def: *mut *mut c_void,
        min: *mut *mut c_void,
        max: *mut *mut c_void,
    );

    fn lilv_node_as_string(node: *const c_void) -> *const c_char;
    fn lilv_node_as_float(node: *const c_void) -> c_float;
    fn lilv_node_is_float(node: *const c_void) -> bool;
    fn lilv_node_free(node: *mut c_void);
    fn lilv_new_uri(world: *mut LilvWorld, uri: *const c_char) -> *mut c_void;
    fn lilv_port_has_property(
        plugin: *const c_void,
        port: *const c_void,
        property: *const c_void,
    ) -> bool;
}

const LV2_CONTROL_PORT: &str = "http://lv2plug.in/ns/lv2core#ControlPort";
const LV2_INPUT_PORT: &str = "http://lv2plug.in/ns/lv2core#InputPort";
const LV2_TOGGLED: &str = "http://lv2plug.in/ns/lv2core#toggled";
const LV2_INTEGER: &str = "http://lv2plug.in/ns/lv2core#integer";

// ── Plugin scanner ────────────────────────────────────────────────────────────

/// Scan all installed LV2 plugins via lilv and return a JSON array.
///
/// Output shape:
/// ```json
/// [
///   {
///     "uri": "http://...",
///     "name": "...",
///     "factory": "gst-element-name",
///     "controls": [
///       {"symbol": "gain", "name": "Gain", "min": 0.0, "max": 2.0, "default": 1.0}
///     ]
///   }
/// ]
/// ```
pub fn lv2_scan_plugins() -> String {
    unsafe { scan_plugins_unsafe() }
}

unsafe fn scan_plugins_unsafe() -> String {
    refresh_gstreamer_registry();
    let world = lilv_world_new();
    if world.is_null() {
        return "[]".to_string();
    }
    lilv_world_load_all(world);

    let ctrl_class = {
        let uri = CString::new(LV2_CONTROL_PORT).unwrap();
        lilv_new_uri(world, uri.as_ptr())
    };
    let in_class = {
        let uri = CString::new(LV2_INPUT_PORT).unwrap();
        lilv_new_uri(world, uri.as_ptr())
    };
    let toggled_prop = {
        let uri = CString::new(LV2_TOGGLED).unwrap();
        lilv_new_uri(world, uri.as_ptr())
    };
    let integer_prop = {
        let uri = CString::new(LV2_INTEGER).unwrap();
        lilv_new_uri(world, uri.as_ptr())
    };

    let plugins = lilv_world_get_all_plugins(world);
    let count = lilv_plugins_size(plugins) as usize;
    let mut entries: Vec<String> = Vec::with_capacity(count);
    let mut seen_uris: std::collections::HashSet<String> = std::collections::HashSet::new();

    let mut iter = lilv_plugins_begin(plugins);
    while !lilv_plugins_is_end(plugins, iter) {
        let plugin = lilv_plugins_get(plugins, iter);
        if !plugin.is_null() {
            if let Some((uri, entry)) = build_plugin_entry_with_uri(
                plugin, ctrl_class, in_class, toggled_prop, integer_prop,
            ) {
                if seen_uris.insert(uri) {
                    entries.push(entry);
                }
            }
        }
        iter = lilv_plugins_next(plugins, iter);
    }

    lilv_node_free(toggled_prop);
    lilv_node_free(integer_prop);
    lilv_node_free(ctrl_class);
    lilv_node_free(in_class);
    lilv_world_free(world);

    format!("[{}]", entries.join(","))
}

unsafe fn build_plugin_entry_with_uri(
    plugin: *const c_void,
    ctrl_class: *const c_void,
    in_class: *const c_void,
    toggled_prop: *const c_void,
    integer_prop: *const c_void,
) -> Option<(String, String)> {
    let uri_node = lilv_plugin_get_uri(plugin);
    if uri_node.is_null() {
        return None;
    }
    let uri_ptr = lilv_node_as_string(uri_node);
    if uri_ptr.is_null() {
        return None;
    }
    let uri = CStr::from_ptr(uri_ptr).to_string_lossy().into_owned();
    if uri.is_empty() {
        return None;
    }

    let name_node = lilv_plugin_get_name(plugin);
    let name = if name_node.is_null() {
        uri.clone()
    } else {
        let ptr = lilv_node_as_string(name_node);
        let s = if ptr.is_null() {
            uri.clone()
        } else {
            CStr::from_ptr(ptr).to_string_lossy().into_owned()
        };
        lilv_node_free(name_node);
        s
    };

    let factory = uri_to_gst_factory_name(&uri);
    let gst_element = gst::ElementFactory::make(&factory).build().ok();
    let num_ports = lilv_plugin_get_num_ports(plugin);
    let mut controls: Vec<String> = Vec::new();

    for i in 0..num_ports {
        let port = lilv_plugin_get_port_by_index(plugin, i);
        if port.is_null() {
            continue;
        }
        if !lilv_port_is_a(plugin, port, ctrl_class) {
            continue;
        }
        if !lilv_port_is_a(plugin, port, in_class) {
            continue;
        }

        let sym_node = lilv_port_get_symbol(plugin, port);
        if sym_node.is_null() {
            continue;
        }
        let sym_ptr = lilv_node_as_string(sym_node);
        if sym_ptr.is_null() {
            continue;
        }
        let mut symbol = CStr::from_ptr(sym_ptr).to_string_lossy().into_owned();

        let pname_node = lilv_port_get_name(plugin, port);
        let pname = if pname_node.is_null() {
            symbol.clone()
        } else {
            let ptr = lilv_node_as_string(pname_node);
            let s = if ptr.is_null() {
                symbol.clone()
            } else {
                CStr::from_ptr(ptr).to_string_lossy().into_owned()
            };
            lilv_node_free(pname_node);
            s
        };

        let mut def_node: *mut c_void = std::ptr::null_mut();
        let mut min_node: *mut c_void = std::ptr::null_mut();
        let mut max_node: *mut c_void = std::ptr::null_mut();
        lilv_port_get_range(plugin, port, &mut def_node, &mut min_node, &mut max_node);

        let def_val = if !def_node.is_null() && lilv_node_is_float(def_node) {
            lilv_node_as_float(def_node)
        } else {
            0.0
        };
        let min_val = if !min_node.is_null() && lilv_node_is_float(min_node) {
            lilv_node_as_float(min_node)
        } else {
            0.0
        };
        let max_val = if !max_node.is_null() && lilv_node_is_float(max_node) {
            lilv_node_as_float(max_node)
        } else {
            1.0
        };

        let mut is_toggled = lilv_port_has_property(plugin, port, toggled_prop);
        let mut is_integer = lilv_port_has_property(plugin, port, integer_prop);
        let mut min_val = min_val;
        let mut max_val = max_val;
        let mut def_val = def_val;

        if let Some(ref element) = gst_element {
            if let Some((actual_name, actual_min, actual_max, actual_default, actual_toggled, actual_integer)) =
                gst_property_info(element, symbol.as_str())
            {
                symbol = actual_name;
                min_val = actual_min;
                max_val = actual_max;
                def_val = actual_default;
                is_toggled = actual_toggled;
                is_integer = actual_integer;
            }
        }

        if !def_node.is_null() {
            lilv_node_free(def_node);
        }
        if !min_node.is_null() {
            lilv_node_free(min_node);
        }
        if !max_node.is_null() {
            lilv_node_free(max_node);
        }

        // Build JSON fields as a Vec so hints can be appended without fragile
        // substring slicing on the closing brace.
        let mut fields = vec![
            format!(r#""symbol":{}"#, json_str(&symbol)),
            format!(r#""name":{}"#, json_str(&pname)),
            format!(r#""min":{min_val}"#),
            format!(r#""max":{max_val}"#),
            format!(r#""default":{def_val}"#),
        ];
        if is_toggled {
            fields.push(r#""toggled":true"#.to_string());
        } else if is_integer {
            fields.push(r#""integer":true"#.to_string());
        }
        controls.push(format!("{{{}}}", fields.join(",")));
    }

    let json = format!(
        r#"{{"uri":{},"name":{},"factory":{},"controls":[{}]}}"#,
        json_str(&uri),
        json_str(&name),
        json_str(&factory),
        controls.join(","),
    );
    Some((uri, json))
}

fn json_str(s: &str) -> String {
    let escaped = s
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t");
    format!("\"{escaped}\"")
}

#[cfg(test)]
mod tests {
    use super::{host_managed_port_bool, host_managed_port_scalar, is_host_managed_port_symbol, Lv2SlotConfig};

    #[test]
    fn bypass_host_port_uses_inverse_semantics() {
        assert_eq!(host_managed_port_scalar("bypass", true), 0.0);
        assert_eq!(host_managed_port_scalar("bypass", false), 1.0);
        assert!(!host_managed_port_bool("bypass", true));
        assert!(host_managed_port_bool("bypass", false));
    }

    #[test]
    fn enabled_host_port_uses_direct_semantics() {
        assert_eq!(host_managed_port_scalar("enabled", true), 1.0);
        assert_eq!(host_managed_port_scalar("enabled", false), 0.0);
        assert!(host_managed_port_bool("enabled", true));
        assert!(!host_managed_port_bool("enabled", false));
    }

    #[test]
    fn host_managed_port_symbols_are_not_persisted_as_regular_port_values() {
        let mut slot = Lv2SlotConfig::new("lv2_0", "http://example.com/plugin");
        assert!(is_host_managed_port_symbol("enabled"));
        assert!(is_host_managed_port_symbol("enable"));
        assert!(is_host_managed_port_symbol("bypass"));

        slot.set_port_value("enabled", 1.0);
        slot.set_port_value("bypass", 0.0);
        slot.set_port_value("mix", 0.5);

        assert_eq!(slot.port_values.len(), 1);
        assert_eq!(slot.port_values.get("mix"), Some(&0.5));
    }
}
