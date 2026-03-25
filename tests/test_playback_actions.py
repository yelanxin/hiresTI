import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from types import SimpleNamespace

from actions import playback_actions


class _Player:
    def __init__(self):
        self.position = 0.0
        self.duration = 180.0
        self.seek_calls = []

    def get_position(self):
        return (self.position, self.duration)

    def seek(self, value):
        self.position = float(value)
        self.seek_calls.append(float(value))


def _make_app():
    app = SimpleNamespace()
    app.MODE_LOOP = 0
    app.MODE_ONE = 1
    app.MODE_SHUFFLE = 2
    app.MODE_SMART = 3
    app.play_mode = app.MODE_LOOP
    app.current_track_list = [1, 2, 3, 4]
    app.current_track_index = 1
    app.shuffle_indices = []
    app.player = _Player()
    app.play_track_calls = []
    app._generate_shuffle_list = lambda: setattr(app, "shuffle_indices", [0, 2, 3])
    app.play_track = lambda index: app.play_track_calls.append(int(index))
    return app


def test_get_next_index_loop_forward():
    app = _make_app()
    app.play_mode = app.MODE_LOOP
    assert playback_actions.get_next_index(app, 1) == 2


def test_get_next_index_loop_backward_wrap():
    app = _make_app()
    app.play_mode = app.MODE_LOOP
    app.current_track_index = 0
    assert playback_actions.get_next_index(app, -1) == 3


def test_get_next_index_invalid_current_recovers():
    app = _make_app()
    app.current_track_index = -1
    assert playback_actions.get_next_index(app, 1) == 1


def test_get_next_index_shuffle_not_same_track():
    app = _make_app()
    app.play_mode = app.MODE_SHUFFLE
    app.current_track_index = 2
    for _ in range(30):
        next_idx = playback_actions.get_next_index(app, 1)
        assert 0 <= next_idx < len(app.current_track_list)
        assert next_idx != app.current_track_index


def test_on_prev_track_within_5_seconds_restarts_current_track():
    app = _make_app()
    app.player.position = 4.9
    seeked = []
    synced = []
    remote = []
    app._mpris_emit_seeked = lambda value: seeked.append(float(value))
    app._mpris_sync_position = lambda force=False: synced.append(bool(force))
    app._remote_publish_playback_event = lambda reason: remote.append(str(reason))

    playback_actions.on_prev_track(app)

    assert app.player.seek_calls == [0.0]
    assert app.play_track_calls == []
    assert seeked == [0.0]
    assert synced == [True]
    assert remote == ["seek"]


def test_on_prev_track_at_5_seconds_still_restarts_current_track():
    app = _make_app()
    app.player.position = 5.0

    playback_actions.on_prev_track(app)

    assert app.player.seek_calls == [0.0]
    assert app.play_track_calls == []


def test_on_prev_track_after_5_seconds_goes_to_previous_track():
    app = _make_app()
    app.player.position = 5.1

    playback_actions.on_prev_track(app)

    assert app.player.seek_calls == []
    assert app.play_track_calls == [0]


def test_on_prev_track_second_click_within_2_seconds_goes_to_previous_track(monkeypatch):
    app = _make_app()
    app.player.position = 4.9
    now = {"value": 100.0}
    monkeypatch.setattr(playback_actions.time, "monotonic", lambda: now["value"])

    playback_actions.on_prev_track(app)
    now["value"] = 101.5

    playback_actions.on_prev_track(app)

    assert app.player.seek_calls == [0.0]
    assert app.play_track_calls == [0]


def test_on_prev_track_second_click_after_2_seconds_restarts_current_track_again(monkeypatch):
    app = _make_app()
    app.player.position = 4.9
    now = {"value": 100.0}
    monkeypatch.setattr(playback_actions.time, "monotonic", lambda: now["value"])

    playback_actions.on_prev_track(app)
    now["value"] = 102.1

    playback_actions.on_prev_track(app)

    assert app.player.seek_calls == [0.0, 0.0]
    assert app.play_track_calls == []
