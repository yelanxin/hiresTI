from types import SimpleNamespace

from actions import playback_actions


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
    app._generate_shuffle_list = lambda: setattr(app, "shuffle_indices", [0, 2, 3])
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
