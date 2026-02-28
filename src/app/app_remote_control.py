"""Remote-control settings, lifecycle and GTK glue."""

from __future__ import annotations

import ipaddress
import logging
import os
import threading

from gi.repository import GLib

from services.remote_api import RemoteAPIService, parse_allowed_cidrs
from services.remote_auth import ensure_secret, load_secret
from services.remote_dispatch import player_state_snapshot, queue_public_snapshot
from services.remote_events import RemoteEventHub

logger = logging.getLogger(__name__)


REMOTE_ACCESS_MODES = ["Local only", "LAN"]
REMOTE_ACCESS_VALUE_BY_LABEL = {
    "Local only": "local",
    "LAN": "lan",
}
REMOTE_ACCESS_LABEL_BY_VALUE = {
    "local": "Local only",
    "lan": "LAN",
}


def _init_remote_control_state(self):
    self.remote_api_secret_file = os.path.join(self._config_root, "remote_api_secret.json")
    self.remote_api_key = str(load_secret(self.remote_api_secret_file).get("api_key", "") or "").strip()
    self._remote_api_service = None
    self._remote_event_hub = RemoteEventHub()
    self._remote_queue_event_suppression = 0
    self.remote_api_status_state = "stopped"
    self.remote_api_status_text = "Stopped"
    self.remote_api_last_error = ""


def _effective_remote_api_host(self):
    mode = str(self.settings.get("remote_api_access_mode", "local") or "local")
    if mode != "lan":
        return "127.0.0.1"
    return str(self.settings.get("remote_api_bind_host", "0.0.0.0") or "0.0.0.0").strip() or "0.0.0.0"


def get_remote_api_endpoint(self):
    host = self._effective_remote_api_host()
    port = int(self.settings.get("remote_api_port", 18473) or 18473)
    return f"http://{host}:{port}/rpc"


def get_remote_mcp_endpoint(self):
    host = self._effective_remote_api_host()
    port = int(self.settings.get("remote_api_port", 18473) or 18473)
    return f"http://{host}:{port}/mcp"


def _set_remote_api_status(self, state, text, detail=""):
    self.remote_api_status_state = str(state or "stopped")
    self.remote_api_status_text = str(text or "")
    self.remote_api_last_error = str(detail or "")
    if hasattr(self, "_refresh_remote_api_settings_ui"):
        self._refresh_remote_api_settings_ui()


def _ensure_remote_api_key(self, regenerate=False):
    payload = ensure_secret(self.remote_api_secret_file, regenerate=bool(regenerate))
    self.remote_api_key = str(payload.get("api_key", "") or "").strip()
    if hasattr(self, "_refresh_remote_api_settings_ui"):
        self._refresh_remote_api_settings_ui()
    return self.remote_api_key


def _refresh_remote_api_settings_ui(self):
    if getattr(self, "_remote_ui_syncing", False):
        return
    self._remote_ui_syncing = True
    try:
        enabled = bool(self.settings.get("remote_api_enabled", False))
        mode = str(self.settings.get("remote_api_access_mode", "local") or "local")
        is_lan = mode == "lan"
        mode_label = REMOTE_ACCESS_LABEL_BY_VALUE.get(mode, "Local only")
        bind_host = str(self.settings.get("remote_api_bind_host", "0.0.0.0") or "0.0.0.0")
        allowed = ", ".join(self.settings.get("remote_api_allowed_cidrs", []) or [])
        key_value = str(getattr(self, "remote_api_key", "") or "")

        switch = getattr(self, "remote_api_switch", None)
        if switch is not None:
            switch.set_active(enabled)

        dd = getattr(self, "remote_api_access_dd", None)
        if dd is not None:
            labels = REMOTE_ACCESS_MODES
            try:
                dd.set_selected(labels.index(mode_label))
            except ValueError:
                dd.set_selected(0)

        network_row = getattr(self, "remote_api_network_row", None)
        if network_row is not None:
            network_row.set_visible(is_lan)

        bind_entry = getattr(self, "remote_api_bind_entry", None)
        if bind_entry is not None:
            bind_entry.set_text(bind_host)
            bind_entry.set_sensitive(is_lan)

        port_spin = getattr(self, "remote_api_port_spin", None)
        if port_spin is not None:
            port_spin.set_value(float(int(self.settings.get("remote_api_port", 18473) or 18473)))

        allowlist_row = getattr(self, "remote_api_allowlist_row", None)
        if allowlist_row is not None:
            allowlist_row.set_visible(is_lan)

        allow_entry = getattr(self, "remote_api_allowlist_entry", None)
        if allow_entry is not None:
            allow_entry.set_text(allowed)

        endpoint_label = getattr(self, "remote_api_endpoint_label", None)
        if endpoint_label is not None:
            endpoint_label.set_label(self.get_remote_api_endpoint())

        status_label = getattr(self, "remote_api_status_label", None)
        if status_label is not None:
            status = self.remote_api_status_text or ("Running" if self._remote_api_service else "Stopped")
            status_label.set_label(status)

        key_entry = getattr(self, "remote_api_key_entry", None)
        if key_entry is not None:
            key_entry.set_text(key_value)

        copy_btn = getattr(self, "remote_api_copy_btn", None)
        if copy_btn is not None:
            copy_btn.set_sensitive(bool(key_value))

        gen_btn = getattr(self, "remote_api_generate_btn", None)
        if gen_btn is not None:
            gen_btn.set_label("Regenerate Key" if key_value else "Generate Key")

        apply_btn = getattr(self, "remote_api_apply_btn", None)
        if apply_btn is not None:
            apply_btn.set_sensitive(True)
    finally:
        self._remote_ui_syncing = False


def _start_remote_api(self, show_notice=False):
    if getattr(self, "_remote_api_service", None) is not None:
        return True

    host = self._effective_remote_api_host()
    port = int(self.settings.get("remote_api_port", 18473) or 18473)
    api_key = self._ensure_remote_api_key()
    allowed_cidrs = list(self.settings.get("remote_api_allowed_cidrs", []) or [])

    try:
        service = RemoteAPIService(
            self,
            host=host,
            port=port,
            api_key=api_key,
            allowed_cidrs=allowed_cidrs,
        )
        service.start()
    except Exception as exc:
        logger.exception("Failed to start remote API")
        text = f"Error: {exc}"
        self._set_remote_api_status("error", text, str(exc))
        if hasattr(self, "record_diag_event"):
            self.record_diag_event(f"Remote API start failed: {exc}")
        if show_notice and hasattr(self, "show_output_notice"):
            self.show_output_notice(text, "error", 3600)
        return False

    self._remote_api_service = service
    status = f"Running on {service.host}:{service.port}"
    self._set_remote_api_status("running", status)
    if hasattr(self, "record_diag_event"):
        self.record_diag_event(f"Remote API listening on {service.host}:{service.port}")
    if show_notice and hasattr(self, "show_output_notice"):
        self.show_output_notice("Remote control enabled.", "ok", 2200)
    return True


def _stop_remote_api(self, show_notice=False):
    service = getattr(self, "_remote_api_service", None)
    self._remote_api_service = None
    if service is not None:
        try:
            service.stop()
        except Exception:
            logger.exception("Failed to stop remote API cleanly")
    self._set_remote_api_status("stopped", "Stopped")
    if hasattr(self, "record_diag_event"):
        self.record_diag_event("Remote API stopped")
    if show_notice and hasattr(self, "show_output_notice"):
        self.show_output_notice("Remote control disabled.", "warn", 2200)


def _restart_remote_api(self, show_notice=False):
    was_running = getattr(self, "_remote_api_service", None) is not None
    if was_running:
        self._stop_remote_api(show_notice=False)
    if bool(self.settings.get("remote_api_enabled", False)):
        return self._start_remote_api(show_notice=show_notice)
    return True


def _start_remote_api_if_enabled(self):
    if bool(self.settings.get("remote_api_enabled", False)):
        self._start_remote_api(show_notice=False)
    else:
        self._set_remote_api_status("stopped", "Stopped")
    return False


def _remote_publish_event(self, event_type, payload=None):
    hub = getattr(self, "_remote_event_hub", None)
    if hub is None:
        return None
    return hub.publish(str(event_type or "message"), payload if isinstance(payload, dict) else {})


def _remote_publish_queue_event(self, reason="queue_changed"):
    if int(getattr(self, "_remote_queue_event_suppression", 0) or 0) > 0:
        return None
    payload = queue_public_snapshot(self)
    payload["reason"] = str(reason or "queue_changed")
    return self._remote_publish_event("queue_changed", payload)


def _remote_publish_track_event(self, reason="track_changed"):
    payload = {
        "reason": str(reason or "track_changed"),
        "state": player_state_snapshot(self),
    }
    return self._remote_publish_event("track_changed", payload)


def _remote_publish_playback_event(self, reason="playback_changed"):
    payload = {
        "reason": str(reason or "playback_changed"),
        "state": player_state_snapshot(self),
    }
    return self._remote_publish_event("playback_changed", payload)


def _parse_allowed_cidrs(value):
    text = str(value or "").strip()
    if not text:
        return []
    cidrs = []
    for chunk in text.split(","):
        token = str(chunk or "").strip()
        if not token:
            continue
        cidrs.append(str(ipaddress.ip_network(token, strict=False)))
    return parse_allowed_cidrs(cidrs)


def _copy_remote_text_to_clipboard(self, value, label):
    text = str(value or "").strip()
    if not text:
        return False
    win = getattr(self, "win", None)
    if win is None:
        return False
    display = win.get_display()
    if display is None:
        return False
    try:
        display.get_clipboard().set(text)
        return True
    except Exception:
        logger.exception("Failed to copy remote %s", label)
        return False


def _copy_remote_api_key_to_clipboard(self):
    return _copy_remote_text_to_clipboard(self, getattr(self, "remote_api_key", ""), "API key")


def on_remote_api_enabled_toggled(self, _switch, state):
    if getattr(self, "_remote_ui_syncing", False):
        return
    self.settings["remote_api_enabled"] = bool(state)
    self.save_settings()
    if state:
        self._start_remote_api(show_notice=True)
    else:
        self._stop_remote_api(show_notice=True)
    self._refresh_remote_api_settings_ui()


def on_remote_api_access_mode_changed(self, dropdown, _param=None):
    if getattr(self, "_remote_ui_syncing", False):
        return
    item = dropdown.get_selected_item()
    label = item.get_string() if item is not None else "Local only"
    mode = REMOTE_ACCESS_VALUE_BY_LABEL.get(label, "local")
    self.settings["remote_api_access_mode"] = mode
    self.save_settings()
    self._refresh_remote_api_settings_ui()
    if bool(self.settings.get("remote_api_enabled", False)):
        self._restart_remote_api(show_notice=False)


def on_remote_api_apply_network_settings(self, _btn=None):
    bind_entry = getattr(self, "remote_api_bind_entry", None)
    allow_entry = getattr(self, "remote_api_allowlist_entry", None)
    port_spin = getattr(self, "remote_api_port_spin", None)

    try:
        host = str(bind_entry.get_text() if bind_entry is not None else self.settings.get("remote_api_bind_host", "0.0.0.0") or "").strip()
        if not host:
            host = "0.0.0.0"
        port = int(port_spin.get_value_as_int() if port_spin is not None else int(self.settings.get("remote_api_port", 18473) or 18473))
        if port < 1 or port > 65535:
            raise ValueError("Port must be between 1 and 65535.")
        allowed = _parse_allowed_cidrs(allow_entry.get_text() if allow_entry is not None else "")
    except Exception as exc:
        if hasattr(self, "show_output_notice"):
            self.show_output_notice(f"Invalid remote network settings: {exc}", "warn", 3200)
        return

    self.settings["remote_api_bind_host"] = host
    self.settings["remote_api_port"] = port
    self.settings["remote_api_allowed_cidrs"] = allowed
    self.save_settings()

    if bool(self.settings.get("remote_api_enabled", False)):
        ok = self._restart_remote_api(show_notice=False)
        if hasattr(self, "show_output_notice"):
            self.show_output_notice(
                "Remote network settings applied." if ok else "Remote network settings saved, but service restart failed.",
                "ok" if ok else "warn",
                2600,
            )
    else:
        self._refresh_remote_api_settings_ui()
        if hasattr(self, "show_output_notice"):
            self.show_output_notice("Remote network settings saved.", "ok", 2200)


def on_remote_api_generate_key_clicked(self, _btn=None):
    self._ensure_remote_api_key(regenerate=True)
    if bool(self.settings.get("remote_api_enabled", False)):
        self._restart_remote_api(show_notice=False)
    if hasattr(self, "show_output_notice"):
        self.show_output_notice("Remote API key regenerated.", "ok", 2200)


def on_remote_api_copy_key_clicked(self, _btn=None):
    copied = self._copy_remote_api_key_to_clipboard()
    if hasattr(self, "show_output_notice"):
        self.show_output_notice(
            "Remote API key copied." if copied else "Failed to copy remote API key.",
            "ok" if copied else "warn",
            2200,
        )


def on_remote_api_copy_endpoint_clicked(self, _btn=None):
    copied = _copy_remote_text_to_clipboard(self, self.get_remote_api_endpoint(), "endpoint")
    if hasattr(self, "show_output_notice"):
        self.show_output_notice(
            "Remote endpoint copied." if copied else "Failed to copy remote endpoint.",
            "ok" if copied else "warn",
            2200,
        )


def _remote_invoke_on_main(self, fn, *args, timeout=6.0):
    done = threading.Event()
    box = {"result": None, "error": None}

    def _task():
        try:
            box["result"] = fn(*args)
        except Exception as exc:
            box["error"] = exc
        finally:
            done.set()
        return False

    GLib.idle_add(_task)
    if not done.wait(timeout=max(0.1, float(timeout or 6.0))):
        raise TimeoutError("Timed out waiting for GTK main loop.")
    if box["error"] is not None:
        raise box["error"]
    return box["result"]


def _remote_close_event_streams(self):
    hub = getattr(self, "_remote_event_hub", None)
    if hub is not None:
        hub.close_all()


def _remote_replace_queue(self, tracks, autoplay=True, start_index=0):
    queue = list(tracks or [])
    self._remote_queue_event_suppression = int(getattr(self, "_remote_queue_event_suppression", 0) or 0) + 1
    try:
        if hasattr(self, "_set_play_queue"):
            self._set_play_queue(queue)
        else:
            self.play_queue = queue
    finally:
        self._remote_queue_event_suppression = max(0, int(getattr(self, "_remote_queue_event_suppression", 1) or 1) - 1)
    self.shuffle_indices = []

    if not queue:
        self.current_track_index = -1
        self.playing_track = None
        self.playing_track_id = None
        try:
            self.player.stop()
        except Exception:
            pass
        if getattr(self, "play_btn", None) is not None:
            self.play_btn.set_icon_name("media-playback-start-symbolic")
        if hasattr(self, "_mpris_sync_all"):
            self._mpris_sync_all(force=True)
        if hasattr(self, "_refresh_queue_views"):
            GLib.idle_add(self._refresh_queue_views)
        self._remote_publish_queue_event("queue_replaced")
        self._remote_publish_playback_event("queue_cleared")
        return {"queue_size": 0, "autoplay": False, "start_index": -1}

    if not autoplay:
        self.current_track_index = 0
        self.playing_track = None
        self.playing_track_id = None
        try:
            self.player.stop()
        except Exception:
            pass
        if getattr(self, "play_btn", None) is not None:
            self.play_btn.set_icon_name("media-playback-start-symbolic")
        if hasattr(self, "_mpris_sync_all"):
            self._mpris_sync_all(force=True)
        if hasattr(self, "_refresh_queue_views"):
            GLib.idle_add(self._refresh_queue_views)
        self._remote_publish_queue_event("queue_replaced")
        self._remote_publish_playback_event("queue_loaded")
        return {"queue_size": len(queue), "autoplay": False, "start_index": 0}

    idx = int(start_index or 0)
    if idx < 0 or idx >= len(queue):
        idx = 0
    self._remote_publish_queue_event("queue_replaced")
    self.play_track(idx)
    if hasattr(self, "_refresh_queue_views"):
        GLib.idle_add(self._refresh_queue_views)
    return {"queue_size": len(queue), "autoplay": True, "start_index": idx}


def _remote_append_queue(self, tracks):
    additions = list(tracks or [])
    base_queue = list(self._get_active_queue() if hasattr(self, "_get_active_queue") else [])
    new_queue = base_queue + additions
    self._remote_queue_event_suppression = int(getattr(self, "_remote_queue_event_suppression", 0) or 0) + 1
    try:
        if hasattr(self, "_set_play_queue"):
            self._set_play_queue(new_queue)
        else:
            self.play_queue = new_queue
    finally:
        self._remote_queue_event_suppression = max(0, int(getattr(self, "_remote_queue_event_suppression", 1) or 1) - 1)
    if hasattr(self, "_refresh_queue_views"):
        GLib.idle_add(self._refresh_queue_views)
    if hasattr(self, "_mpris_sync_metadata"):
        self._mpris_sync_metadata()
    self._remote_publish_queue_event("queue_appended")
    return {"queue_size": len(new_queue), "added": len(additions)}


def _remote_move_queue_item(self, from_index, to_index):
    queue = list(self._get_active_queue() if hasattr(self, "_get_active_queue") else [])
    total = len(queue)
    src = int(from_index)
    dst = int(to_index)
    if src < 0 or src >= total or dst < 0 or dst >= total:
        raise ValueError("Queue move indexes are out of range.")
    if src == dst:
        return {
            "queue_size": total,
            "from_index": src,
            "to_index": dst,
            "current_index": int(getattr(self, "current_track_index", -1)),
        }

    moved = queue.pop(src)
    queue.insert(dst, moved)
    current_index = int(getattr(self, "current_track_index", -1))
    if current_index == src:
        current_index = dst
    elif src < current_index <= dst:
        current_index -= 1
    elif dst <= current_index < src:
        current_index += 1

    self._remote_queue_event_suppression = int(getattr(self, "_remote_queue_event_suppression", 0) or 0) + 1
    try:
        if hasattr(self, "_set_play_queue"):
            self._set_play_queue(queue)
        else:
            self.play_queue = queue
    finally:
        self._remote_queue_event_suppression = max(0, int(getattr(self, "_remote_queue_event_suppression", 1) or 1) - 1)

    self.current_track_index = current_index if 0 <= current_index < len(queue) else -1
    if 0 <= self.current_track_index < len(queue):
        self.playing_track = queue[self.current_track_index]
        self.playing_track_id = getattr(self.playing_track, "id", None)
    if hasattr(self, "_refresh_queue_views"):
        GLib.idle_add(self._refresh_queue_views)
    if hasattr(self, "_mpris_sync_metadata"):
        self._mpris_sync_metadata()
    self._remote_publish_queue_event("queue_moved")
    return {
        "queue_size": len(queue),
        "from_index": src,
        "to_index": dst,
        "current_index": self.current_track_index,
    }


def _remote_insert_queue_at(self, tracks, index):
    additions = list(tracks or [])
    base_queue = list(self._get_active_queue() if hasattr(self, "_get_active_queue") else [])
    insert_index = max(0, min(int(index), len(base_queue)))
    new_queue = base_queue[:insert_index] + additions + base_queue[insert_index:]
    current_index = int(getattr(self, "current_track_index", -1))
    if current_index >= insert_index:
        current_index += len(additions)

    self._remote_queue_event_suppression = int(getattr(self, "_remote_queue_event_suppression", 0) or 0) + 1
    try:
        if hasattr(self, "_set_play_queue"):
            self._set_play_queue(new_queue)
        else:
            self.play_queue = new_queue
    finally:
        self._remote_queue_event_suppression = max(0, int(getattr(self, "_remote_queue_event_suppression", 1) or 1) - 1)

    self.current_track_index = current_index if 0 <= current_index < len(new_queue) else -1
    if 0 <= self.current_track_index < len(new_queue):
        self.playing_track = new_queue[self.current_track_index]
        self.playing_track_id = getattr(self.playing_track, "id", None)
    if hasattr(self, "_refresh_queue_views"):
        GLib.idle_add(self._refresh_queue_views)
    if hasattr(self, "_mpris_sync_metadata"):
        self._mpris_sync_metadata()
    self._remote_publish_queue_event("queue_inserted")
    return {
        "queue_size": len(new_queue),
        "insert_index": insert_index,
        "inserted": len(additions),
        "current_index": self.current_track_index,
    }


def _remote_insert_queue_next(self, tracks):
    current_index = int(getattr(self, "current_track_index", -1))
    base_queue = list(self._get_active_queue() if hasattr(self, "_get_active_queue") else [])
    insert_index = current_index + 1 if 0 <= current_index < len(base_queue) else 0
    return self._remote_insert_queue_at(tracks, insert_index)
