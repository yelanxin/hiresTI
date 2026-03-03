import json
import os
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import backend.tidal as tidal_mod
from backend.tidal import TidalBackend


class _FakeConfig:
    def __init__(self):
        self.quality = None

    def set_quality(self, quality):
        self.quality = quality


class _FakeSession:
    def __init__(self):
        self.config = _FakeConfig()
        self.user = SimpleNamespace(id="user-1")
        self.token_type = "Bearer"
        self.access_token = "fresh-access"
        self.refresh_token = "fresh-refresh"
        self.expiry_time = "2030-01-01T00:00:00"
        self.loaded = None

    def load_oauth_session(self, token_type, access_token, refresh_token, expiry_time):
        self.loaded = (token_type, access_token, refresh_token, expiry_time)

    def check_login(self):
        return True


class StaleAlbum:
    def __init__(self, album_id):
        self.id = str(album_id)

    def tracks(self):
        raise AssertionError("stale album object should not be used directly after recovery")


def _make_backend():
    backend = object.__new__(TidalBackend)
    backend.quality = "LOSSLESS"
    backend.user = None
    backend.session = None
    backend.token_file = ""
    backend.legacy_token_file = ""
    backend.fav_album_ids = set()
    backend.fav_artist_ids = set()
    backend.fav_track_ids = set()
    backend._cached_albums = []
    backend._cached_albums_ts = 0.0
    backend._albums_cache_ttl = 0.0
    backend._mix_fail_until = {}
    backend._last_login_error = ""
    backend._session_recovery_lock = threading.Lock()
    return backend


def test_recover_session_rebuilds_session_from_saved_token(tmp_path, monkeypatch):
    backend = _make_backend()
    backend.token_file = str(tmp_path / "hiresti_token.json")
    backend.legacy_token_file = str(tmp_path / "hiresti_token.pkl")

    with open(backend.token_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "token_type": "Bearer",
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "expiry_time": "2025-01-01T00:00:00",
            },
            f,
        )

    monkeypatch.setattr(tidal_mod.tidalapi, "Session", _FakeSession)
    backend._tune_http_pool = lambda session_obj=None: None

    assert backend.recover_session(reason="albums") is True
    assert isinstance(backend.session, _FakeSession)
    assert backend.user.id == "user-1"
    assert backend.session.loaded[:3] == ("Bearer", "old-access", "old-refresh")
    assert backend.session.config.quality == "LOSSLESS"

    with open(backend.token_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["access_token"] == "fresh-access"
    assert saved["refresh_token"] == "fresh-refresh"


def test_get_recent_albums_returns_cached_albums_when_recovery_fails():
    backend = _make_backend()
    cached = [SimpleNamespace(id="a1"), SimpleNamespace(id="a2")]

    def _failing_albums(**_kwargs):
        raise RuntimeError("401 unauthorized")

    backend.user = SimpleNamespace(favorites=SimpleNamespace(albums=_failing_albums))
    backend._cached_albums = list(cached)
    backend._cached_albums_ts = 123.0
    backend.recover_session = lambda reason="api": False

    result = backend.get_recent_albums(limit=100)

    assert [alb.id for alb in result] == ["a1", "a2"]
    assert [alb.id for alb in backend._cached_albums] == ["a1", "a2"]


def test_get_tracks_recovers_album_fetch_with_fresh_session():
    backend = _make_backend()
    track = SimpleNamespace(id="t1", name="Recovered Track")

    class _OldSession:
        def album(self, _album_id):
            return SimpleNamespace(tracks=lambda: (_ for _ in ()).throw(RuntimeError("401 unauthorized")))

    class _NewSession:
        def album(self, album_id):
            return SimpleNamespace(tracks=lambda: [track], id=album_id)

    backend.session = _OldSession()

    def _recover(reason="api"):
        backend.session = _NewSession()
        return True

    backend.recover_session = _recover

    result = backend.get_tracks(StaleAlbum("42"))

    assert result == [track]
