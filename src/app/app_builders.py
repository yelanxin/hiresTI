"""
UI builders and interactive UI methods for TidalApp.
Contains popover builders, key handler, mini mode, volume lock and simple dialog.
"""
import logging

from gi.repository import Gtk, Gdk, GLib, Pango

from ui import config as ui_config

logger = logging.getLogger(__name__)


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


def _build_volume_popover(self):
    pop = Gtk.Popover()
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)

    self.vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 100, 5)
    self.vol_scale.set_inverted(True)
    self.vol_scale.set_size_request(-1, 150)
    self.vol_scale.set_value(80)
    self.vol_scale.connect("value-changed", self.on_volume_changed_ui)

    vbox.append(self.vol_scale)
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

    if keyval == Gdk.KEY_Escape and getattr(self, "queue_revealer", None) is not None:
        if self.queue_revealer.get_reveal_child():
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


def _build_eq_popover(self):
    pop = Gtk.Popover()
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
    hb = Gtk.Box(spacing=12)
    hb.append(Gtk.Label(label="10-Band Equalizer", css_classes=["title-4"]))
    reset = Gtk.Button(label="Reset", css_classes=["flat"])
    reset.connect("clicked", lambda b: (self.player.reset_eq(), [s.set_value(0) for s in self.sliders]))
    hb.append(reset)
    vbox.append(hb)
    hbox = Gtk.Box(spacing=8)
    freqs = ["30", "60", "120", "240", "480", "1k", "2k", "4k", "8k", "16k"]
    self.sliders = []
    for i, f in enumerate(freqs):
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -24, 12, 1)
        scale.set_inverted(True)
        scale.set_size_request(-1, 150)
        scale.set_value(0)
        scale.add_mark(0, Gtk.PositionType.RIGHT, None)
        scale.connect("value-changed", lambda s, idx=i: self.player.set_eq_band(idx, s.get_value()))
        self.sliders.append(scale)
        vb.append(scale)
        vb.append(Gtk.Label(label=f, css_classes=["caption"]))
        hbox.append(vb)
    vbox.append(hbox)
    pop.set_child(vbox)
    return pop


def _lock_volume_controls(self, locked):
    if self.vol_scale is not None and self.vol_btn is not None:
        if locked:
            self.vol_scale.set_value(100)
            self.vol_btn.set_sensitive(False)
            self.vol_btn.set_tooltip_text("Volume locked in Bit-Perfect/Exclusive mode")
            self.vol_btn.set_icon_name("hiresti-volume-high-symbolic")
            if self.vol_pop is not None:
                self.vol_pop.popdown()
        else:
            self.vol_btn.set_sensitive(True)
            self.vol_scale.set_sensitive(True)
            self.vol_btn.set_tooltip_text("Adjust Volume")

    if self.eq_btn is not None:
        self.eq_btn.set_sensitive(not locked)
        if locked:
            self.eq_btn.set_tooltip_text("EQ disabled in Bit-Perfect mode (Bypassed)")
            if self.eq_pop is not None:
                self.eq_pop.popdown()
        else:
            self.eq_btn.set_tooltip_text("Equalizer")


def _build_help_popover(self):
    pop = Gtk.Popover()
    pop.set_has_arrow(False)
    pop.add_css_class("shortcuts-surface")
    vbox = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=18,
        margin_bottom=18,
        margin_start=18,
        margin_end=18,
        css_classes=["shortcuts-popover"],
    )
    vbox.set_size_request(420, -1)

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
