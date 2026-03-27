import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app_ui_loop
from actions import lyrics_playback_actions


class _Player:
    def __init__(self, position=10.0, duration=180.0, playing=True):
        self.position = float(position)
        self.duration = float(duration)
        self.playing = bool(playing)
        self.get_position_calls = 0

    def is_playing(self):
        return self.playing

    def get_position(self):
        self.get_position_calls += 1
        return self.position, self.duration


class _Scale:
    def __init__(self, value=0.0):
        self.value = float(value)
        self.range = (0.0, 0.0)

    def set_range(self, lower, upper):
        self.range = (float(lower), float(upper))

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = float(value)


class _Label:
    def __init__(self):
        self.text = None

    def set_text(self, value):
        self.text = str(value)


def _make_loop_app(*, playing=True, overlay_open=False):
    player = _Player(playing=playing)
    return SimpleNamespace(
        player=player,
        playing_track_id="track-1",
        _seek_user_interacting=False,
        _viz_current_page="spectrum",
        _is_viz_surface_visible=lambda: False,
        is_now_playing_overlay_open=lambda: bool(overlay_open),
    )


def _make_update_app(*, playing=True, overlay_open=False):
    player = _Player(position=10.0, duration=180.0, playing=playing)
    return SimpleNamespace(
        player=player,
        play_btn=None,
        scale=_Scale(value=10.0),
        lbl_current_time=_Label(),
        lbl_total_time=_Label(),
        is_programmatic_update=False,
        _seek_user_interacting=False,
        _viz_current_page="spectrum",
        _is_viz_surface_visible=lambda: False,
        is_now_playing_overlay_open=lambda: bool(overlay_open),
        _ui_cached_pd=(10.0, 180.0),
        _ui_last_pos_poll_ts=100.0,
        _ui_last_scale_max=180.0,
        _last_playing_ui_state=bool(playing),
        _last_sec=10,
    )


def test_hidden_playing_ui_loop_uses_slower_interval():
    app = _make_loop_app(playing=True, overlay_open=False)

    assert app_ui_loop._get_ui_loop_interval_ms(app) == 280


def test_overlay_open_keeps_ui_loop_faster():
    app = _make_loop_app(playing=True, overlay_open=True)

    assert app_ui_loop._get_ui_loop_interval_ms(app) == 90


def test_update_ui_loop_hidden_playing_reuses_recent_cached_position(monkeypatch):
    app = _make_update_app(playing=True, overlay_open=False)
    monkeypatch.setattr(
        lyrics_playback_actions.GLib,
        "get_monotonic_time",
        lambda: int(100.2 * 1_000_000.0),
    )

    assert lyrics_playback_actions.update_ui_loop(app) is True
    assert app.player.get_position_calls == 0
    assert app.scale.get_value() == pytest.approx(10.2)


def test_update_ui_loop_skips_overlay_sync_when_overlay_closed(monkeypatch):
    app = _make_update_app(playing=True, overlay_open=False)
    app._sync_now_playing_overlay_state = lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected overlay sync"))
    monkeypatch.setattr(
        lyrics_playback_actions.GLib,
        "get_monotonic_time",
        lambda: int(100.2 * 1_000_000.0),
    )

    assert lyrics_playback_actions.update_ui_loop(app) is True
