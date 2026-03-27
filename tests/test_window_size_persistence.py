import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.settings import (
    WINDOW_SIZE_DEFAULT_HEIGHT,
    WINDOW_SIZE_DEFAULT_WIDTH,
    WINDOW_SIZE_MIN_HEIGHT,
    WINDOW_SIZE_MIN_WIDTH,
    normalize_settings,
)


def test_normalize_settings_window_size_defaults_and_bounds():
    out = normalize_settings({})
    assert out["remember_window_size"] is False
    assert out["window_width"] == 0
    assert out["window_height"] == 0

    out = normalize_settings(
        {
            "remember_window_size": True,
            "window_width": WINDOW_SIZE_MIN_WIDTH + 320,
            "window_height": WINDOW_SIZE_MIN_HEIGHT + 180,
        }
    )
    assert out["remember_window_size"] is True
    assert out["window_width"] == WINDOW_SIZE_MIN_WIDTH + 320
    assert out["window_height"] == WINDOW_SIZE_MIN_HEIGHT + 180

    out = normalize_settings(
        {
            "remember_window_size": True,
            "window_width": WINDOW_SIZE_MIN_WIDTH - 1,
            "window_height": WINDOW_SIZE_MIN_HEIGHT - 1,
        }
    )
    assert out["window_width"] == 0
    assert out["window_height"] == 0


def test_get_startup_window_size_requires_opt_in():
    pytest.importorskip("gi")
    from app import app_state_persistence as mod

    app = SimpleNamespace(
        settings={
            "remember_window_size": False,
            "window_width": 1600,
            "window_height": 900,
        }
    )

    assert mod._get_startup_window_size(app) == (
        WINDOW_SIZE_DEFAULT_WIDTH,
        WINDOW_SIZE_DEFAULT_HEIGHT,
    )


def test_remember_current_window_size_uses_last_normal_size_in_mini_mode():
    pytest.importorskip("gi")
    from app import app_state_persistence as mod

    scheduled = []

    class _Win:
        def get_width(self):
            return 390

        def get_height(self):
            return 85

    app = SimpleNamespace(
        settings={
            "remember_window_size": True,
            "window_width": 0,
            "window_height": 0,
        },
        is_mini_mode=True,
        saved_width=1440,
        saved_height=900,
        win=_Win(),
        schedule_save_settings=lambda delay_ms=250: scheduled.append(delay_ms),
    )

    changed = mod._remember_current_window_size(app)

    assert changed is True
    assert app.settings["window_width"] == 1440
    assert app.settings["window_height"] == 900
    assert scheduled == [250]


def test_remember_current_window_size_refreshes_cache_for_hidden_window_shutdown():
    pytest.importorskip("gi")
    from app import app_state_persistence as mod

    class _Win:
        def __init__(self):
            self.width = 1510
            self.height = 930

        def get_size(self):
            return (self.width, self.height)

        def get_width(self):
            return self.width

        def get_height(self):
            return self.height

    scheduled = []
    win = _Win()
    app = SimpleNamespace(
        settings={
            "remember_window_size": True,
            "window_width": 0,
            "window_height": 0,
        },
        is_mini_mode=False,
        saved_width=WINDOW_SIZE_DEFAULT_WIDTH,
        saved_height=WINDOW_SIZE_DEFAULT_HEIGHT,
        win=win,
        schedule_save_settings=lambda delay_ms=250: scheduled.append(delay_ms),
    )

    changed = mod._remember_current_window_size(app)
    assert changed is True
    assert app.saved_width == 1510
    assert app.saved_height == 930
    assert app.settings["window_width"] == 1510
    assert app.settings["window_height"] == 930
    assert scheduled == [250]

    win.width = 0
    win.height = 0
    changed = mod._remember_current_window_size(app, persist=False)
    assert changed is False
    assert app.settings["window_width"] == 1510
    assert app.settings["window_height"] == 930


def test_close_request_remembers_size_before_hiding_to_tray():
    pytest.importorskip("gi")
    from app import app_tray

    calls = []

    class _Win:
        def __init__(self):
            self.hidden = False

        def hide(self):
            self.hidden = True

    app = SimpleNamespace(
        _allow_window_close=False,
        _tray_ready=False,
        win=_Win(),
        _init_tray_icon=lambda: setattr(app, "_tray_ready", True),
        _remember_current_window_size=lambda: calls.append("remembered"),
    )

    handled = app_tray.on_window_close_request(app, app.win)

    assert handled is True
    assert calls == ["remembered"]
    assert app.win.hidden is True


def test_window_size_changed_updates_settings():
    pytest.importorskip("gi")
    from app import app_state_persistence as mod

    class _Win:
        def get_default_size(self):
            return (1660, 980)

        def get_width(self):
            return 1660

        def get_height(self):
            return 980

    scheduled = []
    win = _Win()
    app = SimpleNamespace(
        settings={
            "remember_window_size": True,
            "window_width": 0,
            "window_height": 0,
        },
        is_mini_mode=False,
        saved_width=WINDOW_SIZE_DEFAULT_WIDTH,
        saved_height=WINDOW_SIZE_DEFAULT_HEIGHT,
        win=win,
        schedule_save_settings=lambda delay_ms=250: scheduled.append(delay_ms),
    )

    mod.on_window_size_changed(app, win, None)
    assert app.settings["window_width"] == 1660
    assert app.settings["window_height"] == 980
    assert scheduled == [250]
