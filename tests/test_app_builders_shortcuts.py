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


class _Scale:
    def __init__(self, value=0.0):
        self.value = float(value)
        self.sensitive_calls = []

    def set_value(self, value):
        self.value = float(value)

    def get_value(self):
        return self.value

    def set_sensitive(self, value):
        self.sensitive_calls.append(bool(value))


class _Button:
    def __init__(self):
        self.sensitive_calls = []
        self.tooltips = []
        self.icons = []

    def set_sensitive(self, value):
        self.sensitive_calls.append(bool(value))

    def set_tooltip_text(self, value):
        self.tooltips.append(str(value))

    def set_icon_name(self, value):
        self.icons.append(str(value))


class _Popover:
    def __init__(self):
        self.popdown_calls = 0

    def popdown(self):
        self.popdown_calls += 1


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


def test_lock_volume_controls_forces_backend_volume_to_unity_and_restores_saved_volume():
    player_calls = []
    app = SimpleNamespace(
        settings={"volume": 37},
        player=SimpleNamespace(set_volume=lambda value: player_calls.append(round(float(value), 2))),
        vol_scale=_Scale(37),
        now_playing_vol_scale=_Scale(37),
        vol_btn=_Button(),
        now_playing_vol_btn=_Button(),
        vol_pop=_Popover(),
        now_playing_vol_pop=_Popover(),
        eq_btn=_Button(),
        now_playing_eq_btn=_Button(),
        dsp_btn=_Button(),
        now_playing_dsp_btn=_Button(),
        _sync_volume_ui_state=lambda value=None, source_scale=None: (
            app.vol_scale.set_value(value),
            app.now_playing_vol_scale.set_value(value),
        ),
    )

    app_builders._lock_volume_controls(app, True)
    app_builders._lock_volume_controls(app, False)

    assert player_calls == [1.0, 0.37]
    assert app.vol_scale.get_value() == 37.0
    assert app.now_playing_vol_scale.get_value() == 37.0
