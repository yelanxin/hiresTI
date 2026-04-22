"""Local-file playback handlers.

Opens a file picker, builds a LocalTrack via the sources/local module,
replaces the active queue with that single track, and starts playback.
"""

from __future__ import annotations

import logging
import os

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

logger = logging.getLogger(__name__)


_AUDIO_EXTENSIONS = (
    "flac", "mp3", "m4a", "mp4", "aac", "alac",
    "wav", "wave", "aiff", "aif", "ogg", "oga", "opus",
    "dsf", "dff", "ape", "wv",
)


def _build_audio_filters():
    filters = Gtk.ListStore.new(Gtk.FileFilter)
    audio_filter = Gtk.FileFilter()
    audio_filter.set_name("Audio files")
    for ext in _AUDIO_EXTENSIONS:
        audio_filter.add_pattern(f"*.{ext}")
        audio_filter.add_pattern(f"*.{ext.upper()}")
    filters.append(audio_filter)
    any_filter = Gtk.FileFilter()
    any_filter.set_name("All files")
    any_filter.add_pattern("*")
    filters.append(any_filter)
    return filters, audio_filter


def on_open_local_file_clicked(self, _btn=None):
    dialog = Gtk.FileDialog(title="Open Local Audio File")
    try:
        dialog.set_modal(True)
    except Exception:
        pass
    try:
        filters, default_filter = _build_audio_filters()
        dialog.set_filters(filters)
        dialog.set_default_filter(default_filter)
    except Exception:
        logger.debug("failed to attach audio filters", exc_info=True)
    parent = getattr(self, "win", None)
    dialog.open(parent, None, self._on_local_file_selected)


def _on_local_file_selected(self, dialog, result):
    try:
        file_obj = dialog.open_finish(result)
    except GLib.Error as exc:
        logger.debug("file dialog cancelled or failed: %s", exc)
        return
    except Exception:
        logger.debug("file dialog open_finish failed", exc_info=True)
        return
    if file_obj is None:
        return
    try:
        path = file_obj.get_path()
    except Exception:
        path = None
    if not path or not os.path.isfile(path):
        logger.info("selected local file is not a regular file: %r", path)
        return

    _start_local_playback(self, path)


def _start_local_playback(app, path: str):
    from sources.local.tags import read_tags
    from sources.local.track import make_local_track

    try:
        tags = read_tags(path)
    except Exception:
        logger.debug("read_tags failed for %s", path, exc_info=True)
        tags = {"path": path}

    try:
        track = make_local_track(path, tags)
    except Exception:
        logger.exception("make_local_track failed for %s", path)
        return

    logger.info(
        "local playback start: path=%s title=%r bit_depth=%s sample_rate=%s",
        path, track.name, track.bit_depth, track.sample_rate,
    )

    try:
        app.playback_source = {"type": "local", "path": path}
    except Exception:
        pass
    app.current_track_list = [track]
    if hasattr(app, "_set_play_queue"):
        app._set_play_queue([track])
    else:
        app.play_queue = [track]

    # Make sure the bottom play bar + player overlay are visible even when
    # the user hasn't logged into Tidal — the login gate normally keeps them
    # hidden. Phase-0 scaffold: surface local playback regardless.
    for attr in ("bottom_bar", "player_overlay"):
        widget = getattr(app, attr, None)
        if widget is not None:
            try:
                widget.set_visible(True)
            except Exception:
                pass

    if hasattr(app, "play_track"):
        app.play_track(0)
