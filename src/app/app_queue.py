"""Queue-related handlers extracted from app_handlers."""

import logging

from gi.repository import GLib

logger = logging.getLogger(__name__)


def _get_active_queue(self):
    q = list(getattr(self, "play_queue", []) or [])
    if q:
        return q
    return list(getattr(self, "current_track_list", []) or [])


def _set_play_queue(self, tracks):
    self.play_queue = list(tracks or [])
    self.shuffle_indices = []
    if hasattr(self, "_mpris_sync_metadata"):
        self._mpris_sync_metadata()


def _is_queue_nav_selected(self):
    row = self.nav_list.get_selected_row() if self.nav_list is not None else None
    return bool(row and getattr(row, "nav_id", None) == "queue")


def _sync_queue_handle_state(self, expanded):
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
    revealer = getattr(self, "queue_revealer", None)
    if revealer is not None:
        revealer.set_reveal_child(False)
    if getattr(self, "queue_backdrop", None) is not None:
        self.queue_backdrop.set_visible(False)
    _sync_queue_handle_state(self, False)


def on_queue_track_selected(self, box, row):
    if not row:
        return
    idx = getattr(row, "queue_track_index", row.get_index())
    tracks = self._get_active_queue()
    if idx < 0 or idx >= len(tracks):
        return
    self.play_track(idx)


def _refresh_queue_views(self):
    if self._is_queue_nav_selected():
        self.render_queue_dashboard()
    if getattr(self, "queue_revealer", None) is not None and self.queue_revealer.get_reveal_child():
        self.render_queue_drawer()


def on_queue_remove_track_clicked(self, track_index):
    tracks = self._get_active_queue()
    idx = int(track_index)
    if idx < 0 or idx >= len(tracks):
        return
    removed_current = idx == int(getattr(self, "current_track_index", -1) or -1)
    tracks.pop(idx)
    self.play_queue = tracks

    if not tracks:
        self.current_track_index = -1
        self.playing_track = None
        self.playing_track_id = None
        try:
            self.player.stop()
        except Exception:
            pass
        if self.play_btn is not None:
            self.play_btn.set_icon_name("media-playback-start-symbolic")
        self.refresh_current_track_favorite_state()
        if hasattr(self, "_mpris_sync_all"):
            self._mpris_sync_all(force=True)
        GLib.idle_add(self._refresh_queue_views)
        return

    if idx < self.current_track_index:
        self.current_track_index = max(0, self.current_track_index - 1)

    if removed_current:
        new_idx = min(idx, len(tracks) - 1)
        if hasattr(self, "_mpris_sync_metadata"):
            self._mpris_sync_metadata()
        GLib.idle_add(self._refresh_queue_views)
        GLib.idle_add(lambda: self.play_track(new_idx) or False)
        return

    GLib.idle_add(self._refresh_queue_views)
    self._update_track_list_icon()
    if hasattr(self, "_mpris_sync_metadata"):
        self._mpris_sync_metadata()


def on_queue_clear_clicked(self, _btn=None):
    tracks = self._get_active_queue()
    if not tracks:
        return
    self.play_queue = []
    self.current_track_index = -1
    self.playing_track = None
    self.playing_track_id = None
    try:
        self.player.stop()
    except Exception:
        pass
    if self.play_btn is not None:
        self.play_btn.set_icon_name("media-playback-start-symbolic")
    self.refresh_current_track_favorite_state()
    if hasattr(self, "_mpris_sync_all"):
        self._mpris_sync_all(force=True)
    GLib.idle_add(self._refresh_queue_views)
