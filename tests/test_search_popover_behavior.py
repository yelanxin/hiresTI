import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from actions import ui_actions


class _Popover:
    def __init__(self):
        self.popdown_calls = 0

    def popdown(self):
        self.popdown_calls += 1


class _Box:
    def __init__(self):
        self.visible = None

    def set_visible(self, value):
        self.visible = bool(value)


class _Stack:
    def __init__(self):
        self.visible_child_name = None

    def set_visible_child_name(self, name):
        self.visible_child_name = name


class _NavList:
    def __init__(self):
        self.selected_row = object()

    def select_row(self, row):
        self.selected_row = row


class _Button:
    def __init__(self):
        self.sensitive = None

    def set_sensitive(self, value):
        self.sensitive = bool(value)


def _make_app():
    return SimpleNamespace(
        search_suggest_popover=_Popover(),
        nav_history=[],
        right_stack=_Stack(),
        nav_list=_NavList(),
        back_btn=_Button(),
        res_art_flow=object(),
        res_alb_flow=object(),
        res_pl_flow=object(),
        res_trk_list=object(),
        res_art_box=_Box(),
        res_alb_box=_Box(),
        res_pl_box=_Box(),
        res_trk_box=_Box(),
        backend=SimpleNamespace(search_items=lambda _query: {}),
    )


def test_run_search_closes_search_suggestions(monkeypatch):
    app = _make_app()

    monkeypatch.setattr(ui_actions, "_generate_search_variants", lambda q: [q])
    monkeypatch.setattr(ui_actions, "_remember_query", lambda _app, _q: None)
    monkeypatch.setattr(
        ui_actions,
        "_build_local_search_results",
        lambda _app, _variants: {"playlists": [], "history_tracks": []},
    )
    monkeypatch.setattr(ui_actions, "_clear_container", lambda _container: None)
    monkeypatch.setattr(ui_actions, "set_search_status", lambda _app, _status: None)
    monkeypatch.setattr(
        ui_actions,
        "Thread",
        lambda target, daemon: SimpleNamespace(start=lambda: None),
    )

    ui_actions._run_search(app, "Muse")

    assert app.search_suggest_popover.popdown_calls == 1
    assert app.right_stack.visible_child_name == "search_view"
