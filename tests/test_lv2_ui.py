import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app_builders as mod


def test_lv2_save_slots_strips_host_managed_enabled_port():
    calls = []
    app = SimpleNamespace(
        player=SimpleNamespace(
            lv2_slots={
                "lv2_0": {
                    "uri": "http://example.com/plugin",
                    "enabled": True,
                    "port_values": {"enabled": 1.0, "mix": 0.5},
                }
            }
        ),
        settings={},
        schedule_save_settings=lambda: calls.append("save"),
    )

    mod._lv2_save_slots(app)

    assert app.settings["dsp_lv2_slots"] == [
        {
            "slot_id": "lv2_0",
            "uri": "http://example.com/plugin",
            "enabled": True,
            "port_values": {"mix": 0.5},
        }
    ]
    assert calls == ["save"]


def test_lv2_port_change_ignores_host_managed_enabled_symbol():
    calls = []
    app = SimpleNamespace(
        _dsp_ui_syncing=False,
        player=SimpleNamespace(
            lv2_set_port_value=lambda slot_id, symbol, value: calls.append(
                ("set", slot_id, symbol, value)
            )
        ),
        _lv2_save_slots=lambda: calls.append(("save",)),
    )

    mod._on_lv2_port_scale_changed(app, "lv2_0", "enabled", object())

    assert calls == []


def test_lv2_port_change_ignores_host_managed_enable_symbol():
    calls = []
    app = SimpleNamespace(
        _dsp_ui_syncing=False,
        player=SimpleNamespace(
            lv2_set_port_value=lambda slot_id, symbol, value: calls.append(
                ("set", slot_id, symbol, value)
            )
        ),
        _lv2_save_slots=lambda: calls.append(("save",)),
    )

    mod._on_lv2_port_scale_changed(app, "lv2_0", "enable", object())

    assert calls == []


def test_show_dsp_module_selects_lv2_row_from_lv2_list():
    class _Row:
        def __init__(self, module_id):
            self.dsp_module_id = module_id
            self._next = None

        def get_next_sibling(self):
            return self._next

    class _ListBox:
        def __init__(self, rows):
            self.rows = rows
            for idx, row in enumerate(rows[:-1]):
                row._next = rows[idx + 1]
            self.selected = None
            self.unselected = False

        def get_first_child(self):
            return self.rows[0] if self.rows else None

        def select_row(self, row):
            self.selected = row

        def unselect_all(self):
            self.unselected = True

    class _Stack:
        def __init__(self):
            self.visible_child_name = None

        def set_visible_child_name(self, name):
            self.visible_child_name = name

    builtin_row = _Row("peq")
    lv2_row = _Row("lv2_0")
    app = SimpleNamespace(
        dsp_module_stack=_Stack(),
        dsp_module_list=_ListBox([builtin_row]),
        dsp_lv2_module_list=_ListBox([lv2_row]),
    )

    mod._show_dsp_module(app, "lv2_0", select_row=True)

    assert app._dsp_selected_module == "lv2_0"
    assert app.dsp_module_stack.visible_child_name == "lv2_0"
    assert app.dsp_module_list.unselected is True
    assert app.dsp_lv2_module_list.selected is lv2_row


def test_on_dsp_module_selected_clears_other_list_selection():
    calls = []

    class _ListBox:
        def __init__(self, name):
            self.name = name
            self.unselected = False

        def unselect_all(self):
            self.unselected = True

    row = SimpleNamespace(dsp_module_id="lv2_0")
    builtin_list = _ListBox("builtin")
    lv2_list = _ListBox("lv2")
    app = SimpleNamespace(
        dsp_module_list=builtin_list,
        dsp_lv2_module_list=lv2_list,
        _show_dsp_module=lambda module_id, select_row=False: calls.append((module_id, select_row)),
    )

    mod._on_dsp_module_selected(app, lv2_list, row)

    assert builtin_list.unselected is True
    assert lv2_list.unselected is False
    assert calls == [("lv2_0", False)]


def test_open_lv2_plugin_browser_schedules_scan_when_cache_missing():
    calls = []
    notices = []
    app = SimpleNamespace(
        _lv2_plugin_cache=None,
        _lv2_scan_inflight=False,
        _lv2_schedule_scan_cache=lambda refresh_ui=False, on_ready=None, force=False: calls.append(
            ("scan", bool(refresh_ui), callable(on_ready), bool(force))
        ),
        show_output_notice=lambda text, state, timeout: notices.append((text, state, timeout)),
    )

    mod._open_lv2_plugin_browser(app)

    assert calls == [("scan", True, True, False)]
    assert notices == [("Scanning LV2 plugins...", "info", 2200)]


def test_open_lv2_plugin_browser_uses_cache_when_available():
    calls = []
    notices = []
    opened = []
    app = SimpleNamespace(
        _lv2_plugin_cache={"http://example.com/plugin": {"uri": "http://example.com/plugin", "name": "Example"}},
        _lv2_scan_inflight=False,
        _lv2_schedule_scan_cache=lambda refresh_ui=False, on_ready=None, force=False: calls.append(
            ("scan", bool(refresh_ui), callable(on_ready), bool(force))
        ),
        show_output_notice=lambda text, state, timeout: notices.append((text, state, timeout)),
        _present_lv2_plugin_browser=lambda plugins: opened.append(list(plugins)),
    )

    mod._open_lv2_plugin_browser(app)

    assert calls == []
    assert notices == []
    assert opened == [[{"uri": "http://example.com/plugin", "name": "Example"}]]


def test_lv2_update_browser_action_state_disables_add_button_while_scanning():
    class _Btn:
        def __init__(self):
            self.sensitive = None
            self.tooltip = None

        def set_sensitive(self, value):
            self.sensitive = bool(value)

        def set_tooltip_text(self, text):
            self.tooltip = text

    btn = _Btn()
    app = SimpleNamespace(add_lv2_plugin_btn=btn, _lv2_scan_inflight=True)

    mod._lv2_update_browser_action_state(app)

    assert btn.sensitive is False
    assert btn.tooltip == "Scanning installed LV2 plugins..."


def test_open_lv2_plugin_browser_force_refresh_scans_even_when_cache_exists():
    calls = []
    notices = []
    app = SimpleNamespace(
        _lv2_plugin_cache={"http://example.com/plugin": {"uri": "http://example.com/plugin", "name": "Example"}},
        _lv2_scan_inflight=False,
        _lv2_schedule_scan_cache=lambda refresh_ui=False, on_ready=None, force=False: calls.append(
            ("scan", bool(refresh_ui), callable(on_ready), bool(force))
        ),
        show_output_notice=lambda text, state, timeout: notices.append((text, state, timeout)),
    )

    mod._open_lv2_plugin_browser(app, force_refresh=True)

    assert calls == [("scan", True, True, True)]
    assert notices == [("Scanning LV2 plugins...", "info", 2200)]


def test_open_lv2_plugin_browser_during_scan_does_not_queue_duplicate_open():
    calls = []
    notices = []
    app = SimpleNamespace(
        _lv2_plugin_cache=None,
        _lv2_scan_inflight=True,
        _lv2_browser_open_pending=False,
        _lv2_schedule_scan_cache=lambda refresh_ui=False, on_ready=None, force=False: calls.append(
            ("scan", bool(refresh_ui), callable(on_ready), bool(force))
        ),
        show_output_notice=lambda text, state, timeout: notices.append((text, state, timeout)),
    )

    mod._open_lv2_plugin_browser(app)
    mod._open_lv2_plugin_browser(app)

    assert calls == [("scan", True, True, False)]
    assert notices == [
        ("Scanning LV2 plugins...", "info", 2200),
        ("Scanning LV2 plugins...", "info", 2200),
    ]


def test_lv2_schedule_scan_cache_restores_persistent_cache_before_scanning():
    calls = []
    app = SimpleNamespace(
        _lv2_plugin_cache=None,
        _lv2_plugin_cache_file="/tmp/lv2_plugins.json",
        _lv2_scan_ready_callbacks=[],
        _lv2_scan_inflight=False,
        _lv2_scan_refresh_ui_pending=False,
    )

    original_read_json = mod.read_json
    original_sig = mod._lv2_scan_source_signature
    mod.read_json = lambda path, default=None: (
        {"digest": "ok"} if path.endswith(".meta") else [{"uri": "http://example.com/plugin", "name": "Example Plugin"}]
    )
    mod._lv2_scan_source_signature = lambda: {"digest": "ok"}
    try:
        mod._lv2_schedule_scan_cache(app, refresh_ui=False, on_ready=lambda: calls.append(("ready",)), force=False)
    finally:
        mod.read_json = original_read_json
        mod._lv2_scan_source_signature = original_sig

    assert app._lv2_plugin_cache == {
        "http://example.com/plugin": {"uri": "http://example.com/plugin", "name": "Example Plugin"}
    }
    assert calls == [("ready",)]


def test_lv2_schedule_scan_cache_persists_scan_results():
    writes = []
    callbacks = []

    app = SimpleNamespace(
        _lv2_plugin_cache=None,
        _lv2_plugin_cache_file="/tmp/lv2_plugins.json",
        _lv2_scan_ready_callbacks=[],
        _lv2_scan_inflight=False,
        _lv2_scan_refresh_ui_pending=False,
        player=SimpleNamespace(
            lv2_scan_plugins=lambda: [{"uri": "http://example.com/plugin", "name": "Example Plugin"}]
        ),
    )

    original_submit_daemon = mod.submit_daemon
    original_idle_add = mod.GLib.idle_add
    original_read_json = mod.read_json
    original_write_json = mod.write_json
    original_sig = mod._lv2_scan_source_signature
    mod.submit_daemon = lambda fn: fn()
    mod.GLib.idle_add = lambda fn: fn()
    mod.read_json = lambda path, default=None: None
    mod.write_json = lambda path, data, indent=2: writes.append((path, data, indent))
    mod._lv2_scan_source_signature = lambda: {"digest": "fresh", "bundle_count": 1}
    try:
        mod._lv2_schedule_scan_cache(app, refresh_ui=False, on_ready=lambda: callbacks.append(("ready",)), force=False)
    finally:
        mod.submit_daemon = original_submit_daemon
        mod.GLib.idle_add = original_idle_add
        mod.read_json = original_read_json
        mod.write_json = original_write_json
        mod._lv2_scan_source_signature = original_sig

    assert app._lv2_plugin_cache == {
        "http://example.com/plugin": {"uri": "http://example.com/plugin", "name": "Example Plugin"}
    }
    assert writes == [
        (
            "/tmp/lv2_plugins.json",
            [{"uri": "http://example.com/plugin", "name": "Example Plugin"}],
            2,
        ),
        (
            "/tmp/lv2_plugins.json.meta",
            {"digest": "fresh", "bundle_count": 1},
            2,
        ),
    ]
    assert callbacks == [("ready",)]


def test_lv2_load_persistent_scan_cache_invalidates_when_source_signature_changes():
    app = SimpleNamespace(
        _lv2_plugin_cache=None,
        _lv2_plugin_cache_file="/tmp/lv2_plugins.json",
    )

    original_read_json = mod.read_json
    original_sig = mod._lv2_scan_source_signature
    mod.read_json = lambda path, default=None: (
        {"digest": "stale"} if path.endswith(".meta") else [{"uri": "http://example.com/plugin", "name": "Example Plugin"}]
    )
    mod._lv2_scan_source_signature = lambda: {"digest": "fresh"}
    try:
        loaded = mod._lv2_load_persistent_scan_cache(app)
    finally:
        mod.read_json = original_read_json
        mod._lv2_scan_source_signature = original_sig

    assert loaded is False
    assert app._lv2_plugin_cache is None


def test_lv2_refresh_ui_after_scan_rebuilds_overview_chain():
    app = SimpleNamespace(
        player=SimpleNamespace(lv2_slots={"lv2_0": {"uri": "http://example.com/plugin"}}),
        dsp_module_stack=None,
        dsp_lv2_slot_scales={},
        _lv2_rebuild_sidebar_rows=lambda: setattr(app, "_sidebar_rebuilt", True),
        _rebuild_dsp_overview_chain=lambda: setattr(app, "_overview_rebuilt", True),
        _update_dsp_ui_state=lambda: setattr(app, "_ui_updated", True),
        _dsp_selected_module="",
    )

    mod._lv2_refresh_ui_after_scan(app)

    assert app._sidebar_rebuilt is True
    assert app._overview_rebuilt is True
    assert app._ui_updated is True


def test_lv2_host_managed_port_value_uses_bypass_semantics():
    assert mod._lv2_host_managed_port_value("bypass", True) == 0.0
    assert mod._lv2_host_managed_port_value("bypass", False) == 1.0
    assert mod._lv2_host_managed_port_value("enabled", True) == 1.0
    assert mod._lv2_host_managed_port_value("enabled", False) == 0.0


def test_lv2_sync_enabled_port_sets_bypass_false_when_slot_enabled():
    calls = []
    app = SimpleNamespace(
        _lv2_get_plugin_meta=lambda slot_id: {
            "controls": [{"symbol": "bypass", "toggled": True}],
        },
        player=SimpleNamespace(
            lv2_slots={"lv2_0": {"uri": "http://calf.sourceforge.net/plugins/Compressor"}},
            lv2_set_port_value=lambda slot_id, symbol, value: calls.append((slot_id, symbol, value)),
        ),
        dsp_lv2_slot_scales={},
        _dsp_ui_syncing=False,
    )

    mod._lv2_sync_enabled_port(app, "lv2_0", True)

    assert calls == [("lv2_0", "bypass", 0.0)]


def test_lv2_slot_toggle_restarts_playback_after_successful_rebind():
    calls = []
    app = SimpleNamespace(
        _dsp_ui_syncing=False,
        player=SimpleNamespace(
            lv2_set_slot_enabled=lambda slot_id, enabled: calls.append(
                ("toggle", slot_id, enabled)
            ) or True
        ),
        _lv2_sync_enabled_port=lambda slot_id, enabled: calls.append(
            ("sync", slot_id, enabled)
        ),
        _lv2_save_slots=lambda: calls.append(("save",)),
    )

    original_restart = mod._lv2_restart_playback_for_graph_rebind
    mod._lv2_restart_playback_for_graph_rebind = lambda self: calls.append(("restart",))
    try:
        result = mod._on_lv2_slot_toggled(app, "lv2_0", object(), False)
    finally:
        mod._lv2_restart_playback_for_graph_rebind = original_restart

    assert result is False
    assert calls == [
        ("toggle", "lv2_0", False),
        ("sync", "lv2_0", False),
        ("save",),
        ("restart",),
    ]


def test_update_dsp_ui_state_disables_lv2_controls_when_bit_perfect_locked():
    class _Switch:
        def __init__(self, active=True):
            self.active = active
            self.sensitive = True
            self.tooltip = None

        def get_active(self):
            return self.active

        def set_active(self, value):
            self.active = bool(value)

        def set_sensitive(self, value):
            self.sensitive = bool(value)

        def set_tooltip_text(self, text):
            self.tooltip = text

    class _Widget:
        def __init__(self):
            self.sensitive = True

        def set_sensitive(self, value):
            self.sensitive = bool(value)

    slot_switch = _Switch(active=True)
    remove_btn = _Switch(active=False)
    param_widget = _Widget()
    app = SimpleNamespace(
        settings={"bit_perfect": True},
        player=SimpleNamespace(
            dsp_enabled=False,
            peq_enabled=False,
            convolver_enabled=False,
            limiter_enabled=False,
            resampler_enabled=False,
            tube_enabled=False,
            widener_enabled=False,
            tape_enabled=False,
            lv2_slots={"lv2_0": {"uri": "http://example.com/plugin", "enabled": True, "port_values": {}}},
        ),
        _dsp_ui_syncing=False,
        dsp_module_switches={},
        dsp_lv2_slot_rows={"lv2_0": {"switch": slot_switch, "remove_btn": remove_btn}},
        dsp_lv2_slot_scales={"lv2_0": {"mix": param_widget}},
    )

    mod._update_dsp_ui_state(app)

    assert slot_switch.sensitive is False
    assert slot_switch.tooltip == "LV2 bypassed in Bit-Perfect mode"
    assert remove_btn.sensitive is False
    assert param_widget.sensitive is False


def test_lv2_add_slot_reuses_existing_slot_with_same_uri():
    calls = []
    app = SimpleNamespace(
        player=SimpleNamespace(
            lv2_slots={"lv2_0": {"uri": "http://example.com/plugin", "enabled": True, "port_values": {}}},
            lv2_add_slot=lambda uri: calls.append(("add", uri)),
        ),
        settings={"dsp_order": ["peq", "convolver", "tape", "tube", "widener"]},
        _lv2_sync_enabled_port=lambda slot_id, enabled: calls.append(("sync", slot_id, enabled)),
        _apply_dsp_order=lambda order, save=False: calls.append(("order", list(order), save)),
        _lv2_save_slots=lambda: calls.append(("save",)),
    )

    original_restart = mod._lv2_restart_playback_for_graph_rebind
    mod._lv2_restart_playback_for_graph_rebind = lambda self: calls.append(("restart",))
    try:
        slot_id = mod._lv2_add_slot(app, "http://example.com/plugin")
    finally:
        mod._lv2_restart_playback_for_graph_rebind = original_restart

    assert slot_id == "lv2_0"
    assert calls == []


def test_lv2_restart_playback_for_graph_rebind_holds_progress_until_seek_restore():
    calls = []
    app = SimpleNamespace(
        _playback_rebind_inflight=False,
        _playback_rebind_pending=False,
    )
    app.player = SimpleNamespace(
        _last_loaded_uri="https://example.test/track.flac",
        get_position=lambda: (123.4, 240.0),
        is_playing=lambda: True,
        set_volume=lambda value: calls.append(("volume", round(float(value), 2))),
        stop=lambda: calls.append(("stop",)),
        load=lambda uri: calls.append(("load", uri)),
        play=lambda: calls.append(("play",)),
        seek=lambda pos: calls.append(("seek", round(float(pos), 1))),
    )

    idle_calls = []
    timeout_calls = []

    def fake_idle_add(fn):
        idle_calls.append("idle")
        fn()
        return 1

    def fake_timeout_add(delay, fn):
        timeout_calls.append(delay)
        fn()
        return 1

    with patch.object(mod.GLib, "get_monotonic_time", return_value=10_000_000), \
         patch.object(mod.GLib, "idle_add", side_effect=fake_idle_add), \
         patch.object(mod.GLib, "timeout_add", side_effect=fake_timeout_add):
        assert mod._lv2_restart_playback_for_graph_rebind(app) is True

    assert app._playback_rebind_hold_position_s == 123.4
    assert app._playback_rebind_hold_duration_s == 240.0
    assert round(app._playback_rebind_hold_until_s, 3) == 11.5
    assert app._playback_rebind_inflight is False
    assert app._playback_rebind_pending is False
    assert idle_calls == ["idle"]
    assert timeout_calls == [700, 180]
    assert calls == [
        ("volume", 0.0),
        ("stop",),
        ("load", "https://example.test/track.flac"),
        ("play",),
        ("seek", 123.4),
        ("volume", 0.8),
    ]


def test_lv2_restart_playback_for_graph_rebind_coalesces_when_inflight():
    calls = []
    app = SimpleNamespace(
        _playback_rebind_inflight=True,
        _playback_rebind_pending=False,
        player=SimpleNamespace(_last_loaded_uri="https://example.test/track.flac"),
    )

    assert mod._lv2_restart_playback_for_graph_rebind(app) is False
    assert app._playback_rebind_pending is True
    assert calls == []


def test_lv2_install_help_text_mentions_fedora_packages():
    text = mod._lv2_install_help_text()

    assert "already installed on your system" in text
    assert "sudo dnf install" in text
    assert "gstreamer1-plugins-bad-free-lv2" in text
    assert "lv2-x42-plugins" in text
