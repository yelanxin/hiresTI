"""Start remote playlist playback without waiting for the browsing pages."""

import logging
import random

from gi.repository import GLib

from core.executor import submit_daemon
from models.playlist_queue import PlaylistQueueTrack

logger = logging.getLogger(__name__)


def _notice(app, message):
    if hasattr(app, "show_output_notice"):
        app.show_output_notice(message, "warn", 4000)


def cancel_pending_playlist(app):
    app._playlist_play_request = getattr(app, "_playlist_play_request", 0) + 1
    app._pending_playlist_start = None
    pending = getattr(app, "_pending_playlist_resolution", None)
    if pending is not None and pending == getattr(app, "_play_request_id", 0):
        app._play_request_id += 1
    app._pending_playlist_resolution = None


def start_playlist(app, shuffle=False, start_position=0, track_id=None):
    playlist = getattr(app, "current_remote_playlist", None)
    if playlist is None:
        return False
    pending = getattr(app, "_pending_playlist_start", None)
    if (pending is not None and pending[0] is playlist and pending[1] == shuffle
            and pending[2] == getattr(app, "_playlist_play_request", 0)
            and pending[3] == getattr(app, "_play_request_id", 0)
            and pending[4] == getattr(app, "_remote_pl_render_token", 0)
            and pending[5] == start_position and pending[6] == track_id):
        return True
    token = getattr(app, "_playlist_play_request", 0) + 1
    app._playlist_play_request = token
    play_request = getattr(app, "_play_request_id", 0)
    render_token = getattr(app, "_remote_pl_render_token", 0)
    pending = (playlist, shuffle, token, play_request, render_token, start_position, track_id)
    app._pending_playlist_start = pending
    if hasattr(app, "show_output_notice"):
        app.show_output_notice("Preparing playlist playback…", "info", 1800)

    def is_current():
        return (
            token == getattr(app, "_playlist_play_request", 0)
            and play_request == getattr(app, "_play_request_id", 0)
            and getattr(app, "current_remote_playlist", None) is playlist
            and render_token == getattr(app, "_remote_pl_render_token", 0)
            and app.right_stack.get_visible_child_name() == "tracks"
        )

    def task():
        try:
            source = app.backend.get_playlist_playback_queue(playlist, shuffled=shuffle)
            entries = source.entries()
            if not entries:
                raise ValueError("This playlist has no tracks.")
            if shuffle:
                random.shuffle(entries)
            # Resolve just the selected position before replacing existing playback.
            if not 0 <= start_position < len(entries):
                raise ValueError("The playlist has changed. Please open it again.")
            selected = entries[start_position].resolve()
            if track_id is not None and str(selected.id) != str(track_id):
                raise ValueError("The playlist has changed. Please open it again.")
            error = None
        except Exception as exc:
            logger.warning("Playlist playback could not start: %s", exc, exc_info=True)
            entries = []
            error = str(exc)

        def apply():
            if getattr(app, "_pending_playlist_start", None) is pending:
                app._pending_playlist_start = None
            if not is_current():
                return False
            if error:
                _notice(app, f"Could not play playlist: {error}")
                return False
            app.playback_source = {
                "type": "playlist", "name": getattr(playlist, "name", "Playlist"),
                "obj": playlist,
            }
            app._set_play_queue(entries)
            app.play_track(start_position)
            return False

        GLib.idle_add(apply)

    submit_daemon(task)
    return True


def resolve_for_playback(app, entry, index, request_id, from_history=False):
    """Resolve a queue selection off the UI thread; ignore superseded selections."""
    app._pending_playlist_resolution = request_id

    def task():
        try:
            entry.resolve()
            error = None
        except Exception as exc:
            logger.warning("Playlist track could not load: %s", exc, exc_info=True)
            error = str(exc)

        def apply():
            if getattr(app, "_pending_playlist_resolution", None) == request_id:
                app._pending_playlist_resolution = None
            queue = list(getattr(app, "play_queue", []) or [])
            if (request_id != getattr(app, "_play_request_id", 0)
                    or index >= len(queue) or queue[index] is not entry):
                return False
            if error:
                _notice(app, f"Could not load playlist track: {error}")
                return False
            # Preserve the Previous-navigation flag across the async hop so
            # replaying a not-yet-resolved track from the back-stack doesn't
            # re-record it as a forward step.
            app.play_track(index, from_history=from_history)
            return False

        GLib.idle_add(apply)

    submit_daemon(task)


def uses_shuffled_playlist_order(app):
    # The queue already contains a random permutation of ALL playlist positions.
    # Re-randomizing at every next/prefetch would repeat entries and break prefetch.
    return any(
        isinstance(track, PlaylistQueueTrack) and track.source.shuffled
        for track in (getattr(app, "play_queue", []) or [])
    )
