import os
import logging
import time
from datetime import datetime, timedelta
os.environ["MESA_LOG_LEVEL"] = "error"

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, Pango
import webbrowser
from threading import Thread, current_thread, main_thread
from tidal_backend import TidalBackend
from audio_player import AudioPlayer
from models import HistoryManager, PlaylistManager
from signal_path import AudioSignalPathWindow
import utils
import ui_config
from ui import builders as ui_builders
from ui import views_builders as ui_views_builders
from actions import ui_actions
from actions import ui_navigation
from actions import playback_actions
from actions import audio_settings_actions
from actions import lyrics_playback_actions
from actions import playback_stream_actions
from lyrics_manager import LyricsManager
from app_logging import setup_logging
from app_settings import load_settings, save_settings as persist_settings

logger = logging.getLogger(__name__)

try:
    import pystray
    from PIL import Image
except Exception:
    pystray = None
    Image = None

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
        self.current_selected_artist = None
        self.list_box = None
        self.output_status_label = None
        self.output_recover_btn = None
        self.output_notice_revealer = None
        self.output_notice_icon = None
        self.output_notice_label = None
        self._output_notice_source = 0
        self._viz_handle_anim_source = 0
        self._viz_handle_settle_source = 0
        self._viz_handle_resize_source = 0
        self._viz_handle_resize_retries = 0
        self._last_output_state = None
        self._last_output_error = None
        self.network_status_label = None
        self.decoder_status_label = None
        self.events_btn = None
        self._diag_events = []
        self._diag_health = {"network": "idle", "decoder": "idle", "output": "idle"}
        self._diag_pop = None
        self._diag_text = None
        self.search_content_box = None
        self.add_playlist_btn = None
        self.add_selected_tracks_btn = None
        self.search_selected_indices = set()
        self.collection_base_margin_bottom = 32
        self.track_list_base_margin_bottom = 32
        self.search_base_margin_bottom = 32
        self.daily_mix_data = []
        self._tray_icon = None
        self._tray_ready = False
        self._allow_window_close = False
        self._thumb_smooth_x = None

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
            self.show_output_notice("Audio device changed, reconnecting...", "switching", 2400)
            return
        if state == "active" and prev_state in ("switching", "fallback", "error"):
            self.show_output_notice("Audio output reconnected", "ok", 2200)
            return
        if state == "fallback":
            self.show_output_notice("Primary output unavailable, switched to fallback", "warn", 3200)
            return
        if state == "error":
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

        self.player = AudioPlayer(
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
        self._play_request_id = 0
        self._settings_save_source = 0
        self._playing_pulse_source = 0
        self._playing_pulse_on = False
        self._home_sections_cache = None
        self.stream_prefetch_cache = {}
        self._init_ui_refs()
        
        # Mini Mode 状态与尺寸记忆
        self.is_mini_mode = False
        self.saved_width = ui_config.WINDOW_WIDTH
        self.saved_height = ui_config.WINDOW_HEIGHT

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
        self.save_settings()
        if self.player is not None:
            self.player.cleanup()
        super().do_shutdown()

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

        self._apply_spectrum_theme_by_index(self.settings.get("spectrum_theme", 0), update_dropdown=True)
        self._apply_viz_bars_by_count(self.settings.get("viz_bar_count", 32), update_dropdown=True)
        self._apply_viz_profile_by_index(self.settings.get("viz_profile", 1), update_dropdown=True)
        self._apply_viz_effect_by_index(self.settings.get("viz_effect", 3), update_dropdown=True)
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

    def on_viz_bars_changed(self, dd, _param):
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
        if not isinstance(idx, int) or idx < 0 or idx >= len(names):
            idx = 0
        self.viz.set_effect(names[idx])
        self.settings["viz_effect"] = idx
        if update_dropdown and self.viz_effect_dd is not None:
            self.viz_effect_dd.set_selected(idx)

    def on_viz_effect_changed(self, dd, _param):
        idx = dd.get_selected()
        self._apply_viz_effect_by_index(idx, update_dropdown=False)
        self.schedule_save_settings()

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
        idx = dd.get_selected()
        self._apply_viz_profile_by_index(idx, update_dropdown=False)
        self.schedule_save_settings()

    def on_spectrum_theme_changed(self, dd, _param):
        idx = dd.get_selected()
        self._apply_spectrum_theme_by_index(idx, update_dropdown=False)
        self.schedule_save_settings()

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
        is_spectrum = page == "spectrum"
        is_lyrics = page == "lyrics"
        self.viz_theme_dd.set_visible(is_spectrum)
        if self.viz_bars_dd is not None:
            self.viz_bars_dd.set_visible(is_spectrum)
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
        
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icons_path = os.path.join(os.path.dirname(__file__), "icons")
        if os.path.exists(icons_path):
            icon_theme.add_search_path(icons_path)

        provider = Gtk.CssProvider()
        logo_svg = os.path.join(os.path.dirname(__file__), "icons", "hicolor", "scalable", "apps", "hiresti.svg")
        css_data = ui_config.CSS_DATA.replace("__HIRESTI_LOGO_SVG__", logo_svg.replace("\\", "/"))
        provider.load_from_data(css_data.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

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

        GLib.timeout_add(20, self.update_ui_loop)
        GLib.timeout_add(1000, self._refresh_output_status_loop)
        self._init_tray_icon()

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
        ui_views_builders.toggle_login_view(self, logged_in)

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
        if not self.viz_revealer.get_reveal_child():
            return
        current_page = self.viz_stack.get_visible_child_name()
        if current_page == "lyrics" and self.bg_viz is not None:
            self.bg_viz.update_energy(magnitudes)
        if current_page == "spectrum" and self.viz is not None:
            self.viz.update_data(magnitudes)

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
        else:
            u, f = self.backend.start_oauth(); webbrowser.open(u)
            def login_thread():
                if self.backend.finish_login(f):
                    GLib.idle_add(self.on_login_success)
            Thread(target=login_thread, daemon=True).start()

    def on_logout_clicked(self, btn):
        self.user_popover.popdown()
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
        return True

    def _force_driver_selection(self, keyword):
        model = self.driver_dd.get_model()
        for i in range(model.get_n_items()):
            if keyword in model.get_item(i).get_string(): self.driver_dd.set_selected(i); break

    def update_tech_label(self, info):
        fmt = info.get('fmt_str', '')
        codec = info.get('codec', '-')
        if not fmt and (not codec or codec in ["-", "Loading..."]):
            self.lbl_tech.set_text("")
            self.lbl_tech.set_tooltip_text(None)
            self.lbl_tech.remove_css_class("tech-label")
            for cls in ("tech-state-ok", "tech-state-mixed", "tech-state-warn"):
                self.lbl_tech.remove_css_class(cls)
            self.lbl_tech.set_visible(True)
            return

        display_codec = codec if codec and codec not in ["-", "Loading..."] else "PCM"

        rate_depth = fmt
        if "|" in fmt:
            parts = [p.strip() for p in fmt.split("|")]
            if len(parts) >= 2:
                rate = parts[0]
                depth = parts[1].replace("bit", "-bit")
                rate_depth = f"{depth}/{rate}"

        bitrate = int(info.get("bitrate", 0) or 0)
        bitrate_text = f" • {bitrate//1000}k" if bitrate > 0 else ""

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
            f"{display_codec} | {fmt} | {bitrate//1000}kbps | {dev_name} | output={output_state}"
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

        def task():
            tracks = list(self.backend.get_favorite_tracks(limit=500))
            try:
                self.backend.fav_track_ids = {
                    str(getattr(t, "id", ""))
                    for t in tracks
                    if getattr(t, "id", None) is not None
                }
            except Exception:
                pass
            self.liked_tracks_last_fetch_ts = time.time()

            def _apply():
                current = self.nav_list.get_selected_row() if self.nav_list is not None else None
                if not current or getattr(current, "nav_id", None) != "liked_songs":
                    return False
                self.render_liked_songs_dashboard(tracks)
                return False

            GLib.idle_add(_apply)

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
        if show:
            self.render_queue_drawer()
        revealer.set_reveal_child(show)
        if getattr(self, "queue_backdrop", None) is not None:
            self.queue_backdrop.set_visible(show)
        self._sync_queue_handle_state(show)

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
        if hasattr(self, "grid_title_label") and self.grid_title_label is not None:
            self.grid_title_label.set_text("Playlists")
            self.grid_title_label.set_visible(True)
        if hasattr(self, "grid_subtitle_label") and self.grid_subtitle_label is not None:
            self.grid_subtitle_label.set_text("Create and manage your local playlists")
            self.grid_subtitle_label.set_visible(True)
        ui_actions.render_playlists_home(self)

    def render_playlist_detail(self, playlist_id):
        ui_actions.render_playlist_detail(self, playlist_id)

    def on_playlist_card_clicked(self, playlist_id):
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
        creator_name = getattr(creator, "name", "TIDAL")
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
        playlists = self.playlist_mgr.list_playlists() if hasattr(self, "playlist_mgr") else []
        max_n = 0
        for p in playlists:
            name = str(p.get("name", "") or "").strip()
            if not name.startswith("Playlist "):
                continue
            suffix = name[len("Playlist "):].strip()
            if suffix.isdigit():
                n = int(suffix)
                if n > max_n:
                    max_n = n
        return f"Playlist {max_n + 1}"

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
        default_name = self._next_playlist_name()
        dialog = Gtk.Dialog(title="Create Playlist", transient_for=self.win, modal=True)
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        root.append(Gtk.Label(label="Playlist name:", xalign=0))
        name_entry = Gtk.Entry(text=default_name)
        name_entry.set_activates_default(True)
        root.append(name_entry)

        action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        create_btn = Gtk.Button(label="Create")
        create_btn.add_css_class("suggested-action")
        cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
        create_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
        action_row.append(cancel_btn)
        action_row.append(create_btn)
        root.append(action_row)
        dialog.set_child(root)

        def _on_response(d, resp):
            if resp != Gtk.ResponseType.OK:
                d.destroy()
                return

            name = str(name_entry.get_text() or "").strip() or default_name
            d.destroy()

            p = self.playlist_mgr.create_playlist(name)
            self.current_playlist_id = p.get("id")
            self.render_playlists_home()

        dialog.connect("response", _on_response)
        dialog.present()

    def _prompt_playlist_pick(self, on_pick):
        playlists = self.playlist_mgr.list_playlists() if hasattr(self, "playlist_mgr") else []
        if not playlists:
            created = self.playlist_mgr.create_playlist(self._next_playlist_name())
            on_pick(created.get("id"), True)
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

        names = [p.get("name", "Untitled Playlist") for p in playlists]
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
                    on_pick(playlists[idx].get("id"), dedupe_ck.get_active())
            elif resp == Gtk.ResponseType.APPLY:
                created = self.playlist_mgr.create_playlist(self._next_playlist_name())
                on_pick(created.get("id"), dedupe_ck.get_active())
            d.destroy()

        dialog.connect("response", _on_response)
        dialog.present()

    def on_add_tracks_to_playlist(self, tracks):
        items = [t for t in (tracks or []) if t is not None]
        if not items:
            return

        def _do_add(playlist_id, dedupe):
            for t in items:
                cover_url = self.backend.get_artwork_url(t, 320)
                self.playlist_mgr.add_track(playlist_id, t, cover_url=cover_url, dedupe=dedupe)
            if self.current_playlist_id and str(self.current_playlist_id) == str(playlist_id):
                self.render_playlist_detail(playlist_id)

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
        if btn is None:
            return
        count = len(getattr(self, "search_selected_indices", set()) or set())
        btn.set_sensitive(count > 0)
        btn.set_label(f"Add Selected ({count})" if count > 0 else "Add Selected")

    def on_add_selected_search_tracks(self, _btn=None):
        selected = sorted(list(getattr(self, "search_selected_indices", set()) or []))
        tracks = []
        for idx in selected:
            if 0 <= idx < len(self.search_track_data):
                tracks.append(self.search_track_data[idx])
        if not tracks:
            return
        self.on_add_tracks_to_playlist(tracks)

    def _prompt_playlist_name(self, title, initial_name, on_submit):
        dialog = Gtk.Dialog(title=title, transient_for=self.win, modal=True)
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        entry = Gtk.Entry(text=initial_name or "")
        entry.connect("activate", lambda _e: dialog.response(Gtk.ResponseType.OK))
        root.append(entry)
        action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        save_btn = Gtk.Button(label="Save")
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
        self.play_track(index)

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
        if not self.is_programmatic_update: self.player.seek(s.get_value())

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
        idx = row.get_index()

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
        # 触发 Revealer 动画 (上下滑动)
        self.viz_revealer.set_reveal_child(expanded)
        self._apply_overlay_scroll_padding(expanded)
        self._position_viz_handle(expanded)
        if self._viz_handle_settle_source:
            GLib.source_remove(self._viz_handle_settle_source)
            self._viz_handle_settle_source = 0
        if expanded:
            def _settle_handle():
                self._viz_handle_settle_source = 0
                self._position_viz_handle(True)
                return False
            # Reposition once after layout settles; avoids first-open mismatch.
            self._viz_handle_settle_source = GLib.timeout_add(220, _settle_handle)

        # 图标切换
        if expanded:
            self.viz_btn.set_icon_name("hiresti-pan-down-symbolic")
            self.viz_btn.add_css_class("active")
            if self.viz is not None:
                self.viz.queue_draw()
        else:
            self.viz_btn.set_icon_name("hiresti-pan-up-symbolic")
            self.viz_btn.remove_css_class("active")

    def _position_viz_handle(self, expanded):
        box = getattr(self, "viz_handle_box", None)
        if box is None:
            return
        self._align_viz_handle_to_play_button()
        base_bottom = 0
        target = 0
        if not expanded:
            self._animate_viz_handle_to(base_bottom, duration_ms=180)
            return
        panel_h = 0
        if getattr(self, "viz_root", None) is not None:
            panel_h = int(self.viz_root.get_height() or 0)
        if panel_h <= 1 and getattr(self, "viz_stack", None) is not None:
            stack_h = int(self.viz_stack.get_height() or 0)
            if stack_h > 1:
                panel_h = stack_h + 36
        if panel_h <= 1:
            panel_h = 286
        target = max(base_bottom, panel_h - 24 + base_bottom - 12 - 7)
        self._animate_viz_handle_to(target, duration_ms=180)

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
