from threading import Thread
import logging

from gi.repository import Gtk, GLib

logger = logging.getLogger(__name__)

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


def on_recover_output_clicked(app, _btn=None):
    driver = getattr(app.player, "requested_driver", None)
    device_id = getattr(app.player, "requested_device_id", None)
    if not driver:
        return
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
                app.player.set_output(driver_name, target_id)
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
    idx = dd.get_selected()
    if hasattr(app, "current_device_list") and idx < len(app.current_device_list):
        device_info = app.current_device_list[idx]
        app.current_device_name = device_info["name"]
        app.update_tech_label(app.player.stream_info)
        app.settings["device"] = device_info["name"]
        app.save_settings()
        driver_label = app.driver_dd.get_selected_item().get_string()
        app.player.set_output(driver_label, device_info["device_id"])
        if hasattr(app, "_apply_viz_sync_offset_for_device"):
            app._apply_viz_sync_offset_for_device(driver_label, device_id=device_info["device_id"], device_name=device_info["name"])
        update_output_status_ui(app)
