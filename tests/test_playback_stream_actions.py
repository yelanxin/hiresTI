import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from types import SimpleNamespace

from actions import playback_stream_actions


def _make_app(calls):
    app = SimpleNamespace()
    app.player = SimpleNamespace(
        stop=lambda: calls.append(("stop",)),
        load=lambda url: calls.append(("load", url)),
        play=lambda: calls.append(("play",)),
        seek=lambda value: calls.append(("seek", float(value))),
    )
    app.backend = SimpleNamespace()
    app._mpris_sync_playback = lambda: calls.append(("sync_playback",))
    app._mpris_emit_seeked = lambda seconds: calls.append(("seeked", float(seconds)))
    return app


def test_stream_reload_announces_the_restored_position_with_seeked(monkeypatch):
    calls = []
    monkeypatch.setattr(
        playback_stream_actions,
        "GLib",
        SimpleNamespace(timeout_add=lambda _delay, callback: callback()),
    )
    app = _make_app(calls)

    playback_stream_actions.restart_player_with_url(app, "https://example/stream", 42.0)

    assert ("seek", 42.0) in calls
    assert ("seeked", 42.0) in calls


def test_stream_reload_without_url_is_a_no_op(monkeypatch):
    calls = []
    monkeypatch.setattr(
        playback_stream_actions,
        "GLib",
        SimpleNamespace(timeout_add=lambda _delay, callback: callback()),
    )
    app = _make_app(calls)

    playback_stream_actions.restart_player_with_url(app, "", 42.0)

    assert calls == []
