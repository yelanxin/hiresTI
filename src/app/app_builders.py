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


def _configure_dsp_scale(scale, digits=0, value_pos=Gtk.PositionType.RIGHT):
    scale.set_digits(int(digits))
    scale.set_draw_value(True)
    scale.set_value_pos(value_pos)
    return scale


def _build_dsp_scroll_area(child, min_height=_DSP_WORKSPACE_MIN_HEIGHT, max_height=_DSP_WORKSPACE_MAX_HEIGHT):
    scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll.set_propagate_natural_height(True)
    scroll.set_propagate_natural_width(False)
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
    return bool(module_id in _DSP_REORDERABLE_MODULE_IDS)


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
    return module_id.title()


def _volume_icon_name(percent, hardware=False):
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
        "DSP show module request module_id=%s select_row=%s rows=%s",
        module_id,
        bool(select_row),
        _listbox_debug_rows(getattr(self, "dsp_module_list", None)),
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
    if primary_list is None:
        return
    target_row = None
    row = primary_list.get_first_child()
    while row is not None:
        if getattr(row, "dsp_module_id", None) == module_id:
            target_row = row
            break
        row = row.get_next_sibling()
    if target_row is None:
        return
    primary_list.select_row(target_row)


def _on_dsp_module_selected(self, _listbox, row):
    if row is None:
        return
    module_id = getattr(row, "dsp_module_id", "peq")
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
        "DSP master toggle request state=%s current_dsp_enabled=%s bit_perfect=%s",
        state,
        bool(getattr(player, "dsp_enabled", False)),
        bool(getattr(self, "settings", {}).get("bit_perfect", False)),
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
            "Drag PEQ / Convolution / Tape / Tube / Stereo Widener to reorder them, then save once to rebuild the chain."
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

    # --- DSP Presets card ---
    preset_card = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=10,
        margin_top=0,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
        css_classes=["dsp-detail-card", "dsp-chain-card"],
    )
    preset_title_row = Gtk.Box(spacing=12)
    preset_title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
    preset_title_box.append(Gtk.Label(label="DSP Presets", xalign=0, css_classes=["title-4"]))
    preset_title_box.append(
        Gtk.Label(
            label="Save and restore complete DSP chain configurations",
            xalign=0,
            wrap=True,
            css_classes=["dim-label"],
        )
    )
    preset_title_row.append(preset_title_box)
    preset_card.append(preset_title_row)

    preset_controls_row = Gtk.Box(spacing=8, margin_top=4)
    self.dsp_preset_dd = Gtk.DropDown(model=Gtk.StringList.new(["(no presets)"]))
    self.dsp_preset_dd.set_sensitive(False)
    self.dsp_preset_dd.set_hexpand(True)
    preset_controls_row.append(self.dsp_preset_dd)
    self.dsp_preset_load_btn = Gtk.Button(label="Load", css_classes=["flat"])
    self.dsp_preset_load_btn.set_sensitive(False)
    self.dsp_preset_load_btn.connect("clicked", self.on_dsp_preset_load_clicked)
    preset_controls_row.append(self.dsp_preset_load_btn)
    self.dsp_preset_save_btn = Gtk.Button(label="Save As…", css_classes=["flat"])
    self.dsp_preset_save_btn.connect("clicked", self.on_dsp_preset_save_clicked)
    preset_controls_row.append(self.dsp_preset_save_btn)
    self.dsp_preset_delete_btn = Gtk.Button(label="Delete", css_classes=["flat", "destructive-action"])
    self.dsp_preset_delete_btn.set_sensitive(False)
    self.dsp_preset_delete_btn.connect("clicked", self.on_dsp_preset_delete_clicked)
    preset_controls_row.append(self.dsp_preset_delete_btn)
    preset_card.append(preset_controls_row)
    overview_page.append(preset_card)
    if hasattr(self, "refresh_dsp_preset_list"):
        self.refresh_dsp_preset_list()

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


def _on_hw_volume_ready(self):
    """Refresh the volume UI when hardware-volume capability becomes available."""
    self._hw_vol_ch_initial_synced = False
    _rebuild_hw_volume_ch_sliders(self)

    player = getattr(self, "player", None)
    if player is not None and _hw_volume_main_slider_controls_master(player):
        # Read the DAC's actual current volume instead of using the saved
        # settings value — avoids showing 100% when the DAC is actually lower.
        actual_percent = None
        try:
            raw = player.usb_hw_volume_get()
            if raw is not None:
                actual_percent = player.usb_hw_volume_raw_to_percent(raw)
        except Exception:
            pass
        sync_fn = getattr(self, "_sync_volume_ui_state", None)
        if callable(sync_fn):
            if actual_percent is not None:
                actual_percent = max(0.0, min(100.0, float(actual_percent)))
                settings = getattr(self, "settings", None)
                if isinstance(settings, dict):
                    settings["volume"] = int(round(actual_percent))
                sync_fn(value=actual_percent)
            else:
                sync_fn()

    # Sync per-channel slider positions + dB labels now that sliders exist.
    # The per-channel volume events may have arrived before the sliders were
    # built, so we need to explicitly sync here.
    _sync_hw_volume_ch_slider_positions(self)
    self._hw_vol_ch_initial_synced = True

    if not bool(getattr(self, "settings", {}).get("bit_perfect", False)):
        _update_volume_device_label(self)
        return False
    # In bit-perfect mode with hardware volume (e.g. USB Rawlink v2),
    # unlock volume controls — hw volume doesn't touch PCM data.
    # At startup the controls were locked because the USB device wasn't
    # claimed yet; now that hw volume is confirmed, unlock them.
    if player is not None and hasattr(player, "usb_hw_volume_supported") and player.usb_hw_volume_supported():
        _lock_volume_controls(self, False)
        _update_volume_device_label(self)
        return False
    _lock_volume_controls(self, True)
    _update_volume_device_label(self)
    return False  # remove idle source


def _on_hw_volume_changed(self, raw_value, uac_ch=None):
    """Sync UI/settings when the DAC reports a new hardware volume value."""
    player = getattr(self, "player", None)
    if player is None or not hasattr(player, "usb_hw_volume_raw_to_percent"):
        return False
    try:
        percent = player.usb_hw_volume_raw_to_percent(raw_value)
    except Exception:
        logger.debug("hw volume feedback conversion failed", exc_info=True)
        return False
    if percent is None:
        return False
    percent = max(0.0, min(100.0, float(percent)))
    logger.info(
        "Hardware volume actual ch=%s raw=%s db=%+.2f percent=%.2f",
        uac_ch, raw_value,
        float(raw_value) / 256.0,
        percent,
    )
    # On first event, sync all channel sliders (they were at default until now)
    if not getattr(self, "_hw_vol_ch_initial_synced", False):
        self._hw_vol_ch_initial_synced = True
        _sync_hw_volume_ch_slider_positions(self)
    # Update per-channel slider and dB label if present
    if uac_ch is not None:
        scales = getattr(self, "_hw_vol_ch_scales_all", {}).get(uac_ch, [])
        if scales:
            try:
                self._hw_vol_ch_programmatic = True
                for scale in scales:
                    scale.set_value(percent)
            finally:
                self._hw_vol_ch_programmatic = False
        db_val = float(raw_value) / 256.0
        text = f"{db_val:+.1f} dB"
        for lbl in getattr(self, "_hw_vol_ch_db_labels_all", {}).get(uac_ch, []):
            lbl.set_text(text)
    # For the main volume slider, use master (ch0) or any channel
    is_master = uac_ch is None or (
        _hw_volume_main_slider_controls_master(player) and uac_ch == 0
    )
    if is_master:
        settings = getattr(self, "settings", None)
        if isinstance(settings, dict):
            settings["volume"] = int(round(percent))
        save_fn = getattr(self, "schedule_save_settings", None)
        if callable(save_fn):
            save_fn()
        sync_fn = getattr(self, "_sync_volume_ui_state", None)
        if callable(sync_fn):
            sync_fn(value=percent)
        if hasattr(self, "_update_volume_db_label"):
            self._update_volume_db_label(percent)
        if hasattr(self, "_mpris_sync_volume"):
            self._mpris_sync_volume()
    _update_volume_device_label(self)
    return False


def _update_volume_db_label(self, percent):
    """Update the dB label on volume popovers.  `percent` is 0-100 or None to clear."""
    player = getattr(self, "player", None)
    for attr in ("vol_db_label", "now_playing_vol_db_label"):
        label = getattr(self, attr, None)
        if label is None:
            continue
        if percent is None or player is None:
            label.set_text("")
            continue
        db = None
        if hasattr(player, "usb_hw_volume_percent_to_db"):
            try:
                db = player.usb_hw_volume_percent_to_db(percent)
            except Exception:
                pass
        if db is not None:
            label.set_text(f"{db:+.1f} dB")
        else:
            label.set_text("")


def _update_volume_device_label(self):
    """Pick the right popover content for the active driver / Bit-Perfect state.

    Three cases:

    1. USB Rawlink v2 with a UAC Feature Unit → "Hardware Volume" label
       above the slider, slider controls the DAC directly.
    2. Any other driver (ALSA / PipeWire / Auto) with Bit-Perfect *off* →
       "Software Volume" label, slider scales PCM via the Rust engine's
       VolumePcmProcessor. Previously this case was treated the same as
       case 3 (slider hidden, "Hardware volume not supported" shown),
       which silently broke software volume after the V2 transport
       gained per-slab gain.
    3. No hardware volume *and* Bit-Perfect on → no usable volume path:
       hide the slider and show the "Hardware volume not supported"
       placeholder so the user isn't fiddling with a slider that has
       no audible effect.
    """
    player = getattr(self, "player", None)
    hw_vol = (
        player is not None
        and hasattr(player, "usb_hw_volume_supported")
        and player.usb_hw_volume_supported()
    )
    bit_perfect = bool(getattr(self, "settings", {}).get("bit_perfect", False))
    software_vol = (not hw_vol) and (not bit_perfect)
    device_name = str(getattr(self, "current_device_name", "") or "").strip()
    for prefix in ("", "now_playing_"):
        device_label = getattr(self, f"{prefix}vol_device_label", None)
        unsupported_label = getattr(self, f"{prefix}vol_unsupported_label", None)
        scale = getattr(self, f"{prefix}vol_scale", None)
        db_label = getattr(self, f"{prefix}vol_db_label", None)
        ch_box = getattr(self, f"{prefix}vol_ch_box", None)
        if hw_vol:
            if device_label is not None:
                device_label.set_text(
                    f"Hardware Volume\n{device_name}" if device_name else "Hardware Volume"
                )
                device_label.set_visible(True)
            if unsupported_label is not None:
                unsupported_label.set_visible(False)
            # Restore scale/db visibility — _rebuild_hw_volume_ch_sliders
            # will refine this once channel info arrives.
            if scale is not None:
                scale.set_visible(True)
            if db_label is not None:
                db_label.set_visible(True)
        elif software_vol:
            if device_label is not None:
                device_label.set_text(
                    f"Software Volume\n{device_name}" if device_name else "Software Volume"
                )
                device_label.set_visible(True)
            if unsupported_label is not None:
                unsupported_label.set_visible(False)
            if scale is not None:
                scale.set_visible(True)
            if db_label is not None:
                db_label.set_visible(True)
            if ch_box is not None:
                # Per-channel sliders are a hardware-only concept.
                ch_box.set_visible(False)
        else:
            if device_label is not None:
                device_label.set_text("")
                device_label.set_visible(False)
            if scale is not None:
                scale.set_visible(False)
            if db_label is not None:
                db_label.set_visible(False)
            if ch_box is not None:
                ch_box.set_visible(False)
            if unsupported_label is not None:
                unsupported_label.set_visible(True)


def _build_volume_popover(self, scale_attr="vol_scale"):
    pop = Gtk.Popover()
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)

    # dB label at the top of the volume popover
    db_label_attr = scale_attr.replace("vol_scale", "vol_db_label")
    db_label = Gtk.Label(label="")
    db_label.add_css_class("dim-label")
    db_label.add_css_class("caption")
    setattr(self, db_label_attr, db_label)
    vbox.append(db_label)

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

    # Per-channel hardware volume sliders (hidden until hw volume is ready)
    ch_box_attr = scale_attr.replace("vol_scale", "vol_ch_box")
    ch_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    ch_box.set_visible(False)
    setattr(self, ch_box_attr, ch_box)
    vbox.append(ch_box)

    # Shown in place of all sliders when the active DAC has no UAC volume
    # control. Toggled by `_update_volume_device_label`.
    unsupported_label_attr = scale_attr.replace("vol_scale", "vol_unsupported_label")
    unsupported_label = Gtk.Label(label="Hardware volume\nnot supported")
    unsupported_label.add_css_class("dim-label")
    unsupported_label.set_justify(Gtk.Justification.CENTER)
    unsupported_label.set_xalign(0.5)
    unsupported_label.set_margin_top(8)
    unsupported_label.set_margin_bottom(8)
    unsupported_label.set_visible(False)
    setattr(self, unsupported_label_attr, unsupported_label)
    vbox.append(unsupported_label)

    device_label_attr = scale_attr.replace("vol_scale", "vol_device_label")
    device_label = Gtk.Label(label="")
    device_label.add_css_class("dim-label")
    device_label.add_css_class("caption")
    device_label.set_xalign(0.5)
    device_label.set_justify(Gtk.Justification.CENTER)
    device_label.set_ellipsize(Pango.EllipsizeMode.END)
    device_label.set_max_width_chars(18)
    device_label.set_visible(False)
    setattr(self, device_label_attr, device_label)
    vbox.append(device_label)
    pop.connect("notify::visible", lambda *_args: _update_volume_device_label(self))
    pop.set_child(vbox)
    _update_volume_device_label(self)
    return pop


_UAC_CH_NAMES = {0: "Master", 1: "Left", 2: "Right"}


def _hw_volume_main_slider_controls_master(player):
    if player is None or not hasattr(player, "usb_hw_volume_channels"):
        return True
    try:
        channels = list(player.usb_hw_volume_channels() or [])
    except Exception:
        return True
    if not channels:
        return True
    return len(channels) == 1 or 0 in channels


def _hw_volume_extra_channel_entries(player):
    if player is None or not hasattr(player, "usb_hw_volume_channels"):
        return []
    try:
        channels = list(player.usb_hw_volume_channels() or [])
    except Exception:
        return []
    if not channels:
        return []
    if 0 in channels:
        return [(idx, uac_ch) for idx, uac_ch in enumerate(channels) if uac_ch != 0]
    return [(idx, uac_ch) for idx, uac_ch in enumerate(channels)]


def _rebuild_hw_volume_ch_sliders(self):
    """Build per-channel sliders when hardware volume channels are known."""
    player = getattr(self, "player", None)
    if player is None or not hasattr(player, "usb_hw_volume_channels"):
        return
    channels = player.usb_hw_volume_channels()
    extra_entries = _hw_volume_extra_channel_entries(player)
    main_controls_master = _hw_volume_main_slider_controls_master(player)
    rng = player.usb_hw_volume_get_range() if hasattr(player, "usb_hw_volume_get_range") else None
    logger.info("hw volume channels=%s extra=%s range=%s", channels, extra_entries, rng)
    if not extra_entries:
        # No per-channel sliders to build. Defer all visibility decisions
        # (master scale vs. "not supported" placeholder) to
        # `_update_volume_device_label`, which knows whether the active DAC
        # exposes hardware volume at all.
        for attr in ("vol_ch_box", "now_playing_vol_ch_box"):
            box = getattr(self, attr, None)
            if box is not None:
                box.set_visible(False)
        _update_volume_device_label(self)
        return

    for attr in ("vol_scale", "now_playing_vol_scale"):
        scale = getattr(self, attr, None)
        if scale is not None:
            scale.set_visible(bool(main_controls_master))
    for attr in ("vol_db_label", "now_playing_vol_db_label"):
        lbl = getattr(self, attr, None)
        if lbl is not None:
            lbl.set_visible(bool(main_controls_master))

    if not hasattr(self, "_hw_vol_ch_programmatic"):
        self._hw_vol_ch_programmatic = False
    self._hw_vol_ch_scales_all = {}
    self._hw_vol_ch_db_labels_all = {}

    if not hasattr(self, "_hw_vol_ch_linked"):
        self._hw_vol_ch_linked = True

    for attr in ("vol_ch_box", "now_playing_vol_ch_box"):
        ch_box = getattr(self, attr, None)
        if ch_box is None:
            continue
        # Clear old children
        while True:
            child = ch_box.get_first_child()
            if child is None:
                break
            ch_box.remove(child)

        sliders_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER)
        columns = []
        for full_idx, uac_ch in extra_entries:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, halign=Gtk.Align.CENTER)
            ch_label = Gtk.Label(label=_UAC_CH_NAMES.get(uac_ch, f"Ch{uac_ch}"))
            ch_label.add_css_class("dim-label")
            ch_label.add_css_class("caption")
            col.append(ch_label)

            # dB label per channel
            db_label = Gtk.Label(label="-- dB")
            db_label.add_css_class("dim-label")
            db_label.add_css_class("caption")
            self._hw_vol_ch_db_labels_all.setdefault(uac_ch, []).append(db_label)
            col.append(db_label)

            ch_scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 100, 5)
            ch_scale.set_inverted(True)
            ch_scale.set_size_request(-1, 120)
            # Don't set initial value from settings — wait for hw events to report
            # the actual DAC volume. This prevents resetting the DAC on playback.
            ch_scale.set_value(50)  # neutral placeholder

            _ch_idx = full_idx
            _uac_ch = uac_ch

            def _on_ch_vol_changed(s, ch_idx=_ch_idx, u_ch=_uac_ch):
                if getattr(self, "_hw_vol_ch_programmatic", False):
                    return
                val = float(s.get_value())
                try:
                    self.player.usb_hw_volume_set_percent_ch(ch_idx, val)
                except Exception:
                    logger.debug("per-channel hw vol set failed", exc_info=True)
                # Update dB labels for this channel (all boxes)
                db = None
                if hasattr(self.player, "usb_hw_volume_percent_to_db"):
                    try:
                        db = self.player.usb_hw_volume_percent_to_db(val)
                    except Exception:
                        pass
                text = f"{db:+.1f} dB" if db is not None else ""
                for lbl in getattr(self, "_hw_vol_ch_db_labels_all", {}).get(u_ch, []):
                    lbl.set_text(text)
                # When L/R are linked, sync the other channel
                if getattr(self, "_hw_vol_ch_linked", True):
                    _sync_linked_ch_volume(self, u_ch, val)

            # Connect after set_value to avoid triggering a hw write on init
            ch_scale.connect("value-changed", _on_ch_vol_changed)
            self._hw_vol_ch_scales_all.setdefault(uac_ch, []).append(ch_scale)
            col.append(ch_scale)
            columns.append(col)

        for c in columns:
            sliders_row.append(c)
        ch_box.append(sliders_row)

        # Link button below the sliders
        if len(columns) >= 2:
            link_btn = Gtk.ToggleButton()
            link_btn.set_active(getattr(self, "_hw_vol_ch_linked", True))
            link_btn.set_icon_name(
                "changes-prevent-symbolic" if link_btn.get_active() else "changes-allow-symbolic"
            )
            link_btn.set_tooltip_text("Link Left/Right channels")
            link_btn.set_halign(Gtk.Align.CENTER)
            link_btn.add_css_class("flat")
            link_btn.add_css_class("circular")
            link_btn.connect("toggled", lambda b: _on_hw_vol_link_toggled(self, b))
            ch_box.append(link_btn)

        ch_box.set_visible(True)


def _on_hw_vol_link_toggled(self, btn):
    """Toggle linked state for Left/Right channel sliders."""
    linked = btn.get_active()
    self._hw_vol_ch_linked = linked
    btn.set_icon_name(
        "changes-prevent-symbolic" if linked else "changes-allow-symbolic"
    )
    # When linking, sync Right to Left's current value
    if linked:
        left_scales = getattr(self, "_hw_vol_ch_scales_all", {}).get(1, [])
        if left_scales:
            val = left_scales[0].get_value()
            _sync_linked_ch_volume(self, 1, val)


def _sync_linked_ch_volume(self, source_uac_ch, percent):
    """When L/R are linked, set the other channel to the same percent."""
    if source_uac_ch == 1:
        target_uac_ch = 2
    elif source_uac_ch == 2:
        target_uac_ch = 1
    else:
        return
    # Find the target channel's full_idx for the hw volume call
    player = getattr(self, "player", None)
    if player is None:
        return
    extra_entries = _hw_volume_extra_channel_entries(player)
    target_idx = None
    for full_idx, uac_ch in extra_entries:
        if uac_ch == target_uac_ch:
            target_idx = full_idx
            break
    if target_idx is None:
        return
    # Set hw volume on the other channel
    try:
        player.usb_hw_volume_set_percent_ch(target_idx, percent)
    except Exception:
        logger.debug("linked ch vol set failed", exc_info=True)
    # Sync the other channel's slider(s) and dB label(s)
    try:
        self._hw_vol_ch_programmatic = True
        for scale in getattr(self, "_hw_vol_ch_scales_all", {}).get(target_uac_ch, []):
            scale.set_value(percent)
    finally:
        self._hw_vol_ch_programmatic = False
    db = None
    if hasattr(player, "usb_hw_volume_percent_to_db"):
        try:
            db = player.usb_hw_volume_percent_to_db(percent)
        except Exception:
            pass
    text = f"{db:+.1f} dB" if db is not None else ""
    for lbl in getattr(self, "_hw_vol_ch_db_labels_all", {}).get(target_uac_ch, []):
        lbl.set_text(text)


def _sync_hw_volume_ch_slider_positions(self):
    """Read current hw volume per channel and update slider positions + dB labels."""
    player = getattr(self, "player", None)
    ch_scales_all = getattr(self, "_hw_vol_ch_scales_all", {})
    if not player or not ch_scales_all:
        return
    extra_entries = _hw_volume_extra_channel_entries(player)
    try:
        self._hw_vol_ch_programmatic = True
        for full_idx, uac_ch in extra_entries:
            scales = ch_scales_all.get(uac_ch, [])
            if not scales:
                continue
            raw = player.usb_hw_volume_get_ch(full_idx)
            pct = player.usb_hw_volume_raw_to_percent(raw) if raw is not None else None
            if pct is not None:
                pct = max(0.0, min(100.0, float(pct)))
                for scale in scales:
                    scale.set_value(pct)
                # Update dB labels
                db_val = float(raw) / 256.0
                text = f"{db_val:+.1f} dB"
                for lbl in getattr(self, "_hw_vol_ch_db_labels_all", {}).get(uac_ch, []):
                    lbl.set_text(text)
    finally:
        self._hw_vol_ch_programmatic = False


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
    self.close_mini_queue()
    _reset_search_focus_after_layout_change(self)

    self.is_mini_mode = not self.is_mini_mode

    if self.is_mini_mode:
        self.saved_width = self.win.get_width()
        self.saved_height = self.win.get_height()

        self.header.set_visible(False)
        self.paned.set_visible(False)

        self.bottom_bar.add_css_class("mini-state")
        self.mini_controls.set_visible(True)
        if getattr(self, "mini_queue_arrow", None) is not None:
            self.mini_queue_arrow.set_visible(True)

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
        self.win.add_css_class("mini-mode")
        self.win.set_resizable(False)
        self.win.set_size_request(390, 85)
        self.win.set_default_size(390, 85)
    else:
        self.close_mini_queue()
        self.header.set_visible(True)
        self.paned.set_visible(True)
        self.mini_controls.set_visible(False)
        if getattr(self, "mini_queue_arrow", None) is not None:
            self.mini_queue_arrow.set_visible(False)
        if getattr(self, "mini_queue_revealer", None) is not None:
            self.mini_queue_revealer.set_visible(False)
            self.mini_queue_revealer.set_reveal_child(False)

        if self.timeline_box is not None: self.timeline_box.set_visible(True)
        if self.vol_box is not None: self.vol_box.set_visible(True)
        if self.tech_box is not None: self.tech_box.set_visible(True)
        if getattr(self, "player_left_panel", None) is not None:
            self.player_left_panel.set_size_request(-1, -1)
        if getattr(self, "player_right_panel", None) is not None:
            self.player_right_panel.set_size_request(-1, -1)
        if getattr(self, "info_area", None) is not None:
            self.info_area.set_size_request(-1, -1)
        if getattr(self, "player_text_box", None) is not None:
            self.player_text_box.set_size_request(120, -1)
        if getattr(self, "art_img", None) is not None:
            self.art_img.set_size_request(80, 80)
        # Reset adaptive tier so the width handler re-evaluates.
        self._player_bar_layout_tier = "full"

        self.bottom_bar.remove_css_class("mini-state")
        # Reset scroll height that may have been changed by drawer resize.
        self.win.remove_css_class("mini-mode")
        self.win.set_decorated(True)
        self.win.set_resizable(True)
        self.win.set_size_request(-1, -1)
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
    player = getattr(self, "player", None)
    hw_vol = (
        player is not None
        and hasattr(player, "usb_hw_volume_supported")
        and player.usb_hw_volume_supported()
    )

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
    _update_volume_db_label(self, target_volume if not locked else None)

    for pop in (getattr(self, "vol_pop", None), getattr(self, "now_playing_vol_pop", None)):
        if locked and pop is not None:
            pop.popdown()
    _update_volume_device_label(self)

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
