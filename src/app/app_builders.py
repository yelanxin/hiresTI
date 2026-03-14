"""
UI builders and interactive UI methods for TidalApp.
Contains popover builders, key handler, mini mode, volume lock and simple dialog.
"""
import logging
import os
import hashlib

from gi.repository import Gtk, Gdk, GLib, GObject, Pango

from core.settings import read_json, write_json
from core.executor import submit_daemon
from ui import config as ui_config

logger = logging.getLogger(__name__)

_EQ_FREQS = ["30", "60", "120", "240", "480", "1k", "2k", "4k", "8k", "16k"]
_DSP_PRESET_NAMES = [
    "Flat",
    "Bass Boost",
    "Vocal",
    "Treble Lift",
    "Warm",
    "Late Night",
    "Soft",
    "Bright",
]
_DSP_PRESETS = {
    "Flat": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "Bass Boost": [6.0, 5.0, 3.5, 2.0, 1.0, 0.0, -1.0, -1.5, -2.0, -2.0],
    "Vocal": [-2.0, -1.0, 0.0, 1.5, 2.5, 3.0, 2.0, 0.5, -0.5, -1.0],
    "Treble Lift": [-1.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 3.5, 4.5, 5.0],
    "Warm": [2.5, 2.0, 1.2, 0.6, 0.2, -0.2, -0.8, -1.4, -1.8, -2.0],
    "Late Night": [2.0, 1.5, 1.0, 0.5, 0.5, 1.0, 1.5, 1.5, 1.0, 0.5],
    "Soft": [-1.0, -0.8, -0.5, -0.2, 0.0, 0.3, 0.4, 0.2, -0.3, -0.8],
    "Bright": [-1.5, -1.0, -0.5, 0.0, 0.8, 1.6, 2.6, 3.4, 3.8, 3.2],
}

_DSP_LIMITER_THRESHOLD_DEFAULT = 85
_DSP_LIMITER_RATIO_DEFAULT = 20
_DSP_CONVOLVER_MIX_DEFAULT = 100
_DSP_CONVOLVER_PRE_DELAY_DEFAULT = 0
_DSP_RESAMPLER_RATES = [0, 44100, 48000, 88200, 96000, 176400, 192000]
_DSP_RESAMPLER_RATE_LABELS = {
    0: "Off (passthrough)",
    44100: "44.1 kHz",
    48000: "48 kHz",
    88200: "88.2 kHz",
    96000: "96 kHz",
    176400: "176.4 kHz",
    192000: "192 kHz",
}
_DSP_RESAMPLER_QUALITY_LEVELS = [0, 3, 5, 8, 10]
_DSP_RESAMPLER_QUALITY_LABELS = {
    0: "0 — Linear (fastest)",
    3: "3 — Low",
    5: "5 — Medium",
    8: "8 — High",
    10: "10 — Best (slowest)",
}
# (drive, tone, warmth)
_DSP_TAPE_PRESETS = {
    "Subtle":   (15, 65, 30),
    "Classic":  (30, 60, 40),
    "Vintage":  (50, 30, 65),
    "Lo-Fi":    (70, 20, 75),
    "Bright":   (25, 85, 25),
}
_DSP_TAPE_PRESET_NAMES = list(_DSP_TAPE_PRESETS.keys())
_DSP_TUBE_DEFAULTS = {
    "drive": 28,
    "bias": 55,
    "sag": 18,
    "air": 52,
}
_DSP_TUBE_PRESETS = {
    "Subtle": (18, 54, 10, 58),
    "Triode": (30, 62, 18, 52),
    "Romantic": (40, 68, 26, 44),
    "Night": (24, 60, 22, 36),
    "Sparkle": (26, 56, 12, 68),
}
_DSP_TUBE_PRESET_NAMES = list(_DSP_TUBE_PRESETS.keys())
_DSP_WIDENER_WIDTH_DEFAULT = 125
_DSP_WIDENER_BASS_MONO_FREQ_DEFAULT = 120
_DSP_WIDENER_BASS_MONO_AMOUNT_DEFAULT = 100
_DSP_MODULES = [
    ("peq", "PEQ"),
    ("convolver", "Convolution"),
    ("tape", "Tape"),
    ("tube", "Tube"),
    ("widener", "Stereo Widener"),
    ("limiter", "Limiter"),
    ("resampler", "Resampler"),
]
_DSP_REORDERABLE_MODULE_IDS = ["peq", "convolver", "tape", "tube", "widener"]
_DSP_MODULE_TITLES = {
    "decode": "Decode",
    "output_driver": "Output Driver",
    "output": "Output Device",
    **dict(_DSP_MODULES),
}
_DSP_WORKSPACE_MIN_HEIGHT = 300
_DSP_WORKSPACE_MAX_HEIGHT = max(420, int(ui_config.WINDOW_HEIGHT * 0.48))
_LV2_HOST_MANAGED_PORT_SYMBOLS = {"enabled", "enable", "bypass"}
_LV2_DEFAULT_SEARCH_DIRS = [
    "~/.lv2",
    "~/.local/share/lv2",
    "~/.local/lib/lv2",
    "/usr/local/lib/lv2",
    "/usr/lib/lv2",
    "/usr/share/lv2",
]
_LV2_INSTALL_HELP_TEXT = (
    "This dialog shows LV2 plugins that are already installed on your system.\n\n"
    "Fedora example:\n"
    "sudo dnf install gstreamer1-plugins-bad-free-lv2 "
    "lsp-plugins-lv2 lv2-x42-plugins lv2-calf-plugins lv2-zam-plugins\n\n"
    "After installing packages, reopen this dialog or click Add LV2 Plugin again."
)


def _configure_dsp_scale(scale, digits=0, value_pos=Gtk.PositionType.RIGHT):
    scale.set_digits(int(digits))
    scale.set_draw_value(True)
    scale.set_value_pos(value_pos)
    return scale


def _build_dsp_scroll_area(child, min_height=_DSP_WORKSPACE_MIN_HEIGHT, max_height=_DSP_WORKSPACE_MAX_HEIGHT):
    scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_propagate_natural_height(True)
    if min_height is not None:
        scroll.set_min_content_height(int(min_height))
    if max_height is not None:
        scroll.set_max_content_height(int(max_height))
    scroll.set_child(child)
    return scroll


def _build_dsp_detail_page(child):
    try:
        child.set_hexpand(True)
    except Exception:
        pass
    try:
        child.set_vexpand(False)
    except Exception:
        pass
    return _build_dsp_scroll_area(child)


def _build_dsp_control_label(self, text):
    label = Gtk.Label(label=str(text or ""), xalign=0, hexpand=False)
    group = getattr(self, "dsp_control_label_group", None)
    if group is not None:
        group.add_widget(label)
    return label


def _is_dsp_reorderable_module(module_id):
    module_id = str(module_id or "").strip()
    return bool(module_id in _DSP_REORDERABLE_MODULE_IDS or module_id.startswith("lv2_"))


def _normalize_dsp_order(order=None):
    raw = list(order or [])
    normalized = []
    for module_id in raw:
        module_id = str(module_id or "").strip()
        if not module_id or module_id in normalized:
            continue
        if _is_dsp_reorderable_module(module_id):
            normalized.append(module_id)
    for module_id in _DSP_REORDERABLE_MODULE_IDS:
        if module_id not in normalized:
            normalized.append(module_id)
    return normalized


def _listbox_debug_rows(listbox):
    rows = []
    if listbox is None:
        return rows
    child = listbox.get_first_child()
    while child is not None:
        rows.append(
            {
                "row_id": hex(id(child)),
                "module_id": getattr(child, "dsp_module_id", None),
            }
        )
        child = child.get_next_sibling()
    return rows


def _suppress_search_focus_temporarily(self, duration_ms=320):
    try:
        now_us = int(GLib.get_monotonic_time())
    except Exception:
        return
    self._search_focus_suppressed_until_us = now_us + max(0, int(duration_ms)) * 1000


def _dsp_overview_module_title(self, module_id):
    module_id = str(module_id or "").strip()
    if module_id in _DSP_MODULE_TITLES:
        return _DSP_MODULE_TITLES[module_id]
    if module_id.startswith("lv2_"):
        meta = self._lv2_get_plugin_meta(module_id) if hasattr(self, "_lv2_get_plugin_meta") else None
        if meta:
            name = str(meta.get("name", "") or "").strip()
            if name:
                return name
        player = getattr(self, "player", None)
        slot = (getattr(player, "lv2_slots", {}) or {}).get(module_id, {}) if player else {}
        uri = str(slot.get("uri", "") or "").strip()
        if uri:
            return uri.rsplit("/", 1)[-1] or module_id
    return module_id.title()


def _volume_icon_name(percent):
    value = float(percent or 0.0)
    if value <= 0.0:
        return "hiresti-volume-muted-symbolic"
    if value < 30.0:
        return "hiresti-volume-low-symbolic"
    if value < 70.0:
        return "hiresti-volume-medium-symbolic"
    return "hiresti-volume-high-symbolic"


def _sync_volume_ui_state(self, value=None, source_scale=None):
    try:
        volume = float(value if value is not None else self.settings.get("volume", 80))
    except Exception:
        volume = 80.0
    volume = max(0.0, min(100.0, volume))

    self._volume_ui_syncing = True
    try:
        for scale in (getattr(self, "vol_scale", None), getattr(self, "now_playing_vol_scale", None)):
            if scale is None or scale is source_scale:
                continue
            try:
                if abs(float(scale.get_value()) - volume) > 0.1:
                    scale.set_value(volume)
            except Exception:
                continue
    finally:
        self._volume_ui_syncing = False

    icon = _volume_icon_name(volume)
    for btn in (getattr(self, "vol_btn", None), getattr(self, "now_playing_vol_btn", None)):
        if btn is not None:
            try:
                btn.set_icon_name(icon)
            except Exception:
                pass


def _sync_eq_slider_groups(self, source_scale=None):
    values = list(getattr(self, "eq_band_values", [0.0] * len(_EQ_FREQS)) or [])
    if len(values) < len(_EQ_FREQS):
        values.extend([0.0] * (len(_EQ_FREQS) - len(values)))
        self.eq_band_values = values

    self._eq_ui_syncing = True
    try:
        for group in (
            getattr(self, "sliders", None) or [],
            getattr(self, "now_playing_eq_sliders", None) or [],
            getattr(self, "dsp_peq_sliders", None) or [],
        ):
            for idx, scale in enumerate(group):
                if scale is None or scale is source_scale or idx >= len(values):
                    continue
                try:
                    if abs(float(scale.get_value()) - float(values[idx])) > 0.01:
                        scale.set_value(float(values[idx]))
                except Exception:
                    continue
    finally:
        self._eq_ui_syncing = False
    if hasattr(self, "_sync_dsp_preset_dropdown"):
        self._sync_dsp_preset_dropdown()


def _on_eq_slider_changed(self, scale, idx):
    if getattr(self, "_eq_ui_syncing", False):
        return
    values = list(getattr(self, "eq_band_values", [0.0] * len(_EQ_FREQS)) or [])
    if len(values) < len(_EQ_FREQS):
        values.extend([0.0] * (len(_EQ_FREQS) - len(values)))
    value = float(scale.get_value())
    values[idx] = value
    self.eq_band_values = values
    try:
        self.player.set_eq_band(idx, value)
    except Exception:
        logger.debug("set_eq_band failed", exc_info=True)
    settings = getattr(self, "settings", None)
    if isinstance(settings, dict):
        settings["dsp_peq_bands"] = list(values)
        settings["dsp_peq_enabled"] = True
    if isinstance(settings, dict) and hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    _sync_eq_slider_groups(self, source_scale=scale)
    if hasattr(self, "_update_dsp_ui_state"):
        self._update_dsp_ui_state()


def _reset_eq_ui(self):
    self.eq_band_values = [0.0] * len(_EQ_FREQS)
    try:
        self.player.reset_eq()
    except Exception:
        logger.debug("reset_eq failed", exc_info=True)
    settings = getattr(self, "settings", None)
    if isinstance(settings, dict):
        settings["dsp_peq_bands"] = list(self.eq_band_values)
        settings["dsp_peq_enabled"] = False
    if isinstance(settings, dict) and hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    _sync_eq_slider_groups(self)
    if hasattr(self, "_update_dsp_ui_state"):
        self._update_dsp_ui_state()


def _eq_active_summary(values):
    active = sum(1 for value in (values or []) if abs(float(value or 0.0)) >= 0.01)
    if active <= 0:
        return "Flat"
    return f"{active} band{'s' if active != 1 else ''} active"


def _eq_values_close(a, b, tol=0.01):
    left = list(a or [])
    right = list(b or [])
    if len(left) != len(right):
        return False
    for x, y in zip(left, right):
        if abs(float(x) - float(y)) > tol:
            return False
    return True


def _current_eq_preset_name(self):
    values = list(getattr(self, "eq_band_values", [0.0] * len(_EQ_FREQS)) or [])
    while len(values) < len(_EQ_FREQS):
        values.append(0.0)
    for name in _DSP_PRESET_NAMES:
        if _eq_values_close(values, _DSP_PRESETS.get(name)):
            return name
    return "Custom"


def _sync_dsp_preset_dropdown(self):
    dd = getattr(self, "dsp_peq_preset_dd", None)
    if dd is None:
        return
    names = list(_DSP_PRESET_NAMES) + ["Custom"]
    current = _current_eq_preset_name(self)
    try:
        idx = names.index(current)
    except ValueError:
        idx = len(names) - 1
    self._dsp_ui_syncing = True
    try:
        if int(dd.get_selected()) != idx:
            dd.set_selected(idx)
    finally:
        self._dsp_ui_syncing = False


def _apply_eq_preset(self, preset_name):
    name = str(preset_name or "").strip()
    values = list(_DSP_PRESETS.get(name) or [])
    if len(values) != len(_EQ_FREQS):
        return False
    self.eq_band_values = list(values)
    peq_enabled = any(abs(float(v or 0.0)) >= 0.01 for v in values)
    try:
        self.player.set_peq_enabled(peq_enabled)
    except Exception:
        logger.debug("set_peq_enabled failed during preset apply", exc_info=True)
    for idx, value in enumerate(values):
        try:
            self.player.set_eq_band(idx, float(value))
        except Exception:
            logger.debug("set_eq_band failed during preset apply", exc_info=True)
    settings = getattr(self, "settings", None)
    if isinstance(settings, dict):
        settings["dsp_peq_bands"] = list(values)
        settings["dsp_peq_enabled"] = peq_enabled
    if isinstance(settings, dict) and hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    sync_fn = getattr(self, "_sync_eq_slider_groups", None)
    if callable(sync_fn):
        sync_fn()
    else:
        _sync_eq_slider_groups(self)
    if hasattr(self, "_update_dsp_ui_state"):
        self._update_dsp_ui_state()
    return True


def _on_dsp_preset_changed(self, dd, _param=None):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    item = dd.get_selected_item() if dd is not None else None
    name = item.get_string() if item is not None else ""
    if not name or name == "Custom":
        return
    if getattr(self, "settings", {}).get("bit_perfect", False):
        if not self._release_bit_perfect_for_dsp():
            self._sync_dsp_preset_dropdown()
            return
    self._apply_eq_preset(name)


def _build_eq_editor_content(self, sliders_attr="sliders", show_header=True):
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    if show_header:
        hb = Gtk.Box(spacing=12)
        hb.append(Gtk.Label(label="10-Band Equalizer", css_classes=["title-4"]))
        reset = Gtk.Button(label="Reset", css_classes=["flat"])
        reset.connect("clicked", lambda _b: self._reset_eq_ui())
        hb.append(reset)
        vbox.append(hb)
    hbox = Gtk.Box(spacing=8, hexpand=True, halign=Gtk.Align.FILL)
    hbox.set_homogeneous(True)
    sliders = []
    eq_values = list(getattr(self, "eq_band_values", [0.0] * len(_EQ_FREQS)) or [])
    if len(eq_values) < len(_EQ_FREQS):
        eq_values.extend([0.0] * (len(_EQ_FREQS) - len(eq_values)))
        self.eq_band_values = eq_values
    for i, f in enumerate(_EQ_FREQS):
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True, halign=Gtk.Align.FILL)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -24, 12, 1)
        scale.set_inverted(True)
        scale.set_size_request(24, 150)
        scale.set_hexpand(True)
        scale.set_halign(Gtk.Align.CENTER)
        _configure_dsp_scale(scale, digits=0, value_pos=Gtk.PositionType.RIGHT)
        scale.set_value(float(eq_values[i]))
        scale.add_mark(0, Gtk.PositionType.RIGHT, None)
        scale.connect("value-changed", lambda s, idx=i: self._on_eq_slider_changed(s, idx))
        sliders.append(scale)
        vb.set_valign(Gtk.Align.FILL)
        vb.append(scale)
        vb.append(Gtk.Label(label=f, css_classes=["caption"], halign=Gtk.Align.CENTER))
        hbox.append(vb)
    setattr(self, sliders_attr, sliders)
    vbox.append(hbox)
    return vbox


def _build_dsp_placeholder_page(self, title, summary):
    host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True, valign=Gtk.Align.FILL)
    box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=10,
        margin_top=20,
        margin_bottom=20,
        margin_start=20,
        margin_end=20,
        valign=Gtk.Align.START,
        css_classes=["dsp-detail-card"],
    )
    box.append(Gtk.Label(label=title, xalign=0, css_classes=["title-3"]))
    box.append(Gtk.Label(label=summary, xalign=0, wrap=True, css_classes=["dim-label"]))
    host.append(box)
    return host


def _convolver_display_name(path):
    raw = str(path or "").strip()
    if not raw:
        return ""
    name = os.path.basename(raw)
    return name or raw


def _limiter_status_text(enabled, threshold_pct, ratio):
    if not enabled:
        return "Limiter bypassed"
    return f"Ceiling {int(round(threshold_pct))}% / Ratio {float(ratio):.0f}:1"


def _apply_dsp_convolver_path(self, path=None, enable_after_load=True):
    entry = getattr(self, "dsp_convolver_path_entry", None)
    raw = path
    if raw is None and entry is not None:
        try:
            raw = entry.get_text()
        except Exception:
            raw = ""
    raw = str(raw or "").strip()
    if not raw:
        self._dsp_convolver_last_error = "Enter a .wav, .txt, or .csv FIR / IR path"
        self._update_dsp_ui_state()
        return False
    if getattr(self, "settings", {}).get("bit_perfect", False):
        if not self._release_bit_perfect_for_dsp():
            self._update_dsp_ui_state()
            return False
    try:
        loaded = bool(self.player.load_convolver_ir(raw))
    except Exception:
        loaded = False
        logger.debug("load_convolver_ir failed", exc_info=True)
    if not loaded:
        self._dsp_convolver_last_error = f"Failed to load IR: {_convolver_display_name(raw)}"
        self._update_dsp_ui_state()
        return False
    self._dsp_convolver_last_error = ""
    self.settings["dsp_convolver_path"] = raw
    if entry is not None:
        try:
            if entry.get_text() != raw:
                entry.set_text(raw)
        except Exception:
            pass
    enabled_ok = True
    if enable_after_load:
        try:
            enabled_ok = bool(self.player.set_convolver_enabled(True))
        except Exception:
            enabled_ok = False
            logger.debug("set_convolver_enabled failed after load", exc_info=True)
        self.settings["dsp_convolver_enabled"] = bool(enabled_ok)
    else:
        self.settings["dsp_convolver_enabled"] = bool(getattr(self.player, "convolver_enabled", False))
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    self._update_dsp_ui_state()
    return bool(enabled_ok)


def _clear_dsp_convolver_path(self):
    try:
        cleared = bool(self.player.clear_convolver_ir())
    except Exception:
        cleared = False
        logger.debug("clear_convolver_ir failed", exc_info=True)
    if not cleared:
        self._dsp_convolver_last_error = "Failed to clear convolution IR"
        self._update_dsp_ui_state()
        return False
    self._dsp_convolver_last_error = ""
    self.settings["dsp_convolver_path"] = ""
    self.settings["dsp_convolver_enabled"] = False
    entry = getattr(self, "dsp_convolver_path_entry", None)
    if entry is not None:
        try:
            if entry.get_text():
                entry.set_text("")
        except Exception:
            pass
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    self._update_dsp_ui_state()
    return True


def _on_dsp_convolver_file_selected(self, dialog, result):
    try:
        file_obj = dialog.open_finish(result)
    except Exception:
        return
    if file_obj is None:
        return
    try:
        path = file_obj.get_path()
    except Exception:
        path = None
    if not path:
        return
    self._apply_dsp_convolver_path(path, enable_after_load=True)


def _open_dsp_convolver_file_dialog(self, _btn=None):
    dialog = Gtk.FileDialog(title="Select FIR / IR File")
    try:
        dialog.set_modal(True)
    except Exception:
        pass
    try:
        filters = Gtk.ListStore.new(Gtk.FileFilter)
        ir_filter = Gtk.FileFilter()
        ir_filter.set_name("FIR / IR files")
        for pattern in ("*.wav", "*.wave", "*.txt", "*.csv"):
            ir_filter.add_pattern(pattern)
        filters.append(ir_filter)
        any_filter = Gtk.FileFilter()
        any_filter.set_name("All files")
        any_filter.add_pattern("*")
        filters.append(any_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(ir_filter)
    except Exception:
        pass
    parent = getattr(self, "win", None)
    dialog.open(parent, None, self._on_dsp_convolver_file_selected)


def _show_dsp_module(self, module_id, select_row=True):
    module_id = str(module_id or "peq")
    self._dsp_selected_module = module_id
    logger.info(
        "DSP show module request module_id=%s select_row=%s main_rows=%s lv2_rows=%s",
        module_id,
        bool(select_row),
        _listbox_debug_rows(getattr(self, "dsp_module_list", None)),
        _listbox_debug_rows(getattr(self, "dsp_lv2_module_list", None)),
    )
    if getattr(self, "dsp_module_stack", None) is not None:
        get_child_by_name = getattr(self.dsp_module_stack, "get_child_by_name", None)
        if callable(get_child_by_name):
            if get_child_by_name(module_id) is None:
                logger.debug("DSP module page not yet built for %s, deferring show", module_id)
                GLib.idle_add(lambda: self._show_dsp_module(module_id, select_row))
                return
        self.dsp_module_stack.set_visible_child_name(module_id)
    if hasattr(self, "_update_dsp_ui_state"):
        try:
            self._update_dsp_ui_state()
        except Exception:
            logger.debug("dsp ui state refresh after show module failed", exc_info=True)
    if not select_row:
        return
    primary_list = getattr(self, "dsp_module_list", None)
    lv2_list = getattr(self, "dsp_lv2_module_list", None)
    target_list = None
    target_row = None
    for listbox in (primary_list, lv2_list):
        if listbox is None:
            continue
        row = listbox.get_first_child()
        while row is not None:
            if getattr(row, "dsp_module_id", None) == module_id:
                target_list = listbox
                target_row = row
                break
            row = row.get_next_sibling()
        if target_row is not None:
            break
    if target_list is None or target_row is None:
        return
    for listbox in (primary_list, lv2_list):
        if listbox is None or listbox is target_list:
            continue
        try:
            listbox.unselect_all()
        except Exception:
            pass
    target_list.select_row(target_row)


def _on_dsp_module_selected(self, _listbox, row):
    if row is None:
        return
    module_id = getattr(row, "dsp_module_id", "peq")
    current_list = _listbox
    for listbox in (getattr(self, "dsp_module_list", None), getattr(self, "dsp_lv2_module_list", None)):
        if listbox is None or listbox is current_list:
            continue
        try:
            listbox.unselect_all()
        except Exception:
            pass
    self._show_dsp_module(module_id, select_row=False)


def _update_dsp_ui_state(self):
    values = list(getattr(self, "eq_band_values", [0.0] * len(_EQ_FREQS)) or [])
    while len(values) < len(_EQ_FREQS):
        values.append(0.0)
    player = getattr(self, "player", None)
    dsp_enabled = bool(getattr(player, "dsp_enabled", True))
    peq_enabled = bool(getattr(player, "peq_enabled", False))
    convolver_enabled = bool(getattr(player, "convolver_enabled", False))
    tape_enabled = bool(getattr(player, "tape_enabled", False))
    tube_enabled = bool(getattr(player, "tube_enabled", False))
    widener_enabled = bool(getattr(player, "widener_enabled", False))
    limiter_enabled = bool(getattr(player, "limiter_enabled", False))
    resampler_enabled = bool(getattr(player, "resampler_enabled", False))
    resampler_target_rate = int(getattr(player, "resampler_target_rate", 0) or 0)
    convolver_path = str(
        getattr(player, "convolver_ir_path", "")
        or getattr(self, "settings", {}).get("dsp_convolver_path", "")
        or ""
    ).strip()
    current_driver_name = str(
        getattr(player, "current_driver", "")
        or getattr(self, "settings", {}).get("driver", "")
        or "Output Driver"
    ).strip()
    driver_available = current_driver_name not in ("", "Unavailable")
    current_output_name = str(
        getattr(self, "current_device_name", "")
        or getattr(self, "settings", {}).get("device", "")
        or "Output Device"
    ).strip()
    output_available = current_output_name not in ("", "Unavailable")
    limiter_threshold = float(
        getattr(player, "limiter_threshold", 0.85)
        if player is not None
        else 0.85
    )
    limiter_ratio = float(
        getattr(player, "limiter_ratio", 20.0)
        if player is not None
        else 20.0
    )
    limiter_threshold_pct = max(0.0, min(100.0, limiter_threshold * 100.0))
    tube_values = {
        "drive": int(getattr(player, "tube_drive", self.settings.get("dsp_tube_drive", _DSP_TUBE_DEFAULTS["drive"])) if player is not None else self.settings.get("dsp_tube_drive", _DSP_TUBE_DEFAULTS["drive"])),
        "bias": int(getattr(player, "tube_bias", self.settings.get("dsp_tube_bias", _DSP_TUBE_DEFAULTS["bias"])) if player is not None else self.settings.get("dsp_tube_bias", _DSP_TUBE_DEFAULTS["bias"])),
        "sag": int(getattr(player, "tube_sag", self.settings.get("dsp_tube_sag", _DSP_TUBE_DEFAULTS["sag"])) if player is not None else self.settings.get("dsp_tube_sag", _DSP_TUBE_DEFAULTS["sag"])),
        "air": int(getattr(player, "tube_air", self.settings.get("dsp_tube_air", _DSP_TUBE_DEFAULTS["air"])) if player is not None else self.settings.get("dsp_tube_air", _DSP_TUBE_DEFAULTS["air"])),
    }
    widener_width = int(
        getattr(player, "widener_width", self.settings.get("dsp_widener_width", _DSP_WIDENER_WIDTH_DEFAULT))
        if player is not None
        else self.settings.get("dsp_widener_width", _DSP_WIDENER_WIDTH_DEFAULT)
    )
    widener_bass_mono_freq = int(
        getattr(player, "widener_bass_mono_freq", self.settings.get("dsp_widener_bass_mono_freq", _DSP_WIDENER_BASS_MONO_FREQ_DEFAULT))
        if player is not None
        else self.settings.get("dsp_widener_bass_mono_freq", _DSP_WIDENER_BASS_MONO_FREQ_DEFAULT)
    )
    widener_bass_mono_amount = int(
        getattr(player, "widener_bass_mono_amount", self.settings.get("dsp_widener_bass_mono_amount", _DSP_WIDENER_BASS_MONO_AMOUNT_DEFAULT))
        if player is not None
        else self.settings.get("dsp_widener_bass_mono_amount", _DSP_WIDENER_BASS_MONO_AMOUNT_DEFAULT)
    )
    peq_summary = _eq_active_summary(values)
    bit_perfect_locked = bool(getattr(self, "settings", {}).get("bit_perfect", False))
    if bit_perfect_locked:
        master_state_text = "Bypassed in Bit-Perfect mode"
        master_hint_text = "Bit-Perfect is enabled, so the entire DSP chain is bypassed until that mode is turned off."
        peq_status_text = "Disabled while Bit-Perfect mode is enabled"
        peq_state_text = "Locked"
        convolver_status_text = "Disabled while Bit-Perfect mode is enabled"
        convolver_state_text = "Locked"
        limiter_status_text = "Disabled while Bit-Perfect mode is enabled"
        limiter_state_text = "Locked"
        resampler_status_text = "Disabled while Bit-Perfect mode is enabled"
        resampler_state_text = "Locked"
        tape_status_text = "Disabled while Bit-Perfect mode is enabled"
        tape_state_text = "Locked"
        tube_status_text = "Disabled while Bit-Perfect mode is enabled"
        tube_state_text = "Locked"
        widener_status_text = "Disabled while Bit-Perfect mode is enabled"
        widener_state_text = "Locked"
    else:
        if not dsp_enabled:
            master_state_text = "Off"
            master_hint_text = "Turn DSP master on to activate the processing chain."
        else:
            master_state_text = "On"
            master_hint_text = "Processing chain is live. Open Effects & Config to tune each stage."

        if not dsp_enabled:
            peq_status_text = "Enable DSP master to process PEQ"
            peq_state_text = "Master Off"
        elif not peq_enabled:
            peq_status_text = "PEQ bypassed"
            peq_state_text = "Bypassed"
        else:
            peq_status_text = peq_summary
            peq_state_text = "Active"

        if getattr(self, "_dsp_convolver_last_error", ""):
            convolver_status_text = str(self._dsp_convolver_last_error)
            convolver_state_text = "Error"
        elif not convolver_path:
            convolver_status_text = "Load a .wav, .txt, or .csv FIR / IR file"
            convolver_state_text = "Needs IR"
        elif not dsp_enabled:
            convolver_status_text = f"Loaded: {_convolver_display_name(convolver_path)} (DSP master off)"
            convolver_state_text = "Master Off"
        elif not convolver_enabled:
            convolver_status_text = f"Loaded: {_convolver_display_name(convolver_path)} (bypassed)"
            convolver_state_text = "Ready"
        else:
            convolver_status_text = f"Loaded: {_convolver_display_name(convolver_path)}"
            convolver_state_text = "Active"

        if getattr(self, "_dsp_limiter_last_error", ""):
            limiter_status_text = str(self._dsp_limiter_last_error)
            limiter_state_text = "Error"
        elif not dsp_enabled:
            limiter_status_text = "Enable DSP master to process limiter"
            limiter_state_text = "Master Off"
        else:
            limiter_status_text = _limiter_status_text(limiter_enabled, limiter_threshold_pct, limiter_ratio)
            limiter_state_text = "Active" if limiter_enabled else "Bypassed"

        if not dsp_enabled:
            resampler_status_text = "Enable DSP master to use resampler"
            resampler_state_text = "Master Off"
        elif not resampler_enabled:
            resampler_status_text = "Resampler bypassed"
            resampler_state_text = "Bypassed"
        elif resampler_target_rate > 0:
            resampler_status_text = f"Active: {_DSP_RESAMPLER_RATE_LABELS.get(resampler_target_rate, f'{resampler_target_rate} Hz')}"
            resampler_state_text = "Active"
        else:
            resampler_status_text = "Resampler enabled (passthrough)"
            resampler_state_text = "Passthrough"

        if not dsp_enabled:
            tape_status_text = "Enable DSP master to use tape simulation"
            tape_state_text = "Master Off"
        elif tape_enabled:
            tape_status_text = "Active: Tape simulation processing"
            tape_state_text = "Active"
        else:
            tape_status_text = "Tape simulation bypassed"
            tape_state_text = "Bypassed"

        if not dsp_enabled:
            tube_status_text = "Enable DSP master to use tube stage"
            tube_state_text = "Master Off"
        elif tube_enabled:
            tube_status_text = (
                f"Active: Drive {tube_values['drive']} / Bias {tube_values['bias']} / "
                f"Sag {tube_values['sag']} / Air {tube_values['air']}"
            )
            tube_state_text = "Active"
        else:
            tube_status_text = "Tube stage bypassed"
            tube_state_text = "Bypassed"

        if not dsp_enabled:
            widener_status_text = "Enable DSP master to use widener"
            widener_state_text = "Master Off"
        elif widener_enabled:
            widener_status_text = f"Active: Width {widener_width}% / Bass Mono {widener_bass_mono_freq} Hz @ {widener_bass_mono_amount}%"
            widener_state_text = "Active"
        else:
            widener_status_text = "Stereo widener bypassed"
            widener_state_text = "Bypassed"

    overview_status_text = {
        "decode": (
            "Audio stream decoded and handed into the DSP chain"
            if dsp_enabled and not bit_perfect_locked
            else "DSP master is bypassing the chain"
        ),
        "peq": peq_status_text,
        "convolver": convolver_status_text,
        "tape": tape_status_text,
        "tube": tube_status_text,
        "widener": widener_status_text,
        "limiter": limiter_status_text,
        "resampler": resampler_status_text,
        "output_driver": (
            current_driver_name if (driver_available and dsp_enabled and not bit_perfect_locked)
            else "DSP master is bypassing the chain"
        ),
        "output": (
            current_output_name if (output_available and dsp_enabled and not bit_perfect_locked)
            else "DSP master is bypassing the chain"
        ),
    }
    player_lv2_slots = dict(getattr(player, "lv2_slots", {}) or {}) if player is not None else {}
    for slot_id, slot_info in player_lv2_slots.items():
        plugin_title = _dsp_overview_module_title(self, slot_id)
        if bit_perfect_locked:
            overview_status_text[slot_id] = f"{plugin_title}: disabled while Bit-Perfect mode is enabled"
        elif not dsp_enabled:
            overview_status_text[slot_id] = f"{plugin_title}: DSP master off"
        elif bool(slot_info.get("enabled", True)):
            overview_status_text[slot_id] = f"{plugin_title}: active"
        else:
            overview_status_text[slot_id] = f"{plugin_title}: bypassed"
    overview_enabled_state = {
        "decode": bool(dsp_enabled and not bit_perfect_locked),
        "peq": bool(dsp_enabled and peq_enabled and not bit_perfect_locked),
        "convolver": bool(dsp_enabled and convolver_enabled and convolver_path and not bit_perfect_locked),
        "tape": bool(dsp_enabled and tape_enabled and not bit_perfect_locked),
        "tube": bool(dsp_enabled and tube_enabled and not bit_perfect_locked),
        "widener": bool(dsp_enabled and widener_enabled and not bit_perfect_locked),
        "limiter": bool(dsp_enabled and limiter_enabled and not bit_perfect_locked),
        "resampler": bool(dsp_enabled and resampler_enabled and not bit_perfect_locked),
        "output_driver": bool(driver_available and dsp_enabled and not bit_perfect_locked),
        "output": bool(output_available and dsp_enabled and not bit_perfect_locked),
    }
    for slot_id, slot_info in player_lv2_slots.items():
        overview_enabled_state[slot_id] = bool(
            dsp_enabled and bool(slot_info.get("enabled", True)) and not bit_perfect_locked
        )
    if getattr(self, "dsp_master_switch", None) is not None:
        self._dsp_ui_syncing = True
        try:
            if bool(self.dsp_master_switch.get_active()) != dsp_enabled:
                self.dsp_master_switch.set_active(dsp_enabled)
        finally:
            self._dsp_ui_syncing = False
        self.dsp_master_switch.set_sensitive(True)
    if getattr(self, "dsp_master_summary_label", None) is not None:
        self.dsp_master_summary_label.set_text("")
        self.dsp_master_summary_label.set_visible(False)
    if getattr(self, "dsp_master_hint_label", None) is not None:
        self.dsp_master_hint_label.set_text(master_hint_text)
    if getattr(self, "dsp_peq_enable_switch", None) is not None:
        self._dsp_ui_syncing = True
        try:
            if bool(self.dsp_peq_enable_switch.get_active()) != peq_enabled:
                self.dsp_peq_enable_switch.set_active(peq_enabled)
        finally:
            self._dsp_ui_syncing = False
        self.dsp_peq_enable_switch.set_sensitive(True)
    if getattr(self, "dsp_peq_status_label", None) is not None:
        self.dsp_peq_status_label.set_text(peq_status_text)
    if getattr(self, "dsp_convolver_path_entry", None) is not None:
        try:
            if self.dsp_convolver_path_entry.get_text() != convolver_path:
                self.dsp_convolver_path_entry.set_text(convolver_path)
        except Exception:
            pass
    if getattr(self, "dsp_convolver_status_label", None) is not None:
        self.dsp_convolver_status_label.set_text(convolver_status_text)
    if getattr(self, "dsp_overview_output_driver_label", None) is not None:
        self.dsp_overview_output_driver_label.set_text(current_driver_name if driver_available else "Driver Unavailable")
    if getattr(self, "dsp_overview_output_label", None) is not None:
        self.dsp_overview_output_label.set_text(current_output_name if output_available else "Output Unavailable")
    for module_id, button in {
        "decode": getattr(self, "dsp_overview_decode_button", None),
        "output_driver": getattr(self, "dsp_overview_output_driver_button", None),
        "output": getattr(self, "dsp_overview_output_button", None),
    }.items():
        if button is None:
            continue
        button.set_tooltip_text(overview_status_text.get(module_id, "Unavailable"))
        button.remove_css_class("dsp-chain-button-active")
        button.remove_css_class("dsp-chain-button-inactive")
        button.remove_css_class("dsp-chain-button-io")
        button.add_css_class("dsp-chain-button-io")
        button.add_css_class("dsp-chain-button-active" if overview_enabled_state.get(module_id, False) else "dsp-chain-button-inactive")
    for module_id, button in dict(getattr(self, "dsp_overview_module_buttons", {}) or {}).items():
        if button is None:
            continue
        button.set_tooltip_text(overview_status_text.get(module_id, "Unavailable"))
        button.remove_css_class("dsp-chain-button-active")
        button.remove_css_class("dsp-chain-button-inactive")
        button.remove_css_class("dsp-chain-button-io")
        button.add_css_class("dsp-chain-button-active" if overview_enabled_state.get(module_id, False) else "dsp-chain-button-inactive")
    convolver_controls_sensitive = bool(dsp_enabled and convolver_path and not bit_perfect_locked)
    if getattr(self, "dsp_convolver_mix_scale", None) is not None:
        self._dsp_ui_syncing = True
        try:
            saved_mix = float(self.settings.get("dsp_convolver_mix", _DSP_CONVOLVER_MIX_DEFAULT))
            if abs(float(self.dsp_convolver_mix_scale.get_value()) - saved_mix) > 0.1:
                self.dsp_convolver_mix_scale.set_value(saved_mix)
        finally:
            self._dsp_ui_syncing = False
        self.dsp_convolver_mix_scale.set_sensitive(convolver_controls_sensitive)
    if getattr(self, "dsp_convolver_pre_delay_scale", None) is not None:
        self._dsp_ui_syncing = True
        try:
            saved_pd = float(self.settings.get("dsp_convolver_pre_delay_ms", _DSP_CONVOLVER_PRE_DELAY_DEFAULT))
            if abs(float(self.dsp_convolver_pre_delay_scale.get_value()) - saved_pd) > 0.1:
                self.dsp_convolver_pre_delay_scale.set_value(saved_pd)
        finally:
            self._dsp_ui_syncing = False
        self.dsp_convolver_pre_delay_scale.set_sensitive(convolver_controls_sensitive)
    if getattr(self, "dsp_limiter_threshold_scale", None) is not None:
        self._dsp_ui_syncing = True
        try:
            if abs(float(self.dsp_limiter_threshold_scale.get_value()) - limiter_threshold_pct) > 0.1:
                self.dsp_limiter_threshold_scale.set_value(limiter_threshold_pct)
        finally:
            self._dsp_ui_syncing = False
        self.dsp_limiter_threshold_scale.set_sensitive(bool(dsp_enabled))
    if getattr(self, "dsp_limiter_ratio_scale", None) is not None:
        self._dsp_ui_syncing = True
        try:
            if abs(float(self.dsp_limiter_ratio_scale.get_value()) - limiter_ratio) > 0.1:
                self.dsp_limiter_ratio_scale.set_value(limiter_ratio)
        finally:
            self._dsp_ui_syncing = False
        self.dsp_limiter_ratio_scale.set_sensitive(bool(dsp_enabled))
    if getattr(self, "dsp_limiter_status_label", None) is not None:
        self.dsp_limiter_status_label.set_text(limiter_status_text)
    if getattr(self, "dsp_resampler_status_label", None) is not None:
        self.dsp_resampler_status_label.set_text(resampler_status_text)
    if getattr(self, "dsp_resampler_rate_dropdown", None) is not None:
        self._dsp_ui_syncing = True
        try:
            saved_rate = int(self.settings.get("dsp_resampler_target_rate", 0) or 0)
            idx = _DSP_RESAMPLER_RATES.index(saved_rate) if saved_rate in _DSP_RESAMPLER_RATES else 0
            if self.dsp_resampler_rate_dropdown.get_selected() != idx:
                self.dsp_resampler_rate_dropdown.set_selected(idx)
        except Exception:
            pass
        finally:
            self._dsp_ui_syncing = False
        self.dsp_resampler_rate_dropdown.set_sensitive(bool(dsp_enabled))
    if getattr(self, "dsp_resampler_quality_dropdown", None) is not None:
        self._dsp_ui_syncing = True
        try:
            saved_quality = int(self.settings.get("dsp_resampler_quality", 10) or 10)
            qidx = _DSP_RESAMPLER_QUALITY_LEVELS.index(saved_quality) if saved_quality in _DSP_RESAMPLER_QUALITY_LEVELS else len(_DSP_RESAMPLER_QUALITY_LEVELS) - 1
            if self.dsp_resampler_quality_dropdown.get_selected() != qidx:
                self.dsp_resampler_quality_dropdown.set_selected(qidx)
        except Exception:
            pass
        finally:
            self._dsp_ui_syncing = False
        self.dsp_resampler_quality_dropdown.set_sensitive(bool(dsp_enabled))
    if getattr(self, "dsp_tape_status_label", None) is not None:
        self.dsp_tape_status_label.set_text(tape_status_text)
    if getattr(self, "dsp_tube_status_label", None) is not None:
        self.dsp_tube_status_label.set_text(tube_status_text)
    if getattr(self, "dsp_widener_status_label", None) is not None:
        self.dsp_widener_status_label.set_text(widener_status_text)
    if getattr(self, "dsp_tube_preset_dd", None) is not None:
        matched = next(
            (
                i for i, name in enumerate(_DSP_TUBE_PRESET_NAMES)
                if _DSP_TUBE_PRESETS[name] == (
                    tube_values["drive"],
                    tube_values["bias"],
                    tube_values["sag"],
                    tube_values["air"],
                )
            ),
            None,
        )
        self._dsp_ui_syncing = True
        try:
            target = matched if matched is not None else len(_DSP_TUBE_PRESET_NAMES)
            if self.dsp_tube_preset_dd.get_selected() != target:
                self.dsp_tube_preset_dd.set_selected(target)
        finally:
            self._dsp_ui_syncing = False
    if getattr(self, "dsp_tape_preset_dd", None) is not None:
        drive = int(self.settings.get("dsp_tape_drive", 30) or 30)
        tone = int(self.settings.get("dsp_tape_tone", 60) or 60)
        warmth = int(self.settings.get("dsp_tape_warmth", 40) or 40)
        matched = next(
            (i for i, name in enumerate(_DSP_TAPE_PRESET_NAMES)
             if _DSP_TAPE_PRESETS[name] == (drive, tone, warmth)),
            None,
        )
        self._dsp_ui_syncing = True
        try:
            target = matched if matched is not None else len(_DSP_TAPE_PRESET_NAMES)
            if self.dsp_tape_preset_dd.get_selected() != target:
                self.dsp_tape_preset_dd.set_selected(target)
        finally:
            self._dsp_ui_syncing = False
    for attr, key, default in [
        ("dsp_tape_drive_scale", "dsp_tape_drive", 30),
        ("dsp_tape_tone_scale", "dsp_tape_tone", 60),
        ("dsp_tape_warmth_scale", "dsp_tape_warmth", 40),
    ]:
        scale = getattr(self, attr, None)
        if scale is not None:
            self._dsp_ui_syncing = True
            try:
                saved_v = float(self.settings.get(key, default) or default)
                if abs(float(scale.get_value()) - saved_v) > 0.1:
                    scale.set_value(saved_v)
            finally:
                self._dsp_ui_syncing = False
            scale.set_sensitive(bool(dsp_enabled))
    for attr, tube_key in [
        ("dsp_tube_drive_scale", "drive"),
        ("dsp_tube_bias_scale", "bias"),
        ("dsp_tube_sag_scale", "sag"),
        ("dsp_tube_air_scale", "air"),
    ]:
        scale = getattr(self, attr, None)
        if scale is not None:
            self._dsp_ui_syncing = True
            try:
                saved_v = float(tube_values[tube_key])
                if abs(float(scale.get_value()) - saved_v) > 0.1:
                    scale.set_value(saved_v)
            finally:
                self._dsp_ui_syncing = False
            scale.set_sensitive(bool(dsp_enabled))
    if getattr(self, "dsp_widener_width_scale", None) is not None:
        self._dsp_ui_syncing = True
        try:
            if abs(float(self.dsp_widener_width_scale.get_value()) - float(widener_width)) > 0.1:
                self.dsp_widener_width_scale.set_value(float(widener_width))
        finally:
            self._dsp_ui_syncing = False
        self.dsp_widener_width_scale.set_sensitive(bool(dsp_enabled))
    for attr, value in [
        ("dsp_widener_bass_mono_freq_scale", widener_bass_mono_freq),
        ("dsp_widener_bass_mono_amount_scale", widener_bass_mono_amount),
    ]:
        scale = getattr(self, attr, None)
        if scale is not None:
            self._dsp_ui_syncing = True
            try:
                if abs(float(scale.get_value()) - float(value)) > 0.1:
                    scale.set_value(float(value))
            finally:
                self._dsp_ui_syncing = False
            scale.set_sensitive(bool(dsp_enabled))
    for module_id, switch in dict(getattr(self, "dsp_module_switches", {}) or {}).items():
        if switch is None:
            continue
        if module_id == "peq":
            self._dsp_ui_syncing = True
            try:
                if bool(switch.get_active()) != peq_enabled:
                    switch.set_active(peq_enabled)
            finally:
                self._dsp_ui_syncing = False
            switch.set_sensitive(bool(dsp_enabled))
            switch.set_tooltip_text("Enable or bypass parametric EQ")
        elif module_id == "convolver":
            self._dsp_ui_syncing = True
            try:
                if bool(switch.get_active()) != convolver_enabled:
                    switch.set_active(convolver_enabled)
            finally:
                self._dsp_ui_syncing = False
            can_toggle = bool(dsp_enabled and convolver_path)
            switch.set_sensitive(can_toggle)
            if not convolver_path:
                switch.set_tooltip_text("Load a FIR / IR file first")
            elif not dsp_enabled:
                switch.set_tooltip_text("Enable DSP master first")
            else:
                switch.set_tooltip_text("Enable or bypass convolution")
        elif module_id == "limiter":
            self._dsp_ui_syncing = True
            try:
                if bool(switch.get_active()) != limiter_enabled:
                    switch.set_active(limiter_enabled)
            finally:
                self._dsp_ui_syncing = False
            switch.set_sensitive(bool(dsp_enabled))
            switch.set_tooltip_text("Enable or bypass limiter" if dsp_enabled else "Enable DSP master first")
        elif module_id == "resampler":
            self._dsp_ui_syncing = True
            try:
                if bool(switch.get_active()) != resampler_enabled:
                    switch.set_active(resampler_enabled)
            finally:
                self._dsp_ui_syncing = False
            switch.set_sensitive(bool(dsp_enabled))
            switch.set_tooltip_text("Enable or bypass resampler" if dsp_enabled else "Enable DSP master first")
        elif module_id == "tube":
            self._dsp_ui_syncing = True
            try:
                if bool(switch.get_active()) != tube_enabled:
                    switch.set_active(tube_enabled)
            finally:
                self._dsp_ui_syncing = False
            switch.set_sensitive(bool(dsp_enabled))
            switch.set_tooltip_text("Enable or bypass tube stage" if dsp_enabled else "Enable DSP master first")
        elif module_id == "widener":
            self._dsp_ui_syncing = True
            try:
                if bool(switch.get_active()) != widener_enabled:
                    switch.set_active(widener_enabled)
            finally:
                self._dsp_ui_syncing = False
            switch.set_sensitive(bool(dsp_enabled))
            switch.set_tooltip_text("Enable or bypass stereo widener" if dsp_enabled else "Enable DSP master first")
        elif module_id == "tape":
            self._dsp_ui_syncing = True
            try:
                if bool(switch.get_active()) != tape_enabled:
                    switch.set_active(tape_enabled)
            finally:
                self._dsp_ui_syncing = False
            switch.set_sensitive(bool(dsp_enabled))
            switch.set_tooltip_text("Enable or bypass tape simulation" if dsp_enabled else "Enable DSP master first")
        else:
            switch.set_sensitive(False)
    lv2_row_refs = dict(getattr(self, "dsp_lv2_slot_rows", {}) or {})
    lv2_scales = dict(getattr(self, "dsp_lv2_slot_scales", {}) or {})
    player_lv2_slots = dict(getattr(player, "lv2_slots", {}) or {}) if player is not None else {}
    lv2_controls_sensitive = bool(dsp_enabled and not bit_perfect_locked)
    for slot_id, refs in lv2_row_refs.items():
        slot_enabled = bool((player_lv2_slots.get(slot_id) or {}).get("enabled", True))
        switch = (refs or {}).get("switch")
        remove_btn = (refs or {}).get("remove_btn")
        if switch is not None:
            self._dsp_ui_syncing = True
            try:
                if bool(switch.get_active()) != slot_enabled:
                    switch.set_active(slot_enabled)
            finally:
                self._dsp_ui_syncing = False
            switch.set_sensitive(lv2_controls_sensitive)
            if bit_perfect_locked:
                switch.set_tooltip_text("LV2 bypassed in Bit-Perfect mode")
            elif not dsp_enabled:
                switch.set_tooltip_text("Enable DSP master first")
            else:
                switch.set_tooltip_text("Enable or bypass LV2 plugin")
        if remove_btn is not None:
            remove_btn.set_sensitive(lv2_controls_sensitive)
            if bit_perfect_locked:
                remove_btn.set_tooltip_text("Unavailable while Bit-Perfect mode is enabled")
            elif not dsp_enabled:
                remove_btn.set_tooltip_text("Enable DSP master first")
            else:
                remove_btn.set_tooltip_text("Remove LV2 plugin")
    for slot_id, widgets in lv2_scales.items():
        slot_enabled = bool((player_lv2_slots.get(slot_id) or {}).get("enabled", True))
        controls_enabled = bool(lv2_controls_sensitive and slot_enabled)
        for widget in dict(widgets or {}).values():
            try:
                widget.set_sensitive(controls_enabled)
            except Exception:
                pass
    for btn in (getattr(self, "dsp_btn", None), getattr(self, "now_playing_dsp_btn", None)):
        if btn is None:
            continue
        btn.set_sensitive(True)
        btn.set_tooltip_text("Open DSP Workspace")
    if hasattr(self, "_sync_playback_status_icon"):
        self._sync_playback_status_icon()


def _release_bit_perfect_for_dsp(self):
    if not bool(getattr(self, "settings", {}).get("bit_perfect", False)):
        return True
    bp_switch = getattr(self, "bp_switch", None)
    try:
        self.on_bit_perfect_toggled(bp_switch, False)
    except Exception:
        logger.debug("disable bit-perfect for dsp failed", exc_info=True)
        return False
    try:
        if bp_switch is not None:
            bp_switch.set_active(False)
    except Exception:
        pass
    if hasattr(self, "show_output_notice"):
        try:
            self.show_output_notice("Bit-Perfect disabled: DSP processing enabled", "info", 2400)
        except Exception:
            pass
    return not bool(getattr(self, "settings", {}).get("bit_perfect", False))


def _on_dsp_master_toggled(self, switch, state):
    if getattr(self, "_dsp_ui_syncing", False):
        return False
    state = bool(state)
    player = getattr(self, "player", None)
    logger.info(
        "DSP master toggle request state=%s current_dsp_enabled=%s bit_perfect=%s lv2_slots=%s",
        state,
        bool(getattr(player, "dsp_enabled", False)),
        bool(getattr(self, "settings", {}).get("bit_perfect", False)),
        [
            (sid, bool((info or {}).get("enabled", True)))
            for sid, info in dict(getattr(player, "lv2_slots", {}) or {}).items()
        ] if player is not None else [],
    )
    if state and (not self._release_bit_perfect_for_dsp()):
        self._update_dsp_ui_state()
        return True
    try:
        ok = bool(self.player.set_dsp_enabled(state))
    except Exception:
        ok = False
        logger.debug("set_dsp_enabled failed", exc_info=True)
    if not ok:
        self._update_dsp_ui_state()
        return True
    self.settings["dsp_enabled"] = state
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    logger.info(
        "DSP master toggle applied state=%s player_dsp_enabled=%s",
        state,
        bool(getattr(player, "dsp_enabled", False)),
    )
    self._update_dsp_ui_state()
    logger.info(
        "DSP master toggle rebind hook available=%s",
        hasattr(self, "_lv2_restart_playback_for_graph_rebind"),
    )
    if hasattr(self, "_lv2_restart_playback_for_graph_rebind"):
        try:
            logger.info("DSP master toggle invoking playback rebind")
            self._lv2_restart_playback_for_graph_rebind(reason="dsp-master-toggle")
        except Exception:
            logger.debug("dsp master rebind failed", exc_info=True)
    return False


def _on_dsp_peq_toggled(self, switch, state):
    if getattr(self, "_dsp_ui_syncing", False):
        return False
    state = bool(state)
    if state and (not self._release_bit_perfect_for_dsp()):
        self._update_dsp_ui_state()
        return True
    try:
        ok = bool(self.player.set_peq_enabled(state))
    except Exception:
        ok = False
        logger.debug("set_peq_enabled failed", exc_info=True)
    if not ok:
        self._update_dsp_ui_state()
        return True
    settings = getattr(self, "settings", None)
    if isinstance(settings, dict):
        settings["dsp_peq_enabled"] = state
        settings["dsp_peq_bands"] = list(getattr(self, "eq_band_values", [0.0] * len(_EQ_FREQS)) or [])
    if isinstance(settings, dict) and hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    self._update_dsp_ui_state()
    return False


def _on_dsp_convolver_toggled(self, switch, state):
    if getattr(self, "_dsp_ui_syncing", False):
        return False
    state = bool(state)
    player = getattr(self, "player", None)
    current_path = str(getattr(player, "convolver_ir_path", "") or "").strip()
    entry = getattr(self, "dsp_convolver_path_entry", None)
    entry_path = ""
    if entry is not None:
        try:
            entry_path = str(entry.get_text() or "").strip()
        except Exception:
            entry_path = ""
    if state and not current_path:
        if entry_path:
            self._apply_dsp_convolver_path(entry_path, enable_after_load=True)
        else:
            self._dsp_convolver_last_error = "Load an FIR / IR file first"
            self._update_dsp_ui_state()
        return True
    if state and (not self._release_bit_perfect_for_dsp()):
        self._update_dsp_ui_state()
        return True
    try:
        ok = bool(self.player.set_convolver_enabled(state))
    except Exception:
        ok = False
        logger.debug("set_convolver_enabled failed", exc_info=True)
    if not ok:
        self._update_dsp_ui_state()
        return True
    self._dsp_convolver_last_error = ""
    self.settings["dsp_convolver_enabled"] = state
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    self._update_dsp_ui_state()
    return False


def _on_dsp_limiter_toggled(self, switch, state):
    if getattr(self, "_dsp_ui_syncing", False):
        return False
    state = bool(state)
    if state and (not self._release_bit_perfect_for_dsp()):
        self._update_dsp_ui_state()
        return True
    try:
        ok = bool(self.player.set_limiter_enabled(state))
    except Exception:
        ok = False
        logger.debug("set_limiter_enabled failed", exc_info=True)
    if not ok:
        self._dsp_limiter_last_error = "Failed to update limiter state"
        self._update_dsp_ui_state()
        return True
    self._dsp_limiter_last_error = ""
    self.settings["dsp_limiter_enabled"] = state
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    self._update_dsp_ui_state()
    return False


def _on_dsp_limiter_threshold_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = max(0.0, min(100.0, float(scale.get_value())))
    try:
        ok = bool(self.player.set_limiter_threshold(value / 100.0))
    except Exception:
        ok = False
        logger.debug("set_limiter_threshold failed", exc_info=True)
    if not ok:
        self._dsp_limiter_last_error = "Failed to update limiter ceiling"
        self._update_dsp_ui_state()
        return
    self._dsp_limiter_last_error = ""
    self.settings["dsp_limiter_threshold"] = int(round(value))
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    self._update_dsp_ui_state()


def _on_dsp_limiter_ratio_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = max(1.0, min(60.0, float(scale.get_value())))
    try:
        ok = bool(self.player.set_limiter_ratio(value))
    except Exception:
        ok = False
        logger.debug("set_limiter_ratio failed", exc_info=True)
    if not ok:
        self._dsp_limiter_last_error = "Failed to update limiter ratio"
        self._update_dsp_ui_state()
        return
    self._dsp_limiter_last_error = ""
    self.settings["dsp_limiter_ratio"] = int(round(value))
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    self._update_dsp_ui_state()


def _on_dsp_convolver_mix_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = max(0.0, min(100.0, float(scale.get_value())))
    try:
        ok = bool(self.player.set_convolver_mix(value / 100.0))
    except Exception:
        ok = False
        logger.debug("set_convolver_mix failed", exc_info=True)
    if not ok:
        return
    self.settings["dsp_convolver_mix"] = int(round(value))
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()


def _on_dsp_convolver_pre_delay_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = max(0.0, min(200.0, float(scale.get_value())))
    try:
        ok = bool(self.player.set_convolver_pre_delay(value))
    except Exception:
        ok = False
        logger.debug("set_convolver_pre_delay failed", exc_info=True)
    if not ok:
        return
    self.settings["dsp_convolver_pre_delay_ms"] = int(round(value))
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()


def _on_dsp_tape_preset_changed(self, dropdown, _pspec):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    idx = dropdown.get_selected()
    if idx < 0 or idx >= len(_DSP_TAPE_PRESET_NAMES):
        return
    name = _DSP_TAPE_PRESET_NAMES[idx]
    drive, tone, warmth = _DSP_TAPE_PRESETS[name]
    self._dsp_ui_syncing = True
    try:
        if getattr(self, "dsp_tape_drive_scale", None) is not None:
            self.dsp_tape_drive_scale.set_value(float(drive))
        if getattr(self, "dsp_tape_tone_scale", None) is not None:
            self.dsp_tape_tone_scale.set_value(float(tone))
        if getattr(self, "dsp_tape_warmth_scale", None) is not None:
            self.dsp_tape_warmth_scale.set_value(float(warmth))
    finally:
        self._dsp_ui_syncing = False
    try:
        self.player.set_tape_drive(drive)
        self.player.set_tape_tone(tone)
        self.player.set_tape_warmth(warmth)
    except Exception:
        logger.debug("apply tape preset failed", exc_info=True)
        return
    self.settings["dsp_tape_drive"] = drive
    self.settings["dsp_tape_tone"] = tone
    self.settings["dsp_tape_warmth"] = warmth
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()


def _on_dsp_tape_toggled(self, switch, state):
    if getattr(self, "_dsp_ui_syncing", False):
        return False
    state = bool(state)
    if state and (not self._release_bit_perfect_for_dsp()):
        self._update_dsp_ui_state()
        return True
    try:
        ok = bool(self.player.set_tape_enabled(state))
    except Exception:
        ok = False
        logger.debug("set_tape_enabled failed", exc_info=True)
    if not ok:
        self._update_dsp_ui_state()
        return True
    self.settings["dsp_tape_enabled"] = state
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    self._update_dsp_ui_state()
    return False


def _on_dsp_tape_drive_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = int(scale.get_value())
    try:
        self.player.set_tape_drive(value)
    except Exception:
        logger.debug("set_tape_drive failed", exc_info=True)
        return
    self.settings["dsp_tape_drive"] = value
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()


def _on_dsp_tape_tone_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = int(scale.get_value())
    try:
        self.player.set_tape_tone(value)
    except Exception:
        logger.debug("set_tape_tone failed", exc_info=True)
        return
    self.settings["dsp_tape_tone"] = value
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()


def _on_dsp_tape_warmth_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = int(scale.get_value())
    try:
        self.player.set_tape_warmth(value)
    except Exception:
        logger.debug("set_tape_warmth failed", exc_info=True)
        return
    self.settings["dsp_tape_warmth"] = value
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()


def _on_dsp_tube_toggled(self, switch, state):
    if getattr(self, "_dsp_ui_syncing", False):
        return False
    state = bool(state)
    if state and (not self._release_bit_perfect_for_dsp()):
        self._update_dsp_ui_state()
        return True
    try:
        ok = bool(self.player.set_tube_enabled(state))
    except Exception:
        ok = False
        logger.debug("set_tube_enabled failed", exc_info=True)
    if not ok:
        self._update_dsp_ui_state()
        return True
    self.settings["dsp_tube_enabled"] = state
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    self._update_dsp_ui_state()
    return False


def _on_dsp_tube_drive_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = int(scale.get_value())
    try:
        self.player.set_tube_drive(value)
    except Exception:
        logger.debug("set_tube_drive failed", exc_info=True)
        return
    self.settings["dsp_tube_drive"] = value
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()


def _on_dsp_tube_bias_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = int(scale.get_value())
    try:
        self.player.set_tube_bias(value)
    except Exception:
        logger.debug("set_tube_bias failed", exc_info=True)
        return
    self.settings["dsp_tube_bias"] = value
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()


def _on_dsp_tube_sag_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = int(scale.get_value())
    try:
        self.player.set_tube_sag(value)
    except Exception:
        logger.debug("set_tube_sag failed", exc_info=True)
        return
    self.settings["dsp_tube_sag"] = value
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()


def _on_dsp_tube_air_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = int(scale.get_value())
    try:
        self.player.set_tube_air(value)
    except Exception:
        logger.debug("set_tube_air failed", exc_info=True)
        return
    self.settings["dsp_tube_air"] = value
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()


def _on_dsp_tube_preset_changed(self, dropdown, _pspec):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    idx = dropdown.get_selected()
    if idx < 0 or idx >= len(_DSP_TUBE_PRESET_NAMES):
        return
    name = _DSP_TUBE_PRESET_NAMES[idx]
    drive, bias, sag, air = _DSP_TUBE_PRESETS[name]
    self._dsp_ui_syncing = True
    try:
        if getattr(self, "dsp_tube_drive_scale", None) is not None:
            self.dsp_tube_drive_scale.set_value(float(drive))
        if getattr(self, "dsp_tube_bias_scale", None) is not None:
            self.dsp_tube_bias_scale.set_value(float(bias))
        if getattr(self, "dsp_tube_sag_scale", None) is not None:
            self.dsp_tube_sag_scale.set_value(float(sag))
        if getattr(self, "dsp_tube_air_scale", None) is not None:
            self.dsp_tube_air_scale.set_value(float(air))
    finally:
        self._dsp_ui_syncing = False
    try:
        self.player.set_tube_drive(drive)
        self.player.set_tube_bias(bias)
        self.player.set_tube_sag(sag)
        self.player.set_tube_air(air)
    except Exception:
        logger.debug("apply tube preset failed", exc_info=True)
        return
    self.settings["dsp_tube_drive"] = drive
    self.settings["dsp_tube_bias"] = bias
    self.settings["dsp_tube_sag"] = sag
    self.settings["dsp_tube_air"] = air
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()


def _on_dsp_widener_toggled(self, switch, state):
    if getattr(self, "_dsp_ui_syncing", False):
        return False
    state = bool(state)
    if state and (not self._release_bit_perfect_for_dsp()):
        self._update_dsp_ui_state()
        return True
    try:
        ok = bool(self.player.set_widener_enabled(state))
    except Exception:
        ok = False
        logger.debug("set_widener_enabled failed", exc_info=True)
    if not ok:
        self._update_dsp_ui_state()
        return True
    self.settings["dsp_widener_enabled"] = state
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    self._update_dsp_ui_state()
    return False


def _on_dsp_widener_width_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = int(scale.get_value())
    try:
        self.player.set_widener_width(value)
    except Exception:
        logger.debug("set_widener_width failed", exc_info=True)
        return
    self.settings["dsp_widener_width"] = value
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    if hasattr(self, "_update_dsp_ui_state"):
        self._update_dsp_ui_state()


def _on_dsp_widener_bass_mono_freq_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = int(scale.get_value())
    try:
        self.player.set_widener_bass_mono_freq(value)
    except Exception:
        logger.debug("set_widener_bass_mono_freq failed", exc_info=True)
        return
    self.settings["dsp_widener_bass_mono_freq"] = value
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    if hasattr(self, "_update_dsp_ui_state"):
        self._update_dsp_ui_state()


def _on_dsp_widener_bass_mono_amount_changed(self, scale):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    value = int(scale.get_value())
    try:
        self.player.set_widener_bass_mono_amount(value)
    except Exception:
        logger.debug("set_widener_bass_mono_amount failed", exc_info=True)
        return
    self.settings["dsp_widener_bass_mono_amount"] = value
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    if hasattr(self, "_update_dsp_ui_state"):
        self._update_dsp_ui_state()


def _on_dsp_resampler_toggled(self, switch, state):
    if getattr(self, "_dsp_ui_syncing", False):
        return False
    state = bool(state)
    if state and (not self._release_bit_perfect_for_dsp()):
        self._update_dsp_ui_state()
        return True
    try:
        ok = bool(self.player.set_resampler_enabled(state))
    except Exception:
        ok = False
        logger.debug("set_resampler_enabled failed", exc_info=True)
    if not ok:
        self._update_dsp_ui_state()
        return True
    self.settings["dsp_resampler_enabled"] = state
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    self._update_dsp_ui_state()
    return False


def _on_dsp_resampler_rate_changed(self, dropdown, _pspec):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    idx = dropdown.get_selected()
    if idx < 0 or idx >= len(_DSP_RESAMPLER_RATES):
        return
    rate = _DSP_RESAMPLER_RATES[idx]
    try:
        ok = bool(self.player.set_resampler_target_rate(rate))
    except Exception:
        ok = False
        logger.debug("set_resampler_target_rate failed", exc_info=True)
    if not ok:
        return
    self.settings["dsp_resampler_target_rate"] = rate
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    self._update_dsp_ui_state()


def _on_dsp_resampler_quality_changed(self, dropdown, _pspec):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    idx = dropdown.get_selected()
    if idx < 0 or idx >= len(_DSP_RESAMPLER_QUALITY_LEVELS):
        return
    quality = _DSP_RESAMPLER_QUALITY_LEVELS[idx]
    try:
        ok = bool(self.player.set_resampler_quality(quality))
    except Exception:
        ok = False
        logger.debug("set_resampler_quality failed", exc_info=True)
    if not ok:
        return
    self.settings["dsp_resampler_quality"] = quality
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()


def _apply_dsp_order(self, order, save=True):
    normalized = _normalize_dsp_order(order)
    player = getattr(self, "player", None)
    if player is not None and hasattr(player, "set_dsp_order"):
        try:
            ok = bool(player.set_dsp_order(normalized))
        except Exception:
            ok = False
            logger.debug("set_dsp_order failed", exc_info=True)
        if not ok:
            return False
    self.settings["dsp_order"] = list(normalized)
    if save and hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()
    if hasattr(self, "_rebuild_dsp_overview_chain"):
        self._rebuild_dsp_overview_chain()
    if hasattr(self, "_update_dsp_ui_state"):
        self._update_dsp_ui_state()
    return True


def _refresh_dsp_order_edit_ui(self):
    editing = bool(getattr(self, "_dsp_order_editing", False))
    hint = getattr(self, "dsp_chain_hint_label", None)
    if hint is not None:
        hint.set_text(
            "Drag PEQ / Convolution / Tape / Tube / Stereo Widener and LV2 slots to reorder them, then save once to rebuild the chain."
            if editing
            else "Enter edit mode to reorder the middle DSP stages. Limiter and Resampler stay fixed at the tail."
        )
    for attr, visible in [
        ("dsp_order_edit_btn", not editing),
        ("dsp_order_save_btn", editing),
        ("dsp_order_cancel_btn", editing),
    ]:
        btn = getattr(self, attr, None)
        if btn is not None:
            btn.set_visible(visible)


def _dsp_overview_modules_per_row(self):
    available_width = 0
    chain_flow = getattr(self, "dsp_chain_flow", None)
    # Read chain_card (parent) width only — not chain_flow itself, which may be
    # wider than the card when overflowing and would create a feedback loop.
    card = getattr(chain_flow, "get_parent", lambda: None)() if chain_flow is not None else None
    if card is not None:
        try:
            available_width = int(card.get_width() or 0)
        except Exception:
            pass

    win = getattr(self, "win", None)
    if available_width <= 0 and win is not None:
        try:
            win_width = int(win.get_width() or 0)
        except Exception:
            win_width = 0
        if win_width <= 0:
            try:
                win_width = int(win.get_default_size()[0] or 0)
            except Exception:
                win_width = 0
        if win_width > 0:
            # Use actual sidebar ratio; avoid inflating with SIDEBAR_MIN_WIDTH.
            # Subtract card margins (12+12=24) to approximate chain_card.get_width().
            sidebar_width = max(int(win_width * float(ui_config.SIDEBAR_RATIO)), 120)
            available_width = max(0, win_width - sidebar_width - 24)
    if available_width <= 0:
        try:
            available_width = int(getattr(self, "saved_width", 0) or 0)
        except Exception:
            available_width = 0
    if available_width <= 0:
        available_width = int(getattr(ui_config, "WINDOW_WIDTH", 1250) or 1250)
    # Subtract CSS padding (16px each side) to get the usable inner content width.
    # Each module slot = 136px button + 40px connector; n slots need n*176 - 40px.
    usable_width = max(360, available_width - 32)
    return max(3, min(7, int((usable_width + 40) // 176) or 5))


def _queue_rebuild_dsp_overview_chain(self):
    pending = int(getattr(self, "_dsp_overview_rebuild_source", 0) or 0)
    if pending:
        return

    def _run():
        self._dsp_overview_rebuild_source = 0
        target = _dsp_overview_modules_per_row(self)
        if target != int(getattr(self, "_dsp_overview_modules_per_row_cached", 0) or 0):
            # Update cache before calling rebuild so the rebuild uses the new value.
            self._dsp_overview_modules_per_row_cached = target
            self._rebuild_dsp_overview_chain()
        return False

    # Use a short timeout instead of idle_add so the card has time to receive
    # its real allocation before we measure its width.
    self._dsp_overview_rebuild_source = GLib.timeout_add(80, _run)


def _build_dsp_chain_horizontal_connector(reverse=False):
    overlay = Gtk.Overlay(
        hexpand=True,
        halign=Gtk.Align.FILL,
        valign=Gtk.Align.CENTER,
        css_classes=["dsp-chain-connector", "dsp-chain-connector-horizontal"],
    )
    overlay.set_size_request(40, 20)
    line = Gtk.Box(hexpand=True, valign=Gtk.Align.CENTER, css_classes=["dsp-chain-connector-line"])
    overlay.set_child(line)
    head = Gtk.Label(
        label="◀" if reverse else "▶",
        halign=Gtk.Align.CENTER,
        valign=Gtk.Align.CENTER,
        css_classes=["dsp-chain-connector-head"],
    )
    overlay.add_overlay(head)
    return overlay


def _build_dsp_chain_vertical_connector():
    overlay = Gtk.Overlay(
        halign=Gtk.Align.CENTER,
        valign=Gtk.Align.FILL,
        css_classes=["dsp-chain-connector", "dsp-chain-connector-vertical"],
    )
    overlay.set_size_request(16, 56)
    overlay.set_vexpand(False)
    line = Gtk.Box(halign=Gtk.Align.CENTER, css_classes=["dsp-chain-connector-line-vertical"])
    line.set_vexpand(True)
    overlay.set_child(line)
    head = Gtk.Label(
        label="▼",
        halign=Gtk.Align.CENTER,
        valign=Gtk.Align.CENTER,
        css_classes=["dsp-chain-connector-head"],
    )
    overlay.add_overlay(head)
    return overlay


def _build_dsp_overview_module_cell(self, module_id, title, target_module=None, row_index=0):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, valign=Gtk.Align.CENTER)
    box.append(
        self._build_dsp_overview_module_row(
            module_id,
            title,
            target_module=target_module,
            row_index=row_index,
        )
    )
    return box


def _start_dsp_order_edit(self, _btn=None):
    self._dsp_order_editing = True
    self._dsp_order_pending = list(_normalize_dsp_order(getattr(self, "settings", {}).get("dsp_order")))
    self._rebuild_dsp_overview_chain()
    self._refresh_dsp_order_edit_ui()
    if hasattr(self, "_update_dsp_ui_state"):
        self._update_dsp_ui_state()


def _cancel_dsp_order_edit(self, _btn=None):
    self._dsp_order_editing = False
    self._dsp_order_pending = None
    self._rebuild_dsp_overview_chain()
    self._refresh_dsp_order_edit_ui()
    if hasattr(self, "_update_dsp_ui_state"):
        self._update_dsp_ui_state()


def _save_dsp_order_edit(self, _btn=None):
    pending = list(getattr(self, "_dsp_order_pending", None) or [])
    if not pending:
        self._cancel_dsp_order_edit()
        return
    if not self._apply_dsp_order(pending, save=True):
        if hasattr(self, "show_output_notice"):
            self.show_output_notice("Failed to rebuild DSP chain with the new order", "error", 2800)
        return
    self._dsp_order_editing = False
    self._dsp_order_pending = None
    self._rebuild_dsp_overview_chain()
    self._refresh_dsp_order_edit_ui()
    if hasattr(self, "_update_dsp_ui_state"):
        self._update_dsp_ui_state()
    _lv2_restart_playback_for_graph_rebind(self)
    if hasattr(self, "show_output_notice"):
        self.show_output_notice("DSP chain order saved", "ok", 2200)


def _rebuild_dsp_overview_chain(self):
    chain_flow = getattr(self, "dsp_chain_flow", None)
    if chain_flow is None:
        return
    child = chain_flow.get_first_child()
    while child is not None:
        next_child = child.get_next_sibling()
        chain_flow.remove(child)
        child = next_child

    self.dsp_overview_decode_button = None
    self.dsp_overview_output_driver_button = None
    self.dsp_overview_output_driver_label = None
    self.dsp_overview_output_button = None
    self.dsp_overview_output_label = None
    self.dsp_overview_module_buttons = {}

    order = _normalize_dsp_order(
        getattr(self, "_dsp_order_pending", None)
        if getattr(self, "_dsp_order_editing", False)
        else getattr(self, "settings", {}).get("dsp_order")
    )
    processing_chain = [("decode", None)] + [(module_id, module_id) for module_id in order] + [
        ("limiter", "limiter"),
        ("resampler", "resampler"),
        ("output_driver", None),
        ("output", None),
    ]
    # Use cached value when available so that entering/exiting edit mode doesn't
    # change the layout. The cache is updated by _queue_rebuild_dsp_overview_chain
    # when the card is resized (window resize or first allocation).
    cached = int(getattr(self, "_dsp_overview_modules_per_row_cached", 0) or 0)
    modules_per_row = cached if cached > 0 else _dsp_overview_modules_per_row(self)
    self._dsp_overview_modules_per_row_cached = modules_per_row
    chunks = [
        processing_chain[index:index + modules_per_row]
        for index in range(0, len(processing_chain), modules_per_row)
    ]

    for row_index, chunk in enumerate(chunks):
        reverse = bool(row_index % 2)
        row_entries = list(reversed(chunk)) if reverse else list(chunk)
        row_y = row_index * 2
        row_width = len(row_entries) * 2 - 1
        max_row_width = modules_per_row * 2 - 1
        column_offset = (max_row_width - row_width) if reverse else 0
        connector_column = None
        if row_index > 0:
            prev_chunk = chunks[row_index - 1]
            prev_reverse = bool((row_index - 1) % 2)
            prev_row_width = len(prev_chunk) * 2 - 1
            prev_column_offset = (max_row_width - prev_row_width) if prev_reverse else 0
            connector_column = (
                prev_column_offset if prev_reverse
                else (prev_column_offset + (len(prev_chunk) - 1) * 2)
            )
            chain_flow.attach(
                _build_dsp_chain_vertical_connector(),
                connector_column,
                row_y - 1,
                1,
                1,
            )
        for index, (module_id, target_module) in enumerate(row_entries):
            column = column_offset + (index * 2)
            chain_flow.attach(
                _build_dsp_overview_module_cell(
                    self,
                    module_id,
                    _dsp_overview_module_title(self, module_id),
                    target_module=target_module,
                    row_index=row_index,
                ),
                column,
                row_y,
                1,
                1,
            )
            if index < len(row_entries) - 1:
                chain_flow.attach(
                    _build_dsp_chain_horizontal_connector(reverse=reverse),
                    column + 1,
                    row_y,
                    1,
                    1,
                )


def _on_dsp_order_drop(self, source_module_id, target_module_id):
    src = str(source_module_id or "").strip()
    dst = str(target_module_id or "").strip()
    if not bool(getattr(self, "_dsp_order_editing", False)):
        return False
    if not _is_dsp_reorderable_module(src) or not _is_dsp_reorderable_module(dst) or src == dst:
        return False
    current = _normalize_dsp_order(getattr(self, "_dsp_order_pending", None))
    if src not in current or dst not in current:
        return False
    src_index = current.index(src)
    dst_index = current.index(dst)
    updated = [module_id for module_id in current if module_id != src]
    insert_at = updated.index(dst)
    if src_index < dst_index:
        insert_at += 1
    updated.insert(insert_at, src)
    self._dsp_order_pending = list(updated)
    self._rebuild_dsp_overview_chain()
    self._refresh_dsp_order_edit_ui()
    if hasattr(self, "_update_dsp_ui_state"):
        self._update_dsp_ui_state()
    return True


def _build_dsp_overview_module_row(self, module_id, title, target_module=None, row_index=0):
    is_reorderable = _is_dsp_reorderable_module(module_id)
    editing = bool(getattr(self, "_dsp_order_editing", False))
    handle = None
    content = None
    button = Gtk.Button(
        css_classes=["flat", "dsp-chain-button"],
        halign=Gtk.Align.CENTER,
        valign=Gtk.Align.CENTER,
    )
    button.set_size_request(136, 50)

    shell = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=4,
        margin_top=8,
        margin_bottom=6,
        margin_start=10,
        margin_end=10,
        valign=Gtk.Align.CENTER,
        vexpand=True,
    )

    title_label = Gtk.Label(
        label=title,
        xalign=0.5,
        yalign=0.5,
        justify=Gtk.Justification.CENTER,
        wrap=False,
        ellipsize=Pango.EllipsizeMode.END,
        max_width_chars=12,
        lines=1,
        hexpand=True,
        vexpand=True,
        css_classes=["settings-label", "dsp-chain-title"],
    )
    shell.append(title_label)

    overlay = Gtk.Overlay()
    overlay.set_child(shell)

    lamp = Gtk.Box(
        width_request=14,
        height_request=8,
        halign=Gtk.Align.END,
        valign=Gtk.Align.START,
        margin_top=9,
        margin_end=10,
        css_classes=["dsp-chain-lamp"],
    )
    overlay.add_overlay(lamp)

    if is_reorderable and editing:
        handle = Gtk.Image.new_from_icon_name("open-menu-symbolic")
        handle.add_css_class("dsp-chain-handle")
        handle.set_halign(Gtk.Align.START)
        handle.set_valign(Gtk.Align.START)
        handle.set_margin_top(8)
        handle.set_margin_start(8)
        try:
            handle.set_cursor_from_name("pointer")
        except Exception:
            pass
        overlay.add_overlay(handle)
    content = overlay

    button.set_child(content)

    def _open_module(_btn, target_module=target_module):
        if not target_module:
            return
        if getattr(self, "dsp_workspace_stack", None) is not None:
            self.dsp_workspace_stack.set_visible_child_name("effects")
        self._show_dsp_module(target_module, select_row=True)

    if target_module:
        button.connect("clicked", _open_module)
    else:
        button.set_can_focus(False)

    if is_reorderable and editing:
        drag_source = Gtk.DragSource.new()
        drag_source.set_actions(Gdk.DragAction.MOVE)
        drag_source.connect(
            "prepare",
            lambda _src, _x, _y, value=module_id: Gdk.ContentProvider.new_for_value(value),
        )
        def _on_drag_begin(_src, _drag):
            try:
                self._dsp_order_drag_active = True
                _suppress_search_focus_temporarily(self, duration_ms=500)
            except Exception:
                logger.debug("dsp drag icon setup failed", exc_info=True)

        def _on_drag_end(*_args):
            self._dsp_order_drag_active = False
            _suppress_search_focus_temporarily(self, duration_ms=500)

        def _on_drag_cancel(*_args):
            self._dsp_order_drag_active = False
            _suppress_search_focus_temporarily(self, duration_ms=500)
            return False

        drag_source.connect("drag-begin", _on_drag_begin)
        drag_source.connect("drag-end", _on_drag_end)
        drag_source.connect("drag-cancel", _on_drag_cancel)
        if handle is not None:
            handle.add_controller(drag_source)
        else:
            button.add_controller(drag_source)

        drop_target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)

        def _on_drop(_target, value, _x, _y, dst=module_id):
            self._dsp_order_drag_active = False
            return bool(self._on_dsp_order_drop(value, dst))

        drop_target.connect("drop", _on_drop)
        button.add_controller(drop_target)

    if module_id == "decode":
        self.dsp_overview_decode_button = button
    elif module_id == "output_driver":
        self.dsp_overview_output_driver_button = button
        self.dsp_overview_output_driver_label = title_label
    elif module_id == "output":
        self.dsp_overview_output_button = button
        self.dsp_overview_output_label = title_label
    else:
        self.dsp_overview_module_buttons[module_id] = button
    return button


def _build_dsp_workspace(self):
    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=10,
        margin_bottom=8,
        margin_start=18,
        margin_end=18,
        css_classes=["dsp-workspace"],
    )

    self.dsp_module_summary_labels = {}
    self.dsp_module_state_labels = {}
    self.dsp_control_label_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
    self.dsp_overview_decode_button = None
    self.dsp_overview_output_driver_button = None
    self.dsp_overview_output_driver_label = None
    self.dsp_overview_output_button = None
    self.dsp_overview_output_label = None
    self.dsp_overview_module_buttons = {}
    self.dsp_module_switches = {}

    switcher_row = Gtk.Box(spacing=12, hexpand=True, halign=Gtk.Align.FILL, valign=Gtk.Align.CENTER)
    self.dsp_workspace_switcher = Gtk.StackSwitcher()
    self.dsp_workspace_switcher.set_halign(Gtk.Align.START)
    self.dsp_workspace_switcher.add_css_class("dsp-workspace-switcher")
    switcher_row.append(self.dsp_workspace_switcher)
    right_ctrl = Gtk.Box(spacing=10, halign=Gtk.Align.END)
    switcher_row.append(Gtk.Box(hexpand=True))
    right_ctrl.append(Gtk.Label(label="DSP", xalign=1, css_classes=["title-5"]))
    self.dsp_master_summary_label = Gtk.Label(label="", xalign=0, css_classes=["dim-label"])
    self.dsp_master_hint_label = Gtk.Label(label="", xalign=0, wrap=True, css_classes=["dim-label"])
    self.dsp_master_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
    self.dsp_master_switch.connect("state-set", self._on_dsp_master_toggled)
    right_ctrl.append(self.dsp_master_switch)
    dsp_help_btn = Gtk.MenuButton(css_classes=["flat", "circular"], valign=Gtk.Align.CENTER)
    dsp_help_btn.set_icon_name("dialog-question-symbolic")
    dsp_help_btn.set_tooltip_text("LV2 Plugin Compatibility")
    dsp_help_btn.set_popover(self._build_dsp_lv2_help_popover())
    right_ctrl.append(dsp_help_btn)
    right_ctrl.set_margin_end(52)
    switcher_row.append(right_ctrl)
    root.append(switcher_row)

    self.dsp_workspace_stack = Gtk.Stack(
        transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
        hexpand=True,
        vexpand=True,
    )
    self.dsp_workspace_switcher.set_stack(self.dsp_workspace_stack)
    root.append(self.dsp_workspace_stack)

    overview_page = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        hexpand=True,
        vexpand=True,
        css_classes=["dsp-overview-page"],
    )

    chain_card = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=10,
        margin_top=0,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
        css_classes=["dsp-detail-card", "dsp-chain-card"],
    )
    chain_title = Gtk.Box(spacing=12)
    chain_title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
    chain_title_box.append(Gtk.Label(label="Signal Chain", xalign=0, css_classes=["title-4"]))
    self.dsp_chain_hint_label = Gtk.Label(
        label="Enter edit mode to reorder the middle DSP stages. Limiter and Resampler stay fixed at the tail.",
        xalign=0,
        wrap=True,
        css_classes=["dim-label"],
    )
    chain_title_box.append(self.dsp_chain_hint_label)
    chain_title.append(chain_title_box)
    chain_actions = Gtk.Box(spacing=8, valign=Gtk.Align.START)
    self.dsp_order_edit_btn = Gtk.Button(
        icon_name="document-edit-symbolic",
        css_classes=["flat", "circular"],
    )
    self.dsp_order_edit_btn.set_tooltip_text("Edit DSP Order")
    self.dsp_order_edit_btn.connect("clicked", self._start_dsp_order_edit)
    chain_actions.append(self.dsp_order_edit_btn)
    self.dsp_order_save_btn = Gtk.Button(label="Save", css_classes=["suggested-action"])
    self.dsp_order_save_btn.connect("clicked", self._save_dsp_order_edit)
    chain_actions.append(self.dsp_order_save_btn)
    self.dsp_order_cancel_btn = Gtk.Button(label="Cancel", css_classes=["flat"])
    self.dsp_order_cancel_btn.connect("clicked", self._cancel_dsp_order_edit)
    chain_actions.append(self.dsp_order_cancel_btn)
    chain_title.append(chain_actions)
    chain_card.append(chain_title)
    chain_flow = Gtk.Grid(
        column_spacing=0,
        row_spacing=0,
        halign=Gtk.Align.CENTER,
        valign=Gtk.Align.CENTER,
        css_classes=["dsp-chain-grid"],
    )
    self.dsp_chain_flow = chain_flow
    chain_card.connect("notify::width", lambda *_args: self._queue_rebuild_dsp_overview_chain())
    if getattr(self, "win", None) is not None:
        self.win.connect("notify::width", lambda *_args: self._queue_rebuild_dsp_overview_chain())
    self._rebuild_dsp_overview_chain()
    GLib.idle_add(lambda: (self._queue_rebuild_dsp_overview_chain(), False)[1])
    self._refresh_dsp_order_edit_ui()
    chain_card.append(chain_flow)
    overview_page.append(chain_card)
    overview_scroll = _build_dsp_scroll_area(overview_page)
    self.dsp_workspace_stack.add_titled(overview_scroll, "overview", "Overview")

    effects_page = Gtk.Grid(
        column_spacing=18,
        row_spacing=0,
        column_homogeneous=True,
        hexpand=True,
        vexpand=True,
        margin_start=12,
        margin_end=12,
        css_classes=["dsp-effects-page"],
    )

    sidebar = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        hexpand=True,
        halign=Gtk.Align.FILL,
        css_classes=["dsp-sidebar"],
    )

    module_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["dsp-module-list"])
    module_list.set_margin_top(12)
    module_list.connect("row-selected", self._on_dsp_module_selected)
    self.dsp_module_list = module_list
    for module_id, title in _DSP_MODULES:
        row = Gtk.ListBoxRow()
        row.dsp_module_id = module_id
        row.set_activatable(False)
        row.set_margin_top(5)
        row.set_margin_bottom(5)
        box = Gtk.Box(spacing=10, margin_top=10, margin_bottom=10, margin_start=12, margin_end=12, valign=Gtk.Align.CENTER)
        info = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            hexpand=True,
            halign=Gtk.Align.FILL,
            valign=Gtk.Align.CENTER,
        )
        info.append(Gtk.Label(label=title, xalign=0, css_classes=["settings-label"], hexpand=True))
        box.append(info)
        switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        if module_id == "peq":
            switch.connect("state-set", self._on_dsp_peq_toggled)
        elif module_id == "convolver":
            switch.connect("state-set", self._on_dsp_convolver_toggled)
            self.dsp_convolver_enable_switch = switch
        elif module_id == "limiter":
            switch.connect("state-set", self._on_dsp_limiter_toggled)
            self.dsp_limiter_enable_switch = switch
        elif module_id == "tape":
            switch.connect("state-set", self._on_dsp_tape_toggled)
            self.dsp_tape_enable_switch = switch
        elif module_id == "tube":
            switch.connect("state-set", self._on_dsp_tube_toggled)
            self.dsp_tube_enable_switch = switch
        elif module_id == "widener":
            switch.connect("state-set", self._on_dsp_widener_toggled)
            self.dsp_widener_enable_switch = switch
        elif module_id == "resampler":
            switch.connect("state-set", self._on_dsp_resampler_toggled)
            self.dsp_resampler_enable_switch = switch
        else:
            switch.set_sensitive(False)
        box.append(switch)
        row.set_child(box)
        module_list.append(row)
        self.dsp_module_switches[module_id] = switch
    sidebar.append(module_list)

    # LV2 dynamic slot rows
    lv2_module_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["dsp-module-list"])
    lv2_module_list.set_margin_top(4)
    lv2_module_list.connect("row-selected", self._on_dsp_module_selected)
    lv2_module_list.set_visible(False)
    self.dsp_lv2_module_list = lv2_module_list
    logger.info("DSP workspace created lv2 listbox id=%s", hex(id(lv2_module_list)))
    sidebar.append(lv2_module_list)

    add_lv2_btn = Gtk.Button(
        label="Add LV2 Plugin",
        icon_name="list-add-symbolic",
        css_classes=["flat"],
        margin_top=4,
        margin_bottom=4,
        margin_start=8,
        margin_end=8,
    )
    self.add_lv2_plugin_btn = add_lv2_btn
    add_lv2_btn.connect("clicked", self._open_lv2_plugin_browser)
    _lv2_update_browser_action_state(self)
    sidebar.append(add_lv2_btn)
    sidebar_scroll = _build_dsp_scroll_area(sidebar)

    effects_page.attach(sidebar_scroll, 0, 0, 1, 1)

    detail_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, hexpand=True, vexpand=True)
    self.dsp_module_stack = detail_stack

    peq_page = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=14,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
        valign=Gtk.Align.START,
        css_classes=["dsp-detail-card"],
    )
    peq_head = Gtk.Box(spacing=12)
    peq_title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
    peq_title_box.append(Gtk.Label(label="Parametric EQ", xalign=0, css_classes=["title-4"]))
    self.dsp_peq_status_label = None
    peq_head.append(peq_title_box)
    self.dsp_peq_preset_dd = Gtk.DropDown(model=Gtk.StringList.new(_DSP_PRESET_NAMES + ["Custom"]))
    self.dsp_peq_preset_dd.add_css_class("dsp-preset-dd")
    self.dsp_peq_preset_dd.set_valign(Gtk.Align.CENTER)
    self.dsp_peq_preset_dd.connect("notify::selected-item", self._on_dsp_preset_changed)
    peq_head.append(self.dsp_peq_preset_dd)
    self.dsp_peq_enable_switch = None
    reset_btn = Gtk.Button(label="Reset", css_classes=["flat"])
    reset_btn.connect("clicked", lambda _b: self._reset_eq_ui())
    peq_head.append(reset_btn)
    peq_page.append(peq_head)
    peq_page.append(self._build_eq_editor_content(sliders_attr="dsp_peq_sliders", show_header=False))
    detail_stack.add_titled(_build_dsp_detail_page(peq_page), "peq", "PEQ")

    convolver_page = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=14,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
        valign=Gtk.Align.START,
        css_classes=["dsp-detail-card"],
    )
    convolver_title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    convolver_title_box.append(Gtk.Label(label="Convolution", xalign=0, css_classes=["title-4"]))
    convolver_title_box.append(
        Gtk.Label(
            label="Mono FIR / IR kernel applied across playback channels",
            xalign=0,
            wrap=True,
            css_classes=["dim-label"],
        )
    )
    convolver_page.append(convolver_title_box)
    path_row = Gtk.Box(spacing=8)
    self.dsp_convolver_path_entry = Gtk.Entry(
        hexpand=True,
        placeholder_text="Choose a .wav, .txt, or .csv FIR / IR file",
        editable=False,
    )
    path_row.append(self.dsp_convolver_path_entry)
    choose_btn = Gtk.Button(label="Choose File", css_classes=["flat"])
    choose_btn.connect("clicked", self._open_dsp_convolver_file_dialog)
    path_row.append(choose_btn)
    clear_btn = Gtk.Button(label="Clear", css_classes=["flat"])
    clear_btn.connect("clicked", lambda _b: self._clear_dsp_convolver_path())
    path_row.append(clear_btn)
    convolver_page.append(path_row)
    self.dsp_convolver_status_label = Gtk.Label(
        label="Load a .wav, .txt, or .csv FIR / IR file",
        xalign=0,
        wrap=True,
        css_classes=["dim-label"],
    )
    convolver_page.append(self.dsp_convolver_status_label)
    conv_controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    mix_row = Gtk.Box(spacing=12)
    mix_row.set_valign(Gtk.Align.START)
    mix_row.append(_build_dsp_control_label(self, "Wet Mix"))
    self.dsp_convolver_mix_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
    _configure_dsp_scale(self.dsp_convolver_mix_scale)
    self.dsp_convolver_mix_scale.set_hexpand(True)
    self.dsp_convolver_mix_scale.set_valign(Gtk.Align.CENTER)
    self.dsp_convolver_mix_scale.set_value(float(self.settings.get("dsp_convolver_mix", _DSP_CONVOLVER_MIX_DEFAULT)))
    self.dsp_convolver_mix_scale.connect("value-changed", self._on_dsp_convolver_mix_changed)
    mix_row.append(self.dsp_convolver_mix_scale)
    conv_controls_box.append(mix_row)
    pre_delay_row = Gtk.Box(spacing=12)
    pre_delay_row.set_valign(Gtk.Align.START)
    pre_delay_row.append(_build_dsp_control_label(self, "Pre-Delay (ms)"))
    self.dsp_convolver_pre_delay_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 200, 5)
    _configure_dsp_scale(self.dsp_convolver_pre_delay_scale)
    self.dsp_convolver_pre_delay_scale.set_hexpand(True)
    self.dsp_convolver_pre_delay_scale.set_valign(Gtk.Align.CENTER)
    self.dsp_convolver_pre_delay_scale.set_value(float(self.settings.get("dsp_convolver_pre_delay_ms", _DSP_CONVOLVER_PRE_DELAY_DEFAULT)))
    self.dsp_convolver_pre_delay_scale.connect("value-changed", self._on_dsp_convolver_pre_delay_changed)
    pre_delay_row.append(self.dsp_convolver_pre_delay_scale)
    conv_controls_box.append(pre_delay_row)
    convolver_page.append(conv_controls_box)
    convolver_page.append(
        Gtk.Label(
            label="WAV IRs support stereo. Text files should contain one coefficient list separated by whitespace, commas, or semicolons.",
            xalign=0,
            wrap=True,
            css_classes=["caption"],
        )
    )
    detail_stack.add_titled(_build_dsp_detail_page(convolver_page), "convolver", "Convolution")

    tape_page = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=10,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
        valign=Gtk.Align.START,
        css_classes=["dsp-detail-card"],
    )
    tape_page.set_vexpand(False)
    tape_head = Gtk.Box(spacing=12)
    tape_title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
    tape_title_box.append(Gtk.Label(label="Tape Simulation", xalign=0, css_classes=["title-4"]))
    tape_title_box.append(
        Gtk.Label(
            label="Magnetic tape character: harmonic saturation, warmth, and HF bandwidth shaping.",
            xalign=0,
            wrap=True,
            css_classes=["dim-label"],
        )
    )
    tape_head.append(tape_title_box)
    self.dsp_tape_preset_dd = Gtk.DropDown(
        model=Gtk.StringList.new(_DSP_TAPE_PRESET_NAMES + ["Custom"]),
        valign=Gtk.Align.CENTER,
    )
    self.dsp_tape_preset_dd.add_css_class("dsp-preset-dd")
    self.dsp_tape_preset_dd.connect("notify::selected-item", self._on_dsp_tape_preset_changed)
    tape_head.append(self.dsp_tape_preset_dd)
    tape_page.append(tape_head)
    self.dsp_tape_status_label = Gtk.Label(
        label="Tape simulation bypassed",
        xalign=0,
        wrap=True,
        css_classes=["dim-label"],
    )
    tape_page.append(self.dsp_tape_status_label)
    tape_controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    tape_controls_box.set_vexpand(False)
    drive_row = Gtk.Box(spacing=12)
    drive_row.set_valign(Gtk.Align.START)
    drive_row.append(_build_dsp_control_label(self, "Drive"))
    self.dsp_tape_drive_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
    _configure_dsp_scale(self.dsp_tape_drive_scale)
    self.dsp_tape_drive_scale.set_hexpand(True)
    self.dsp_tape_drive_scale.set_valign(Gtk.Align.CENTER)
    self.dsp_tape_drive_scale.set_value(float(self.settings.get("dsp_tape_drive", 30) or 30))
    self.dsp_tape_drive_scale.connect("value-changed", self._on_dsp_tape_drive_changed)
    drive_row.append(self.dsp_tape_drive_scale)
    tape_controls_box.append(drive_row)
    tone_row = Gtk.Box(spacing=12)
    tone_row.set_valign(Gtk.Align.START)
    tone_row.append(_build_dsp_control_label(self, "Tone"))
    self.dsp_tape_tone_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
    _configure_dsp_scale(self.dsp_tape_tone_scale)
    self.dsp_tape_tone_scale.set_hexpand(True)
    self.dsp_tape_tone_scale.set_valign(Gtk.Align.CENTER)
    self.dsp_tape_tone_scale.set_value(float(self.settings.get("dsp_tape_tone", 60) or 60))
    self.dsp_tape_tone_scale.connect("value-changed", self._on_dsp_tape_tone_changed)
    tone_row.append(self.dsp_tape_tone_scale)
    tape_controls_box.append(tone_row)
    warmth_row = Gtk.Box(spacing=12)
    warmth_row.set_valign(Gtk.Align.START)
    warmth_row.append(_build_dsp_control_label(self, "Warmth"))
    self.dsp_tape_warmth_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
    _configure_dsp_scale(self.dsp_tape_warmth_scale)
    self.dsp_tape_warmth_scale.set_hexpand(True)
    self.dsp_tape_warmth_scale.set_valign(Gtk.Align.CENTER)
    self.dsp_tape_warmth_scale.set_value(float(self.settings.get("dsp_tape_warmth", 40) or 40))
    self.dsp_tape_warmth_scale.connect("value-changed", self._on_dsp_tape_warmth_changed)
    warmth_row.append(self.dsp_tape_warmth_scale)
    tape_controls_box.append(warmth_row)
    tape_page.append(tape_controls_box)
    tape_page.append(
        Gtk.Label(
            label="Drive adds harmonic saturation. Tone controls HF presence (dark to bright). Warmth boosts low-frequency body.",
            xalign=0,
            wrap=True,
            css_classes=["caption"],
        )
    )
    detail_stack.add_titled(_build_dsp_detail_page(tape_page), "tape", "Tape")

    tube_page = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=10,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
        valign=Gtk.Align.START,
        css_classes=["dsp-detail-card"],
    )
    tube_page.set_vexpand(False)
    tube_head = Gtk.Box(spacing=12)
    tube_title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
    tube_title_box.append(Gtk.Label(label="Tube Stage", xalign=0, css_classes=["title-4"]))
    tube_title_box.append(
        Gtk.Label(
            label="Tube-style headphone amp flavour: asymmetric saturation, gentle sag, and softened air band.",
            xalign=0,
            wrap=True,
            css_classes=["dim-label"],
        )
    )
    tube_head.append(tube_title_box)
    self.dsp_tube_preset_dd = Gtk.DropDown(
        model=Gtk.StringList.new(_DSP_TUBE_PRESET_NAMES + ["Custom"]),
        valign=Gtk.Align.CENTER,
    )
    self.dsp_tube_preset_dd.add_css_class("dsp-preset-dd")
    self.dsp_tube_preset_dd.connect("notify::selected-item", self._on_dsp_tube_preset_changed)
    tube_head.append(self.dsp_tube_preset_dd)
    tube_page.append(tube_head)
    self.dsp_tube_status_label = Gtk.Label(
        label="Tube stage bypassed",
        xalign=0,
        wrap=True,
        css_classes=["dim-label"],
    )
    tube_page.append(self.dsp_tube_status_label)
    tube_controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    tube_controls_box.set_vexpand(False)
    for label_text, attr_name, key_name, default_value, handler in [
        ("Drive", "dsp_tube_drive_scale", "dsp_tube_drive", _DSP_TUBE_DEFAULTS["drive"], self._on_dsp_tube_drive_changed),
        ("Bias", "dsp_tube_bias_scale", "dsp_tube_bias", _DSP_TUBE_DEFAULTS["bias"], self._on_dsp_tube_bias_changed),
        ("Sag", "dsp_tube_sag_scale", "dsp_tube_sag", _DSP_TUBE_DEFAULTS["sag"], self._on_dsp_tube_sag_changed),
        ("Air", "dsp_tube_air_scale", "dsp_tube_air", _DSP_TUBE_DEFAULTS["air"], self._on_dsp_tube_air_changed),
    ]:
        row = Gtk.Box(spacing=12)
        row.set_valign(Gtk.Align.START)
        row.append(_build_dsp_control_label(self, label_text))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        _configure_dsp_scale(scale)
        scale.set_hexpand(True)
        scale.set_valign(Gtk.Align.CENTER)
        scale.set_value(float(self.settings.get(key_name, default_value) or default_value))
        scale.connect("value-changed", handler)
        setattr(self, attr_name, scale)
        row.append(scale)
        tube_controls_box.append(row)
    tube_page.append(tube_controls_box)
    tube_page.append(
        Gtk.Label(
            label="Drive pushes more harmonic colour. Bias increases even-order tube sweetness. Sag softens hard transients. Air opens or darkens the top end.",
            xalign=0,
            wrap=True,
            css_classes=["caption"],
        )
    )
    detail_stack.add_titled(_build_dsp_detail_page(tube_page), "tube", "Tube")

    widener_page = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=10,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
        valign=Gtk.Align.START,
        css_classes=["dsp-detail-card"],
    )
    widener_page.set_vexpand(False)
    widener_title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    widener_title_box.append(Gtk.Label(label="Stereo Widener", xalign=0, css_classes=["title-4"]))
    widener_title_box.append(
        Gtk.Label(
            label="Mid/Side width expansion to open the stereo stage while keeping the center anchored.",
            xalign=0,
            wrap=True,
            css_classes=["dim-label"],
        )
    )
    widener_page.append(widener_title_box)
    self.dsp_widener_status_label = Gtk.Label(
        label="Stereo widener bypassed",
        xalign=0,
        wrap=True,
        css_classes=["dim-label"],
    )
    widener_page.append(self.dsp_widener_status_label)
    width_row = Gtk.Box(spacing=12)
    width_row.set_valign(Gtk.Align.START)
    width_row.append(_build_dsp_control_label(self, "Width"))
    self.dsp_widener_width_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 200, 1)
    _configure_dsp_scale(self.dsp_widener_width_scale)
    self.dsp_widener_width_scale.set_hexpand(True)
    self.dsp_widener_width_scale.set_valign(Gtk.Align.CENTER)
    self.dsp_widener_width_scale.set_value(float(self.settings.get("dsp_widener_width", _DSP_WIDENER_WIDTH_DEFAULT) or _DSP_WIDENER_WIDTH_DEFAULT))
    self.dsp_widener_width_scale.connect("value-changed", self._on_dsp_widener_width_changed)
    width_row.append(self.dsp_widener_width_scale)
    widener_page.append(width_row)
    bass_freq_row = Gtk.Box(spacing=12)
    bass_freq_row.set_valign(Gtk.Align.START)
    bass_freq_row.append(_build_dsp_control_label(self, "Bass Mono Freq"))
    self.dsp_widener_bass_mono_freq_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 40, 250, 5)
    _configure_dsp_scale(self.dsp_widener_bass_mono_freq_scale)
    self.dsp_widener_bass_mono_freq_scale.set_hexpand(True)
    self.dsp_widener_bass_mono_freq_scale.set_valign(Gtk.Align.CENTER)
    self.dsp_widener_bass_mono_freq_scale.set_value(float(self.settings.get("dsp_widener_bass_mono_freq", _DSP_WIDENER_BASS_MONO_FREQ_DEFAULT) or _DSP_WIDENER_BASS_MONO_FREQ_DEFAULT))
    self.dsp_widener_bass_mono_freq_scale.connect("value-changed", self._on_dsp_widener_bass_mono_freq_changed)
    bass_freq_row.append(self.dsp_widener_bass_mono_freq_scale)
    widener_page.append(bass_freq_row)
    bass_amount_row = Gtk.Box(spacing=12)
    bass_amount_row.set_valign(Gtk.Align.START)
    bass_amount_row.append(_build_dsp_control_label(self, "Bass Mono Amount"))
    self.dsp_widener_bass_mono_amount_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
    _configure_dsp_scale(self.dsp_widener_bass_mono_amount_scale)
    self.dsp_widener_bass_mono_amount_scale.set_hexpand(True)
    self.dsp_widener_bass_mono_amount_scale.set_valign(Gtk.Align.CENTER)
    self.dsp_widener_bass_mono_amount_scale.set_value(float(self.settings.get("dsp_widener_bass_mono_amount", _DSP_WIDENER_BASS_MONO_AMOUNT_DEFAULT) or _DSP_WIDENER_BASS_MONO_AMOUNT_DEFAULT))
    self.dsp_widener_bass_mono_amount_scale.connect("value-changed", self._on_dsp_widener_bass_mono_amount_changed)
    bass_amount_row.append(self.dsp_widener_bass_mono_amount_scale)
    widener_page.append(bass_amount_row)
    widener_page.append(
        Gtk.Label(
            label="100% keeps the original image. Bass Mono folds low-frequency side energy back to the center so wide settings stay solid and focused.",
            xalign=0,
            wrap=True,
            css_classes=["caption"],
        )
    )
    detail_stack.add_titled(_build_dsp_detail_page(widener_page), "widener", "Widener")

    limiter_page = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=10,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
        valign=Gtk.Align.START,
        css_classes=["dsp-detail-card"],
    )
    limiter_page.set_vexpand(False)
    limiter_title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    limiter_title_box.append(Gtk.Label(label="Limiter", xalign=0, css_classes=["title-4"]))
    limiter_title_box.append(
        Gtk.Label(
            label="Clip-guard style compressor to catch overs and tame aggressive peaks.",
            xalign=0,
            wrap=True,
            css_classes=["dim-label"],
        )
    )
    limiter_page.append(limiter_title_box)
    self.dsp_limiter_status_label = Gtk.Label(
        label="Limiter bypassed",
        xalign=0,
        wrap=True,
        css_classes=["dim-label"],
    )
    limiter_page.append(self.dsp_limiter_status_label)
    controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    controls_box.set_vexpand(False)
    threshold_row = Gtk.Box(spacing=12)
    threshold_row.set_valign(Gtk.Align.START)
    threshold_row.append(_build_dsp_control_label(self, "Threshold"))
    self.dsp_limiter_threshold_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
    _configure_dsp_scale(self.dsp_limiter_threshold_scale)
    self.dsp_limiter_threshold_scale.set_hexpand(True)
    self.dsp_limiter_threshold_scale.set_valign(Gtk.Align.CENTER)
    self.dsp_limiter_threshold_scale.set_value(float(self.settings.get("dsp_limiter_threshold", _DSP_LIMITER_THRESHOLD_DEFAULT)))
    self.dsp_limiter_threshold_scale.connect("value-changed", self._on_dsp_limiter_threshold_changed)
    threshold_row.append(self.dsp_limiter_threshold_scale)
    controls_box.append(threshold_row)
    ratio_row = Gtk.Box(spacing=12)
    ratio_row.set_valign(Gtk.Align.START)
    ratio_row.append(_build_dsp_control_label(self, "Ratio"))
    self.dsp_limiter_ratio_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 60, 1)
    _configure_dsp_scale(self.dsp_limiter_ratio_scale)
    self.dsp_limiter_ratio_scale.set_hexpand(True)
    self.dsp_limiter_ratio_scale.set_valign(Gtk.Align.CENTER)
    self.dsp_limiter_ratio_scale.set_value(float(self.settings.get("dsp_limiter_ratio", _DSP_LIMITER_RATIO_DEFAULT)))
    self.dsp_limiter_ratio_scale.connect("value-changed", self._on_dsp_limiter_ratio_changed)
    ratio_row.append(self.dsp_limiter_ratio_scale)
    controls_box.append(ratio_row)
    limiter_page.append(controls_box)
    limiter_page.append(
        Gtk.Label(
            label="Lower threshold catches peaks earlier. Higher ratio makes the ceiling behave more like a hard limiter.",
            xalign=0,
            wrap=True,
            css_classes=["caption"],
        )
    )
    detail_stack.add_titled(_build_dsp_detail_page(limiter_page), "limiter", "Limiter")

    resampler_page = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=10,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
        valign=Gtk.Align.START,
        css_classes=["dsp-detail-card"],
    )
    resampler_page.set_vexpand(False)
    resampler_title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    resampler_title_box.append(Gtk.Label(label="Resampler", xalign=0, css_classes=["title-4"]))
    resampler_title_box.append(
        Gtk.Label(
            label="Upsample or downsample the output to a fixed rate using a high-quality sinc resampler.",
            xalign=0,
            wrap=True,
            css_classes=["dim-label"],
        )
    )
    resampler_page.append(resampler_title_box)
    self.dsp_resampler_status_label = Gtk.Label(
        label="Resampler bypassed",
        xalign=0,
        wrap=True,
        css_classes=["dim-label"],
    )
    resampler_page.append(self.dsp_resampler_status_label)
    rate_row = Gtk.Box(spacing=12)
    rate_row.set_valign(Gtk.Align.CENTER)
    rate_row.set_halign(Gtk.Align.FILL)
    rate_row.append(_build_dsp_control_label(self, "Target rate"))
    rate_strings = Gtk.StringList.new([_DSP_RESAMPLER_RATE_LABELS[r] for r in _DSP_RESAMPLER_RATES])
    self.dsp_resampler_rate_dropdown = Gtk.DropDown.new(rate_strings, None)
    self.dsp_resampler_rate_dropdown.add_css_class("dsp-preset-dd")
    self.dsp_resampler_rate_dropdown.set_hexpand(True)
    saved_rate = int(self.settings.get("dsp_resampler_target_rate", 0) or 0)
    saved_rate_idx = _DSP_RESAMPLER_RATES.index(saved_rate) if saved_rate in _DSP_RESAMPLER_RATES else 0
    self.dsp_resampler_rate_dropdown.set_selected(saved_rate_idx)
    self.dsp_resampler_rate_dropdown.connect("notify::selected", self._on_dsp_resampler_rate_changed)
    rate_row.append(self.dsp_resampler_rate_dropdown)
    resampler_page.append(rate_row)
    quality_row = Gtk.Box(spacing=12)
    quality_row.set_valign(Gtk.Align.CENTER)
    quality_row.set_halign(Gtk.Align.FILL)
    quality_row.append(_build_dsp_control_label(self, "Quality"))
    quality_strings = Gtk.StringList.new([_DSP_RESAMPLER_QUALITY_LABELS[q] for q in _DSP_RESAMPLER_QUALITY_LEVELS])
    self.dsp_resampler_quality_dropdown = Gtk.DropDown.new(quality_strings, None)
    self.dsp_resampler_quality_dropdown.add_css_class("dsp-preset-dd")
    self.dsp_resampler_quality_dropdown.set_hexpand(True)
    saved_quality = int(self.settings.get("dsp_resampler_quality", 10) or 10)
    saved_quality_idx = _DSP_RESAMPLER_QUALITY_LEVELS.index(saved_quality) if saved_quality in _DSP_RESAMPLER_QUALITY_LEVELS else len(_DSP_RESAMPLER_QUALITY_LEVELS) - 1
    self.dsp_resampler_quality_dropdown.set_selected(saved_quality_idx)
    self.dsp_resampler_quality_dropdown.connect("notify::selected", self._on_dsp_resampler_quality_changed)
    quality_row.append(self.dsp_resampler_quality_dropdown)
    resampler_page.append(quality_row)
    resampler_page.append(
        Gtk.Label(
            label="Passthrough leaves the sample rate unchanged. Higher quality uses more CPU but produces cleaner output.",
            xalign=0,
            wrap=True,
            css_classes=["caption"],
        )
    )
    detail_stack.add_titled(_build_dsp_detail_page(resampler_page), "resampler", "Resampler")
    effects_page.attach(detail_stack, 1, 0, 2, 1)
    self.dsp_workspace_stack.add_titled(effects_page, "effects", "Effects & Config")
    self.dsp_workspace_stack.set_visible_child_name("overview")

    self._show_dsp_module(getattr(self, "_dsp_selected_module", "peq"), select_row=True)
    self._sync_dsp_preset_dropdown()
    self._update_dsp_ui_state()
    self._lv2_rebuild_sidebar_rows()
    return root


def _reset_search_focus_after_layout_change(self, duration_ms=260):
    try:
        now_us = GLib.get_monotonic_time()
    except Exception:
        now_us = 0
    self._search_focus_suppressed_until_us = int(now_us) + (int(duration_ms) * 1000)

    pop = getattr(self, "search_suggest_popover", None)
    if pop is not None:
        try:
            pop.popdown()
        except Exception:
            pass

    def _clear():
        win = getattr(self, "win", None)
        if win is not None:
            try:
                win.set_focus(None)
            except Exception:
                pass
        return False

    _clear()
    GLib.idle_add(_clear)
    GLib.timeout_add(max(60, int(duration_ms // 2)), _clear)
    GLib.timeout_add(int(duration_ms), _clear)


def _build_volume_popover(self, scale_attr="vol_scale"):
    pop = Gtk.Popover()
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)

    scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 100, 5)
    scale.set_inverted(True)
    scale.set_size_request(-1, 150)
    try:
        scale.set_value(float(self.settings.get("volume", 80)))
    except Exception:
        scale.set_value(80)
    scale.connect("value-changed", self.on_volume_changed_ui)
    setattr(self, scale_attr, scale)

    vbox.append(scale)
    pop.set_child(vbox)
    return pop


def on_key_pressed(self, controller, keyval, keycode, state):
    if keyval == Gdk.KEY_space:
        if not self.search_entry.has_focus():
            self.on_play_pause(self.play_btn)
            return True

    if (state & Gdk.ModifierType.CONTROL_MASK) and keyval == Gdk.KEY_Right:
        self.on_next_track()
        return True

    if (state & Gdk.ModifierType.CONTROL_MASK) and keyval == Gdk.KEY_Left:
        self.on_prev_track()
        return True

    if (state & Gdk.ModifierType.CONTROL_MASK) and keyval == Gdk.KEY_f:
        self.search_entry.grab_focus()
        return True

    if keyval == Gdk.KEY_q or keyval == Gdk.KEY_Q:
        queue_open = bool(
            getattr(self, "queue_revealer", None) is not None
            and self.queue_revealer.get_reveal_child()
        )
        if queue_open or not self.search_entry.has_focus():
            self.toggle_queue_drawer()
            return True

    if keyval == Gdk.KEY_w or keyval == Gdk.KEY_W:
        now_playing_open = bool(
            getattr(self, "now_playing_revealer", None) is not None
            and self.now_playing_revealer.get_reveal_child()
        )
        if now_playing_open or not self.search_entry.has_focus():
            self.toggle_now_playing_overlay()
            return True

    if keyval == Gdk.KEY_Escape:
        if getattr(self, "now_playing_revealer", None) is not None and self.now_playing_revealer.get_reveal_child():
            self.hide_now_playing_overlay()
            return True
        if getattr(self, "queue_revealer", None) is not None and self.queue_revealer.get_reveal_child():
            self.close_queue_drawer()
            return True

    if keyval == Gdk.KEY_Tab and not self.search_entry.has_focus():
        self.toggle_visualizer(self.viz_btn)
        return True

    return False


def toggle_mini_mode(self, btn):
    if not hasattr(self, "is_mini_mode"):
        self.is_mini_mode = False
    if not hasattr(self, "saved_width"):
        self.saved_width = ui_config.WINDOW_WIDTH
    if not hasattr(self, "saved_height"):
        self.saved_height = ui_config.WINDOW_HEIGHT

    if self.viz_revealer is not None:
        self._set_visualizer_expanded(False)
        self.settings["viz_expanded"] = False
        self.schedule_save_settings()
    if hasattr(self, "hide_now_playing_overlay"):
        self.hide_now_playing_overlay()
    self.close_queue_drawer()
    _reset_search_focus_after_layout_change(self)

    self.is_mini_mode = not self.is_mini_mode

    if self.is_mini_mode:
        self.saved_width = self.win.get_width()
        self.saved_height = self.win.get_height()

        self.header.set_visible(False)
        self.paned.set_visible(False)

        self.bottom_bar.add_css_class("mini-state")
        self.mini_controls.set_visible(True)

        if self.timeline_box is not None: self.timeline_box.set_visible(False)
        if self.vol_box is not None: self.vol_box.set_visible(False)
        if self.tech_box is not None: self.tech_box.set_visible(False)
        if getattr(self, "player_left_panel", None) is not None:
            self.player_left_panel.set_size_request(-1, -1)
        if getattr(self, "player_right_panel", None) is not None:
            self.player_right_panel.set_size_request(-1, -1)
        if getattr(self, "info_area", None) is not None:
            self.info_area.set_size_request(-1, -1)
        if getattr(self, "player_text_box", None) is not None:
            self.player_text_box.set_size_request(-1, -1)
        if getattr(self, "art_img", None) is not None:
            self.art_img.set_size_request(56, 56)

        self.win.set_decorated(False)
        self.win.set_resizable(False)
        self.win.set_size_request(390, 85)
        self.win.set_default_size(390, 85)
    else:
        self.header.set_visible(True)
        self.paned.set_visible(True)
        self.mini_controls.set_visible(False)

        if self.timeline_box is not None: self.timeline_box.set_visible(True)
        if self.vol_box is not None: self.vol_box.set_visible(True)
        if self.tech_box is not None: self.tech_box.set_visible(True)
        panel_w = int(getattr(self, "player_side_panel_width", 340) or 340)
        if getattr(self, "player_left_panel", None) is not None:
            self.player_left_panel.set_size_request(panel_w, -1)
        if getattr(self, "player_right_panel", None) is not None:
            self.player_right_panel.set_size_request(panel_w, -1)
        if getattr(self, "info_area", None) is not None:
            self.info_area.set_size_request(panel_w, -1)
        if getattr(self, "player_text_box", None) is not None:
            self.player_text_box.set_size_request(240, -1)
        if getattr(self, "art_img", None) is not None:
            self.art_img.set_size_request(80, 80)

        self.bottom_bar.remove_css_class("mini-state")
        self.win.set_decorated(True)
        self.win.set_resizable(True)
        self.win.set_size_request(ui_config.WINDOW_WIDTH, ui_config.WINDOW_HEIGHT)
        self.win.set_default_size(self.saved_width, self.saved_height)
        # Use saved_width directly — win.get_width() still returns the mini size
        # at this point because the window resize is asynchronous.
        sidebar_px = int(max(120, self.saved_width * float(ui_config.SIDEBAR_RATIO)))
        self.paned.set_position(sidebar_px)
        _reset_search_focus_after_layout_change(self, duration_ms=320)


def _build_user_popover(self):
    pop = Gtk.Popover()
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
    btn = Gtk.Button(label="Logout", css_classes=["flat", "destructive-action"])
    btn.connect("clicked", self.on_logout_clicked)
    vbox.append(btn)
    pop.set_child(vbox)
    return pop


def _build_eq_popover(self, sliders_attr="sliders"):
    pop = Gtk.Popover()
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
    vbox.append(self._build_eq_editor_content(sliders_attr=sliders_attr, show_header=True))
    pop.set_child(vbox)
    return pop


def _lock_volume_controls(self, locked):
    target_volume = 100.0 if locked else float(getattr(self, "settings", {}).get("volume", 80) or 80)
    target_volume = max(0.0, min(100.0, target_volume))
    sync_fn = getattr(self, "_sync_volume_ui_state", None)
    if callable(sync_fn):
        sync_fn(value=target_volume)
    else:
        volume_syncing = bool(getattr(self, "_volume_ui_syncing", False))
        self._volume_ui_syncing = True
        try:
            for scale in (getattr(self, "vol_scale", None), getattr(self, "now_playing_vol_scale", None)):
                if scale is not None:
                    scale.set_value(target_volume)
        finally:
            self._volume_ui_syncing = volume_syncing

    player = getattr(self, "player", None)
    if player is not None and hasattr(player, "set_volume"):
        try:
            player.set_volume(1.0 if locked else (target_volume / 100.0))
        except Exception:
            logger.debug("volume lock sync failed", exc_info=True)

    for scale in (getattr(self, "vol_scale", None), getattr(self, "now_playing_vol_scale", None)):
        if scale is not None:
            scale.set_sensitive(not locked)

    for btn in (getattr(self, "vol_btn", None), getattr(self, "now_playing_vol_btn", None)):
        if btn is None:
            continue
        if locked:
            btn.set_sensitive(False)
            btn.set_tooltip_text("Volume locked in Bit-Perfect/Exclusive mode")
            btn.set_icon_name("hiresti-volume-high-symbolic")
        else:
            btn.set_sensitive(True)
            btn.set_tooltip_text("Adjust Volume")

    for pop in (getattr(self, "vol_pop", None), getattr(self, "now_playing_vol_pop", None)):
        if locked and pop is not None:
            pop.popdown()

    for btn in (
        getattr(self, "eq_btn", None),
        getattr(self, "now_playing_eq_btn", None),
        getattr(self, "dsp_btn", None),
        getattr(self, "now_playing_dsp_btn", None),
    ):
        if btn is None:
            continue
        btn.set_sensitive(not locked)
        if locked:
            btn.set_tooltip_text("DSP disabled in Bit-Perfect mode (Bypassed)")
        else:
            btn.set_tooltip_text("Open DSP Workspace")

    for pop in (getattr(self, "eq_pop", None), getattr(self, "now_playing_eq_pop", None)):
        if locked and pop is not None:
            pop.popdown()
    if hasattr(self, "_update_dsp_ui_state"):
        self._update_dsp_ui_state()


def _build_help_popover(self):
    pop = Gtk.Popover()
    pop.set_has_arrow(False)
    pop.add_css_class("shortcuts-surface")
    vbox = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=8,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
        css_classes=["shortcuts-popover"],
    )
    vbox.set_size_request(280, -1)

    title = Gtk.Label(label="Keyboard Shortcuts", css_classes=["shortcuts-title"], halign=Gtk.Align.START)
    vbox.append(title)
    subtitle = Gtk.Label(
        label="Fast controls for playback and navigation",
        xalign=0,
        wrap=True,
        css_classes=["shortcuts-subtitle"],
    )
    vbox.append(subtitle)

    shortcuts = [
        ("Space", "Play / Pause"),
        ("Ctrl + →", "Next Track"),
        ("Ctrl + ←", "Previous Track"),
        ("Ctrl + F", "Focus Search"),
        ("Q", "Toggle Queue Drawer"),
        ("W", "Toggle Now Playing"),
        ("Tab", "Toggle Lyrics & Viz")
    ]

    list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["shortcuts-list"])
    for key, action in shortcuts:
        row = Gtk.Box(spacing=12, css_classes=["shortcuts-row"])
        action_lbl = Gtk.Label(label=action, xalign=0, hexpand=True, css_classes=["shortcuts-action"])
        key_lbl = Gtk.Label(label=key, xalign=1, hexpand=False, css_classes=["shortcuts-keycap"])
        key_lbl.set_attributes(Pango.AttrList.from_string("font-features 'tnum=1'"))
        row.append(action_lbl)
        row.append(key_lbl)
        list_box.append(row)

    vbox.append(list_box)
    pop.set_child(vbox)
    return pop


def _build_dsp_lv2_help_popover(self):
    pop = Gtk.Popover()
    vbox = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=8,
        margin_top=10,
        margin_bottom=10,
        margin_start=12,
        margin_end=12,
    )
    vbox.set_size_request(300, -1)
    title = Gtk.Label(label="LV2 Plugin Compatibility", xalign=0, css_classes=["title-5"])
    body = Gtk.Label(
        label=(
            "Some LV2 plugins may not work correctly in this player.\n\n"
            "If a plugin causes problems, please remove it."
        ),
        xalign=0,
        wrap=True,
        css_classes=["dim-label"],
    )
    vbox.append(title)
    vbox.append(body)
    pop.set_child(vbox)
    return pop


def _lv2_save_slots(self):
    """Sync player.lv2_slots state into settings and schedule save."""
    player = getattr(self, "player", None)
    if player is None or not hasattr(player, "lv2_slots"):
        return
    slots_list = [
        {
            "slot_id": sid,
            "uri": info.get("uri", ""),
            "enabled": info.get("enabled", True),
            "port_values": _lv2_filter_persisted_port_values(info.get("port_values", {})),
        }
        for sid, info in player.lv2_slots.items()
    ]
    self.settings["dsp_lv2_slots"] = slots_list
    if hasattr(self, "schedule_save_settings"):
        self.schedule_save_settings()


def _lv2_is_host_managed_symbol(symbol):
    return str(symbol or "").strip().lower() in _LV2_HOST_MANAGED_PORT_SYMBOLS


def _lv2_filter_persisted_port_values(port_values):
    clean = {}
    for symbol, value in dict(port_values or {}).items():
        if _lv2_is_host_managed_symbol(symbol):
            continue
        clean[symbol] = value
    return clean


def _lv2_host_managed_port_value(symbol, enabled):
    normalized = str(symbol or "").strip().lower()
    if normalized == "bypass":
        return 0.0 if enabled else 1.0
    return 1.0 if enabled else 0.0


def _lv2_install_help_text():
    return _LV2_INSTALL_HELP_TEXT


def _lv2_restart_playback_for_graph_rebind(self, reason="unspecified"):
    player = getattr(self, "player", None)
    if player is None:
        logger.info("LV2 playback rebind skipped: reason=%s cause=no-player", reason)
        return False
    if bool(getattr(self, "_playback_rebind_inflight", False)):
        self._playback_rebind_pending = True
        logger.info("LV2 playback rebind coalesced: inflight=1 reason=%s", reason)
        return False
    try:
        uri = str(getattr(player, "_last_loaded_uri", "") or "").strip()
    except Exception:
        uri = ""
    if not uri:
        logger.info("LV2 playback rebind skipped: reason=%s cause=no-uri", reason)
        return False

    try:
        pos, dur = player.get_position()
    except Exception:
        pos = 0.0
        dur = 0.0
    try:
        was_playing = bool(player.is_playing())
    except Exception:
        was_playing = True

    seek_delay_ms = 700 if was_playing else 180
    now_s = GLib.get_monotonic_time() / 1_000_000.0
    self._playback_rebind_inflight = True
    self._playback_rebind_pending = False
    self._playback_rebind_hold_position_s = float(pos or 0.0)
    self._playback_rebind_hold_duration_s = float(dur or 0.0)
    self._playback_rebind_hold_until_s = now_s + (float(seek_delay_ms) / 1000.0) + 0.8
    restore_volume = max(0.0, min(1.0, float(getattr(self, "settings", {}).get("volume", 80) or 80) / 100.0))
    logger.info(
        "LV2 playback rebind start reason=%s pos=%.3f dur=%.3f was_playing=%s dsp_enabled=%s bit_perfect=%s lv2_slots=%s",
        reason,
        float(pos or 0.0),
        float(dur or 0.0),
        was_playing,
        bool(getattr(player, "dsp_enabled", False)),
        bool(getattr(self, "settings", {}).get("bit_perfect", False)),
        [
            (sid, bool((info or {}).get("enabled", True)))
            for sid, info in dict(getattr(player, "lv2_slots", {}) or {}).items()
        ],
    )

    def restart():
        try:
            if was_playing and hasattr(player, "set_volume"):
                player.set_volume(0.0)
            player.stop()
            player.load(uri)
            if was_playing:
                player.play()
            GLib.timeout_add(
                seek_delay_ms,
                lambda: _lv2_finish_playback_rebind(
                    self,
                    player,
                    float(pos or 0.0),
                    was_playing,
                    restore_volume,
                    reason,
                ),
            )
        except Exception:
            logger.debug("lv2 playback restart failed", exc_info=True)
            self._playback_rebind_inflight = False
            self._playback_rebind_hold_until_s = 0.0
            self._playback_rebind_hold_position_s = None
            self._playback_rebind_hold_duration_s = 0.0
            return False
        return False

    GLib.idle_add(restart)
    return True


def _lv2_finish_playback_rebind(self, player, pos, was_playing, restore_volume=0.8, reason="unspecified"):
    try:
        player.seek(float(pos or 0.0))
        if was_playing and hasattr(player, "set_volume"):
            GLib.timeout_add(180, lambda: (player.set_volume(float(restore_volume)), False)[1])
    except Exception:
        logger.debug("lv2 playback finish-rebind failed", exc_info=True)
    pending = bool(getattr(self, "_playback_rebind_pending", False))
    self._playback_rebind_inflight = False
    logger.info(
        "LV2 playback rebind finish reason=%s pos=%.3f was_playing=%s pending=%s dsp_enabled=%s bit_perfect=%s",
        reason,
        float(pos or 0.0),
        was_playing,
        pending,
        bool(getattr(player, "dsp_enabled", False)),
        bool(getattr(self, "settings", {}).get("bit_perfect", False)),
    )
    if pending:
        self._playback_rebind_pending = False
        GLib.idle_add(lambda: (_lv2_restart_playback_for_graph_rebind(self, reason="coalesced"), False)[1])
    return False


def _lv2_add_slot(self, uri):
    """Add a new LV2 plugin slot. Returns slot_id or None."""
    player = getattr(self, "player", None)
    if player is None or not hasattr(player, "lv2_add_slot"):
        return None
    normalized_uri = str(uri or "").strip()
    existing_slots = dict(getattr(player, "lv2_slots", {}) or {})
    logger.info(
        "LV2 add request uri=%s existing_slots=%s",
        normalized_uri,
        [(sid, str((info or {}).get("uri", "") or "")) for sid, info in existing_slots.items()],
    )
    for slot_id, info in existing_slots.items():
        if str((info or {}).get("uri", "") or "").strip() == normalized_uri:
            logger.info("LV2 add skipped: existing slot_id=%s uri=%s", slot_id, normalized_uri)
            return slot_id
    slot_id = player.lv2_add_slot(uri)
    if slot_id:
        logger.info(
            "LV2 add created slot_id=%s uri=%s slots_now=%s",
            slot_id,
            normalized_uri,
            [
                (sid, str((info or {}).get("uri", "") or ""))
                for sid, info in dict(getattr(player, "lv2_slots", {}) or {}).items()
            ],
        )
        # Ensure the plugin's "enabled" port starts at 1.0 (active).
        # Some plugins default the port to 0 (bypass), so we set it explicitly.
        self._lv2_sync_enabled_port(slot_id, True)
        order = list(getattr(self, "settings", {}).get("dsp_order", []))
        if slot_id not in order:
            order.append(slot_id)
        self._apply_dsp_order(order, save=False)
        self._lv2_save_slots()
        _lv2_restart_playback_for_graph_rebind(self)
    return slot_id


def _lv2_remove_slot(self, slot_id):
    """Remove an LV2 plugin slot."""
    player = getattr(self, "player", None)
    if player is None or not hasattr(player, "lv2_remove_slot"):
        return False
    ok = player.lv2_remove_slot(slot_id)
    if ok:
        order = [m for m in list(getattr(self, "settings", {}).get("dsp_order", [])) if m != slot_id]
        self._apply_dsp_order(order, save=False)
        self._lv2_save_slots()
        _lv2_restart_playback_for_graph_rebind(self)
    return ok


def _lv2_sync_enabled_port(self, slot_id, enabled):
    """Sync the plugin's lv2:toggled 'enabled' port value and widget to match slot state.

    When our slot-level switch is toggled, this keeps the plugin's own bypass
    control in lockstep so they never contradict each other.
    """
    meta = self._lv2_get_plugin_meta(slot_id)
    if not meta:
        return
    # Find the conventional bypass port: lv2:toggled with symbol "enabled".
    sym = next(
        (
            c["symbol"]
            for c in meta.get("controls", [])
            if c.get("toggled") and _lv2_is_host_managed_symbol(c.get("symbol"))
        ),
        None,
    )
    if sym is None:
        logger.info(
            "LV2 sync-enabled-port skipped: slot_id=%s enabled=%s reason=no-host-managed-control",
            slot_id,
            bool(enabled),
        )
        return
    value = _lv2_host_managed_port_value(sym, enabled)
    logger.info(
        "LV2 sync-enabled-port slot_id=%s enabled=%s symbol=%s value=%s",
        slot_id,
        bool(enabled),
        sym,
        value,
    )
    player = getattr(self, "player", None)
    if player and hasattr(player, "lv2_set_port_value"):
        player.lv2_set_port_value(slot_id, sym, value)
    # Update the parameter-page widget without firing another callback.
    scales = getattr(self, "dsp_lv2_slot_scales", {})
    widget = (scales.get(slot_id) or {}).get(sym)
    if isinstance(widget, Gtk.Switch):
        self._dsp_ui_syncing = True
        try:
            widget.set_active(bool(enabled))
        finally:
            self._dsp_ui_syncing = False


def _lv2_get_plugin_meta(self, slot_id):
    """Return cached plugin metadata dict for a slot, or None."""
    cache = getattr(self, "_lv2_plugin_cache", None)
    if cache is None:
        return None
    player = getattr(self, "player", None)
    slot_info = (getattr(player, "lv2_slots", {}) or {}).get(slot_id, {}) if player else {}
    uri = slot_info.get("uri", "")
    return cache.get(uri)


def _lv2_persistent_cache_file(self):
    path = str(getattr(self, "_lv2_plugin_cache_file", "") or "").strip()
    if path:
        return path
    cache_root = str(getattr(self, "_cache_root", "") or "").strip()
    if not cache_root:
        return ""
    return os.path.join(cache_root, "lv2_plugins.json")


def _lv2_persistent_scan_meta_file(self):
    path = _lv2_persistent_cache_file(self)
    if not path:
        return ""
    return f"{path}.meta"


def _lv2_update_browser_action_state(self):
    btn = getattr(self, "add_lv2_plugin_btn", None)
    if btn is None:
        return
    inflight = bool(getattr(self, "_lv2_scan_inflight", False))
    btn.set_sensitive(not inflight)
    btn.set_tooltip_text("Scanning installed LV2 plugins..." if inflight else "Browse installed LV2 plugins")


def _lv2_scan_search_roots():
    roots = []
    env_raw = str(os.environ.get("LV2_PATH", "") or "").strip()
    if env_raw:
        roots.extend([part.strip() for part in env_raw.split(os.pathsep) if part.strip()])
    roots.extend(_LV2_DEFAULT_SEARCH_DIRS)
    out = []
    seen = set()
    for raw in roots:
        path = os.path.abspath(os.path.expanduser(str(raw or "").strip()))
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _lv2_scan_source_signature():
    roots = _lv2_scan_search_roots()
    bundle_tokens = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if not entry.name.endswith(".lv2"):
                        continue
                    try:
                        stat = entry.stat(follow_symlinks=False)
                        token = f"{entry.path}|{int(getattr(stat, 'st_mtime_ns', 0) or 0)}"
                    except Exception:
                        token = entry.path
                    bundle_tokens.append(token)
        except Exception:
            logger.debug("lv2 source signature scan failed for root=%s", root, exc_info=True)
    bundle_tokens.sort()
    digest = hashlib.sha256("\n".join(bundle_tokens).encode("utf-8")).hexdigest()
    return {
        "version": 1,
        "roots": roots,
        "bundle_count": len(bundle_tokens),
        "digest": digest,
    }


def _lv2_load_persistent_scan_cache(self):
    path = _lv2_persistent_cache_file(self)
    if not path:
        return False
    meta_path = _lv2_persistent_scan_meta_file(self)
    meta = read_json(meta_path, default=None) if meta_path else None
    current_sig = _lv2_scan_source_signature()
    if not isinstance(meta, dict) or meta.get("digest") != current_sig.get("digest"):
        logger.info(
            "LV2 scan cache invalidated: path=%s reason=%s",
            path,
            "missing-meta" if not isinstance(meta, dict) else "source-changed",
        )
        return False
    raw = read_json(path, default=None)
    if not isinstance(raw, list):
        return False
    cache_map = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri", "") or "").strip()
        if not uri:
            continue
        cache_map[uri] = dict(item)
    if not cache_map:
        return False
    self._lv2_plugin_cache = cache_map
    logger.info("LV2 scan cache restored from disk: plugins=%d path=%s", len(cache_map), path)
    return True


def _lv2_store_persistent_scan_cache(self, cache_map):
    path = _lv2_persistent_cache_file(self)
    if not path:
        return
    try:
        payload = sorted(
            [dict(plugin) for plugin in dict(cache_map or {}).values() if isinstance(plugin, dict)],
            key=lambda item: str(item.get("name", "") or "").lower(),
        )
        write_json(path, payload, indent=2)
        meta_path = _lv2_persistent_scan_meta_file(self)
        if meta_path:
            write_json(meta_path, _lv2_scan_source_signature(), indent=2)
        logger.info("LV2 scan cache saved: plugins=%d path=%s", len(payload), path)
    except Exception:
        logger.debug("lv2 scan cache save failed", exc_info=True)


def _lv2_ensure_scan_cache(self):
    """Ensure an LV2 scan is scheduled; returns True if cache is already ready."""
    if getattr(self, "_lv2_plugin_cache", None) is not None:
        return True
    self._lv2_schedule_scan_cache(refresh_ui=False)
    return False


def _lv2_refresh_ui_after_scan(self):
    player = getattr(self, "player", None)
    slots = dict(getattr(player, "lv2_slots", {}) or {}) if player else {}
    slot_ids = list(slots.keys())
    stack = getattr(self, "dsp_module_stack", None)
    if stack is not None:
        for slot_id in slot_ids:
            child = stack.get_child_by_name(slot_id)
            if child is not None:
                stack.remove(child)
    scales = getattr(self, "dsp_lv2_slot_scales", None)
    if isinstance(scales, dict):
        for slot_id in slot_ids:
            scales.pop(slot_id, None)
    self._lv2_rebuild_sidebar_rows()
    if hasattr(self, "_rebuild_dsp_overview_chain"):
        self._rebuild_dsp_overview_chain()
    if hasattr(self, "_update_dsp_ui_state"):
        try:
            self._update_dsp_ui_state()
        except Exception:
            logger.debug("dsp ui state refresh after lv2 scan failed", exc_info=True)
    selected = str(getattr(self, "_dsp_selected_module", "") or "")
    if selected in slot_ids:
        # Defer via idle_add so any coalesced (pending) sidebar rebuild runs first
        # and adds the module page to the stack before we try to show it.
        # GLib idle callbacks are FIFO, so the rebuild idle (queued by the
        # coalesced guard) always fires before this one.
        GLib.idle_add(lambda: self._show_dsp_module(selected, select_row=True))


def _lv2_schedule_scan_cache(self, refresh_ui=False, on_ready=None, force=False):
    callbacks = getattr(self, "_lv2_scan_ready_callbacks", None)
    if callbacks is None:
        callbacks = []
        self._lv2_scan_ready_callbacks = callbacks
    if callable(on_ready):
        callbacks.append(on_ready)

    if force:
        self._lv2_plugin_cache = None
    cache = getattr(self, "_lv2_plugin_cache", None)
    if cache is not None:
        if refresh_ui:
            _lv2_refresh_ui_after_scan(self)
        ready_callbacks = list(getattr(self, "_lv2_scan_ready_callbacks", []) or [])
        self._lv2_scan_ready_callbacks = []
        for cb in ready_callbacks:
            try:
                cb()
            except Exception:
                logger.debug("lv2 scan ready callback failed", exc_info=True)
        return
    if not force and _lv2_load_persistent_scan_cache(self):
        if refresh_ui:
            _lv2_refresh_ui_after_scan(self)
        ready_callbacks = list(getattr(self, "_lv2_scan_ready_callbacks", []) or [])
        self._lv2_scan_ready_callbacks = []
        for cb in ready_callbacks:
            try:
                cb()
            except Exception:
                logger.debug("lv2 scan ready callback failed", exc_info=True)
        return

    if refresh_ui:
        self._lv2_scan_refresh_ui_pending = True
    if bool(getattr(self, "_lv2_scan_inflight", False)):
        return

    player = getattr(self, "player", None)
    if player is None or not hasattr(player, "lv2_scan_plugins"):
        self._lv2_plugin_cache = {}
        self._lv2_scan_inflight = False
        if bool(getattr(self, "_lv2_scan_refresh_ui_pending", False)):
            self._lv2_scan_refresh_ui_pending = False
            _lv2_refresh_ui_after_scan(self)
        ready_callbacks = list(getattr(self, "_lv2_scan_ready_callbacks", []) or [])
        self._lv2_scan_ready_callbacks = []
        for cb in ready_callbacks:
            try:
                cb()
            except Exception:
                logger.debug("lv2 scan ready callback failed", exc_info=True)
        return

    self._lv2_scan_inflight = True
    _lv2_update_browser_action_state(self)
    logger.info("LV2 scan scheduled")

    def task():
        try:
            plugins = player.lv2_scan_plugins()
            cache_map = {p["uri"]: p for p in (plugins or [])}
        except Exception:
            logger.debug("lv2 scan failed", exc_info=True)
            cache_map = {}

        def apply():
            self._lv2_plugin_cache = cache_map
            self._lv2_scan_inflight = False
            _lv2_update_browser_action_state(self)
            _lv2_store_persistent_scan_cache(self, cache_map)
            logger.info("LV2 scan complete: plugins=%d", len(cache_map))
            if bool(getattr(self, "_lv2_scan_refresh_ui_pending", False)):
                self._lv2_scan_refresh_ui_pending = False
                _lv2_refresh_ui_after_scan(self)
            ready_callbacks = list(getattr(self, "_lv2_scan_ready_callbacks", []) or [])
            self._lv2_scan_ready_callbacks = []
            for cb in ready_callbacks:
                try:
                    cb()
                except Exception:
                    logger.debug("lv2 scan ready callback failed", exc_info=True)
            return False

        GLib.idle_add(apply)

    submit_daemon(task)


def _lv2_build_slot_page(self, slot_id):
    """Build and register the detail page for an LV2 slot. No-op if page already exists."""
    stack = getattr(self, "dsp_module_stack", None)
    if stack is None:
        return
    # Already built?
    if stack.get_child_by_name(slot_id) is not None:
        return

    player = getattr(self, "player", None)
    slot_info = (getattr(player, "lv2_slots", {}) or {}).get(slot_id, {}) if player else {}
    meta = self._lv2_get_plugin_meta(slot_id)
    plugin_name = (meta or {}).get("name", slot_id)
    controls = (meta or {}).get("controls", [])
    port_values = slot_info.get("port_values", {})

    page = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=10,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
        valign=Gtk.Align.START,
        css_classes=["dsp-detail-card"],
    )
    page.set_vexpand(False)

    # Header
    title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
    title_box.append(Gtk.Label(label=plugin_name, xalign=0, css_classes=["title-4"]))
    uri = slot_info.get("uri", "")
    if uri:
        uri_label = Gtk.Label(label=uri, xalign=0, wrap=True, css_classes=["dim-label"])
        uri_label.set_selectable(True)
        title_box.append(uri_label)
    page.append(title_box)

    if controls:
        scales_dict = getattr(self, "dsp_lv2_slot_scales", None)
        if scales_dict is None:
            self.dsp_lv2_slot_scales = {}
            scales_dict = self.dsp_lv2_slot_scales
        if slot_id not in scales_dict:
            scales_dict[slot_id] = {}

        controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        rendered_controls = 0
        for ctrl in controls:
            symbol = ctrl.get("symbol", "")
            if _lv2_is_host_managed_symbol(symbol):
                continue
            name = ctrl.get("name", symbol)
            is_toggled = ctrl.get("toggled", False)
            is_integer = ctrl.get("integer", False)
            mn = float(ctrl.get("min", 0.0))
            mx = float(ctrl.get("max", 1.0))
            default = float(ctrl.get("default", mn))
            current = float(port_values.get(symbol, default))

            row = Gtk.Box(spacing=12)
            row.set_valign(Gtk.Align.CENTER)
            row.append(_build_dsp_control_label(self, name))

            if is_toggled:
                widget = Gtk.Switch()
                widget.set_valign(Gtk.Align.CENTER)
                widget.set_halign(Gtk.Align.END)
                widget.set_hexpand(True)
                widget.set_active(current != 0.0)
                widget.connect(
                    "notify::active",
                    lambda sw, _param, sid=slot_id, sym=symbol: self._on_lv2_port_scale_changed(
                        sid, sym, sw
                    ),
                )
            else:
                if mx <= mn:
                    mx = mn + 1.0
                if is_integer:
                    step = 1.0
                    digits = 0
                else:
                    step = (mx - mn) / 100.0
                    digits = 2
                current = max(mn, min(mx, current))
                widget = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, mn, mx, step)
                widget.set_digits(digits)
                widget.set_draw_value(True)
                widget.set_value_pos(Gtk.PositionType.RIGHT)
                widget.set_hexpand(True)
                widget.set_valign(Gtk.Align.CENTER)
                widget.set_value(current)
                widget.connect(
                    "value-changed",
                    lambda sc, sid=slot_id, sym=symbol: self._on_lv2_port_scale_changed(
                        sid, sym, sc
                    ),
                )

            row.append(widget)
            controls_box.append(row)
            scales_dict[slot_id][symbol] = widget
            rendered_controls += 1
        if rendered_controls > 0:
            page.append(controls_box)
        else:
            page.append(
                Gtk.Label(
                    label="No controllable parameters for this plugin.",
                    xalign=0,
                    wrap=True,
                    css_classes=["dim-label"],
                )
            )
    else:
        page.append(
            Gtk.Label(
                label="No controllable parameters for this plugin.",
                xalign=0,
                wrap=True,
                css_classes=["dim-label"],
            )
        )

    stack.add_titled(_build_dsp_detail_page(page), slot_id, plugin_name)
    if hasattr(self, "_update_dsp_ui_state"):
        try:
            self._update_dsp_ui_state()
        except Exception:
            logger.debug("dsp ui state refresh after lv2 page build failed", exc_info=True)


def _on_lv2_port_scale_changed(self, slot_id, symbol, widget):
    if getattr(self, "_dsp_ui_syncing", False):
        return
    if _lv2_is_host_managed_symbol(symbol):
        return
    if isinstance(widget, Gtk.Switch):
        value = 1.0 if widget.get_active() else 0.0
    else:
        value = float(widget.get_value())
    player = getattr(self, "player", None)
    if player and hasattr(player, "lv2_set_port_value"):
        player.lv2_set_port_value(slot_id, symbol, value)
    self._lv2_save_slots()


def _lv2_rebuild_sidebar_rows(self):
    """Add/remove LV2 sidebar rows to match current player.lv2_slots."""
    lv2_list = getattr(self, "dsp_lv2_module_list", None)
    if lv2_list is None:
        return
    if bool(getattr(self, "_lv2_sidebar_rebuild_inflight", False)):
        self._lv2_sidebar_rebuild_pending = True
        logger.info("LV2 sidebar rebuild coalesced: inflight=1")
        return
    self._lv2_sidebar_rebuild_inflight = True
    self._lv2_sidebar_rebuild_pending = False
    logger.info(
        "LV2 sidebar rebuild start listbox_id=%s existing_rows=%s",
        hex(id(lv2_list)),
        _listbox_debug_rows(lv2_list),
    )
    try:
        # Remove all existing rows
        while True:
            child = lv2_list.get_first_child()
            if child is None:
                break
            lv2_list.remove(child)
        logger.info(
            "LV2 sidebar rebuild cleared listbox_id=%s rows=%s",
            hex(id(lv2_list)),
            _listbox_debug_rows(lv2_list),
        )

        player = getattr(self, "player", None)
        slots = dict(getattr(player, "lv2_slots", {}) or {}) if player else {}
        self.dsp_lv2_slot_rows = {}
        logger.info(
            "LV2 sidebar rebuild slots=%s",
            [(sid, str((info or {}).get("uri", "") or "")) for sid, info in slots.items()],
        )

        if not slots:
            lv2_list.set_visible(False)
            return

        if getattr(self, "_lv2_plugin_cache", None) is None:
            self._lv2_schedule_scan_cache(refresh_ui=True)

        lv2_list.set_visible(True)
        for slot_id, info in slots.items():
            meta = self._lv2_get_plugin_meta(slot_id)
            plugin_name = (meta or {}).get("name", slot_id)
            row = Gtk.ListBoxRow()
            row.dsp_module_id = slot_id
            row.set_activatable(True)
            row.set_margin_top(4)
            row.set_margin_bottom(4)
            box = Gtk.Box(spacing=8, margin_top=8, margin_bottom=8, margin_start=12, margin_end=8, valign=Gtk.Align.CENTER)
            name_label = Gtk.Label(label=plugin_name, xalign=0, hexpand=True, ellipsize=3)  # PANGO_ELLIPSIZE_END=3
            name_label.set_max_width_chars(18)
            name_label.add_css_class("settings-label")
            box.append(name_label)
            switch = Gtk.Switch(valign=Gtk.Align.CENTER)
            switch.set_active(bool(info.get("enabled", True)))
            switch.connect("state-set", lambda sw, state, sid=slot_id: self._on_lv2_slot_toggled(sid, sw, state))
            box.append(switch)
            remove_btn = Gtk.Button(icon_name="list-remove-symbolic", css_classes=["flat", "circular"], valign=Gtk.Align.CENTER)
            remove_btn.connect("clicked", lambda _b, sid=slot_id: self._on_lv2_slot_remove(sid))
            box.append(remove_btn)
            select_click = Gtk.GestureClick()
            select_click.set_button(Gdk.BUTTON_PRIMARY)
            select_click.connect(
                "released",
                lambda _gesture, _n, _x, _y, sid=slot_id: self._show_dsp_module(sid, select_row=True),
            )
            box.add_controller(select_click)
            row.set_child(box)
            lv2_list.append(row)
            self.dsp_lv2_slot_rows[slot_id] = {
                "row": row,
                "switch": switch,
                "remove_btn": remove_btn,
            }
            logger.info(
                "LV2 sidebar append listbox_id=%s row_id=%s slot_id=%s plugin_name=%s uri=%s",
                hex(id(lv2_list)),
                hex(id(row)),
                slot_id,
                plugin_name,
                str((info or {}).get("uri", "") or ""),
            )
            # Build detail page if not yet built
            self._lv2_build_slot_page(slot_id)
        logger.info(
            "LV2 sidebar rebuild finish listbox_id=%s rows=%s",
            hex(id(lv2_list)),
            _listbox_debug_rows(lv2_list),
        )
    finally:
        pending = bool(getattr(self, "_lv2_sidebar_rebuild_pending", False))
        self._lv2_sidebar_rebuild_inflight = False
        if pending:
            self._lv2_sidebar_rebuild_pending = False
            GLib.idle_add(lambda: (_lv2_rebuild_sidebar_rows(self), False)[1])


def _on_lv2_slot_toggled(self, slot_id, switch, state):
    if getattr(self, "_dsp_ui_syncing", False):
        return True
    logger.info("LV2 toggle request slot_id=%s state=%s", slot_id, bool(state))
    player = getattr(self, "player", None)
    if player and hasattr(player, "lv2_set_slot_enabled"):
        ok = player.lv2_set_slot_enabled(slot_id, bool(state))
        if not ok:
            logger.warning("LV2 toggle failed slot_id=%s state=%s", slot_id, bool(state))
            self._dsp_ui_syncing = True
            try:
                switch.set_active(not state)
            finally:
                self._dsp_ui_syncing = False
            return True
        # Keep the plugin's own "enabled" port in sync with the slot switch.
        self._lv2_sync_enabled_port(slot_id, bool(state))
        logger.info("LV2 toggle applied slot_id=%s state=%s", slot_id, bool(state))
    self._lv2_save_slots()
    if hasattr(self, "_update_dsp_ui_state"):
        try:
            self._update_dsp_ui_state()
        except Exception:
            logger.debug("dsp ui state refresh after lv2 toggle failed", exc_info=True)
    _lv2_restart_playback_for_graph_rebind(self)
    return False


def _on_lv2_slot_remove(self, slot_id):
    # Remove the detail page if present
    stack = getattr(self, "dsp_module_stack", None)
    if stack is not None:
        child_page = stack.get_child_by_name(slot_id)
        if child_page is not None:
            stack.remove(child_page)
    # Remove scale dict entry
    scales = getattr(self, "dsp_lv2_slot_scales", {})
    scales.pop(slot_id, None)
    self._lv2_remove_slot(slot_id)
    self._lv2_rebuild_sidebar_rows()
    self._show_dsp_module("peq", select_row=True)


def _present_lv2_plugin_browser(self, plugins):
    win = getattr(self, "win", None)
    dialog = Gtk.Dialog(title="Add LV2 Plugin", transient_for=win, modal=True)
    dialog.set_default_size(520, 480)

    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=8,
        margin_top=8,
        margin_bottom=8,
        margin_start=12,
        margin_end=12,
    )

    help_row = Gtk.Box(spacing=8)
    help_label = Gtk.Label(
        label="This list shows installed LV2 plugins. Install packages first if you need more plugins.",
        xalign=0,
        wrap=True,
        hexpand=True,
        css_classes=["dim-label"],
    )
    help_row.append(help_label)
    help_btn = Gtk.Button(label="Install Help", css_classes=["flat"])
    help_btn.connect(
        "clicked",
        lambda _b: self._show_simple_dialog("LV2 Install Help", _lv2_install_help_text()),
    )
    help_row.append(help_btn)
    root.append(help_row)

    search_entry = Gtk.SearchEntry(placeholder_text="Search plugins\u2026")
    root.append(search_entry)

    scroll = Gtk.ScrolledWindow(vexpand=True)
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    plugin_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["boxed-list"])
    plugin_list.set_filter_func(
        lambda row: search_entry.get_text().lower() in (getattr(row, "_plugin_search_str", ""))
    )
    scroll.set_child(plugin_list)

    if not plugins:
        plugin_list.append(
            Gtk.Label(
                label=(
                    "No LV2 plugins found.\n\n"
                    "Use Install Help for Fedora package examples, then reopen this dialog."
                ),
                wrap=True,
                margin_top=12,
                margin_bottom=12,
                margin_start=8,
                margin_end=8,
            )
        )
    else:
        for p in plugins:
            row = Gtk.ListBoxRow()
            row._plugin_uri = p.get("uri", "")
            row._plugin_search_str = (p.get("name", "") + " " + row._plugin_uri).lower()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
            box.append(Gtk.Label(label=p.get("name", row._plugin_uri), xalign=0))
            box.append(Gtk.Label(label=row._plugin_uri, xalign=0, css_classes=["dim-label", "caption"]))
            row.set_child(box)
            plugin_list.append(row)

    search_entry.connect("search-changed", lambda _e: plugin_list.invalidate_filter())
    root.append(scroll)

    btn_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    cancel_btn = Gtk.Button(label="Cancel")
    cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
    btn_row.append(cancel_btn)
    add_btn = Gtk.Button(label="Add", css_classes=["suggested-action"])
    add_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
    btn_row.append(add_btn)
    root.append(btn_row)

    dialog.set_child(root)
    dialog.connect("response", lambda d, resp: self._on_lv2_plugin_browser_response(d, resp, plugin_list))
    dialog.present()


def _open_lv2_plugin_browser(self, _btn=None, force_refresh=False):
    """Open a plugin browser dialog."""
    if bool(getattr(self, "_lv2_scan_inflight", False)):
        if not bool(getattr(self, "_lv2_browser_open_pending", False)):
            self._lv2_browser_open_pending = True
            self._lv2_schedule_scan_cache(
                refresh_ui=True,
                on_ready=lambda: self._open_lv2_plugin_browser(force_refresh=False),
                force=bool(force_refresh),
            )
        if hasattr(self, "show_output_notice"):
            self.show_output_notice("Scanning LV2 plugins...", "info", 2200)
        return

    if force_refresh:
        self._lv2_browser_open_pending = True
        self._lv2_schedule_scan_cache(
            refresh_ui=True,
            on_ready=lambda: self._open_lv2_plugin_browser(force_refresh=False),
            force=True,
        )
        if hasattr(self, "show_output_notice"):
            self.show_output_notice("Scanning LV2 plugins...", "info", 2200)
        return

    cache = getattr(self, "_lv2_plugin_cache", None)
    if cache is None:
        self._lv2_browser_open_pending = True
        self._lv2_schedule_scan_cache(
            refresh_ui=True,
            on_ready=lambda: self._open_lv2_plugin_browser(force_refresh=False),
        )
        if hasattr(self, "show_output_notice"):
            self.show_output_notice("Scanning LV2 plugins...", "info", 2200)
        return
    self._lv2_browser_open_pending = False
    cache = cache or {}
    plugins = sorted(cache.values(), key=lambda p: p.get("name", "").lower())
    self._present_lv2_plugin_browser(plugins)


def _on_lv2_plugin_browser_response(self, dialog, response, plugin_list):
    dialog.destroy()
    if response != Gtk.ResponseType.OK:
        return
    selected_row = plugin_list.get_selected_row()
    if selected_row is None:
        return
    uri = getattr(selected_row, "_plugin_uri", "")
    if not uri:
        return
    player = getattr(self, "player", None)
    existing_slot_id = None
    existing_slots = dict(getattr(player, "lv2_slots", {}) or {}) if player else {}
    for slot_id, info in existing_slots.items():
        if str((info or {}).get("uri", "") or "").strip() == str(uri or "").strip():
            existing_slot_id = slot_id
            break
    logger.info(
        "LV2 browser response uri=%s existing_slot_id=%s existing_slots=%s",
        str(uri or ""),
        existing_slot_id,
        [
            (sid, str((info or {}).get("uri", "") or ""))
            for sid, info in existing_slots.items()
        ],
    )
    slot_id = self._lv2_add_slot(uri)
    if slot_id:
        self._lv2_rebuild_sidebar_rows()
        self._show_dsp_module(slot_id, select_row=True)
        if hasattr(self, "show_output_notice"):
            meta = self._lv2_get_plugin_meta(slot_id)
            name = (meta or {}).get("name", slot_id)
            if existing_slot_id is not None:
                self.show_output_notice(f"LV2 already added: {name}", "info", 2200)
            else:
                self.show_output_notice(f"Added LV2: {name}", "ok", 2500)
    else:
        if hasattr(self, "show_output_notice"):
            self.show_output_notice("Failed to load LV2 plugin", "error", 3000)


def _show_simple_dialog(self, title, message):
    dialog = Gtk.Dialog(title=title, transient_for=self.win, modal=True)
    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
    )
    root.append(Gtk.Label(label=str(message or ""), xalign=0, wrap=True))
    action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    ok_btn = Gtk.Button(label="OK")
    ok_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
    action_row.append(ok_btn)
    root.append(action_row)
    dialog.set_child(root)
    dialog.connect("response", lambda d, _resp: d.destroy())
    dialog.present()
