import os
import logging
import time
import math
import random
import shutil
import subprocess
import platform
from datetime import datetime, timedelta
from urllib.parse import urlparse
os.environ["MESA_LOG_LEVEL"] = "error"

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, Pango
import webbrowser
from threading import Thread, current_thread, main_thread
from tidal_backend import TidalBackend
from rust_audio_engine import create_audio_engine
from models import HistoryManager, PlaylistManager
from signal_path import AudioSignalPathWindow
import utils
import ui_config
from ui import builders as ui_builders
from ui import views_builders as ui_views_builders
from visualizer import SpectrumVisualizer
from visualizer_glarea import SpectrumVisualizerGLArea
from visualizer_gpu import SpectrumVisualizerGPU
from actions import ui_actions
from actions import ui_navigation
from actions import playback_actions
from actions import audio_settings_actions
from actions import lyrics_playback_actions
from actions import playback_stream_actions
from lyrics_manager import LyricsManager
from app_logging import setup_logging
from app_settings import load_settings, save_settings as persist_settings
from app_errors import classify_exception

logger = logging.getLogger(__name__)

try:
    import pystray
    from PIL import Image
except Exception:
    pystray = None
    Image = None

try:
    import qrcode
except Exception:
    qrcode = None

class TidalApp(Adw.Application):
    MODE_LOOP = 0     # 列表循环 (默认)
    MODE_ONE = 1      # 单曲循环
    MODE_SHUFFLE = 2  # 专辑/列表随机 (本地乱序)
    MODE_SMART = 3    # 算法随机 (模拟 AI 推荐/无限流)

    # 对应的图标
    MODE_ICONS = {
        0: "hiresti-mode-loop-symbolic",
        1: "hiresti-mode-one-symbolic",
        2: "hiresti-mode-shuffle-symbolic",
        3: "hiresti-mode-smart-symbolic"
    }

    # 对应的提示文字
    MODE_TOOLTIPS = {
        0: "Loop All (Album/Playlist)",
        1: "Loop Single Track",
        2: "Shuffle (Randomize Order)",
        3: "Smart Shuffle (Algorithm)"
    }
    LYRICS_FONT_PRESETS = ["Live", "Studio", "Compact"]
    LATENCY_OPTIONS = ["Safe (400ms)", "Standard (100ms)", "Low Latency (40ms)", "Aggressive (20ms)"]
    VIZ_BAR_OPTIONS = [4, 8, 16, 32, 48, 64, 96, 128]
    VIZ_BACKEND_POLICIES = ["Perf", "Quality"]
    LATENCY_MAP = {
        "Safe (400ms)":      (400, 40),  # Buffer, Latency
        "Standard (100ms)":  (100, 10),
        "Low Latency (40ms)":(40, 4),
        "Aggressive (20ms)": (20, 2)
    }

    def _init_ui_refs(self):
        # Widgets created during do_activate/build steps.
        self.bp_label = None
        self.viz_stack_box = None
        self.vol_btn = None
        self.vol_scale = None
        self.vol_pop = None
        self.viz_revealer = None
        self.viz_theme_dd = None
        self.viz_bars_dd = None
        self.viz_effect_dd = None
        self.viz_profile_dd = None
        self.viz_policy_dd = None
        self.lyrics_font_dd = None
        self.lyrics_motion_dd = None
        self.lyrics_font_label = None
        self.lyrics_offset_label = None
        self.timeline_box = None
        self.scale_overlay = None
        self.scale_thumb = None
        self.vol_box = None
        self.tech_box = None
        self.bg_viz = None
        self.lyrics_tab_root = None
        self.viz = None
        self._viz_backend_key = None
        self._viz_ui_syncing = False
        self._viz_effect_apply_source = None
        self._viz_profile_apply_source = None
        self._viz_theme_apply_source = None
        self._viz_policy_apply_source = None
        self.eq_btn = None
        self.eq_pop = None
        self.mode_btn = None
        self.track_fav_btn = None
        self.track_list = None
        self.playlist_track_list = None
        self.liked_track_list = None
        self.liked_tracks_data = []
        self.liked_tracks_last_fetch_ts = 0.0
        self.liked_tracks_cache_ttl_sec = 30.0
        self.queue_track_list = None
        self.queue_drawer_list = None
        self.queue_count_label = None
        self.queue_clear_btn = None
        self.queue_revealer = None
        self.queue_backdrop = None
        self.queue_btn = None
        self.viz_anchor = None
        self.viz_handle_box = None
        self.current_album = None
        self.current_remote_playlist = None
        self.current_playlist_folder = None
        self.current_playlist_folder_stack = []
        self.current_selected_artist = None
        self.list_box = None
        self.output_status_label = None
        self.output_recover_btn = None
        self.output_notice_revealer = None
        self.output_notice_icon = None
        self.output_notice_label = None
        self._output_notice_source = 0
        self._output_status_source = 0
        self._viz_handle_anim_source = 0
        self._viz_handle_settle_source = 0
        self._viz_handle_resize_source = 0
        self._viz_handle_resize_retries = 0
        self._viz_open_layout_source = 0
        self._viz_fade_source = 0
        self._viz_open_stream_source = 0
        self._viz_stream_prewarm_source = 0
        self._viz_opened_once = False
        self._viz_gl_prewarm_done = False
        self._last_spectrum_frame = None
        self._last_spectrum_ts = 0.0
        self._viz_seed_frame = None
        self._viz_warmup_until = 0.0
        self._viz_warmup_duration_s = 2.0
        self._viz_placeholder_source = 0
        self._viz_placeholder_phase = 0.0
        self._viz_placeholder_frame = []
        self._viz_real_frame_streak = 0
        self._viz_trace_open_ts = 0.0
        self._viz_trace_last_cb_ts = 0.0
        self._viz_trace_first_real_logged = False
        self._ui_loop_source = 0
        self._last_output_state = None
        self._last_output_error = None
        self.network_status_label = None
        self.decoder_status_label = None
        self.events_btn = None
        self._diag_events = []
        self._diag_health = {"network": "idle", "decoder": "idle", "output": "idle"}
        self._diag_pop = None
        self._diag_text = None
        self._login_in_progress = False
        self._login_attempt_id = None
        self._login_mode = None
        self._login_dialog = None
        self._login_qr_tempfile = None
        self._login_status_label = None
        self._session_restore_pending = False
        self.search_content_box = None
        self.add_playlist_btn = None
        self.remote_playlist_edit_btn = None
        self.remote_playlist_visibility_btn = None
        self.remote_playlist_more_btn = None
        self.remote_playlist_more_pop = None
        self.add_selected_tracks_btn = None
        self.like_selected_tracks_btn = None
        self.search_prev_page_btn = None
        self.search_next_page_btn = None
        self.search_tracks_page_label = None
        self.search_selected_indices = set()
        self.search_tracks_page = 0
        self.search_tracks_page_size = 50
        self.collection_base_margin_bottom = 32
        self.track_list_base_margin_bottom = 32
        self.search_base_margin_bottom = 32
        self.daily_mix_data = []
        self._tray_icon = None
        self._tray_ready = False
        self._allow_window_close = False
        self._thumb_smooth_x = None
        self._seek_pending_value = None
        self._seek_commit_source = 0
        self._seek_user_interacting = False
        self._viz_current_page = "spectrum"

    def _apply_overlay_scroll_padding(self, expanded):
        extra = 0
        if expanded:
            # Use actual overlay height + small breathing room.
            breathing_px = 12
            overlay_h = 0
            # Use stack content height only (exclude switcher/header), closer to actual covered area.
            if hasattr(self, "viz_stack") and self.viz_stack is not None:
                overlay_h = self.viz_stack.get_height()
            if overlay_h <= 1:
                overlay_h = 250
            extra = overlay_h + breathing_px
        if hasattr(self, "collection_content_box") and self.collection_content_box is not None:
            self.collection_content_box.set_margin_bottom(self.collection_base_margin_bottom + extra)
        if self.track_list is not None:
            self.track_list.set_margin_bottom(self.track_list_base_margin_bottom + extra)
        if self.search_content_box is not None:
            self.search_content_box.set_margin_bottom(self.search_base_margin_bottom + extra)

    def record_diag_event(self, message):
        if current_thread() is not main_thread():
            GLib.idle_add(self.record_diag_event, message)
            return
        ts = time.strftime("%H:%M:%S")
        self._diag_events.append(f"{ts} | {message}")
        if len(self._diag_events) > 120:
            self._diag_events = self._diag_events[-120:]
        if self._diag_text is not None:
            combined = list(getattr(self.player, "event_log", [])) + self._diag_events
            buf = self._diag_text.get_buffer()
            buf.set_text("\n".join(combined[-120:]))

    def _apply_status_class(self, label, state):
        if label is None:
            return
        class_map = {
            "ok": "status-active",
            "warn": "status-fallback",
            "error": "status-error",
            "idle": "status-idle",
            "switching": "status-switching",
        }
        for cls in ("status-active", "status-fallback", "status-error", "status-switching", "status-idle"):
            label.remove_css_class(cls)
        label.add_css_class(class_map.get(state, "status-idle"))

    def set_diag_health(self, kind, state, detail=None):
        if current_thread() is not main_thread():
            GLib.idle_add(self.set_diag_health, kind, state, detail)
            return
        if kind not in self._diag_health:
            return
        prev = self._diag_health.get(kind)
        self._diag_health[kind] = state
        if prev != state:
            text = f"{kind.upper()} -> {state.upper()}"
            if detail:
                text = f"{text} ({detail})"
            self.record_diag_event(text)
        if kind == "network" and self.network_status_label is not None:
            self.network_status_label.set_text(f"NET {state.upper()}")
            self._apply_status_class(self.network_status_label, state)
        if kind == "decoder" and self.decoder_status_label is not None:
            self.decoder_status_label.set_text(f"DEC {state.upper()}")
            self._apply_status_class(self.decoder_status_label, state)

    def show_diag_events(self, _btn=None):
        if self._diag_pop is None or self._diag_text is None:
            return
        combined = list(getattr(self.player, "event_log", [])) + self._diag_events
        buf = self._diag_text.get_buffer()
        buf.set_text("\n".join(combined[-120:]) if combined else "No events yet.")
        self._diag_pop.popup()

    def show_output_notice(self, text, state="idle", timeout_ms=2600):
        if not text or self.output_notice_revealer is None or self.output_notice_label is None:
            return
        self.output_notice_label.set_text(str(text))
        icon_map = {
            "switching": "hiresti-tech-symbolic",
            "ok": "emblem-ok-symbolic",
            "warn": "dialog-warning-symbolic",
            "error": "dialog-error-symbolic",
            "idle": "hiresti-tech-symbolic",
        }
        if self.output_notice_icon is not None:
            self.output_notice_icon.set_from_icon_name(icon_map.get(state, "hiresti-tech-symbolic"))
        chip = self.output_notice_revealer.get_child()
        if chip is not None:
            for cls in ("output-notice-ok", "output-notice-warn", "output-notice-error", "output-notice-switching"):
                chip.remove_css_class(cls)
            class_map = {
                "ok": "output-notice-ok",
                "warn": "output-notice-warn",
                "error": "output-notice-error",
                "switching": "output-notice-switching",
            }
            cls = class_map.get(state)
            if cls:
                chip.add_css_class(cls)
        self.output_notice_revealer.set_reveal_child(True)
        if self._output_notice_source:
            GLib.source_remove(self._output_notice_source)
            self._output_notice_source = 0

        def _hide_notice():
            self._output_notice_source = 0
            if self.output_notice_revealer is not None:
                self.output_notice_revealer.set_reveal_child(False)
            return False

        self._output_notice_source = GLib.timeout_add(int(timeout_ms), _hide_notice)

    def on_output_state_transition(self, prev_state, state, detail=None):
        if state == "switching":
            try:
                audio_settings_actions._touch_output_probe_burst(self, seconds=30)
            except Exception:
                pass
            self.show_output_notice("Audio device changed, reconnecting...", "switching", 2400)
            return
        if state == "active" and prev_state in ("switching", "fallback", "error"):
            self.show_output_notice("Audio output reconnected", "ok", 2200)
            return
        if state == "fallback":
            try:
                audio_settings_actions._touch_output_probe_burst(self, seconds=60)
            except Exception:
                pass
            if self.play_btn is not None:
                self.play_btn.set_icon_name("media-playback-start-symbolic")
            detail_text = str(detail or "")
            if "disconnected" in detail_text.lower():
                # Remember the device that was active when disconnect happened, so
                # hotplug logic can detect "same device came back" and optionally
                # auto-rebind once.
                try:
                    drv_item = self.driver_dd.get_selected_item() if self.driver_dd is not None else None
                    dev_item = self.device_dd.get_selected_item() if self.device_dd is not None else None
                    if drv_item is not None:
                        self._last_disconnected_driver = drv_item.get_string()
                    if dev_item is not None:
                        self._last_disconnected_device_name = dev_item.get_string()
                except Exception:
                    pass
                self.show_output_notice("USB audio device disconnected, rebinding to first available output", "warn", 3600)
                # Keep selected driver unchanged; refresh devices and bind to first available.
                try:
                    audio_settings_actions.refresh_devices_keep_driver_select_first(self, reason="usb-disconnect")
                    audio_settings_actions.start_output_hotplug_watch(
                        self,
                        seconds=60,
                        interval_ms=1000,
                        slow_interval_ms=5000,
                    )
                except Exception:
                    pass
            else:
                self.show_output_notice("Primary output unavailable, switched to fallback", "warn", 3200)
            return
        if state == "error":
            try:
                audio_settings_actions._touch_output_probe_burst(self, seconds=45)
            except Exception:
                pass
            if self.play_btn is not None:
                self.play_btn.set_icon_name("media-playback-start-symbolic")
            msg = str(detail or "Unknown output error")
            self.show_output_notice(f"Output error: {msg}", "error", 3600)

    def _schedule_cache_maintenance(self):
        def _parse_int_env(name, default):
            raw = os.getenv(name)
            if not raw:
                return default
            try:
                value = int(raw)
                return value if value > 0 else default
            except ValueError:
                return default

        max_mb = _parse_int_env("HIRESTI_COVER_CACHE_MAX_MB", 300)
        max_days = _parse_int_env("HIRESTI_COVER_CACHE_MAX_DAYS", 30)
        max_bytes = max_mb * 1024 * 1024

        def task():
            logger.info(
                "Running cover/audio cache maintenance (cover=%sMB ttl=%sd, audio tracks=%s)",
                max_mb,
                max_days,
                getattr(self, "audio_cache_tracks", 0),
            )
            utils.prune_image_cache(self.cache_dir, max_bytes=max_bytes, max_age_days=max_days)
            utils.prune_audio_cache(
                getattr(self, "audio_cache_dir", ""),
                max_tracks=max(0, int(getattr(self, "audio_cache_tracks", 0) or 0)),
            )

        Thread(target=task, daemon=True).start()

    def _account_scope_from_backend_user(self):
        user = getattr(self.backend, "user", None)
        uid = getattr(user, "id", None)
        if uid is None:
            return "guest"
        raw = str(uid).strip()
        if not raw:
            return "guest"
        safe = "".join(ch if (ch.isalnum() or ch in ("-", "_")) else "_" for ch in raw)
        return f"u_{safe}" if safe else "guest"

    def _apply_account_scope(self, force=False):
        scope = self._account_scope_from_backend_user()
        if (not force) and scope == getattr(self, "_account_scope", None):
            return
        self._account_scope = scope
        if hasattr(self, "history_mgr") and self.history_mgr is not None:
            self.history_mgr.set_scope(scope)
        if hasattr(self, "playlist_mgr") and self.playlist_mgr is not None:
            self.playlist_mgr.set_scope(scope)
        # Reset playlist-specific transient state to avoid stale references across accounts.
        self.current_playlist_id = None
        self.playlist_edit_mode = False
        self.playlist_rename_mode = False
        logger.info("Local data scope switched to account: %s", scope)

    def __init__(self):
        super().__init__(application_id="com.hiresti.player")
        GLib.set_application_name("HiresTI")
        GLib.set_prgname("HiresTI")
        self.app_version = self._detect_app_version()
        self.backend = TidalBackend()
        self._cache_root = os.path.expanduser("~/.cache/hiresti")
        self._account_scope = "guest"
        self.settings_file = os.path.join(self._cache_root, "settings.json")
        self.settings = load_settings(self.settings_file)
        # Guard against corrupted/extreme sync offset values.
        try:
            raw_off = int(self.settings.get("viz_sync_offset_ms", 0) or 0)
        except Exception:
            raw_off = 0
        if abs(raw_off) > 200:
            self.settings["viz_sync_offset_ms"] = 0
        raw_map = self.settings.get("viz_sync_device_offsets", {})
        if isinstance(raw_map, dict):
            clean_map = {}
            for k, v in raw_map.items():
                if isinstance(k, str) and isinstance(v, int) and abs(v) <= 200:
                    clean_map[k] = v
            self.settings["viz_sync_device_offsets"] = clean_map
        else:
            self.settings["viz_sync_device_offsets"] = {}

        self.play_mode = self.settings.get("play_mode", self.MODE_LOOP)
        if self.play_mode not in self.MODE_ICONS:
            self.play_mode = self.MODE_LOOP
        self.shuffle_indices = [] # 用来存随机播放的顺序列表

        self.player = create_audio_engine(
            on_eos_callback=self.on_next_track,
            on_tag_callback=self.update_tech_label,
            on_spectrum_callback=self.on_spectrum_data,
            on_viz_sync_offset_update=self.on_viz_sync_offset_update,
        )
        self._viz_sync_device_key = None
        self._viz_sync_offsets = dict(self.settings.get("viz_sync_device_offsets", {}))
        self._viz_sync_last_saved_ms = int(self.settings.get("viz_sync_offset_ms", 0) or 0)
        self.player.visual_sync_offset_ms = self._viz_sync_last_saved_ms

        self.lyrics_mgr = LyricsManager()
        logger.info("LyricsManager initialized")

        saved_profile = self.settings.get("latency_profile", "Standard (100ms)")
        if saved_profile not in self.LATENCY_MAP: saved_profile = "Standard (100ms)"
        buf_ms, lat_ms = self.LATENCY_MAP[saved_profile]
        self.player.set_alsa_latency(buf_ms, lat_ms)
        self.player.visual_sync_offset_ms = int(buf_ms)
        self.settings["viz_sync_offset_ms"] = int(buf_ms)
        self._viz_sync_last_saved_ms = int(buf_ms)
        logger.info(
            "Viz sync offset applied: %dms (source=startup latency_profile=%s)",
            int(buf_ms),
            saved_profile,
        )

        self.history_mgr = HistoryManager(base_dir=self._cache_root, scope_key=self._account_scope)
        self.playlist_mgr = PlaylistManager(base_dir=self._cache_root, scope_key=self._account_scope)
        self.cache_dir = os.path.join(self._cache_root, "covers")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.audio_cache_dir = os.path.join(self._cache_root, "audio")
        os.makedirs(self.audio_cache_dir, exist_ok=True)
        self.audio_cache_tracks = int(self.settings.get("audio_cache_tracks", 20) or 0)
        self._schedule_cache_maintenance()
        
        self.current_track_list = []
        self.play_queue = []
        self.current_index = -1
        self.playing_track = None
        self.playing_track_id = None 
        self.current_playlist_id = None
        self.playlist_edit_mode = False
        self.playlist_rename_mode = False
        self.album_track_source = []
        self.album_sort_field = None
        self.album_sort_asc = True
        self.album_sort_buttons = {}
        self.playlist_sort_field = None
        self.playlist_sort_asc = True
        
        self.window_created = False
        self.is_programmatic_update = False
        self.current_device_list = []
        self.current_device_name = self.settings.get("device", "Default Output")
        self.search_track_data = []
        self.search_history = list(self.settings.get("search_history", []))
        self.nav_history = []
        self.ignore_device_change = False
        self._search_request_id = 0
        self._search_debounce_source = 0
        self._liked_tracks_request_id = 0
        self._play_request_id = 0
        self._settings_save_source = 0
        self._playing_pulse_source = 0
        self._playing_pulse_on = False
        self._home_sections_cache = None
        self.stream_prefetch_cache = {}
        self._init_ui_refs()
        # Mini mode state must be initialized at startup.
        self.is_mini_mode = False
        self.saved_width = ui_config.WINDOW_WIDTH
        self.saved_height = ui_config.WINDOW_HEIGHT

    def _detect_app_version(self):
        env_ver = str(os.environ.get("HIRESTI_VERSION", "")).strip()
        if env_ver:
            return env_ver
        try:
            root = os.path.dirname(os.path.abspath(__file__))
            ver_file = os.path.join(root, "version.txt")
            if os.path.exists(ver_file):
                with open(ver_file, "r", encoding="utf-8") as f:
                    version = str(f.read()).strip()
                    if version:
                        return version
            changelog = os.path.join(root, "CHANGELOG.md")
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

    def on_about_clicked(self, _btn=None):
        info_lines = [
            "A desktop TIDAL client focused on audio quality and visual experience.",
            f"Python: {platform.python_version()}",
        ]
        about = Adw.AboutWindow(
            transient_for=getattr(self, "win", None),
            modal=True,
            application_name="HiresTI",
            application_icon="hiresti",
            version=str(getattr(self, "app_version", "dev")),
            developers=["Yelanxin"],
            website="https://github.com/yelanxin/hiresTI",
            issue_url="https://github.com/yelanxin/hiresTI/issues",
            license_type=Gtk.License.GPL_3_0,
            comments="\n".join(info_lines),
        )
        about.present()

    def do_shutdown(self):
        logger.info("Shutting down application...")
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

    def save_settings(self):
        try:
            persist_settings(self.settings_file, self.settings)
        except Exception as e:
            logger.warning("Failed to save settings to %s: %s", self.settings_file, e)

    def schedule_save_settings(self, delay_ms=250):
        pending = getattr(self, "_settings_save_source", 0)
        if pending:
            GLib.source_remove(pending)
            self._settings_save_source = 0

        def _flush():
            self._settings_save_source = 0
            self.save_settings()
            return False

        self._settings_save_source = GLib.timeout_add(delay_ms, _flush)

    def _remember_last_nav(self, nav_id):
        if not nav_id:
            return
        self.settings["last_nav"] = nav_id
        self.settings["last_view"] = "grid_view"
        self.schedule_save_settings()

    def _remember_last_view(self, view_name):
        if not view_name:
            return
        self.settings["last_view"] = view_name
        self.schedule_save_settings()

    def _save_search_history(self):
        self.settings["search_history"] = list(self.search_history)[:10]
        self.schedule_save_settings()

    def _restore_runtime_state(self):
        saved_volume = self.settings.get("volume", 80)
        if self.vol_scale is not None:
            self.vol_scale.set_value(saved_volume)
        if self.player is not None:
            self.player.set_volume(saved_volume / 100.0)

        if self.mode_btn is not None:
            self.mode_btn.set_icon_name(self.MODE_ICONS.get(self.play_mode, "hiresti-mode-loop-symbolic"))
            self.mode_btn.set_tooltip_text(self.MODE_TOOLTIPS.get(self.play_mode, "Loop All (Album/Playlist)"))

        saved_paned = self.settings.get("paned_position", 0)
        if isinstance(saved_paned, int) and saved_paned > 0 and self.paned is not None:
            self.paned.set_position(saved_paned)

        self._apply_viz_backend_policy_by_index(self.settings.get("viz_backend_policy", 0), update_dropdown=True)
        self._apply_viz_bars_by_count(self.settings.get("viz_bar_count", 32), update_dropdown=True)
        self._apply_viz_profile_by_index(self.settings.get("viz_profile", 1), update_dropdown=True)
        self._apply_viz_effect_by_index(self.settings.get("viz_effect", 3), update_dropdown=True)
        self._apply_spectrum_theme_by_index(self.settings.get("spectrum_theme", 0), update_dropdown=True)
        self._apply_lyrics_font_preset_by_index(self.settings.get("lyrics_font_preset", 1), update_dropdown=True)
        self._apply_lyrics_motion_by_index(self.settings.get("lyrics_bg_motion", 1), update_dropdown=True)
        self._apply_lyrics_offset_ms(self.settings.get("lyrics_user_offset_ms", 0))

    def _viz_sync_key(self, driver, device_id=None, device_name=None):
        drv = str(driver or "Auto").strip() or "Auto"
        dev = str(device_id or "").strip()
        if not dev:
            dev = str(device_name or self.settings.get("device") or "default").strip() or "default"
        return f"{drv}|{dev}"

    def _get_viz_offset_from_latency_profile(self):
        profile = str(self.settings.get("latency_profile", "Standard (100ms)") or "").strip()
        if profile in self.LATENCY_MAP:
            buf_ms, _lat_ms = self.LATENCY_MAP[profile]
            return int(max(0, min(500, buf_ms)))
        return 100

    def _apply_viz_sync_offset_for_device(self, driver, device_id=None, device_name=None):
        key = self._viz_sync_key(driver, device_id=device_id, device_name=device_name)
        self._viz_sync_device_key = key
        profile_off = self._get_viz_offset_from_latency_profile()
        self.player.visual_sync_offset_ms = profile_off
        self.settings["viz_sync_offset_ms"] = profile_off
        if hasattr(self.player, "visual_sync_auto_offset_ms"):
            self.player.visual_sync_auto_offset_ms = 0.0
        self._viz_sync_last_saved_ms = profile_off
        logger.info(
            "Viz sync offset applied: %dms (source=output-change key=%s)",
            int(profile_off),
            key,
        )

    def on_viz_sync_offset_update(self, learned_offset_ms):
        # Disabled: runtime auto-learning should not persist to settings.
        return False

    def _apply_viz_bars_by_count(self, count, update_dropdown=False):
        try:
            c = int(count)
        except Exception:
            c = 64
        if c not in self.VIZ_BAR_OPTIONS:
            c = 64
        if self.viz is not None:
            self.viz.set_num_bars(c)
        self.settings["viz_bar_count"] = c
        if update_dropdown and self.viz_bars_dd is not None:
            self.viz_bars_dd.set_selected(self.VIZ_BAR_OPTIONS.index(c))

    def _drop_down_names(self, dd):
        names = []
        if dd is None:
            return names
        model = dd.get_model()
        if model is None:
            return names
        n = model.get_n_items()
        for i in range(n):
            try:
                names.append(model.get_string(i))
            except Exception:
                pass
        return names

    def _selected_name_from_dropdown(self, dd):
        names = self._drop_down_names(dd)
        if not names:
            return None
        idx = int(dd.get_selected())
        if idx < 0 or idx >= len(names):
            return None
        return names[idx]

    def _build_visualizer_for_backend(self, backend_key):
        order = []
        if backend_key == "cairo":
            order = [("cairo", SpectrumVisualizer), ("gl", SpectrumVisualizerGLArea), ("gpu", SpectrumVisualizerGPU)]
        elif backend_key == "gpu":
            order = [("gpu", SpectrumVisualizerGPU), ("gl", SpectrumVisualizerGLArea), ("cairo", SpectrumVisualizer)]
        else:
            order = [("gl", SpectrumVisualizerGLArea), ("gpu", SpectrumVisualizerGPU), ("cairo", SpectrumVisualizer)]
        for key, ctor in order:
            try:
                return ctor(), key
            except Exception as e:
                logger.warning("Visualizer backend %s unavailable, falling back: %s", key, e)
        raise RuntimeError("No visualizer backend available")

    def _resolve_viz_backend_key(self, effect_name=None):
        if not effect_name:
            effect_name = self._selected_name_from_dropdown(self.viz_effect_dd)
        # Force Bars to GL shader path to avoid Cairo/pixman composition overhead.
        # If GL is unavailable, backend rebuild will gracefully fall back.
        if effect_name == "Bars":
            return "gl"
        try:
            idx = int(self.settings.get("viz_backend_policy", 0))
        except Exception:
            idx = 0
        idx = max(0, min(len(self.VIZ_BACKEND_POLICIES) - 1, idx))
        policy = self.VIZ_BACKEND_POLICIES[idx]
        if policy.startswith("Quality"):
            return "cairo"
        if policy.startswith("Performance"):
            return "gl"
        return "gl"

    def _sync_viz_dropdown_models(self, theme_name=None, effect_name=None, profile_name=None):
        self._viz_ui_syncing = True
        try:
            if self.viz_theme_dd is not None:
                t_names = self.viz.get_theme_names() or []
                self.viz_theme_dd.set_model(Gtk.StringList.new(t_names))
                if t_names:
                    idx = t_names.index(theme_name) if theme_name in t_names else 0
                    self.viz_theme_dd.set_selected(idx)
            if self.viz_effect_dd is not None:
                e_names = self.viz.get_effect_names() or []
                self.viz_effect_dd.set_model(Gtk.StringList.new(e_names))
                if e_names:
                    idx = e_names.index(effect_name) if effect_name in e_names else 0
                    self.viz_effect_dd.set_selected(idx)
            if self.viz_profile_dd is not None:
                p_names = self.viz.get_profile_names() or []
                self.viz_profile_dd.set_model(Gtk.StringList.new(p_names))
                if p_names:
                    idx = p_names.index(profile_name) if profile_name in p_names else min(1, len(p_names) - 1)
                    self.viz_profile_dd.set_selected(idx)
        finally:
            self._viz_ui_syncing = False

    def _rebuild_visualizer_backend(self, backend_key, effect_name=None):
        if self.viz_stack is None:
            return
        if effect_name is None:
            effect_name = self._selected_name_from_dropdown(self.viz_effect_dd)
        theme_name = self._selected_name_from_dropdown(self.viz_theme_dd)
        profile_name = self._selected_name_from_dropdown(self.viz_profile_dd)
        bar_count = int(self.settings.get("viz_bar_count", 32) or 32)
        vis_name = self.viz_stack.get_visible_child_name() if self.viz_stack is not None else "spectrum"

        new_viz, actual_key = self._build_visualizer_for_backend(backend_key)
        new_viz.set_num_bars(bar_count)
        new_viz.set_valign(Gtk.Align.FILL)
        if theme_name and theme_name in (new_viz.get_theme_names() or []):
            new_viz.set_theme(theme_name)
        if profile_name and profile_name in (new_viz.get_profile_names() or []):
            new_viz.set_profile(profile_name)
        if effect_name and effect_name in (new_viz.get_effect_names() or []):
            new_viz.set_effect(effect_name)

        if self.viz is not None:
            try:
                self.viz_stack.remove(self.viz)
            except Exception:
                pass
        self.viz = new_viz
        self._viz_backend_key = actual_key
        self.viz_stack.add_titled(self.viz, "spectrum", "Spectrum")
        if vis_name:
            self.viz_stack.set_visible_child_name(vis_name)
        self._sync_viz_tab_runtime_state()
        self._sync_viz_dropdown_models(theme_name=theme_name, effect_name=effect_name, profile_name=profile_name)
        logger.info("Visualizer backend switched: %s (requested=%s effect=%s)", actual_key, backend_key, effect_name)

    def _apply_viz_backend_policy_by_index(self, idx, update_dropdown=False):
        if not isinstance(idx, int) or idx < 0 or idx >= len(self.VIZ_BACKEND_POLICIES):
            idx = 0
        self.settings["viz_backend_policy"] = idx
        if update_dropdown and self.viz_policy_dd is not None:
            self._viz_ui_syncing = True
            try:
                self.viz_policy_dd.set_selected(idx)
            finally:
                self._viz_ui_syncing = False
        effect_name = self._selected_name_from_dropdown(self.viz_effect_dd)
        desired = self._resolve_viz_backend_key(effect_name)
        if desired != self._viz_backend_key:
            self._rebuild_visualizer_backend(desired, effect_name=effect_name)

    def on_viz_bars_changed(self, dd, _param):
        if self._viz_ui_syncing:
            return
        idx = dd.get_selected()
        if idx < 0 or idx >= len(self.VIZ_BAR_OPTIONS):
            return
        self._apply_viz_bars_by_count(self.VIZ_BAR_OPTIONS[idx], update_dropdown=False)
        self.schedule_save_settings()

    def _apply_spectrum_theme_by_index(self, idx, update_dropdown=False):
        if self.viz is None:
            return
        names = self.viz.get_theme_names()
        if not names:
            return
        if not isinstance(idx, int) or idx < 0 or idx >= len(names):
            idx = 0
        self.viz.set_theme(names[idx])
        self.settings["spectrum_theme"] = idx
        if update_dropdown and self.viz_theme_dd is not None:
            self.viz_theme_dd.set_selected(idx)

    def _apply_viz_effect_by_index(self, idx, update_dropdown=False):
        if self.viz is None:
            return
        names = self.viz.get_effect_names()
        if not names:
            return
        if not isinstance(idx, int):
            idx = 0
        effect_name = None
        dd_names = self._drop_down_names(self.viz_effect_dd)
        if 0 <= idx < len(dd_names):
            effect_name = dd_names[idx]
        if not effect_name:
            if idx < 0 or idx >= len(names):
                idx = 0
            effect_name = names[idx]
        desired = self._resolve_viz_backend_key(effect_name)
        if desired != self._viz_backend_key:
            self._rebuild_visualizer_backend(desired, effect_name=effect_name)
            names = self.viz.get_effect_names() or []
        if effect_name not in names:
            effect_name = names[0] if names else None
        if effect_name:
            self.viz.set_effect(effect_name)
            eff_idx = names.index(effect_name)
        else:
            eff_idx = 0
        self.settings["viz_effect"] = eff_idx
        if update_dropdown and self.viz_effect_dd is not None:
            self._viz_ui_syncing = True
            try:
                self.viz_effect_dd.set_selected(eff_idx)
            finally:
                self._viz_ui_syncing = False

    def on_viz_effect_changed(self, dd, _param):
        if self._viz_ui_syncing:
            return
        idx = dd.get_selected()
        if self._viz_effect_apply_source:
            try:
                GLib.source_remove(self._viz_effect_apply_source)
            except Exception:
                pass
            self._viz_effect_apply_source = None

        def _apply_effect_later():
            self._viz_effect_apply_source = None
            if self._viz_ui_syncing:
                return False
            logger.debug("Applying visualizer effect (deferred): idx=%s", idx)
            self._apply_viz_effect_by_index(idx, update_dropdown=False)
            self.schedule_save_settings()
            return False

        # Avoid mutating dropdown model/stack synchronously in GTK activate callback.
        self._viz_effect_apply_source = GLib.idle_add(_apply_effect_later)

    def _apply_viz_profile_by_index(self, idx, update_dropdown=False):
        if self.viz is None:
            return
        names = self.viz.get_profile_names()
        if not names:
            return
        if not isinstance(idx, int) or idx < 0 or idx >= len(names):
            idx = 1 if len(names) > 1 else 0
        self.viz.set_profile(names[idx])
        self.settings["viz_profile"] = idx
        if update_dropdown and self.viz_profile_dd is not None:
            self.viz_profile_dd.set_selected(idx)

    def on_viz_profile_changed(self, dd, _param):
        if self._viz_ui_syncing:
            return
        idx = dd.get_selected()
        if self._viz_profile_apply_source:
            try:
                GLib.source_remove(self._viz_profile_apply_source)
            except Exception:
                pass
            self._viz_profile_apply_source = None

        def _apply_profile_later():
            self._viz_profile_apply_source = None
            if self._viz_ui_syncing:
                return False
            logger.debug("Applying visualizer profile (deferred): idx=%s", idx)
            self._apply_viz_profile_by_index(idx, update_dropdown=False)
            self.schedule_save_settings()
            return False

        self._viz_profile_apply_source = GLib.idle_add(_apply_profile_later)

    def on_spectrum_theme_changed(self, dd, _param):
        if self._viz_ui_syncing:
            return
        idx = dd.get_selected()
        if self._viz_theme_apply_source:
            try:
                GLib.source_remove(self._viz_theme_apply_source)
            except Exception:
                pass
            self._viz_theme_apply_source = None

        def _apply_theme_later():
            self._viz_theme_apply_source = None
            if self._viz_ui_syncing:
                return False
            logger.debug("Applying visualizer theme (deferred): idx=%s", idx)
            self._apply_spectrum_theme_by_index(idx, update_dropdown=False)
            self.schedule_save_settings()
            return False

        self._viz_theme_apply_source = GLib.idle_add(_apply_theme_later)

    def on_viz_backend_policy_changed(self, dd, _param):
        if self._viz_ui_syncing:
            return
        idx = dd.get_selected()
        if self._viz_policy_apply_source:
            try:
                GLib.source_remove(self._viz_policy_apply_source)
            except Exception:
                pass
            self._viz_policy_apply_source = None

        def _apply_policy_later():
            self._viz_policy_apply_source = None
            if self._viz_ui_syncing:
                return False
            logger.debug("Applying visualizer policy (deferred): idx=%s", idx)
            self._apply_viz_backend_policy_by_index(idx, update_dropdown=False)
            self.schedule_save_settings()
            return False

        self._viz_policy_apply_source = GLib.idle_add(_apply_policy_later)

    def _apply_lyrics_font_preset_by_index(self, idx, update_dropdown=False):
        if self.lyrics_vbox is None:
            return
        if not isinstance(idx, int) or idx < 0 or idx >= len(self.LYRICS_FONT_PRESETS):
            idx = 1
        for cls in ("lyrics-font-live", "lyrics-font-studio", "lyrics-font-compact"):
            self.lyrics_vbox.remove_css_class(cls)
        class_map = {0: "lyrics-font-live", 1: "lyrics-font-studio", 2: "lyrics-font-compact"}
        self.lyrics_vbox.add_css_class(class_map.get(idx, "lyrics-font-studio"))
        self.settings["lyrics_font_preset"] = idx
        if update_dropdown and self.lyrics_font_dd is not None:
            self.lyrics_font_dd.set_selected(idx)

    def on_lyrics_font_preset_changed(self, dd, _param):
        idx = dd.get_selected()
        self._apply_lyrics_font_preset_by_index(idx, update_dropdown=False)
        self.schedule_save_settings()

    def _apply_lyrics_motion_by_index(self, idx, update_dropdown=False):
        if self.bg_viz is None:
            return
        names = self.bg_viz.get_motion_mode_names()
        if not isinstance(idx, int) or idx < 0 or idx >= len(names):
            idx = 1
        self.bg_viz.set_motion_mode(names[idx])
        self.settings["lyrics_bg_motion"] = idx
        if update_dropdown and self.lyrics_motion_dd is not None:
            self.lyrics_motion_dd.set_selected(idx)

    def on_lyrics_motion_changed(self, dd, _param):
        idx = dd.get_selected()
        self._apply_lyrics_motion_by_index(idx, update_dropdown=False)
        self._sync_spectrum_stream_state()
        self.schedule_save_settings()

    def _apply_lyrics_offset_ms(self, offset_ms):
        try:
            val = int(offset_ms)
        except Exception:
            val = 0
        val = max(-2000, min(2000, val))
        self.lyrics_user_offset_ms = val
        self.settings["lyrics_user_offset_ms"] = val
        if self.lyrics_offset_label is not None:
            sign = "+" if val > 0 else ""
            self.lyrics_offset_label.set_text(f"{sign}{val}ms")

    def on_lyrics_offset_step(self, _btn, delta_ms):
        self._apply_lyrics_offset_ms(getattr(self, "lyrics_user_offset_ms", 0) + int(delta_ms))
        self.schedule_save_settings()

    def on_viz_page_changed(self, stack, _param):
        if self.viz_theme_dd is None:
            return
        page = stack.get_visible_child_name() if stack is not None else ""
        self._viz_current_page = page or "spectrum"
        is_spectrum = page == "spectrum"
        is_lyrics = page == "lyrics"
        self.viz_theme_dd.set_visible(is_spectrum)
        if self.viz_bars_dd is not None:
            self.viz_bars_dd.set_visible(is_spectrum)
        if self.viz_policy_dd is not None:
            self.viz_policy_dd.set_visible(is_spectrum)
        if self.viz_profile_dd is not None:
            self.viz_profile_dd.set_visible(is_spectrum)
        if self.viz_effect_dd is not None:
            self.viz_effect_dd.set_visible(is_spectrum)
        if self.lyrics_font_label is not None:
            self.lyrics_font_label.set_visible(is_lyrics)
        if self.lyrics_font_dd is not None:
            self.lyrics_font_dd.set_visible(is_lyrics)
        if self.lyrics_motion_dd is not None:
            self.lyrics_motion_dd.set_visible(is_lyrics)
        if hasattr(self, "lyrics_ctrl_box") and self.lyrics_ctrl_box is not None:
            self.lyrics_ctrl_box.set_visible(is_lyrics)
        if hasattr(self, "lyrics_offset_box") and self.lyrics_offset_box is not None:
            self.lyrics_offset_box.set_visible(is_lyrics)
        self._sync_viz_tab_runtime_state()
        self._sync_spectrum_stream_state()

    def _sync_viz_tab_runtime_state(self):
        revealer = getattr(self, "viz_revealer", None)
        is_open = bool(revealer is not None and revealer.get_reveal_child())
        page = str(getattr(self, "_viz_current_page", "spectrum") or "spectrum")
        spectrum_active = bool(is_open and page == "spectrum")
        lyrics_active = bool(is_open and page == "lyrics")
        if getattr(self, "viz", None) is not None and hasattr(self.viz, "set_active"):
            try:
                self.viz.set_active(spectrum_active)
            except Exception:
                pass
        if getattr(self, "bg_viz", None) is not None and hasattr(self.bg_viz, "set_active"):
            try:
                self.bg_viz.set_active(lyrics_active)
            except Exception:
                pass

    def _should_enable_spectrum_stream(self):
        revealer = getattr(self, "viz_revealer", None)
        if revealer is None or (not revealer.get_reveal_child()):
            return False
        page = str(getattr(self, "_viz_current_page", "spectrum") or "spectrum")
        if page == "spectrum":
            return True
        # Lyrics tab: Static background does not need live spectrum data.
        if page == "lyrics":
            motion_idx = int(self.settings.get("lyrics_bg_motion", 1) or 0)
            if motion_idx == 0:
                return False
            return True
        return False

    def _sync_spectrum_stream_state(self):
        self._sync_viz_tab_runtime_state()
        if self.player is not None and hasattr(self.player, "set_spectrum_enabled"):
            self.player.set_spectrum_enabled(self._should_enable_spectrum_stream())

    def _restore_last_view(self):
        nav_id = self.settings.get("last_nav", "home")
        view = self.settings.get("last_view", "grid_view")

        if view == "settings":
            self.on_settings_clicked(getattr(self, "tools_btn", None))
            return

        if view == "search_view":
            self.right_stack.set_visible_child_name("search_view")
            self.back_btn.set_sensitive(True)
            self.nav_list.select_row(None)
            self.grid_title_label.set_text("Search")
            return

        target = None
        child = self.nav_list.get_first_child()
        while child:
            if hasattr(child, "nav_id") and child.nav_id == nav_id:
                target = child
                break
            child = child.get_next_sibling()
        if target is None:
            target = self.nav_list.get_first_child()
        if target is not None:
            self.nav_list.select_row(target)
            self.on_nav_selected(self.nav_list, target)

    def do_activate(self):
        if self.window_created: 
            self.win.present()
            return

        display = Gdk.Display.get_default()
        if display is None:
            logger.error("No graphical display detected; cannot start GTK UI.")
            self.quit()
            return

        icon_theme = Gtk.IconTheme.get_for_display(display)
        icons_path = os.path.join(os.path.dirname(__file__), "icons")
        if os.path.exists(icons_path):
            icon_theme.add_search_path(icons_path)

        provider = Gtk.CssProvider()
        logo_svg = os.path.join(os.path.dirname(__file__), "icons", "hicolor", "scalable", "apps", "hiresti.svg")
        css_data = ui_config.CSS_DATA.replace("__HIRESTI_LOGO_SVG__", logo_svg.replace("\\", "/"))
        provider.load_from_data(css_data.encode())
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.win = Adw.ApplicationWindow(application=self, title="hiresTI Desktop", default_width=ui_config.WINDOW_WIDTH, default_height=ui_config.WINDOW_HEIGHT)
        self.window_created = True
        self.win.connect("close-request", self.on_window_close_request)
        
        self.window_handle = Gtk.WindowHandle()
        self.win.set_content(self.window_handle)
        
        self.main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.window_handle.set_child(self.main_vbox)

        self._build_header(self.main_vbox)
        self._build_body(self.main_vbox)
        self._build_player_bar(self.main_vbox)
        self._setup_theme_watch()
        self._restore_runtime_state()
        self._set_login_view_pending()

        # === 恢复设置逻辑 ===
        is_bp = self.settings.get("bit_perfect", False)
        is_ex = self.settings.get("exclusive_lock", False)
        
        # 1. 应用 Bit-Perfect 和 独占状态
        self.player.toggle_bit_perfect(is_bp, exclusive_lock=is_ex)
        if is_bp:
            if self.bp_label is not None: self.bp_label.set_visible(True)
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

        self._restore_session_async()

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.win.add_controller(key_controller)

        self.win.present()
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
        GLib.idle_add(self._restore_paned_position_after_layout)
        GLib.idle_add(lambda: (self._schedule_viz_handle_realign(), False)[1])

        self._schedule_update_ui_loop(40)
        self._schedule_output_status_loop(1000)
        GLib.timeout_add(260, self._prewarm_gl_visualizer_once)
        GLib.timeout_add(80, self._start_spectrum_stream_prewarm)
        self._init_tray_icon()

    def _prewarm_gl_visualizer_once(self):
        # Warm up GLArea realize/shader path once without visible drawer motion.
        if bool(getattr(self, "_viz_gl_prewarm_done", False)):
            return False
        if str(getattr(self, "_viz_backend_key", "")) != "gl":
            return False
        revealer = getattr(self, "viz_revealer", None)
        root = getattr(self, "viz_root", None)
        handle = getattr(self, "viz_handle_box", None)
        if revealer is None or root is None:
            return False
        if bool(revealer.get_reveal_child()):
            return False

        self._viz_gl_prewarm_done = True
        try:
            old_dur = int(revealer.get_transition_duration() or 0)
        except Exception:
            old_dur = 0
        try:
            old_opacity = float(root.get_opacity() or 1.0)
        except Exception:
            old_opacity = 1.0
        old_handle_visible = bool(handle.get_visible()) if handle is not None else True

        try:
            revealer.set_transition_duration(0)
            root.set_opacity(0.0)
            if handle is not None:
                handle.set_visible(False)
            revealer.set_reveal_child(True)
        except Exception:
            # Best-effort only; never block startup.
            try:
                revealer.set_transition_duration(old_dur)
            except Exception:
                pass
            if handle is not None:
                handle.set_visible(old_handle_visible)
            root.set_opacity(old_opacity)
            return False

        def _finish():
            try:
                revealer.set_reveal_child(False)
                root.set_opacity(old_opacity)
                revealer.set_transition_duration(old_dur)
                if handle is not None:
                    handle.set_visible(old_handle_visible)
            except Exception:
                pass
            return False

        GLib.timeout_add(70, _finish)
        return False

    def _start_spectrum_stream_prewarm(self):
        # Warm up spectrum pipeline once in background to avoid first-open hitch.
        if self.player is None or (not hasattr(self.player, "set_spectrum_enabled")):
            return False
        revealer = getattr(self, "viz_revealer", None)
        if revealer is not None and bool(revealer.get_reveal_child()):
            return False
        try:
            self.player.set_spectrum_enabled(True)
        except Exception:
            return False

        if self._viz_stream_prewarm_source:
            GLib.source_remove(self._viz_stream_prewarm_source)
            self._viz_stream_prewarm_source = 0

        def _finish():
            self._viz_stream_prewarm_source = 0
            self._sync_spectrum_stream_state()
            return False

        # Keep warm briefly, then restore to intended state.
        self._viz_stream_prewarm_source = GLib.timeout_add(900, _finish)
        return False

    def _get_tray_icon_path(self):
        candidates = [
            os.path.join(os.path.dirname(__file__), "icons", "hicolor", "64x64", "apps", "hiresti.png"),
            os.path.join(os.path.dirname(__file__), "icons", "hicolor", "128x128", "apps", "hiresti.png"),
            os.path.join(os.path.dirname(__file__), "icons", "hicolor", "32x32", "apps", "hiresti.png"),
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None

    def _show_from_tray(self, _icon=None, _item=None):
        def _show():
            if self.win is not None:
                self.win.present()
            return False
        GLib.idle_add(_show)

    def _quit_from_tray(self, _icon=None, _item=None):
        def _quit():
            self._allow_window_close = True
            self.quit()
            return False
        GLib.idle_add(_quit)

    def _init_tray_icon(self):
        if self._tray_ready:
            return
        if pystray is None or Image is None:
            logger.info("pystray is unavailable. Window will still hide to background on close.")
            return
        icon_path = self._get_tray_icon_path()
        if not icon_path:
            logger.info("Tray icon image not found. Skipping tray setup.")
            return
        try:
            image = Image.open(icon_path)
            menu = pystray.Menu(
                pystray.MenuItem("Show", self._show_from_tray, default=True),
                pystray.MenuItem("Quit", self._quit_from_tray),
            )
            self._tray_icon = pystray.Icon("hiresti", image, "HiresTI", menu)
            self._tray_icon.run_detached()
            self._tray_ready = True
        except Exception as e:
            logger.warning("Failed to initialize tray icon: %s", e)
            self._tray_icon = None
            self._tray_ready = False

    def _stop_tray_icon(self):
        if self._tray_icon is None:
            return
        try:
            self._tray_icon.stop()
        except Exception:
            pass
        self._tray_icon = None
        self._tray_ready = False

    def on_window_close_request(self, _win):
        if self._allow_window_close:
            return False
        try:
            self._init_tray_icon()
            if not self._tray_ready:
                # No tray support (e.g. GNOME without indicator extension): close normally.
                return False
            if self.win is not None:
                self.win.hide()
            logger.info("Window hidden to background. Playback continues.")
        except Exception as e:
            logger.warning("Failed to hide window to background: %s", e)
            return False
        return True

    def _restore_session_async(self):
        def task():
            ok = self.backend.try_load_session()
            if ok:
                GLib.idle_add(self.on_login_success)
            else:
                GLib.idle_add(self._toggle_login_view, False)

        Thread(target=task, daemon=True).start()

    def _setup_theme_watch(self):
        """
        Keep spectrum/lyrics panel background in sync with system light/dark mode.
        """
        self.style_manager = Adw.StyleManager.get_default()
        self.style_manager.set_color_scheme(Adw.ColorScheme.DEFAULT)
        self.style_manager.connect("notify::dark", lambda *_: self._apply_viz_panel_theme())
        self._apply_viz_panel_theme()
        self._apply_app_theme_classes()

    def _apply_viz_panel_theme(self):
        if self.viz_stack_box is None:
            return
        is_dark = self.style_manager.get_dark()
        self.viz_stack_box.remove_css_class("viz-panel-dark")
        self.viz_stack_box.remove_css_class("viz-panel-light")
        if getattr(self, "viz_handle_box", None) is not None:
            self.viz_handle_box.remove_css_class("viz-handle-dark")
            self.viz_handle_box.remove_css_class("viz-handle-light")
        if getattr(self, "queue_anchor", None) is not None:
            self.queue_anchor.remove_css_class("queue-handle-dark")
            self.queue_anchor.remove_css_class("queue-handle-light")
        if getattr(self, "viz_root", None) is not None:
            self.viz_root.remove_css_class("viz-surface-dark")
            self.viz_root.remove_css_class("viz-surface-light")
        if is_dark:
            self.viz_stack_box.add_css_class("viz-panel-dark")
            if getattr(self, "viz_handle_box", None) is not None:
                self.viz_handle_box.add_css_class("viz-handle-dark")
            if getattr(self, "queue_anchor", None) is not None:
                self.queue_anchor.add_css_class("queue-handle-dark")
            if getattr(self, "viz_root", None) is not None:
                self.viz_root.add_css_class("viz-surface-dark")
        else:
            self.viz_stack_box.add_css_class("viz-panel-light")
            if getattr(self, "viz_handle_box", None) is not None:
                self.viz_handle_box.add_css_class("viz-handle-light")
            if getattr(self, "queue_anchor", None) is not None:
                self.queue_anchor.add_css_class("queue-handle-light")
            if getattr(self, "viz_root", None) is not None:
                self.viz_root.add_css_class("viz-surface-light")
        if self.lyrics_vbox is not None:
            self.lyrics_vbox.remove_css_class("lyrics-theme-dark")
            self.lyrics_vbox.remove_css_class("lyrics-theme-light")
            self.lyrics_vbox.add_css_class("lyrics-theme-dark" if is_dark else "lyrics-theme-light")
        if self.bg_viz is not None:
            self.bg_viz.set_theme_mode(is_dark)

    def _apply_app_theme_classes(self):
        root = getattr(self, "main_vbox", None)
        if root is None:
            return
        root.remove_css_class("app-theme-dark")
        root.remove_css_class("app-theme-fresh")
        root.remove_css_class("app-theme-sunset")
        root.remove_css_class("app-theme-mint")
        root.remove_css_class("app-theme-retro")

    def _clear_initial_search_focus(self):
        # Keep shortcuts available until user explicitly clicks/focuses the search box.
        if getattr(self, "win", None) is not None:
            try:
                self.win.set_focus(None)
            except Exception:
                pass
        return False

    def _build_header(self, container):
        ui_builders.build_header(self, container)

    def _build_volume_popover(self):
        pop = Gtk.Popover()
        # 创建垂直布局容器
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)

        # 垂直滑块
        self.vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 100, 5)
        self.vol_scale.set_inverted(True) # 让 100 在上面，0 在下面，符合直觉
        self.vol_scale.set_size_request(-1, 150) # 设置高度
        self.vol_scale.set_value(80) # 默认值

        # 绑定事件：调整音量 + 动态更新图标
        self.vol_scale.connect("value-changed", self.on_volume_changed_ui)

        vbox.append(self.vol_scale)
        pop.set_child(vbox)
        return pop

    def on_key_pressed(self, controller, keyval, keycode, state):
        """处理键盘快捷键"""
        # 1. 空格键: 播放/暂停
        if keyval == Gdk.KEY_space:
            # 如果焦点不在搜索框里，才触发播放/暂停
            if not self.search_entry.has_focus():
                self.on_play_pause(self.play_btn)
                return True

        # 2. Ctrl + Right: 下一曲
        if (state & Gdk.ModifierType.CONTROL_MASK) and keyval == Gdk.KEY_Right:
            self.on_next_track()
            return True

        # 3. Ctrl + Left: 上一曲
        if (state & Gdk.ModifierType.CONTROL_MASK) and keyval == Gdk.KEY_Left:
            self.on_prev_track()
            return True

        # 4. Ctrl + F: 聚焦搜索框
        if (state & Gdk.ModifierType.CONTROL_MASK) and keyval == Gdk.KEY_f:
            self.search_entry.grab_focus()
            return True
        if keyval == Gdk.KEY_q or keyval == Gdk.KEY_Q:
            queue_open = bool(
                getattr(self, "queue_revealer", None) is not None
                and self.queue_revealer.get_reveal_child()
            )
            # Allow Q to always close an opened queue; only block opening while typing in search.
            if queue_open or not self.search_entry.has_focus():
                self.toggle_queue_drawer()
                return True
        if keyval == Gdk.KEY_Escape and getattr(self, "queue_revealer", None) is not None:
            if self.queue_revealer.get_reveal_child():
                self.close_queue_drawer()
                return True
        # Tab: 展开/收起波形和歌词
        if keyval == Gdk.KEY_Tab and not self.search_entry.has_focus():
            self.toggle_visualizer(self.viz_btn)
            return True

        return False
    
    def on_volume_changed_ui(self, scale):
        val = scale.get_value()
        self.player.set_volume(val / 100.0)
        self.settings["volume"] = int(round(val))
        self.schedule_save_settings()

        # 根据音量大小切换图标
        icon = "hiresti-volume-high-symbolic"
        if val == 0: icon = "hiresti-volume-muted-symbolic"
        elif val < 30: icon = "hiresti-volume-low-symbolic"
        elif val < 70: icon = "hiresti-volume-medium-symbolic"

        if self.vol_btn is not None:
            self.vol_btn.set_icon_name(icon)


    def toggle_mini_mode(self, btn):
        if not hasattr(self, "is_mini_mode"):
            self.is_mini_mode = False
        if not hasattr(self, "saved_width"):
            self.saved_width = ui_config.WINDOW_WIDTH
        if not hasattr(self, "saved_height"):
            self.saved_height = ui_config.WINDOW_HEIGHT
        # 0. 隐藏抽屉
        if self.viz_revealer is not None:
            self._set_visualizer_expanded(False)
            self.settings["viz_expanded"] = False
            self.schedule_save_settings()
        self.close_queue_drawer()

        self.is_mini_mode = not self.is_mini_mode
        
        if self.is_mini_mode:
            # === 进入迷你模式 ===
            self.saved_width = self.win.get_width()
            self.saved_height = self.win.get_height()
            
            # [关键修复] 不要 remove，而是直接隐藏，防止布局崩溃导致信息消失
            self.header.set_visible(False)
            self.paned.set_visible(False) 
            
            self.bottom_bar.add_css_class("mini-state")
            self.mini_controls.set_visible(True)
            
            # 隐藏进度条和音量，仅保留歌曲信息和控制键
            if self.timeline_box is not None: self.timeline_box.set_visible(False)
            if self.vol_box is not None: self.vol_box.set_visible(False)
            if self.tech_box is not None: self.tech_box.set_visible(False)
            # Relax fixed min widths so mini mode can stay compact.
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
            
            # [调优] 进一步收窄迷你模式宽度
            self.win.set_size_request(390, 85)
            self.win.set_default_size(390, 85)
            
        else:
            # === 恢复完整模式 ===
            self.header.set_visible(True)
            self.paned.set_visible(True)
            self.mini_controls.set_visible(False)
            
            if self.timeline_box is not None: self.timeline_box.set_visible(True)
            if self.vol_box is not None: self.vol_box.set_visible(True)
            if self.tech_box is not None: self.tech_box.set_visible(True)
            # Restore default player panel sizing.
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

    def _build_user_popover(self):
        pop = Gtk.Popover()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        btn = Gtk.Button(label="Logout", css_classes=["flat", "destructive-action"])
        btn.connect("clicked", self.on_logout_clicked)
        vbox.append(btn)
        pop.set_child(vbox)
        return pop
    
    def on_tech_info_clicked(self, btn):
        win = AudioSignalPathWindow(self)
        win.present()

    def _build_body(self, container):
        ui_builders.build_body(self, container)

    def _build_grid_view(self):
        ui_views_builders.build_grid_view(self)

    def _toggle_login_view(self, logged_in):
        self._session_restore_pending = False
        ui_views_builders.toggle_login_view(self, logged_in)
        paned = getattr(self, "paned", None)
        if paned is not None:
            paned.set_visible(True)
        mini_btn = getattr(self, "mini_btn", None)
        if mini_btn is not None:
            mini_btn.set_visible(bool(logged_in))
        tools_btn = getattr(self, "tools_btn", None)
        if tools_btn is not None:
            tools_btn.set_visible(bool(logged_in))
        player_overlay = getattr(self, "player_overlay", None)
        if player_overlay is not None:
            player_overlay.set_visible(bool(logged_in))
        bottom_bar = getattr(self, "bottom_bar", None)
        if bottom_bar is not None:
            bottom_bar.set_visible(bool(logged_in))
        self._set_overlay_handles_visible(bool(logged_in))

    def _set_login_view_pending(self):
        # Startup session check in progress: avoid flashing logged-out prompt.
        self._session_restore_pending = True
        paned = getattr(self, "paned", None)
        if paned is not None:
            paned.set_visible(False)
        if hasattr(self, "login_prompt_box") and self.login_prompt_box is not None:
            self.login_prompt_box.set_visible(False)
        if hasattr(self, "alb_scroll") and self.alb_scroll is not None:
            self.alb_scroll.set_visible(False)
        if hasattr(self, "sidebar_box") and self.sidebar_box is not None:
            self.sidebar_box.set_visible(False)
        if hasattr(self, "search_entry") and self.search_entry is not None:
            self.search_entry.set_visible(False)
        mini_btn = getattr(self, "mini_btn", None)
        if mini_btn is not None:
            mini_btn.set_visible(False)
        tools_btn = getattr(self, "tools_btn", None)
        if tools_btn is not None:
            tools_btn.set_visible(False)
        player_overlay = getattr(self, "player_overlay", None)
        if player_overlay is not None:
            player_overlay.set_visible(False)
        bottom_bar = getattr(self, "bottom_bar", None)
        if bottom_bar is not None:
            bottom_bar.set_visible(False)
        self._set_overlay_handles_visible(False)

    def _set_overlay_handles_visible(self, visible):
        queue_anchor = getattr(self, "queue_anchor", None)
        if queue_anchor is not None:
            queue_anchor.set_visible(bool(visible))

        viz_handle_box = getattr(self, "viz_handle_box", None)
        if viz_handle_box is not None:
            viz_handle_box.set_visible(bool(visible))

        if visible:
            return

        # Ensure overlays are collapsed when hidden in logged-out state.
        self.close_queue_drawer()
        revealer = getattr(self, "viz_revealer", None)
        if revealer is not None:
            self._set_visualizer_expanded(False)

    def _build_tracks_view(self):
        ui_views_builders.build_tracks_view(self)

    def _build_settings_page(self):
        ui_views_builders.build_settings_page(self)

    def _build_eq_popover(self):
        pop = Gtk.Popover()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        hb = Gtk.Box(spacing=12); hb.append(Gtk.Label(label="10-Band Equalizer", css_classes=["title-4"]))
        reset = Gtk.Button(label="Reset", css_classes=["flat"]); reset.connect("clicked", lambda b: (self.player.reset_eq(), [s.set_value(0) for s in self.sliders])); hb.append(reset); vbox.append(hb)
        hbox = Gtk.Box(spacing=8); freqs = ["30", "60", "120", "240", "480", "1k", "2k", "4k", "8k", "16k"]
        self.sliders = []
        for i, f in enumerate(freqs):
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -24, 12, 1); scale.set_inverted(True); scale.set_size_request(-1, 150); scale.set_value(0); scale.add_mark(0, Gtk.PositionType.RIGHT, None)
            scale.connect("value-changed", lambda s, idx=i: self.player.set_eq_band(idx, s.get_value())); self.sliders.append(scale)
            vb.append(scale); vb.append(Gtk.Label(label=f, css_classes=["caption"])); hbox.append(vb)
        vbox.append(hbox); pop.set_child(vbox); return pop


    def _build_player_bar(self, container):
        ui_builders.build_player_bar(self, container)


    def on_spectrum_data(self, magnitudes, position_s=None):
        if not magnitudes:
            return
        trace = str(os.getenv("HIRESTI_VIZ_TRACE", "0")).strip().lower() in ("1", "true", "yes", "on")
        now_cb = time.monotonic()
        frame = magnitudes if isinstance(magnitudes, list) else list(magnitudes)
        self._last_spectrum_frame = frame
        self._last_spectrum_ts = now_cb
        if trace:
            if self._viz_trace_open_ts > 0.0 and (not self._viz_trace_first_real_logged):
                self._viz_trace_first_real_logged = True
                logger.info(
                    "VIZ TRACE first-real: delta_open=%.1fms len=%d page=%s",
                    (now_cb - self._viz_trace_open_ts) * 1000.0,
                    len(frame),
                    str(getattr(self, "_viz_current_page", "spectrum")),
                )
            if self._viz_trace_last_cb_ts > 0.0:
                gap_ms = (now_cb - self._viz_trace_last_cb_ts) * 1000.0
                if gap_ms >= 80.0:
                    logger.info("VIZ TRACE callback-gap: %.1fms", gap_ms)
            self._viz_trace_last_cb_ts = now_cb
        # Soft handoff: don't cut placeholder on first real frame.
        # Wait for a short real-frame streak and blend from current placeholder frame.
        if int(getattr(self, "_viz_placeholder_source", 0) or 0):
            self._viz_real_frame_streak = int(getattr(self, "_viz_real_frame_streak", 0) or 0) + 1
            if self._viz_real_frame_streak == 1 and self._viz_placeholder_frame:
                self._viz_seed_frame = list(self._viz_placeholder_frame)
                self._viz_warmup_until = time.monotonic() + 0.32
            if self._viz_real_frame_streak >= 4:
                self._stop_viz_placeholder()
        else:
            self._viz_real_frame_streak = 0
        revealer = self.viz_revealer
        if revealer is None or (not revealer.get_reveal_child()):
            return
        now = time.monotonic()
        if self._viz_warmup_until > now and self._viz_seed_frame:
            t = 1.0 - ((self._viz_warmup_until - now) / max(1e-6, float(self._viz_warmup_duration_s)))
            t = max(0.0, min(1.0, t))
            frame = self._blend_spectrum_frames(self._viz_seed_frame, frame, t)
        elif self._viz_warmup_until <= now:
            self._viz_seed_frame = None
            self._viz_warmup_until = 0.0
        self._apply_viz_frame(frame)

    def _apply_viz_frame(self, frame):
        if not frame:
            return
        current_page = self._viz_current_page
        if current_page == "lyrics" and self.bg_viz is not None:
            self.bg_viz.update_energy(frame)
        if current_page == "spectrum" and self.viz is not None:
            self.viz.update_data(frame)

    def _stop_viz_placeholder(self):
        src = int(getattr(self, "_viz_placeholder_source", 0) or 0)
        if src:
            GLib.source_remove(src)
            self._viz_placeholder_source = 0
        self._viz_real_frame_streak = 0

    def _start_viz_placeholder_if_needed(self):
        self._stop_viz_placeholder()
        revealer = getattr(self, "viz_revealer", None)
        if revealer is None or (not revealer.get_reveal_child()):
            return
        # If we already have a recent real frame, no need for synthetic bootstrap.
        # But when opening quickly after close, spectrum stream may still be in
        # deferred re-enable window (_viz_open_stream_source active), and
        # _last_spectrum_ts can look "fresh" while no new frames are actually
        # flowing yet. In that case we should still start placeholder to avoid
        # a visible 0.5~1s freeze.
        now = time.monotonic()
        stream_reenable_pending = bool(int(getattr(self, "_viz_open_stream_source", 0) or 0))
        if (not stream_reenable_pending) and ((now - float(getattr(self, "_last_spectrum_ts", 0.0) or 0.0)) < 0.35):
            return

        try:
            n = int(self.settings.get("viz_bar_count", 32) or 32)
        except Exception:
            n = 32
        n = max(8, min(128, n))
        if not self._viz_placeholder_frame or len(self._viz_placeholder_frame) != n:
            self._viz_placeholder_frame = [-60.0] * n
        self._viz_placeholder_phase = 0.0
        self._viz_real_frame_streak = 0
        start_ts = now
        duration_s = 2.0
        end_ts = start_ts + duration_s

        def _tick():
            rev = getattr(self, "viz_revealer", None)
            if rev is None or (not rev.get_reveal_child()):
                self._viz_placeholder_source = 0
                return False
            # Real data arrived steadily -> handoff in on_spectrum_data.
            if int(getattr(self, "_viz_real_frame_streak", 0) or 0) >= 4:
                self._viz_placeholder_source = 0
                return False
            if time.monotonic() > end_ts:
                self._viz_placeholder_source = 0
                return False

            now_tick = time.monotonic()
            life = max(0.0, min(1.0, (end_ts - now_tick) / max(1e-6, duration_s)))
            # Keep lively at beginning, then fade toward floor.
            energy_gate = pow(life, 0.80)

            self._viz_placeholder_phase += 0.24
            ph = self._viz_placeholder_phase
            frame = self._viz_placeholder_frame
            nn = len(frame)
            center1 = 0.14 + (0.06 * math.sin(ph * 0.23))
            center2 = 0.38 + (0.10 * math.sin((ph * 0.15) + 1.2))
            sigma1 = 0.10
            sigma2 = 0.16
            for i in range(nn):
                x = i / float(max(1, nn - 1))
                # Low-end dominant envelope + moving "energy hills".
                low_tilt = 0.36 * pow(max(0.0, 1.0 - x), 1.22)
                g1 = math.exp(-((x - center1) ** 2) / (2.0 * sigma1 * sigma1))
                g2 = math.exp(-((x - center2) ** 2) / (2.0 * sigma2 * sigma2))
                ripple = 0.042 * math.sin((x * 17.0) + (ph * 0.8))
                # Add jagged per-bin variation so neighbouring bars are less "too smooth".
                jagged = (0.030 * math.sin((i * 3.5) + (ph * 2.8))) + ((random.random() - 0.5) * 0.11)
                noise = (random.random() - 0.5) * 0.060

                target = 0.022 + low_tilt + (0.28 * g1) + (0.18 * g2) + ripple + jagged + noise
                # Rare transient peaks so placeholder feels alive, not static.
                if random.random() < 0.040:
                    target += 0.28 * random.random()
                target = max(0.0, min(0.82, target * energy_gate))
                # Convert to dB-like spectrum values expected by visualizer path.
                # Keep in realistic range to avoid full-screen "max level" look.
                target_db = -60.0 + (target * 48.0)  # ~[-60 dB, -12 dB]
                # Slightly faster response, and progressively pull to floor near the end.
                blend = 0.34 if life > 0.45 else 0.24
                floor_pull = (1.0 - life) * 0.22
                frame[i] = (frame[i] * (1.0 - blend)) + (target_db * blend)
                frame[i] = (frame[i] * (1.0 - floor_pull)) + (-60.0 * floor_pull)
            self._apply_viz_frame(frame)
            return True

        self._viz_placeholder_source = GLib.timeout_add(33, _tick)

    def _blend_spectrum_frames(self, seed, live, t):
        if not seed:
            return list(live or [])
        if not live:
            return list(seed)
        a = list(seed)
        b = list(live)
        n = max(len(a), len(b))
        if len(a) < n:
            a.extend([a[-1] if a else 0.0] * (n - len(a)))
        if len(b) < n:
            b.extend([b[-1] if b else 0.0] * (n - len(b)))
        k = max(0.0, min(1.0, float(t)))
        return [a[i] + ((b[i] - a[i]) * k) for i in range(n)]

    def _lock_volume_controls(self, locked):
        """
        在 Bit-Perfect / 独占模式下，强制锁定音量和 EQ 控制
        """
        
        # --- 1. 处理音量控制 (Volume) ---
        # 确保组件已创建 (防止在 UI 初始化前调用报错)
        if self.vol_scale is not None and self.vol_btn is not None:
            if locked:
                # [锁定状态]
                # 1. 物理/UI 音量强制设为 100% (Bit-Perfect 要求)
                self.vol_scale.set_value(100)
                
                # 2. 禁用按钮，防止用户点击
                self.vol_btn.set_sensitive(False)
                
                # 3. 更新提示文字
                self.vol_btn.set_tooltip_text("Volume locked in Bit-Perfect/Exclusive mode")
                
                # 4. 强制显示最大音量图标 (视觉反馈)
                self.vol_btn.set_icon_name("hiresti-volume-high-symbolic")
                
                # 5. 如果弹窗正开着，强制关掉
                if self.vol_pop is not None:
                    self.vol_pop.popdown()
            else:
                # [解锁状态]
                self.vol_btn.set_sensitive(True)
                self.vol_scale.set_sensitive(True)
                self.vol_btn.set_tooltip_text("Adjust Volume")

        # --- 2. 处理均衡器 (EQ) ---
        if self.eq_btn is not None:
            # Bit-Perfect 开启时，软件 EQ 被绕过，必须禁用入口
            self.eq_btn.set_sensitive(not locked)
            
            if locked:
                self.eq_btn.set_tooltip_text("EQ disabled in Bit-Perfect mode (Bypassed)")
                # 如果 EQ 面板正开着，强制关掉
                if self.eq_pop is not None:
                    self.eq_pop.popdown()
            else:
                self.eq_btn.set_tooltip_text("Equalizer")

    def on_login_clicked(self, btn):
        if self.backend.user:
            self.user_popover.popup()
            return
        if self._login_in_progress:
            self.show_output_notice("Login already in progress.", "warn", 2200)
            if self._login_dialog is not None:
                self._login_dialog.present()
            return
        self._show_login_method_dialog()

    def _show_login_method_dialog(self):
        self._cleanup_login_dialog()
        dialog = Gtk.Dialog(title="Choose Login Method", transient_for=self.win, modal=True)
        dialog.set_default_size(460, 250)
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        title = Gtk.Label(label="Select Login Method", xalign=0)
        title.add_css_class("title-3")
        sub = Gtk.Label(
            label="Choose one method to continue with your TIDAL account authorization.",
            xalign=0,
            wrap=True,
            css_classes=["dim-label"],
        )
        root.append(title)
        root.append(sub)

        actions = Gtk.Box(spacing=10, orientation=Gtk.Orientation.VERTICAL)

        web_btn = Gtk.Button(css_classes=["suggested-action"])
        web_row = Gtk.Box(spacing=10, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        web_row.append(Gtk.Image.new_from_icon_name("network-workgroup-symbolic"))
        web_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        web_text.append(Gtk.Label(label="Web Login", xalign=0))
        web_text.append(Gtk.Label(label="Open browser on this device to authorize", xalign=0, css_classes=["dim-label"]))
        web_row.append(web_text)
        web_btn.set_child(web_row)

        qr_btn = Gtk.Button()
        qr_row = Gtk.Box(spacing=10, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        qr_row.append(Gtk.Image.new_from_icon_name("view-grid-symbolic"))
        qr_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        qr_text.append(Gtk.Label(label="QR Login", xalign=0))
        qr_text.append(Gtk.Label(label="Scan QR with your phone to authorize", xalign=0, css_classes=["dim-label"]))
        qr_row.append(qr_text)
        qr_btn.set_child(qr_row)

        web_btn.connect("clicked", lambda _b: dialog.response(1))
        qr_btn.connect("clicked", lambda _b: dialog.response(2))
        actions.append(web_btn)
        actions.append(qr_btn)
        root.append(actions)
        dialog.set_child(root)

        def _on_response(d, resp):
            d.destroy()
            if self._login_dialog is d:
                self._login_dialog = None
            if resp == 1:
                self._start_login_flow("web")
            elif resp == 2:
                self._start_login_flow("qr")

        dialog.connect("response", _on_response)
        dialog.present()
        self._login_dialog = dialog

    def _start_login_flow(self, mode):
        mode = "qr" if str(mode).lower() == "qr" else "web"

        attempt_id = str(int(time.time() * 1000))
        self._login_in_progress = True
        self._login_attempt_id = attempt_id
        self._login_mode = mode
        self.record_diag_event(f"AUTH START id={attempt_id} mode={mode}")
        logger.info("Login start (id=%s mode=%s).", attempt_id, mode)

        try:
            oauth = self.backend.start_oauth()
            login_url = oauth.get("url", "")
            login_future = oauth.get("future")
            if not login_url or login_future is None:
                raise RuntimeError("OAuth context is incomplete")
        except Exception as e:
            self._on_login_failed(attempt_id, e)
            return

        if mode == "web":
            browser_ok = self._open_login_url(login_url, attempt_id)
            if browser_ok:
                self.show_output_notice("Browser opened. Please complete login there.", "ok", 3200)
            else:
                self.show_output_notice("Failed to open browser. Please retry or use QR login.", "warn", 3600)
        else:
            shown = self._show_login_qr_dialog(oauth, attempt_id)
            if not shown:
                self._on_login_failed_for_attempt(
                    attempt_id,
                    "QR code rendering failed. Install Python package 'qrcode' or system tool 'qrencode'.",
                )
                return
            self.show_output_notice("Please scan the QR code with your phone to login.", "ok", 3200)

        def login_thread():
            ok = self.backend.finish_login(login_future)
            if ok:
                GLib.idle_add(self._on_login_success_for_attempt, attempt_id)
            else:
                detail = ""
                try:
                    detail = str(getattr(self.backend, "get_last_login_error", lambda: "")() or "").strip()
                except Exception:
                    detail = ""
                msg = detail or "Authentication failed or timed out."
                GLib.idle_add(self._on_login_failed_for_attempt, attempt_id, msg)

        Thread(target=login_thread, daemon=True).start()

    def _open_login_url(self, url, attempt_id):
        url = str(url or "").strip()
        if not url:
            logger.error("Login URL empty (id=%s).", attempt_id)
            return False
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            logger.error("Login URL invalid scheme=%s (id=%s): %s", parsed.scheme, attempt_id, url)
            return False
        try:
            opened = bool(webbrowser.open(url, new=2))
            logger.info("Browser open result=%s (id=%s host=%s).", opened, attempt_id, parsed.netloc or "")
            self.record_diag_event(f"AUTH BROWSER id={attempt_id} opened={opened}")
            return opened
        except Exception as e:
            logger.error("Browser open error (id=%s): %s", attempt_id, e)
            self.record_diag_event(f"AUTH BROWSER ERROR id={attempt_id} err={e}")
            return False

    def _cleanup_login_dialog(self):
        if self._login_dialog is not None:
            try:
                self._login_dialog.destroy()
            except Exception:
                pass
            self._login_dialog = None
        self._login_status_label = None
        if self._login_qr_tempfile:
            try:
                if os.path.exists(self._login_qr_tempfile):
                    os.remove(self._login_qr_tempfile)
            except Exception as e:
                logger.debug("Failed to remove QR temp file %s: %s", self._login_qr_tempfile, e)
            self._login_qr_tempfile = None

    def _cancel_login_attempt(self, attempt_id, reason="canceled"):
        if not self._login_in_progress:
            return
        if attempt_id != self._login_attempt_id:
            return
        self.record_diag_event(f"AUTH CANCELED id={attempt_id} reason={reason}")
        logger.info("Login canceled (id=%s reason=%s).", attempt_id, reason)
        self._login_in_progress = False
        self._login_attempt_id = None
        self._login_mode = None
        self._cleanup_login_dialog()
        self.show_output_notice("Login canceled.", "warn", 1800)

    def _build_qr_tempfile(self, url, attempt_id):
        url = str(url or "").strip()
        if not url:
            logger.error("QR generation aborted: empty login url (id=%s).", attempt_id)
            return None
        path = os.path.join(GLib.get_tmp_dir(), f"hiresti-login-qr-{attempt_id}.png")

        def _try_qrencode_fallback():
            tool = shutil.which("qrencode")
            if not tool:
                return None
            try:
                subprocess.run([tool, "-m", "1", "-s", "6", "-o", path, url], check=True)
                if os.path.exists(path):
                    logger.info("QR generated via qrencode fallback (id=%s).", attempt_id)
                    return path
            except Exception as e:
                logger.warning("qrencode generation failed (id=%s): %s", attempt_id, e)
            return None

        if qrcode is None:
            out = _try_qrencode_fallback()
            if out:
                return out
            logger.error(
                "QR generation unavailable (id=%s): python 'qrcode' and system 'qrencode' are both missing.",
                attempt_id,
            )
            return None
        try:
            qr = qrcode.QRCode(border=1, box_size=6)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            img.save(path)
            return path
        except Exception as e:
            logger.warning("QR generation failed (id=%s): %s", attempt_id, e)
            out = _try_qrencode_fallback()
            if out:
                return out
            return None

    def _show_login_qr_dialog(self, oauth, attempt_id):
        self._cleanup_login_dialog()
        login_url = str((oauth or {}).get("url", "") or "")
        user_code = str((oauth or {}).get("user_code", "") or "")

        dialog = Gtk.Dialog(title="Scan QR to Login", transient_for=self.win, modal=True)
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        root.append(Gtk.Label(label="Use your phone camera or TIDAL app to scan this QR code.", xalign=0, wrap=True))

        qr_path = self._build_qr_tempfile(login_url, attempt_id)
        self._login_qr_tempfile = qr_path
        if not qr_path or not os.path.exists(qr_path):
            return False
        pic = Gtk.Picture.new_for_filename(qr_path)
        pic.set_size_request(280, 280)
        pic.set_halign(Gtk.Align.CENTER)
        try:
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        except Exception:
            pass
        root.append(pic)

        if user_code:
            root.append(Gtk.Label(label=f"Verification code: {user_code}", xalign=0))
        status = Gtk.Label(label="Waiting for mobile authorization...", xalign=0, wrap=True)
        root.append(status)
        self._login_status_label = status

        actions = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
        actions.append(cancel_btn)
        root.append(actions)
        dialog.set_child(root)

        def _on_response(d, resp):
            d.destroy()
            if self._login_dialog is d:
                self._login_dialog = None
            if resp == Gtk.ResponseType.CANCEL:
                self._cancel_login_attempt(attempt_id, reason="user-cancel")

        dialog.connect("response", _on_response)
        dialog.present()
        self._login_dialog = dialog
        return True

    def _on_login_success_for_attempt(self, attempt_id):
        if attempt_id != self._login_attempt_id:
            return False
        self.record_diag_event(f"AUTH SUCCESS id={attempt_id}")
        if self._login_status_label is not None:
            self._login_status_label.set_text("Authorization complete, signing in...")
        self._login_in_progress = False
        self._login_attempt_id = None
        self._login_mode = None
        self._cleanup_login_dialog()
        self.on_login_success()
        return False

    def _on_login_failed(self, attempt_id, exc):
        kind = classify_exception(exc)
        logger.error("Login bootstrap failed (id=%s kind=%s): %s", attempt_id, kind, exc)
        self.record_diag_event(f"AUTH ERROR id={attempt_id} kind={kind}")
        self._login_in_progress = False
        self._login_attempt_id = None
        self._login_mode = None
        self._cleanup_login_dialog()
        self.show_output_notice("Login start failed.", "error", 2800)
        self._show_simple_dialog("Login failed", f"[{kind}] {exc}")

    def _on_login_failed_for_attempt(self, attempt_id, message):
        if attempt_id != self._login_attempt_id:
            return False
        self.record_diag_event(f"AUTH FAILED id={attempt_id}")
        logger.warning("Login failed (id=%s): %s", attempt_id, message)
        if self._login_status_label is not None:
            self._login_status_label.set_text(f"Authorization failed: {message}")
        self._login_in_progress = False
        self._login_attempt_id = None
        self._login_mode = None
        self._cleanup_login_dialog()
        self.show_output_notice("Login failed. Please retry.", "error", 2800)
        self._show_simple_dialog("Login failed", message)
        return False

    def on_logout_clicked(self, btn):
        self.user_popover.popdown()
        self._login_in_progress = False
        self._login_attempt_id = None
        self._login_mode = None
        self._cleanup_login_dialog()
        self.backend.logout()
        self._apply_account_scope(force=True)
        self._home_sections_cache = None
        self.stream_prefetch_cache.clear()
        self._toggle_login_view(False)
        self.refresh_visible_track_fav_buttons()
        self.refresh_current_track_favorite_state()
        while c := self.collection_content_box.get_first_child(): self.collection_content_box.remove(c)
        logger.info("User logged out.")

    def on_login_success(self):
        logger.info("Login successful.")
        self.show_output_notice("Login successful.", "ok", 2000)
        self._apply_account_scope(force=True)
        self._home_sections_cache = None
        self._toggle_login_view(True)
        self.refresh_visible_track_fav_buttons()
        self.refresh_current_track_favorite_state()
        self._restore_last_view()

    def on_bit_perfect_toggled(self, switch, state):
        self.settings["bit_perfect"] = state; self.save_settings()
        self._lock_volume_controls(state)
        self.ex_switch.set_sensitive(state)
        if not state: self.ex_switch.set_active(False)
        is_ex = self.ex_switch.get_active()
        self.player.toggle_bit_perfect(state, exclusive_lock=is_ex)
        self.eq_btn.set_sensitive(not state)
        if state: self.eq_pop.popdown()
        if self.bp_label is not None: self.bp_label.set_visible(state)
        if is_ex:
            self._force_driver_selection("ALSA"); self.driver_dd.set_sensitive(False); self.on_driver_changed(self.driver_dd, None)
        else:
            self.driver_dd.set_sensitive(True)
            drv_item = self.driver_dd.get_selected_item() if self.driver_dd is not None else None
            drv_name = drv_item.get_string() if drv_item is not None else ""
            if state and drv_name == "PipeWire" and hasattr(self.player, "ensure_pipewire_pro_audio"):
                def _switch_to_pro_audio():
                    ok = False
                    try:
                        ok = bool(self.player.ensure_pipewire_pro_audio())
                    except Exception:
                        ok = False

                    def _apply_ui():
                        try:
                            audio_settings_actions._refresh_devices_for_current_driver_ui_only(
                                self, reason="bit-perfect-pro-audio"
                            )
                        except Exception:
                            pass
                        if ok:
                            self.show_output_notice("Bit-perfect enabled: switched card profile to pro-audio.", "ok", 2800)
                        else:
                            self.show_output_notice(
                                "Bit-perfect enabled, but pro-audio switch failed. You can still choose device manually.",
                                "warn",
                                3800,
                            )
                        return False

                    GLib.idle_add(_apply_ui)

                Thread(target=_switch_to_pro_audio, daemon=True).start()

    def on_exclusive_toggled(self, switch, state):
        self.settings["exclusive_lock"] = state
        self.save_settings()
        
        self.player.toggle_bit_perfect(True, exclusive_lock=state)
        
        self.latency_dd.set_sensitive(state)

        if state:
            # 开启独占：强制 ALSA，禁用驱动选择
            self._force_driver_selection("ALSA")
            self.driver_dd.set_sensitive(False)
            self.on_driver_changed(self.driver_dd, None)
        else:
            # 关闭独占：恢复驱动选择
            self.driver_dd.set_sensitive(True)
            # 刷新一下非独占状态下的设备列表
            self.on_device_changed(self.device_dd, None)

    def on_auto_rebind_once_toggled(self, switch, state):
        self.settings["output_auto_rebind_once"] = bool(state)
        self.save_settings()

    def on_toggle_mode(self, btn):
        """切换播放模式：循环 -> 单曲 -> 随机 -> 算法 -> 循环"""
        # 循环切换 0 -> 1 -> 2 -> 3 -> 0
        self.play_mode = (self.play_mode + 1) % 4
        
        # 获取图标和提示文字
        icon = self.MODE_ICONS.get(self.play_mode, "hiresti-mode-loop-symbolic")
        tooltip = self.MODE_TOOLTIPS.get(self.play_mode, "Loop")
        
        # 更新 UI
        if self.mode_btn is not None:
            self.mode_btn.set_icon_name(icon)
            self.mode_btn.set_tooltip_text(tooltip)
        
        # 状态处理
        if self.play_mode == self.MODE_SHUFFLE or self.play_mode == self.MODE_SMART:
            # 立即生成随机池，防止切歌时 shuffle_indices 为空
            self._generate_shuffle_list()
            # print(f"[Mode] Switched to {tooltip}")
        else:
            # 切回顺序模式，清空随机池以节省内存
            self.shuffle_indices = []
            # print(f"[Mode] Switched to {tooltip}")
        self.settings["play_mode"] = self.play_mode
        self.schedule_save_settings()

    def _generate_shuffle_list(self):
        """生成随机播放索引列表"""
        # 1. 安全检查：列表是否存在
        queue = self._get_active_queue()
        if not queue:
            self.shuffle_indices = []
            return 
        
        total = len(queue)
        if total == 0:
            self.shuffle_indices = []
            return

        # 2. 生成基础索引 [0, 1, 2, ... total-1]
        indices = list(range(total))
        
        # 3. 获取当前播放索引（防止类型错误）
        current_idx = getattr(self, 'current_track_index', -1)
        if current_idx is None: current_idx = -1
        
        # 4. 如果当前正在播放，从随机池中移除它（避免下一首立刻重复）
        if current_idx >= 0 and current_idx < total:
            if current_idx in indices:
                indices.remove(current_idx)
            
        # 5. 执行洗牌
        import random
        random.shuffle(indices)
        
        self.shuffle_indices = indices

    def get_next_index(self, direction=1):
        return playback_actions.get_next_index(self, direction)

    def on_latency_changed(self, dd, p):
        audio_settings_actions.on_latency_changed(self, dd, p)

    def _refresh_output_status_loop(self):
        audio_settings_actions.update_output_status_ui(self)

    def _get_output_status_interval_ms(self):
        try:
            is_settings = bool(
                getattr(self, "right_stack", None) is not None
                and self.right_stack.get_visible_child_name() == "settings"
            )
        except Exception:
            is_settings = False
        if is_settings:
            return 1000
        state = str(getattr(self.player, "output_state", "idle") or "idle")
        if state in ("fallback", "error", "switching"):
            return 1200
        try:
            is_playing = bool(self.player.is_playing())
        except Exception:
            is_playing = False
        return 2500 if is_playing else 6000

    def _schedule_output_status_loop(self, delay_ms=None):
        source = getattr(self, "_output_status_source", 0)
        if source:
            try:
                GLib.source_remove(source)
            except Exception:
                pass
            self._output_status_source = 0
        next_delay = int(delay_ms if delay_ms is not None else self._get_output_status_interval_ms())

        def _tick():
            self._output_status_source = 0
            try:
                self._refresh_output_status_loop()
            except Exception:
                logger.exception("Output status loop tick failed")
            self._schedule_output_status_loop()
            return False

        self._output_status_source = GLib.timeout_add(max(250, next_delay), _tick)

    def _force_driver_selection(self, keyword):
        model = self.driver_dd.get_model()
        for i in range(model.get_n_items()):
            if keyword in model.get_item(i).get_string(): self.driver_dd.set_selected(i); break

    def update_tech_label(self, info):
        fmt = str(info.get('fmt_str', '') or '')
        fmt_norm = " ".join(fmt.replace("\\", " ").split())
        codec = info.get('codec', '-')
        if (not fmt_norm) and (not codec or codec in ["-", "Loading..."]):
            self.lbl_tech.set_text("")
            self.lbl_tech.set_tooltip_text(None)
            self.lbl_tech.remove_css_class("tech-label")
            for cls in ("tech-state-ok", "tech-state-mixed", "tech-state-warn"):
                self.lbl_tech.remove_css_class(cls)
            self.lbl_tech.set_visible(True)
            return

        display_codec = codec if codec and codec not in ["-", "Loading..."] else "PCM"
        if isinstance(display_codec, str):
            codec_low = display_codec.lower()
            if "flac" in codec_low:
                display_codec = "FLAC"
            elif "aac" in codec_low:
                display_codec = "AAC"
            elif "alac" in codec_low:
                display_codec = "ALAC"
            else:
                display_codec = display_codec.replace("\\", " ").strip()

        # Prefer explicit numeric fields; fmt_str can be missing or escaped.
        def _pick_int(*keys):
            for k in keys:
                try:
                    v = int(info.get(k, 0) or 0)
                except Exception:
                    v = 0
                if v > 0:
                    return v
            return 0

        src_rate = _pick_int("source_rate", "rate", "output_rate")
        src_depth = _pick_int("source_depth", "depth", "output_depth")

        if src_rate > 0 and src_depth > 0:
            rate_depth = f"{src_depth}-bit/{(src_rate / 1000.0):g}kHz"
        else:
            rate_depth = fmt_norm
            if "|" in fmt_norm:
                parts = [p.strip() for p in fmt_norm.split("|")]
                if len(parts) >= 2:
                    rate = parts[0]
                    depth = parts[1].replace("bit", "-bit")
                    rate_depth = f"{depth}/{rate}"
            if not rate_depth:
                rate_depth = "-"

        bitrate = int(info.get("bitrate", 0) or 0)
        if bitrate > 0:
            kbps = max(1, int(round(bitrate / 1000.0)))
            bitrate_text = f" • {kbps}k"
        else:
            bitrate_text = ""

        is_bp = bool(getattr(self.player, "bit_perfect_mode", False))
        is_ex = bool(getattr(self.player, "exclusive_lock_mode", False))
        output_state = str(getattr(self.player, "output_state", "idle"))

        mode_tag = "BP" if is_bp else "MIX"
        lock_tag = "EX" if is_ex else "SHR"
        self.lbl_tech.add_css_class("tech-label")
        self.lbl_tech.set_text(f"{mode_tag}/{lock_tag} • {rate_depth} • {display_codec}{bitrate_text}")

        # Full detail remains available on hover.
        dev_name = getattr(self, "current_device_name", "Default")
        self.lbl_tech.set_tooltip_text(
            f"{display_codec} | {rate_depth} | {bitrate//1000}kbps | {dev_name} | output={output_state}"
        )

        for cls in ("tech-state-ok", "tech-state-mixed", "tech-state-warn"):
            self.lbl_tech.remove_css_class(cls)
        if output_state in ("fallback", "error"):
            self.lbl_tech.add_css_class("tech-state-warn")
        elif is_bp:
            self.lbl_tech.add_css_class("tech-state-ok")
        else:
            self.lbl_tech.add_css_class("tech-state-mixed")

        self.lbl_tech.set_visible(True)

    def on_settings_clicked(self, btn):
        self._remember_last_view("settings")
        self.right_stack.set_visible_child_name("settings"); self.grid_title_label.set_text("Settings"); self.back_btn.set_sensitive(True); self.nav_list.select_row(None)

    def on_quality_changed(self, dd, p):
        playback_stream_actions.on_quality_changed(self, dd, p)

    def _restart_player_with_url(self, url, pos):
        playback_stream_actions.restart_player_with_url(self, url, pos)

    def on_driver_changed(self, dd, p):
        audio_settings_actions.on_driver_changed(self, dd, p)

    def on_device_changed(self, dd, p):
        audio_settings_actions.on_device_changed(self, dd, p)

    def on_recover_output_clicked(self, btn):
        audio_settings_actions.on_recover_output_clicked(self, btn)

    # [统一点击入口]
    def on_grid_item_activated(self, flow, child):
        if not child: return
        data = getattr(child, 'data_item', None)
        if not data: return
        obj = data.get('obj')
        
        if data['type'] == 'Track':
            self._play_single_track(obj)
            return
        if data['type'] == 'Artist':
            self.on_artist_clicked(obj)
            return
        self.show_album_details(obj)

    def _play_single_track(self, track):
        self.current_track_list = [track]
        self._set_play_queue([track])
        self.play_track(0)

    def show_album_details(self, alb):
        self.current_remote_playlist = None
        ui_actions.show_album_details(self, alb)

    def _sort_tracks(self, tracks, field, asc=True):
        items = list(tracks or [])
        if not field:
            return items

        def _artist_name(t):
            return str(getattr(getattr(t, "artist", None), "name", "") or "").lower()

        def _album_name(t):
            return str(getattr(getattr(t, "album", None), "name", "") or "").lower()

        def _title(t):
            return str(getattr(t, "name", "") or "").lower()

        if field == "title":
            key_func = _title
        elif field == "artist":
            key_func = _artist_name
        elif field == "album":
            key_func = _album_name
        elif field == "time":
            key_func = lambda t: int(getattr(t, "duration", 0) or 0)
        else:
            return items
        return sorted(items, key=key_func, reverse=not asc)

    def _format_sort_label(self, base, field, active_field, asc):
        if field != active_field:
            return base
        return f"{base} {'▲' if asc else '▼'}"

    def _update_album_sort_headers(self):
        btns = getattr(self, "album_sort_buttons", {}) or {}
        if not btns:
            return
        labels = {
            "title": "Title",
            "artist": "Artist",
            "album": "Album",
            "time": "Time",
        }
        for field, btn in btns.items():
            if field in labels:
                text = self._format_sort_label(labels[field], field, self.album_sort_field, self.album_sort_asc)
                head_lbl = getattr(btn, "_head_label", None)
                if head_lbl is not None:
                    head_lbl.set_text(text)
                elif hasattr(btn, "set_text"):
                    btn.set_text(text)
                else:
                    btn.set_label(text)

    def load_album_tracks(self, tracks):
        self.album_track_source = list(tracks or [])
        self._render_album_tracks()

    def _render_album_tracks(self):
        tracks = self._sort_tracks(self.album_track_source, self.album_sort_field, self.album_sort_asc)
        self.populate_tracks(tracks)
        self._update_album_sort_headers()

    def on_album_sort_clicked(self, field):
        if self.album_sort_field == field:
            self.album_sort_asc = not self.album_sort_asc
        else:
            self.album_sort_field = field
            self.album_sort_asc = True
        self._render_album_tracks()

    def on_playlist_sort_clicked(self, field):
        if self.playlist_sort_field == field:
            self.playlist_sort_asc = not self.playlist_sort_asc
        else:
            self.playlist_sort_field = field
            self.playlist_sort_asc = True
        if self.current_playlist_id:
            self.render_playlist_detail(self.current_playlist_id)

    def get_sorted_playlist_tracks(self, playlist_id):
        tracks = self.playlist_mgr.get_tracks(playlist_id) if hasattr(self, "playlist_mgr") else []
        if getattr(self, "playlist_edit_mode", False):
            return tracks
        return self._sort_tracks(tracks, self.playlist_sort_field, self.playlist_sort_asc)

    def populate_tracks(self, tracks):
        ui_actions.populate_tracks(self, tracks)

    def _update_track_list_icon(self, target_list=None):
        """
        [升级版] 刷新列表图标：当前播放的显示 ▶，其他的显示数字
        """
        if self.playing_track_id and not getattr(self, "_playing_pulse_source", 0):
            self._playing_pulse_source = GLib.timeout_add(1000, self._tick_playing_row_pulse)
        if not self.playing_track_id and getattr(self, "_playing_pulse_source", 0):
            GLib.source_remove(self._playing_pulse_source)
            self._playing_pulse_source = 0
            self._playing_pulse_on = False

        targets = []
        if target_list is not None:
            targets.append(target_list)
        else:
            if self.track_list is not None:
                targets.append(self.track_list)
            if getattr(self, "liked_track_list", None) is not None:
                targets.append(self.liked_track_list)
            if getattr(self, "playlist_track_list", None) is not None:
                targets.append(self.playlist_track_list)
            if getattr(self, "queue_track_list", None) is not None:
                targets.append(self.queue_track_list)
            if getattr(self, "queue_drawer_list", None) is not None:
                targets.append(self.queue_drawer_list)
            if not targets:
                return

        for tl in targets:
            row = tl.get_first_child()
            while row:
                # 只有带 track_id 的行才处理
                if hasattr(row, 'track_id'):
                    box = row.get_child()
                    if box:
                        stack = box.get_first_child()
                        # 确保它是我们放图标的那个 Stack 组件
                        if isinstance(stack, Gtk.Stack):
                            # 核心比对：行的 ID vs 当前播放 ID
                            if row.track_id == self.playing_track_id: 
                                stack.set_visible_child_name("icon")
                                row.add_css_class("playing-row")
                                if getattr(self, "_playing_pulse_on", False):
                                    row.add_css_class("playing-row-pulse")
                                else:
                                    row.remove_css_class("playing-row-pulse")
                            else: 
                                stack.set_visible_child_name("num")
                                row.remove_css_class("playing-row")
                                row.remove_css_class("playing-row-pulse")
                row = row.get_next_sibling()

    def _tick_playing_row_pulse(self):
        if not self.playing_track_id:
            self._playing_pulse_source = 0
            self._playing_pulse_on = False
            self._update_track_list_icon()
            return False
        self._playing_pulse_on = not self._playing_pulse_on
        self._update_track_list_icon()
        return True

    def on_header_artist_clicked(self, gest, n, x, y):
        if self.current_album:
            artist_obj = None
            if hasattr(self.current_album, 'artist') and self.current_album.artist:
                artist_obj = self.current_album.artist

            if not artist_obj or isinstance(artist_obj, str):
                return

            artist_id = getattr(artist_obj, "id", None)
            artist_name = getattr(artist_obj, "name", "").strip()
            if not artist_id and not artist_name:
                return

            def resolve_artist():
                # Always resolve to a real backend artist object before navigation.
                resolved = self.backend.resolve_artist(artist_id=artist_id, artist_name=artist_name)
                if not resolved:
                    logger.info("Artist resolve failed for history entry: id=%s name=%s", artist_id, artist_name)
                    return
                GLib.idle_add(self.on_artist_clicked, resolved)

            Thread(target=resolve_artist, daemon=True).start()

    def on_artist_clicked(self, artist):
        ui_navigation.on_artist_clicked(self, artist)

    def batch_load_albums(self, albs, batch=6):
        return ui_actions.batch_load_albums(self, albs, batch)

    def batch_load_artists(self, artists, batch=10):
        return ui_actions.batch_load_artists(self, artists, batch)

    def batch_load_home(self, sections):
        ui_actions.batch_load_home(self, sections)

    def render_daily_mixes(self, mixes=None):
        if mixes is None:
            mixes = self.build_daily_mixes()
        ui_actions.render_daily_mixes(self, mixes)

    def render_history_dashboard(self):
        ui_actions.render_history_dashboard(self)

    def render_collection_dashboard(self, favorite_tracks=None, favorite_albums=None):
        ui_actions.render_collection_dashboard(self, favorite_tracks, favorite_albums)

    def render_liked_songs_dashboard(self, tracks=None):
        ui_actions.render_liked_songs_dashboard(self, tracks)

    def refresh_liked_songs_dashboard(self):
        row = self.nav_list.get_selected_row() if self.nav_list is not None else None
        if not row or getattr(row, "nav_id", None) != "liked_songs":
            return False

        if not getattr(self.backend, "user", None):
            self.render_liked_songs_dashboard([])
            return False

        # Render cached data immediately to avoid perceived UI stall when revisiting this page.
        cached_tracks = list(getattr(self, "liked_tracks_data", []) or [])
        now = time.time()
        ttl = float(getattr(self, "liked_tracks_cache_ttl_sec", 30.0) or 30.0)
        last_ts = float(getattr(self, "liked_tracks_last_fetch_ts", 0.0) or 0.0)
        if cached_tracks:
            self.render_liked_songs_dashboard(cached_tracks)
            if now - last_ts <= max(0.0, ttl):
                return False

        req_id = int(getattr(self, "_liked_tracks_request_id", 0) or 0) + 1
        self._liked_tracks_request_id = req_id

        def _is_stale():
            return req_id != int(getattr(self, "_liked_tracks_request_id", 0) or 0)

        def _liked_view_active():
            current = self.nav_list.get_selected_row() if self.nav_list is not None else None
            return bool(current and getattr(current, "nav_id", None) == "liked_songs")

        def _apply_if_active(tracks):
            current = self.nav_list.get_selected_row() if self.nav_list is not None else None
            if not current or getattr(current, "nav_id", None) != "liked_songs":
                return False
            if _is_stale():
                return False
            self.render_liked_songs_dashboard(tracks)
            return False

        def task():
            if _is_stale() or (not _liked_view_active()):
                return
            # Stage 1: get a small slice for fast first paint.
            head_tracks = list(self.backend.get_favorite_tracks(limit=100))
            if head_tracks and not _is_stale():
                if len(head_tracks) > len(cached_tracks):
                    GLib.idle_add(lambda: _apply_if_active(head_tracks))

            # Stage 2: fetch full library in background.
            # Skip full fetch if user already left Liked Songs to avoid pointless heavy work.
            if _is_stale() or (not _liked_view_active()):
                return
            tracks = list(self.backend.get_favorite_tracks(limit=20000))
            if _is_stale():
                return
            try:
                self.backend.fav_track_ids = {
                    str(getattr(t, "id", ""))
                    for t in tracks
                    if getattr(t, "id", None) is not None
                }
            except Exception:
                pass
            self.liked_tracks_last_fetch_ts = time.time()
            GLib.idle_add(lambda: _apply_if_active(tracks))

        Thread(target=task, daemon=True).start()
        return False

    def render_queue_dashboard(self):
        ui_actions.render_queue_dashboard(self)

    def render_queue_drawer(self):
        ui_actions.render_queue_drawer(self)

    def _sync_queue_handle_state(self, expanded):
        btn = getattr(self, "queue_btn", None)
        if btn is not None:
            btn.set_icon_name(
                "hiresti-queue-handle-right-symbolic" if expanded else "hiresti-queue-handle-left-symbolic"
            )
            btn.set_tooltip_text("Close Queue" if expanded else "Open Queue")
            if expanded:
                btn.add_css_class("active")
            else:
                btn.remove_css_class("active")
        anchor = getattr(self, "queue_anchor", None)
        if anchor is not None:
            if expanded:
                anchor.add_css_class("open")
            else:
                anchor.remove_css_class("open")

    def toggle_queue_drawer(self, _btn=None):
        revealer = getattr(self, "queue_revealer", None)
        if revealer is None:
            return
        show = not revealer.get_reveal_child()
        revealer.set_reveal_child(show)
        if getattr(self, "queue_backdrop", None) is not None:
            self.queue_backdrop.set_visible(show)
        self._sync_queue_handle_state(show)
        if show:
            # Let reveal animation start first; defer queue row rendering so
            # first-frame animation is not blocked by list build work.
            GLib.timeout_add(120, lambda: (self.render_queue_drawer(), False)[1])

    def close_queue_drawer(self):
        revealer = getattr(self, "queue_revealer", None)
        if revealer is not None:
            revealer.set_reveal_child(False)
        if getattr(self, "queue_backdrop", None) is not None:
            self.queue_backdrop.set_visible(False)
        self._sync_queue_handle_state(False)

    def _is_queue_nav_selected(self):
        row = self.nav_list.get_selected_row() if self.nav_list is not None else None
        return bool(row and getattr(row, "nav_id", None) == "queue")

    def _get_active_queue(self):
        q = list(getattr(self, "play_queue", []) or [])
        if q:
            return q
        return list(getattr(self, "current_track_list", []) or [])

    def _set_play_queue(self, tracks):
        self.play_queue = list(tracks or [])
        self.shuffle_indices = []

    def _refresh_queue_views(self):
        self.render_queue_drawer()
        if self._is_queue_nav_selected():
            self.render_queue_dashboard()
        return False

    def render_playlists_home(self):
        self.current_remote_playlist = None
        if self.right_stack is not None:
            self.right_stack.set_visible_child_name("grid_view")
            if hasattr(self, "_remember_last_view"):
                self._remember_last_view("grid_view")
        folder_stack = list(getattr(self, "current_playlist_folder_stack", []) or [])
        if self.back_btn is not None:
            self.back_btn.set_sensitive(bool(folder_stack))
        if self.remote_playlist_edit_btn is not None:
            self.remote_playlist_edit_btn.set_visible(False)
        if self.remote_playlist_visibility_btn is not None:
            self.remote_playlist_visibility_btn.set_visible(False)
        if self.remote_playlist_more_btn is not None:
            self.remote_playlist_more_btn.set_visible(False)
        if hasattr(self, "grid_title_label") and self.grid_title_label is not None:
            self.grid_title_label.set_text("Playlists")
            self.grid_title_label.set_visible(True)
        if hasattr(self, "grid_subtitle_label") and self.grid_subtitle_label is not None:
            self.grid_subtitle_label.set_text("Browse and manage your cloud playlists")
            self.grid_subtitle_label.set_visible(True)
        ui_actions.render_playlists_home(self)

    def on_playlist_folder_card_clicked(self, folder_obj):
        if folder_obj is None:
            return
        fid = str(getattr(folder_obj, "id", "") or "")
        if not fid:
            return
        self.current_playlist_folder = folder_obj
        stack = list(getattr(self, "current_playlist_folder_stack", []) or [])
        if stack and str(stack[-1].get("id", "")) == fid:
            pass
        else:
            stack.append({"id": fid, "name": str(getattr(folder_obj, "name", "") or "Folder"), "obj": folder_obj})
        self.current_playlist_folder_stack = stack
        self.render_playlists_home()

    def on_playlist_folder_up_clicked(self, _btn=None):
        stack = list(getattr(self, "current_playlist_folder_stack", []) or [])
        if not stack:
            self.current_playlist_folder = None
            self.render_playlists_home()
            return
        stack.pop()
        self.current_playlist_folder_stack = stack
        if stack:
            self.current_playlist_folder = stack[-1].get("obj")
        else:
            self.current_playlist_folder = None
        self.render_playlists_home()

    def on_create_playlist_folder_clicked(self, _btn=None):
        if not getattr(self.backend, "user", None):
            self._show_simple_dialog("Login Required", "Please login first.")
            return

        def _submit(name):
            folder_name = str(name or "").strip() or "New Folder"
            parent_id = "root"
            if getattr(self, "current_playlist_folder", None) is not None:
                parent_id = str(getattr(self.current_playlist_folder, "id", "root") or "root")
            self.show_output_notice("Creating folder...", "ok", 1500)

            def task():
                f = self.backend.create_cloud_folder(folder_name, parent_folder_id=parent_id)

                def apply():
                    if f is None:
                        self.show_output_notice("Failed to create folder.", "warn", 2600)
                    else:
                        self.show_output_notice("Folder created.", "ok", 2200)
                        self.render_playlists_home()
                    return False

                GLib.idle_add(apply)

            Thread(target=task, daemon=True).start()

        self._prompt_playlist_name(
            "New Folder",
            "New Folder",
            _submit,
            subtitle="Create a folder to organize your cloud playlists.",
            placeholder="Folder name",
            save_label="Create",
            dialog_size=(480, 220),
        )

    def on_playlist_folder_rename_clicked(self, folder_obj=None):
        folder_obj = folder_obj or getattr(self, "current_playlist_folder", None)
        if folder_obj is None:
            return
        old_name = str(getattr(folder_obj, "name", "") or "Folder")

        def _submit(name):
            new_name = str(name or "").strip()
            if not new_name or new_name == old_name:
                return
            self.show_output_notice("Renaming folder...", "ok", 1500)

            def task():
                res = self.backend.rename_cloud_folder(folder_obj, new_name)

                def apply():
                    if bool(res.get("ok")):
                        self.show_output_notice("Folder renamed.", "ok", 2200)
                        stack = list(getattr(self, "current_playlist_folder_stack", []) or [])
                        for item in stack:
                            if str(item.get("id", "")) == str(getattr(folder_obj, "id", "") or ""):
                                item["name"] = new_name
                        self.current_playlist_folder_stack = stack
                        self.render_playlists_home()
                    else:
                        self.show_output_notice("Failed to rename folder.", "warn", 2600)
                    return False

                GLib.idle_add(apply)

            Thread(target=task, daemon=True).start()

        self._prompt_playlist_name(
            "Rename Folder",
            old_name,
            _submit,
            subtitle="Update folder name for your cloud playlists.",
            placeholder="Folder name",
            save_label="Rename",
            dialog_size=(480, 220),
        )

    def on_playlist_folder_delete_clicked(self, folder_obj=None):
        folder_obj = folder_obj or getattr(self, "current_playlist_folder", None)
        if folder_obj is None:
            return
        fname = str(getattr(folder_obj, "name", "") or "this folder")
        dialog = Gtk.Dialog(title="Delete Folder", transient_for=self.win, modal=True)
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        root.append(Gtk.Label(label=f"Delete '{fname}' permanently?", xalign=0))
        action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        delete_btn = Gtk.Button(label="Delete")
        cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
        delete_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
        action_row.append(cancel_btn)
        action_row.append(delete_btn)
        root.append(action_row)
        dialog.set_child(root)

        def _on_response(d, resp):
            if resp != Gtk.ResponseType.OK:
                d.destroy()
                return
            d.destroy()
            self.show_output_notice("Deleting folder...", "ok", 1600)

            def task():
                res = self.backend.delete_cloud_folder(folder_obj)

                def apply():
                    if bool(res.get("ok")):
                        self.show_output_notice("Folder deleted.", "ok", 2200)
                        fid = str(getattr(folder_obj, "id", "") or "")
                        stack = [x for x in list(getattr(self, "current_playlist_folder_stack", []) or []) if str(x.get("id", "")) != fid]
                        self.current_playlist_folder_stack = stack
                        self.current_playlist_folder = stack[-1].get("obj") if stack else None
                        self.render_playlists_home()
                    else:
                        self.show_output_notice("Failed to delete folder.", "warn", 2800)
                    return False

                GLib.idle_add(apply)

            Thread(target=task, daemon=True).start()

        dialog.connect("response", _on_response)
        dialog.present()

    def render_playlist_detail(self, playlist_id):
        ui_actions.render_playlist_detail(self, playlist_id)

    def on_playlist_card_clicked(self, playlist_id):
        self.current_remote_playlist = None
        if self.remote_playlist_edit_btn is not None:
            self.remote_playlist_edit_btn.set_visible(False)
        if self.remote_playlist_visibility_btn is not None:
            self.remote_playlist_visibility_btn.set_visible(False)
        if self.remote_playlist_more_btn is not None:
            self.remote_playlist_more_btn.set_visible(False)
        self.current_playlist_id = playlist_id
        self.playlist_edit_mode = False
        self.playlist_rename_mode = False
        if hasattr(self, "grid_title_label") and self.grid_title_label is not None:
            self.grid_title_label.set_visible(False)
        if hasattr(self, "grid_subtitle_label") and self.grid_subtitle_label is not None:
            self.grid_subtitle_label.set_visible(False)
        if self.back_btn is not None:
            self.back_btn.set_sensitive(True)
        self.render_playlist_detail(playlist_id)

    def on_remote_playlist_card_clicked(self, playlist_obj):
        if playlist_obj is None:
            return
        self.current_remote_playlist = playlist_obj
        self.current_album = None
        self.current_playlist_id = None
        self.playlist_edit_mode = False
        self.playlist_rename_mode = False
        self.right_stack.set_visible_child_name("tracks")
        if hasattr(self, "_remember_last_view"):
            self._remember_last_view("tracks")
        self.back_btn.set_sensitive(True)

        title = getattr(playlist_obj, "name", "TIDAL Playlist")
        creator = getattr(playlist_obj, "creator", None)
        creator_name = str(getattr(creator, "name", None) or "TIDAL")
        self.header_kicker.set_text("Playlist")
        self.header_title.set_text(title)
        self.header_title.set_tooltip_text(title)
        self.header_artist.set_text(creator_name)
        self.header_artist.set_tooltip_text(creator_name)
        self.header_meta.set_text("")
        if self.fav_btn is not None:
            self.fav_btn.set_visible(False)
        if self.add_playlist_btn is not None:
            self.add_playlist_btn.set_visible(True)
        if self.remote_playlist_edit_btn is not None:
            self.remote_playlist_edit_btn.set_visible(True)
        if self.remote_playlist_visibility_btn is not None:
            self.remote_playlist_visibility_btn.set_visible(True)
        if self.remote_playlist_more_btn is not None:
            self.remote_playlist_more_btn.set_visible(True)
        self._refresh_remote_playlist_visibility_button(playlist_obj)
        utils.load_img(self.header_art, lambda: self.backend.get_artwork_url(playlist_obj, 640), self.cache_dir, 160)

        while c := self.track_list.get_first_child():
            self.track_list.remove(c)

        def task():
            tracks = self.backend.get_tracks(playlist_obj) or []

            def apply():
                self.header_meta.set_text(f"{len(tracks)} Tracks" if tracks else "0 Tracks")
                self.load_album_tracks(tracks)
                return False

            GLib.idle_add(apply)

        Thread(target=task, daemon=True).start()

    def _refresh_remote_playlist_visibility_button(self, playlist_obj=None):
        btn = getattr(self, "remote_playlist_visibility_btn", None)
        if btn is None:
            return
        pl = playlist_obj or getattr(self, "current_remote_playlist", None)
        if pl is None:
            btn.set_visible(False)
            return
        is_public = bool(getattr(pl, "public", False))
        btn.set_icon_name("changes-allow-symbolic" if is_public else "changes-prevent-symbolic")
        btn.set_tooltip_text("Click to make private" if is_public else "Click to make public")
        try:
            if is_public:
                btn.add_css_class("liked-action-btn-primary")
            else:
                btn.remove_css_class("liked-action-btn-primary")
        except Exception:
            pass

    def on_remote_playlist_toggle_public_clicked(self, _btn=None, playlist_obj=None):
        pl = playlist_obj or getattr(self, "current_remote_playlist", None)
        if pl is None:
            return
        target_public = not bool(getattr(pl, "public", False))
        self.show_output_notice("Updating playlist visibility...", "ok", 1800)

        def task():
            res = self.backend.update_cloud_playlist(pl, is_public=target_public)

            def apply():
                if bool(res.get("ok")):
                    try:
                        pl.public = target_public
                    except Exception:
                        pass
                    self._refresh_remote_playlist_visibility_button(pl)
                    self.show_output_notice(
                        "Playlist is now public." if target_public else "Playlist is now private.",
                        "ok",
                        2200,
                    )
                else:
                    self.show_output_notice("Failed to update playlist visibility.", "warn", 3200)
                return False

            GLib.idle_add(apply)

        Thread(target=task, daemon=True).start()

    def _open_cloud_playlist_editor(
        self,
        dialog_title,
        save_label,
        initial_title,
        initial_desc="",
        initial_public=False,
        playlist_obj=None,
        folder_options=None,
        initial_folder_id="root",
        on_submit=None,
    ):
        dialog = Gtk.Dialog(title=dialog_title, transient_for=self.win, modal=True)
        dialog.set_default_size(586, 413)
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=14,
            margin_bottom=14,
            margin_start=14,
            margin_end=14,
        )
        content = Gtk.Box(spacing=16)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        cover = Gtk.Image(css_classes=["album-cover-img", "playlist-cover-img"])
        cover.set_size_request(147, 147)
        if playlist_obj is not None:
            utils.load_img(cover, lambda: self.backend.get_artwork_url(playlist_obj, 640), self.cache_dir, 147)
        else:
            cover.set_from_icon_name("audio-x-generic-symbolic")
        left.append(cover)
        change_btn = Gtk.Button(label="Change image")
        change_btn.set_sensitive(False)
        change_btn.set_tooltip_text("Not available in this version")
        left.append(change_btn)
        content.append(left)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True)
        right.append(Gtk.Label(label="Title", xalign=0))
        title_entry = Gtk.Entry(text=str(initial_title or ""))
        right.append(title_entry)

        folder_dd = None
        folder_ids = []
        if folder_options:
            right.append(Gtk.Label(label="Folder", xalign=0))
            folder_labels = [str(item[1] or "Root") for item in folder_options]
            folder_ids = [str(item[0] or "root") for item in folder_options]
            folder_dd = Gtk.DropDown(model=Gtk.StringList.new(folder_labels))
            selected_idx = 0
            target_id = str(initial_folder_id or "root")
            for i, fid in enumerate(folder_ids):
                if fid == target_id:
                    selected_idx = i
                    break
            folder_dd.set_selected(selected_idx)
            right.append(folder_dd)

        right.append(Gtk.Label(label="Description", xalign=0))
        desc_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, vexpand=True)
        desc_buf = desc_view.get_buffer()
        desc_buf.set_text(str(initial_desc or ""))
        desc_scroll = Gtk.ScrolledWindow(vexpand=True, min_content_height=120)
        desc_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        desc_scroll.set_child(desc_view)
        right.append(desc_scroll)
        count_lbl = Gtk.Label(xalign=0, css_classes=["dim-label"])
        right.append(count_lbl)

        public_row = Gtk.Box(spacing=8, margin_top=6)
        public_lbl_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        public_lbl_box.append(Gtk.Label(label="Make it public", xalign=0))
        public_lbl_box.append(Gtk.Label(label="Your playlist will be visible on your profile and accessible by anyone.", xalign=0, css_classes=["dim-label"]))
        public_switch = Gtk.Switch(active=bool(initial_public), halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
        public_row.append(public_lbl_box)
        public_row.append(public_switch)
        right.append(public_row)

        content.append(right)
        root.append(content)

        action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        save_btn = Gtk.Button(label=save_label)
        save_btn.add_css_class("suggested-action")
        cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
        save_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
        action_row.append(cancel_btn)
        action_row.append(save_btn)
        root.append(action_row)
        dialog.set_child(root)

        def _update_count(_buf=None):
            txt = desc_buf.get_text(desc_buf.get_start_iter(), desc_buf.get_end_iter(), True) or ""
            count_lbl.set_text(f"{len(txt)}/500 characters")
            if len(txt) > 500:
                count_lbl.add_css_class("status-error")
            else:
                count_lbl.remove_css_class("status-error")
            return False

        desc_buf.connect("changed", _update_count)
        _update_count()

        def _on_response(d, resp):
            if resp != Gtk.ResponseType.OK:
                d.destroy()
                return
            title = str(title_entry.get_text() or "").strip()
            desc = desc_buf.get_text(desc_buf.get_start_iter(), desc_buf.get_end_iter(), True) or ""
            is_public = bool(public_switch.get_active())
            selected_folder_id = str(initial_folder_id or "root")
            if folder_dd is not None and folder_ids:
                idx = int(folder_dd.get_selected())
                if 0 <= idx < len(folder_ids):
                    selected_folder_id = folder_ids[idx]
            d.destroy()
            if not title:
                self.show_output_notice("Playlist title cannot be empty.", "warn", 2600)
                return
            if len(desc) > 500:
                self.show_output_notice("Description is too long (max 500).", "warn", 2600)
                return
            if callable(on_submit):
                on_submit(title, desc, is_public, selected_folder_id)

        dialog.connect("response", _on_response)
        dialog.present()

    def on_remote_playlist_rename_clicked(self, playlist_obj=None):
        pl = playlist_obj or getattr(self, "current_remote_playlist", None)
        if pl is None:
            return
        title_init = str(getattr(pl, "name", None) or "Untitled Playlist")
        desc_init = str(getattr(pl, "description", None) or "")
        public_init = bool(getattr(pl, "public", False))

        def _submit(title, desc, is_public, _folder_id):
            self.show_output_notice("Saving playlist...", "ok", 1800)

            def task():
                res = self.backend.update_cloud_playlist(pl, name=title, description=desc, is_public=is_public)

                def apply():
                    if bool(res.get("ok")):
                        try:
                            pl.name = title
                            pl.description = desc
                            pl.public = is_public
                        except Exception:
                            pass
                        self.show_output_notice("Playlist updated.", "ok", 2400)
                        if getattr(self, "current_remote_playlist", None) is not None and getattr(self.current_remote_playlist, "id", None) == getattr(pl, "id", None):
                            self.on_remote_playlist_card_clicked(pl)
                    else:
                        self.show_output_notice("Failed to update playlist.", "warn", 3200)
                    return False

                GLib.idle_add(apply)

            Thread(target=task, daemon=True).start()

        self._open_cloud_playlist_editor(
            dialog_title="Edit playlist",
            save_label="Save",
            initial_title=title_init,
            initial_desc=desc_init,
            initial_public=public_init,
            playlist_obj=pl,
            on_submit=_submit,
        )

    def on_remote_playlist_delete_clicked(self, playlist_obj=None):
        pl = playlist_obj or getattr(self, "current_remote_playlist", None)
        if pl is None:
            return
        pname = str(getattr(pl, "name", None) or "this playlist")
        dialog = Gtk.Dialog(title="Delete Playlist", transient_for=self.win, modal=True)
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        root.append(Gtk.Label(label=f"Delete '{pname}' permanently?", xalign=0))
        action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        delete_btn = Gtk.Button(label="Delete")
        cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
        delete_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
        action_row.append(cancel_btn)
        action_row.append(delete_btn)
        root.append(action_row)
        dialog.set_child(root)

        def _on_response(d, resp):
            if resp != Gtk.ResponseType.OK:
                d.destroy()
                return
            d.destroy()
            self.show_output_notice("Deleting playlist...", "ok", 1600)

            def task():
                res = self.backend.delete_cloud_playlist(pl)

                def apply():
                    if bool(res.get("ok")):
                        self.show_output_notice("Playlist deleted.", "ok", 2200)
                        if getattr(self, "current_remote_playlist", None) is not None and getattr(self.current_remote_playlist, "id", None) == getattr(pl, "id", None):
                            self.current_remote_playlist = None
                        self.render_playlists_home()
                    else:
                        self.show_output_notice("Failed to delete playlist.", "warn", 3000)
                    return False

                GLib.idle_add(apply)

            Thread(target=task, daemon=True).start()

        dialog.connect("response", _on_response)
        dialog.present()

    def on_remote_playlist_move_to_folder_clicked(self, playlist_obj=None):
        pl = playlist_obj or getattr(self, "current_remote_playlist", None)
        if pl is None:
            return
        folders = [{"id": "root", "path": "Root"}] + list(self.backend.get_all_playlist_folders(limit=1000) or [])
        options = [(str(f.get("id", "root")), str(f.get("path", "Root"))) for f in folders]
        if not options:
            self.show_output_notice("No folders available.", "warn", 2400)
            return
        dialog = Gtk.Dialog(title="Move to Folder", transient_for=self.win, modal=True)
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        root.append(Gtk.Label(label="Select destination folder:", xalign=0))
        dd = Gtk.DropDown(model=Gtk.StringList.new([label for _fid, label in options]))
        dd.set_selected(0)
        root.append(dd)
        action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        move_btn = Gtk.Button(label="Move")
        move_btn.add_css_class("suggested-action")
        cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
        move_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
        action_row.append(cancel_btn)
        action_row.append(move_btn)
        root.append(action_row)
        dialog.set_child(root)

        def _on_response(d, resp):
            if resp != Gtk.ResponseType.OK:
                d.destroy()
                return
            idx = int(dd.get_selected())
            target_id = options[idx][0] if 0 <= idx < len(options) else "root"
            d.destroy()
            self.show_output_notice("Moving playlist...", "ok", 1800)

            def task():
                res = self.backend.move_cloud_playlist_to_folder(pl, target_folder_id=target_id)

                def apply():
                    if bool(res.get("ok")):
                        self.show_output_notice("Playlist moved.", "ok", 2200)
                        self.current_remote_playlist = None
                        self.current_playlist_folder = None
                        self.current_playlist_folder_stack = []
                        self.render_playlists_home()
                    else:
                        self.show_output_notice("Failed to move playlist.", "warn", 2800)
                    return False

                GLib.idle_add(apply)

            Thread(target=task, daemon=True).start()

        dialog.connect("response", _on_response)
        dialog.present()

    def on_remove_single_track_from_remote_playlist(self, track):
        pl = getattr(self, "current_remote_playlist", None)
        if pl is None or track is None:
            return

        def task():
            res = self.backend.remove_tracks_from_cloud_playlist(pl, [track])

            def apply():
                if bool(res.get("ok")):
                    removed = int(res.get("removed", 0) or 0)
                    self.show_output_notice(f"Removed {removed} track", "ok", 2200)
                    # Refresh current remote playlist view
                    self.on_remote_playlist_card_clicked(pl)
                else:
                    self.show_output_notice("Failed to remove track from playlist.", "warn", 2800)
                return False

            GLib.idle_add(apply)

        Thread(target=task, daemon=True).start()

    def on_playlist_track_selected(self, box, row):
        if not row:
            return
        idx = getattr(row, "playlist_track_index", -1)
        tracks = getattr(box, "playlist_tracks", [])
        if not tracks or idx < 0 or idx >= len(tracks):
            return
        self.current_track_list = tracks
        self._set_play_queue(tracks)
        self.play_track(idx)

    def _next_playlist_name(self):
        return "New Playlist"

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

    def on_create_playlist_clicked(self, _btn=None):
        if not getattr(self.backend, "user", None):
            self._show_simple_dialog("Login Required", "Please login first.")
            return
        default_name = self._next_playlist_name()
        folder_rows = [{"id": "root", "path": "Root"}] + list(self.backend.get_all_playlist_folders(limit=1000) or [])
        folder_options = [(str(row.get("id", "root")), str(row.get("path", "Root"))) for row in folder_rows]
        initial_folder_id = "root"
        if getattr(self, "current_playlist_folder", None) is not None:
            initial_folder_id = str(getattr(self.current_playlist_folder, "id", "root") or "root")

        def _submit(name, desc, is_public, folder_id):
            self.show_output_notice("Creating cloud playlist...", "ok", 1600)

            def task():
                pl = self.backend.create_cloud_playlist_in_folder(name, desc, parent_folder_id=folder_id)
                if pl is not None and bool(is_public):
                    try:
                        self.backend.update_cloud_playlist(pl, is_public=True)
                    except Exception:
                        pass

                def apply():
                    if pl is None:
                        self.show_output_notice("Failed to create cloud playlist.", "warn", 2600)
                        return False
                    self.show_output_notice(f"Created playlist: {getattr(pl, 'name', name)}", "ok", 2200)
                    self.render_playlists_home()
                    return False

                GLib.idle_add(apply)

            Thread(target=task, daemon=True).start()

        self._open_cloud_playlist_editor(
            dialog_title="Create playlist",
            save_label="Create",
            initial_title=default_name,
            initial_desc="Created from HiresTI",
            initial_public=False,
            playlist_obj=None,
            folder_options=folder_options,
            initial_folder_id=initial_folder_id,
            on_submit=_submit,
        )

    def _prompt_playlist_pick(self, on_pick):
        if not getattr(self.backend, "user", None):
            self._show_simple_dialog("Login Required", "Please login first.")
            return
        playlists = list(self.backend.get_user_playlists(limit=1000) or [])
        if not playlists:
            created = self.backend.create_cloud_playlist(self._next_playlist_name(), "Created from HiresTI")
            if created is not None:
                on_pick(created, True)
            else:
                self.show_output_notice("Failed to create cloud playlist.", "warn", 2600)
            return

        dialog = Gtk.Dialog(title="Add to Playlist", transient_for=self.win, modal=True)
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        box_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        box_wrap.append(Gtk.Label(label="Select a playlist:", xalign=0))

        names = [getattr(p, "name", None) or "Untitled Playlist" for p in playlists]
        dd = Gtk.DropDown(model=Gtk.StringList.new(names))
        dd.set_selected(0)
        box_wrap.append(dd)
        dedupe_ck = Gtk.CheckButton(label="Auto de-duplicate", active=True)
        box_wrap.append(dedupe_ck)
        root.append(box_wrap)
        action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        new_btn = Gtk.Button(label="New Playlist")
        add_btn = Gtk.Button(label="Add")
        cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
        new_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.APPLY))
        add_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
        action_row.append(cancel_btn)
        action_row.append(new_btn)
        action_row.append(add_btn)
        root.append(action_row)
        dialog.set_child(root)

        def _on_response(d, resp):
            if resp == Gtk.ResponseType.OK:
                idx = dd.get_selected()
                if 0 <= idx < len(playlists):
                    on_pick(playlists[idx], dedupe_ck.get_active())
            elif resp == Gtk.ResponseType.APPLY:
                created = self.backend.create_cloud_playlist(self._next_playlist_name(), "Created from HiresTI")
                if created is not None:
                    on_pick(created, dedupe_ck.get_active())
                else:
                    self.show_output_notice("Failed to create cloud playlist.", "warn", 2600)
            d.destroy()

        dialog.connect("response", _on_response)
        dialog.present()

    def on_add_tracks_to_playlist(self, tracks):
        items = [t for t in (tracks or []) if t is not None]
        if not items:
            return

        def _do_add(playlist_obj, dedupe):
            self.show_output_notice("Adding tracks to cloud playlist...", "ok", 1800)

            def task():
                res = self.backend.add_tracks_to_cloud_playlist(playlist_obj, items, dedupe=bool(dedupe), batch_size=100)

                def apply():
                    if bool(res.get("ok")):
                        added = int(res.get("added", 0) or 0)
                        requested = int(res.get("requested", 0) or 0)
                        skipped = max(0, requested - added)
                        msg = f"Added {added} tracks"
                        if skipped:
                            msg += f" (skipped {skipped})"
                        self.show_output_notice(msg, "ok", 2600)
                    else:
                        self.show_output_notice("Failed to add tracks to cloud playlist.", "warn", 3000)
                    return False

                GLib.idle_add(apply)

            Thread(target=task, daemon=True).start()

        self._prompt_playlist_pick(_do_add)

    def on_add_single_track_to_playlist(self, track):
        if track is None:
            return
        self.on_add_tracks_to_playlist([track])

    def on_add_current_album_to_playlist(self, _btn=None):
        tracks = list(getattr(self, "current_track_list", []) or [])
        if not tracks:
            return
        self.on_add_tracks_to_playlist(tracks)

    def on_search_track_checkbox_toggled(self, _cb, track_index, checked):
        if not isinstance(getattr(self, "search_selected_indices", None), set):
            self.search_selected_indices = set()
        if checked:
            self.search_selected_indices.add(int(track_index))
        else:
            self.search_selected_indices.discard(int(track_index))
        self._update_search_batch_add_state()

    def _update_search_batch_add_state(self):
        btn = getattr(self, "add_selected_tracks_btn", None)
        count = len(getattr(self, "search_selected_indices", set()) or set())
        user_ready = bool(getattr(self.backend, "user", None))
        if btn is not None:
            btn.set_sensitive(count > 0)
            btn.set_label(f"Add Selected ({count})" if count > 0 else "Add Selected")
        like_btn = getattr(self, "like_selected_tracks_btn", None)
        if like_btn is not None:
            like_btn.set_sensitive(user_ready and count > 0)
            like_btn.set_label(f"Like Selected ({count})" if count > 0 else "Like Selected")

    def on_add_selected_search_tracks(self, _btn=None):
        selected = sorted(list(getattr(self, "search_selected_indices", set()) or []))
        tracks = []
        for idx in selected:
            if 0 <= idx < len(self.search_track_data):
                tracks.append(self.search_track_data[idx])
        if not tracks:
            return
        self.on_add_tracks_to_playlist(tracks)

    def on_like_selected_search_tracks(self, _btn=None):
        if not getattr(self.backend, "user", None):
            return
        selected = sorted(list(getattr(self, "search_selected_indices", set()) or []))
        tracks = []
        for idx in selected:
            if 0 <= idx < len(self.search_track_data):
                tracks.append(self.search_track_data[idx])
        if not tracks:
            return

        add_btn = getattr(self, "add_selected_tracks_btn", None)
        like_btn = getattr(self, "like_selected_tracks_btn", None)
        if add_btn is not None:
            add_btn.set_sensitive(False)
        if like_btn is not None:
            like_btn.set_sensitive(False)

        def do():
            liked = 0
            skipped = 0
            failed = 0
            fav_ids = getattr(self.backend, "fav_track_ids", set()) or set()
            for t in tracks:
                track_id = str(getattr(t, "id", "") or "").strip()
                if not track_id:
                    failed += 1
                    continue
                if track_id in fav_ids:
                    skipped += 1
                    continue
                if self.backend.toggle_track_favorite(track_id, True):
                    liked += 1
                else:
                    failed += 1

            def apply():
                self.refresh_visible_track_fav_buttons()
                self.refresh_current_track_favorite_state()
                self._update_search_batch_add_state()
                msg = f"Liked {liked}"
                if skipped:
                    msg += f", skipped {skipped}"
                if failed:
                    msg += f", failed {failed}"
                self.show_output_notice(msg, "ok" if failed == 0 else "warn", 2800)
                return False

            GLib.idle_add(apply)

        Thread(target=do, daemon=True).start()

    def on_search_tracks_prev_page(self, _btn=None):
        self.search_tracks_page = max(0, int(getattr(self, "search_tracks_page", 0) or 0) - 1)
        ui_actions.render_search_tracks_page(self)

    def on_search_tracks_next_page(self, _btn=None):
        self.search_tracks_page = int(getattr(self, "search_tracks_page", 0) or 0) + 1
        ui_actions.render_search_tracks_page(self)

    def _prompt_playlist_name(
        self,
        title,
        initial_name,
        on_submit,
        subtitle=None,
        placeholder=None,
        save_label="Save",
        dialog_size=None,
    ):
        dialog = Gtk.Dialog(title=title, transient_for=self.win, modal=True)
        if dialog_size:
            try:
                dialog.set_default_size(int(dialog_size[0]), int(dialog_size[1]))
            except Exception:
                pass
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=14,
            margin_top=14,
            margin_bottom=14,
            margin_start=14,
            margin_end=14,
        )
        title_lbl = Gtk.Label(label=str(title or ""), xalign=0, css_classes=["home-section-title"])
        root.append(title_lbl)
        if subtitle:
            root.append(Gtk.Label(label=str(subtitle), xalign=0, css_classes=["dim-label"]))
        entry = Gtk.Entry(text=initial_name or "")
        if placeholder:
            entry.set_placeholder_text(str(placeholder))
        entry.connect("activate", lambda _e: dialog.response(Gtk.ResponseType.OK))
        root.append(entry)
        action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        save_btn = Gtk.Button(label=str(save_label or "Save"), css_classes=["suggested-action"])
        cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
        save_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
        action_row.append(cancel_btn)
        action_row.append(save_btn)
        root.append(action_row)
        dialog.set_child(root)

        def _on_response(d, resp):
            if resp == Gtk.ResponseType.OK:
                on_submit(entry.get_text().strip())
            d.destroy()

        dialog.connect("response", _on_response)
        dialog.present()
        entry.grab_focus()

    def on_playlist_start_inline_rename(self, playlist_id):
        self.playlist_rename_mode = True
        self.render_playlist_detail(playlist_id)

    def on_playlist_commit_inline_rename(self, playlist_id, name):
        new_name = (name or "").strip()
        if new_name:
            self.playlist_mgr.rename_playlist(playlist_id, new_name)
        self.playlist_rename_mode = False
        self.render_playlist_detail(playlist_id)

    def on_playlist_cancel_inline_rename(self, playlist_id):
        self.playlist_rename_mode = False
        self.render_playlist_detail(playlist_id)

    def on_playlist_delete_clicked(self, playlist_id):
        dialog = Gtk.Dialog(title="Delete Playlist", transient_for=self.win, modal=True)
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        root.append(Gtk.Label(label="Delete this playlist permanently?", xalign=0))
        action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        delete_btn = Gtk.Button(label="Delete")
        cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
        delete_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
        action_row.append(cancel_btn)
        action_row.append(delete_btn)
        root.append(action_row)
        dialog.set_child(root)

        def _on_response(d, resp):
            if resp == Gtk.ResponseType.OK:
                self.playlist_mgr.delete_playlist(playlist_id)
                self.current_playlist_id = None
                self.render_playlists_home()
            d.destroy()

        dialog.connect("response", _on_response)
        dialog.present()

    def on_playlist_remove_track_clicked(self, playlist_id, track_index):
        self.playlist_mgr.remove_track(playlist_id, track_index)
        self.render_playlist_detail(playlist_id)

    def on_playlist_move_track_clicked(self, playlist_id, track_index, direction):
        self.playlist_mgr.move_track(playlist_id, track_index, direction)
        self.render_playlist_detail(playlist_id)

    def on_playlist_toggle_edit(self, _btn=None):
        self.playlist_edit_mode = not bool(getattr(self, "playlist_edit_mode", False))
        if self.current_playlist_id:
            self.render_playlist_detail(self.current_playlist_id)

    def on_playlist_reorder_track(self, playlist_id, from_index, to_index):
        if self.playlist_mgr.move_track_to(playlist_id, from_index, to_index):
            self.render_playlist_detail(playlist_id)

    def on_history_album_clicked(self, album):
        if album is None:
            return
        self.show_album_details(album)

    def on_history_track_clicked(self, tracks, index):
        if not tracks or index < 0 or index >= len(tracks):
            return
        self.current_track_list = tracks
        self._set_play_queue(tracks)
        self._debug_dump_button_metrics("history-click:before-play")
        self.play_track(index)
        GLib.timeout_add(120, lambda: self._debug_dump_button_metrics("history-click:after-play"))

    def _debug_dump_button_metrics(self, tag="ui"):
        if os.getenv("HIRES_DEBUG_BUTTONS", "0") != "1":
            return False
        if not getattr(self, "win", None):
            return False

        rows = []

        def _walk(widget):
            if isinstance(widget, Gtk.Button):
                classes = ",".join(widget.get_css_classes() or [])
                try:
                    min_h, nat_h, _min_b, _nat_b = widget.measure(Gtk.Orientation.VERTICAL, -1)
                except Exception:
                    min_h, nat_h = -1, -1
                try:
                    alloc_h = widget.get_allocated_height()
                except Exception:
                    alloc_h = -1
                ptr = hex(hash(widget))
                rows.append((ptr, classes, min_h, nat_h, alloc_h))
            child = widget.get_first_child()
            while child is not None:
                _walk(child)
                child = child.get_next_sibling()

        try:
            _walk(self.win)
        except Exception as e:
            logger.warning("BTNDBG %s failed: %s", tag, e)
            return False

        rows.sort(key=lambda r: (r[2], r[3], r[4]))
        logger.warning("BTNDBG %s count=%d", tag, len(rows))
        for ptr, classes, min_h, nat_h, alloc_h in rows:
            if nat_h <= 32 or min_h <= 32 or alloc_h <= 32:
                logger.warning(
                    "BTNDBG %s ptr=%s cls=[%s] min_h=%s nat_h=%s alloc_h=%s",
                    tag,
                    ptr,
                    classes,
                    min_h,
                    nat_h,
                    alloc_h,
                )
        return False

    def on_queue_track_selected(self, box, row):
        if not row:
            return
        idx = getattr(row, "queue_track_index", row.get_index())
        tracks = self._get_active_queue()
        if idx < 0 or idx >= len(tracks):
            return
        self.play_track(idx)

    def on_queue_remove_track_clicked(self, track_index):
        tracks = self._get_active_queue()
        idx = int(track_index)
        if idx < 0 or idx >= len(tracks):
            return
        removed_current = idx == int(getattr(self, "current_track_index", -1) or -1)
        tracks.pop(idx)
        self.play_queue = tracks

        if not tracks:
            self.current_track_index = -1
            self.playing_track = None
            self.playing_track_id = None
            try:
                self.player.stop()
            except Exception:
                pass
            if self.play_btn is not None:
                self.play_btn.set_icon_name("media-playback-start-symbolic")
            self.refresh_current_track_favorite_state()
            GLib.idle_add(self._refresh_queue_views)
            return

        if idx < self.current_track_index:
            self.current_track_index = max(0, self.current_track_index - 1)

        if removed_current:
            new_idx = min(idx, len(tracks) - 1)
            GLib.idle_add(self._refresh_queue_views)
            GLib.idle_add(lambda: self.play_track(new_idx) or False)
            return

        GLib.idle_add(self._refresh_queue_views)
        self._update_track_list_icon()

    def on_queue_clear_clicked(self, _btn=None):
        tracks = self._get_active_queue()
        if not tracks:
            return
        self.play_queue = []
        self.current_track_index = -1
        self.playing_track = None
        self.playing_track_id = None
        try:
            self.player.stop()
        except Exception:
            pass
        if self.play_btn is not None:
            self.play_btn.set_icon_name("media-playback-start-symbolic")
        self.refresh_current_track_favorite_state()
        GLib.idle_add(self._refresh_queue_views)

    def build_daily_mixes(self, days=7, per_day=8):
        per_day = max(6, int(per_day))
        entries = []
        if hasattr(self, "history_mgr") and self.history_mgr is not None:
            entries = self.history_mgr.get_recent_track_entries(limit=400)
            if not entries and getattr(self.backend, "user", None):
                # Backfill for legacy history format (album-only records).
                for alb in self.history_mgr.get_albums()[:24]:
                    tracks = self.backend.get_tracks(alb) or []
                    for t in tracks[:10]:
                        entries.append(
                            {
                                "track_id": getattr(t, "id", None),
                                "track_name": getattr(t, "name", "Unknown Track"),
                                "duration": getattr(t, "duration", 0) or 0,
                                "album_id": getattr(getattr(t, "album", None), "id", getattr(alb, "id", None)),
                                "album_name": getattr(getattr(t, "album", None), "name", getattr(alb, "name", "Unknown Album")),
                                "artist": getattr(getattr(t, "artist", None), "name", "Unknown"),
                                "artist_id": getattr(getattr(t, "artist", None), "id", None),
                                "cover": getattr(getattr(t, "album", None), "cover", getattr(alb, "cover_url", None)),
                            }
                        )
                    if len(entries) >= 400:
                        break
        if not entries:
            self.daily_mix_data = []
            return []

        track_stats = {}
        artist_stats = {}
        album_stats = {}
        meta_by_track = {}
        total = max(1, len(entries))

        for idx, e in enumerate(entries):
            tid = str(e.get("track_id"))
            if not tid:
                continue
            recency = max(0.2, 1.0 - (idx / total))
            track_stats[tid] = track_stats.get(tid, 0.0) + 1.6 + recency

            artist_key = str(e.get("artist_id") or e.get("artist") or "")
            if artist_key:
                artist_stats[artist_key] = artist_stats.get(artist_key, 0.0) + 1.0 + recency * 0.4

            album_key = str(e.get("album_id") or "")
            if album_key:
                album_stats[album_key] = album_stats.get(album_key, 0.0) + 0.8 + recency * 0.3

            if tid not in meta_by_track:
                meta_by_track[tid] = e

        if not meta_by_track:
            self.daily_mix_data = []
            return []

        def _score(tid):
            meta = meta_by_track[tid]
            artist_key = str(meta.get("artist_id") or meta.get("artist") or "")
            album_key = str(meta.get("album_id") or "")
            return (
                track_stats.get(tid, 0.0)
                + 0.9 * artist_stats.get(artist_key, 0.0)
                + 0.5 * album_stats.get(album_key, 0.0)
            )

        sorted_ids = sorted(meta_by_track.keys(), key=_score, reverse=True)
        mixes = []
        today = datetime.now().date()
        used_track_ids = set()

        for day_offset in range(days):
            day = today - timedelta(days=day_offset)
            day_seed = int(day.strftime("%Y%m%d"))
            if not sorted_ids:
                break
            rot = day_seed % len(sorted_ids)
            rotated = sorted_ids[rot:] + sorted_ids[:rot]
            pick_ids = []
            for tid in rotated:
                if tid in used_track_ids:
                    continue
                pick_ids.append(tid)
                if len(pick_ids) >= per_day:
                    break
            if len(pick_ids) < 6:
                break
            tracks = []
            for tid in pick_ids:
                local_track = self.history_mgr.to_local_track(meta_by_track[tid])
                if local_track is not None:
                    tracks.append(local_track)
            if len(tracks) >= 6:
                used_track_ids.update(pick_ids)
                mixes.append(
                    {
                        "date_label": day.strftime("%Y-%m-%d"),
                        "title": "Daily Mix",
                        "tracks": tracks,
                    }
                )

        self.daily_mix_data = mixes
        return mixes

    def on_daily_mix_track_selected(self, box, row):
        if not row:
            return
        track_index = getattr(row, "daily_track_index", -1)
        daily_tracks = getattr(box, "daily_tracks", None)
        if not daily_tracks or track_index < 0 or track_index >= len(daily_tracks):
            return
        self.current_track_list = daily_tracks
        self._set_play_queue(daily_tracks)
        self.play_track(track_index)

    def on_daily_mix_item_activated(self, flow, child):
        if child is None:
            return
        track_index = getattr(child, "daily_track_index", -1)
        daily_tracks = getattr(flow, "daily_tracks", None)
        if not daily_tracks or track_index < 0 or track_index >= len(daily_tracks):
            return
        self.current_track_list = daily_tracks
        self._set_play_queue(daily_tracks)
        self.play_track(track_index)

    def on_nav_selected(self, box, row):
        if row and hasattr(row, "nav_id"):
            self._remember_last_nav(row.nav_id)
        ui_navigation.on_nav_selected(self, box, row)

    def create_album_flow(self):
        section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section", "home-generic-section"])
        self.main_flow = Gtk.FlowBox(
            valign=Gtk.Align.START,
            max_children_per_line=30,
            selection_mode=Gtk.SelectionMode.NONE,
            column_spacing=24,
            row_spacing=28,
            css_classes=["home-flow"],
        )
        self.main_flow.connect("child-activated", self.on_grid_item_activated)
        section_box.append(self.main_flow)
        self.collection_content_box.append(section_box)

    def on_play_pause(self, btn):
        playback_actions.on_play_pause(self, btn)


    def on_next_track(self, btn=None):
        playback_actions.on_next_track(self, btn)

    def on_prev_track(self, btn=None):
        playback_actions.on_prev_track(self, btn)

    def _load_cover_art(self, cover_id_or_url):
        playback_stream_actions.load_cover_art(self, cover_id_or_url)

    def _update_list_ui(self, index):
        """更新列表选中状态。"""
        if self.list_box is None: return

        try:
            row = self.list_box.get_row_at_index(index)
            if row:
                self.list_box.select_row(row)
        except Exception as e:
            logger.warning("List update failed: %s", e)


    def render_lyrics_list(self, lyrics_obj=None, status_msg=None):
        lyrics_playback_actions.render_lyrics_list(self, lyrics_obj, status_msg)


    def play_track(self, index):
        lyrics_playback_actions.play_track(self, index)

    def _get_tidal_image_url(self, uuid, width=320, height=320):
        """将 TIDAL UUID 转换为可访问的图片 URL。"""
        if not uuid: return None
        if isinstance(uuid, str) and ("http" in uuid or "file://" in uuid):
            return uuid

        try:
            path = uuid.replace("-", "/")
            return f"https://resources.tidal.com/images/{path}/{width}x{height}.jpg"
        except Exception as e:
            logger.warning("Failed to build TIDAL image URL from uuid '%s': %s", uuid, e)
            return None

    def on_seek(self, s): 
        self._update_progress_thumb_position()
        if self.is_programmatic_update:
            return
        self._seek_user_interacting = True
        value = float(s.get_value())
        self._seek_pending_value = value
        try:
            self.lbl_current_time.set_text(f"{int(value//60)}:{int(value%60):02d}")
        except Exception:
            pass
        if self._seek_commit_source:
            GLib.source_remove(self._seek_commit_source)
            self._seek_commit_source = 0

        def _commit_seek():
            self._seek_commit_source = 0
            target = self._seek_pending_value
            self._seek_pending_value = None
            try:
                if target is not None:
                    self.player.seek(float(target))
            finally:
                # Never keep seek-interacting state latched on errors, otherwise
                # progress UI can appear frozen.
                self._seek_user_interacting = False
            return False

        # Commit only after dragging value settles.
        self._seek_commit_source = GLib.timeout_add(120, _commit_seek)

    def _update_progress_thumb_position(self):
        if self.scale is None or self.scale_thumb is None:
            return
        try:
            adj = self.scale.get_adjustment()
            lower = float(adj.get_lower())
            upper = float(adj.get_upper())
            value = float(self.scale.get_value())
            width = int(self.scale.get_width())
            if upper <= lower or width <= 0:
                self.scale_thumb.set_margin_start(0)
                self._thumb_smooth_x = None
                return
            ratio = (value - lower) / (upper - lower)
            ratio = max(0.0, min(1.0, ratio))
            thumb_w = 14
            max_x = float(max(0, width - thumb_w))
            raw_x = float(ratio * max_x)

            prev_x = self._thumb_smooth_x
            if prev_x is None:
                smooth_x = raw_x
            elif not self.is_programmatic_update:
                # User drag/seek: follow cursor immediately.
                smooth_x = raw_x
            else:
                # Playback tick: smooth motion and suppress tiny backward jitter.
                if raw_x < prev_x and (prev_x - raw_x) <= 1.5:
                    raw_x = prev_x
                if abs(raw_x - prev_x) > 56.0:
                    # Track switch / hard seek: snap to new position.
                    smooth_x = raw_x
                else:
                    smooth_x = prev_x + (raw_x - prev_x) * 0.38
                    if abs(smooth_x - prev_x) < 0.30:
                        smooth_x = prev_x

            smooth_x = max(0.0, min(max_x, smooth_x))
            self._thumb_smooth_x = smooth_x
            self.scale_thumb.set_margin_start(int(round(smooth_x)))
        except Exception:
            pass

    def _scroll_to_lyric(self, widget):
        lyrics_playback_actions.scroll_to_lyric(self, widget)

    def _restore_paned_position_after_layout(self):
        if self.paned is None:
            return False
        try:
            saved_paned = int(self.settings.get("paned_position", 0) or 0)
        except Exception:
            saved_paned = 0
        if saved_paned > 0 and self.paned.get_position() != saved_paned:
            self.paned.set_position(saved_paned)
        return False

    def update_ui_loop(self):
        return lyrics_playback_actions.update_ui_loop(self)

    def _get_ui_loop_interval_ms(self):
        is_playing = False
        try:
            is_playing = bool(self.player.is_playing())
        except Exception:
            is_playing = False

        if not self.playing_track_id:
            return 280
        if not is_playing:
            revealer = self.viz_revealer
            if revealer is not None and revealer.get_reveal_child():
                return 120
            return 220
        revealer = self.viz_revealer
        if revealer is not None and revealer.get_reveal_child():
            if self._viz_current_page == "lyrics":
                return 25
            return 40
        # No visualizer/lyrics drawer visible: keep UI updates responsive but reduce idle wakeups.
        return 160

    def _schedule_update_ui_loop(self, delay_ms=None):
        source = getattr(self, "_ui_loop_source", 0)
        if source:
            GLib.source_remove(source)
            self._ui_loop_source = 0
        next_delay = int(delay_ms if delay_ms is not None else self._get_ui_loop_interval_ms())

        def _tick():
            self._ui_loop_source = 0
            try:
                keep_running = bool(self.update_ui_loop())
            except Exception:
                logger.exception("UI loop tick failed")
                keep_running = True
            if keep_running:
                self._schedule_update_ui_loop()
            return False

        self._ui_loop_source = GLib.timeout_add(max(20, next_delay), _tick)

    def update_layout_proportions(self, w, p):
        try:
            saved_paned = int(self.settings.get("paned_position", 0) or 0)
        except Exception:
            saved_paned = 0
        if saved_paned > 0:
            s_px = saved_paned
        else:
            s_px = max(int(self.win.get_width() * ui_config.SIDEBAR_RATIO), 240)
        self.paned.set_position(s_px)
        GLib.idle_add(lambda: (self._schedule_viz_handle_realign(), False)[1])

    def _schedule_viz_handle_realign(self):
        # Immediate pass + delayed retries to survive fullscreen/restore re-allocation jitter.
        expanded = bool(getattr(self, "viz_revealer", None) is not None and self.viz_revealer.get_reveal_child())
        self._position_viz_handle(expanded)

        if self._viz_handle_resize_source:
            GLib.source_remove(self._viz_handle_resize_source)
            self._viz_handle_resize_source = 0

        self._viz_handle_resize_retries = 2

        def _retry():
            expanded_now = bool(getattr(self, "viz_revealer", None) is not None and self.viz_revealer.get_reveal_child())
            self._position_viz_handle(expanded_now)
            self._viz_handle_resize_retries -= 1
            if self._viz_handle_resize_retries <= 0:
                self._viz_handle_resize_source = 0
                return False
            return True

        self._viz_handle_resize_source = GLib.timeout_add(120, _retry)
        return False

    def on_paned_position_changed(self, _paned, _param):
        if self.paned is None:
            return
        pos = self.paned.get_position()
        if not isinstance(pos, int) or pos <= 0:
            return
        self.settings["paned_position"] = pos
        self.schedule_save_settings()

    def _update_fav_icon(self, btn, is_active):
        if is_active:
            btn.set_icon_name("hiresti-favorite-symbolic"); btn.add_css_class("active")
        else:
            btn.set_icon_name("hiresti-favorite-outline-symbolic"); btn.remove_css_class("active")

    def refresh_current_track_favorite_state(self):
        btn = getattr(self, "track_fav_btn", None)
        track = getattr(self, "playing_track", None)
        user = getattr(self.backend, "user", None)
        if btn is None:
            return
        if not track or getattr(track, "id", None) is None:
            self._update_fav_icon(btn, False)
            btn.set_sensitive(False)
            btn.set_visible(False)
            return
        btn.set_visible(True)
        if not user:
            self._update_fav_icon(btn, False)
            btn.set_sensitive(False)
            return

        track_id = str(track.id)
        btn.set_sensitive(False)

        def do():
            is_fav = self.backend.is_track_favorite(track_id)

            def apply():
                current = getattr(getattr(self, "playing_track", None), "id", None)
                if str(current) != track_id:
                    return False
                self._update_fav_icon(btn, is_fav)
                btn.set_sensitive(True)
                return False

            GLib.idle_add(apply)

        Thread(target=do, daemon=True).start()

    def create_track_fav_button(self, track, css_classes=None):
        classes = css_classes or ["flat", "circular", "track-heart-btn"]
        btn = Gtk.Button(icon_name="hiresti-favorite-outline-symbolic", css_classes=classes, valign=Gtk.Align.CENTER)
        btn.set_tooltip_text("Favorite Track")
        btn._is_track_fav_btn = True
        track_id = getattr(track, "id", None)
        btn._track_fav_id = str(track_id) if track_id is not None else None
        btn.connect("clicked", self.on_track_row_fav_clicked)
        self._refresh_track_fav_button(btn)
        return btn

    def _refresh_track_fav_button(self, btn):
        track_id = getattr(btn, "_track_fav_id", None)
        user = getattr(self.backend, "user", None)
        if not track_id or not user:
            self._update_fav_icon(btn, False)
            btn.set_sensitive(False)
            return

        btn.set_sensitive(False)

        def do():
            is_fav = self.backend.is_track_favorite(track_id)

            def apply():
                if getattr(btn, "_track_fav_id", None) != track_id:
                    return False
                self._update_fav_icon(btn, is_fav)
                btn.set_sensitive(True)
                return False

            GLib.idle_add(apply)

        Thread(target=do, daemon=True).start()

    def on_track_row_fav_clicked(self, btn):
        track_id = getattr(btn, "_track_fav_id", None)
        if not track_id or not getattr(self.backend, "user", None):
            return

        is_currently_active = "active" in btn.get_css_classes()
        is_add = not is_currently_active
        btn.set_sensitive(False)

        def do():
            ok = self.backend.toggle_track_favorite(track_id, is_add)

            def apply():
                if getattr(btn, "_track_fav_id", None) != track_id:
                    return False
                if ok:
                    self._update_fav_icon(btn, is_add)
                    if str(getattr(getattr(self, "playing_track", None), "id", "")) == track_id:
                        self.refresh_current_track_favorite_state()
                    self.refresh_visible_track_fav_buttons()
                    self.refresh_liked_songs_dashboard()
                btn.set_sensitive(True)
                return False

            GLib.idle_add(apply)

        Thread(target=do, daemon=True).start()

    def refresh_visible_track_fav_buttons(self):
        roots = [
            getattr(self, "track_list", None),
            getattr(self, "playlist_track_list", None),
            getattr(self, "liked_track_list", None),
            getattr(self, "queue_track_list", None),
            getattr(self, "queue_drawer_list", None),
            getattr(self, "res_trk_list", None),
            getattr(self, "res_hist_list", None),
        ]

        def walk(widget):
            if widget is None:
                return
            if isinstance(widget, Gtk.Button) and getattr(widget, "_is_track_fav_btn", False):
                self._refresh_track_fav_button(widget)
            child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
            while child:
                walk(child)
                child = child.get_next_sibling()

        for root in roots:
            walk(root)

    def on_track_fav_clicked(self, btn):
        track = getattr(self, "playing_track", None)
        if track is None or getattr(track, "id", None) is None or not getattr(self.backend, "user", None):
            return
        track_id = str(track.id)
        is_currently_active = "active" in btn.get_css_classes()
        is_add = not is_currently_active
        btn.set_sensitive(False)

        def do():
            ok = self.backend.toggle_track_favorite(track_id, is_add)

            def apply():
                current = getattr(getattr(self, "playing_track", None), "id", None)
                if str(current) != track_id:
                    return False
                if ok:
                    self._update_fav_icon(btn, is_add)
                btn.set_sensitive(True)
                return False

            GLib.idle_add(apply)

        Thread(target=do, daemon=True).start()

    def on_fav_clicked(self, btn):
        if not self.current_album: return
        is_currently_active = "active" in btn.get_css_classes()
        is_add = not is_currently_active
        def do():
            if self.backend.toggle_album_favorite(self.current_album.id, is_add): GLib.idle_add(lambda: self._update_fav_icon(btn, is_add))
        Thread(target=do, daemon=True).start()

    def on_artist_fav_clicked(self, btn):
        if not self.current_selected_artist: return
        art = self.current_selected_artist
        is_currently_active = "active" in btn.get_css_classes()
        is_add = not is_currently_active
        def do():
            if self.backend.toggle_artist_favorite(art.id, is_add): GLib.idle_add(lambda: self._update_fav_icon(btn, is_add))
        Thread(target=do, daemon=True).start()

    def _build_search_view(self):
        ui_views_builders.build_search_view(self)
        ui_actions.render_search_history(self)

    def on_search(self, entry):
        ui_actions.on_search(self, entry)

    def on_search_changed(self, entry):
        ui_actions.on_search_changed(self, entry)

    def clear_search_history(self, btn):
        ui_actions.clear_search_history(self, btn)

    def render_search_results(self, res):
        ui_actions.render_search_results(self, res)

    def on_search_track_selected(self, box, row):
        if not row: return
        idx = getattr(row, "search_track_index", row.get_index())

        if idx < len(self.search_track_data):
            self.current_track_list = self.search_track_data
            self._set_play_queue(self.search_track_data)
            self.play_track(idx)

    def on_search_history_track_selected(self, box, row):
        if not row:
            return
        idx = row.get_index()
        tracks = list(getattr(self, "search_history_track_data", []) or [])
        if idx < 0 or idx >= len(tracks):
            return
        self.current_track_list = tracks
        self._set_play_queue(tracks)
        self.play_track(idx)

    def on_track_selected(self, box, row):
        if not row: return

        idx = row.get_index()
        self._set_play_queue(getattr(self, "current_track_list", []))

        self.play_track(idx)

    def on_back_clicked(self, btn):
        ui_navigation.on_back_clicked(self, btn)

    def on_player_art_clicked(self, gest, n, x, y):
        if self.playing_track:
            track = self.playing_track
            if hasattr(track, 'album') and track.album: self.show_album_details(track.album)

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

    def toggle_visualizer(self, btn):
        """
        [Overlay 适配版]
        """
        is_visible = self.viz_revealer.get_reveal_child()
        target_state = not is_visible
        self._set_visualizer_expanded(target_state)
        self.settings["viz_expanded"] = target_state
        self.schedule_save_settings()

    def _set_visualizer_expanded(self, expanded):
        trace = str(os.getenv("HIRESTI_VIZ_TRACE", "0")).strip().lower() in ("1", "true", "yes", "on")
        if expanded:
            self._viz_trace_open_ts = time.monotonic()
            self._viz_trace_last_cb_ts = 0.0
            self._viz_trace_first_real_logged = False
            self._viz_seed_frame = list(self._last_spectrum_frame) if self._last_spectrum_frame else None
            self._viz_warmup_until = time.monotonic() + float(self._viz_warmup_duration_s)
            if trace:
                logger.info(
                    "VIZ TRACE drawer-open: seed=%s warmup=%.2fs page=%s",
                    bool(self._viz_seed_frame),
                    float(self._viz_warmup_duration_s),
                    str(getattr(self, "_viz_current_page", "spectrum")),
                )
        if self._viz_open_layout_source:
            GLib.source_remove(self._viz_open_layout_source)
            self._viz_open_layout_source = 0
        if self._viz_open_stream_source:
            GLib.source_remove(self._viz_open_stream_source)
            self._viz_open_stream_source = 0
        if self._viz_handle_settle_source:
            GLib.source_remove(self._viz_handle_settle_source)
            self._viz_handle_settle_source = 0
        # 触发 Revealer 动画 (上下滑动)
        self.viz_revealer.set_reveal_child(expanded)
        if expanded:
            self._start_viz_handle_follow_transition()
        if expanded:
            # Enable stream immediately to avoid "never started" corner cases,
            # then keep deferred sync for layout-friendly startup.
            self._sync_spectrum_stream_state()
            # First-open smoothness: let reveal animation run first, then do heavier work.
            def _defer_open_layout():
                self._viz_open_layout_source = 0
                self._apply_overlay_scroll_padding(True)
                self._position_viz_handle(True, animate=False)
                return False

            def _defer_open_stream():
                self._viz_open_stream_source = 0
                self._sync_spectrum_stream_state()
                if self._viz_seed_frame:
                    page = str(getattr(self, "_viz_current_page", "spectrum") or "spectrum")
                    if page == "spectrum" and getattr(self, "viz", None) is not None:
                        self.viz.update_data(self._viz_seed_frame)
                    if page == "lyrics" and getattr(self, "bg_viz", None) is not None:
                        self.bg_viz.update_energy(self._viz_seed_frame)
                return False

            self._viz_open_layout_source = GLib.timeout_add(220, _defer_open_layout)
            self._viz_open_stream_source = GLib.timeout_add(260, _defer_open_stream)
            self._start_viz_placeholder_if_needed()
        else:
            # Closing should stop spectrum stream and restore layout immediately.
            self._sync_spectrum_stream_state()
            self._apply_overlay_scroll_padding(False)
            self._position_viz_handle(False)
            self._stop_viz_placeholder()
            if trace:
                logger.info("VIZ TRACE drawer-close")
        if expanded:
            # Temporarily disable visualizer content fade-in for latency A/B test.
            if self._viz_fade_source:
                GLib.source_remove(self._viz_fade_source)
                self._viz_fade_source = 0
            self._set_viz_content_opacity(1.0)
            self._viz_opened_once = True

        # 图标切换
        if expanded:
            self.viz_btn.set_icon_name("hiresti-pan-down-symbolic")
            self.viz_btn.add_css_class("active")
        else:
            if self._last_spectrum_frame:
                self._viz_seed_frame = list(self._last_spectrum_frame)
            self.viz_btn.set_icon_name("hiresti-pan-up-symbolic")
            self.viz_btn.remove_css_class("active")
            if self._viz_fade_source:
                GLib.source_remove(self._viz_fade_source)
                self._viz_fade_source = 0
            self._set_viz_content_opacity(0.0)

    def _set_viz_content_opacity(self, alpha):
        a = max(0.0, min(1.0, float(alpha)))
        if getattr(self, "viz", None) is not None:
            self.viz.set_opacity(a)
        if getattr(self, "bg_viz", None) is not None:
            # Keep lyrics background always visible enough; avoid "all black" when
            # fade state gets out of sync with GLArea rendering.
            self.bg_viz.set_opacity(max(0.35, a))

    def _start_viz_fade_in(self, duration_ms=1000):
        if self._viz_fade_source:
            GLib.source_remove(self._viz_fade_source)
            self._viz_fade_source = 0
        start_us = GLib.get_monotonic_time()
        duration_us = max(1, int(duration_ms) * 1000)

        def _tick():
            revealer = getattr(self, "viz_revealer", None)
            if revealer is None or not revealer.get_reveal_child():
                self._viz_fade_source = 0
                return False
            elapsed = GLib.get_monotonic_time() - start_us
            t = max(0.0, min(1.0, elapsed / float(duration_us)))
            self._set_viz_content_opacity(t)
            if t >= 1.0:
                self._viz_fade_source = 0
                return False
            return True

        self._viz_fade_source = GLib.timeout_add(16, _tick)

    def _position_viz_handle(self, expanded, animate=True):
        box = getattr(self, "viz_handle_box", None)
        if box is None:
            return
        self._align_viz_handle_to_play_button()
        base_bottom = 0
        target = 0
        if not expanded:
            if animate:
                self._animate_viz_handle_to(base_bottom, duration_ms=180)
            else:
                box.set_margin_bottom(base_bottom)
            return
        panel_h = 0
        revealer = getattr(self, "viz_revealer", None)
        if revealer is not None:
            # During reveal animation this is the live visible height.
            panel_h = int(revealer.get_height() or 0)
        if getattr(self, "viz_root", None) is not None:
            panel_h = max(panel_h, int(self.viz_root.get_height() or 0))
        if panel_h <= 1 and getattr(self, "viz_stack", None) is not None:
            stack_h = int(self.viz_stack.get_height() or 0)
            if stack_h > 1:
                panel_h = stack_h + 36
        if panel_h <= 1:
            panel_h = 286
        target = max(base_bottom, panel_h - 24 + base_bottom - 12 - 7)
        if animate:
            self._animate_viz_handle_to(target, duration_ms=180)
        else:
            box.set_margin_bottom(target)

    def _start_viz_handle_follow_transition(self):
        if self._viz_handle_settle_source:
            GLib.source_remove(self._viz_handle_settle_source)
            self._viz_handle_settle_source = 0
        if self._viz_handle_anim_source:
            GLib.source_remove(self._viz_handle_anim_source)
            self._viz_handle_anim_source = 0
        revealer = getattr(self, "viz_revealer", None)
        box = getattr(self, "viz_handle_box", None)
        if revealer is None:
            return
        if box is None:
            return
        duration_ms = int(revealer.get_transition_duration() or 220)
        start_us = GLib.get_monotonic_time()
        # Keep watcher alive a bit beyond revealer transition; position is
        # computed from live revealer height every frame, so no lag drift.
        span_us = max(120_000, (duration_ms + 120) * 1000)

        def _tick():
            rev = getattr(self, "viz_revealer", None)
            if rev is None or (not rev.get_reveal_child()):
                self._viz_handle_settle_source = 0
                return False
            live_h = int(rev.get_height() or 0)
            if live_h <= 1:
                live_h = int(getattr(self, "viz_root", None).get_height() or 0) if getattr(self, "viz_root", None) is not None else 0
            cur = max(0, live_h - 24 - 12 - 7)
            self._align_viz_handle_to_play_button()
            box.set_margin_bottom(max(0, cur))
            elapsed = GLib.get_monotonic_time() - start_us
            if elapsed >= span_us:
                self._viz_handle_settle_source = 0
                # Final settle to exact layout target.
                self._position_viz_handle(True, animate=False)
                return False
            return True

        self._viz_handle_settle_source = GLib.timeout_add(16, _tick)

    def _align_viz_handle_to_play_button(self):
        box = getattr(self, "viz_handle_box", None)
        play_btn = getattr(self, "play_btn", None)
        overlay = getattr(self, "body_overlay", None)
        if box is None or play_btn is None or overlay is None:
            return
        try:
            ok, rect = play_btn.compute_bounds(overlay)
        except Exception:
            return
        if not ok or rect is None:
            return
        viz_btn = getattr(self, "viz_btn", None)
        handle_w = int(box.get_width() or (viz_btn.get_width() if viz_btn is not None else 0) or 50)
        overlay_w = int(overlay.get_width() or 0)
        center_x = float(rect.get_x()) + (float(rect.get_width()) / 2.0)
        target_start = int(round(center_x - (handle_w / 2.0)))
        if overlay_w > 0:
            target_start = max(0, min(max(0, overlay_w - handle_w), target_start))
        box.set_halign(Gtk.Align.START)
        box.set_margin_start(target_start)
        box.set_margin_end(0)

    def _animate_viz_handle_to(self, target_bottom, duration_ms=180):
        box = getattr(self, "viz_handle_box", None)
        if box is None:
            return
        try:
            target = int(target_bottom)
        except Exception:
            target = 0
        target = max(0, min(2000, target))
        start = int(box.get_margin_bottom() or 0)
        if self._viz_handle_anim_source:
            GLib.source_remove(self._viz_handle_anim_source)
            self._viz_handle_anim_source = 0
        if duration_ms <= 0 or start == target:
            box.set_margin_bottom(target)
            return

        start_us = GLib.get_monotonic_time()
        span_us = max(1, int(duration_ms) * 1000)

        def _tick():
            elapsed = GLib.get_monotonic_time() - start_us
            t = min(1.0, max(0.0, float(elapsed) / float(span_us)))
            # Ease-out curve for a natural "pushed out" feeling.
            eased = 1.0 - ((1.0 - t) * (1.0 - t))
            cur = int(round(start + (target - start) * eased))
            box.set_margin_bottom(max(0, cur))
            if t >= 1.0:
                self._viz_handle_anim_source = 0
                return False
            return True

        self._viz_handle_anim_source = GLib.timeout_add(16, _tick)

if __name__ == "__main__":
    setup_logging()
    TidalApp().run(None)
