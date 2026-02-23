import json
import os
from typing import Any


CURRENT_SETTINGS_VERSION = 2

DEFAULT_SETTINGS = {
    "settings_version": CURRENT_SETTINGS_VERSION,
    "driver": "Auto (Default)",
    "device": "Default Output",
    "bit_perfect": False,
    "exclusive_lock": False,
    "latency_profile": "Standard (100ms)",
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
}


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _as_str(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return default


def _as_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    if not isinstance(value, int):
        return default
    if minimum is not None and value < minimum:
        return default
    if maximum is not None and value > maximum:
        return default
    return value


def _as_str_list(value: Any, default: list[str], max_items: int = 10) -> list[str]:
    if not isinstance(value, list):
        return list(default)
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        if len(out) >= max_items:
            break
    return out


def _as_int_dict(
    value: Any,
    default: dict[str, int],
    minimum: int = -500,
    maximum: int = 500,
    max_items: int = 64,
) -> dict[str, int]:
    if not isinstance(value, dict):
        return dict(default)
    out: dict[str, int] = {}
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


def normalize_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    raw_settings_version = _as_int(raw.get("settings_version"), 0, minimum=0)
    normalized = dict(DEFAULT_SETTINGS)
    normalized["driver"] = _as_str(raw.get("driver"), DEFAULT_SETTINGS["driver"])
    normalized["device"] = _as_str(raw.get("device"), DEFAULT_SETTINGS["device"])
    normalized["bit_perfect"] = _as_bool(raw.get("bit_perfect"), DEFAULT_SETTINGS["bit_perfect"])
    normalized["exclusive_lock"] = _as_bool(raw.get("exclusive_lock"), DEFAULT_SETTINGS["exclusive_lock"])
    normalized["latency_profile"] = _as_str(raw.get("latency_profile"), DEFAULT_SETTINGS["latency_profile"])
    normalized["volume"] = _as_int(raw.get("volume"), DEFAULT_SETTINGS["volume"], minimum=0, maximum=100)
    normalized["play_mode"] = _as_int(raw.get("play_mode"), DEFAULT_SETTINGS["play_mode"], minimum=0, maximum=3)
    normalized["last_nav"] = _as_str(raw.get("last_nav"), DEFAULT_SETTINGS["last_nav"])
    normalized["last_view"] = _as_str(raw.get("last_view"), DEFAULT_SETTINGS["last_view"])
    normalized["viz_expanded"] = _as_bool(raw.get("viz_expanded"), DEFAULT_SETTINGS["viz_expanded"])
    normalized["spectrum_theme"] = _as_int(raw.get("spectrum_theme"), DEFAULT_SETTINGS["spectrum_theme"], minimum=0, maximum=64)
    normalized["viz_backend_policy"] = _as_int(raw.get("viz_backend_policy"), DEFAULT_SETTINGS["viz_backend_policy"], minimum=0, maximum=1)
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
    except Exception:
        return dict(DEFAULT_SETTINGS)

    if not isinstance(data, dict):
        return dict(DEFAULT_SETTINGS)
    return normalize_settings(data)


def save_settings(path: str, settings: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = normalize_settings(settings)
    temp_file = f"{path}.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_file, path)
