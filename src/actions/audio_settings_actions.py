from threading import Thread
import logging
import re
import time

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib

from core.executor import submit_daemon

logger = logging.getLogger(__name__)

_OUTPUT_BIT_DEPTH_GUESS_FORMATS = {
    16: "S16LE",
    24: "S24LE",
    32: "S32LE",
}


def _canonical_output_format_name(fmt):
    up = str(fmt or "").strip().upper()
    mapping = {
        "S16_LE": "S16LE",
        "S16LE": "S16LE",
        "S24_LE": "S24LE",
        "S24LE": "S24LE",
        "S24_3LE": "S24LE",
        "S24_32_LE": "S24_32LE",
        "S24_32LE": "S24_32LE",
        "S32_LE": "S32LE",
        "S32LE": "S32LE",
    }
    return mapping.get(up, up)


def _output_format_bit_depth(fmt):
    up = _canonical_output_format_name(fmt)
    if not up:
        return 0
    if "S24_32" in up:
        return 24
    match = re.search(r"(\d+)", up)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


def _device_supported_output_formats(device_info):
    if not isinstance(device_info, dict):
        return []
    out = []
    seen = set()
    for raw in list(device_info.get("supported_formats") or []):
        fmt = _canonical_output_format_name(raw)
        depth = _output_format_bit_depth(fmt)
        if depth not in (16, 24, 32):
            continue
        if fmt in seen:
            continue
        seen.add(fmt)
        out.append(fmt)
    return out


def _device_supported_bit_depths(device_info):
    seen = set()
    out = []
    for fmt in _device_supported_output_formats(device_info):
        depth = _output_format_bit_depth(fmt)
        if depth in (16, 24, 32) and depth not in seen:
            seen.add(depth)
            out.append(depth)
    if out:
        return out
    if isinstance(device_info, dict):
        for raw in list(device_info.get("supported_bit_depths") or []):
            try:
                depth = int(raw or 0)
            except Exception:
                depth = 0
            if depth in (16, 24, 32) and depth not in seen:
                seen.add(depth)
                out.append(depth)
    out.sort()
    return out


def _bit_depth_labels_for_device(device_info):
    return ["Auto"] + [f"{depth}-bit" for depth in _device_supported_bit_depths(device_info)]


def _parse_output_bit_depth_label(label):
    text = str(label or "").strip()
    if not text or text.lower() == "auto":
        return 0
    match = re.search(r"(\d+)", text)
    if not match:
        return 0
    try:
        depth = int(match.group(1))
    except Exception:
        return 0
    return depth if depth in (16, 24, 32) else 0


def _current_selected_device_info(app):
    dd = getattr(app, "device_dd", None)
    devices = list(getattr(app, "current_device_list", []) or [])
    if dd is None or not devices:
        return None
    try:
        idx = int(dd.get_selected())
    except Exception:
        idx = 0
    if 0 <= idx < len(devices):
        return devices[idx]
    return None


def _preferred_output_format_for_device(device_info, label):
    depth = _parse_output_bit_depth_label(label)
    if depth <= 0:
        return None
    for fmt in _device_supported_output_formats(device_info):
        if _output_format_bit_depth(fmt) == depth:
            return fmt
    if depth in _device_supported_bit_depths(device_info):
        return _OUTPUT_BIT_DEPTH_GUESS_FORMATS.get(depth)
    return None


def _selected_driver_name(app):
    dd = getattr(app, "driver_dd", None)
    item = dd.get_selected_item() if dd is not None else None
    return item.get_string() if item is not None else ""


def _driver_supports_explicit_output_bit_depth(app):
    return str(_selected_driver_name(app) or "").strip().upper() == "ALSA"


def _apply_output_bit_depth_preference(app, device_info=None):
    player = getattr(app, "player", None)
    if player is None:
        return None
    fmt = None
    if _driver_supports_explicit_output_bit_depth(app):
        label = str(getattr(app, "settings", {}).get("output_bit_depth", "Auto") or "Auto")
        fmt = _preferred_output_format_for_device(device_info, label)
    if hasattr(player, "set_output_format_preference"):
        player.set_output_format_preference(fmt)
    else:
        setattr(player, "preferred_output_format", str(fmt or ""))
    return fmt


def _sync_output_bit_depth_dropdown(app, device_info=None):
    dd = getattr(app, "bit_depth_dd", None)
    if dd is None:
        _apply_output_bit_depth_preference(app, device_info)
        return
    if _driver_supports_explicit_output_bit_depth(app):
        labels = _bit_depth_labels_for_device(device_info)
        saved = str(getattr(app, "settings", {}).get("output_bit_depth", "Auto") or "Auto")
        selected_label = saved if saved in labels else "Auto"
        if selected_label != saved:
            app.settings["output_bit_depth"] = selected_label
            if hasattr(app, "save_settings"):
                app.save_settings()
        sensitive = len(labels) > 1
        selected_idx = labels.index(selected_label)
    else:
        labels = ["Auto"]
        sensitive = False
        selected_idx = 0
    app.ignore_output_bit_depth_change = True
    dd.set_model(Gtk.StringList.new(labels))
    dd.set_sensitive(sensitive)
    dd.set_selected(selected_idx)
    app.ignore_output_bit_depth_change = False
    _apply_output_bit_depth_preference(app, device_info)


def _device_enum_signature(devices):
    sig = []
    for info in list(devices or []):
        if not isinstance(info, dict):
            continue
        sig.append(
            (
                str(info.get("name") or ""),
                str(info.get("device_id") or ""),
                tuple(str(v or "") for v in list(info.get("supported_formats") or [])),
                tuple(int(v or 0) for v in list(info.get("supported_bit_depths") or [])),
            )
        )
    return tuple(sig)


def _stop_output_hotplug_watch(app):
    source_id = getattr(app, "_output_hotplug_source", 0)
    if source_id:
        try:
            GLib.source_remove(source_id)
        except Exception:
            pass
    app._output_hotplug_source = 0


def _touch_output_probe_burst(app, seconds=20):
    try:
        app._output_probe_burst_until = time.monotonic() + max(1.0, float(seconds))
    except Exception:
        app._output_probe_burst_until = time.monotonic() + 20.0


def _get_output_probe_intervals(app):
    # Event-priority strategy:
    # - playing / recent output event => fast probe
    # - idle => low-frequency fallback probe
    try:
        is_playing = bool(getattr(app, "player", None) is not None and app.player.is_playing())
    except Exception:
        is_playing = False
    now = time.monotonic()
    burst_until = float(getattr(app, "_output_probe_burst_until", 0.0) or 0.0)
    in_burst = now < burst_until
    mode = "fast" if (is_playing or in_burst) else "idle"
    prev_mode = getattr(app, "_output_probe_mode", None)
    if prev_mode != mode:
        app._output_probe_mode = mode
        logger.info("Output probe mode: %s", mode)
    if is_playing or in_burst:
        return 2.0, 4.0
    return 12.0, 20.0


def _refresh_devices_for_current_driver_ui_only(app, reason="hotplug-watch"):
    """Refresh current driver's device dropdown only, without applying output switch."""
    selected_driver = app.driver_dd.get_selected_item()
    if not selected_driver:
        return
    driver_name = selected_driver.get_string()
    selected_item = app.device_dd.get_selected_item()
    prefer_name = selected_item.get_string() if selected_item else getattr(app, "current_device_name", None)

    def worker():
        devices = app.player.get_devices_for_driver(driver_name)

        def apply_devices():
            old_sig = _device_enum_signature(getattr(app, "current_device_list", []))
            new_sig = _device_enum_signature(devices)
            new_names = [d.get("name") for d in devices]
            if new_sig == old_sig:
                return False
            old_names = [d.get("name") for d in getattr(app, "current_device_list", [])]
            old_set = set([n for n in old_names if n])
            new_set = set([n for n in new_names if n])
            added = [n for n in new_names if n in (new_set - old_set)]

            app.ignore_device_change = True
            app.current_device_list = devices
            app.device_dd.set_model(Gtk.StringList.new(new_names))
            app.device_dd.set_sensitive(len(devices) > 1)

            sel_idx = 0
            if prefer_name:
                for i, d in enumerate(devices):
                    if d.get("name") == prefer_name:
                        sel_idx = i
                        break
            if devices and sel_idx < len(devices):
                app.device_dd.set_selected(sel_idx)
                app.current_device_name = devices[sel_idx].get("name") or app.current_device_name
            device_info = devices[sel_idx] if devices and sel_idx < len(devices) else None
            _sync_output_bit_depth_dropdown(app, device_info)
            app.ignore_device_change = False
            app.update_tech_label(app.player.stream_info)
            logger.info("Output device list refreshed (%s): %d devices", reason, len(devices))
            if reason == "hotplug-watch" and added and hasattr(app, "show_output_notice"):
                remembered_name = str(getattr(app, "_last_disconnected_device_name", "") or "")
                remembered_driver = str(getattr(app, "_last_disconnected_driver", "") or "")
                if remembered_name and remembered_driver == driver_name and remembered_name in added:
                    auto_rebind = bool(getattr(app, "settings", {}).get("output_auto_rebind_once", False))
                    if auto_rebind:
                        now_mono = time.monotonic()
                        cooldown_until = float(getattr(app, "_auto_rebind_cooldown_until", 0.0) or 0.0)
                        if now_mono < cooldown_until:
                            remain = int(max(1, round(cooldown_until - now_mono)))
                            app.show_output_notice(
                                f"Your previous device is back: {remembered_name}. Auto rebind cooling down ({remain}s), switch manually if needed.",
                                "warn",
                                3800,
                            )
                            app._last_disconnected_device_name = ""
                            app._last_disconnected_driver = ""
                            _stop_output_hotplug_watch(app)
                            logger.info("Output hotplug watch stopped: auto-rebind cooldown active")
                            return False
                        target_idx = None
                        target_device = None
                        for i, d in enumerate(devices):
                            if d.get("name") == remembered_name:
                                target_idx = i
                                target_device = d
                                break
                        if target_idx is not None and target_device is not None:
                            app.ignore_device_change = True
                            app.device_dd.set_selected(target_idx)
                            app.current_device_name = target_device.get("name") or app.current_device_name
                            app.settings["device"] = app.current_device_name
                            app.save_settings()
                            app.ignore_device_change = False
                            app.update_tech_label(app.player.stream_info)

                            def _apply_auto_rebind():
                                app.player.set_output(driver_name, target_device.get("device_id"))
                                if hasattr(app, "_apply_viz_sync_offset_for_device"):
                                    app._apply_viz_sync_offset_for_device(
                                        driver_name,
                                        device_id=target_device.get("device_id"),
                                        device_name=target_device.get("name"),
                                    )
                                GLib.idle_add(lambda: update_output_status_ui(app) or False)

                            Thread(target=_apply_auto_rebind, daemon=True).start()
                            app.show_output_notice(
                                f"Your previous device is back: {remembered_name}. Switched back automatically.",
                                "ok",
                                4200,
                            )
                            app._auto_rebind_cooldown_until = now_mono + 15.0
                        else:
                            app.show_output_notice(
                                f"Your previous device is back: {remembered_name}. You can switch back in Output settings.",
                                "ok",
                                4200,
                            )
                    else:
                        app.show_output_notice(
                            f"Your previous device is back: {remembered_name}. You can switch back in Output settings.",
                            "ok",
                            4200,
                        )
                    app._last_disconnected_device_name = ""
                    app._last_disconnected_driver = ""
                    _stop_output_hotplug_watch(app)
                    logger.info("Output hotplug watch stopped: previous device rediscovered")
                    return False
                name = added[0]
                if len(added) > 1:
                    app.show_output_notice(
                        f"New audio devices detected ({len(added)}). Example: {name}",
                        "ok",
                        3600,
                    )
                else:
                    app.show_output_notice(
                        f"New audio device detected: {name}",
                        "ok",
                        3200,
                    )
                # Stop hotplug polling once new devices are discovered.
                _stop_output_hotplug_watch(app)
                logger.info("Output hotplug watch stopped: new device discovered")
            return False

        GLib.idle_add(apply_devices)

    Thread(target=worker, daemon=True).start()


def start_output_hotplug_watch(app, seconds=60, interval_ms=1000, slow_interval_ms=5000):
    """Start two-stage device auto-refresh after disconnect.

    Stage-1 (fast): interval_ms for `seconds`.
    Stage-2 (slow): slow_interval_ms until stopped by rediscovery or caller.
    """
    _stop_output_hotplug_watch(app)
    _touch_output_probe_burst(app, seconds=max(20, seconds))
    now_us = GLib.get_monotonic_time()
    app._output_hotplug_deadline = now_us + int(seconds * 1_000_000)
    app._output_hotplug_fast_interval_us = int(max(200, interval_ms) * 1000)
    app._output_hotplug_slow_interval_us = int(max(1000, slow_interval_ms) * 1000)
    app._output_hotplug_next_probe_us = 0
    logger.info(
        "Output hotplug watch started: fast_seconds=%s fast_interval_ms=%s slow_interval_ms=%s",
        seconds,
        interval_ms,
        slow_interval_ms,
    )

    def _tick():
        now = GLib.get_monotonic_time()
        deadline = int(getattr(app, "_output_hotplug_deadline", 0) or 0)
        fast_us = int(getattr(app, "_output_hotplug_fast_interval_us", 1_000_000) or 1_000_000)
        slow_us = int(getattr(app, "_output_hotplug_slow_interval_us", 5_000_000) or 5_000_000)
        next_probe = int(getattr(app, "_output_hotplug_next_probe_us", 0) or 0)
        current_us = fast_us if (deadline and now < deadline) else slow_us
        if next_probe and now < next_probe:
            return True
        app._output_hotplug_next_probe_us = now + current_us
        _refresh_devices_for_current_driver_ui_only(app, reason="hotplug-watch")
        return True

    # Keep 1s timer and internally gate probes for slow phase.
    app._output_hotplug_source = GLib.timeout_add(1000, _tick)


def refresh_devices_keep_driver_select_first(app, reason="device-refresh"):
    """Refresh device list for current driver, keep driver unchanged, select first available device."""
    selected_driver = app.driver_dd.get_selected_item()
    if not selected_driver:
        return
    driver_name = selected_driver.get_string()

    def worker():
        devices = app.player.get_devices_for_driver(driver_name)

        def apply_devices():
            app.ignore_device_change = True
            app.current_device_list = devices
            app.device_dd.set_model(Gtk.StringList.new([d["name"] for d in devices]))
            app.device_dd.set_sensitive(len(devices) > 1)

            if not devices:
                app.current_device_name = "Unavailable"
                _sync_output_bit_depth_dropdown(app, None)
                app.ignore_device_change = False
                try:
                    app.player.output_state = "error"
                    app.player.output_error = f"No available output devices for {driver_name}"
                except Exception:
                    pass
                if hasattr(app, "show_output_notice"):
                    app.show_output_notice(
                        f"No available output devices for {driver_name}. Waiting for reconnect...",
                        "error",
                        3600,
                    )
                update_output_status_ui(app)
                return False

            sel_idx = 0
            app.device_dd.set_selected(sel_idx)
            target = devices[sel_idx]
            app.current_device_name = target["name"]
            app.settings["device"] = target["name"]
            app.save_settings()
            _sync_output_bit_depth_dropdown(app, target)
            app.ignore_device_change = False
            app.update_tech_label(app.player.stream_info)

            def apply_output_async():
                logger.warning(
                    "Output auto-rebind (%s): driver=%s device=%s",
                    reason,
                    driver_name,
                    target.get("device_id"),
                )
                ok = app.player.set_output(driver_name, target.get("device_id"))
                if not ok:
                    if hasattr(app, "show_output_notice"):
                        app.show_output_notice(
                            f"Failed to switch output to {target.get('name')}",
                            "error",
                            3500,
                        )
                if hasattr(app, "_apply_viz_sync_offset_for_device"):
                    app._apply_viz_sync_offset_for_device(
                        driver_name,
                        device_id=target.get("device_id"),
                        device_name=target.get("name"),
                    )
                GLib.idle_add(lambda: update_output_status_ui(app) or False)

            Thread(target=apply_output_async, daemon=True).start()
            return False

        GLib.idle_add(apply_devices)

    Thread(target=worker, daemon=True).start()


def _monitor_selected_device_presence(app):
    """Detect unplugged selected device even when idle (no active playback errors)."""
    try:
        now = time.monotonic()
        next_ts = float(getattr(app, "_device_presence_next_ts", 0.0) or 0.0)
        if now < next_ts:
            return
        presence_interval_s, _ = _get_output_probe_intervals(app)
        app._device_presence_next_ts = now + presence_interval_s
        if getattr(app, "_device_presence_probe_running", False):
            return
        if getattr(app, "ignore_device_change", False):
            return
        if getattr(app, "_output_hotplug_source", 0):
            return

        drv_item = app.driver_dd.get_selected_item() if hasattr(app, "driver_dd") else None
        dev_item = app.device_dd.get_selected_item() if hasattr(app, "device_dd") else None
        if not drv_item or not dev_item:
            return
        driver_name = drv_item.get_string()
        device_name = dev_item.get_string()
        if not driver_name or not device_name:
            return
        if driver_name not in ("ALSA", "PipeWire"):
            return
        if device_name in ("Default Output", "Default System Output", "Unavailable", "Default"):
            return

        app._device_presence_probe_running = True

        def worker():
            try:
                devices = app.player.get_devices_for_driver(driver_name)
                names = [d.get("name") for d in devices]

                def apply_result():
                    app._device_presence_probe_running = False
                    if device_name in names:
                        return False
                    if hasattr(app, "show_output_notice"):
                        app.show_output_notice(
                            f"Audio device disconnected: {device_name}",
                            "warn",
                            3600,
                        )
                    app._last_disconnected_device_name = device_name
                    app._last_disconnected_driver = driver_name
                    logger.warning(
                        "Selected device disappeared (idle monitor): driver=%s device=%s",
                        driver_name,
                        device_name,
                    )
                    refresh_devices_keep_driver_select_first(app, reason="device-missing-idle")
                    start_output_hotplug_watch(app, seconds=60, interval_ms=1000, slow_interval_ms=5000)
                    return False

                GLib.idle_add(apply_result)
            except Exception:
                app._device_presence_probe_running = False

        Thread(target=worker, daemon=True).start()
    except Exception:
        pass


def _passive_sync_device_list(app):
    """Keep device dropdown in sync with actual hardware even if selected device is unaffected."""
    try:
        now = time.monotonic()
        next_ts = float(getattr(app, "_device_list_sync_next_ts", 0.0) or 0.0)
        if now < next_ts:
            return
        _, sync_interval_s = _get_output_probe_intervals(app)
        app._device_list_sync_next_ts = now + sync_interval_s
        if getattr(app, "_device_list_sync_running", False):
            return
        if getattr(app, "ignore_device_change", False):
            return
        if getattr(app, "_output_hotplug_source", 0):
            return

        drv_item = app.driver_dd.get_selected_item() if hasattr(app, "driver_dd") else None
        if not drv_item:
            return
        driver_name = drv_item.get_string()
        if driver_name not in ("ALSA", "PipeWire"):
            return

        selected_item = app.device_dd.get_selected_item() if hasattr(app, "device_dd") else None
        prefer_name = selected_item.get_string() if selected_item else getattr(app, "current_device_name", None)
        old_sig = _device_enum_signature(getattr(app, "current_device_list", []))

        app._device_list_sync_running = True

        def worker():
            try:
                devices = app.player.get_devices_for_driver(driver_name)
                new_sig = _device_enum_signature(devices)

                def apply_result():
                    app._device_list_sync_running = False
                    if new_sig == old_sig:
                        return False

                    app.ignore_device_change = True
                    app.current_device_list = devices
                    app.device_dd.set_model(Gtk.StringList.new(new_names))
                    app.device_dd.set_sensitive(len(devices) > 1)

                    sel_idx = 0
                    if prefer_name:
                        for i, d in enumerate(devices):
                            if d.get("name") == prefer_name:
                                sel_idx = i
                                break
                    if devices and sel_idx < len(devices):
                        app.device_dd.set_selected(sel_idx)
                        app.current_device_name = devices[sel_idx].get("name") or app.current_device_name
                    device_info = devices[sel_idx] if devices and sel_idx < len(devices) else None
                    _sync_output_bit_depth_dropdown(app, device_info)
                    app.ignore_device_change = False
                    app.update_tech_label(app.player.stream_info)
                    logger.info("Output device list synced (passive): driver=%s count=%d", driver_name, len(devices))
                    return False

                GLib.idle_add(apply_result)
            except Exception:
                app._device_list_sync_running = False

        Thread(target=worker, daemon=True).start()
    except Exception:
        pass


def update_output_status_ui(app):
    if not hasattr(app, "output_status_label") or app.output_status_label is None:
        return

    state = getattr(app.player, "output_state", "idle")
    err = getattr(app.player, "output_error", None)
    text = state.capitalize()
    if err and state in ("fallback", "error"):
        text = f"{text}: {err}"
    app.output_status_label.set_text(text)

    class_map = {
        "active": "status-active",
        "fallback": "status-fallback",
        "error": "status-error",
        "switching": "status-switching",
        "idle": "status-idle",
    }
    for cls in ("status-active", "status-fallback", "status-error", "status-switching", "status-idle"):
        app.output_status_label.remove_css_class(cls)
    app.output_status_label.add_css_class(class_map.get(state, "status-idle"))

    prev_state = getattr(app, "_last_output_state", None)
    prev_err = getattr(app, "_last_output_error", None)
    changed = (state != prev_state) or (state in ("fallback", "error") and err != prev_err)
    if changed and hasattr(app, "on_output_state_transition"):
        app.on_output_state_transition(prev_state, state, err)
    app._last_output_state = state
    app._last_output_error = err

    can_recover = state in ("fallback", "error") and bool(getattr(app.player, "requested_driver", None))
    if hasattr(app, "output_recover_btn") and app.output_recover_btn is not None:
        app.output_recover_btn.set_sensitive(can_recover)
    if hasattr(app, "set_diag_health"):
        if state == "active":
            app.set_diag_health("output", "ok")
        elif state in ("fallback", "switching"):
            app.set_diag_health("output", "warn", err)
        elif state == "error":
            app.set_diag_health("output", "error", err)
        else:
            app.set_diag_health("output", "idle")
    _monitor_selected_device_presence(app)
    _passive_sync_device_list(app)


def on_recover_output_clicked(app, _btn=None):
    driver = getattr(app.player, "requested_driver", None)
    device_id = getattr(app.player, "requested_device_id", None)
    if not driver:
        return
    _touch_output_probe_burst(app, seconds=30)
    logger.info("Recovering output to requested target: driver=%s device=%s", driver, device_id)
    if hasattr(app, "record_diag_event"):
        app.record_diag_event(f"Recover output requested: {driver} / {device_id or 'default'}")
    app.player.set_output(driver, device_id)
    if hasattr(app, "_apply_viz_sync_offset_for_device"):
        app._apply_viz_sync_offset_for_device(driver, device_id=device_id, device_name=getattr(app, "current_device_name", None))
    update_output_status_ui(app)


def on_latency_changed(app, dd, p):
    selected = dd.get_selected_item()
    if not selected:
        return
    profile_name = selected.get_string()

    app.settings["latency_profile"] = profile_name
    app.save_settings()

    if profile_name in app.LATENCY_MAP:
        buf_ms, lat_ms = app.LATENCY_MAP[profile_name]
        app.player.set_alsa_latency(buf_ms, lat_ms)
        logger.info(
            "Audio latency profile applied: buffer=%dms latency=%dms (latency-change, viz offset unchanged, profile=%s)",
            int(buf_ms),
            int(lat_ms),
            profile_name,
        )

        if app.ex_switch.get_active():
            logger.info("Latency changed, restarting output")
            app.on_driver_changed(app.driver_dd, None)


def on_driver_changed(app, dd, p):
    _stop_output_hotplug_watch(app)
    _touch_output_probe_burst(app, seconds=30)
    selected = dd.get_selected_item()
    if not selected:
        return
    driver_name = selected.get_string()

    if not app.ex_switch.get_active() or driver_name == "ALSA":
        app.settings["driver"] = driver_name
        app.save_settings()

    app.current_device_name = "Default"
    app.update_tech_label(app.player.stream_info)

    def worker():
        devices = app.player.get_devices_for_driver(driver_name)

        def apply_devices():
            app.ignore_device_change = True

            app.current_device_list = devices
            app.device_dd.set_model(Gtk.StringList.new([d["name"] for d in devices]))

            saved_dev = app.settings.get("device")
            sel_idx = 0

            if saved_dev:
                for i, d in enumerate(devices):
                    if d["name"] == saved_dev:
                        sel_idx = i
                        break

            app.device_dd.set_sensitive(len(devices) > 1)

            if sel_idx < len(devices):
                app.device_dd.set_selected(sel_idx)

            device_info = devices[sel_idx] if sel_idx < len(devices) else None
            _sync_output_bit_depth_dropdown(app, device_info)
            app.ignore_device_change = False

            target_id = None
            if sel_idx < len(devices):
                target_id = devices[sel_idx]["device_id"]
                app.current_device_name = devices[sel_idx]["name"]

            app.update_tech_label(app.player.stream_info)

            def apply_output_async():
                ok = app.player.set_output(driver_name, target_id)
                if not ok and hasattr(app, "show_output_notice"):
                    app.show_output_notice(
                        f"Failed to switch output to {app.current_device_name or 'selected device'}",
                        "error",
                        3500,
                    )
                if hasattr(app, "_apply_viz_sync_offset_for_device"):
                    app._apply_viz_sync_offset_for_device(
                        driver_name,
                        device_id=target_id,
                        device_name=app.current_device_name,
                    )
                GLib.idle_add(lambda: update_output_status_ui(app) or False)

            Thread(target=apply_output_async, daemon=True).start()
            return False

        GLib.idle_add(apply_devices)

    Thread(target=worker, daemon=True).start()


def on_device_changed(app, dd, p):
    if app.ignore_device_change:
        return
    _stop_output_hotplug_watch(app)
    _touch_output_probe_burst(app, seconds=30)
    idx = dd.get_selected()
    if hasattr(app, "current_device_list") and idx < len(app.current_device_list):
        device_info = app.current_device_list[idx]
        previous_name = str(getattr(app, "current_device_name", "") or "")
        previous_saved = str(app.settings.get("device", "") or "")
        previous_idx = None
        for i, info in enumerate(list(getattr(app, "current_device_list", []) or [])):
            if str(info.get("name", "") or "") == previous_name:
                previous_idx = i
                break
        remembered_name = str(getattr(app, "_last_disconnected_device_name", "") or "")
        target_name = device_info["name"]
        driver_label = app.driver_dd.get_selected_item().get_string()
        _sync_output_bit_depth_dropdown(app, device_info)
        ok = app.player.set_output(driver_label, device_info["device_id"])
        if not ok:
            if previous_idx is not None and previous_idx != idx:
                app.ignore_device_change = True
                try:
                    dd.set_selected(previous_idx)
                finally:
                    app.ignore_device_change = False
            if previous_saved:
                app.settings["device"] = previous_saved
            app.current_device_name = previous_name or getattr(app, "current_device_name", "Default")
            app.update_tech_label(app.player.stream_info)
            if hasattr(app, "show_output_notice"):
                app.show_output_notice(
                    f"Output device unavailable: {target_name}",
                    "error",
                    4200,
                )
            update_output_status_ui(app)
            return
        if remembered_name and target_name == remembered_name:
            app._last_disconnected_device_name = ""
            app._last_disconnected_driver = ""
        app.current_device_name = target_name
        app.update_tech_label(app.player.stream_info)
        app.settings["device"] = target_name
        app.save_settings()
        if hasattr(app, "_apply_viz_sync_offset_for_device"):
            app._apply_viz_sync_offset_for_device(driver_label, device_id=device_info["device_id"], device_name=target_name)
        update_output_status_ui(app)


def on_output_bit_depth_changed(app, dd, p):
    if getattr(app, "ignore_output_bit_depth_change", False):
        return
    selected = dd.get_selected_item()
    label = selected.get_string() if selected is not None else "Auto"
    app.settings["output_bit_depth"] = str(label or "Auto")
    app.save_settings()
    device_info = _current_selected_device_info(app)
    _apply_output_bit_depth_preference(app, device_info)
    app.update_tech_label(app.player.stream_info)

    drv_item = app.driver_dd.get_selected_item() if getattr(app, "driver_dd", None) is not None else None
    if drv_item is None:
        update_output_status_ui(app)
        return
    driver_label = drv_item.get_string()
    device_id = device_info.get("device_id") if isinstance(device_info, dict) else None
    ok = app.player.set_output(driver_label, device_id)
    if not ok and hasattr(app, "show_output_notice"):
        app.show_output_notice(
            f"Failed to apply {label or 'Auto'} output depth",
            "error",
            3600,
        )
    elif ok and hasattr(app, "_apply_viz_sync_offset_for_device"):
        app._apply_viz_sync_offset_for_device(
            driver_label,
            device_id=device_id,
            device_name=(device_info or {}).get("name"),
        )
    update_output_status_ui(app)


def on_output_state_transition(self, prev_state, state, detail=None):
    if state == "switching":
        try:
            _touch_output_probe_burst(self, seconds=30)
        except Exception:
            pass
        self.show_output_notice("Audio device changed, reconnecting...", "switching", 2400)
        return
    if state == "active" and prev_state in ("switching", "fallback", "error"):
        self.show_output_notice("Audio output reconnected", "ok", 2200)
        return
    if state == "fallback":
        try:
            _touch_output_probe_burst(self, seconds=60)
        except Exception:
            pass
        if self.play_btn is not None:
            self.play_btn.set_icon_name("media-playback-start-symbolic")
        detail_text = str(detail or "")
        if "disconnected" in detail_text.lower():
            # Remember the device that was active when disconnect happened, so
            # hotplug logic can detect "same device came back" and optionally
            # auto-rebind once.
            try:
                drv_item = self.driver_dd.get_selected_item() if self.driver_dd is not None else None
                dev_item = self.device_dd.get_selected_item() if self.device_dd is not None else None
                if drv_item is not None:
                    self._last_disconnected_driver = drv_item.get_string()
                if dev_item is not None:
                    self._last_disconnected_device_name = dev_item.get_string()
            except Exception:
                pass
            self.show_output_notice("USB audio device disconnected, rebinding to first available output", "warn", 3600)
            # Keep selected driver unchanged; refresh devices and bind to first available.
            try:
                refresh_devices_keep_driver_select_first(self, reason="usb-disconnect")
                start_output_hotplug_watch(
                    self,
                    seconds=60,
                    interval_ms=1000,
                    slow_interval_ms=5000,
                )
            except Exception:
                pass
        else:
            self.show_output_notice("Primary output unavailable, switched to fallback", "warn", 3200)
        return
    if state == "error":
        try:
            _touch_output_probe_burst(self, seconds=45)
        except Exception:
            pass
        if self.play_btn is not None:
            self.play_btn.set_icon_name("media-playback-start-symbolic")
        msg = str(detail or "Unknown output error")
        self.show_output_notice(f"Output error: {msg}", "error", 3600)


def _get_output_status_interval_ms(self):
    try:
        is_settings = bool(
            getattr(self, "right_stack", None) is not None
            and self.right_stack.get_visible_child_name() == "settings"
        )
    except Exception:
        is_settings = False
    if is_settings:
        return 1000
    state = str(getattr(self.player, "output_state", "idle") or "idle")
    if state in ("fallback", "error", "switching"):
        return 1200
    try:
        is_playing = bool(self.player.is_playing())
    except Exception:
        is_playing = False
    return 2500 if is_playing else 6000


def _schedule_output_status_loop(self, delay_ms=None):
    source = getattr(self, "_output_status_source", 0)
    if source:
        try:
            GLib.source_remove(source)
        except Exception:
            pass
        self._output_status_source = 0
    next_delay = int(delay_ms if delay_ms is not None else self._get_output_status_interval_ms())

    def _tick():
        self._output_status_source = 0
        try:
            self._refresh_output_status_loop()
        except Exception:
            logger.exception("Output status loop tick failed")
        self._schedule_output_status_loop()
        return False

    self._output_status_source = GLib.timeout_add(max(250, next_delay), _tick)


def _force_driver_selection(self, keyword):
    model = self.driver_dd.get_model()
    for i in range(model.get_n_items()):
        if keyword in model.get_item(i).get_string(): self.driver_dd.set_selected(i); break


def update_tech_label(self, info):
    fmt = str(info.get('fmt_str', '') or '')
    fmt_norm = " ".join(fmt.replace("\\", " ").split())
    codec = info.get('codec', '-')
    if (not fmt_norm) and (not codec or codec in ["-", "Loading..."]):
        self.lbl_tech.set_text("")
        self.lbl_tech.set_tooltip_text(None)
        self.lbl_tech.remove_css_class("tech-label")
        for cls in ("tech-state-ok", "tech-state-mixed", "tech-state-warn"):
            self.lbl_tech.remove_css_class(cls)
        self.lbl_tech.set_visible(True)
        # Track changed — reset bitrate stability tracking state.
        self._bitrate_pending = 0
        self._bitrate_shown = 0
        return

    display_codec = codec if codec and codec not in ["-", "Loading..."] else "PCM"
    if isinstance(display_codec, str):
        codec_low = display_codec.lower()
        if "flac" in codec_low:
            display_codec = "FLAC"
        elif "aac" in codec_low:
            display_codec = "AAC"
        elif "alac" in codec_low:
            display_codec = "ALAC"
        else:
            display_codec = display_codec.replace("\\", " ").strip()

    # Prefer explicit numeric fields; fmt_str can be missing or escaped.
    def _pick_int(*keys):
        for k in keys:
            try:
                v = int(info.get(k, 0) or 0)
            except Exception:
                v = 0
            if v > 0:
                return v
        return 0

    src_rate = _pick_int("source_rate", "rate", "output_rate")
    src_depth = _pick_int("source_depth", "depth", "output_depth")

    if src_rate > 0 and src_depth > 0:
        rate_depth = f"{src_depth}-bit/{(src_rate / 1000.0):g}kHz"
    else:
        rate_depth = fmt_norm
        if "|" in fmt_norm:
            parts = [p.strip() for p in fmt_norm.split("|")]
            if len(parts) >= 2:
                rate = parts[0]
                depth = parts[1].replace("bit", "-bit")
                rate_depth = f"{depth}/{rate}"
        if not rate_depth:
            rate_depth = "-"

    bitrate = int(info.get("bitrate", 0) or 0)
    if bitrate > 0:
        # GStreamer's bitrate estimate for lossless streams (FLAC) starts very
        # low and converges upward over several TAG events.  Only display the
        # value once two consecutive TAG events agree within ±40%, which means
        # the estimate has stabilised.  Until then keep the last stable value
        # (or show nothing if this is the very first track).
        pending = int(getattr(self, "_bitrate_pending", 0) or 0)
        shown   = int(getattr(self, "_bitrate_shown",   0) or 0)
        self._bitrate_pending = bitrate
        if pending > 0 and 0.6 <= bitrate / pending <= 1.67:
            # Two consecutive similar readings → stable; update display.
            self._bitrate_shown = bitrate
            shown = bitrate
        # If not yet stable: keep the previously confirmed value (or nothing).
        if shown > 0:
            kbps = max(1, int(round(shown / 1000.0)))
            bitrate_text = f" • {kbps}kbps"
        else:
            bitrate_text = ""
    else:
        self._bitrate_pending = 0
        self._bitrate_shown = 0
        bitrate_text = ""

    is_bp = bool(getattr(self.player, "bit_perfect_mode", False))
    is_ex = bool(getattr(self.player, "exclusive_lock_mode", False))
    output_state = str(getattr(self.player, "output_state", "idle"))

    mode_tag = "BP" if is_bp else "MIX"
    lock_tag = "EX" if is_ex else "SHR"
    self.lbl_tech.add_css_class("tech-label")
    self.lbl_tech.set_text(f"{mode_tag}/{lock_tag} • {rate_depth} • {display_codec}{bitrate_text}")

    # Full detail remains available on hover.
    dev_name = getattr(self, "current_device_name", "Default")
    self.lbl_tech.set_tooltip_text(
        f"{display_codec} | {rate_depth} | {bitrate//1000}kbps | {dev_name} | output={output_state}"
    )

    for cls in ("tech-state-ok", "tech-state-mixed", "tech-state-warn"):
        self.lbl_tech.remove_css_class(cls)
    if output_state in ("fallback", "error"):
        self.lbl_tech.add_css_class("tech-state-warn")
    elif is_bp:
        self.lbl_tech.add_css_class("tech-state-ok")
    else:
        self.lbl_tech.add_css_class("tech-state-mixed")

    self.lbl_tech.set_visible(True)


def on_bit_perfect_toggled(self, switch, state):
    self.settings["bit_perfect"] = state; self.save_settings()
    self._lock_volume_controls(state)
    self.ex_switch.set_sensitive(state)
    if not state: self.ex_switch.set_active(False)
    is_ex = self.ex_switch.get_active()
    self.player.toggle_bit_perfect(state, exclusive_lock=is_ex)
    if getattr(self, "eq_btn", None) is not None:
        self.eq_btn.set_sensitive(not state)
    if state and getattr(self, "eq_pop", None) is not None:
        self.eq_pop.popdown()
    if self.bp_label is not None: self.bp_label.set_visible(state)
    if is_ex:
        self._force_driver_selection("ALSA"); self.driver_dd.set_sensitive(False); self.on_driver_changed(self.driver_dd, None)
    else:
        self.driver_dd.set_sensitive(True)
        drv_item = self.driver_dd.get_selected_item() if self.driver_dd is not None else None
        drv_name = drv_item.get_string() if drv_item is not None else ""
        if state and drv_name == "PipeWire" and hasattr(self.player, "ensure_pipewire_pro_audio"):
            def _switch_to_pro_audio():
                ok = False
                try:
                    ok = bool(self.player.ensure_pipewire_pro_audio())
                except Exception:
                    ok = False

                def _apply_ui():
                    try:
                        _refresh_devices_for_current_driver_ui_only(
                            self, reason="bit-perfect-pro-audio"
                        )
                    except Exception:
                        pass
                    if ok:
                        self.show_output_notice("Bit-perfect enabled: switched card profile to pro-audio.", "ok", 2800)
                    else:
                        self.show_output_notice(
                            "Bit-perfect enabled, but pro-audio switch failed. You can still choose device manually.",
                            "warn",
                            3800,
                        )
                    return False

                GLib.idle_add(_apply_ui)

            submit_daemon(_switch_to_pro_audio)


def on_exclusive_toggled(self, switch, state):
    self.settings["exclusive_lock"] = state
    self.save_settings()

    self.player.toggle_bit_perfect(True, exclusive_lock=state)

    self.latency_dd.set_sensitive(state)

    if state:
        # 开启独占：强制 ALSA，禁用驱动选择
        self._force_driver_selection("ALSA")
        self.driver_dd.set_sensitive(False)
        self.on_driver_changed(self.driver_dd, None)
    else:
        # 关闭独占：恢复驱动选择
        self.driver_dd.set_sensitive(True)
        # 刷新一下非独占状态下的设备列表
        self.on_device_changed(self.device_dd, None)


def on_auto_rebind_once_toggled(self, switch, state):
    self.settings["output_auto_rebind_once"] = bool(state)
    self.save_settings()
