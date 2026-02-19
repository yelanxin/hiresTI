from types import SimpleNamespace

from tidal_backend import TidalBackend


def test_artist_artwork_falls_back_to_album_cover_and_caches():
    backend = TidalBackend()
    artist = SimpleNamespace(id=42, name="Fallback Artist")
    album = SimpleNamespace(id=1001, name="Fallback Album")

    calls = {"get_albums": 0}

    backend.session = SimpleNamespace(artist=lambda _artist_id: artist)
    backend.search_artist = lambda _query: []

    def fake_get_albums(_artist_obj):
        calls["get_albums"] += 1
        return [album]

    def fake_get_artwork_url(obj, size=320):
        if getattr(obj, "id", None) == artist.id:
            return None
        if getattr(obj, "id", None) == album.id:
            return f"https://img.local/{size}/album.jpg"
        return None

    backend.get_albums = fake_get_albums
    backend.get_artwork_url = fake_get_artwork_url
    backend._scan_image_like_attrs = lambda _obj, _size=320: None

    first = backend.get_artist_artwork_url(artist, 320)
    second = backend.get_artist_artwork_url(artist, 320)

    assert first == "https://img.local/320/album.jpg"
    assert second == "https://img.local/320/album.jpg"
    assert calls["get_albums"] == 1


def test_artist_artwork_does_not_cache_none_and_can_retry():
    backend = TidalBackend()
    artist = SimpleNamespace(id=7, name="Retry Artist")

    calls = {"get_artwork_url": 0}

    def flaky_get_artwork_url(_obj, size=320):
        calls["get_artwork_url"] += 1
        if calls["get_artwork_url"] == 1:
            return None
        return f"https://img.local/{size}/artist.jpg"

    backend.get_artwork_url = flaky_get_artwork_url
    backend.get_albums = lambda _artist_obj: []
    backend.search_artist = lambda _query: []
    backend._scan_image_like_attrs = lambda _obj, _size=320: None

    first = backend.get_artist_artwork_url(artist, 320)
    second = backend.get_artist_artwork_url(artist, 320)

    assert first is None
    assert second == "https://img.local/320/artist.jpg"
    assert calls["get_artwork_url"] >= 2


def test_artist_artwork_skips_known_placeholder_url_and_falls_back_album():
    backend = TidalBackend()
    artist = SimpleNamespace(id=9, name="Placeholder Artist")
    album = SimpleNamespace(id=9001, name="Real Album")
    placeholder = "https://resources.tidal.com/images/1e01cdb6/f15d/4d8b/8440/a047976c1cac/320x320.jpg"

    def fake_get_artwork_url(obj, size=320):
        if getattr(obj, "id", None) == artist.id:
            return placeholder
        if getattr(obj, "id", None) == album.id:
            return f"https://img.local/{size}/album.jpg"
        return None

    backend.get_artwork_url = fake_get_artwork_url
    backend.session = SimpleNamespace(artist=lambda _artist_id: artist)
    backend.get_albums = lambda _artist_obj: [album]
    backend.search_artist = lambda _query: []
    backend._scan_image_like_attrs = lambda _obj, _size=320: None

    url = backend.get_artist_artwork_url(artist, 320)
    assert url == "https://img.local/320/album.jpg"
