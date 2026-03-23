import json
import logging
import os
from dataclasses import dataclass, field, fields
from typing import Any, Optional

from core.constants import AlsaMmapRealtimePriority, VisualizerSettings

logger = logging.getLogger(__name__)

CURRENT_SETTINGS_VERSION = 7
DSP_REORDERABLE_MODULES = ["peq", "convolver", "tape", "tube", "widener"]
PEQ_BAND_COUNT = 10


@dataclass
class SettingsSchema:
    """Settings schema using dataclass for declarative validation."""

    settings_version: int = CURRENT_SETTINGS_VERSION
    driver: str = "Auto (Default)"
    device: str = "Default Output"
    bit_perfect: bool = False
    exclusive_lock: bool = False
    latency_profile: str = "Standard (100ms)"
    alsa_mmap_realtime_priority: str = AlsaMmapRealtimePriority.DEFAULT_LABEL
    output_bit_depth: str = "Auto"
    volume: int = 80
    play_mode: int = 0
    last_nav: str = "home"
    last_view: str = "grid_view"
    viz_expanded: bool = False
    spectrum_theme: int = 0
    viz_frequency_scale: int = 0
    viz_bar_count: int = 32
    viz_profile: int = 2
    viz_effect: int = 3
    lyrics_font_preset: int = 1
    lyrics_bg_motion: int = 1
    lyrics_user_offset_ms: int = 0
    viz_sync_offset_ms: int = 0
    viz_sync_device_offsets: dict = field(default_factory=dict)
    paned_position: int = 0
    search_history: list = field(default_factory=list)
    audio_cache_tracks: int = 20
    dsp_enabled: bool = True
    dsp_peq_enabled: bool = False
    dsp_peq_bands: list = field(default_factory=lambda: [0.0] * PEQ_BAND_COUNT)
    dsp_convolver_enabled: bool = False
    dsp_convolver_path: str = ""
    dsp_convolver_mix: int = 100
    dsp_convolver_pre_delay_ms: int = 0
    dsp_order: list = field(default_factory=lambda: list(DSP_REORDERABLE_MODULES))
    dsp_resampler_enabled: bool = False
    dsp_resampler_target_rate: int = 0
    dsp_resampler_quality: int = 10
    dsp_tape_enabled: bool = False
    dsp_tape_drive: int = 30
    dsp_tape_tone: int = 60
    dsp_tape_warmth: int = 40
    dsp_tube_enabled: bool = False
    dsp_tube_drive: int = 28
    dsp_tube_bias: int = 55
    dsp_tube_sag: int = 18
    dsp_tube_air: int = 52
    dsp_widener_enabled: bool = False
    dsp_widener_width: int = 125
    dsp_widener_bass_mono_freq: int = 120
    dsp_widener_bass_mono_amount: int = 100
    dsp_lv2_slots: list = field(default_factory=list)
    dsp_limiter_enabled: bool = False
    dsp_limiter_threshold: int = 85
    dsp_limiter_ratio: int = 20
    usb_clock_mode: str = "Push"
    output_auto_rebind_once: bool = False
    remote_api_enabled: bool = False
    remote_api_access_mode: str = "local"
    remote_api_bind_host: str = "0.0.0.0"
    remote_api_port: int = 18473
    remote_api_allowed_cidrs: list = field(default_factory=list)
    scrobble_lastfm_enabled: bool = False
    scrobble_lastfm_session_key: str = ""
    scrobble_listenbrainz_enabled: bool = False
    scrobble_listenbrainz_token: str = ""


# Default settings as dict for quick access
DEFAULT_SETTINGS = {
    "settings_version": CURRENT_SETTINGS_VERSION,
    "driver": "Auto (Default)",
    "device": "Default Output",
    "bit_perfect": False,
    "exclusive_lock": False,
    "latency_profile": "Standard (100ms)",
    "alsa_mmap_realtime_priority": AlsaMmapRealtimePriority.DEFAULT_LABEL,
    "output_bit_depth": "Auto",
    "volume": 80,
    "play_mode": 0,
    "last_nav": "home",
    "last_view": "grid_view",
    "viz_expanded": False,
    "spectrum_theme": 0,
    "viz_frequency_scale": 0,
    "viz_bar_count": 32,
    "viz_profile": 2,
    "viz_effect": 3,
    "lyrics_font_preset": 1,
    "lyrics_bg_motion": 1,
    "lyrics_user_offset_ms": 0,
    "viz_sync_offset_ms": 0,
    "viz_sync_device_offsets": {},
    "paned_position": 0,
    "search_history": [],
    "audio_cache_tracks": 20,
    "dsp_enabled": True,
    "dsp_peq_enabled": False,
    "dsp_peq_bands": [0.0] * PEQ_BAND_COUNT,
    "dsp_convolver_enabled": False,
    "dsp_convolver_path": "",
    "dsp_convolver_mix": 100,
    "dsp_convolver_pre_delay_ms": 0,
    "dsp_order": list(DSP_REORDERABLE_MODULES),
    "dsp_resampler_enabled": False,
    "dsp_resampler_target_rate": 0,
    "dsp_resampler_quality": 10,
    "dsp_tape_enabled": False,
    "dsp_tape_drive": 30,
    "dsp_tape_tone": 60,
    "dsp_tape_warmth": 40,
    "dsp_tube_enabled": False,
    "dsp_tube_drive": 28,
    "dsp_tube_bias": 55,
    "dsp_tube_sag": 18,
    "dsp_tube_air": 52,
    "dsp_widener_enabled": False,
    "dsp_widener_width": 125,
    "dsp_widener_bass_mono_freq": 120,
    "dsp_widener_bass_mono_amount": 100,
    "dsp_lv2_slots": [],
    "dsp_limiter_enabled": False,
    "dsp_limiter_threshold": 85,
    "dsp_limiter_ratio": 20,
    "usb_clock_mode": "Push",
    "output_auto_rebind_once": False,
    "remote_api_enabled": False,
    "remote_api_access_mode": "local",
    "remote_api_bind_host": "0.0.0.0",
    "remote_api_port": 18473,
    "remote_api_allowed_cidrs": [],
    "scrobble_lastfm_enabled": False,
    "scrobble_lastfm_session_key": "",
    "scrobble_listenbrainz_enabled": False,
    "scrobble_listenbrainz_token": "",
}


# Validation rules: (key, type_check, min_val, max_val, default)
# type_check: 0=int, 1=str, 2=bool, 3=list[str], 4=dict
_VALIDATION_RULES = {
    "settings_version": (int, 0, None, CURRENT_SETTINGS_VERSION),
    "driver": (str, None, None, "Auto (Default)"),
    "device": (str, None, None, "Default Output"),
    "bit_perfect": (bool, None, None, False),
    "exclusive_lock": (bool, None, None, False),
    "latency_profile": (str, None, None, "Standard (100ms)"),
    "alsa_mmap_realtime_priority": (str, None, None, AlsaMmapRealtimePriority.DEFAULT_LABEL),
    "output_bit_depth": (str, None, None, "Auto"),
    "volume": (int, 0, 100, 80),
    "play_mode": (int, 0, 3, 0),
    "last_nav": (str, None, None, "home"),
    "last_view": (str, None, None, "grid_view"),
    "viz_expanded": (bool, None, None, False),
    "spectrum_theme": (int, 0, 64, 0),
    "viz_frequency_scale": (int, 0, 1, 0),
    "viz_bar_count": (int, 4, 128, 32),
    "viz_profile": (int, 0, 4, 2),
    "viz_effect": (int, 0, 24, 3),
    "lyrics_font_preset": (int, 0, 2, 1),
    "lyrics_bg_motion": (int, 0, 2, 1),
    "lyrics_user_offset_ms": (int, -2000, 2000, 0),
    "viz_sync_offset_ms": (int, -500, 500, 0),
    "paned_position": (int, 0, None, 0),
    "search_history": (list, None, None, []),
    "audio_cache_tracks": (int, 0, 200, 20),
    "dsp_enabled": (bool, None, None, True),
    "dsp_peq_enabled": (bool, None, None, False),
    "dsp_convolver_enabled": (bool, None, None, False),
    "dsp_convolver_path": (str, None, None, ""),
    "dsp_convolver_mix": (int, 0, 100, 100),
    "dsp_convolver_pre_delay_ms": (int, 0, 200, 0),
    "dsp_order": (list, None, None, list(DSP_REORDERABLE_MODULES)),
    "dsp_resampler_enabled": (bool, None, None, False),
    "dsp_resampler_target_rate": (int, 0, 384000, 0),
    "dsp_resampler_quality": (int, 0, 10, 10),
    "dsp_tape_enabled": (bool, None, None, False),
    "dsp_tape_drive": (int, 0, 100, 30),
    "dsp_tape_tone": (int, 0, 100, 60),
    "dsp_tape_warmth": (int, 0, 100, 40),
    "dsp_tube_enabled": (bool, None, None, False),
    "dsp_tube_drive": (int, 0, 100, 28),
    "dsp_tube_bias": (int, 0, 100, 55),
    "dsp_tube_sag": (int, 0, 100, 18),
    "dsp_tube_air": (int, 0, 100, 52),
    "dsp_widener_enabled": (bool, None, None, False),
    "dsp_widener_width": (int, 0, 200, 125),
    "dsp_widener_bass_mono_freq": (int, 40, 250, 120),
    "dsp_widener_bass_mono_amount": (int, 0, 100, 100),
    "dsp_limiter_enabled": (bool, None, None, False),
    "dsp_limiter_threshold": (int, 0, 100, 85),
    "dsp_limiter_ratio": (int, 1, 60, 20),
    "output_auto_rebind_once": (bool, None, None, False),
    "remote_api_enabled": (bool, None, None, False),
    "remote_api_access_mode": (str, None, None, "local"),
    "remote_api_bind_host": (str, None, None, "0.0.0.0"),
    "remote_api_port": (int, 1, 65535, 18473),
    "remote_api_allowed_cidrs": (list, None, None, []),
    "scrobble_lastfm_enabled": (bool, None, None, False),
    "scrobble_lastfm_session_key": (str, None, None, ""),
    "scrobble_listenbrainz_enabled": (bool, None, None, False),
    "scrobble_listenbrainz_token": (str, None, None, ""),
}


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _as_str(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _as_int(value: Any, default: int, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    if not isinstance(value, int):
        return default
    if minimum is not None and value < minimum:
        return default
    if maximum is not None and value > maximum:
        return default
    return value


def _as_str_list(value: Any, default: list, max_items: int = 10) -> list:
    if not isinstance(value, list):
        return list(default)
    out = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        if len(out) >= max_items:
            break
    return out


def _normalize_dsp_order(value: Any) -> list[str]:
    if not isinstance(value, list):
        return list(DSP_REORDERABLE_MODULES)
    seen = set()
    out = []
    for item in value:
        if not isinstance(item, str):
            continue
        module_id = item.strip()
        if not module_id or module_id in seen:
            continue
        # Allow both built-in module ids and lv2_ slot ids
        if module_id not in DSP_REORDERABLE_MODULES and not module_id.startswith("lv2_"):
            continue
        seen.add(module_id)
        out.append(module_id)
    # Append any missing built-in modules at the end
    for module_id in DSP_REORDERABLE_MODULES:
        if module_id not in seen:
            out.append(module_id)
    return out


def _normalize_peq_bands(value: Any) -> list[float]:
    if not isinstance(value, list):
        return [0.0] * PEQ_BAND_COUNT
    out = []
    for item in value[:PEQ_BAND_COUNT]:
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            band = float(item)
            out.append(max(-24.0, min(12.0, band)))
        else:
            out.append(0.0)
    while len(out) < PEQ_BAND_COUNT:
        out.append(0.0)
    return out


def _as_int_dict(
    value: Any,
    default: dict,
    minimum: int = -500,
    maximum: int = 500,
    max_items: int = 64,
) -> dict:
    if not isinstance(value, dict):
        return dict(default)
    out = {}
    for k, v in value.items():
        if not isinstance(k, str) or not k:
            continue
        if not isinstance(v, int):
            continue
        if v < minimum or v > maximum:
            continue
        out[k] = v
        if len(out) >= max_items:
            break
    return out


def _normalize_lv2_slots(value: Any) -> list:
    """Validate and normalize the dsp_lv2_slots list."""
    if not isinstance(value, list):
        return []
    out = []
    seen_ids = set()
    seen_uris = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        slot_id = item.get("slot_id", "")
        uri = item.get("uri", "")
        if not isinstance(slot_id, str) or not slot_id.startswith("lv2_"):
            continue
        if not isinstance(uri, str) or not uri:
            continue
        if slot_id in seen_ids:
            continue
        uri_key = uri.strip()
        if uri_key in seen_uris:
            continue
        seen_ids.add(slot_id)
        seen_uris.add(uri_key)
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            enabled = True
        port_values = item.get("port_values", {})
        if not isinstance(port_values, dict):
            port_values = {}
        clean_ports = {}
        for k, v in port_values.items():
            if isinstance(k, str) and k and isinstance(v, (int, float)):
                clean_ports[k] = float(v)
        out.append({"slot_id": slot_id, "uri": uri, "enabled": enabled, "port_values": clean_ports})
        if len(out) >= 32:
            break
    return out


def normalize_settings(raw: Optional[dict[str, Any]]) -> dict[str, Any]:
    raw = raw or {}
    raw_settings_version = _as_int(raw.get("settings_version"), 0, minimum=0)
    normalized = dict(DEFAULT_SETTINGS)
    normalized["driver"] = _as_str(raw.get("driver"), DEFAULT_SETTINGS["driver"])
    normalized["device"] = _as_str(raw.get("device"), DEFAULT_SETTINGS["device"])
    normalized["bit_perfect"] = _as_bool(raw.get("bit_perfect"), DEFAULT_SETTINGS["bit_perfect"])
    normalized["exclusive_lock"] = _as_bool(raw.get("exclusive_lock"), DEFAULT_SETTINGS["exclusive_lock"])
    normalized["latency_profile"] = _as_str(raw.get("latency_profile"), DEFAULT_SETTINGS["latency_profile"])
    realtime_profile = _as_str(
        raw.get("alsa_mmap_realtime_priority"),
        DEFAULT_SETTINGS["alsa_mmap_realtime_priority"],
    )
    normalized["alsa_mmap_realtime_priority"] = (
        realtime_profile
        if realtime_profile in AlsaMmapRealtimePriority.MAP
        else DEFAULT_SETTINGS["alsa_mmap_realtime_priority"]
    )
    normalized["output_bit_depth"] = _as_str(raw.get("output_bit_depth"), DEFAULT_SETTINGS["output_bit_depth"])
    normalized["volume"] = _as_int(raw.get("volume"), DEFAULT_SETTINGS["volume"], minimum=0, maximum=100)
    normalized["play_mode"] = _as_int(raw.get("play_mode"), DEFAULT_SETTINGS["play_mode"], minimum=0, maximum=3)
    normalized["last_nav"] = _as_str(raw.get("last_nav"), DEFAULT_SETTINGS["last_nav"])
    normalized["last_view"] = _as_str(raw.get("last_view"), DEFAULT_SETTINGS["last_view"])
    normalized["viz_expanded"] = _as_bool(raw.get("viz_expanded"), DEFAULT_SETTINGS["viz_expanded"])
    normalized["spectrum_theme"] = _as_int(raw.get("spectrum_theme"), DEFAULT_SETTINGS["spectrum_theme"], minimum=0, maximum=64)
    normalized["viz_frequency_scale"] = _as_int(raw.get("viz_frequency_scale"), DEFAULT_SETTINGS["viz_frequency_scale"], minimum=0, maximum=1)
    normalized["viz_bar_count"] = _as_int(raw.get("viz_bar_count"), DEFAULT_SETTINGS["viz_bar_count"], minimum=4, maximum=128)
    if normalized["viz_bar_count"] not in VisualizerSettings.BAR_OPTIONS:
        normalized["viz_bar_count"] = DEFAULT_SETTINGS["viz_bar_count"]
    # Current profile options: Gentle/Soft/Dynamic/Extreme/Insane => 0..4
    raw_viz_profile = raw.get("viz_profile")
    if isinstance(raw_viz_profile, int) and raw_settings_version < 4:
        raw_viz_profile += 1
    normalized["viz_profile"] = _as_int(raw_viz_profile, DEFAULT_SETTINGS["viz_profile"], minimum=0, maximum=4)
    # Current effect options after removing Radial, legacy Fall, Pro Bars,
    # and Pro Line, then adding Orbit, Shards, Stereo Mirror, Lissajous,
    # Stereo Scope, Balance Wave, Center Side, Phase Flower, Stereo Meter,
    # and the appended optional GL Dots slot:
    # 25 entries => 0..24
    raw_viz_effect = raw.get("viz_effect")
    if isinstance(raw_viz_effect, int):
        if raw_settings_version < 1 and raw_viz_effect >= 6:
            # Legacy shift: old list contained Radial at index 5.
            raw_viz_effect -= 1
        if raw_settings_version < 2 and raw_viz_effect >= 14:
            # Legacy shift: v1 list contained Fall at index 13.
            raw_viz_effect -= 1
        if raw_settings_version < 3:
            raw_viz_effect = {
                14: 0,   # Pro Bars -> Bars
                15: 1,   # Pro Line -> Wave
                16: 14,  # Pro Fall -> Fall
            }.get(raw_viz_effect, raw_viz_effect)
    normalized["viz_effect"] = _as_int(raw_viz_effect, DEFAULT_SETTINGS["viz_effect"], minimum=0, maximum=24)
    normalized["lyrics_font_preset"] = _as_int(raw.get("lyrics_font_preset"), DEFAULT_SETTINGS["lyrics_font_preset"], minimum=0, maximum=2)
    normalized["lyrics_bg_motion"] = _as_int(raw.get("lyrics_bg_motion"), DEFAULT_SETTINGS["lyrics_bg_motion"], minimum=0, maximum=2)
    normalized["lyrics_user_offset_ms"] = _as_int(raw.get("lyrics_user_offset_ms"), DEFAULT_SETTINGS["lyrics_user_offset_ms"], minimum=-2000, maximum=2000)
    normalized["viz_sync_offset_ms"] = _as_int(raw.get("viz_sync_offset_ms"), DEFAULT_SETTINGS["viz_sync_offset_ms"], minimum=-500, maximum=500)
    normalized["viz_sync_device_offsets"] = _as_int_dict(raw.get("viz_sync_device_offsets"), DEFAULT_SETTINGS["viz_sync_device_offsets"], minimum=-500, maximum=500, max_items=64)
    normalized["paned_position"] = _as_int(raw.get("paned_position"), DEFAULT_SETTINGS["paned_position"], minimum=0)
    normalized["search_history"] = _as_str_list(raw.get("search_history"), DEFAULT_SETTINGS["search_history"])
    normalized["audio_cache_tracks"] = _as_int(raw.get("audio_cache_tracks"), DEFAULT_SETTINGS["audio_cache_tracks"], minimum=0, maximum=200)
    normalized["dsp_enabled"] = _as_bool(raw.get("dsp_enabled"), DEFAULT_SETTINGS["dsp_enabled"])
    normalized["dsp_peq_enabled"] = _as_bool(raw.get("dsp_peq_enabled"), DEFAULT_SETTINGS["dsp_peq_enabled"])
    normalized["dsp_peq_bands"] = _normalize_peq_bands(raw.get("dsp_peq_bands"))
    normalized["dsp_convolver_enabled"] = _as_bool(raw.get("dsp_convolver_enabled"), DEFAULT_SETTINGS["dsp_convolver_enabled"])
    normalized["dsp_convolver_path"] = _as_str(raw.get("dsp_convolver_path"), DEFAULT_SETTINGS["dsp_convolver_path"])
    normalized["dsp_convolver_mix"] = _as_int(raw.get("dsp_convolver_mix"), DEFAULT_SETTINGS["dsp_convolver_mix"], minimum=0, maximum=100)
    normalized["dsp_convolver_pre_delay_ms"] = _as_int(raw.get("dsp_convolver_pre_delay_ms"), DEFAULT_SETTINGS["dsp_convolver_pre_delay_ms"], minimum=0, maximum=200)
    normalized["dsp_resampler_enabled"] = _as_bool(raw.get("dsp_resampler_enabled"), DEFAULT_SETTINGS["dsp_resampler_enabled"])
    normalized["dsp_resampler_target_rate"] = _as_int(raw.get("dsp_resampler_target_rate"), DEFAULT_SETTINGS["dsp_resampler_target_rate"], minimum=0, maximum=384000)
    normalized["dsp_resampler_quality"] = _as_int(raw.get("dsp_resampler_quality"), DEFAULT_SETTINGS["dsp_resampler_quality"], minimum=0, maximum=10)
    normalized["dsp_tape_enabled"] = _as_bool(raw.get("dsp_tape_enabled"), DEFAULT_SETTINGS["dsp_tape_enabled"])
    normalized["dsp_tape_drive"] = _as_int(raw.get("dsp_tape_drive"), DEFAULT_SETTINGS["dsp_tape_drive"], minimum=0, maximum=100)
    normalized["dsp_tape_tone"] = _as_int(raw.get("dsp_tape_tone"), DEFAULT_SETTINGS["dsp_tape_tone"], minimum=0, maximum=100)
    normalized["dsp_tape_warmth"] = _as_int(raw.get("dsp_tape_warmth"), DEFAULT_SETTINGS["dsp_tape_warmth"], minimum=0, maximum=100)
    normalized["dsp_tube_enabled"] = _as_bool(raw.get("dsp_tube_enabled"), DEFAULT_SETTINGS["dsp_tube_enabled"])
    normalized["dsp_tube_drive"] = _as_int(raw.get("dsp_tube_drive"), DEFAULT_SETTINGS["dsp_tube_drive"], minimum=0, maximum=100)
    normalized["dsp_tube_bias"] = _as_int(raw.get("dsp_tube_bias"), DEFAULT_SETTINGS["dsp_tube_bias"], minimum=0, maximum=100)
    normalized["dsp_tube_sag"] = _as_int(raw.get("dsp_tube_sag"), DEFAULT_SETTINGS["dsp_tube_sag"], minimum=0, maximum=100)
    normalized["dsp_tube_air"] = _as_int(raw.get("dsp_tube_air"), DEFAULT_SETTINGS["dsp_tube_air"], minimum=0, maximum=100)
    normalized["dsp_widener_enabled"] = _as_bool(raw.get("dsp_widener_enabled"), DEFAULT_SETTINGS["dsp_widener_enabled"])
    normalized["dsp_widener_width"] = _as_int(raw.get("dsp_widener_width"), DEFAULT_SETTINGS["dsp_widener_width"], minimum=0, maximum=200)
    normalized["dsp_widener_bass_mono_freq"] = _as_int(raw.get("dsp_widener_bass_mono_freq"), DEFAULT_SETTINGS["dsp_widener_bass_mono_freq"], minimum=40, maximum=250)
    normalized["dsp_widener_bass_mono_amount"] = _as_int(raw.get("dsp_widener_bass_mono_amount"), DEFAULT_SETTINGS["dsp_widener_bass_mono_amount"], minimum=0, maximum=100)
    normalized["dsp_lv2_slots"] = _normalize_lv2_slots(raw.get("dsp_lv2_slots"))
    valid_lv2_slot_ids = {slot["slot_id"] for slot in normalized["dsp_lv2_slots"]}
    normalized["dsp_order"] = [
        item
        for item in _normalize_dsp_order(raw.get("dsp_order"))
        if item in DSP_REORDERABLE_MODULES or item in valid_lv2_slot_ids
    ]
    for module_id in DSP_REORDERABLE_MODULES:
        if module_id not in normalized["dsp_order"]:
            normalized["dsp_order"].append(module_id)
    normalized["dsp_limiter_enabled"] = _as_bool(raw.get("dsp_limiter_enabled"), DEFAULT_SETTINGS["dsp_limiter_enabled"])
    normalized["dsp_limiter_threshold"] = _as_int(raw.get("dsp_limiter_threshold"), DEFAULT_SETTINGS["dsp_limiter_threshold"], minimum=0, maximum=100)
    normalized["dsp_limiter_ratio"] = _as_int(raw.get("dsp_limiter_ratio"), DEFAULT_SETTINGS["dsp_limiter_ratio"], minimum=1, maximum=60)
    _usb_clk = _as_str(raw.get("usb_clock_mode"), DEFAULT_SETTINGS["usb_clock_mode"])
    normalized["usb_clock_mode"] = _usb_clk if _usb_clk in ("Push", "Pull") else DEFAULT_SETTINGS["usb_clock_mode"]
    normalized["output_auto_rebind_once"] = _as_bool(raw.get("output_auto_rebind_once"), DEFAULT_SETTINGS["output_auto_rebind_once"])
    normalized["remote_api_enabled"] = _as_bool(raw.get("remote_api_enabled"), DEFAULT_SETTINGS["remote_api_enabled"])
    remote_mode = _as_str(raw.get("remote_api_access_mode"), DEFAULT_SETTINGS["remote_api_access_mode"]).lower()
    normalized["remote_api_access_mode"] = remote_mode if remote_mode in ("local", "lan") else DEFAULT_SETTINGS["remote_api_access_mode"]
    normalized["remote_api_bind_host"] = _as_str(raw.get("remote_api_bind_host"), DEFAULT_SETTINGS["remote_api_bind_host"])
    normalized["remote_api_port"] = _as_int(raw.get("remote_api_port"), DEFAULT_SETTINGS["remote_api_port"], minimum=1, maximum=65535)
    normalized["remote_api_allowed_cidrs"] = _as_str_list(raw.get("remote_api_allowed_cidrs"), DEFAULT_SETTINGS["remote_api_allowed_cidrs"], max_items=32)
    normalized["scrobble_lastfm_enabled"] = _as_bool(raw.get("scrobble_lastfm_enabled"), False)
    normalized["scrobble_lastfm_session_key"] = raw.get("scrobble_lastfm_session_key", "") if isinstance(raw.get("scrobble_lastfm_session_key"), str) else ""
    normalized["scrobble_listenbrainz_enabled"] = _as_bool(raw.get("scrobble_listenbrainz_enabled"), False)
    normalized["scrobble_listenbrainz_token"] = raw.get("scrobble_listenbrainz_token", "") if isinstance(raw.get("scrobble_listenbrainz_token"), str) else ""
    normalized["settings_version"] = CURRENT_SETTINGS_VERSION

    # Exclusive lock requires bit-perfect mode.
    if not normalized["bit_perfect"]:
        normalized["exclusive_lock"] = False
    return normalized


def load_settings(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return dict(DEFAULT_SETTINGS)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Failed to load settings from %s: %s", path, e)
        return dict(DEFAULT_SETTINGS)

    if not isinstance(data, dict):
        logger.warning("Settings file %s is not a valid dict", path)
        return dict(DEFAULT_SETTINGS)
    return normalize_settings(data)


def save_settings(path: str, settings: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = normalize_settings(settings)
    temp_file = f"{path}.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_file, path)


# Simple JSON file utilities for general use
def read_json(path: str, default=None):
    """Read JSON file, returning default if not found or invalid."""
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to read JSON from %s: %s", path, e)
        return default


def write_json(path: str, data, indent: int = 2) -> None:
    """Write data to JSON file atomically."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_file = f"{path}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
        os.replace(temp_file, path)
    except Exception as e:
        logger.warning("Failed to write JSON to %s: %s", path, e)
