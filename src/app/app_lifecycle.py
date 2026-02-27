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
            GLib.idle_add(self._toggle_login_view, False)

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
        self.right_stack.set_visible_child_name("search_view")
        self.back_btn.set_sensitive(True)
        self.nav_list.select_row(None)
        self.grid_title_label.set_text("Search")
        return

    target = None
    child = self.nav_list.get_first_child()
    while child:
        if hasattr(child, "nav_id") and child.nav_id == nav_id:
            target = child
            break
        child = child.get_next_sibling()
    if target is None:
        target = self.nav_list.get_first_child()
    if target is not None:
        self.nav_list.select_row(target)
        self.on_nav_selected(self.nav_list, target)
