import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backend.tidal import TidalBackend


def _make_backend(categories):
    backend = object.__new__(TidalBackend)
    backend.session = SimpleNamespace(home=lambda: SimpleNamespace(categories=categories))
    backend._process_generic_item = lambda item: {"obj": item, "name": "Track", "sub_title": "", "type": "Track"}
    backend._call_with_session_recovery = lambda fn, context="api": fn()
    return backend


def test_get_home_page_keeps_section_subtitle_and_filters_by_it():
    categories = [
        SimpleNamespace(
            title="Recommended Tracks",
            subtitle="Because you liked Hello",
            description="",
            type="HORIZONTAL_LIST_WITH_CONTEXT",
            items=[SimpleNamespace(id="t1")],
        ),
        SimpleNamespace(
            title="Editorial Picks",
            subtitle="Staff selections",
            description="",
            type="HORIZONTAL_LIST",
            items=[SimpleNamespace(id="t2")],
        ),
    ]
    backend = _make_backend(categories)

    sections = backend.get_home_page()

    assert len(sections) == 1
    assert sections[0]["title"] == "Recommended Tracks"
    assert sections[0]["subtitle"] == "Because you liked Hello"
    assert sections[0]["section_type"] == "HORIZONTAL_LIST_WITH_CONTEXT"


def test_get_home_page_uses_description_when_subtitle_is_missing():
    categories = [
        SimpleNamespace(
            title="Tracks for you",
            subtitle="",
            description="Recommended because you listened to Hello",
            type="HORIZONTAL_LIST_WITH_CONTEXT",
            items=[SimpleNamespace(id="t1")],
        ),
    ]
    backend = _make_backend(categories)

    sections = backend.get_home_page()

    assert len(sections) == 1
    assert sections[0]["subtitle"] == "Recommended because you listened to Hello"


def test_get_home_page_uses_raw_context_header_from_official_feed():
    def _parse_album(data):
        artist_names = [a.get("name", "") for a in list(data.get("artists") or []) if isinstance(a, dict)]
        artist_name = artist_names[0] if artist_names else ""
        return SimpleNamespace(
            id=data.get("id"),
            title=data.get("title"),
            name=data.get("title"),
            cover=data.get("cover"),
            artist=SimpleNamespace(name=artist_name),
        )

    raw_payload = {
        "items": [
            {
                "type": "HORIZONTAL_LIST_WITH_CONTEXT",
                "title": "Because you liked",
                "subtitle": None,
                "description": "",
                "header": {
                    "type": "ALBUM",
                    "data": {
                        "id": 1,
                        "title": "初次嚐到寂寞",
                        "cover": "0624f556-efef-4268-ae0e-070e5dc4230e",
                        "artists": [{"name": "鄧麗君"}],
                    },
                },
                "items": [
                    {
                        "type": "ALBUM",
                        "data": {
                            "id": 2,
                            "title": "島國之情歌第六集 小城故事",
                            "cover": "f3fdab50-9022-4947-83b7-308059ed358c",
                            "artists": [{"name": "鄧麗君"}],
                        },
                    }
                ],
            }
        ]
    }

    backend = object.__new__(TidalBackend)
    backend._process_generic_item = lambda item: {
        "obj": item,
        "name": getattr(item, "title", getattr(item, "name", "")),
        "sub_title": getattr(getattr(item, "artist", None), "name", ""),
        "type": "Album",
        "image_url": f"mock://{getattr(item, 'cover', '')}",
    }
    backend._call_with_session_recovery = lambda fn, context="api": fn()
    backend.session = SimpleNamespace(
        locale="en_US",
        config=SimpleNamespace(api_v2_location="https://example.invalid"),
        request=SimpleNamespace(request=lambda *args, **kwargs: SimpleNamespace(json=lambda: raw_payload)),
        parse_album=_parse_album,
    )

    sections = backend.get_home_page()

    assert len(sections) == 1
    assert sections[0]["section_type"] == "HORIZONTAL_LIST_WITH_CONTEXT"
    assert sections[0]["context_header"]["name"] == "初次嚐到寂寞"
    assert sections[0]["context_header"]["image_url"] == "mock://0624f556-efef-4268-ae0e-070e5dc4230e"
