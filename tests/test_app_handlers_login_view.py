import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app_handlers
from app import app_auth


class _Widget:
    def __init__(self):
        self.visible = None

    def set_visible(self, v):
        self.visible = bool(v)


class _Paned(_Widget):
    def __init__(self):
        super().__init__()
        self.position = None

    def set_position(self, pos):
        self.position = int(pos)


def _make_app():
    app = SimpleNamespace()
    app._session_restore_pending = False
    app.paned = _Paned()
    app.win = SimpleNamespace(get_width=lambda: 800)
    app.settings = {"paned_position": 700}
    app._restore_paned_position_after_layout = lambda: False
    app.mini_btn = _Widget()
    app.tools_btn = _Widget()
    app.player_overlay = _Widget()
    app.bottom_bar = _Widget()
    app.login_prompt_box = _Widget()
    app.alb_scroll = _Widget()
    app.sidebar_box = _Widget()
    app.search_entry = _Widget()
    app.overlay_vis = []
    app._set_overlay_handles_visible = lambda v: app.overlay_vis.append(bool(v))
    return app


def test_toggle_login_view_logged_out(monkeypatch):
    app = _make_app()
    calls = []
    monkeypatch.setattr(
        app_auth.ui_views_builders,
        "toggle_login_view",
        lambda _app, logged_in: calls.append(logged_in),
    )

    app_handlers._toggle_login_view(app, False)

    assert app._session_restore_pending is False
    assert app.paned.position == 0
    assert app.paned.visible is True
    assert calls == [False]
    assert app.mini_btn.visible is False
    assert app.tools_btn.visible is False
    assert app.player_overlay.visible is False
    assert app.bottom_bar.visible is False
    assert app.overlay_vis[-1] is False


def test_toggle_login_view_logged_in(monkeypatch):
    app = _make_app()
    calls = []
    idle_calls = []
    monkeypatch.setattr(
        app_auth.ui_views_builders,
        "toggle_login_view",
        lambda _app, logged_in: calls.append(logged_in),
    )
    monkeypatch.setattr(app_auth.GLib, "idle_add", lambda fn: idle_calls.append(fn))

    app_handlers._toggle_login_view(app, True)

    # win_w=800 and SIDEBAR_RATIO=0.20 -> paned pos is 160
    assert app.paned.position == 160
    assert app.paned.visible is True
    assert calls == [True]
    assert len(idle_calls) == 1
    assert app.mini_btn.visible is True
    assert app.tools_btn.visible is True
    assert app.player_overlay.visible is True
    assert app.bottom_bar.visible is True
    assert app.overlay_vis[-1] is True


def test_set_login_view_pending_hides_controls():
    app = _make_app()

    app_handlers._set_login_view_pending(app)

    assert app._session_restore_pending is True
    assert app.paned.visible is False
    assert app.login_prompt_box.visible is False
    assert app.alb_scroll.visible is False
    assert app.sidebar_box.visible is False
    assert app.search_entry.visible is False
    assert app.mini_btn.visible is False
    assert app.tools_btn.visible is False
    assert app.player_overlay.visible is False
    assert app.bottom_bar.visible is False
    assert app.overlay_vis[-1] is False
