"""Runtime initialization pipeline for TidalApp.__init__."""

import logging
import os

from gi.repository import GLib

from _rust.audio import create_audio_engine
from backend import TidalBackend
from core.constants import CacheSettings
from core.settings import load_settings
from models import HistoryManager, PlaylistManager
from services.lyrics import LyricsManager
from ui import config as ui_config
from utils.paths import get_cache_dir, get_config_dir

logger = logging.getLogger(__name__)


def _init_paths_and_settings(self):
    self.backend = TidalBackend()
    self._cache_root = get_cache_dir()
    self._config_root = get_config_dir()
    os.makedirs(self._config_root, exist_ok=True)
    self._account_scope = "guest"

    # Migrate settings.json from old cache location to config dir (one-time).
    old_settings = os.path.join(self._cache_root, "settings.json")
    new_settings = os.path.join(self._config_root, "settings.json")
    if os.path.exists(old_settings) and not os.path.exists(new_settings):
        try:
            os.rename(old_settings, new_settings)
            logger.info("Migrated settings.json: %s -> %s", old_settings, new_settings)
        except Exception as e:
            logger.warning("Settings migration failed: %s", e)

    self.settings_file = new_settings
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
    self.shuffle_indices = []  # 用来存随机播放的顺序列表


def _init_audio_and_data_services(self):
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
    if saved_profile not in self.LATENCY_MAP:
        saved_profile = "Standard (100ms)"
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
    self.audio_cache_tracks = int(
        self.settings.get("audio_cache_tracks", CacheSettings.DEFAULT_AUDIO_TRACKS) or 0
    )
    self._schedule_cache_maintenance()


def _init_runtime_state(self):
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


def init_runtime(self):
    GLib.set_application_name("HiresTI")
    GLib.set_prgname("HiresTI")
    self.app_version = self._detect_app_version()
    _init_paths_and_settings(self)
    _init_audio_and_data_services(self)
    _init_runtime_state(self)
