import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backend.tidal import TidalBackend


class _FakeFavorites:
    def __init__(self):
        self.added = []
        self.removed = []

    def add_album(self, album_id):
        self.added.append(str(album_id))

    def remove_album(self, album_id):
        self.removed.append(str(album_id))


class _FakeAlbum:
    def __init__(self, album_id):
        self.id = str(album_id)


def _make_backend():
    backend = object.__new__(TidalBackend)
    backend.user = SimpleNamespace(favorites=_FakeFavorites())
    backend.fav_album_ids = set()
    backend.fav_artist_ids = set()
    backend.fav_track_ids = set()
    backend._cached_albums = []
    backend._cached_albums_ts = 0.0
    backend._albums_cache_ttl = 0.0
    return backend


def test_recent_album_cache_ttl_zero_never_counts_as_fresh():
    backend = _make_backend()
    backend._cached_albums = [_FakeAlbum("1")]
    backend._cached_albums_ts = 100.0
    backend._albums_cache_ttl = 0.0

    assert backend._album_cache_ttl_seconds() == 0.0
    assert backend._has_fresh_recent_albums_cache(now=100.1) is False


def test_toggle_album_favorite_remove_updates_cached_albums():
    backend = _make_backend()
    backend.fav_album_ids = {"1", "2"}
    backend._cached_albums = [_FakeAlbum("1"), _FakeAlbum("2")]
    favorites = backend.user.favorites

    assert backend.toggle_album_favorite("1", add=False) is True
    assert favorites.removed == ["1"]
    assert backend.fav_album_ids == {"2"}
    assert [alb.id for alb in backend._cached_albums] == ["2"]
    assert backend._cached_albums_ts > 0.0


def test_toggle_album_favorite_add_invalidates_cached_albums():
    backend = _make_backend()
    backend._cached_albums = [_FakeAlbum("2")]
    backend._cached_albums_ts = 321.0
    favorites = backend.user.favorites

    assert backend.toggle_album_favorite("9", add=True) is True
    assert favorites.added == ["9"]
    assert "9" in backend.fav_album_ids
    assert backend._cached_albums == []
    assert backend._cached_albums_ts == 0.0
