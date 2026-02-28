import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app_remote_control


def _make_track(track_id):
    return SimpleNamespace(id=str(track_id), name=f"Song {track_id}")


def _make_app():
    track1 = _make_track("1")
    track2 = _make_track("2")
    track3 = _make_track("3")
    app = SimpleNamespace()
    app.play_queue = [track1, track2, track3]
    app.current_track_index = 1
    app.playing_track = track2
    app.playing_track_id = track2.id
    app._remote_queue_event_suppression = 0
    app._get_active_queue = lambda: list(app.play_queue)
    app._set_play_queue = lambda tracks: setattr(app, "play_queue", list(tracks))
    app._mpris_sync_metadata = lambda *a, **k: None
    app._remote_publish_queue_event = lambda *a, **k: None
    app._remote_insert_queue_at = lambda tracks, index: app_remote_control._remote_insert_queue_at(app, tracks, index)
    return app


def test_remote_move_queue_item_keeps_current_track_selected():
    app = _make_app()

    result = app_remote_control._remote_move_queue_item(app, 1, 2)

    assert [track.id for track in app.play_queue] == ["1", "3", "2"]
    assert app.current_track_index == 2
    assert app.playing_track_id == "2"
    assert result["to_index"] == 2


def test_remote_insert_queue_next_inserts_after_current_track():
    app = _make_app()
    new_track = _make_track("9")

    result = app_remote_control._remote_insert_queue_next(app, [new_track])

    assert [track.id for track in app.play_queue] == ["1", "2", "9", "3"]
    assert app.current_track_index == 1
    assert result["insert_index"] == 2
    assert result["inserted"] == 1


def test_remote_insert_queue_next_handles_first_track_index_zero():
    app = _make_app()
    app.current_track_index = 0
    app.playing_track = app.play_queue[0]
    app.playing_track_id = app.playing_track.id
    new_track = _make_track("9")

    result = app_remote_control._remote_insert_queue_next(app, [new_track])

    assert [track.id for track in app.play_queue] == ["1", "9", "2", "3"]
    assert result["insert_index"] == 1


def test_remote_move_queue_item_handles_first_track_index_zero():
    app = _make_app()
    app.current_track_index = 0
    app.playing_track = app.play_queue[0]
    app.playing_track_id = app.playing_track.id

    result = app_remote_control._remote_move_queue_item(app, 0, 2)

    assert [track.id for track in app.play_queue] == ["2", "3", "1"]
    assert app.current_track_index == 2
    assert result["current_index"] == 2


def test_display_remote_api_host_prefers_detected_lan_ip_for_wildcard_bind(monkeypatch):
    app = SimpleNamespace(settings={"remote_api_access_mode": "lan", "remote_api_bind_host": "0.0.0.0"})
    app._effective_remote_api_host = lambda: app_remote_control._effective_remote_api_host(app)
    app._display_remote_api_host = lambda: app_remote_control._display_remote_api_host(app)
    monkeypatch.setattr(app_remote_control, "_discover_non_loopback_ipv4", lambda: "192.168.1.23")

    assert app_remote_control._display_remote_api_host(app) == "192.168.1.23"
    assert app_remote_control.get_remote_mcp_endpoint(app) == "http://192.168.1.23:18473/mcp"
    assert app_remote_control.get_remote_api_endpoint(app) == "http://192.168.1.23:18473/rpc"


def test_display_remote_api_host_keeps_explicit_bind_host(monkeypatch):
    app = SimpleNamespace(settings={"remote_api_access_mode": "lan", "remote_api_bind_host": "192.168.50.10"})
    app._effective_remote_api_host = lambda: app_remote_control._effective_remote_api_host(app)
    app._display_remote_api_host = lambda: app_remote_control._display_remote_api_host(app)
    monkeypatch.setattr(app_remote_control, "_discover_non_loopback_ipv4", lambda: "192.168.1.23")

    assert app_remote_control._display_remote_api_host(app) == "192.168.50.10"
