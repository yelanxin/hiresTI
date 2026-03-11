import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_init_paths_and_settings_migration_and_sanitize(tmp_path, monkeypatch):
    pytest.importorskip("gi")
    from app import app_init_runtime as mod
    from core.settings import normalize_settings

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
        lambda _path: normalize_settings(
            {
                "viz_sync_offset_ms": 999,
                "viz_sync_device_offsets": {"ok": 120, "bad_type": "x", "too_big": 260, 1: 10},
                "play_mode": 999,
                "dsp_order": ["peq", "lv2_0", "lv2_1", "tube", "convolver", "tape", "widener"],
                "dsp_lv2_slots": [
                    {"slot_id": "lv2_0", "uri": "http://example.com/plugin", "enabled": True, "port_values": {}},
                    {"slot_id": "lv2_1", "uri": "http://example.com/plugin", "enabled": True, "port_values": {}},
                ],
            }
        ),
    )

    app = SimpleNamespace()
    app.MODE_LOOP = 0
    app.MODE_ICONS = {0: "loop", 1: "one", 2: "shuffle", 3: "smart"}

    mod._init_paths_and_settings(app)

    assert app.settings_file == str(config_dir / "settings.json")
    assert app._lv2_plugin_cache_file == str(cache_dir / "lv2_plugins.json")
    assert not old.exists()
    assert (config_dir / "settings.json").exists()
    assert app.settings["viz_sync_offset_ms"] == 0
    assert app.settings["viz_sync_device_offsets"] == {"ok": 120}
    assert app.settings["dsp_lv2_slots"] == [
        {"slot_id": "lv2_0", "uri": "http://example.com/plugin", "enabled": True, "port_values": {}}
    ]
    assert app.settings["dsp_order"] == ["peq", "lv2_0", "tube", "convolver", "tape", "widener"]
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
            self.realtime_priority_calls = []
            self.dsp_enabled_calls = []
            self.dsp_order_calls = []
            self.peq_enabled_calls = []
            self.eq_band_calls = []
            self.load_convolver_calls = []
            self.set_convolver_enabled_calls = []
            self.limiter_threshold_calls = []
            self.limiter_ratio_calls = []
            self.limiter_enabled_calls = []
            self.tube_drive_calls = []
            self.tube_bias_calls = []
            self.tube_sag_calls = []
            self.tube_air_calls = []
            self.tube_enabled_calls = []
            self.widener_width_calls = []
            self.widener_enabled_calls = []
            self.widener_bass_freq_calls = []
            self.widener_bass_amount_calls = []

        def set_alsa_latency(self, buf_ms, lat_ms):
            self.latency_calls.append((buf_ms, lat_ms))

        def set_alsa_mmap_realtime_priority(self, priority):
            self.realtime_priority_calls.append(int(priority))

        def set_dsp_order(self, order):
            self.dsp_order_calls.append(list(order))
            return True

        def set_dsp_enabled(self, enabled):
            self.dsp_enabled_calls.append(bool(enabled))
            return True

        def set_peq_enabled(self, enabled):
            self.peq_enabled_calls.append(bool(enabled))
            return True

        def set_eq_band(self, idx, value):
            self.eq_band_calls.append((int(idx), float(value)))
            return True

        def load_convolver_ir(self, path):
            self.load_convolver_calls.append(str(path))
            return True

        def set_convolver_enabled(self, enabled):
            self.set_convolver_enabled_calls.append(bool(enabled))
            return True

        def set_limiter_threshold(self, threshold):
            self.limiter_threshold_calls.append(float(threshold))
            return True

        def set_limiter_ratio(self, ratio):
            self.limiter_ratio_calls.append(float(ratio))
            return True

        def set_limiter_enabled(self, enabled):
            self.limiter_enabled_calls.append(bool(enabled))
            return True

        def set_tube_drive(self, drive):
            self.tube_drive_calls.append(int(drive))
            return True

        def set_tube_bias(self, bias):
            self.tube_bias_calls.append(int(bias))
            return True

        def set_tube_sag(self, sag):
            self.tube_sag_calls.append(int(sag))
            return True

        def set_tube_air(self, air):
            self.tube_air_calls.append(int(air))
            return True

        def set_tube_enabled(self, enabled):
            self.tube_enabled_calls.append(bool(enabled))
            return True

        def set_widener_width(self, width):
            self.widener_width_calls.append(int(width))
            return True

        def set_widener_enabled(self, enabled):
            self.widener_enabled_calls.append(bool(enabled))
            return True

        def set_widener_bass_mono_freq(self, freq):
            self.widener_bass_freq_calls.append(int(freq))
            return True

        def set_widener_bass_mono_amount(self, amount):
            self.widener_bass_amount_calls.append(int(amount))
            return True

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
        "alsa_mmap_realtime_priority": "High (70)",
        "latency_profile": "Low Latency (40ms)",
        "audio_cache_tracks": 7,
        "dsp_peq_enabled": True,
        "dsp_peq_bands": [1.5, -2.0, 0.0, 3.0, 0.5, -1.0, 0.0, 2.5, 1.0, -0.5],
        "dsp_enabled": False,
        "dsp_order": ["tube", "peq", "widener", "convolver", "tape"],
    }
    app.LATENCY_MAP = {"Low Latency (40ms)": (40, 40), "Standard (100ms)": (100, 100)}
    app.ALSA_MMAP_REALTIME_PRIORITY_MAP = {
        "Off": 0,
        "Recommended (60)": 60,
        "High (70)": 70,
    }
    app.ALSA_MMAP_REALTIME_PRIORITY_DEFAULT = "Recommended (60)"
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
    assert app.player.realtime_priority_calls == [70]
    assert app.player.latency_calls == [(40, 40)]
    assert app.player.dsp_order_calls == [["tube", "peq", "widener", "convolver", "tape"]]
    assert app.player.eq_band_calls == [
        (0, 1.5), (1, -2.0), (2, 0.0), (3, 3.0), (4, 0.5),
        (5, -1.0), (6, 0.0), (7, 2.5), (8, 1.0), (9, -0.5),
    ]
    assert app.player.peq_enabled_calls == [True]
    assert app.player.dsp_enabled_calls == [False]
    assert app.player.visual_sync_offset_ms == 40
    assert app.settings["viz_sync_offset_ms"] == 40
    assert app.lyrics_mgr == "lyrics_mgr"
    assert isinstance(app.history_mgr, _Mgr)
    assert isinstance(app.playlist_mgr, _Mgr)
    assert app.audio_cache_tracks == 7
    assert os.path.isdir(app.cache_dir)
    assert os.path.isdir(app.audio_cache_dir)
    assert player.load_convolver_calls == []
    assert player.set_convolver_enabled_calls == []
    assert player.limiter_threshold_calls == [0.85]
    assert player.limiter_ratio_calls == [20.0]
    assert player.limiter_enabled_calls == [False]
    assert player.tube_drive_calls == [28]
    assert player.tube_bias_calls == [55]
    assert player.tube_sag_calls == [18]
    assert player.tube_air_calls == [52]
    assert player.tube_enabled_calls == [False]
    assert player.widener_width_calls == [125]
    assert player.widener_bass_freq_calls == [120]
    assert player.widener_bass_amount_calls == [100]
    assert player.widener_enabled_calls == [False]
    assert called == ["scheduled"]


def test_init_runtime_state_restores_saved_peq_values():
    pytest.importorskip("gi")
    from app import app_init_runtime as mod

    app = SimpleNamespace(
        settings={
            "device": "Default Output",
            "search_history": ["a", "b"],
            "dsp_peq_bands": [1, 2, 3],
        },
        MODE_LOOP=0,
        _init_ui_refs=lambda: None,
    )

    mod._init_runtime_state(app)

    assert app.eq_band_values == [1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_init_audio_and_data_services_restores_saved_convolver(tmp_path, monkeypatch):
    pytest.importorskip("gi")
    from app import app_init_runtime as mod

    class _Player:
        def __init__(self):
            self.visual_sync_offset_ms = None
            self.latency_calls = []
            self.realtime_priority_calls = []
            self.dsp_enabled_calls = []
            self.dsp_order_calls = []
            self.load_convolver_calls = []
            self.set_convolver_enabled_calls = []
            self.limiter_threshold_calls = []
            self.limiter_ratio_calls = []
            self.limiter_enabled_calls = []
            self.tube_drive_calls = []
            self.tube_bias_calls = []
            self.tube_sag_calls = []
            self.tube_air_calls = []
            self.tube_enabled_calls = []
            self.widener_width_calls = []
            self.widener_enabled_calls = []
            self.widener_bass_freq_calls = []
            self.widener_bass_amount_calls = []

        def set_alsa_latency(self, buf_ms, lat_ms):
            self.latency_calls.append((buf_ms, lat_ms))

        def set_alsa_mmap_realtime_priority(self, priority):
            self.realtime_priority_calls.append(int(priority))

        def set_dsp_order(self, order):
            self.dsp_order_calls.append(list(order))
            return True

        def set_dsp_enabled(self, enabled):
            self.dsp_enabled_calls.append(bool(enabled))
            return True

        def load_convolver_ir(self, path):
            self.load_convolver_calls.append(str(path))
            return True

        def set_convolver_enabled(self, enabled):
            self.set_convolver_enabled_calls.append(bool(enabled))
            return True

        def set_limiter_threshold(self, threshold):
            self.limiter_threshold_calls.append(float(threshold))
            return True

        def set_limiter_ratio(self, ratio):
            self.limiter_ratio_calls.append(float(ratio))
            return True

        def set_limiter_enabled(self, enabled):
            self.limiter_enabled_calls.append(bool(enabled))
            return True

        def set_tube_drive(self, drive):
            self.tube_drive_calls.append(int(drive))
            return True

        def set_tube_bias(self, bias):
            self.tube_bias_calls.append(int(bias))
            return True

        def set_tube_sag(self, sag):
            self.tube_sag_calls.append(int(sag))
            return True

        def set_tube_air(self, air):
            self.tube_air_calls.append(int(air))
            return True

        def set_tube_enabled(self, enabled):
            self.tube_enabled_calls.append(bool(enabled))
            return True

        def set_widener_width(self, width):
            self.widener_width_calls.append(int(width))
            return True

        def set_widener_enabled(self, enabled):
            self.widener_enabled_calls.append(bool(enabled))
            return True

        def set_widener_bass_mono_freq(self, freq):
            self.widener_bass_freq_calls.append(int(freq))
            return True

        def set_widener_bass_mono_amount(self, amount):
            self.widener_bass_amount_calls.append(int(amount))
            return True

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
        "viz_sync_device_offsets": {},
        "viz_sync_offset_ms": 0,
        "alsa_mmap_realtime_priority": "High (70)",
        "latency_profile": "Low Latency (40ms)",
        "audio_cache_tracks": 7,
        "dsp_convolver_path": "/tmp/room.wav",
        "dsp_convolver_enabled": True,
        "dsp_tube_drive": 36,
        "dsp_tube_bias": 63,
        "dsp_tube_sag": 24,
        "dsp_tube_air": 47,
        "dsp_tube_enabled": True,
        "dsp_widener_width": 140,
        "dsp_widener_bass_mono_freq": 90,
        "dsp_widener_bass_mono_amount": 75,
        "dsp_widener_enabled": True,
        "dsp_limiter_threshold": 78,
        "dsp_limiter_ratio": 12,
        "dsp_limiter_enabled": True,
    }
    app.LATENCY_MAP = {"Low Latency (40ms)": (40, 40), "Standard (100ms)": (100, 100)}
    app.ALSA_MMAP_REALTIME_PRIORITY_MAP = {
        "Off": 0,
        "Recommended (60)": 60,
        "High (70)": 70,
    }
    app.ALSA_MMAP_REALTIME_PRIORITY_DEFAULT = "Recommended (60)"
    app.on_next_track = lambda *a, **k: None
    app.update_tech_label = lambda *a, **k: None
    app.on_spectrum_data = lambda *a, **k: None
    app.on_viz_sync_offset_update = lambda *a, **k: None
    app._schedule_cache_maintenance = lambda: None

    mod._init_audio_and_data_services(app)

    assert player.dsp_order_calls == [["peq", "convolver", "tape", "tube", "widener"]]
    assert player.load_convolver_calls == ["/tmp/room.wav"]
    assert player.set_convolver_enabled_calls == [True]
    assert player.tube_drive_calls == [36]
    assert player.tube_bias_calls == [63]
    assert player.tube_sag_calls == [24]
    assert player.tube_air_calls == [47]
    assert player.tube_enabled_calls == [True]
    assert player.widener_width_calls == [140]
    assert player.widener_bass_freq_calls == [90]
    assert player.widener_bass_amount_calls == [75]
    assert player.widener_enabled_calls == [True]
    assert player.limiter_threshold_calls == [0.78]
    assert player.limiter_ratio_calls == [12.0]
    assert player.limiter_enabled_calls == [True]


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


def test_init_audio_and_data_services_batches_lv2_restore(tmp_path, monkeypatch):
    pytest.importorskip("gi")
    from app import app_init_runtime as mod

    class _Player:
        def __init__(self):
            self.visual_sync_offset_ms = None
            self.latency_calls = []
            self.realtime_priority_calls = []
            self.dsp_enabled_calls = []
            self.dsp_order_calls = []
            self.lv2_restore_slots_calls = []
            self.limiter_threshold_calls = []
            self.limiter_ratio_calls = []
            self.limiter_enabled_calls = []

        def set_alsa_latency(self, buf_ms, lat_ms):
            self.latency_calls.append((buf_ms, lat_ms))

        def set_alsa_mmap_realtime_priority(self, priority):
            self.realtime_priority_calls.append(int(priority))

        def set_dsp_order(self, order):
            self.dsp_order_calls.append(list(order))
            return True

        def set_dsp_enabled(self, enabled):
            self.dsp_enabled_calls.append(bool(enabled))
            return True

        def lv2_restore_slots(self, slots):
            self.lv2_restore_slots_calls.append(list(slots))
            return True

        def set_limiter_threshold(self, threshold):
            self.limiter_threshold_calls.append(float(threshold))
            return True

        def set_limiter_ratio(self, ratio):
            self.limiter_ratio_calls.append(float(ratio))
            return True

        def set_limiter_enabled(self, enabled):
            self.limiter_enabled_calls.append(bool(enabled))
            return True

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
        "viz_sync_device_offsets": {},
        "viz_sync_offset_ms": 0,
        "alsa_mmap_realtime_priority": "Recommended (60)",
        "latency_profile": "Standard (100ms)",
        "audio_cache_tracks": 0,
        "dsp_order": ["peq", "lv2_0", "tube", "convolver", "tape", "widener"],
        "dsp_lv2_slots": [
            {
                "slot_id": "lv2_0",
                "uri": "http://example.com/plugin",
                "enabled": False,
                "port_values": {"mix": 0.5},
            }
        ],
    }
    app.LATENCY_MAP = {"Standard (100ms)": (100, 100)}
    app.ALSA_MMAP_REALTIME_PRIORITY_MAP = {"Recommended (60)": 60}
    app.ALSA_MMAP_REALTIME_PRIORITY_DEFAULT = "Recommended (60)"
    app.on_next_track = lambda *a, **k: None
    app.update_tech_label = lambda *a, **k: None
    app.on_spectrum_data = lambda *a, **k: None
    app.on_viz_sync_offset_update = lambda *a, **k: None
    called = []
    app._schedule_cache_maintenance = lambda: called.append("scheduled")

    mod._init_audio_and_data_services(app)

    assert app.player is player
    assert player.dsp_order_calls == [["peq", "lv2_0", "tube", "convolver", "tape", "widener"]]
    assert player.lv2_restore_slots_calls == [[
        {
            "slot_id": "lv2_0",
            "uri": "http://example.com/plugin",
            "enabled": False,
            "port_values": {"mix": 0.5},
        }
    ]]
    assert player.limiter_threshold_calls == [0.85]
    assert player.limiter_ratio_calls == [20.0]
    assert player.limiter_enabled_calls == [False]
    assert called == ["scheduled"]
