import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from _rust import audio as rust_audio


def test_viz_render_tick_forces_runtime_cache_refresh():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = SimpleNamespace(available=True)
    adapter._viz_render_source = 123
    adapter._rust_spectrum_enabled = True
    adapter._cached_pos_s = 1.25
    adapter._viz_trace_enabled = False
    adapter._viz_diag_last_ts = 0.0
    adapter._viz_debug_last_ts = 0.0
    adapter._on_spectrum_callback = lambda frame, pos: seen.append((frame, pos))
    adapter._estimate_rust_visual_delay_ms = lambda current_pos_s=None, msg_pos_s=None: 0
    adapter._sample_spectrum_at_pos = lambda pos: [0.1, 0.2, 0.3]
    adapter._viz_last_render_frame = None
    adapter._viz_interp_lookback_s = 0.06

    calls = []
    seen = []

    def fake_refresh(force=False):
        calls.append(bool(force))

    adapter._refresh_rust_cache = fake_refresh

    ok = rust_audio.RustAudioPlayerAdapter._viz_render_tick(adapter)

    assert ok is True
    assert calls == [True]
    assert seen == [([0.1, 0.2, 0.3], 1.19)]


def test_sample_spectrum_at_pos_prefers_rust_sampler():
    seen = []
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._viz_rust_sampler = SimpleNamespace(
        sample=lambda pos, stereo=False, out_len=0: seen.append((pos, stereo, out_len)) or [0.4, 0.2]
    )
    adapter._rust_spectrum_stereo_enabled = False
    adapter._rust_spectrum_active_bands = 512
    adapter._viz_spectrum_queue = []

    out = rust_audio.RustAudioPlayerAdapter._sample_spectrum_at_pos(adapter, 1.5)

    assert out == [0.4, 0.2]
    assert seen == [(1.5, False, 512)]


def test_reset_rust_visual_sync_state_clears_rust_sampler():
    calls = []
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._viz_latency_cached_ms = 1.0
    adapter._viz_latency_smooth_ms = 2.0
    adapter._viz_msg_age_smooth_ms = 3.0
    adapter._viz_latency_last_probe_ts = 4.0
    adapter._last_rust_spectrum_seq = 9
    adapter._viz_spectrum_queue = []
    adapter._viz_rust_sampler = SimpleNamespace(clear=lambda: calls.append("clear"))
    adapter._viz_last_render_frame = [1.0]
    adapter._rust_last_spectrum_seen_ts = 8.0
    adapter._viz_epoch = 4

    rust_audio.RustAudioPlayerAdapter._reset_rust_visual_sync_state(adapter)

    assert calls == ["clear"]
    assert adapter._last_rust_spectrum_seq == 0
    assert adapter._viz_last_render_frame is None
    assert adapter._viz_epoch == 5


def test_enqueue_rust_spectrum_pushes_frame_into_rust_sampler():
    pushed = []
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._viz_spectrum_queue = []
    adapter._viz_rust_sampler = SimpleNamespace(push_frame=lambda pos, frame: pushed.append((pos, frame)))
    adapter._last_rust_spectrum_seq = 0
    adapter._viz_last_render_frame = None
    adapter._cached_pos_s = 1.0
    adapter._viz_trace_enabled = False

    rust_audio.RustAudioPlayerAdapter._enqueue_rust_spectrum(adapter, 1.25, [0.1, 0.2])

    assert list(adapter._viz_spectrum_queue) == [(1.25, [0.1, 0.2])]
    assert pushed == [(1.25, [0.1, 0.2])]


def test_set_spectrum_stereo_enabled_clears_old_queue_state():
    calls = []
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust_spectrum_stereo_enabled = False
    adapter._rust = SimpleNamespace(available=True, set_spectrum_stereo_enabled=lambda enabled: calls.append(("rust", bool(enabled))))
    adapter._viz_spectrum_queue = [("old", [1.0])]
    adapter._viz_last_render_frame = [0.2]
    adapter._last_rust_spectrum_seq = 7
    adapter._viz_rust_sampler = SimpleNamespace(clear=lambda: calls.append(("clear",)))

    ok = rust_audio.RustAudioPlayerAdapter.set_spectrum_stereo_enabled(adapter, True)

    assert ok is True
    assert adapter._rust_spectrum_stereo_enabled is True
    assert adapter._viz_spectrum_queue == []
    assert adapter._viz_last_render_frame is None
    assert adapter._last_rust_spectrum_seq == 0
    assert calls == [("rust", True), ("clear",)]


def test_sample_spectrum_at_pos_handles_mixed_mono_and_stereo_frames():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._viz_rust_sampler = None
    adapter._viz_spectrum_queue = [
        (1.0, [0.0, 1.0]),
        (2.0, {"mono": [1.0, 0.0], "left": [0.2, 0.8], "right": [0.8, 0.2]}),
    ]

    out = rust_audio.RustAudioPlayerAdapter._sample_spectrum_at_pos(adapter, 1.5)

    assert out == {
        "mono": [0.5, 0.5],
        "left": [0.1, 0.9],
        "right": [0.4, 0.6],
    }
