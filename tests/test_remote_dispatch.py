import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.remote_dispatch import dispatch_rpc


def _make_track(track_id, title, artist_name, album_name, duration=180):
    artist = SimpleNamespace(id=f"artist-{track_id}", name=artist_name)
    album = SimpleNamespace(id=f"album-{track_id}", name=album_name, title=album_name, cover=f"cover-{track_id}")
    return SimpleNamespace(
        id=str(track_id),
        name=title,
        title=title,
        artist=artist,
        album=album,
        duration=duration,
        cover=f"track-cover-{track_id}",
    )


class _Player:
    def __init__(self):
        self._playing = False
        self._position = 12.5
        self._duration = 245.0
        self.seek_calls = []
        self.stop_calls = 0

    def is_playing(self):
        return self._playing

    def get_position(self):
        return (self._position, self._duration)

    def play(self):
        self._playing = True

    def pause(self):
        self._playing = False

    def stop(self):
        self._playing = False
        self.stop_calls += 1

    def seek(self, value):
        self._position = float(value)
        self.seek_calls.append(float(value))


class _Button:
    def __init__(self):
        self.icon_name = None

    def set_icon_name(self, icon_name):
        self.icon_name = icon_name


def _make_app():
    track1 = _make_track("1", "Song A", "Artist One", "Album Prime")
    track2 = _make_track("2", "Song B", "Artist Two", "Album Prime")
    track3 = _make_track("3", "Song C", "Artist Three", "Album Second")
    player = _Player()

    class _Session:
        def __init__(self):
            self._track_map = {track.id: track for track in (track1, track2, track3)}

        def check_login(self):
            return True

        def track(self, track_id):
            return self._track_map[str(track_id)]

    backend = SimpleNamespace(
        session=_Session(),
        search_items=lambda query: {
            "artists": [],
            "albums": [],
            "tracks": [track1, track2, track3] if "song" in query.lower() else [track1],
        },
    )

    app = SimpleNamespace()
    app.app_version = "1.3.2"
    app.settings = {
        "volume": 66,
        "remote_api_enabled": True,
        "remote_api_access_mode": "lan",
        "remote_api_port": 18473,
        "remote_api_bind_host": "0.0.0.0",
    }
    app.play_mode = 0
    app.MODE_LOOP = 0
    app.MODE_ONE = 1
    app.MODE_SHUFFLE = 2
    app.MODE_SMART = 3
    app.player = player
    app.play_btn = _Button()
    app.backend = backend
    app.play_queue = [track1, track2]
    app.current_track_index = 0
    app.current_index = 0
    app.playing_track = track1
    app.playing_track_id = track1.id
    app._remote_invoke_on_main = lambda fn, *args, **kwargs: fn(*args)
    app._get_active_queue = lambda: list(app.play_queue)
    app._set_play_queue = lambda tracks: setattr(app, "play_queue", list(tracks))
    app._mpris_sync_metadata = lambda *a, **k: None
    app._mpris_sync_playback = lambda *a, **k: None
    app._mpris_sync_position = lambda *a, **k: None
    app._mpris_sync_all = lambda *a, **k: None
    app._mpris_emit_seeked = lambda *a, **k: None
    app._refresh_queue_views = lambda: None
    app.get_remote_api_endpoint = lambda: "http://0.0.0.0:18473/rpc"

    def play_track(index):
        app.current_track_index = int(index)
        app.current_index = int(index)
        app.playing_track = app.play_queue[index]
        app.playing_track_id = app.playing_track.id
        app.player.play()

    def on_play_pause(_btn):
        if app.player.is_playing():
            app.player.pause()
        else:
            app.player.play()

    def on_next_track(_btn):
        nxt = (app.current_track_index + 1) % len(app.play_queue)
        play_track(nxt)

    def on_prev_track(_btn):
        prev = (app.current_track_index - 1) % len(app.play_queue)
        play_track(prev)

    def on_queue_clear_clicked(_btn):
        app.play_queue = []
        app.current_track_index = -1
        app.playing_track = None
        app.playing_track_id = None
        app.player.stop()

    def on_queue_remove_track_clicked(index):
        app.play_queue.pop(index)
        if not app.play_queue:
            on_queue_clear_clicked(None)

    def _remote_replace_queue(tracks, autoplay, start_index):
        app.play_queue = list(tracks)
        if autoplay:
            play_track(start_index or 0)
        else:
            app.current_track_index = 0 if tracks else -1
            app.playing_track = None
            app.playing_track_id = None
            app.player.stop()
        return {"queue_size": len(app.play_queue), "autoplay": bool(autoplay), "start_index": int(start_index or 0)}

    def _remote_append_queue(tracks):
        app.play_queue.extend(list(tracks))
        return {"queue_size": len(app.play_queue), "added": len(list(tracks))}

    app.play_track = play_track
    app.on_play_pause = on_play_pause
    app.on_next_track = on_next_track
    app.on_prev_track = on_prev_track
    app.on_queue_clear_clicked = on_queue_clear_clicked
    app.on_queue_remove_track_clicked = on_queue_remove_track_clicked
    app._remote_replace_queue = _remote_replace_queue
    app._remote_append_queue = _remote_append_queue
    return app


def test_player_get_state_returns_current_track_and_queue():
    app = _make_app()

    result = dispatch_rpc(app, "player.get_state")

    assert result["track"]["id"] == "1"
    assert result["queue_size"] == 2
    assert result["volume_percent"] == 66
    assert len(result["queue"]) == 2


def test_queue_replace_with_track_ids_resolves_ids_and_updates_queue():
    app = _make_app()

    result = dispatch_rpc(
        app,
        "queue.replace_with_track_ids",
        {"track_ids": ["2", "3"], "autoplay": False, "start_index": 0},
    )

    assert [track.id for track in app.play_queue] == ["2", "3"]
    assert result["queue_size"] == 2
    assert result["missing_ids"] == []
    assert app.player.stop_calls == 1


def test_search_match_tracks_prefers_title_and_artist_match():
    app = _make_app()

    result = dispatch_rpc(
        app,
        "search.match_tracks",
        {"items": [{"title": "Song A", "artist": "Artist One"}]},
    )

    assert result["matched_count"] == 1
    assert result["results"][0]["matched"] is True
    assert result["results"][0]["track"]["id"] == "1"
