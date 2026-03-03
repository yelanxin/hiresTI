import json
import logging
import os
from dataclasses import dataclass, field, fields
from typing import Any, Optional

logger = logging.getLogger(__name__)

CURRENT_SETTINGS_VERSION = 2


@dataclass
class SettingsSchema:
    """Settings schema using dataclass for declarative validation."""

    settings_version: int = CURRENT_SETTINGS_VERSION
    driver: str = "Auto (Default)"
    device: str = "Default Output"
    bit_perfect: bool = False
    exclusive_lock: bool = False
    latency_profile: str = "Standard (100ms)"
    output_bit_depth: str = "Auto"
    volume: int = 80
    play_mode: int = 0
    last_nav: str = "home"
    last_view: str = "grid_view"
    viz_expanded: bool = False
    spectrum_theme: int = 0
    viz_backend_policy: int = 0
    viz_bar_count: int = 32
    viz_profile: int = 1
    viz_effect: int = 3
    lyrics_font_preset: int = 1
    lyrics_bg_motion: int = 1
    lyrics_user_offset_ms: int = 0
    viz_sync_offset_ms: int = 0
    viz_sync_device_offsets: dict = field(default_factory=dict)
    paned_position: int = 0
    search_history: list = field(default_factory=list)
    audio_cache_tracks: int = 20
    output_auto_rebind_once: bool = False
    remote_api_enabled: bool = False
    remote_api_access_mode: str = "local"
    remote_api_bind_host: str = "0.0.0.0"
    remote_api_port: int = 18473
    remote_api_allowed_cidrs: list = field(default_factory=list)


# Default settings as dict for quick access
DEFAULT_SETTINGS = {
    "settings_version": CURRENT_SETTINGS_VERSION,
    "driver": "Auto (Default)",
    "device": "Default Output",
    "bit_perfect": False,
    "exclusive_lock": False,
    "latency_profile": "Standard (100ms)",
    "output_bit_depth": "Auto",
    "volume": 80,
    "play_mode": 0,
    "last_nav": "home",
    "last_view": "grid_view",
    "viz_expanded": False,
    "spectrum_theme": 0,
    "viz_backend_policy": 0,
    "viz_bar_count": 32,
    "viz_profile": 1,
    "viz_effect": 3,
    "lyrics_font_preset": 1,
    "lyrics_bg_motion": 1,
    "lyrics_user_offset_ms": 0,
    "viz_sync_offset_ms": 0,
    "viz_sync_device_offsets": {},
    "paned_position": 0,
    "search_history": [],
    "audio_cache_tracks": 20,
    "output_auto_rebind_once": False,
    "remote_api_enabled": False,
    "remote_api_access_mode": "local",
    "remote_api_bind_host": "0.0.0.0",
    "remote_api_port": 18473,
    "remote_api_allowed_cidrs": [],
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
    "output_bit_depth": (str, None, None, "Auto"),
    "volume": (int, 0, 100, 80),
    "play_mode": (int, 0, 3, 0),
    "last_nav": (str, None, None, "home"),
    "last_view": (str, None, None, "grid_view"),
    "viz_expanded": (bool, None, None, False),
    "spectrum_theme": (int, 0, 64, 0),
    "viz_backend_policy": (int, 0, 0, 0),
    "viz_bar_count": (int, 4, 128, 32),
    "viz_profile": (int, 0, 3, 1),
    "viz_effect": (int, 0, 16, 3),
    "lyrics_font_preset": (int, 0, 2, 1),
    "lyrics_bg_motion": (int, 0, 2, 1),
    "lyrics_user_offset_ms": (int, -2000, 2000, 0),
    "viz_sync_offset_ms": (int, -500, 500, 0),
    "paned_position": (int, 0, None, 0),
    "search_history": (list, None, None, []),
    "audio_cache_tracks": (int, 0, 200, 20),
    "output_auto_rebind_once": (bool, None, None, False),
    "remote_api_enabled": (bool, None, None, False),
    "remote_api_access_mode": (str, None, None, "local"),
    "remote_api_bind_host": (str, None, None, "0.0.0.0"),
    "remote_api_port": (int, 1, 65535, 18473),
    "remote_api_allowed_cidrs": (list, None, None, []),
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


def normalize_settings(raw: Optional[dict[str, Any]]) -> dict[str, Any]:
    raw = raw or {}
    raw_settings_version = _as_int(raw.get("settings_version"), 0, minimum=0)
    normalized = dict(DEFAULT_SETTINGS)
    normalized["driver"] = _as_str(raw.get("driver"), DEFAULT_SETTINGS["driver"])
    normalized["device"] = _as_str(raw.get("device"), DEFAULT_SETTINGS["device"])
    normalized["bit_perfect"] = _as_bool(raw.get("bit_perfect"), DEFAULT_SETTINGS["bit_perfect"])
    normalized["exclusive_lock"] = _as_bool(raw.get("exclusive_lock"), DEFAULT_SETTINGS["exclusive_lock"])
    normalized["latency_profile"] = _as_str(raw.get("latency_profile"), DEFAULT_SETTINGS["latency_profile"])
    normalized["output_bit_depth"] = _as_str(raw.get("output_bit_depth"), DEFAULT_SETTINGS["output_bit_depth"])
    normalized["volume"] = _as_int(raw.get("volume"), DEFAULT_SETTINGS["volume"], minimum=0, maximum=100)
    normalized["play_mode"] = _as_int(raw.get("play_mode"), DEFAULT_SETTINGS["play_mode"], minimum=0, maximum=3)
    normalized["last_nav"] = _as_str(raw.get("last_nav"), DEFAULT_SETTINGS["last_nav"])
    normalized["last_view"] = _as_str(raw.get("last_view"), DEFAULT_SETTINGS["last_view"])
    normalized["viz_expanded"] = _as_bool(raw.get("viz_expanded"), DEFAULT_SETTINGS["viz_expanded"])
    normalized["spectrum_theme"] = _as_int(raw.get("spectrum_theme"), DEFAULT_SETTINGS["spectrum_theme"], minimum=0, maximum=64)
    normalized["viz_backend_policy"] = _as_int(raw.get("viz_backend_policy"), DEFAULT_SETTINGS["viz_backend_policy"], minimum=0, maximum=0)
    normalized["viz_bar_count"] = _as_int(raw.get("viz_bar_count"), DEFAULT_SETTINGS["viz_bar_count"], minimum=4, maximum=128)
    # Current profile options: Soft/Dynamic/Extreme/Insane => 0..3
    normalized["viz_profile"] = _as_int(raw.get("viz_profile"), DEFAULT_SETTINGS["viz_profile"], minimum=0, maximum=3)
    # Current effect options after removing Radial and Fall: 17 entries => 0..16
    raw_viz_effect = raw.get("viz_effect")
    if isinstance(raw_viz_effect, int):
        if raw_settings_version < 1 and raw_viz_effect >= 6:
            # Legacy shift: old list contained Radial at index 5.
            raw_viz_effect -= 1
        if raw_settings_version < 2 and raw_viz_effect >= 14:
            # Legacy shift: v1 list contained Fall at index 13.
            raw_viz_effect -= 1
    normalized["viz_effect"] = _as_int(raw_viz_effect, DEFAULT_SETTINGS["viz_effect"], minimum=0, maximum=16)
    normalized["lyrics_font_preset"] = _as_int(raw.get("lyrics_font_preset"), DEFAULT_SETTINGS["lyrics_font_preset"], minimum=0, maximum=2)
    normalized["lyrics_bg_motion"] = _as_int(raw.get("lyrics_bg_motion"), DEFAULT_SETTINGS["lyrics_bg_motion"], minimum=0, maximum=2)
    normalized["lyrics_user_offset_ms"] = _as_int(raw.get("lyrics_user_offset_ms"), DEFAULT_SETTINGS["lyrics_user_offset_ms"], minimum=-2000, maximum=2000)
    normalized["viz_sync_offset_ms"] = _as_int(raw.get("viz_sync_offset_ms"), DEFAULT_SETTINGS["viz_sync_offset_ms"], minimum=-500, maximum=500)
    normalized["viz_sync_device_offsets"] = _as_int_dict(raw.get("viz_sync_device_offsets"), DEFAULT_SETTINGS["viz_sync_device_offsets"], minimum=-500, maximum=500, max_items=64)
    normalized["paned_position"] = _as_int(raw.get("paned_position"), DEFAULT_SETTINGS["paned_position"], minimum=0)
    normalized["search_history"] = _as_str_list(raw.get("search_history"), DEFAULT_SETTINGS["search_history"])
    normalized["audio_cache_tracks"] = _as_int(raw.get("audio_cache_tracks"), DEFAULT_SETTINGS["audio_cache_tracks"], minimum=0, maximum=200)
    normalized["output_auto_rebind_once"] = _as_bool(raw.get("output_auto_rebind_once"), DEFAULT_SETTINGS["output_auto_rebind_once"])
    normalized["remote_api_enabled"] = _as_bool(raw.get("remote_api_enabled"), DEFAULT_SETTINGS["remote_api_enabled"])
    remote_mode = _as_str(raw.get("remote_api_access_mode"), DEFAULT_SETTINGS["remote_api_access_mode"]).lower()
    normalized["remote_api_access_mode"] = remote_mode if remote_mode in ("local", "lan") else DEFAULT_SETTINGS["remote_api_access_mode"]
    normalized["remote_api_bind_host"] = _as_str(raw.get("remote_api_bind_host"), DEFAULT_SETTINGS["remote_api_bind_host"])
    normalized["remote_api_port"] = _as_int(raw.get("remote_api_port"), DEFAULT_SETTINGS["remote_api_port"], minimum=1, maximum=65535)
    normalized["remote_api_allowed_cidrs"] = _as_str_list(raw.get("remote_api_allowed_cidrs"), DEFAULT_SETTINGS["remote_api_allowed_cidrs"], max_items=32)
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
