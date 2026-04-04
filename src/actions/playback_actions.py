import math
import random
import time

from actions import audio_settings_actions

_PREV_RESTART_THRESHOLD_S = 5.0
_PREV_DOUBLE_TAP_WINDOW_S = 2.0


def _stop_after_queue_end(app):
    player = getattr(app, "player", None)
    if player is not None and hasattr(player, "stop"):
        try:
            player.stop()
        except Exception:
            pass
    play_btn = getattr(app, "play_btn", None)
    if play_btn is not None and hasattr(play_btn, "set_icon_name"):
        try:
            play_btn.set_icon_name("media-playback-start-symbolic")
        except Exception:
            pass
    if hasattr(app, "_sync_playback_status_icon"):
        try:
            app._sync_playback_status_icon()
        except Exception:
            pass
    if hasattr(app, "_mpris_sync_playback"):
        app._mpris_sync_playback()
    if hasattr(app, "_mpris_sync_position"):
        app._mpris_sync_position(force=True)
    if hasattr(app, "_remote_publish_playback_event"):
        app._remote_publish_playback_event("stopped")


def _choose_shuffle_index(app, current, total):
    if not hasattr(app, "shuffle_indices") or not app.shuffle_indices:
        app._generate_shuffle_list()

    raw_candidates = list(getattr(app, "shuffle_indices", []) or [])
    candidates = [idx for idx in raw_candidates if isinstance(idx, int) and 0 <= idx < total and idx != current]
    if candidates:
        return random.choice(candidates)

    fallback = [idx for idx in range(total) if idx != current]
    if fallback:
        return random.choice(fallback)
    return current


def on_play_pause(app, btn):
    if app.player.is_playing():
        app.player.pause()
        if btn is not None:
            btn.set_icon_name("media-playback-start-symbolic")
        if hasattr(app, "_mpris_sync_playback"):
            app._mpris_sync_playback()
        if hasattr(app, "_mpris_sync_position"):
            app._mpris_sync_position(force=True)
        if hasattr(app, "_remote_publish_playback_event"):
            app._remote_publish_playback_event("paused")
    else:
        app.player.play()
        audio_settings_actions.update_output_status_ui(app)
        state = str(getattr(app.player, "output_state", "idle") or "idle")
        err = str(getattr(app.player, "output_error", "") or "").strip()
        blocked = bool(getattr(app.player, "_pipewire_rate_blocked", False))
        if blocked or state == "error":
            if btn is not None:
                btn.set_icon_name("media-playback-start-symbolic")
            msg = err or "Audio output error."
            if hasattr(app, "show_output_notice"):
                app.show_output_notice(f"Output error: {msg}", "error", 4200)
            if blocked and hasattr(app, "_show_simple_dialog"):
                app._show_simple_dialog("Playback blocked", msg)
            if hasattr(app, "_mpris_sync_playback"):
                app._mpris_sync_playback()
            if hasattr(app, "_mpris_sync_position"):
                app._mpris_sync_position(force=True)
            if hasattr(app, "_remote_publish_playback_event"):
                app._remote_publish_playback_event("playback_error")
            return
        if btn is not None:
            btn.set_icon_name("media-playback-pause-symbolic")
        if hasattr(app, "_mpris_sync_playback"):
            app._mpris_sync_playback()
        if hasattr(app, "_mpris_sync_position"):
            app._mpris_sync_position(force=True)
        if hasattr(app, "_remote_publish_playback_event"):
            app._remote_publish_playback_event("resumed")


def on_next_track(app, btn=None):
    queue = app._get_active_queue() if hasattr(app, "_get_active_queue") else list(getattr(app, "current_track_list", []) or [])
    if not queue:
        return

    total = len(queue)
    if total == 0:
        return

    current = getattr(app, "current_track_index", 0)
    if current is None:
        current = 0

    next_idx = -1

    mode_normal = getattr(app, "MODE_NORMAL", 4)
    mode_loop = getattr(app, "MODE_LOOP", 0)

    if app.play_mode == app.MODE_ONE:
        if btn is None:
            next_idx = current
        else:
            next_idx = (current + 1) % total
    elif app.play_mode in [app.MODE_SHUFFLE, app.MODE_SMART]:
        if total <= 1:
            next_idx = 0
        else:
            next_idx = _choose_shuffle_index(app, current, total)
    elif app.play_mode == mode_loop:
        next_idx = (current + 1) % total
    elif app.play_mode == mode_normal:
        if current + 1 < total:
            next_idx = current + 1

    if 0 <= next_idx < total:
        app.play_track(next_idx)
    elif app.play_mode == mode_normal:
        _stop_after_queue_end(app)


def on_prev_track(app, btn=None):
    queue = app._get_active_queue() if hasattr(app, "_get_active_queue") else list(getattr(app, "current_track_list", []) or [])
    if not queue:
        return

    total = len(queue)
    if total == 0:
        return

    current = getattr(app, "current_track_index", 0)
    if current is None:
        current = 0

    now = time.monotonic()
    rewind_armed_until = float(getattr(app, "_prev_track_rewind_armed_until", 0.0) or 0.0)
    rewind_armed_index = getattr(app, "_prev_track_rewind_armed_index", None)
    rewind_to_start_armed = rewind_armed_index == current and now <= rewind_armed_until

    player = getattr(app, "player", None)
    if player is not None and hasattr(player, "get_position") and hasattr(player, "seek"):
        try:
            pos_s, _dur_s = player.get_position()
            pos_s = float(pos_s or 0.0)
        except Exception:
            pos_s = None
        if pos_s is not None and math.isfinite(pos_s) and pos_s <= _PREV_RESTART_THRESHOLD_S:
            if not rewind_to_start_armed:
                player.seek(0.0)
                app._prev_track_rewind_armed_until = now + _PREV_DOUBLE_TAP_WINDOW_S
                app._prev_track_rewind_armed_index = current
                if hasattr(app, "_mpris_emit_seeked"):
                    app._mpris_emit_seeked(0.0)
                if hasattr(app, "_mpris_sync_position"):
                    app._mpris_sync_position(force=True)
                if hasattr(app, "_remote_publish_playback_event"):
                    app._remote_publish_playback_event("seek")
                return

    app._prev_track_rewind_armed_until = 0.0
    app._prev_track_rewind_armed_index = None

    prev_idx = (current - 1) % total
    if 0 <= prev_idx < total:
        app.play_track(prev_idx)


def get_next_index(app, direction=1):
    queue = app._get_active_queue() if hasattr(app, "_get_active_queue") else list(getattr(app, "current_track_list", []) or [])
    if not queue:
        return -1

    total = len(queue)
    if total == 0:
        return -1

    current = getattr(app, "current_track_index", 0)
    if current is None or current < 0 or current >= total:
        current = 0

    mode_normal = getattr(app, "MODE_NORMAL", 4)

    if app.play_mode == app.MODE_ONE:
        return current

    if app.play_mode in [app.MODE_SHUFFLE, app.MODE_SMART]:
        if direction == 1:
            # Use the same selection logic as on_next_track so that prefetch
            # actually predicts the track that will be played next.
            return _choose_shuffle_index(app, current, total)
        return (current - 1) % total

    if app.play_mode == mode_normal:
        if direction == 1:
            return current + 1 if (current + 1) < total else -1
        return current - 1 if current > 0 else -1

    return (current + direction) % total
