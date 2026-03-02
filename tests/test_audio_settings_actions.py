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


class _Player:
    def __init__(self):
        self.toggle_calls = []

    def toggle_bit_perfect(self, enabled, exclusive_lock=False):
        self.toggle_calls.append((bool(enabled), bool(exclusive_lock)))


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
