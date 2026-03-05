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


class _FakeLabel:
    def __init__(self, *args, **kwargs):
        self.label = kwargs.get("label")
        self.kwargs = kwargs


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


def test_batch_load_albums_adds_artist_and_year_subtitle(monkeypatch):
    fake_gtk = SimpleNamespace(
        Box=_FakeBox,
        Image=_FakeImage,
        Label=_FakeLabel,
        FlowBoxChild=_FakeFlowBoxChild,
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
    )

    assert ui_actions.batch_load_albums(app, [album], batch=6) is False

    child = app.main_flow.children[0]
    labels = [item for item in child.child.children if isinstance(item, _FakeLabel)]
    assert [label.label for label in labels] == [
        "Mezzanine",
        "1998",
    ]
