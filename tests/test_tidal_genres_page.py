import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backend.tidal import TidalBackend


def test_get_genres_page_reads_official_links_and_prefetches_first_section():
    backend = object.__new__(TidalBackend)
    genre_page = SimpleNamespace(
        categories=[
            SimpleNamespace(
                items=[
                    SimpleNamespace(title="Blues", api_path="/pages/genre/blues"),
                    SimpleNamespace(title="Classical", api_path="pages/genre/classical"),
                ]
            ),
            SimpleNamespace(
                items=[SimpleNamespace(title="Blues", api_path="/pages/genre/blues")]
            ),
        ]
    )
    eager_calls = []
    backend.session = SimpleNamespace(page=object(), genres=lambda: genre_page)
    backend.get_genre_section = lambda label, path: eager_calls.append((label, path)) or {
        "title": label,
        "categories": [],
    }

    definitions, eager = backend.get_genres_page()

    assert definitions == [
        ("Blues", "pages/genre/blues"),
        ("Classical", "pages/genre/classical"),
    ]
    assert eager_calls == [("Blues", "pages/genre/blues")]
    assert eager == [{"title": "Blues", "categories": []}]


def test_get_genre_section_builds_category_sections_from_page_items():
    backend = object.__new__(TidalBackend)
    album_item = SimpleNamespace(
        id="album-1",
        header="Kind of Blue",
        short_header="Kind of Blue",
        short_sub_header="Miles Davis",
        image_id="abc-def",
        type="ALBUM",
    )
    album_dup = SimpleNamespace(
        id="album-1",
        header="Kind of Blue",
        short_header="Kind of Blue",
        short_sub_header="Miles Davis",
        image_id="abc-def",
        type="ALBUM",
    )
    page_link = SimpleNamespace(
        title="Editor Picks",
        api_path="/pages/editor-picks",
        image_id="def-ghi",
    )
    backend.session = SimpleNamespace(
        page=SimpleNamespace(
            get=lambda path, params=None: SimpleNamespace(
                categories=[
                    SimpleNamespace(title="Albums", items=[album_item, album_dup], _more=None),
                    SimpleNamespace(title="Playlists", items=[page_link], _more=None),
                ]
            )
        )
    )
    backend._process_generic_item = lambda _item: None

    section = backend.get_genre_section("Jazz", "pages/genre/jazz")

    assert section["title"] == "Jazz"
    assert [cat["title"] for cat in section["categories"]] == ["Albums", "Playlists"]
    assert len(section["categories"][0]["items"]) == 1
    assert section["categories"][0]["items"][0]["name"] == "Kind of Blue"
    assert section["categories"][0]["items"][0]["type"] == "Album"
    assert section["categories"][1]["items"][0]["name"] == "Editor Picks"
    assert section["categories"][1]["items"][0]["type"] == "PageLink"


def test_get_genre_section_skips_untitled_editorial_items_without_generic_unknown_fallback():
    backend = object.__new__(TidalBackend)
    untitled_page_item = SimpleNamespace(
        header="",
        short_header="",
        short_sub_header="Editorial copy",
        image_id="abc-def",
        type="ALBUM",
    )
    backend.session = SimpleNamespace(
        page=SimpleNamespace(
            get=lambda path, params=None: SimpleNamespace(
                categories=[
                    SimpleNamespace(title="Highlights", items=[untitled_page_item], _more=None),
                ]
            )
        )
    )
    backend._process_generic_item = lambda _item: {
        "obj": _item,
        "name": "Unknown",
        "sub_title": "",
        "image_url": None,
        "type": "Fallback",
    }

    section = backend.get_genre_section("Women's History Month", "pages/moods/whm")

    assert section is None


def test_get_moods_page_filters_tabs_with_no_renderable_content():
    backend = object.__new__(TidalBackend)
    moods_page = SimpleNamespace(
        categories=[
            SimpleNamespace(
                items=[
                    SimpleNamespace(title="Women's History Month", api_path="/pages/moods/whm"),
                    SimpleNamespace(title="For DJs", api_path="/pages/moods/for-djs"),
                    SimpleNamespace(title="TIDAL Magazine", api_path="/pages/moods/magazine"),
                ]
            )
        ]
    )
    backend.session = SimpleNamespace(
        page=SimpleNamespace(get=lambda path, params=None: moods_page)
    )
    backend.get_genre_section = lambda label, path: (
        None
        if label == "Women's History Month"
        else {"title": label, "categories": [{"title": "", "items": [{"name": label}]}]}
    )

    definitions, eager = backend.get_moods_page()

    assert definitions == [
        ("For DJs", "pages/moods/for-djs"),
        ("TIDAL Magazine", "pages/moods/magazine"),
    ]
    assert [sec["title"] for sec in eager] == ["For DJs", "TIDAL Magazine"]
