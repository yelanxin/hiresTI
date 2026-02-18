from threading import Thread

from gi.repository import GLib

import utils


def on_quality_changed(app, dd, p):
    selected = dd.get_selected_item()
    if not selected:
        return
    mode_str = selected.get_string()
    app.backend.set_quality_mode(mode_str)
    if hasattr(app, "stream_prefetch_cache"):
        app.stream_prefetch_cache.clear()

    if app.player.is_playing() and app.current_index >= 0:
        pos, _ = app.player.get_position()
        track = app.current_track_list[app.current_index]

        def refresh():
            new_url = app.backend.get_stream_url(track)
            GLib.idle_add(lambda: app._restart_player_with_url(new_url, pos))

        Thread(target=refresh, daemon=True).start()


def restart_player_with_url(app, url, pos):
    if not url:
        return
    app.player.stop()
    app.player.load(url)
    app.player.play()
    GLib.timeout_add(700, lambda: app.player.seek(pos))


def load_cover_art(app, cover_id_or_url):
    url = app._get_tidal_image_url(cover_id_or_url)
    if not url:
        return

    if hasattr(app, "art_img"):
        utils.load_img(app.art_img, url, app.cache_dir, 80)
