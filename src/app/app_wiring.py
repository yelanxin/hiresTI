"""Bind delegated app/actions methods onto TidalApp."""

from app.wiring_actions import bind_action_delegates, bind_audio_settings_extras
from app.wiring_handlers import bind_handlers_core, bind_handlers_extra
from app.wiring_playlist import bind_playlist
from app.wiring_remote import bind_remote_control
from app.wiring_ui import (
    bind_album,
    bind_builders,
    bind_favorites,
    bind_lifecycle,
    bind_now_playing,
    bind_search,
    bind_tray,
    bind_ui_loop,
)
from app.wiring_utils import bind_map
from app.wiring_visualizer import bind_lyrics_settings, bind_visualizer

# Backward compatibility for tests/importers expecting the old helper name.
_bind_map = bind_map


def is_tidal_app_wired(TidalApp):
    return bool(getattr(TidalApp, "_wiring_applied", False))


def wire_tidal_app(TidalApp, force=False):
    if is_tidal_app_wired(TidalApp) and not force:
        return

    seen = set()

    bind_visualizer(TidalApp, seen=seen)
    bind_handlers_core(TidalApp, seen=seen)
    bind_playlist(TidalApp, seen=seen)
    bind_action_delegates(TidalApp, seen=seen)
    bind_tray(TidalApp, seen=seen)
    bind_lifecycle(TidalApp, seen=seen)
    bind_album(TidalApp, seen=seen)
    bind_favorites(TidalApp, seen=seen)
    bind_ui_loop(TidalApp, seen=seen)
    bind_search(TidalApp, seen=seen)
    bind_now_playing(TidalApp, seen=seen)
    bind_builders(TidalApp, seen=seen)
    bind_remote_control(TidalApp, seen=seen)
    bind_audio_settings_extras(TidalApp, seen=seen)
    bind_lyrics_settings(TidalApp, seen=seen)
    bind_handlers_extra(TidalApp, seen=seen)
    setattr(TidalApp, "_wiring_applied", True)


__all__ = ["wire_tidal_app", "is_tidal_app_wired", "_bind_map"]
