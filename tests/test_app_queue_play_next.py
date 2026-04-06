import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app_queue


def _make_track(track_id):
    return SimpleNamespace(id=str(track_id), name=f"Song {track_id}")


def _make_app():
    notices = []
    queue_events = []
    play_calls = []
    refresh_calls = []
    sync_calls = []
    app = SimpleNamespace()
    app.current_track_list = []
    app.play_queue = []
    app.current_track_index = -1
    app.playing_track = None
    app.playing_track_id = None
    app.current_playlist_id = None
    app._remote_queue_event_suppression = 0
    app.show_output_notice = lambda text, state="idle", timeout_ms=0: notices.append((text, state, timeout_ms))
    app.play_track = lambda index: play_calls.append(int(index))
    app._get_active_queue = lambda: list(app.play_queue) if app.play_queue else list(app.current_track_list)
    app._set_play_queue = lambda tracks: setattr(app, "play_queue", list(tracks))
    app._refresh_queue_views = lambda: refresh_calls.append(True)
    app._mpris_sync_metadata = lambda: sync_calls.append(True)
    app._remote_publish_queue_event = lambda reason="queue_changed": queue_events.append(str(reason))
    app._notices = notices
    app._queue_events = queue_events
    app._play_calls = play_calls
    app._refresh_calls = refresh_calls
    app._sync_calls = sync_calls
    return app


def test_get_current_track_view_tracks_prefers_sorted_playlist_tracks():
    app = _make_app()
    app.current_track_list = [_make_track("fallback")]
    app.current_playlist_id = "playlist-1"
    app.get_sorted_playlist_tracks = lambda playlist_id: [_make_track("a"), _make_track("b")]

    tracks = app_queue._get_current_track_view_tracks(app)

    assert [track.id for track in tracks] == ["a", "b"]


def test_on_play_next_track_clicked_without_playback_plays_single_track_now(monkeypatch):
    app = _make_app()
    track = _make_track("9")
    monkeypatch.setattr(app_queue.GLib, "idle_add", lambda fn, *args: fn(*args))

    app_queue.on_play_next_track_clicked(app, track)

    assert [item.id for item in app.play_queue] == ["9"]
    assert [item.id for item in app.current_track_list] == ["9"]
    assert app._play_calls == [0]
    assert app._notices == [("Playing now: Song 9", "ok", 2400)]


def test_on_play_next_current_tracks_clicked_inserts_playlist_tracks_after_current(monkeypatch):
    app = _make_app()
    queue = [_make_track("1"), _make_track("2"), _make_track("3")]
    playlist_tracks = [_make_track("9"), _make_track("10")]
    app.play_queue = list(queue)
    app.current_track_index = 1
    app.playing_track = queue[1]
    app.playing_track_id = queue[1].id
    app.current_playlist_id = "playlist-1"
    app.get_sorted_playlist_tracks = lambda playlist_id: list(playlist_tracks)
    monkeypatch.setattr(app_queue.GLib, "idle_add", lambda fn, *args: fn(*args))

    app_queue.on_play_next_current_tracks_clicked(app)

    assert [track.id for track in app.play_queue] == ["1", "2", "9", "10", "3"]
    assert app.current_track_index == 1
    assert app.playing_track_id == "2"
    assert app._queue_events == ["queue_inserted"]
    assert app._refresh_calls == [True]
    assert app._sync_calls == [True]
    assert app._notices == [("Added 2 tracks to play next", "ok", 2400)]
