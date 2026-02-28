"""Remote-control wiring."""

from app.wiring_utils import bind_map


def bind_remote_control(TidalApp, seen=None):
    from app.app_remote_control import (
        _copy_remote_api_key_to_clipboard,
        _effective_remote_api_host,
        _ensure_remote_api_key,
        _init_remote_control_state,
        _refresh_remote_api_settings_ui,
        _remote_append_queue,
        _remote_invoke_on_main,
        _remote_replace_queue,
        _restart_remote_api,
        _set_remote_api_status,
        _start_remote_api,
        _start_remote_api_if_enabled,
        _stop_remote_api,
        get_remote_api_endpoint,
        on_remote_api_access_mode_changed,
        on_remote_api_apply_network_settings,
        on_remote_api_copy_key_clicked,
        on_remote_api_enabled_toggled,
        on_remote_api_generate_key_clicked,
    )

    bind_map(TidalApp, [
        ("_copy_remote_api_key_to_clipboard", _copy_remote_api_key_to_clipboard),
        ("_effective_remote_api_host", _effective_remote_api_host),
        ("_ensure_remote_api_key", _ensure_remote_api_key),
        ("_init_remote_control_state", _init_remote_control_state),
        ("_refresh_remote_api_settings_ui", _refresh_remote_api_settings_ui),
        ("_remote_append_queue", _remote_append_queue),
        ("_remote_invoke_on_main", _remote_invoke_on_main),
        ("_remote_replace_queue", _remote_replace_queue),
        ("_restart_remote_api", _restart_remote_api),
        ("_set_remote_api_status", _set_remote_api_status),
        ("_start_remote_api", _start_remote_api),
        ("_start_remote_api_if_enabled", _start_remote_api_if_enabled),
        ("_stop_remote_api", _stop_remote_api),
        ("get_remote_api_endpoint", get_remote_api_endpoint),
        ("on_remote_api_access_mode_changed", on_remote_api_access_mode_changed),
        ("on_remote_api_apply_network_settings", on_remote_api_apply_network_settings),
        ("on_remote_api_copy_key_clicked", on_remote_api_copy_key_clicked),
        ("on_remote_api_enabled_toggled", on_remote_api_enabled_toggled),
        ("on_remote_api_generate_key_clicked", on_remote_api_generate_key_clicked),
    ], seen=seen)
