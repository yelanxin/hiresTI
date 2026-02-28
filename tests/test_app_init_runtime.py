import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_init_paths_and_settings_migration_and_sanitize(tmp_path, monkeypatch):
    pytest.importorskip("gi")
    from app import app_init_runtime as mod

    cache_dir = tmp_path / "cache"
    config_dir = tmp_path / "config"
    cache_dir.mkdir()
    config_dir.mkdir()
    old = cache_dir / "settings.json"
    old.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(mod, "get_cache_dir", lambda: str(cache_dir))
    monkeypatch.setattr(mod, "get_config_dir", lambda: str(config_dir))
    monkeypatch.setattr(mod, "TidalBackend", lambda: SimpleNamespace(user=None))
    monkeypatch.setattr(
        mod,
        "load_settings",
        lambda _path: {
            "viz_sync_offset_ms": 999,
            "viz_sync_device_offsets": {"ok": 120, "bad_type": "x", "too_big": 260, 1: 10},
            "play_mode": 999,
        },
    )

    app = SimpleNamespace()
    app.MODE_LOOP = 0
    app.MODE_ICONS = {0: "loop", 1: "one", 2: "shuffle", 3: "smart"}

    mod._init_paths_and_settings(app)

    assert app.settings_file == str(config_dir / "settings.json")
    assert not old.exists()
    assert (config_dir / "settings.json").exists()
    assert app.settings["viz_sync_offset_ms"] == 0
    assert app.settings["viz_sync_device_offsets"] == {"ok": 120}
    assert app.play_mode == app.MODE_LOOP
    assert app.shuffle_indices == []
    assert app._account_scope == "guest"


def test_init_audio_and_data_services_sets_up_player_and_cache(tmp_path, monkeypatch):
    pytest.importorskip("gi")
    from app import app_init_runtime as mod

    class _Player:
        def __init__(self):
            self.visual_sync_offset_ms = None
            self.latency_calls = []

        def set_alsa_latency(self, buf_ms, lat_ms):
            self.latency_calls.append((buf_ms, lat_ms))

    class _Mgr:
        def __init__(self, base_dir, scope_key):
            self.base_dir = base_dir
            self.scope_key = scope_key

    player = _Player()
    monkeypatch.setattr(mod, "create_audio_engine", lambda **kwargs: player)
    monkeypatch.setattr(mod, "LyricsManager", lambda: "lyrics_mgr")
    monkeypatch.setattr(mod, "HistoryManager", _Mgr)
    monkeypatch.setattr(mod, "PlaylistManager", _Mgr)

    root = tmp_path / "cache"
    root.mkdir()
    app = SimpleNamespace()
    app._cache_root = str(root)
    app._account_scope = "guest"
    app.settings = {
        "viz_sync_device_offsets": {"dev_a": 10},
        "viz_sync_offset_ms": 40,
        "latency_profile": "Low Latency (40ms)",
        "audio_cache_tracks": 7,
    }
    app.LATENCY_MAP = {"Low Latency (40ms)": (40, 40), "Standard (100ms)": (100, 100)}
    app.on_next_track = lambda *a, **k: None
    app.update_tech_label = lambda *a, **k: None
    app.on_spectrum_data = lambda *a, **k: None
    app.on_viz_sync_offset_update = lambda *a, **k: None
    called = []
    app._schedule_cache_maintenance = lambda: called.append("scheduled")

    mod._init_audio_and_data_services(app)

    assert app.player is player
    assert app._viz_sync_device_key is None
    assert app._viz_sync_offsets == {"dev_a": 10}
    assert app._viz_sync_last_saved_ms == 40
    assert app.player.latency_calls == [(40, 40)]
    assert app.player.visual_sync_offset_ms == 40
    assert app.settings["viz_sync_offset_ms"] == 40
    assert app.lyrics_mgr == "lyrics_mgr"
    assert isinstance(app.history_mgr, _Mgr)
    assert isinstance(app.playlist_mgr, _Mgr)
    assert app.audio_cache_tracks == 7
    assert os.path.isdir(app.cache_dir)
    assert os.path.isdir(app.audio_cache_dir)
    assert called == ["scheduled"]


def test_init_runtime_calls_stages_in_order(monkeypatch):
    pytest.importorskip("gi")
    from app import app_init_runtime as mod

    calls = []
    monkeypatch.setattr(mod.GLib, "set_application_name", lambda name: calls.append(("app_name", name)))
    monkeypatch.setattr(mod.GLib, "set_prgname", lambda name: calls.append(("prg", name)))
    monkeypatch.setattr(mod, "_init_paths_and_settings", lambda self: calls.append("paths"))
    monkeypatch.setattr(mod, "_init_audio_and_data_services", lambda self: calls.append("audio"))
    monkeypatch.setattr(mod, "_init_runtime_state", lambda self: calls.append("state"))
    app = SimpleNamespace()
    app._detect_app_version = lambda: "1.2.3"
    app._init_remote_control_state = lambda: calls.append("remote")

    mod.init_runtime(app)

    assert app.app_version == "1.2.3"
    assert calls == [
        ("app_name", "HiresTI"),
        ("prg", "HiresTI"),
        "paths",
        "audio",
        "state",
        "remote",
    ]
