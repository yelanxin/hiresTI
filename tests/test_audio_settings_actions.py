import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from actions import audio_settings_actions


class _Switch:
    def __init__(self, active=False):
        self._active = bool(active)
        self.sensitive_calls = []

    def set_sensitive(self, value):
        self.sensitive_calls.append(bool(value))

    def set_active(self, value):
        self._active = bool(value)

    def get_active(self):
        return bool(self._active)


class _DriverDropdown:
    def __init__(self):
        self.sensitive_calls = []

    def set_sensitive(self, value):
        self.sensitive_calls.append(bool(value))

    def get_selected_item(self):
        return None


class _DriverItem:
    def __init__(self, text):
        self._text = str(text)

    def get_string(self):
        return self._text


class _SelectableDropdown:
    def __init__(self, selected=0):
        self._selected = int(selected)
        self.selected_calls = []

    def get_selected(self):
        return self._selected

    def set_selected(self, value):
        self._selected = int(value)
        self.selected_calls.append(int(value))


class _Player:
    def __init__(self):
        self.toggle_calls = []
        self.stream_info = {}

    def toggle_bit_perfect(self, enabled, exclusive_lock=False):
        self.toggle_calls.append((bool(enabled), bool(exclusive_lock)))

    def set_output(self, driver, device_id):
        raise NotImplementedError


class _Visible:
    def __init__(self):
        self.visible_calls = []

    def set_visible(self, value):
        self.visible_calls.append(bool(value))


def test_on_bit_perfect_toggled_allows_missing_eq_controls():
    saved = []
    locked = []
    player = _Player()
    ex_switch = _Switch(active=False)
    driver_dd = _DriverDropdown()
    bp_label = _Visible()
    app = SimpleNamespace(
        settings={},
        save_settings=lambda: saved.append(True),
        _lock_volume_controls=lambda state: locked.append(bool(state)),
        ex_switch=ex_switch,
        player=player,
        eq_btn=None,
        eq_pop=None,
        bp_label=bp_label,
        driver_dd=driver_dd,
        _force_driver_selection=lambda _driver: None,
        on_driver_changed=lambda *_args: None,
    )

    audio_settings_actions.on_bit_perfect_toggled(app, None, True)

    assert app.settings["bit_perfect"] is True
    assert saved == [True]
    assert locked == [True]
    assert player.toggle_calls == [(True, False)]
    assert ex_switch.sensitive_calls == [True]
    assert driver_dd.sensitive_calls == [True]
    assert bp_label.visible_calls == [True]


def test_on_device_changed_rolls_back_selection_when_output_switch_fails(monkeypatch):
    notices = []
    saved = []
    tech_updates = []

    class _BusyPlayer(_Player):
        def __init__(self):
            super().__init__()
            self.set_output_calls = []

        def set_output(self, driver, device_id):
            self.set_output_calls.append((driver, device_id))
            return False

    driver_dd = SimpleNamespace(get_selected_item=lambda: _DriverItem("ALSA"))
    device_dd = _SelectableDropdown(selected=1)
    player = _BusyPlayer()
    app = SimpleNamespace(
        ignore_device_change=False,
        current_device_list=[
            {"name": "DAC One", "device_id": "hw:1,0"},
            {"name": "DAC Two", "device_id": "hw:2,0"},
        ],
        current_device_name="DAC One",
        settings={"device": "DAC One"},
        player=player,
        driver_dd=driver_dd,
        device_dd=device_dd,
        save_settings=lambda: saved.append(True),
        update_tech_label=lambda stream: tech_updates.append(stream),
        show_output_notice=lambda text, state, timeout: notices.append((text, state, timeout)),
        _last_disconnected_device_name="",
        _last_disconnected_driver="",
    )

    monkeypatch.setattr(audio_settings_actions, "_stop_output_hotplug_watch", lambda _app: None)
    monkeypatch.setattr(audio_settings_actions, "_touch_output_probe_burst", lambda _app, seconds=0: None)
    monkeypatch.setattr(audio_settings_actions, "update_output_status_ui", lambda _app: None)

    audio_settings_actions.on_device_changed(app, device_dd, None)

    assert player.set_output_calls == [("ALSA", "hw:2,0")]
    assert device_dd.get_selected() == 0
    assert device_dd.selected_calls == [0]
    assert app.current_device_name == "DAC One"
    assert app.settings["device"] == "DAC One"
    assert saved == []
    assert tech_updates == [{}]
    assert notices == [("Output device unavailable: DAC Two", "error", 4200)]
