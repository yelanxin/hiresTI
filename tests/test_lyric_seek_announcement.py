import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from types import SimpleNamespace

import pytest

pytest.importorskip("gi")

from actions import lyrics_playback_actions


class _Row:
    def __init__(self):
        self.controllers = []

    def add_controller(self, controller):
        self.controllers.append(controller)

    def add_css_class(self, _name):
        pass

    def set_cursor(self, _cursor):
        pass


class _Gesture:
    def __init__(self):
        self.handlers = {}

    def set_button(self, _button):
        pass

    def connect(self, name, callback):
        self.handlers[name] = callback


def _attach(monkeypatch, app, time_point):
    gesture = _Gesture()
    monkeypatch.setattr(
        lyrics_playback_actions,
        "Gtk",
        SimpleNamespace(GestureClick=SimpleNamespace(new=lambda: gesture)),
    )
    lyrics_playback_actions._attach_lyric_seek_gesture(_Row(), app, time_point)
    return gesture


def test_lyric_click_announces_the_seek(monkeypatch):
    calls = []
    app = SimpleNamespace(
        player=SimpleNamespace(seek=lambda value: calls.append(("seek", float(value)))),
        _mpris_emit_seeked=lambda seconds: calls.append(("seeked", float(seconds))),
    )

    gesture = _attach(monkeypatch, app, 42.0)
    gesture.handlers["released"](gesture, 1, 0.0, 0.0)

    assert calls == [("seek", 42.0), ("seeked", 42.0)]


def test_failed_lyric_seek_announces_nothing(monkeypatch):
    calls = []

    def _boom(_value):
        raise RuntimeError("seek failed")

    app = SimpleNamespace(
        player=SimpleNamespace(seek=_boom),
        _mpris_emit_seeked=lambda seconds: calls.append(("seeked", float(seconds))),
    )

    gesture = _attach(monkeypatch, app, 42.0)
    gesture.handlers["released"](gesture, 1, 0.0, 0.0)

    assert calls == []
