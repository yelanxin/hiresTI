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


class _ModelDropdown(_SelectableDropdown):
    def __init__(self, selected=0):
        super().__init__(selected=selected)
        self.model = []
        self.sensitive_calls = []

    def set_model(self, model):
        self.model = list(model)

    def set_sensitive(self, value):
        self.sensitive_calls.append(bool(value))

    def get_selected_item(self):
        if 0 <= self._selected < len(self.model):
            return _DriverItem(self.model[self._selected])
        return None


class _Player:
    def __init__(self):
        self.toggle_calls = []
        self.stream_info = {}
        self.set_output_calls = []
        self.output_format_pref_calls = []

    def toggle_bit_perfect(self, enabled, exclusive_lock=False):
        self.toggle_calls.append((bool(enabled), bool(exclusive_lock)))

    def set_output(self, driver, device_id):
        self.set_output_calls.append((driver, device_id))
        return True

    def set_output_format_preference(self, format_name=None):
        self.output_format_pref_calls.append(format_name)
        return True


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


def test_sync_output_bit_depth_dropdown_limits_choices_to_supported_depths(monkeypatch):
    monkeypatch.setattr(audio_settings_actions.Gtk, "StringList", SimpleNamespace(new=lambda items: list(items)))

    saved = []
    dd = _ModelDropdown()
    player = _Player()
    app = SimpleNamespace(
        bit_depth_dd=dd,
        settings={"output_bit_depth": "24-bit"},
        save_settings=lambda: saved.append(True),
        player=player,
        driver_dd=SimpleNamespace(get_selected_item=lambda: _DriverItem("ALSA")),
        ignore_output_bit_depth_change=False,
    )
    device_info = {
        "name": "USB DAC",
        "device_id": "hw:1,0",
        "supported_formats": ["S16LE", "S32LE"],
        "supported_bit_depths": [16, 32],
    }

    audio_settings_actions._sync_output_bit_depth_dropdown(app, device_info)

    assert dd.model == ["Auto", "16-bit", "32-bit"]
    assert dd.get_selected() == 0
    assert dd.sensitive_calls == [True]
    assert app.settings["output_bit_depth"] == "Auto"
    assert saved == [True]
    assert player.output_format_pref_calls == [None]


def test_sync_output_bit_depth_dropdown_disables_for_pipewire(monkeypatch):
    monkeypatch.setattr(audio_settings_actions.Gtk, "StringList", SimpleNamespace(new=lambda items: list(items)))

    dd = _ModelDropdown()
    player = _Player()
    app = SimpleNamespace(
        bit_depth_dd=dd,
        settings={"output_bit_depth": "24-bit"},
        save_settings=lambda: None,
        player=player,
        driver_dd=SimpleNamespace(get_selected_item=lambda: _DriverItem("PipeWire")),
        ignore_output_bit_depth_change=False,
    )
    device_info = {
        "name": "USB DAC",
        "device_id": "alsa_output.usb-fiio.pro-output-0",
        "supported_formats": ["S16LE", "S32LE"],
        "supported_bit_depths": [16, 32],
    }

    audio_settings_actions._sync_output_bit_depth_dropdown(app, device_info)

    assert dd.model == ["Auto"]
    assert dd.get_selected() == 0
    assert dd.sensitive_calls == [False]
    assert app.settings["output_bit_depth"] == "24-bit"
    assert player.output_format_pref_calls == [None]


def test_on_output_bit_depth_changed_applies_supported_format(monkeypatch):
    notices = []
    saved = []
    monkeypatch.setattr(audio_settings_actions, "update_output_status_ui", lambda _app: None)

    bit_depth_dd = _ModelDropdown(selected=2)
    bit_depth_dd.model = ["Auto", "16-bit", "24-bit"]
    device_dd = _SelectableDropdown(selected=0)
    driver_dd = SimpleNamespace(get_selected_item=lambda: _DriverItem("ALSA"))
    player = _Player()
    app = SimpleNamespace(
        bit_depth_dd=bit_depth_dd,
        device_dd=device_dd,
        driver_dd=driver_dd,
        current_device_list=[
            {
                "name": "USB DAC",
                "device_id": "hw:1,0",
                "supported_formats": ["S16LE", "S24_32LE"],
                "supported_bit_depths": [16, 24],
            }
        ],
        settings={"output_bit_depth": "Auto"},
        save_settings=lambda: saved.append(True),
        player=player,
        update_tech_label=lambda _stream: None,
        show_output_notice=lambda text, state, timeout: notices.append((text, state, timeout)),
        _apply_viz_sync_offset_for_device=lambda *_args, **_kwargs: None,
        ignore_output_bit_depth_change=False,
    )

    audio_settings_actions.on_output_bit_depth_changed(app, bit_depth_dd, None)

    assert app.settings["output_bit_depth"] == "24-bit"
    assert saved == [True]
    assert player.output_format_pref_calls == ["S24_32LE"]
    assert player.set_output_calls == [("ALSA", "hw:1,0")]
    assert notices == []
