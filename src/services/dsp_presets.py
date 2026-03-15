"""DSP preset management.

Presets are stored as a separate JSON file in the config directory,
independent of the main settings.json.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

MAX_PRESETS = 20

# Keys captured per preset (excludes non-DSP settings)
DSP_PRESET_KEYS = [
    "dsp_enabled",
    "dsp_order",
    "dsp_peq_enabled",
    "dsp_peq_bands",
    "dsp_convolver_enabled",
    "dsp_convolver_path",
    "dsp_convolver_mix",
    "dsp_convolver_pre_delay_ms",
    "dsp_resampler_enabled",
    "dsp_resampler_target_rate",
    "dsp_resampler_quality",
    "dsp_tape_enabled",
    "dsp_tape_drive",
    "dsp_tape_tone",
    "dsp_tape_warmth",
    "dsp_tube_enabled",
    "dsp_tube_drive",
    "dsp_tube_bias",
    "dsp_tube_sag",
    "dsp_tube_air",
    "dsp_widener_enabled",
    "dsp_widener_width",
    "dsp_widener_bass_mono_freq",
    "dsp_widener_bass_mono_amount",
    "dsp_limiter_enabled",
    "dsp_limiter_threshold",
    "dsp_limiter_ratio",
    "dsp_lv2_slots",
]


class DspPresetManager:
    """Load, save, and delete named DSP presets."""

    def __init__(self, config_dir: str):
        self._path = os.path.join(config_dir, "dsp_presets.json")
        self._presets: dict = {}
        self._load()

    def _load(self):
        if not os.path.exists(self._path):
            self._presets = {}
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._presets = data
            else:
                self._presets = {}
        except Exception as e:
            logger.warning("Failed to load DSP presets from %s: %s", self._path, e)
            self._presets = {}

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = f"{self._path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._presets, f, indent=2)
            os.replace(tmp, self._path)
        except Exception as e:
            logger.warning("Failed to save DSP presets to %s: %s", self._path, e)

    def list_presets(self) -> list:
        return sorted(self._presets.keys())

    def save_preset(self, name: str, settings: dict) -> bool:
        name = name.strip()
        if not name:
            return False
        if len(self._presets) >= MAX_PRESETS and name not in self._presets:
            logger.warning("DSP preset limit (%d) reached", MAX_PRESETS)
            return False
        preset = {k: settings[k] for k in DSP_PRESET_KEYS if k in settings}
        self._presets[name] = preset
        self._save()
        logger.info("DSP preset saved: %r", name)
        return True

    def load_preset(self, name: str) -> dict | None:
        return self._presets.get(name)

    def delete_preset(self, name: str) -> bool:
        if name in self._presets:
            del self._presets[name]
            self._save()
            logger.info("DSP preset deleted: %r", name)
            return True
        return False
