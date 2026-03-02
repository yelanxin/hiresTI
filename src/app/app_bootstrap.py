"""Application bootstrap/lifecycle methods delegated from main.py."""

import logging
import os

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk

from ui import config as ui_config

logger = logging.getLogger(__name__)


def detect_app_version(self):
    env_ver = str(os.environ.get("HIRESTI_VERSION", "")).strip()
    if env_ver:
        return env_ver
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        src_root = os.path.dirname(root)
        ver_file = os.path.join(src_root, "version.txt")
        if os.path.exists(ver_file):
            with open(ver_file, "r", encoding="utf-8") as f:
                version = str(f.read()).strip()
                if version:
                    return version
        changelog = os.path.join(src_root, "CHANGELOG.md")
        with open(changelog, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("## "):
                    head = line[3:].strip()
                    version = head.split(" - ", 1)[0].strip()
                    if version:
                        return version
                    break
    except Exception:
        pass
    return "dev"


def _configure_icon_theme(display):
    icon_theme = Gtk.IconTheme.get_for_display(display)
    app_root = os.path.dirname(os.path.dirname(__file__))
    project_root = os.path.dirname(app_root)
    search_paths = [
        os.path.join(app_root, "icons"),
        os.path.join(project_root, "icons"),
    ]
    added = []
    seen = set()
    for path in search_paths:
        norm = os.path.abspath(path)
        if norm in seen or not os.path.isdir(norm):
            continue
        icon_theme.add_search_path(norm)
        added.append(norm)
        seen.add(norm)
    if added:
        logger.info("Added GTK icon theme search paths: %s", ", ".join(added))
    else:
        logger.warning("No bundled GTK icon theme search path found.")
    return icon_theme


def do_shutdown(self):
    logger.info("Shutting down application...")
    if hasattr(self, "_stop_remote_api"):
        self._stop_remote_api(show_notice=False)
    self._stop_mpris_service()
    self._stop_tray_icon()
    self.settings["search_history"] = list(self.search_history)[:10]
    pending = getattr(self, "_settings_save_source", 0)
    if pending:
        GLib.source_remove(pending)
        self._settings_save_source = 0
    pulse = getattr(self, "_playing_pulse_source", 0)
    if pulse:
        GLib.source_remove(pulse)
        self._playing_pulse_source = 0
    ui_loop = getattr(self, "_ui_loop_source", 0)
    if ui_loop:
        GLib.source_remove(ui_loop)
        self._ui_loop_source = 0
    output_status = getattr(self, "_output_status_source", 0)
    if output_status:
        GLib.source_remove(output_status)
        self._output_status_source = 0
    seek_commit = getattr(self, "_seek_commit_source", 0)
    if seek_commit:
        GLib.source_remove(seek_commit)
        self._seek_commit_source = 0
    self.save_settings()
    if self.player is not None:
        self.player.cleanup()
    # Call explicit parent vfunc to avoid introspection edge-cases when
    # shutting down from headless/error paths.
    Adw.Application.do_shutdown(self)


def _restore_runtime_state(self):
    saved_volume = self.settings.get("volume", 80)
    if hasattr(self, "_sync_volume_ui_state"):
        self._sync_volume_ui_state(value=saved_volume)
    elif self.vol_scale is not None:
        self.vol_scale.set_value(saved_volume)
    if self.player is not None:
        self.player.set_volume(saved_volume / 100.0)

    mode_icon = self.MODE_ICONS.get(self.play_mode, "hiresti-mode-loop-symbolic")
    mode_tip = self.MODE_TOOLTIPS.get(self.play_mode, "Loop All (Album/Playlist)")
    for btn in (getattr(self, "mode_btn", None), getattr(self, "now_playing_mode_btn", None)):
        if btn is not None:
            btn.set_icon_name(mode_icon)
            btn.set_tooltip_text(mode_tip)

    if self.paned is not None and self.win is not None:
        sidebar_px = int(max(120, self.win.get_width() * float(ui_config.SIDEBAR_RATIO)))
        self.paned.set_position(sidebar_px)

    self._apply_viz_bars_by_count(self.settings.get("viz_bar_count", 32), update_dropdown=True)
    self._apply_viz_profile_by_index(self.settings.get("viz_profile", 1), update_dropdown=True)
    self._apply_viz_effect_by_index(self.settings.get("viz_effect", 3), update_dropdown=True)
    self._apply_spectrum_theme_by_index(self.settings.get("spectrum_theme", 0), update_dropdown=True)
    self._apply_lyrics_font_preset_by_index(self.settings.get("lyrics_font_preset", 1), update_dropdown=True)
    self._apply_lyrics_motion_by_index(self.settings.get("lyrics_bg_motion", 1), update_dropdown=True)
    self._apply_lyrics_offset_ms(self.settings.get("lyrics_user_offset_ms", 0))


def _run_post_activate_tasks(app):
    # Run non-critical startup work after first frame to improve perceived launch speed.
    app._start_mpris_service()
    if hasattr(app, "_start_remote_api_if_enabled"):
        app._start_remote_api_if_enabled()
    app._restore_session_async()
    app._schedule_update_ui_loop(40)
    app._schedule_output_status_loop(1000)
    GLib.timeout_add(80, app._start_spectrum_stream_prewarm)
    GLib.timeout_add(220, lambda: (app._init_tray_icon(), False)[1])
    GLib.timeout_add(0, app._ensure_overlay_handles_visible)
    return False


def do_activate(self):
    if self.window_created:
        self.win.present()
        return

    display = Gdk.Display.get_default()
    if display is None:
        logger.error("No graphical display detected; cannot start GTK UI.")
        self.quit()
        return

    src_dir = os.path.dirname(os.path.dirname(__file__))
    _configure_icon_theme(display)

    provider = Gtk.CssProvider()
    logo_svg = os.path.join(src_dir, "icons", "hicolor", "scalable", "apps", "hiresti.svg")
    css_data = ui_config.CSS_DATA.replace("__HIRESTI_LOGO_SVG__", logo_svg.replace("\\", "/"))
    provider.load_from_data(css_data.encode())
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    self.win = Adw.ApplicationWindow(
        application=self,
        title="hiresTI Desktop",
        default_width=ui_config.WINDOW_WIDTH,
        default_height=ui_config.WINDOW_HEIGHT,
    )
    self.window_created = True
    self.win.connect("close-request", self.on_window_close_request)

    self.main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    self.win.set_content(self.main_vbox)

    self._build_header(self.main_vbox)
    self.content_window_handle = Gtk.WindowHandle()
    self.content_window_handle.set_hexpand(True)
    self.content_window_handle.set_vexpand(True)
    self.main_vbox.append(self.content_window_handle)
    self.content_overlay = Gtk.Overlay()
    self.content_overlay.set_hexpand(True)
    self.content_overlay.set_vexpand(True)
    self.content_window_handle.set_child(self.content_overlay)
    self.content_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    self.content_vbox.set_hexpand(True)
    self.content_vbox.set_vexpand(True)
    self.content_overlay.set_child(self.content_vbox)
    self._build_body(self.content_vbox)
    self._build_player_bar(self.content_vbox)
    if hasattr(self, "_build_now_playing_overlay"):
        self._build_now_playing_overlay()
    self._setup_theme_watch()
    self._restore_runtime_state()
    self._set_login_view_pending()

    # === 恢复设置逻辑 ===
    is_bp = self.settings.get("bit_perfect", False)
    is_ex = self.settings.get("exclusive_lock", False)

    # 1. 应用 Bit-Perfect 和 独占状态
    self.player.toggle_bit_perfect(is_bp, exclusive_lock=is_ex)
    if is_bp:
        if self.bp_label is not None:
            self.bp_label.set_visible(True)
        self._lock_volume_controls(True)

    # 2. 应用 Latency
    saved_profile = self.settings.get("latency_profile", "Standard (100ms)")
    if saved_profile in self.LATENCY_MAP:
        buf_ms, lat_ms = self.LATENCY_MAP[saved_profile]
        self.player.set_alsa_latency(buf_ms, lat_ms)

    # 3. 恢复驱动选择
    drivers = self.player.get_drivers()
    saved_drv = self.settings.get("driver", "Auto (Default)")

    # 如果保存的是 ALSA 或其他驱动，先尝试选中
    if saved_drv in drivers:
        try:
            idx = drivers.index(saved_drv)
            self.driver_dd.set_selected(idx)
        except Exception as e:
            logger.warning("Failed to restore saved driver selection '%s': %s", saved_drv, e)

    # Defer heavy output initialization until after first frame is presented.
    GLib.idle_add(lambda: (self.on_driver_changed(self.driver_dd, None), False)[1])

    if is_ex:
        self.driver_dd.set_sensitive(False)
        self._force_driver_selection("ALSA")

    key_controller = Gtk.EventControllerKey()
    key_controller.connect("key-pressed", self.on_key_pressed)
    self.win.add_controller(key_controller)

    self.win.present()
    GLib.idle_add(_run_post_activate_tasks, self)
    GLib.idle_add(self._clear_initial_search_focus)
    GLib.timeout_add(120, self._clear_initial_search_focus)
    self.win.connect("notify::default-width", self.update_layout_proportions)
    self.win.connect("notify::default-height", self.update_layout_proportions)
    # Fullscreen/restore can finish allocation a bit later; listen and re-align.
    for prop in ("fullscreened", "maximized"):
        try:
            self.win.connect(f"notify::{prop}", self.update_layout_proportions)
        except Exception:
            pass
    if getattr(self, "body_overlay", None) is not None:
        self.body_overlay.connect("notify::width", self.update_layout_proportions)
        self.body_overlay.connect("notify::height", self.update_layout_proportions)
    self.paned.connect("notify::position", self.on_paned_position_changed)
    GLib.idle_add(lambda: (self._schedule_viz_handle_realign(animate=False), False)[1])
