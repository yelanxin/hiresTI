import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from app import app_tray


class _Clipboard:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class _Display:
    def __init__(self):
        self.clipboard = _Clipboard()

    def get_clipboard(self):
        return self.clipboard


class _Window:
    def __init__(self, display):
        self._display = display

    def get_display(self):
        return self._display


def test_share_from_tray_copies_repo_url(monkeypatch):
    display = _Display()
    app = SimpleNamespace(win=_Window(display))

    monkeypatch.setattr(app_tray.GLib, "idle_add", lambda func: func())

    app_tray._share_from_tray(app)

    assert display.clipboard.value == "https://github.com/yelanxin/hiresTI"


def test_copy_share_url_to_clipboard_returns_true_when_copied():
    display = _Display()
    app = SimpleNamespace(win=_Window(display))

    assert app_tray._copy_share_url_to_clipboard(app) is True
    assert display.clipboard.value == "https://github.com/yelanxin/hiresTI"
