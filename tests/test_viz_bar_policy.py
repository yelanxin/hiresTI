import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app_visualizer as mod


class _DummyViz:
    def __init__(self):
        self.scale = "Linear"
        self.last_num_bars = None

    def get_frequency_scale_names(self):
        return ["Linear", "Log"]

    def set_frequency_scale(self, name):
        self.scale = name

    def set_num_bars(self, count):
        self.last_num_bars = int(count)


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
        VIZ_BAR_OPTIONS=[4, 8, 16, 32, 48, 64],
        settings={"viz_frequency_scale": scale_idx, "viz_bar_count": bar_count},
        viz=_DummyViz(),
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
    assert app.viz_bars_dd.selected == app.VIZ_BAR_OPTIONS.index(48)


def test_log_mode_restores_requested_bar_count():
    app = _make_app(scale_idx=0, bar_count=48)
    mod._apply_viz_frequency_scale_by_index(app, 1, update_dropdown=False)
    assert app.viz.scale == "Log"
    assert app.viz.last_num_bars == 48
