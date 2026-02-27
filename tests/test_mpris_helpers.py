import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from services.mpris import MPRISService, play_mode_to_loop_shuffle, track_id_to_object_path


class _Player:
    def __init__(self):
        self._playing = False
        self._pos = 0.0
        self._dur = 0.0
        self._vol = 0.8

    def is_playing(self):
        return self._playing

    def get_position(self):
        return self._pos, self._dur

    def set_volume(self, vol):
        self._vol = float(vol)


def _variant_to_python(value):
    return value.unpack() if hasattr(value, "unpack") else value


def _make_app():
    app = SimpleNamespace()
    app.MODE_LOOP = 0
    app.MODE_ONE = 1
    app.MODE_SHUFFLE = 2
    app.MODE_SMART = 3
    app.MODE_ICONS = {}
    app.MODE_TOOLTIPS = {}
    app.play_mode = app.MODE_LOOP
    app.player = _Player()
    app.playing_track = None
    app.playing_track_id = None
    app.current_track_index = -1
    app.current_track_list = []
    app.shuffle_indices = []
    app.settings = {}
    app.schedule_save_settings = lambda: None
    app._generate_shuffle_list = lambda: setattr(app, "shuffle_indices", [0])
    app.backend = SimpleNamespace(get_artwork_url=lambda _track, _size: "")
    app._get_active_queue = lambda: list(app.current_track_list)
    return app


def test_track_id_to_object_path_sanitizes_tokens():
    assert track_id_to_object_path("123 abc/def") == "/com/hiresti/player/track/t_123_abc_def"
    assert track_id_to_object_path("") == "/com/hiresti/player/track/unknown"


def test_play_mode_mapping():
    assert play_mode_to_loop_shuffle(0) == ("Playlist", False)
    assert play_mode_to_loop_shuffle(1) == ("Track", False)
    assert play_mode_to_loop_shuffle(2) == ("Playlist", True)
    assert play_mode_to_loop_shuffle(3) == ("Playlist", True)


def test_mpris_metadata_and_playback_status_snapshot():
    app = _make_app()
    track = SimpleNamespace(
        id="42",
        name="Demo Song",
        artist=SimpleNamespace(name="Demo Artist"),
        album=SimpleNamespace(name="Demo Album"),
    )
    app.playing_track = track
    app.playing_track_id = track.id
    app.current_track_list = [track]
    app.current_track_index = 0
    app.player._dur = 185.0
    svc = MPRISService(app)

    metadata = svc._metadata_variant().unpack()
    assert _variant_to_python(metadata["mpris:trackid"]) == track_id_to_object_path("42")
    assert _variant_to_python(metadata["xesam:title"]) == "Demo Song"
    assert _variant_to_python(metadata["xesam:artist"]) == ["Demo Artist"]
    assert _variant_to_python(metadata["xesam:album"]) == "Demo Album"
    assert _variant_to_python(metadata["mpris:length"]) == 185_000_000

    assert svc._playback_status() == "Paused"
    app.player._playing = True
    assert svc._playback_status() == "Playing"


def test_mpris_property_setters_update_play_mode_and_volume():
    app = _make_app()
    svc = MPRISService(app)

    svc._apply_shuffle(True)
    assert app.play_mode == app.MODE_SHUFFLE

    svc._apply_loop_status("Track")
    assert app.play_mode == app.MODE_ONE

    svc._apply_shuffle(False)
    assert app.play_mode == app.MODE_ONE

    svc._apply_loop_status("Playlist")
    assert app.play_mode == app.MODE_LOOP

    svc._apply_volume(0.35)
    assert int(round(app.settings.get("volume", 0))) == 35

