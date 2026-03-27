"""Settings persistence helpers delegated from main.py."""

import logging

from gi.repository import GLib

from core.settings import (
    WINDOW_SIZE_DEFAULT_HEIGHT,
    WINDOW_SIZE_DEFAULT_WIDTH,
    WINDOW_SIZE_MAX_HEIGHT,
    WINDOW_SIZE_MAX_WIDTH,
    WINDOW_SIZE_MIN_HEIGHT,
    WINDOW_SIZE_MIN_WIDTH,
    save_settings as persist_settings,
)

logger = logging.getLogger(__name__)


def save_settings(self):
    try:
        persist_settings(self.settings_file, self.settings)
    except Exception as e:
        logger.warning("Failed to save settings to %s: %s", self.settings_file, e)


def schedule_save_settings(self, delay_ms=250):
    pending = getattr(self, "_settings_save_source", 0)
    if pending:
        GLib.source_remove(pending)
        self._settings_save_source = 0

    def _flush():
        self._settings_save_source = 0
        self.save_settings()
        return False

    self._settings_save_source = GLib.timeout_add(delay_ms, _flush)


def _get_startup_window_size(self):
    settings = getattr(self, "settings", {}) or {}
    width = int(WINDOW_SIZE_DEFAULT_WIDTH)
    height = int(WINDOW_SIZE_DEFAULT_HEIGHT)
    if not bool(settings.get("remember_window_size", False)):
        return width, height

    saved_width = int(settings.get("window_width", 0) or 0)
    saved_height = int(settings.get("window_height", 0) or 0)
    if WINDOW_SIZE_MIN_WIDTH <= saved_width <= WINDOW_SIZE_MAX_WIDTH:
        width = saved_width
    if WINDOW_SIZE_MIN_HEIGHT <= saved_height <= WINDOW_SIZE_MAX_HEIGHT:
        height = saved_height
    return width, height


def _remember_current_window_size(self, width=None, height=None, force=False, persist=True):
    settings = getattr(self, "settings", None)
    if not isinstance(settings, dict):
        return False
    if not force and not bool(settings.get("remember_window_size", False)):
        return False

    if width is None or height is None:
        if bool(getattr(self, "is_mini_mode", False)):
            width = int(getattr(self, "saved_width", 0) or 0)
            height = int(getattr(self, "saved_height", 0) or 0)
        else:
            win = getattr(self, "win", None)
            if win is not None:
                get_size = getattr(win, "get_size", None)
                if callable(get_size):
                    try:
                        live_size = get_size()
                        width = int(live_size[0] or 0)
                        height = int(live_size[1] or 0)
                    except Exception:
                        width = 0
                        height = 0
                try:
                    if int(width or 0) <= 0:
                        width = int(win.get_width() or 0)
                except Exception:
                    if int(width or 0) <= 0:
                        width = 0
                try:
                    if int(height or 0) <= 0:
                        height = int(win.get_height() or 0)
                except Exception:
                    if int(height or 0) <= 0:
                        height = 0
            else:
                width = 0
                height = 0
            if width <= 0:
                width = int(getattr(self, "saved_width", 0) or 0)
            if height <= 0:
                height = int(getattr(self, "saved_height", 0) or 0)

    try:
        width = int(width or 0)
        height = int(height or 0)
    except Exception:
        return False
    if not (WINDOW_SIZE_MIN_WIDTH <= width <= WINDOW_SIZE_MAX_WIDTH):
        return False
    if not (WINDOW_SIZE_MIN_HEIGHT <= height <= WINDOW_SIZE_MAX_HEIGHT):
        return False

    self.saved_width = width
    self.saved_height = height

    if (
        int(settings.get("window_width", 0) or 0) == width
        and int(settings.get("window_height", 0) or 0) == height
    ):
        return False

    settings["window_width"] = width
    settings["window_height"] = height
    if persist:
        self.schedule_save_settings()
    return True


def on_remember_window_size_toggled(self, _switch, state):
    enabled = bool(state)
    self.settings["remember_window_size"] = enabled
    if enabled:
        self._remember_current_window_size(persist=False)
    self.save_settings()


def on_window_size_changed(self, *_args):
    win = getattr(self, "win", None)
    if win is None:
        return

    width = 0
    height = 0
    try:
        width, height = win.get_default_size()
        width = int(width or 0)
        height = int(height or 0)
    except Exception:
        width = 0
        height = 0
    if width <= 0 or height <= 0:
        _remember_current_window_size(self)
        return
    _remember_current_window_size(self, width=width, height=height)


def _remember_last_nav(self, nav_id):
    if not nav_id:
        return
    self.settings["last_nav"] = nav_id
    self.settings["last_view"] = "grid_view"
    self.schedule_save_settings()


def _remember_last_view(self, view_name):
    if not view_name:
        return
    self.settings["last_view"] = view_name
    self.schedule_save_settings()


def _save_search_history(self):
    self.settings["search_history"] = list(self.search_history)[:10]
    self.schedule_save_settings()
