"""
Event handlers for TidalApp.
Contains on_* callback methods moved from main.py.
"""
import logging
import platform

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

from core.executor import submit_daemon

logger = logging.getLogger(__name__)


# Queue management methods
def _get_active_queue(self):
    """Get the current queue."""
    q = list(getattr(self, "play_queue", []) or [])
    if q:
        return q
    return list(getattr(self, "current_track_list", []) or [])


def _set_play_queue(self, tracks):
    """Set the play queue."""
    self.play_queue = list(tracks or [])
    self.shuffle_indices = []


def _is_queue_nav_selected(self):
    """Check if queue is selected in navigation."""
    row = self.nav_list.get_selected_row() if self.nav_list is not None else None
    return bool(row and getattr(row, "nav_id", None) == "queue")


def _sync_queue_handle_state(self, expanded):
    """Sync queue handle button state."""
    btn = getattr(self, "queue_btn", None)
    if btn is not None:
        btn.set_icon_name(
            "hiresti-queue-handle-right-symbolic" if expanded else "hiresti-queue-handle-left-symbolic"
        )
        btn.set_tooltip_text("Close Queue" if expanded else "Open Queue")
        if expanded:
            btn.add_css_class("active")
        else:
            btn.remove_css_class("active")
    anchor = getattr(self, "queue_anchor", None)
    if anchor is not None:
        if expanded:
            anchor.add_css_class("open")
        else:
            anchor.remove_css_class("open")


def toggle_queue_drawer(self, _btn=None):
    """Toggle queue drawer visibility."""
    revealer = getattr(self, "queue_revealer", None)
    if revealer is None:
        return
    show = not revealer.get_reveal_child()
    revealer.set_reveal_child(show)
    if getattr(self, "queue_backdrop", None) is not None:
        self.queue_backdrop.set_visible(show)
    _sync_queue_handle_state(self, show)
    if show:
        GLib.timeout_add(120, lambda: (self.render_queue_drawer(), False)[1])


def close_queue_drawer(self):
    """Close queue drawer."""
    revealer = getattr(self, "queue_revealer", None)
    if revealer is not None:
        revealer.set_reveal_child(False)
    if getattr(self, "queue_backdrop", None) is not None:
        self.queue_backdrop.set_visible(False)
    _sync_queue_handle_state(self, False)


# Playlist methods
def get_sorted_playlist_tracks(self, playlist_id):
    """Get sorted tracks from playlist."""
    tracks = self.playlist_mgr.get_tracks(playlist_id) if hasattr(self, "playlist_mgr") else []
    if getattr(self, "playlist_edit_mode", False):
        return tracks
    return self._sort_tracks(tracks, self.playlist_sort_field, self.playlist_sort_asc)


def on_about_clicked(self, _btn=None):
    """Show about dialog."""
    info_lines = [
        "A desktop TIDAL client focused on audio quality and visual experience.",
        f"Python: {platform.python_version()}",
    ]
    about = Adw.AboutWindow(
        transient_for=getattr(self, "win", None),
        modal=True,
        application_name="HiresTI",
        application_icon="hiresti",
        version=str(getattr(self, "app_version", "dev")),
        developers=["Yelanxin"],
        website="https://github.com/yelanxin/hiresTI",
        issue_url="https://github.com/yelanxin/hiresTI/issues",
        license_type=Gtk.License.GPL_3_0,
        comments="\n".join(info_lines),
    )
    about.present()


def on_login_clicked(self, btn):
    """Handle login button click."""
    if self.backend.user:
        self.user_popover.popup()
        return
    if self._login_in_progress:
        self.show_output_notice("Login already in progress.", "warn", 2200)
        if self._login_dialog is not None:
            self._login_dialog.present()
        return
    self._show_login_method_dialog()


def on_logout_clicked(self, btn):
    """Handle logout button click."""
    # Implementation in main.py
    if hasattr(self, 'backend') and self.backend.check_login():
        self.backend.session.logout()
    self._toggle_login_view(False)
    self._clear_initial_search_focus()
    while c := self.collection_content_box.get_first_child():
        self.collection_content_box.remove(c)
    logger.info("User logged out.")


def on_settings_clicked(self, btn):
    """Handle settings button click."""
    if hasattr(self, 'right_stack'):
        self.right_stack.set_visible_child_name("settings")


def on_volume_changed_ui(self, scale):
    """Handle volume slider change."""
    val = scale.get_value()
    self.player.set_volume(val / 100.0)
    self.settings["volume"] = int(round(val))
    self.schedule_save_settings()

    # Update volume icon based on level
    icon = "hiresti-volume-high-symbolic"
    if val == 0:
        icon = "hiresti-volume-muted-symbolic"
    elif val < 30:
        icon = "hiresti-volume-low-symbolic"
    elif val < 70:
        icon = "hiresti-volume-medium-symbolic"

    if self.vol_btn is not None:
        self.vol_btn.set_icon_name(icon)


def on_tech_info_clicked(self, btn):
    """Show technical info dialog."""
    from services.signal_path import AudioSignalPathWindow
    win = AudioSignalPathWindow(self)
    win.present()


def on_toggle_mode(self, btn):
    """Switch play mode: loop -> one -> shuffle -> smart -> loop."""
    self.play_mode = (self.play_mode + 1) % 4

    icon = self.MODE_ICONS.get(self.play_mode, "hiresti-mode-loop-symbolic")
    tooltip = self.MODE_TOOLTIPS.get(self.play_mode, "Loop")

    if self.mode_btn is not None:
        self.mode_btn.set_icon_name(icon)
        self.mode_btn.set_tooltip_text(tooltip)

    if self.play_mode == self.MODE_SHUFFLE or self.play_mode == self.MODE_SMART:
        self._generate_shuffle_list()
    else:
        self.shuffle_indices = []
    self.settings["play_mode"] = self.play_mode
    self.schedule_save_settings()


def on_fav_clicked(self, btn):
    """Handle favorite button click for album."""
    if not self.current_album:
        return
    is_currently_active = "active" in btn.get_css_classes()
    is_add = not is_currently_active

    def do():
        if self.backend.toggle_album_favorite(self.current_album.id, is_add):
            GLib.idle_add(lambda: self._update_fav_icon(btn, is_add))

    submit_daemon(do)


def on_artist_fav_clicked(self, btn):
    """Handle favorite button click for artist."""
    if not self.current_selected_artist:
        return
    art = self.current_selected_artist
    is_currently_active = "active" in btn.get_css_classes()
    is_add = not is_currently_active

    def do():
        if self.backend.toggle_artist_favorite(art.id, is_add):
            GLib.idle_add(lambda: self._update_fav_icon(btn, is_add))

    submit_daemon(do)
