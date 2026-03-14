import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from actions import ui_actions


def test_home_section_header_uses_context_kicker_as_small_line():
    result = ui_actions._home_section_header_lines(
        {
            "title": "Because you liked",
            "subtitle": "",
            "section_type": "HORIZONTAL_LIST_WITH_CONTEXT",
            "context_header": {"name": "初次嚐到寂寞"},
        }
    )

    assert result == {
        "title": "初次嚐到寂寞",
        "kicker": "Because you liked",
        "secondary": "",
    }


def test_home_section_header_keeps_full_context_sentence_as_secondary():
    result = ui_actions._home_section_header_lines(
        {"title": "Recommended Tracks", "subtitle": "Because you liked Hello", "section_type": "HORIZONTAL_LIST"}
    )

    assert result == {
        "title": "Recommended Tracks",
        "kicker": "",
        "secondary": "Because you liked Hello",
    }


def test_home_card_subtitle_text_preserves_blank_row_for_missing_subtitle():
    assert ui_actions._home_card_subtitle_text("Dominique Fils-Aime") == "Dominique Fils-Aime"
    assert ui_actions._home_card_subtitle_text("") == " "
    assert ui_actions._home_card_subtitle_text(None) == " "


def test_home_card_layout_uses_fixed_media_slot_plus_card_padding():
    album_layout = ui_actions._home_card_layout({"type": "Album", "name": "Deadline"}, 170)
    track_layout = ui_actions._home_card_layout({"type": "Track", "name": "Song"}, 170)
    radio_layout = ui_actions._home_card_layout({"type": "Playlist", "name": "Personal Radio"}, 170)

    assert album_layout["img_size"] == 170
    assert album_layout["card_width"] == 170
    assert album_layout["img_cls"] == "album-cover-img"
    assert "home-feed-card" in album_layout["card_classes"]
    assert album_layout["text_width_chars"] == 16

    assert track_layout["img_size"] == 88
    assert track_layout["card_width"] == 88
    assert "home-track-card" in track_layout["card_classes"]
    assert track_layout["text_width_chars"] == 10

    assert radio_layout["img_size"] == 150
    assert radio_layout["card_width"] == 150
    assert radio_layout["img_cls"] == "circular-avatar"
    assert radio_layout["text_width_chars"] == 14


def test_home_feed_layout_marks_cards_for_feed_specific_hover_styling():
    layout = ui_actions._home_card_layout({"type": "Album", "name": "Deadline"}, 170)

    assert "home-feed-card" in layout["card_classes"]


def test_feed_card_classes_keeps_common_and_extra_classes():
    classes = ui_actions._feed_card_classes("history-card")

    assert classes == ["card", "home-card", "home-feed-card", "history-card"]


def test_feed_tint_classes_keeps_base_and_shape_classes():
    classes = ui_actions._feed_tint_classes("album-cover-img", "playlist-folder-shape")

    assert classes == ["home-feed-tint", "album-cover-img", "playlist-folder-shape"]


def test_dashboard_track_row_button_classes_keep_flat_row_hover_and_playing_state():
    assert ui_actions._dashboard_track_row_button_classes(False) == [
        "flat",
        "history-card-btn",
        "dashboard-track-row-btn",
    ]
    assert ui_actions._dashboard_track_row_button_classes(True) == [
        "flat",
        "history-card-btn",
        "dashboard-track-row-btn",
        "track-row-playing",
    ]


def test_artist_card_classes_keep_media_only_hover_override():
    classes = ui_actions._artist_card_classes()

    assert classes == ["card", "home-card", "home-feed-card", "artist-feed-card"]


def test_render_history_dashboard_omits_section_titles_and_count_labels(monkeypatch):
    class _FakeWidget:
        def __init__(self, *args, **kwargs):
            self.children = []
            self.label = str(kwargs.get("label", ""))
            self.css_classes = list(kwargs.get("css_classes", []))
            self.hexpand = bool(kwargs.get("hexpand", False))
            self.visible_child_name = ""

        def append(self, child):
            self.children.append(child)

        def connect(self, *_args, **_kwargs):
            return None

        def set_hhomogeneous(self, *_args, **_kwargs):
            return None

        def set_vhomogeneous(self, *_args, **_kwargs):
            return None

        def set_halign(self, *_args, **_kwargs):
            return None

        def set_hexpand(self, value):
            self.hexpand = bool(value)

        def set_visible_child_name(self, value):
            self.visible_child_name = str(value)

        def get_visible_child_name(self):
            return self.visible_child_name

        def add_titled(self, child, *_args, **_kwargs):
            self.children.append(child)

        def attach(self, child, *_args, **_kwargs):
            self.children.append(child)

    class _FakeFlowBoxChild:
        def __init__(self):
            self.child = None

        def set_child(self, child):
            self.child = child

    fake_gtk = SimpleNamespace(
        Box=_FakeWidget,
        Stack=_FakeWidget,
        StackSwitcher=_FakeWidget,
        Label=_FakeWidget,
        Grid=_FakeWidget,
        FlowBox=_FakeWidget,
        FlowBoxChild=_FakeFlowBoxChild,
        StackTransitionType=SimpleNamespace(CROSSFADE="crossfade"),
        Align=SimpleNamespace(START="start", CENTER="center", END="end", FILL="fill"),
        SelectionMode=SimpleNamespace(NONE="none"),
        Orientation=SimpleNamespace(VERTICAL="vertical", HORIZONTAL="horizontal"),
    )
    monkeypatch.setattr(ui_actions, "Gtk", fake_gtk)
    monkeypatch.setattr(ui_actions, "_clear_container", lambda container: container.children.clear())

    app = SimpleNamespace(
        collection_content_box=_FakeWidget(),
        history_mgr=SimpleNamespace(
            get_albums=lambda: [SimpleNamespace(name="Album One", artist=SimpleNamespace(name="Artist"))],
            get_top_tracks=lambda limit=20: [],
        ),
    )

    ui_actions.render_history_dashboard(app)

    tabs_box = app.collection_content_box.children[0]
    history_stack = tabs_box.children[1]
    sec_top = history_stack.children[0]
    sec_recent = history_stack.children[1]

    assert len(sec_top.children) == 1
    assert len(sec_recent.children) == 1

