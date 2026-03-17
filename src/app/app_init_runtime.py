"""Runtime initialization pipeline for TidalApp.__init__."""

import logging
import os

from gi.repository import GLib

from _rust.audio import create_audio_engine
from backend import TidalBackend
from core.constants import CacheSettings
from core.settings import load_settings
from models import HistoryManager, PlaylistManager
from services.dsp_presets import DspPresetManager
from services.lyrics import LyricsManager
from services.scrobbler import ScrobblerService
from ui import config as ui_config
from utils.paths import get_cache_dir, get_config_dir

logger = logging.getLogger(__name__)


def _init_paths_and_settings(self):
    self.backend = TidalBackend()
    self._cache_root = get_cache_dir()
    self._config_root = get_config_dir()
    os.makedirs(self._cache_root, exist_ok=True)
    os.makedirs(self._config_root, exist_ok=True)
    self._lv2_plugin_cache_file = os.path.join(self._cache_root, "lv2_plugins.json")
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

    self.scrobbler = ScrobblerService()
    self.scrobbler.configure(self.settings)
    logger.info("ScrobblerService initialized")

    saved_rt_profile = self.settings.get(
        "alsa_mmap_realtime_priority",
        self.ALSA_MMAP_REALTIME_PRIORITY_DEFAULT,
    )
    if saved_rt_profile not in self.ALSA_MMAP_REALTIME_PRIORITY_MAP:
        saved_rt_profile = self.ALSA_MMAP_REALTIME_PRIORITY_DEFAULT
    self.player.set_alsa_mmap_realtime_priority(
        self.ALSA_MMAP_REALTIME_PRIORITY_MAP[saved_rt_profile]
    )
    logger.info(
        "ALSA mmap realtime priority applied: priority=%d (startup, profile=%s)",
        int(self.ALSA_MMAP_REALTIME_PRIORITY_MAP[saved_rt_profile]),
        saved_rt_profile,
    )

    saved_profile = self.settings.get("latency_profile", "Standard (100ms)")
    if saved_profile not in self.LATENCY_MAP:
        saved_profile = "Standard (100ms)"
    buf_ms, lat_ms = self.LATENCY_MAP[saved_profile]
    self.player.set_alsa_latency(buf_ms, lat_ms)
    logger.info(
        "Audio latency profile applied: buffer=%dms latency=%dms (startup, viz offset unchanged=%dms, profile=%s)",
        int(buf_ms),
        int(lat_ms),
        int(getattr(self.player, "visual_sync_offset_ms", 0) or 0),
        saved_profile,
    )

    self.history_mgr = HistoryManager(base_dir=self._cache_root, scope_key=self._account_scope)
    self.playlist_mgr = PlaylistManager(base_dir=self._cache_root, scope_key=self._account_scope)
    self.dsp_preset_mgr = DspPresetManager(config_dir=self._config_root)
    logger.info("DspPresetManager initialized")
    self.cache_dir = os.path.join(self._cache_root, "covers")
    os.makedirs(self.cache_dir, exist_ok=True)
    self.audio_cache_dir = os.path.join(self._cache_root, "audio")
    os.makedirs(self.audio_cache_dir, exist_ok=True)
    self.audio_cache_tracks = int(
        self.settings.get("audio_cache_tracks", CacheSettings.DEFAULT_AUDIO_TRACKS) or 0
    )
    saved_dsp_order = list(self.settings.get("dsp_order", ["peq", "convolver", "tape", "tube", "widener"]) or [])
    if hasattr(self.player, "set_dsp_order"):
        try:
            self.player.set_dsp_order(saved_dsp_order)
        except Exception:
            logger.debug("set_dsp_order failed during startup", exc_info=True)
    saved_peq_bands = list(self.settings.get("dsp_peq_bands", [0.0] * 10) or [])
    while len(saved_peq_bands) < 10:
        saved_peq_bands.append(0.0)
    saved_peq_bands = [float(v or 0.0) for v in saved_peq_bands[:10]]
    saved_peq_enabled = bool(self.settings.get("dsp_peq_enabled", False))
    if hasattr(self.player, "set_eq_band"):
        for idx, gain in enumerate(saved_peq_bands):
            try:
                self.player.set_eq_band(idx, gain)
            except Exception:
                logger.debug("set_eq_band failed during startup", exc_info=True)
    if hasattr(self.player, "set_peq_enabled"):
        try:
            self.player.set_peq_enabled(saved_peq_enabled)
        except Exception:
            logger.debug("set_peq_enabled failed during startup", exc_info=True)
    saved_convolver_path = str(self.settings.get("dsp_convolver_path", "") or "").strip()
    saved_convolver_enabled = bool(self.settings.get("dsp_convolver_enabled", False))
    if saved_convolver_path and hasattr(self.player, "load_convolver_ir"):
        try:
            loaded = bool(self.player.load_convolver_ir(saved_convolver_path))
        except Exception:
            loaded = False
            logger.debug("load_convolver_ir failed during startup", exc_info=True)
        if loaded and hasattr(self.player, "set_convolver_enabled"):
            try:
                self.player.set_convolver_enabled(saved_convolver_enabled)
            except Exception:
                logger.debug("set_convolver_enabled failed during startup", exc_info=True)
            saved_mix = int(self.settings.get("dsp_convolver_mix", 100) or 100)
            saved_pre_delay = int(self.settings.get("dsp_convolver_pre_delay_ms", 0) or 0)
            if hasattr(self.player, "set_convolver_mix"):
                try:
                    self.player.set_convolver_mix(saved_mix / 100.0)
                except Exception:
                    logger.debug("set_convolver_mix failed during startup", exc_info=True)
            if hasattr(self.player, "set_convolver_pre_delay"):
                try:
                    self.player.set_convolver_pre_delay(float(saved_pre_delay))
                except Exception:
                    logger.debug("set_convolver_pre_delay failed during startup", exc_info=True)
        elif not loaded:
            self.settings["dsp_convolver_path"] = ""
            self.settings["dsp_convolver_enabled"] = False
    saved_resampler_enabled = bool(self.settings.get("dsp_resampler_enabled", False))
    saved_resampler_rate = int(self.settings.get("dsp_resampler_target_rate", 0) or 0)
    saved_resampler_quality = int(self.settings.get("dsp_resampler_quality", 10) or 10)
    if hasattr(self.player, "set_resampler_quality"):
        try:
            self.player.set_resampler_quality(saved_resampler_quality)
        except Exception:
            logger.debug("set_resampler_quality failed during startup", exc_info=True)
    if saved_resampler_rate > 0 and hasattr(self.player, "set_resampler_target_rate"):
        try:
            self.player.set_resampler_target_rate(saved_resampler_rate)
        except Exception:
            logger.debug("set_resampler_target_rate failed during startup", exc_info=True)
    if hasattr(self.player, "set_resampler_enabled"):
        try:
            self.player.set_resampler_enabled(saved_resampler_enabled)
        except Exception:
            logger.debug("set_resampler_enabled failed during startup", exc_info=True)
    saved_tape_drive = int(self.settings.get("dsp_tape_drive", 30) or 30)
    saved_tape_tone = int(self.settings.get("dsp_tape_tone", 60) or 60)
    saved_tape_warmth = int(self.settings.get("dsp_tape_warmth", 40) or 40)
    saved_tape_enabled = bool(self.settings.get("dsp_tape_enabled", False))
    if hasattr(self.player, "set_tape_drive"):
        try:
            self.player.set_tape_drive(saved_tape_drive)
            self.player.set_tape_tone(saved_tape_tone)
            self.player.set_tape_warmth(saved_tape_warmth)
            self.player.set_tape_enabled(saved_tape_enabled)
        except Exception:
            logger.debug("restore tape settings failed during startup", exc_info=True)
    saved_tube_drive = int(self.settings.get("dsp_tube_drive", 28) or 28)
    saved_tube_bias = int(self.settings.get("dsp_tube_bias", 55) or 55)
    saved_tube_sag = int(self.settings.get("dsp_tube_sag", 18) or 18)
    saved_tube_air = int(self.settings.get("dsp_tube_air", 52) or 52)
    saved_tube_enabled = bool(self.settings.get("dsp_tube_enabled", False))
    if hasattr(self.player, "set_tube_drive"):
        try:
            self.player.set_tube_drive(saved_tube_drive)
            self.player.set_tube_bias(saved_tube_bias)
            self.player.set_tube_sag(saved_tube_sag)
            self.player.set_tube_air(saved_tube_air)
            self.player.set_tube_enabled(saved_tube_enabled)
        except Exception:
            logger.debug("restore tube settings failed during startup", exc_info=True)
    saved_widener_width = int(self.settings.get("dsp_widener_width", 125) or 125)
    saved_widener_enabled = bool(self.settings.get("dsp_widener_enabled", False))
    saved_widener_bass_mono_freq = int(self.settings.get("dsp_widener_bass_mono_freq", 120) or 120)
    saved_widener_bass_mono_amount = int(self.settings.get("dsp_widener_bass_mono_amount", 100) or 100)
    if hasattr(self.player, "set_widener_width"):
        try:
            self.player.set_widener_width(saved_widener_width)
            self.player.set_widener_bass_mono_freq(saved_widener_bass_mono_freq)
            self.player.set_widener_bass_mono_amount(saved_widener_bass_mono_amount)
            self.player.set_widener_enabled(saved_widener_enabled)
        except Exception:
            logger.debug("restore widener settings failed during startup", exc_info=True)
    saved_lv2_slots = self.settings.get("dsp_lv2_slots") or []
    if saved_lv2_slots and hasattr(self.player, "lv2_restore_slots"):
        try:
            self.player.lv2_restore_slots(saved_lv2_slots)
        except Exception:
            logger.debug("restore lv2 slots failed during startup", exc_info=True)
    elif saved_lv2_slots and hasattr(self.player, "lv2_restore_slot"):
        try:
            for slot in saved_lv2_slots:
                sid = slot.get("slot_id", "")
                uri = slot.get("uri", "")
                if sid and uri:
                    self.player.lv2_restore_slot(
                        sid, uri,
                        enabled=slot.get("enabled", True),
                        port_values=slot.get("port_values", {}),
                    )
        except Exception:
            logger.debug("restore lv2 slots failed during startup", exc_info=True)
    limiter_threshold = int(self.settings.get("dsp_limiter_threshold", 85) or 85)
    limiter_ratio = int(self.settings.get("dsp_limiter_ratio", 20) or 20)
    try:
        self.player.set_limiter_threshold(float(limiter_threshold) / 100.0)
        self.player.set_limiter_ratio(float(limiter_ratio))
        self.player.set_limiter_enabled(bool(self.settings.get("dsp_limiter_enabled", False)))
    except Exception:
        logger.debug("restore limiter settings failed during startup", exc_info=True)
    try:
        self.player.set_dsp_enabled(bool(self.settings.get("dsp_enabled", True)))
    except Exception:
        logger.debug("restore dsp master state failed during startup", exc_info=True)
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
    self.ignore_output_bit_depth_change = False
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
    self._genres_definitions = None
    self._genres_tab_cache = {}
    self._genres_cache_time = 0.0
    self._genres_selected_tab = ""
    self._moods_definitions = None
    self._moods_tab_cache = {}
    self._moods_cache_time = 0.0
    self._moods_selected_tab = ""
    self.stream_prefetch_cache = {}
    self.eq_band_values = list(self.settings.get("dsp_peq_bands", [0.0] * 10) or [])
    while len(self.eq_band_values) < 10:
        self.eq_band_values.append(0.0)
    self.eq_band_values = [float(v or 0.0) for v in self.eq_band_values[:10]]
    self._eq_ui_syncing = False
    self._volume_ui_syncing = False
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
    if hasattr(self, "_init_remote_control_state"):
        self._init_remote_control_state()
