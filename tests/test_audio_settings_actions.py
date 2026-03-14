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
        self.model = []
        self._selected = 0
        self.sensitive_calls = []

    def set_model(self, model):
        self.model = list(model)

    def set_selected(self, value):
        self._selected = int(value)

    def set_sensitive(self, value):
        self.sensitive_calls.append(bool(value))

    def get_selected_item(self):
        if 0 <= self._selected < len(self.model):
            return _DriverItem(self.model[self._selected])
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
        self.dsp_enabled = False
        self.dsp_calls = []
        self.stream_info = {}
        self.set_output_calls = []
        self.output_format_pref_calls = []
        self.realtime_priority_calls = []
        self.alsa_buffer_time = 100000
        self.alsa_latency_time = 10000
        self.set_volume_calls = []

    def toggle_bit_perfect(self, enabled, exclusive_lock=False):
        self.toggle_calls.append((bool(enabled), bool(exclusive_lock)))

    def set_dsp_enabled(self, enabled):
        self.dsp_enabled = bool(enabled)
        self.dsp_calls.append(bool(enabled))
        return True

    def set_output(self, driver, device_id):
        self.set_output_calls.append((driver, device_id))
        return True

    def set_output_format_preference(self, format_name=None):
        self.output_format_pref_calls.append(format_name)
        return True

    def set_alsa_mmap_realtime_priority(self, priority):
        self.realtime_priority_calls.append(int(priority))
        return True

    def set_alsa_latency(self, buffer_ms, latency_ms):
        self.alsa_buffer_time = int(float(buffer_ms or 0.0) * 1000.0)
        self.alsa_latency_time = int(float(latency_ms or 0.0) * 1000.0)
        return True

    def set_volume(self, vol):
        self.set_volume_calls.append(float(vol))
        return True

    def get_drivers(self):
        return ["Auto (Default)", "PipeWire", "ALSA（auto）", "ALSA（mmap）"]


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


def test_on_bit_perfect_toggled_disables_dsp_and_shows_notice():
    notices = []
    saved = []
    player = _Player()
    player.dsp_enabled = True
    ex_switch = _Switch(active=False)
    driver_dd = _DriverDropdown()
    app = SimpleNamespace(
        settings={},
        save_settings=lambda: saved.append(True),
        _lock_volume_controls=lambda state: None,
        ex_switch=ex_switch,
        player=player,
        eq_btn=None,
        eq_pop=None,
        bp_label=None,
        driver_dd=driver_dd,
        dsp_btn=None,
        now_playing_dsp_btn=None,
        _force_driver_selection=lambda _driver: None,
        on_driver_changed=lambda *_args: None,
        show_output_notice=lambda text, level, timeout: notices.append((text, level, timeout)),
    )

    audio_settings_actions.on_bit_perfect_toggled(app, None, True)

    assert player.dsp_calls == [False]
    assert app.settings["dsp_enabled"] is False
    assert saved == [True, True]
    assert notices == [("DSP disabled: Bit-Perfect mode enabled", "info", 2600)]


def test_on_latency_changed_restarts_output_for_alsa_even_without_exclusive():
    saved = []
    restarted = []
    player = _Player()
    driver_dd = _DriverDropdown()
    driver_dd.set_model(["ALSA（mmap）"])
    driver_dd.set_selected(0)
    dd = _ModelDropdown()
    dd.set_model(["Low Latency (40ms)"])
    dd.set_selected(0)
    app = SimpleNamespace(
        settings={},
        save_settings=lambda: saved.append(True),
        LATENCY_MAP={"Low Latency (40ms)": (40, 10)},
        player=player,
        driver_dd=driver_dd,
        ex_switch=_Switch(active=False),
        on_driver_changed=lambda *_args: restarted.append(True),
    )

    audio_settings_actions.on_latency_changed(app, dd, None)

    assert app.settings["latency_profile"] == "Low Latency (40ms)"
    assert player.alsa_buffer_time == 40_000
    assert player.alsa_latency_time == 10_000
    assert restarted == [True]
    assert saved == [True]


def test_on_exclusive_toggled_keeps_latency_enabled_for_alsa_driver(monkeypatch):
    player = _Player()
    driver_dd = _DriverDropdown()
    driver_dd.set_model(["ALSA（mmap）"])
    driver_dd.set_selected(0)
    latency_dd = _ModelDropdown()
    app = SimpleNamespace(
        settings={},
        save_settings=lambda: None,
        player=player,
        driver_dd=driver_dd,
        device_dd=object(),
        latency_dd=latency_dd,
        _sync_playback_status_icon=lambda: None,
        on_device_changed=lambda *_args: None,
    )

    monkeypatch.setattr(audio_settings_actions, "_refresh_driver_dropdown_options", lambda *_args, **_kwargs: None)

    audio_settings_actions.on_exclusive_toggled(app, None, False)

    assert latency_dd.sensitive_calls[-1] is True


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


def test_on_mmap_realtime_priority_changed_applies_and_restarts_for_mmap():
    saved = []
    restarts = []
    dd = _ModelDropdown(selected=3)
    dd.model = ["Off", "Low (40)", "Recommended (60)", "High (70)"]
    player = _Player()
    app = SimpleNamespace(
        settings={},
        save_settings=lambda: saved.append(True),
        player=player,
        ALSA_MMAP_REALTIME_PRIORITY_MAP={
            "Off": 0,
            "Low (40)": 40,
            "Recommended (60)": 60,
            "High (70)": 70,
        },
        ALSA_MMAP_REALTIME_PRIORITY_DEFAULT="Recommended (60)",
        driver_dd=SimpleNamespace(get_selected_item=lambda: _DriverItem("ALSA（mmap）")),
        on_driver_changed=lambda *_args: restarts.append(True),
    )

    audio_settings_actions.on_mmap_realtime_priority_changed(app, dd, None)

    assert app.settings["alsa_mmap_realtime_priority"] == "High (70)"
    assert saved == [True]
    assert player.realtime_priority_calls == [70]
    assert restarts == [True]


def test_on_driver_changed_skips_stop_during_first_startup_init(monkeypatch):
    monkeypatch.setattr(audio_settings_actions, "_stop_output_hotplug_watch", lambda _app: None)
    monkeypatch.setattr(audio_settings_actions, "_touch_output_probe_burst", lambda _app, seconds=0: None)
    monkeypatch.setattr(audio_settings_actions, "_sync_output_bit_depth_dropdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(audio_settings_actions, "update_output_status_ui", lambda _app: None)
    monkeypatch.setattr(audio_settings_actions.Gtk, "StringList", SimpleNamespace(new=lambda items: list(items)))
    monkeypatch.setattr(audio_settings_actions.GLib, "idle_add", lambda fn: fn())

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr(audio_settings_actions, "Thread", _ImmediateThread)

    class _StartupPlayer(_Player):
        def __init__(self):
            super().__init__()
            self.stop_calls = []
            self.pause_calls = []
            self.output_state = "idle"
            self.current_device_id = None

        def is_playing(self):
            return False

        def pause(self):
            self.pause_calls.append(True)

        def stop(self):
            self.stop_calls.append(True)

        def get_devices_for_driver(self, driver):
            return [{"name": "DAC", "device_id": "hw:1,0"}]

    player = _StartupPlayer()
    driver_dd = _DriverDropdown()
    driver_dd.model = ["ALSA"]
    device_dd = _ModelDropdown()
    app = SimpleNamespace(
        ignore_driver_change=False,
        ex_switch=_Switch(active=False),
        settings={},
        save_settings=lambda: None,
        player=player,
        driver_dd=driver_dd,
        device_dd=device_dd,
        mmap_realtime_priority_dd=_Switch(),
        current_device_name="Default",
        current_device_list=[],
        update_tech_label=lambda _stream: None,
        _apply_viz_sync_offset_for_device=lambda *_args, **_kwargs: None,
        show_output_notice=lambda *_args, **_kwargs: None,
    )

    audio_settings_actions.on_driver_changed(app, driver_dd, None)

    assert player.pause_calls == []
    assert player.stop_calls == []
    assert player.set_output_calls == [("ALSA", "hw:1,0")]


def test_on_driver_changed_refreshes_dsp_overview(monkeypatch):
    monkeypatch.setattr(audio_settings_actions, "_stop_output_hotplug_watch", lambda _app: None)
    monkeypatch.setattr(audio_settings_actions, "_touch_output_probe_burst", lambda _app, seconds=0: None)
    monkeypatch.setattr(audio_settings_actions, "_sync_output_bit_depth_dropdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(audio_settings_actions, "update_output_status_ui", lambda _app: None)
    monkeypatch.setattr(audio_settings_actions.Gtk, "StringList", SimpleNamespace(new=lambda items: list(items)))
    monkeypatch.setattr(audio_settings_actions.GLib, "idle_add", lambda fn: fn())

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr(audio_settings_actions, "Thread", _ImmediateThread)

    class _StartupPlayer(_Player):
        def __init__(self):
            super().__init__()
            self.output_state = "idle"
            self.current_device_id = None

        def is_playing(self):
            return False

        def stop(self):
            pass

        def get_devices_for_driver(self, driver):
            return [{"name": "DAC", "device_id": "hw:1,0"}]

    dsp_updates = []
    player = _StartupPlayer()
    driver_dd = _DriverDropdown()
    driver_dd.model = ["ALSA"]
    device_dd = _ModelDropdown()
    app = SimpleNamespace(
        ignore_driver_change=False,
        ex_switch=_Switch(active=False),
        settings={},
        save_settings=lambda: None,
        player=player,
        driver_dd=driver_dd,
        device_dd=device_dd,
        mmap_realtime_priority_dd=_Switch(),
        current_device_name="Default",
        current_device_list=[],
        update_tech_label=lambda _stream: None,
        _apply_viz_sync_offset_for_device=lambda *_args, **_kwargs: None,
        _update_dsp_ui_state=lambda: dsp_updates.append(True),
        show_output_notice=lambda *_args, **_kwargs: None,
    )

    audio_settings_actions.on_driver_changed(app, driver_dd, None)

    assert len(dsp_updates) >= 3


def test_passive_sync_device_list_updates_dropdown_without_nameerror(monkeypatch):
    monkeypatch.setattr(audio_settings_actions, "_get_output_probe_intervals", lambda _app: (0.0, 0.0))
    monkeypatch.setattr(audio_settings_actions, "_driver_key", lambda _name: "pipewire")
    monkeypatch.setattr(audio_settings_actions, "_device_enum_signature", lambda devices: tuple(d.get("name") for d in devices))
    monkeypatch.setattr(audio_settings_actions, "_sync_output_bit_depth_dropdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(audio_settings_actions.Gtk, "StringList", SimpleNamespace(new=lambda items: list(items)))
    monkeypatch.setattr(audio_settings_actions.GLib, "idle_add", lambda fn: fn())

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr(audio_settings_actions, "Thread", _ImmediateThread)

    player = SimpleNamespace(
        stream_info={},
        get_devices_for_driver=lambda _driver: [
            {"name": "Monitor 09", "device_id": "pw:1"},
            {"name": "HDMI 1", "device_id": "pw:2"},
        ],
    )
    driver_dd = _DriverDropdown()
    driver_dd.model = ["PipeWire"]
    device_dd = _ModelDropdown(selected=0)
    app = SimpleNamespace(
        _device_list_sync_next_ts=0.0,
        _device_list_sync_running=False,
        ignore_device_change=False,
        _output_hotplug_source=0,
        driver_dd=driver_dd,
        device_dd=device_dd,
        current_device_name="Old Device",
        current_device_list=[{"name": "Old Device", "device_id": "pw:0"}],
        player=player,
        update_tech_label=lambda _stream: None,
    )

    audio_settings_actions._passive_sync_device_list(app)

    assert app.current_device_name == "Monitor 09"
    assert device_dd.model == ["Monitor 09", "HDMI 1"]
    assert device_dd.get_selected() == 0


def test_on_device_changed_normalizes_pipewire_card_profile_target_to_pro_audio(monkeypatch):
    notices = []
    saved = []
    tech_updates = []

    player = _Player()
    driver_dd = SimpleNamespace(get_selected_item=lambda: _DriverItem("PipeWire"))
    device_dd = _SelectableDropdown(selected=0)
    app = SimpleNamespace(
        ignore_device_change=False,
        current_device_list=[
            {
                "name": "Monitor 09",
                "device_id": "pwcardprofile:alsa_card.usb-MUSILAND_Monitor_09-00|output:analog-stereo",
            }
        ],
        current_device_name="Default System Output",
        settings={"device": "Default System Output"},
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
    monkeypatch.setattr(audio_settings_actions, "_sync_output_bit_depth_dropdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(audio_settings_actions, "update_output_status_ui", lambda _app: None)
    refreshes = []
    monkeypatch.setattr(
        audio_settings_actions,
        "_refresh_devices_for_current_driver_ui_only",
        lambda app, reason="x", prefer_device_id=None: refreshes.append((reason, prefer_device_id)),
    )
    player.requested_device_id = "alsa_output.usb-MUSILAND_Monitor_09-00.pro-output-0"

    audio_settings_actions.on_device_changed(app, device_dd, None)

    assert player.set_output_calls == [
        ("PipeWire", "pwcardprofile:alsa_card.usb-MUSILAND_Monitor_09-00|pro-audio")
    ]
    assert app.current_device_name == "Monitor 09"
    assert app.settings["device"] == "Monitor 09"
    assert saved == [True]
    assert notices == []
    assert refreshes == [("pipewire-target-normalized", "alsa_output.usb-MUSILAND_Monitor_09-00.pro-output-0")]


def test_on_device_changed_refreshes_dsp_overview(monkeypatch):
    dsp_updates = []
    player = _Player()
    driver_dd = SimpleNamespace(get_selected_item=lambda: _DriverItem("ALSA"))
    device_dd = _SelectableDropdown(selected=0)
    app = SimpleNamespace(
        ignore_device_change=False,
        current_device_list=[{"name": "DAC One", "device_id": "hw:1,0"}],
        current_device_name="Default Output",
        settings={"device": "Default Output"},
        player=player,
        driver_dd=driver_dd,
        device_dd=device_dd,
        save_settings=lambda: None,
        update_tech_label=lambda _stream: None,
        _update_dsp_ui_state=lambda: dsp_updates.append(True),
        show_output_notice=lambda *_args, **_kwargs: None,
        _last_disconnected_device_name="",
        _last_disconnected_driver="",
    )

    monkeypatch.setattr(audio_settings_actions, "_stop_output_hotplug_watch", lambda _app: None)
    monkeypatch.setattr(audio_settings_actions, "_touch_output_probe_burst", lambda _app, seconds=0: None)
    monkeypatch.setattr(audio_settings_actions, "_sync_output_bit_depth_dropdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(audio_settings_actions, "update_output_status_ui", lambda _app: None)

    audio_settings_actions.on_device_changed(app, device_dd, None)

    assert player.set_output_calls == [("ALSA", "hw:1,0")]
    assert app.current_device_name == "DAC One"
    assert dsp_updates == [True]


def test_monitor_selected_device_presence_accepts_requested_device_id(monkeypatch):
    monkeypatch.setattr(audio_settings_actions, "_get_output_probe_intervals", lambda _app: (0.0, 0.0))
    monkeypatch.setattr(audio_settings_actions, "_driver_key", lambda _name: "pipewire")
    monkeypatch.setattr(audio_settings_actions.GLib, "idle_add", lambda fn: fn())

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr(audio_settings_actions, "Thread", _ImmediateThread)

    notices = []
    refreshes = []
    hotplug = []
    app = SimpleNamespace(
        _device_presence_next_ts=0.0,
        _device_presence_probe_running=False,
        ignore_device_change=False,
        _output_hotplug_source=0,
        driver_dd=SimpleNamespace(get_selected_item=lambda: _DriverItem("PipeWire")),
        device_dd=SimpleNamespace(get_selected_item=lambda: _DriverItem("Monitor 09")),
        player=SimpleNamespace(
            requested_device_id="alsa_output.usb-MUSILAND_Monitor_09-00.pro-output-0",
            get_devices_for_driver=lambda _driver: [
                {
                    "name": "Monitor 09 Pro / Monitor 09",
                    "device_id": "alsa_output.usb-MUSILAND_Monitor_09-00.pro-output-0",
                }
            ],
        ),
        show_output_notice=lambda text, level, timeout: notices.append((text, level, timeout)),
    )
    monkeypatch.setattr(audio_settings_actions, "refresh_devices_keep_driver_select_first", lambda *_args, **_kwargs: refreshes.append(True))
    monkeypatch.setattr(audio_settings_actions, "start_output_hotplug_watch", lambda *_args, **_kwargs: hotplug.append(True))

    audio_settings_actions._monitor_selected_device_presence(app)

    assert notices == []
    assert refreshes == []
    assert hotplug == []
