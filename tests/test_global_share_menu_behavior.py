import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from ui import builders


class _Rect:
    def __init__(self):
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0


class _Popover:
    def __init__(self, visible=True):
        self.popup_calls = 0
        self.popdown_calls = 0
        self.rect = None
        self.visible = bool(visible)

    def popup(self):
        self.popup_calls += 1
        self.visible = True

    def popdown(self):
        self.popdown_calls += 1
        self.visible = False

    def set_pointing_to(self, rect):
        self.rect = rect

    def get_visible(self):
        return self.visible


class _Gesture:
    def __init__(self):
        self.state = None

    def set_state(self, value):
        self.state = value


class _Widget:
    def __init__(self, parent=None):
        self._parent = parent

    def get_parent(self):
        return self._parent


def test_global_context_menu_claims_secondary_click_and_opens_popover(monkeypatch):
    popover = _Popover()
    app = SimpleNamespace(global_share_popover=popover, win=None, header=None)
    gesture = _Gesture()
    cleared = []

    monkeypatch.setattr(builders.Gdk, "Rectangle", _Rect)
    monkeypatch.setattr(builders, "_clear_search_focus", lambda _app: cleared.append(True))

    builders._on_global_context_menu_pressed(app, gesture, 42, 64)

    assert gesture.state == builders.Gtk.EventSequenceState.CLAIMED
    assert cleared == [True]
    assert popover.popup_calls == 1
    assert popover.rect is not None
    assert (popover.rect.x, popover.rect.y) == (42, 64)


def test_header_secondary_click_keeps_default_menu(monkeypatch):
    popover = _Popover(visible=False)
    header = _Widget()
    hit = _Widget(parent=header)
    app = SimpleNamespace(
        global_share_popover=popover,
        win=_Window(hit=hit),
        header=header,
    )
    gesture = _Gesture()
    cleared = []

    monkeypatch.setattr(builders, "_clear_search_focus", lambda _app: cleared.append(True))

    builders._on_global_context_menu_pressed(app, gesture, 18, 22)

    assert gesture.state is None
    assert popover.popup_calls == 0
    assert cleared == []


def test_global_share_click_closes_popover_and_copies_link():
    popover = _Popover()
    copied = []
    notices = []
    app = SimpleNamespace(
        global_share_popover=popover,
        _copy_share_url_to_clipboard=lambda: (copied.append(True), True)[1],
        show_output_notice=lambda text, state, timeout_ms: notices.append((text, state, timeout_ms)),
    )

    builders._on_global_share_clicked(app)

    assert popover.popdown_calls == 1
    assert copied == [True]
    assert notices == [("Link copied to clipboard.", "ok", 1800)]


class _Window:
    def __init__(self, hit=None):
        self._hit = hit
        self.close_calls = 0

    def pick(self, _x, _y, _flags):
        return self._hit

    def close(self):
        self.close_calls += 1


def test_primary_click_outside_global_share_menu_claims_and_closes(monkeypatch):
    popover = _Popover(visible=True)
    app = SimpleNamespace(
        global_share_popover=popover,
        win=_Window(hit=None),
    )
    gesture = _Gesture()
    suppressed = []
    cleared = []

    monkeypatch.setattr(builders, "_suppress_search_focus", lambda _app, duration_ms=220: suppressed.append(duration_ms))
    monkeypatch.setattr(builders.GLib, "idle_add", lambda func: func())
    monkeypatch.setattr(builders, "_clear_search_focus", lambda _app: cleared.append(True))

    builders._on_window_pressed_for_dismiss(app, 14, 20, gesture=gesture)

    assert gesture.state == builders.Gtk.EventSequenceState.CLAIMED
    assert popover.popdown_calls == 1
    assert suppressed == [220]
    assert cleared == [True]


def test_global_close_click_closes_popover_and_window():
    popover = _Popover()
    win = _Window()
    app = SimpleNamespace(
        global_share_popover=popover,
        win=win,
    )

    builders._on_global_close_clicked(app)

    assert popover.popdown_calls == 1
    assert win.close_calls == 1
