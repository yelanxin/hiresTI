import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from app import app_visualizer
from viz import dr_meter as dr_mod


def test_compute_level_metrics_uses_rust_helper_when_available(monkeypatch):
    class _RustCore:
        available = True

        def __init__(self):
            self.calls = []

        def compute_level_metrics(self, left, right):
            self.calls.append((list(left), list(right)))
            return (-9.0, -18.0, -7.0, -16.0)

    rust_core = _RustCore()
    monkeypatch.setattr(dr_mod, "_get_rust_viz_core", lambda: rust_core)

    out = dr_mod._compute_level_metrics([1.0, 2.0], [3.0, 4.0])

    assert out == (-9.0, -18.0, -7.0, -16.0)
    assert rust_core.calls == [([1.0, 2.0], [3.0, 4.0])]


def test_apply_viz_frame_throttles_lufs_polling(monkeypatch):
    calls = []
    set_calls = []
    times = iter([100.0, 100.0, 100.01, 100.01])

    class _DrMeter:
        def get_visible(self):
            return True

        def update(self, left, right):
            calls.append((list(left), list(right)))

        def set_lufs(self, *vals):
            set_calls.append(tuple(vals))

    app = SimpleNamespace(
        _viz_current_page="spectrum",
        viz=SimpleNamespace(update_data=lambda frame: calls.append(("viz", frame))),
        dr_meter=_DrMeter(),
        player=SimpleNamespace(
            get_lufs=lambda: (calls.append("poll") or (-18.0, -19.0, -20.0, 6.0, 9.0))
        ),
        _dr_lufs_last_poll_ts=0.0,
        _dr_lufs_cached=None,
    )

    monkeypatch.setattr(app_visualizer.time, "monotonic", lambda: next(times))

    frame = {"mono": [1.0], "left": [2.0], "right": [3.0]}
    app_visualizer._apply_viz_frame(app, frame)
    app_visualizer._apply_viz_frame(app, frame)

    assert calls.count("poll") == 1
    assert len(set_calls) == 1


def test_apply_viz_frame_throttles_dr_meter_update(monkeypatch):
    updates = []
    times = iter([100.0, 100.0, 100.02, 100.02])

    class _DrMeter:
        def get_visible(self):
            return True

        def update(self, left, right):
            updates.append((list(left), list(right)))

        def set_lufs(self, *vals):
            pass

    app = SimpleNamespace(
        _viz_current_page="spectrum",
        viz=SimpleNamespace(update_data=lambda frame: None),
        dr_meter=_DrMeter(),
        player=SimpleNamespace(get_lufs=lambda: None),
        _dr_meter_last_update_ts=0.0,
        _dr_lufs_last_poll_ts=0.0,
        _dr_lufs_cached=None,
    )

    monkeypatch.setattr(app_visualizer.time, "monotonic", lambda: next(times))

    frame = {"mono": [1.0], "left": [2.0], "right": [3.0]}
    app_visualizer._apply_viz_frame(app, frame)
    app_visualizer._apply_viz_frame(app, frame)

    assert updates == [([2.0], [3.0])]


def test_apply_viz_frame_skips_dr_meter_when_hidden(monkeypatch):
    updates = []

    class _DrMeter:
        def get_visible(self):
            return True

        def update(self, left, right):
            updates.append((list(left), list(right)))

        def set_lufs(self, *vals):
            updates.append(("lufs", vals))

    app = SimpleNamespace(
        _viz_current_page="spectrum",
        viz=SimpleNamespace(update_data=lambda frame: None),
        dr_meter=_DrMeter(),
        player=SimpleNamespace(get_lufs=lambda: (-18.0, -19.0, -20.0, 6.0, 9.0)),
        _dr_meter_last_update_ts=0.0,
        _dr_lufs_last_poll_ts=0.0,
        _dr_lufs_cached=None,
    )

    monkeypatch.setattr(app_visualizer, "_hide_dr_meter_debug", lambda: True)

    frame = {"mono": [1.0], "left": [2.0], "right": [3.0]}
    app_visualizer._apply_viz_frame(app, frame)

    assert updates == []


def test_scale_tick_dbs_matches_bar_mapping():
    # Tall bars: 10 dB steps from 0 to -60; floor edge (-70) omitted.
    assert dr_mod.LevelMonitor._scale_tick_dbs(300) == [0, -10, -20, -30, -40, -50, -60]
    # Short bars thin to 20 dB steps so labels don't collide.
    assert dr_mod.LevelMonitor._scale_tick_dbs(100) == [0, -20, -40, -60]


def test_scale_ticks_land_on_true_bar_positions():
    mon = dr_mod.LevelMonitor.__new__(dr_mod.LevelMonitor)
    # The scale is only honest if it uses the exact bar mapping: linear
    # over [-70, 0] dBFS.
    assert mon._db_to_ratio(0.0) == 1.0
    assert mon._db_to_ratio(-70.0) == 0.0
    assert mon._db_to_ratio(-35.0) == 0.5
    for db in dr_mod.LevelMonitor._scale_tick_dbs(300):
        assert abs(mon._db_to_ratio(db) - (db + 70.0) / 70.0) < 1e-9
