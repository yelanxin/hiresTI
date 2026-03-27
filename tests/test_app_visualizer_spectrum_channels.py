import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from app import app_visualizer as mod


def _make_app(*, page="spectrum", visible=True, stereo_needed=False, lyrics_motion=1):
    spectrum_calls = []
    stereo_calls = []
    app = SimpleNamespace(
        _viz_current_page=page,
        settings={"lyrics_bg_motion": lyrics_motion},
        _sync_viz_tab_runtime_state=lambda: None,
        _should_enable_spectrum_stream=lambda: mod._should_enable_spectrum_stream(app),
        player=SimpleNamespace(
            set_spectrum_enabled=lambda enabled: spectrum_calls.append(bool(enabled)),
            set_spectrum_stereo_enabled=lambda enabled: stereo_calls.append(bool(enabled)),
        ),
        viz=SimpleNamespace(
            set_active=lambda _active: None,
            requires_stereo_spectrum=lambda: bool(stereo_needed),
        ),
        bg_viz=SimpleNamespace(set_active=lambda _active: None),
        _is_viz_surface_visible=lambda: bool(visible),
    )
    return app, spectrum_calls, stereo_calls


def test_sync_spectrum_stream_state_requests_mono_for_non_stereo_effect():
    app, spectrum_calls, stereo_calls = _make_app(page="spectrum", visible=True, stereo_needed=False)

    mod._sync_spectrum_stream_state(app)

    assert spectrum_calls == [True]
    assert stereo_calls == [False]


def test_sync_spectrum_stream_state_requests_stereo_for_stereo_effect():
    app, spectrum_calls, stereo_calls = _make_app(page="spectrum", visible=True, stereo_needed=True)

    mod._sync_spectrum_stream_state(app)

    assert spectrum_calls == [True]
    assert stereo_calls == [True]


def test_sync_spectrum_stream_state_requests_mono_for_lyrics_motion():
    app, spectrum_calls, stereo_calls = _make_app(page="lyrics", visible=True, stereo_needed=True, lyrics_motion=1)

    mod._sync_spectrum_stream_state(app)

    assert spectrum_calls == [True]
    assert stereo_calls == [False]
