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


class _Label:
    def __init__(self):
        self.text = ""
        self.visible = True

    def set_text(self, value):
        self.text = str(value)

    def set_visible(self, value):
        self.visible = bool(value)


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


def test_lock_volume_controls_disables_slider_even_when_hw_volume_is_available():
    player_calls = []
    hw_calls = []
    app = SimpleNamespace(
        settings={"volume": 37},
        player=SimpleNamespace(
            set_volume=lambda value: player_calls.append(round(float(value), 2)),
            usb_hw_volume_supported=lambda: True,
            usb_hw_volume_set_percent=lambda value: hw_calls.append(float(value)),
        ),
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

    assert player_calls == [1.0]
    assert hw_calls == []
    assert app.vol_scale.sensitive_calls[-1] is False
    assert app.now_playing_vol_scale.sensitive_calls[-1] is False
    assert app.vol_btn.sensitive_calls[-1] is False
    assert app.now_playing_vol_btn.sensitive_calls[-1] is False


def test_on_hw_volume_changed_syncs_ui_settings_and_mpris():
    sync_calls = []
    db_calls = []
    mpris_calls = []
    save_calls = []
    app = SimpleNamespace(
        settings={"volume": 80},
        player=SimpleNamespace(usb_hw_volume_raw_to_percent=lambda raw: 62.5),
        _sync_volume_ui_state=lambda value=None, source_scale=None: sync_calls.append(float(value)),
        _update_volume_db_label=lambda value: db_calls.append(float(value)),
        _mpris_sync_volume=lambda: mpris_calls.append(True),
        schedule_save_settings=lambda: save_calls.append(True),
    )

    handled = app_builders._on_hw_volume_changed(app, -1234)

    assert handled is False
    assert app.settings["volume"] == 62
    assert sync_calls == [62.5]
    assert db_calls == [62.5]
    assert mpris_calls == [True]
    assert save_calls == [True]


def test_on_hw_volume_changed_is_ignored_while_bit_perfect_is_enabled():
    sync_calls = []
    app = SimpleNamespace(
        settings={"volume": 80, "bit_perfect": True},
        player=SimpleNamespace(usb_hw_volume_raw_to_percent=lambda raw: 62.5),
        _sync_volume_ui_state=lambda value=None, source_scale=None: sync_calls.append(float(value)),
    )

    handled = app_builders._on_hw_volume_changed(app, -1234)

    assert handled is False
    assert app.settings["volume"] == 80
    assert sync_calls == []


def test_sync_volume_ui_state_keeps_standard_icon_when_hardware_available():
    app = SimpleNamespace(
        settings={"volume": 55},
        player=SimpleNamespace(usb_hw_volume_supported=lambda: True),
        vol_scale=_Scale(55),
        now_playing_vol_scale=_Scale(55),
        vol_btn=_Button(),
        now_playing_vol_btn=_Button(),
        _volume_ui_syncing=False,
    )

    app_builders._sync_volume_ui_state(app, value=55)

    assert app.vol_btn.icons[-1] == "hiresti-volume-medium-symbolic"
    assert app.now_playing_vol_btn.icons[-1] == "hiresti-volume-medium-symbolic"


def test_update_volume_device_label_shows_current_device_for_hw_volume():
    app = SimpleNamespace(
        current_device_name="FIIO KA13",
        player=SimpleNamespace(usb_hw_volume_supported=lambda: True),
        vol_device_label=_Label(),
        now_playing_vol_device_label=_Label(),
    )

    app_builders._update_volume_device_label(app)

    assert app.vol_device_label.text == "Hardware Volume\nFIIO KA13"
    assert app.vol_device_label.visible is True
    assert app.now_playing_vol_device_label.text == "Hardware Volume\nFIIO KA13"
    assert app.now_playing_vol_device_label.visible is True
