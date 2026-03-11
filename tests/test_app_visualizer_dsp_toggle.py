import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from app import app_visualizer as mod


class _Revealer:
    def __init__(self, reveal=False):
        self.reveal = bool(reveal)

    def get_reveal_child(self):
        return self.reveal


class _Stack:
    def __init__(self, page="spectrum"):
        self.page = page

    def get_visible_child_name(self):
        return self.page

    def set_visible_child_name(self, page):
        self.page = str(page)


def test_open_dsp_workspace_collapses_when_dsp_page_is_already_open():
    calls = []
    saved = []
    app = SimpleNamespace(
        _viz_fullscreen_active=False,
        viz_revealer=_Revealer(reveal=True),
        viz_stack=_Stack(page="dsp"),
        settings={},
        _set_visualizer_expanded=lambda expanded: calls.append(expanded),
        schedule_save_settings=lambda: saved.append(True),
        hide_now_playing_overlay=lambda: calls.append("hide"),
    )

    mod.open_dsp_workspace(app)

    assert calls == [False]
    assert app.settings["viz_expanded"] is False
    assert saved == [True]


def test_open_dsp_workspace_opens_dsp_page_when_closed():
    calls = []
    saved = []
    app = SimpleNamespace(
        _viz_fullscreen_active=False,
        viz_revealer=_Revealer(reveal=False),
        viz_stack=_Stack(page="lyrics"),
        settings={},
        _set_visualizer_expanded=lambda expanded: calls.append(expanded),
        schedule_save_settings=lambda: saved.append(True),
        hide_now_playing_overlay=lambda: calls.append("hide"),
    )

    mod.open_dsp_workspace(app)

    assert calls == ["hide", True]
    assert app.viz_stack.page == "dsp"
    assert app.settings["viz_expanded"] is True
    assert saved == [True]
