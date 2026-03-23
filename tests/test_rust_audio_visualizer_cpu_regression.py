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
