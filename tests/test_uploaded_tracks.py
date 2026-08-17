import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backend.tidal import TidalBackend


def test_extract_owned_track_ids_keeps_order_and_skips_junk():
    payload = {
        "data": [
            {"id": "111", "type": "tracks"},
            {"id": "222", "type": "videos"},
            {"id": "", "type": "tracks"},
            "garbage",
            {"id": "333", "type": "tracks"},
        ]
    }
    assert TidalBackend._extract_owned_track_ids(payload) == ["111", "333"]
    assert TidalBackend._extract_owned_track_ids({}) == []
    assert TidalBackend._extract_owned_track_ids(None) == []


def test_extract_next_page_cursor():
    payload = {
        "links": {
            "self": "/tracks?filter%5Bowners.id%5D=1",
            "next": "/tracks?filter%5Bowners.id%5D=1&page%5Bcursor%5D=abc123",
        }
    }
    assert TidalBackend._extract_next_page_cursor(payload) == "abc123"
    assert TidalBackend._extract_next_page_cursor({"links": {"self": "/tracks"}}) is None
    assert TidalBackend._extract_next_page_cursor({}) is None


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _make_backend(pages, track_factory):
    """TidalBackend with a stubbed session: openapi pages + v1 hydration."""
    backend = TidalBackend.__new__(TidalBackend)
    backend.user = SimpleNamespace(id=42)
    calls = {"requests": [], "hydrated": []}

    def _request(method, path, params=None, base_url=None, **_kw):
        calls["requests"].append((method, path, dict(params or {}), base_url))
        cursor = (params or {}).get("page[cursor]")
        return _FakeResponse(pages[cursor])

    def _track(tid):
        calls["hydrated"].append(tid)
        return track_factory(tid)

    backend.session = SimpleNamespace(
        config=SimpleNamespace(openapi_v2_location="https://openapi.example/v2/"),
        request=SimpleNamespace(request=_request),
        track=_track,
    )
    return backend, calls


def test_get_uploaded_tracks_paginates_and_hydrates_via_v1():
    pages = {
        None: {
            "data": [{"id": "10", "type": "tracks"}, {"id": "11", "type": "tracks"}],
            "links": {"next": "/tracks?page%5Bcursor%5D=c2"},
        },
        "c2": {
            "data": [{"id": "12", "type": "tracks"}],
            "links": {},
        },
    }
    backend, calls = _make_backend(pages, lambda tid: SimpleNamespace(id=int(tid)))

    tracks = backend.get_uploaded_tracks()

    assert [t.id for t in tracks] == [10, 11, 12]
    assert calls["hydrated"] == ["10", "11", "12"]
    assert all(base == "https://openapi.example/v2/" for _m, _p, _q, base in calls["requests"])
    assert calls["requests"][0][2] == {"filter[owners.id]": "42"}
    assert calls["requests"][1][2]["page[cursor]"] == "c2"


def test_get_uploaded_tracks_drops_failed_hydrations():
    pages = {
        None: {
            "data": [{"id": "10", "type": "tracks"}, {"id": "11", "type": "tracks"}],
            "links": {},
        }
    }

    def _factory(tid):
        if tid == "10":
            raise RuntimeError("gone")
        return SimpleNamespace(id=int(tid))

    backend, _calls = _make_backend(pages, _factory)

    tracks = backend.get_uploaded_tracks()

    assert [t.id for t in tracks] == [11]


def test_get_uploaded_tracks_without_login_returns_empty():
    backend = TidalBackend.__new__(TidalBackend)
    backend.user = None
    assert backend.get_uploaded_tracks() == []
