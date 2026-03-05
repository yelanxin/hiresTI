import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_configure_icon_theme_prefers_bundled_icons(monkeypatch):
    pytest.importorskip("gi")

    from app import app_bootstrap

    existing_paths = ["/tmp/system-icons", "/usr/share/icons"]
    recorded = {}

    class _FakeIconTheme:
        def get_search_path(self):
            return list(existing_paths)

        def set_search_path(self, paths):
            recorded["paths"] = list(paths)

    fake_theme = _FakeIconTheme()
    monkeypatch.setattr(app_bootstrap.Gtk.IconTheme, "get_for_display", lambda _display: fake_theme)

    fake_dirs = {
        os.path.abspath("/worktree/src/icons"),
        os.path.abspath("/worktree/icons"),
        os.path.abspath("/usr/share/icons"),
    }
    monkeypatch.setattr(app_bootstrap.os.path, "abspath", lambda path: os.path.normpath(path))
    monkeypatch.setattr(app_bootstrap.os.path, "isdir", lambda path: os.path.normpath(path) in fake_dirs)
    monkeypatch.setattr(app_bootstrap, "__file__", "/worktree/src/app/app_bootstrap.py")

    returned = app_bootstrap._configure_icon_theme(object())

    assert returned is fake_theme
    assert recorded["paths"] == [
        os.path.abspath("/worktree/src/icons"),
        os.path.abspath("/worktree/icons"),
        os.path.abspath("/usr/share/icons"),
    ]
