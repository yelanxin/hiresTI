import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from viz import visualizer as mod


def test_spectrum_visualizer_update_data_skips_stereo_builds_for_mono_effect():
    calls = []
    obj = SimpleNamespace(
        num_bars=32,
        _input_band_count=2048,
        _rust_state_engine=None,
        target_heights=[],
        target_left_channel_heights=[],
        target_right_channel_heights=[],
        _bass_target=0.0,
        requires_stereo_spectrum=lambda: False,
        _map_magnitudes_to_heights=lambda vals, **_kwargs: calls.append(list(vals)) or [0.5, 0.25],
    )

    mod.SpectrumVisualizer.update_data(
        obj,
        {"mono": [1.0, 2.0, 3.0], "left": [9.0], "right": [8.0]},
    )

    assert len(calls) == 1
    assert obj.target_heights == [0.5, 0.25]
    assert obj.target_left_channel_heights == [0.5, 0.25]
    assert obj.target_right_channel_heights == [0.5, 0.25]


def test_spectrum_visualizer_tick_uses_rust_state_engine_for_mono_effect():
    class _StateEngine:
        def __init__(self):
            self.targets = []

        def set_target(self, levels):
            self.targets.append(list(levels))
            return len(levels)

        def tick_copy(self, cur, trail, peak):
            cur[0] = 0.4
            cur[1] = 0.2
            trail[0] = 0.5
            trail[1] = 0.3
            peak[0] = 0.6
            peak[1] = 0.35
            return 2, 0.18

    calls = []
    obj = SimpleNamespace(
        num_bars=2,
        _input_band_count=2048,
        target_heights=[0.0, 0.0],
        current_heights=[0.0, 0.0],
        target_left_channel_heights=[0.0, 0.0],
        target_right_channel_heights=[0.0, 0.0],
        left_channel_heights=[0.0, 0.0],
        right_channel_heights=[0.0, 0.0],
        left_peak_holds=[0.0, 0.0],
        right_peak_holds=[0.0, 0.0],
        left_peak_ttl=[0, 0],
        right_peak_ttl=[0, 0],
        trail_heights=[0.0, 0.0],
        peak_holds=[0.0, 0.0],
        peak_ttl=[0, 0],
        left_log_heat_history=[],
        right_log_heat_history=[],
        pro_fall_history=[],
        _effect_code=0,
        _active=True,
        _profile_cfg={"smooth": 0.2, "beat_mul": 0.5, "peak_hold_frames": 3, "peak_fall": 0.05, "trail_decay": 0.9},
        phase=0.0,
        bass_level=0.0,
        _bass_target=0.0,
        _rust_state_engine=_StateEngine(),
        _rust_cur_arr=(mod.ctypes.c_float * 2)(0.0, 0.0),
        _rust_trail_arr=(mod.ctypes.c_float * 2)(0.0, 0.0),
        _rust_peak_arr=(mod.ctypes.c_float * 2)(0.0, 0.0),
        requires_stereo_spectrum=lambda: False,
        _map_magnitudes_to_heights=lambda vals, **_kwargs: calls.append(list(vals)) or [0.8, 0.6],
        queue_draw=lambda: calls.append("draw"),
        _build_log_bins=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected history build")),
        _summarize_pro_fall_bins=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected history summarize")),
    )

    mod.SpectrumVisualizer.update_data(obj, {"mono": [1.0, 2.0, 3.0]})
    assert obj._rust_state_engine.targets == [[0.8, 0.6]]

    assert mod.SpectrumVisualizer._on_animation_tick(obj) is True
    assert obj.current_heights == pytest.approx([0.4, 0.2])
    assert obj.trail_heights == pytest.approx([0.5, 0.3])
    assert obj.peak_holds == pytest.approx([0.6, 0.35])
    assert obj.left_channel_heights == pytest.approx([0.4, 0.2])
    assert obj.right_channel_heights == pytest.approx([0.4, 0.2])
    assert obj.bass_level == pytest.approx(0.18)
    assert calls[-1] == "draw"


def test_bars_gl_update_data_skips_extra_builds_for_mono_effect(monkeypatch):
    calls = []

    def fake_build(vals, out_count, **_kwargs):
        calls.append(list(vals))
        return [0.2] * out_count

    monkeypatch.setattr(mod, "_build_linear_spectrum_bins", fake_build)

    obj = SimpleNamespace(
        frequency_scale_name=mod._FREQ_SCALE_LINEAR,
        num_bars=4,
        _input_band_count=512,
        _rust_state_engine=None,
        target_heights=[0.0] * 512,
        target_left_heights=[0.0] * 512,
        target_right_heights=[0.0] * 512,
        _bass_target=0.0,
        _balance_target=1.0,
        requires_stereo_spectrum=lambda: False,
    )

    mod.BarsGLVisualizer.update_data(
        obj,
        {"mono": [1.0, 2.0, 3.0], "left": [9.0], "right": [8.0]},
    )

    assert len(calls) == 1
    assert obj.target_heights[:4] == [0.2] * 4
    assert obj.target_left_heights[:4] == [0.2] * 4
    assert obj.target_right_heights[:4] == [0.2] * 4
    assert obj._balance_target == 0.0


def test_hybrid_copy_frame_drops_stereo_payload_for_mono_effect():
    frame = mod.HybridVisualizer._copy_frame(
        {"mono": [1.0], "left": [2.0], "right": [3.0]},
        stereo=False,
    )

    assert frame == [1.0]


def test_spectrum_visualizer_tick_skips_history_work_for_normal_effect():
    queued = []
    obj = SimpleNamespace(
        _active=True,
        _profile_cfg={"smooth": 0.2, "beat_mul": 0.5, "peak_hold_frames": 3, "peak_fall": 0.05, "trail_decay": 0.9},
        phase=0.0,
        bass_level=0.0,
        _bass_target=0.0,
        num_bars=2,
        target_heights=[0.1, 0.2],
        current_heights=[0.0, 0.0],
        target_left_channel_heights=[0.1, 0.2],
        target_right_channel_heights=[0.1, 0.2],
        left_channel_heights=[0.0, 0.0],
        right_channel_heights=[0.0, 0.0],
        left_peak_holds=[0.0, 0.0],
        right_peak_holds=[0.0, 0.0],
        left_peak_ttl=[0, 0],
        right_peak_ttl=[0, 0],
        trail_heights=[0.0, 0.0],
        peak_holds=[0.0, 0.0],
        peak_ttl=[0, 0],
        left_log_heat_history=[],
        right_log_heat_history=[],
        pro_fall_history=[],
        _effect_code=0,
        queue_draw=lambda: queued.append(True),
        _rust_state_engine=None,
        requires_stereo_spectrum=lambda: False,
        _build_log_bins=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected history build")),
        _summarize_pro_fall_bins=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected history summarize")),
    )

    assert mod.SpectrumVisualizer._on_animation_tick(obj) is True
    assert queued == [True]
    assert obj.left_log_heat_history == []
    assert obj.right_log_heat_history == []
    assert obj.pro_fall_history == []


def test_dots_gl_update_data_uses_rust_state_engine_when_available(monkeypatch):
    calls = []

    def fake_build(vals, out_count, **_kwargs):
        calls.append(("build", list(vals)))
        return [0.4] * out_count

    class _StateEngine:
        def __init__(self):
            self.targets = []

        def set_target(self, levels):
            self.targets.append(list(levels))
            return len(self.targets[-1])

    monkeypatch.setattr(mod, "_build_linear_spectrum_bins", fake_build)
    engine = _StateEngine()
    obj = SimpleNamespace(
        frequency_scale_name=mod._FREQ_SCALE_LINEAR,
        num_bars=4,
        _input_band_count=512,
        _rust_core=SimpleNamespace(available=False),
        _rust_state_engine=engine,
        target_heights=[0.0] * 512,
    )

    mod.DotsGLVisualizer.update_data(obj, {"mono": [1.0, 2.0, 3.0]})

    assert calls == [("build", [1.0, 2.0, 3.0])]
    assert engine.targets == [[0.4, 0.4, 0.4, 0.4]]


def test_bars_gl_update_data_uses_rust_state_engine_when_available(monkeypatch):
    calls = []

    def fake_build(vals, out_count, **_kwargs):
        calls.append(list(vals))
        return [0.3] * out_count

    class _StateEngine:
        def __init__(self):
            self.targets = []

        def set_target(self, levels):
            self.targets.append(list(levels))
            return len(self.targets[-1])

    monkeypatch.setattr(mod, "_build_linear_spectrum_bins", fake_build)
    engine = _StateEngine()
    obj = SimpleNamespace(
        frequency_scale_name=mod._FREQ_SCALE_LINEAR,
        num_bars=4,
        _input_band_count=512,
        _rust_state_engine=engine,
        _bass_target=0.0,
        _balance_target=1.0,
        requires_stereo_spectrum=lambda: False,
    )

    mod.BarsGLVisualizer.update_data(obj, {"mono": [1.0, 2.0, 3.0]})

    assert calls == [[1.0, 2.0, 3.0]]
    assert engine.targets == [[0.3, 0.3, 0.3, 0.3]]
    assert obj._balance_target == 0.0


def test_bars_gl_update_data_prefers_rust_mapper_when_available():
    class _RustCore:
        available = True

        def __init__(self):
            self.calls = []

        def map_spectrum_linear(self, values, out_count, **kwargs):
            self.calls.append((list(values), int(out_count), dict(kwargs)))
            return [0.6] * int(out_count)

    class _StateEngine:
        def __init__(self):
            self.targets = []

        def set_target(self, levels):
            self.targets.append(list(levels))
            return len(levels)

    rust_core = _RustCore()
    engine = _StateEngine()
    obj = SimpleNamespace(
        frequency_scale_name=mod._FREQ_SCALE_LINEAR,
        num_bars=4,
        _input_band_count=512,
        _rust_core=rust_core,
        _rust_state_engine=engine,
        _bass_target=0.0,
        _balance_target=1.0,
        requires_stereo_spectrum=lambda: False,
    )

    mod.BarsGLVisualizer.update_data(obj, {"mono": [1.0, 2.0, 3.0]})

    assert rust_core.calls == [([1.0, 2.0, 3.0], 4, {"analysis_bands": 3, "db_min": -80.0, "db_range": 80.0})]
    assert engine.targets == [[0.6, 0.6, 0.6, 0.6]]
    assert obj._balance_target == 0.0


def test_dots_gl_update_data_prefers_rust_mapper_when_available():
    class _RustCore:
        available = True

        def __init__(self):
            self.calls = []

        def map_spectrum_log(self, values, out_count, **kwargs):
            self.calls.append((list(values), int(out_count), dict(kwargs)))
            return [0.9] * int(out_count)

    class _StateEngine:
        def __init__(self):
            self.targets = []

        def set_target(self, levels):
            self.targets.append(list(levels))
            return len(levels)

    rust_core = _RustCore()
    engine = _StateEngine()
    obj = SimpleNamespace(
        frequency_scale_name=mod._FREQ_SCALE_LOG,
        num_bars=4,
        _input_band_count=512,
        _rust_core=rust_core,
        _rust_state_engine=engine,
        target_heights=[0.0] * 512,
    )

    mod.DotsGLVisualizer.update_data(obj, {"mono": [1.0, 2.0, 3.0]})

    assert rust_core.calls == [([1.0, 2.0, 3.0], 4, {"db_min": -80.0, "db_range": 80.0})]
    assert engine.targets == [[0.9, 0.9, 0.9, 0.9]]


def test_spectrum_visualizer_update_data_uses_rust_stereo_state_engine_for_stereo_effect():
    class _StereoEngine:
        def __init__(self):
            self.targets = []

        def set_targets(self, left, right):
            self.targets.append((list(left), list(right)))
            return len(left)

    calls = []
    obj = SimpleNamespace(
        num_bars=2,
        _input_band_count=2048,
        target_heights=[],
        target_left_channel_heights=[],
        target_right_channel_heights=[],
        _bass_target=0.0,
        _rust_state_engine=None,
        _rust_stereo_state_engine=_StereoEngine(),
        requires_stereo_spectrum=lambda: True,
        _map_magnitudes_to_heights=lambda vals, **_kwargs: calls.append(list(vals)) or [float(len(calls))] * 2,
    )

    mod.SpectrumVisualizer.update_data(
        obj,
        {"mono": [1.0, 2.0], "left": [3.0, 4.0], "right": [5.0, 6.0]},
    )

    assert len(calls) == 3
    assert obj._rust_stereo_state_engine.targets == [([2.0, 2.0], [3.0, 3.0])]


def test_bars_gl_update_data_uses_rust_stereo_state_engine_for_stereo_effect(monkeypatch):
    calls = []

    def fake_build(vals, out_count, **_kwargs):
        calls.append(list(vals))
        return [float(len(calls))] * out_count

    class _StereoEngine:
        def __init__(self):
            self.targets = []

        def set_targets(self, left, right):
            self.targets.append((list(left), list(right)))
            return len(left)

    monkeypatch.setattr(mod, "_build_linear_spectrum_bins", fake_build)
    obj = SimpleNamespace(
        frequency_scale_name=mod._FREQ_SCALE_LINEAR,
        num_bars=2,
        _input_band_count=512,
        _rust_state_engine=None,
        _rust_stereo_state_engine=_StereoEngine(),
        _bass_target=0.0,
        _balance_target=1.0,
        requires_stereo_spectrum=lambda: True,
    )

    mod.BarsGLVisualizer.update_data(
        obj,
        {"mono": [1.0, 2.0], "left": [3.0, 4.0], "right": [5.0, 6.0]},
    )

    assert len(calls) == 3
    assert obj._rust_stereo_state_engine.targets == [([2.0, 2.0], [3.0, 3.0])]
