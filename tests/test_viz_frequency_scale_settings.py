import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.settings import DEFAULT_SETTINGS, normalize_settings


def test_viz_frequency_scale_defaults_to_linear():
    assert DEFAULT_SETTINGS["viz_frequency_scale"] == 0
    assert normalize_settings({})["viz_frequency_scale"] == 0


def test_viz_frequency_scale_normalization_accepts_linear_and_log_only():
    assert normalize_settings({"viz_frequency_scale": 0})["viz_frequency_scale"] == 0
    assert normalize_settings({"viz_frequency_scale": 1})["viz_frequency_scale"] == 1
    assert normalize_settings({"viz_frequency_scale": 2})["viz_frequency_scale"] == 0
