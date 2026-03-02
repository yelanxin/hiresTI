import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from app import app_favorites


class _Button:
    def __init__(self):
        self.icon_name = None
        self.classes = set()
        self.sensitive = None
        self.visible = None

    def set_icon_name(self, value):
        self.icon_name = str(value)

    def add_css_class(self, value):
        self.classes.add(str(value))

    def remove_css_class(self, value):
        self.classes.discard(str(value))

    def set_sensitive(self, value):
        self.sensitive = bool(value)

    def set_visible(self, value):
        self.visible = bool(value)

    def get_css_classes(self):
        return list(self.classes)


def test_refresh_current_track_favorite_state_updates_main_and_now_playing_buttons(monkeypatch):
    main_btn = _Button()
    now_btn = _Button()
    backend = SimpleNamespace(user=object(), is_track_favorite=lambda _track_id: True)
    app = SimpleNamespace(
        track_fav_btn=main_btn,
        now_playing_track_fav_btn=now_btn,
        playing_track=SimpleNamespace(id="track-1"),
        backend=backend,
    )
    app._update_fav_icon = lambda btn, is_active: app_favorites._update_fav_icon(app, btn, is_active)

    monkeypatch.setattr(app_favorites, "submit_daemon", lambda task: task())
    monkeypatch.setattr(app_favorites.GLib, "idle_add", lambda func: func())

    app_favorites.refresh_current_track_favorite_state(app)

    assert main_btn.icon_name == "hiresti-favorite-symbolic"
    assert now_btn.icon_name == "hiresti-favorite-symbolic"
    assert "active" in main_btn.classes
    assert "active" in now_btn.classes
    assert main_btn.sensitive is True
    assert now_btn.sensitive is True
    assert main_btn.visible is True
    assert now_btn.visible is True


def test_on_track_fav_clicked_refreshes_both_current_track_buttons(monkeypatch):
    main_btn = _Button()
    now_btn = _Button()
    backend_calls = []
    side_effects = []
    backend = SimpleNamespace(
        user=object(),
        toggle_track_favorite=lambda track_id, is_add: backend_calls.append((track_id, is_add)) or True,
    )
    app = SimpleNamespace(
        track_fav_btn=main_btn,
        now_playing_track_fav_btn=now_btn,
        playing_track=SimpleNamespace(id="track-1"),
        backend=backend,
        refresh_current_track_favorite_state=lambda: side_effects.append("refresh_current"),
        refresh_visible_track_fav_buttons=lambda: side_effects.append("refresh_visible"),
        refresh_liked_songs_dashboard=lambda force=False: side_effects.append(("refresh_liked", bool(force))),
    )

    monkeypatch.setattr(app_favorites, "submit_daemon", lambda task: task())
    monkeypatch.setattr(app_favorites.GLib, "idle_add", lambda func: func())

    app_favorites.on_track_fav_clicked(app, now_btn)

    assert backend_calls == [("track-1", True)]
    assert side_effects == ["refresh_current", "refresh_visible", ("refresh_liked", True)]

