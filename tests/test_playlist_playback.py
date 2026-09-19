import os
import sys
from concurrent.futures import ThreadPoolExecutor
from types import MethodType, SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from actions import (
    lyrics_playback_actions,
    playback_actions,
    playlist_playback,
    ui_actions,
)
from app import app_queue, app_search
from backend.tidal import TidalBackend
from models.playlist_queue import PlaylistQueue
from services import mpris, remote_dispatch


class Playlist:
    def __init__(self, total=100):
        self.id = "playlist-89"
        self.name = "Whole playlist"
        self.num_tracks = total
        self.num_videos = 7
        self._etag = "revision-1"
        self.calls = []
        self.error = None

    def tracks(self, limit, offset):
        self.calls.append((limit, offset))
        if self.error:
            raise self.error
        return [SimpleNamespace(id=str(i), name=f"Song {i}")
                for i in range(offset, min(offset + limit, self.num_tracks))]


def backend_for(playlist):
    backend = object.__new__(TidalBackend)
    backend.session = SimpleNamespace(playlist=lambda _pid: playlist)
    backend._call_with_session_recovery = lambda fn, **kwargs: fn()
    return backend


@pytest.fixture
def setup(monkeypatch):
    workers, callbacks = [], []
    monkeypatch.setattr(playlist_playback, "submit_daemon", workers.append)
    monkeypatch.setattr(playlist_playback.GLib, "idle_add", lambda fn, *args: callbacks.append(lambda: fn(*args)))
    # Select the last playlist position first, deterministically outside the first page.
    monkeypatch.setattr(playlist_playback.random, "shuffle", lambda entries: entries.reverse())
    playlist = Playlist()
    app = SimpleNamespace(
        backend=backend_for(playlist), current_remote_playlist=playlist,
        right_stack=SimpleNamespace(get_visible_child_name=lambda: "tracks"),
        current_track_list=list(range(20)), play_queue=[SimpleNamespace(id="old")],
        current_track_index=0, _play_request_id=0, _remote_pl_render_token=1,
        MODE_NORMAL=4, MODE_LOOP=0, MODE_ONE=1, MODE_SHUFFLE=2, MODE_SMART=3,
        play_mode=0, played=[], notices=[],
    )
    app._set_play_queue = MethodType(app_queue._set_play_queue, app)
    app._get_active_queue = MethodType(app_queue._get_active_queue, app)
    app.get_next_index = lambda direction=1: playback_actions.get_next_index(app, direction)

    def play(index, from_history=False):
        app.current_track_index = index
        app._play_request_id += 1
        app.played.append(index)

    app.play_track = play
    app.show_output_notice = lambda *args: app.notices.append(args)

    def flush():
        while callbacks:
            callbacks.pop(0)()

    return app, playlist, workers, flush


def test_shuffle_starts_from_unloaded_position_without_loading_whole_playlist(setup):
    app, playlist, workers, flush = setup
    ui_actions._on_shuffle_album_tracks(app)
    assert app.play_queue[0].id == "old"
    assert not app.played
    workers.pop(0)()
    assert playlist.calls == [(1, 99)]
    flush()
    assert len(app.play_queue) == 100
    assert app.play_queue[0].id == "99"
    assert app.played == [0]
    assert app.current_track_list == list(range(20))
    assert app.playback_source["obj"] is playlist
    assert sorted(entry.position for entry in app.play_queue) == list(range(100))


def test_play_uses_full_playlist_with_only_first_track_resolved(setup):
    app, playlist, workers, flush = setup
    ui_actions._on_play_album_tracks(app)
    workers.pop(0)()
    flush()
    assert playlist.calls == [(1, 0)]
    assert len(app.play_queue) == 100
    assert app.play_queue[0].id == "0"
    assert app.play_queue[-1].id is None


def test_repeated_shuffle_coalesces_pending_request(setup):
    app, playlist, workers, flush = setup
    ui_actions._on_shuffle_album_tracks(app)
    ui_actions._on_shuffle_album_tracks(app)
    assert len(workers) == 1
    workers.pop(0)()
    flush()
    assert app.played == [0]
    assert playlist.calls == [(1, 99)]


@pytest.mark.parametrize("cancel", ["playlist", "view", "queue", "play", "reopen"])
def test_superseded_start_never_replaces_current_playback(setup, cancel):
    app, _, workers, flush = setup
    ui_actions._on_shuffle_album_tracks(app)
    workers.pop(0)()
    if cancel == "playlist":
        app.current_remote_playlist = Playlist()
    elif cancel == "view":
        app.right_stack.get_visible_child_name = lambda: "collection"
    elif cancel == "queue":
        app._set_play_queue([SimpleNamespace(id="replacement")])
    elif cancel == "play":
        app.play_track(0)
    else:
        app._remote_pl_render_token += 1
    played = list(app.played)
    flush()
    assert app.played == played
    assert len(app.play_queue) == 1


def test_start_error_preserves_existing_queue_and_can_retry(setup):
    app, playlist, workers, flush = setup
    playlist.error = RuntimeError("Offline")
    ui_actions._on_shuffle_album_tracks(app)
    workers.pop(0)()
    flush()
    assert app.play_queue[0].id == "old"
    assert not app.played
    assert "Offline" in app.notices[-1][0]
    playlist.error = None
    ui_actions._on_shuffle_album_tracks(app)
    workers.pop(0)()
    flush()
    assert len(app.play_queue) == 100


def test_empty_playlist_does_not_replace_queue(setup):
    app, playlist, workers, flush = setup
    playlist.num_tracks = 0
    ui_actions._on_shuffle_album_tracks(app)
    workers.pop(0)()
    flush()
    assert not playlist.calls
    assert app.play_queue[0].id == "old"
    assert "no tracks" in app.notices[-1][0]


@pytest.mark.parametrize("mode", [0, 2, 3, 4])
def test_next_and_prefetch_follow_same_random_permutation_without_repeats(setup, mode):
    app, _, workers, flush = setup
    ui_actions._on_shuffle_album_tracks(app)
    workers.pop(0)()
    flush()
    app.play_mode = mode
    for expected in range(1, 100):
        assert app.get_next_index() == expected
        assert app.get_next_index() == expected
        playback_actions.on_next_track(app, object())
        assert app.played[-1] == expected
    assert len(set(app.played)) == 100


def test_prefetch_resolves_only_next_position_and_caches_real_stream_id(setup):
    app, playlist, workers, flush = setup
    ui_actions._on_shuffle_album_tracks(app)
    workers.pop(0)()
    flush()
    streams = []
    app.backend.quality = "LOSSLESS"
    app.backend.get_stream_url = lambda track: streams.append(track.id) or "https://audio/next"
    app.backend.get_artwork_url = lambda *_args: None
    lyrics_playback_actions._prefetch_next_track(app, 0)
    lyrics_playback_actions._prefetch_next_track(app, 0)
    assert playlist.calls == [(1, 99), (1, 98)]
    assert streams == ["98"]
    assert app.play_queue[1].name == "Song 98"
    assert app.stream_prefetch_cache["98"]["url"] == "https://audio/next"
    assert app.current_track_list == list(range(20))


def test_select_unloaded_queue_entry_defers_playback_until_resolved(setup):
    app, playlist, workers, flush = setup
    source = app.backend.get_playlist_playback_queue(playlist)
    app._set_play_queue(source.entries())
    lyrics_playback_actions.play_track(app, 75)
    assert not app.played
    assert not playlist.calls
    workers.pop(0)()
    flush()
    assert playlist.calls == [(1, 75)]
    assert app.played == [75]


@pytest.mark.parametrize("cancel", ["clear", "select", "replace"])
def test_unloaded_entry_cannot_play_after_cancellation(setup, cancel):
    app, playlist, workers, flush = setup
    app._set_play_queue(app.backend.get_playlist_playback_queue(playlist).entries())
    lyrics_playback_actions.play_track(app, 75)
    workers.pop(0)()
    if cancel == "clear":
        app.player = SimpleNamespace(stop=lambda: None)
        app.play_btn = None
        app.refresh_current_track_favorite_state = lambda: None
        app._refresh_queue_views = lambda: None
        app_queue.on_queue_clear_clicked(app)
    elif cancel == "select":
        app.play_track(0)
    else:
        app._set_play_queue([SimpleNamespace(id="new")])
    played = list(app.played)
    flush()
    assert app.played == played


def test_metadata_failure_does_not_play_placeholder(setup):
    app, playlist, workers, flush = setup
    app._set_play_queue(app.backend.get_playlist_playback_queue(playlist).entries())
    playlist.error = RuntimeError("Offline")
    lyrics_playback_actions.play_track(app, 75)
    workers.pop(0)()
    flush()
    assert not app.played
    assert app.current_track_index == 0
    assert "Offline" in app.notices[-1][0]


def test_playlist_change_rejects_shifted_positions():
    playlist = Playlist()
    source = backend_for(playlist).get_playlist_playback_queue(playlist)
    source.resolve(80)
    playlist._etag = "revision-2"
    with pytest.raises(ValueError, match="playlist has changed"):
        source.resolve(81)


def test_missing_playlist_position_is_not_cached():
    playlist = Playlist()
    source = backend_for(playlist).get_playlist_playback_queue(playlist)
    playlist.num_tracks = 2
    with pytest.raises(ValueError, match="unavailable"):
        source.resolve(80)
    assert source.entries()[80].resolved_track is None


def test_unknown_count_never_uses_visible_page_as_fallback():
    playlist = Playlist()
    playlist.num_tracks = None
    with pytest.raises(ValueError, match="count is unavailable"):
        backend_for(playlist).get_playlist_playback_queue(playlist)


def test_duplicate_song_ids_keep_their_distinct_playlist_positions():
    source = PlaylistQueue(2, lambda position: SimpleNamespace(id="same-song", position=position))
    assert source.resolve(0).position == 0
    assert source.resolve(1).position == 1


def test_concurrent_resolution_requests_only_one_copy():
    playlist = Playlist()
    source = backend_for(playlist).get_playlist_playback_queue(playlist)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tracks = list(pool.map(source.resolve, [75, 75]))
    assert tracks[0] is tracks[1]
    assert playlist.calls == [(1, 75)]


def test_local_album_shuffle_keeps_existing_behavior(setup):
    app, playlist, workers, _ = setup
    app.current_remote_playlist = None
    app.current_track_list = [SimpleNamespace(id=i) for i in range(30)]
    ui_actions._on_shuffle_album_tracks(app)
    assert not workers
    assert not playlist.calls
    assert [track.id for track in app.play_queue] == list(reversed(range(30)))
    assert app.played == [0]


def test_click_sorted_remote_track_preserves_selected_song_and_full_queue(setup):
    app, playlist, workers, flush = setup
    app.album_track_source = playlist.tracks(20, 0)
    app.current_track_list = list(reversed(app.album_track_source))
    playlist.calls.clear()
    app_search.on_track_selected(app, None, SimpleNamespace(get_index=lambda: 0))
    workers.pop(0)()
    flush()
    assert playlist.calls == [(1, 19)]
    assert len(app.play_queue) == 100
    assert app.played == [19]
    assert app.play_queue[19].id == "19"


def test_clicked_song_mismatch_does_not_play_shifted_position(setup):
    app, _, workers, flush = setup
    playlist_playback.start_playlist(app, start_position=10, track_id="different-song")
    workers.pop(0)()
    flush()
    assert not app.played
    assert app.play_queue[0].id == "old"
    assert "playlist has changed" in app.notices[-1][0]


@pytest.mark.parametrize("pending_type", ["start", "selection"])
def test_pause_cancels_pending_playlist_playback(setup, pending_type):
    app, playlist, workers, flush = setup
    paused = []
    app.player = SimpleNamespace(is_playing=lambda: True, pause=lambda: paused.append(True))
    if pending_type == "start":
        ui_actions._on_shuffle_album_tracks(app)
    else:
        app._set_play_queue(app.backend.get_playlist_playback_queue(playlist).entries())
        lyrics_playback_actions.play_track(app, 75)
    workers.pop(0)()
    playback_actions.on_play_pause(app, None)
    flush()
    assert paused == [True]
    assert not app.played


def test_metadata_resolution_rebinds_after_session_recovery():
    old_playlist, new_playlist = Playlist(), Playlist()
    backend = backend_for(old_playlist)
    source = backend.get_playlist_playback_queue(old_playlist)

    def recover_and_retry(fn, **kwargs):
        backend.session = SimpleNamespace(playlist=lambda _pid: new_playlist)
        return fn()

    backend._call_with_session_recovery = recover_and_retry
    assert source.resolve(75).id == "75"
    assert not old_playlist.calls
    assert new_playlist.calls == [(1, 75)]


@pytest.mark.parametrize("control", ["mpris_pause", "mpris_stop", "remote_stop", "remote_pause"])
def test_external_stop_or_pause_cancels_pending_start(setup, monkeypatch, control):
    app, _, workers, flush = setup
    ui_actions._on_shuffle_album_tracks(app)
    workers.pop(0)()
    app.player = SimpleNamespace(stop=lambda: None, pause=lambda: None, is_playing=lambda: False)
    if control.startswith("remote_"):
        monkeypatch.setattr(remote_dispatch, "_invoke_on_main", lambda app, fn: fn())
        monkeypatch.setattr(remote_dispatch, "_player_state_snapshot", lambda app: {})
        if control == "remote_stop":
            remote_dispatch._rpc_player_stop(app, {})
        else:
            remote_dispatch._rpc_player_pause(app, {})
    else:
        service = object.__new__(mpris.MPRISService)
        service.app = app
        service._is_playing = lambda: True
        service.sync_playback = lambda: None
        service.sync_position = lambda **kwargs: None
        if control == "mpris_pause":
            service._action_pause()
        else:
            service._action_stop()
    flush()
    assert not app.played


def _prev_app(play_mode, current, history):
    """Minimal app for exercising on_prev_track's back-stack logic."""
    played = []
    app = SimpleNamespace(
        current_track_list=list(range(100)),
        current_track_index=current,
        play_mode=play_mode,
        MODE_NORMAL=4, MODE_LOOP=0, MODE_ONE=1, MODE_SHUFFLE=2, MODE_SMART=3,
        _play_history=list(history),
        # A position past the restart threshold so Previous steps tracks
        # instead of rewinding the current one to 0.
        player=SimpleNamespace(get_position=lambda: (30.0, 240.0), seek=lambda *_a: None),
    )
    app.play_track = lambda index, from_history=False: played.append((index, from_history))
    return app, played


def test_previous_in_shuffle_returns_actually_played_track():
    # Shuffle order != queue order, so a positional current-1 would be wrong;
    # Previous must replay the track popped from the back-stack.
    app, played = _prev_app(play_mode=2, current=7, history=[3, 42])
    playback_actions.on_prev_track(app)
    assert played == [(42, True)]
    assert app._play_history == [3]


def test_previous_in_shuffle_falls_back_to_positional_when_history_empty():
    app, played = _prev_app(play_mode=2, current=7, history=[])
    playback_actions.on_prev_track(app)
    assert played == [(6, False)]


def test_previous_in_normal_mode_stays_positional():
    # Normal playback order equals queue order; leave it walking the list.
    app, played = _prev_app(play_mode=4, current=7, history=[3, 42])
    playback_actions.on_prev_track(app)
    assert played == [(6, False)]
    assert app._play_history == [3, 42]


def test_previous_skips_stale_history_entries():
    # Entries equal to the current index (or out of range) are discarded
    # rather than replaying the current track or crashing.
    app, played = _prev_app(play_mode=2, current=7, history=[5, 7, 999])
    playback_actions.on_prev_track(app)
    assert played == [(5, True)]
    assert app._play_history == []
