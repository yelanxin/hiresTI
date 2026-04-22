"""
Application lifecycle handlers for TidalApp.
Contains session restore, theme watch, window focus helpers.
"""
import logging

import gi
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib

from core.executor import submit_daemon

logger = logging.getLogger(__name__)


def _restore_session_async(self):
    def task():
        ok = self.backend.try_load_session()
        if ok:
            GLib.idle_add(self.on_login_success)
        else:
            def not_logged_in():
                self._toggle_login_view(False)
                # Ensure the sidebar has a row selected and the grid area
                # renders content for that row, instead of a blank canvas.
                try:
                    self._restore_last_view()
                except Exception:
                    logger.debug("restore_last_view failed (pre-login)", exc_info=True)
                return False
            GLib.idle_add(not_logged_in)

    submit_daemon(task)


def _setup_theme_watch(self):
    """Keep spectrum/lyrics panel background in sync with system light/dark mode."""
    self.style_manager = Adw.StyleManager.get_default()
    self.style_manager.set_color_scheme(Adw.ColorScheme.DEFAULT)
    self.style_manager.connect("notify::dark", lambda *_: self._apply_viz_panel_theme())
    self._apply_viz_panel_theme()
    self._apply_app_theme_classes()


def _apply_app_theme_classes(self):
    root = getattr(self, "main_vbox", None)
    if root is None:
        return
    root.remove_css_class("app-theme-dark")
    root.remove_css_class("app-theme-fresh")
    root.remove_css_class("app-theme-sunset")
    root.remove_css_class("app-theme-mint")
    root.remove_css_class("app-theme-retro")


def _clear_initial_search_focus(self):
    # Keep shortcuts available until user explicitly clicks/focuses the search box.
    if getattr(self, "win", None) is not None:
        try:
            self.win.set_focus(None)
        except Exception:
            pass
    return False


def _restore_last_view(self):
    nav_id = self.settings.get("last_nav", "home")
    view = self.settings.get("last_view", "grid_view")

    if view == "settings":
        self.on_settings_clicked(getattr(self, "tools_btn", None))
        return

    if view == "search_view":
        view = "grid_view"
        nav_id = "home"

    # Pre-login, Tidal-only sections render an empty canvas. Fall back to
    # the local-library Tracks view so the user lands on something
    # meaningful.
    logged_in = bool(getattr(getattr(self, "backend", None), "user", None))
    tidal_only_nav_ids = {
        "home", "new", "top", "hires", "genres", "decades", "moods",
        "collection", "liked_songs", "artists", "playlists", "history",
    }
    if not logged_in and nav_id in tidal_only_nav_ids:
        nav_id = "local_tracks"

    target = None
    child = self.nav_list.get_first_child()
    while child:
        if hasattr(child, "nav_id") and child.nav_id == nav_id:
            target = child
            break
        child = child.get_next_sibling()
    if target is None:
        child = self.nav_list.get_first_child()
        while child:
            if str(getattr(child, "nav_id", "") or "").strip():
                target = child
                break
            child = child.get_next_sibling()
    if target is not None:
        self.nav_list.select_row(target)
        self.on_nav_selected(self.nav_list, target)
