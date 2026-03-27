import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app_visualizer as mod


class _DummyViz:
    def __init__(self):
        self.scale = "Linear"
        self.last_num_bars = None
        self.last_input_bands = None

    def get_frequency_scale_names(self):
        return ["Linear", "Log"]

    def set_frequency_scale(self, name):
        self.scale = name

    def set_num_bars(self, count):
        self.last_num_bars = int(count)

    def set_input_band_count(self, count):
        self.last_input_bands = int(count)


class _DummyDropDown:
    def __init__(self):
        self.selected = None
        self.sensitive = True
        self.tooltip = None

    def set_selected(self, idx):
        self.selected = idx

    def set_sensitive(self, value):
        self.sensitive = bool(value)

    def set_tooltip_text(self, text):
        self.tooltip = text


def _make_app(scale_idx=0, bar_count=48):
    app = SimpleNamespace(
        VIZ_BAR_OPTIONS=[4, 8, 16, 32, 48, 64, 128],
        settings={"viz_frequency_scale": scale_idx, "viz_bar_count": bar_count},
        viz=_DummyViz(),
        player=SimpleNamespace(set_spectrum_active_bands=lambda bands: setattr(app, "last_player_bands", int(bands))),
        viz_bars_dd=_DummyDropDown(),
        viz_freq_scale_dd=None,
    )
    app._apply_viz_bars_by_count = lambda count, update_dropdown=False: mod._apply_viz_bars_by_count(
        app, count, update_dropdown=update_dropdown
    )
    return app


def test_linear_mode_keeps_requested_display_bar_count():
    app = _make_app(scale_idx=0, bar_count=48)
    mod._apply_viz_bars_by_count(app, 48, update_dropdown=True)
    assert app.viz.last_num_bars == 48
    assert app.viz.last_input_bands == 128
    assert app.last_player_bands == 128
    assert app.viz_bars_dd.selected == app.VIZ_BAR_OPTIONS.index(48)


def test_log_mode_restores_requested_bar_count():
    app = _make_app(scale_idx=0, bar_count=48)
    mod._apply_viz_frequency_scale_by_index(app, 1, update_dropdown=False)
    assert app.viz.scale == "Log"
    assert app.viz.last_num_bars == 48
    assert app.viz.last_input_bands == 1024
    assert app.last_player_bands == 1024


def test_dynamic_analysis_band_mapping_tracks_bar_count():
    assert mod._viz_analysis_bands_for_bar_count(32) == 128
    assert mod._viz_analysis_bands_for_bar_count(64) == 128
    assert mod._viz_analysis_bands_for_bar_count(128) == 128
    assert mod._viz_analysis_bands_for_bar_count(32, frequency_scale_name="Log") == 512
    assert mod._viz_analysis_bands_for_bar_count(64, frequency_scale_name="Log") == 1024
    assert mod._viz_analysis_bands_for_bar_count(128, frequency_scale_name="Log") == 2048


def test_linear_active_bands_env_override(monkeypatch):
    monkeypatch.setenv("HIRESTI_VIZ_LINEAR_ACTIVE_BANDS", "1024")

    assert mod._viz_analysis_bands_for_bar_count(32) == 1024
    assert mod._viz_analysis_bands_for_bar_count(128) == 1024
    assert mod._viz_analysis_bands_for_bar_count(128, frequency_scale_name="Log") == 2048
