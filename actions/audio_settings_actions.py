from threading import Thread
import logging
import time

from gi.repository import Gtk, GLib

logger = logging.getLogger(__name__)


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
            old_names = [d.get("name") for d in getattr(app, "current_device_list", [])]
            new_names = [d.get("name") for d in devices]
            if new_names == old_names:
                return False
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
        old_names = [d.get("name") for d in getattr(app, "current_device_list", [])]

        app._device_list_sync_running = True

        def worker():
            try:
                devices = app.player.get_devices_for_driver(driver_name)
                new_names = [d.get("name") for d in devices]

                def apply_result():
                    app._device_list_sync_running = False
                    if new_names == old_names:
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
        app.player.visual_sync_offset_ms = int(buf_ms)
        app.settings["viz_sync_offset_ms"] = int(buf_ms)
        if hasattr(app, "_viz_sync_last_saved_ms"):
            app._viz_sync_last_saved_ms = int(buf_ms)
        logger.info(
            "Viz sync offset applied: %dms (source=latency-change profile=%s)",
            int(buf_ms),
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
        remembered_name = str(getattr(app, "_last_disconnected_device_name", "") or "")
        if remembered_name and device_info.get("name") == remembered_name:
            app._last_disconnected_device_name = ""
            app._last_disconnected_driver = ""
        app.current_device_name = device_info["name"]
        app.update_tech_label(app.player.stream_info)
        app.settings["device"] = device_info["name"]
        app.save_settings()
        driver_label = app.driver_dd.get_selected_item().get_string()
        ok = app.player.set_output(driver_label, device_info["device_id"])
        if not ok:
            if hasattr(app, "show_output_notice"):
                app.show_output_notice(
                    f"Output device unavailable: {device_info['name']}",
                    "error",
                    4200,
                )
            update_output_status_ui(app)
            return
        if hasattr(app, "_apply_viz_sync_offset_for_device"):
            app._apply_viz_sync_offset_for_device(driver_label, device_id=device_info["device_id"], device_name=device_info["name"])
        update_output_status_ui(app)
