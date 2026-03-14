"""Aggregated app handlers.

This module keeps the existing import surface for wiring while delegating
feature-specific logic to dedicated modules.
"""

import logging
import platform
import random

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

from core.executor import submit_daemon

from app.app_auth import (
    on_login_clicked,
    on_logout_clicked,
    _toggle_login_view,
    _set_login_view_pending,
    _set_overlay_handles_visible,
    _show_login_method_dialog,
    _start_login_flow,
    _open_login_url,
    _cleanup_login_dialog,
    _cancel_login_attempt,
    _build_qr_tempfile,
    _show_login_qr_dialog,
    _on_login_success_for_attempt,
    _on_login_failed,
    _on_login_failed_for_attempt,
    on_login_success,
)
from app.app_queue import (
    _get_active_queue,
    _set_play_queue,
    _is_queue_nav_selected,
    _sync_queue_handle_state,
    toggle_queue_drawer,
    close_queue_drawer,
    on_queue_track_selected,
    _refresh_queue_views,
    on_queue_remove_track_clicked,
    on_queue_clear_clicked,
)
from app.app_home_mixes import (
    refresh_liked_songs_dashboard,
    on_history_album_clicked,
    on_history_track_clicked,
    _debug_dump_button_metrics,
    build_daily_mixes,
    render_daily_mixes,
    on_daily_mix_track_selected,
    on_daily_mix_item_activated,
)

logger = logging.getLogger(__name__)


def get_sorted_playlist_tracks(self, playlist_id):
    tracks = self.playlist_mgr.get_tracks(playlist_id) if hasattr(self, "playlist_mgr") else []
    if getattr(self, "playlist_edit_mode", False):
        return tracks
    return self._sort_tracks(tracks, self.playlist_sort_field, self.playlist_sort_asc)


def on_about_clicked(self, _btn=None):
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


def on_settings_clicked(self, btn):
    if hasattr(self, "right_stack"):
        self.right_stack.set_visible_child_name("settings")


def on_volume_changed_ui(self, scale):
    if getattr(self, "_volume_ui_syncing", False):
        return
    if bool(getattr(self, "settings", {}).get("bit_perfect", False)):
        if hasattr(self, "_sync_volume_ui_state"):
            self._sync_volume_ui_state(value=100.0, source_scale=scale)
        return
    val = scale.get_value()
    self.player.set_volume(val / 100.0)
    self.settings["volume"] = int(round(val))
    self.schedule_save_settings()

    if hasattr(self, "_sync_volume_ui_state"):
        self._sync_volume_ui_state(value=val, source_scale=scale)
    if hasattr(self, "_mpris_sync_volume"):
        self._mpris_sync_volume()


def on_tech_info_clicked(self, btn):
    from services.signal_path import AudioSignalPathWindow

    win = AudioSignalPathWindow(self)
    win.present()


def on_toggle_mode(self, btn):
    self.play_mode = (self.play_mode + 1) % 4

    icon = self.MODE_ICONS.get(self.play_mode, "hiresti-mode-loop-symbolic")
    tooltip = self.MODE_TOOLTIPS.get(self.play_mode, "Loop")

    for btn in (getattr(self, "mode_btn", None), getattr(self, "now_playing_mode_btn", None)):
        if btn is not None:
            btn.set_icon_name(icon)
            btn.set_tooltip_text(tooltip)

    if self.play_mode == self.MODE_SHUFFLE or self.play_mode == self.MODE_SMART:
        self._generate_shuffle_list()
    else:
        self.shuffle_indices = []
    self.settings["play_mode"] = self.play_mode
    self.schedule_save_settings()
    if hasattr(self, "_mpris_sync_metadata"):
        self._mpris_sync_metadata()


def on_fav_clicked(self, btn):
    if not self.current_album:
        return
    is_currently_active = "active" in btn.get_css_classes()
    is_add = not is_currently_active

    def do():
        if self.backend.toggle_album_favorite(self.current_album.id, is_add):
            GLib.idle_add(lambda: self._update_fav_icon(btn, is_add))

    submit_daemon(do)


def on_artist_fav_clicked(self, btn):
    if not self.current_selected_artist:
        return
    art = self.current_selected_artist
    is_currently_active = "active" in btn.get_css_classes()
    is_add = not is_currently_active

    def do():
        if self.backend.toggle_artist_favorite(art.id, is_add):
            GLib.idle_add(lambda: self._update_fav_icon(btn, is_add))

    submit_daemon(do)


def _generate_shuffle_list(self):
    queue = self._get_active_queue()
    if not queue:
        self.shuffle_indices = []
        return

    total = len(queue)
    if total == 0:
        self.shuffle_indices = []
        return

    indices = list(range(total))

    current_idx = getattr(self, "current_track_index", -1)
    if current_idx is None:
        current_idx = -1

    if current_idx >= 0 and current_idx < total:
        if current_idx in indices:
            indices.remove(current_idx)

    random.shuffle(indices)
    self.shuffle_indices = indices
