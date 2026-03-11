import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from ui import builders


class _Popover:
    def __init__(self, visible=False):
        self.visible = bool(visible)
        self.popdown_calls = 0

    def popdown(self):
        self.popdown_calls += 1

    def get_visible(self):
        return self.visible


class _Win:
    def __init__(self, hit=None, focus=None):
        self._hit = hit
        self._focus = focus
        self.focus_values = []

    def pick(self, _x, _y, _flags):
        return self._hit

    def set_focus(self, value):
        self.focus_values.append(value)
        self._focus = value

    def get_focus(self):
        return self._focus


class _Widget:
    def __init__(self, parent=None, focusable=False):
        self._parent = parent
        self._focusable = focusable

    def get_parent(self):
        return self._parent

    def get_focusable(self):
        return self._focusable


def test_clicking_non_focusable_area_clears_search_focus(monkeypatch):
    hit = _Widget(focusable=False)
    win = _Win(hit=hit)
    app = SimpleNamespace(
        search_suggest_popover=_Popover(),
        search_entry=object(),
        win=win,
        header=_Widget(),
    )

    monkeypatch.setattr(builders, "_click_is_on_entry", lambda *_args: False)
    monkeypatch.setattr(builders.GLib, "idle_add", lambda func: func())

    builders._on_window_pressed_for_dismiss(app, 20, 30)

    assert win.focus_values == [None]
    assert app.search_suggest_popover.popdown_calls == 1


def test_clicking_button_like_area_keeps_button_focus_behavior(monkeypatch):
    button = _Widget(focusable=True)
    label = _Widget(parent=button, focusable=False)
    win = _Win(hit=label)
    app = SimpleNamespace(
        search_suggest_popover=_Popover(),
        search_entry=object(),
        win=win,
        header=_Widget(),
    )

    monkeypatch.setattr(builders, "_click_is_on_entry", lambda *_args: False)
    monkeypatch.setattr(builders.GLib, "idle_add", lambda func: func())

    builders._on_window_pressed_for_dismiss(app, 20, 30)

    assert win.focus_values == []
    assert app.search_suggest_popover.popdown_calls == 0


def test_header_drag_release_clears_search_focus(monkeypatch):
    win = _Win()
    app = SimpleNamespace(
        search_suggest_popover=_Popover(),
        win=win,
        _search_header_dragging=True,
        _search_press_active=True,
        _search_press_start_x=10.0,
        _search_press_start_y=10.0,
        _search_press_in_header=True,
        _search_focus_suppressed_until_us=0,
    )

    monkeypatch.setattr(builders.GLib, "idle_add", lambda func: func())
    monkeypatch.setattr(builders.GLib, "get_monotonic_time", lambda: 1_000_000)

    builders._on_window_released_for_search_focus(app)

    assert win.focus_values == [None]
    assert app.search_suggest_popover.popdown_calls == 1
    assert app._search_focus_suppressed_until_us > 1_000_000
    assert app._search_header_dragging is False


def test_suppressed_search_focus_is_cleared_on_focus_enter(monkeypatch):
    entry = _Widget()
    win = _Win(focus=entry)
    app = SimpleNamespace(
        search_suggest_popover=_Popover(),
        search_entry=entry,
        win=win,
        _search_focus_suppressed_until_us=2_000_000,
    )

    monkeypatch.setattr(builders.GLib, "idle_add", lambda func: func())
    monkeypatch.setattr(builders.GLib, "get_monotonic_time", lambda: 1_000_000)

    shown = []
    monkeypatch.setattr(builders, "_maybe_show_search_suggestions", lambda _app: shown.append(True))

    builders._on_search_entry_focus_enter(app)

    assert shown == []
    assert win.focus_values == [None]
    assert app.search_suggest_popover.popdown_calls == 1


def test_dsp_order_edit_blocks_search_focus_enter(monkeypatch):
    entry = _Widget()
    win = _Win(focus=entry)
    app = SimpleNamespace(
        search_suggest_popover=_Popover(visible=True),
        search_entry=entry,
        win=win,
        _search_focus_suppressed_until_us=0,
        _dsp_order_editing=True,
        _dsp_order_drag_active=False,
    )

    monkeypatch.setattr(builders.GLib, "idle_add", lambda func: func())

    shown = []
    monkeypatch.setattr(builders, "_maybe_show_search_suggestions", lambda _app: shown.append(True))

    builders._on_search_entry_focus_enter(app)

    assert shown == []
    assert win.focus_values == [None]
    assert app.search_suggest_popover.popdown_calls == 1
