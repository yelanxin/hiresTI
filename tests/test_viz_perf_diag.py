import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.viz_perf import VizPerfWindow
from viz import visualizer as mod


class _Logger:
    def __init__(self):
        self.info_calls = []

    def info(self, msg, *args):
        self.info_calls.append(msg % args if args else str(msg))


def test_viz_perf_window_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HIRESTI_VIZ_PERF", raising=False)
    logger = _Logger()
    win = VizPerfWindow("map", logger)

    with win.track("build_linear"):
        pass

    assert win.snapshot() == {}
    assert logger.info_calls == []


def test_viz_perf_window_track_records_elapsed_ms():
    logger = _Logger()
    now = [0.0]
    timer_vals = iter([1.000, 1.004])
    win = VizPerfWindow(
        "draw",
        logger,
        enabled=True,
        log_interval_s=10.0,
        now_fn=lambda: now[0],
        timer_fn=lambda: next(timer_vals),
    )

    with win.track("bars"):
        pass

    snap = win.snapshot()
    assert snap["bars"]["calls"] == 1
    assert snap["bars"]["total_ms"] == pytest.approx(4.0)
    assert snap["bars"]["avg_ms"] == pytest.approx(4.0)
    assert snap["bars"]["max_ms"] == pytest.approx(4.0)
    assert logger.info_calls == []


def test_viz_perf_window_flushes_aggregated_summary():
    logger = _Logger()
    win = VizPerfWindow("audio", logger, enabled=True, log_interval_s=2.0, now_fn=lambda: 0.0)

    win.record_ms("sample_at_pos", 1.5, now=0.5)
    win.record_ms("sample_at_pos", 2.5, now=1.0)
    assert win.snapshot()["sample_at_pos"]["calls"] == 2

    win.record_ms("render_tick", 4.0, now=2.1)

    assert len(logger.info_calls) == 1
    assert logger.info_calls[0].startswith("VIZ PERF audio: ")
    assert "sample_at_pos calls=2 total=4.00ms avg=2.00ms max=2.50ms" in logger.info_calls[0]
    assert "render_tick calls=1 total=4.00ms avg=4.00ms max=4.00ms" in logger.info_calls[0]
    assert win.snapshot() == {}


def test_hybrid_visualizer_perf_backend_log_is_deduplicated(monkeypatch):
    seen = []
    monkeypatch.setattr(mod, "viz_perf_enabled", lambda: True)
    monkeypatch.setattr(mod.logger, "info", lambda msg, *args: seen.append(msg % args if args else str(msg)))
    fake = SimpleNamespace(
        _CAIRO_CHILD_NAME="cairo",
        _effect_name="Bars",
        _freq_scale_name="Linear",
        _num_bars=48,
        _input_band_count=2048,
        _active=True,
        _viz_perf_backend_sig="",
        requires_stereo_spectrum=lambda: False,
    )

    mod.HybridVisualizer._log_backend_perf_state(fake, "bars_gl")
    mod.HybridVisualizer._log_backend_perf_state(fake, "bars_gl")
    fake._effect_name = "Dots"
    mod.HybridVisualizer._log_backend_perf_state(fake, "gl")

    assert len(seen) == 2
    assert "effect=Bars backend=bars_gl stereo=0 bars=48 input_bands=2048 scale=Linear active=1" in seen[0]
    assert "effect=Dots backend=gl stereo=0 bars=48 input_bands=2048 scale=Linear active=1" in seen[1]


def test_draw_freq_axis_strip_skips_when_hidden(monkeypatch):
    seen = []
    fake = SimpleNamespace(
        _freq_scale_name="Linear",
        _input_band_count=512,
    )
    monkeypatch.setattr(mod, "_hide_freq_axis_debug", lambda: True)
    monkeypatch.setattr(mod, "_draw_freq_axis_cairo", lambda *args, **kwargs: seen.append(True))

    mod.HybridVisualizer._draw_freq_axis_strip(fake, None, None, 100, 50)

    assert seen == []
