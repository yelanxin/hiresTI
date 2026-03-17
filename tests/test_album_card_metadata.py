import os
import sys
from datetime import date
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from actions import ui_actions


class _FakeBox:
    def __init__(self, *args, **kwargs):
        self.children = []

    def append(self, child):
        self.children.append(child)


class _FakeImage:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.icon_name = None

    def set_from_icon_name(self, icon_name):
        self.icon_name = icon_name


class _FakeLabel:
    def __init__(self, *args, **kwargs):
        self.label = kwargs.get("label")
        self.kwargs = kwargs
        self.tooltip = None

    def set_tooltip_text(self, value):
        self.tooltip = value


class _FakeFlowBoxChild:
    def __init__(self, *args, **kwargs):
        self.child = None
        self.data_item = None

    def set_child(self, child):
        self.child = child


class _FakeFlow:
    def __init__(self):
        self.children = []

    def append(self, child):
        self.children.append(child)


class _FakeButton:
    def __init__(self, *args, **kwargs):
        self.child = None
        self._clicked = None

    def set_child(self, child):
        self.child = child

    def connect(self, signal, callback):
        if signal == "clicked":
            self._clicked = callback
        return None

    def emit_clicked(self):
        if self._clicked is not None:
            self._clicked(self)


def test_album_release_year_text_supports_date_and_string_values():
    assert ui_actions._album_release_year_text(SimpleNamespace(release_date=date(1998, 4, 20))) == "1998"
    assert ui_actions._album_release_year_text(SimpleNamespace(release_date="2007-11-06")) == "2007"
    assert ui_actions._album_release_year_text(SimpleNamespace(release_date=None)) == ""


def test_album_subtitle_helpers_keep_year_visible():
    album = SimpleNamespace(
        artist=SimpleNamespace(name="Sissel Kyrkjebo"),
        release_date="1994-09-12",
    )

    assert ui_actions._album_artist_year_subtitle_text(album) == "Sissel Kyrkjebo  •  1994"
    assert ui_actions._album_year_subtitle_text(album) == "1994"


def test_batch_load_albums_matches_saved_album_card_subtitle(monkeypatch):
    fake_gtk = SimpleNamespace(
        Box=_FakeBox,
        Image=_FakeImage,
        Label=_FakeLabel,
        FlowBoxChild=_FakeFlowBoxChild,
        Button=_FakeButton,
        Orientation=SimpleNamespace(VERTICAL="vertical"),
        Align=SimpleNamespace(CENTER="center"),
    )
    monkeypatch.setattr(ui_actions, "Gtk", fake_gtk)
    monkeypatch.setattr(ui_actions.utils, "load_img", lambda *_args, **_kwargs: None)

    album = SimpleNamespace(
        name="Mezzanine",
        artist=SimpleNamespace(name="Massive Attack"),
        release_date="1998-04-20",
    )
    app = SimpleNamespace(
        backend=SimpleNamespace(get_artwork_url=lambda *_args, **_kwargs: "artwork"),
        cache_dir="/tmp",
        main_flow=_FakeFlow(),
        show_album_details=lambda *_args, **_kwargs: None,
    )

    assert ui_actions.batch_load_albums(app, [album], batch=6) is False

    child = app.main_flow.children[0]
    labels = [item for item in child.child.children if isinstance(item, _FakeLabel)]
    assert [label.label for label in labels] == [
        "Mezzanine",
        "Massive Attack  •  1998",
    ]


def test_my_albums_style_button_matches_saved_album_card_layout(monkeypatch):
    fake_gtk = SimpleNamespace(
        Box=_FakeBox,
        Image=_FakeImage,
        Label=_FakeLabel,
        FlowBoxChild=_FakeFlowBoxChild,
        Button=_FakeButton,
        Orientation=SimpleNamespace(VERTICAL="vertical"),
        Align=SimpleNamespace(CENTER="center"),
    )
    monkeypatch.setattr(ui_actions, "Gtk", fake_gtk)
    monkeypatch.setattr(ui_actions.utils, "load_img", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui_actions, "_build_feed_media_overlay", lambda widget, *_args, **_kwargs: widget)

    clicked = []
    album = SimpleNamespace(
        name="Mezzanine",
        artist=SimpleNamespace(name="Massive Attack"),
        release_date="1998-04-20",
    )
    app = SimpleNamespace(
        backend=SimpleNamespace(get_artwork_url=lambda *_args, **_kwargs: "artwork"),
        cache_dir="/tmp",
    )

    btn = ui_actions._build_my_albums_style_button(app, album, lambda alb: clicked.append(alb))

    labels = [item for item in btn.child.children if isinstance(item, _FakeLabel)]
    assert [label.label for label in labels] == [
        "Mezzanine",
        "Massive Attack  •  1998",
    ]
    assert labels[1].tooltip == "Massive Attack  •  1998"

    btn.emit_clicked()
    assert clicked == [album]


def test_artist_index_filter_and_sort_support_full_search_and_ordering():
    entries = [
        {"id": "2", "name": "Teresa Teng", "name_lc": "teresa teng", "added": "2026-01-02T00:00:00+00:00"},
        {"id": "1", "name": "Ada", "name_lc": "ada", "added": "2026-01-03T00:00:00+00:00"},
        {"id": "3", "name": "Aaron", "name_lc": "aaron", "added": "2026-01-01T00:00:00+00:00"},
    ]

    filtered = ui_actions._filter_artist_index_entries(entries, "te")
    assert [entry["id"] for entry in filtered] == ["2"]

    by_name = ui_actions._sort_artist_index_entries(entries, "name_asc")
    assert [entry["id"] for entry in by_name] == ["3", "1", "2"]

    by_recent = ui_actions._sort_artist_index_entries(entries, "date_desc")
    assert [entry["id"] for entry in by_recent] == ["1", "2", "3"]
