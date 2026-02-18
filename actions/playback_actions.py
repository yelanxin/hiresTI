import random


def on_play_pause(app, btn):
    if app.player.is_playing():
        app.player.pause()
        btn.set_icon_name("media-playback-start-symbolic")
    else:
        app.player.play()
        btn.set_icon_name("media-playback-pause-symbolic")


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

    if app.play_mode == app.MODE_ONE:
        if btn is None:
            next_idx = current
        else:
            next_idx = (current + 1) % total
    elif app.play_mode in [app.MODE_SHUFFLE, app.MODE_SMART]:
        if total <= 1:
            next_idx = 0
        else:
            if not hasattr(app, "shuffle_indices") or not app.shuffle_indices:
                app._generate_shuffle_list()
            if app.shuffle_indices:
                next_idx = random.choice(app.shuffle_indices)
            else:
                next_idx = (current + 1) % total
    else:
        next_idx = (current + 1) % total

    if 0 <= next_idx < total:
        app.play_track(next_idx)


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

    if app.play_mode == app.MODE_ONE:
        pass

    if app.play_mode in [app.MODE_SHUFFLE, app.MODE_SMART]:
        if direction == 1:
            if not app.shuffle_indices:
                app._generate_shuffle_list()

            if not app.shuffle_indices:
                return current

            next_idx = random.randint(0, total - 1)
            if total > 1:
                while next_idx == current:
                    next_idx = random.randint(0, total - 1)
            return next_idx
        return (current - 1) % total

    return (current + direction) % total
