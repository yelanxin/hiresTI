import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from app import app_builders


class _Entry:
    def __init__(self, focused=False):
        self.focused = bool(focused)

    def has_focus(self):
        return self.focused


class _Revealer:
    def __init__(self, reveal=False):
        self.reveal = bool(reveal)

    def get_reveal_child(self):
        return self.reveal


def test_w_toggles_now_playing_when_search_is_not_focused():
    calls = []
    app = SimpleNamespace(
        search_entry=_Entry(focused=False),
        now_playing_revealer=_Revealer(reveal=False),
        toggle_now_playing_overlay=lambda *_args: calls.append("toggle"),
    )

    handled = app_builders.on_key_pressed(app, None, app_builders.Gdk.KEY_w, 0, 0)

    assert handled is True
    assert calls == ["toggle"]


def test_w_does_not_intercept_search_typing_when_now_playing_is_closed():
    calls = []
    app = SimpleNamespace(
        search_entry=_Entry(focused=True),
        now_playing_revealer=_Revealer(reveal=False),
        toggle_now_playing_overlay=lambda *_args: calls.append("toggle"),
    )

    handled = app_builders.on_key_pressed(app, None, app_builders.Gdk.KEY_w, 0, 0)

    assert handled is False
    assert calls == []
