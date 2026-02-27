"""Settings persistence helpers delegated from main.py."""

import logging

from gi.repository import GLib

from core.settings import save_settings as persist_settings

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
