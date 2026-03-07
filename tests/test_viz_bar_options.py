import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.constants import VisualizerSettings
from core.settings import normalize_settings


def test_viz_bar_options_drop_96_and_128():
    assert VisualizerSettings.BAR_OPTIONS == [4, 8, 16, 32, 48, 64]


def test_viz_bar_count_normalization_falls_back_from_removed_values():
    assert normalize_settings({"viz_bar_count": 96})["viz_bar_count"] == 32
    assert normalize_settings({"viz_bar_count": 128})["viz_bar_count"] == 32
