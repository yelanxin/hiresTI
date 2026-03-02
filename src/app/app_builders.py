"""
UI builders and interactive UI methods for TidalApp.
Contains popover builders, key handler, mini mode, volume lock and simple dialog.
"""
import logging

from gi.repository import Gtk, Gdk, GLib, Pango

from ui import config as ui_config

logger = logging.getLogger(__name__)

_EQ_FREQS = ["30", "60", "120", "240", "480", "1k", "2k", "4k", "8k", "16k"]


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
    _sync_eq_slider_groups(self, source_scale=scale)


def _reset_eq_ui(self):
    self.eq_band_values = [0.0] * len(_EQ_FREQS)
    try:
        self.player.reset_eq()
    except Exception:
        logger.debug("reset_eq failed", exc_info=True)
    _sync_eq_slider_groups(self)


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
    hb = Gtk.Box(spacing=12)
    hb.append(Gtk.Label(label="10-Band Equalizer", css_classes=["title-4"]))
    reset = Gtk.Button(label="Reset", css_classes=["flat"])
    reset.connect("clicked", lambda _b: self._reset_eq_ui())
    hb.append(reset)
    vbox.append(hb)
    hbox = Gtk.Box(spacing=8)
    sliders = []
    eq_values = list(getattr(self, "eq_band_values", [0.0] * len(_EQ_FREQS)) or [])
    if len(eq_values) < len(_EQ_FREQS):
        eq_values.extend([0.0] * (len(_EQ_FREQS) - len(eq_values)))
        self.eq_band_values = eq_values
    for i, f in enumerate(_EQ_FREQS):
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -24, 12, 1)
        scale.set_inverted(True)
        scale.set_size_request(-1, 150)
        scale.set_value(float(eq_values[i]))
        scale.add_mark(0, Gtk.PositionType.RIGHT, None)
        scale.connect("value-changed", lambda s, idx=i: self._on_eq_slider_changed(s, idx))
        sliders.append(scale)
        vb.append(scale)
        vb.append(Gtk.Label(label=f, css_classes=["caption"]))
        hbox.append(vb)
    setattr(self, sliders_attr, sliders)
    vbox.append(hbox)
    pop.set_child(vbox)
    return pop


def _lock_volume_controls(self, locked):
    for scale in (getattr(self, "vol_scale", None), getattr(self, "now_playing_vol_scale", None)):
        if scale is not None and locked:
            scale.set_value(100)
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

    for btn in (getattr(self, "eq_btn", None), getattr(self, "now_playing_eq_btn", None)):
        if btn is None:
            continue
        btn.set_sensitive(not locked)
        if locked:
            btn.set_tooltip_text("EQ disabled in Bit-Perfect mode (Bypassed)")
        else:
            btn.set_tooltip_text("Equalizer")

    for pop in (getattr(self, "eq_pop", None), getattr(self, "now_playing_eq_pop", None)):
        if locked and pop is not None:
            pop.popdown()


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
