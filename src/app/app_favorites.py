"""
Track and artist favorite management for TidalApp.
Contains favorite toggle, fav button creation and refresh helpers.
"""
import logging

from gi.repository import Gtk, GLib

from core.executor import submit_daemon

logger = logging.getLogger(__name__)


def _current_track_fav_buttons(self):
    return [
        btn
        for btn in (
            getattr(self, "track_fav_btn", None),
            getattr(self, "now_playing_track_fav_btn", None),
        )
        if btn is not None
    ]


def _update_fav_icon(self, btn, is_active):
    if is_active:
        btn.set_icon_name("hiresti-favorite-symbolic")
        btn.add_css_class("active")
    else:
        btn.set_icon_name("hiresti-favorite-outline-symbolic")
        btn.remove_css_class("active")


def refresh_current_track_favorite_state(self):
    buttons = _current_track_fav_buttons(self)
    track = getattr(self, "playing_track", None)
    user = getattr(self.backend, "user", None)
    if not buttons:
        return
    if not track or getattr(track, "id", None) is None:
        for btn in buttons:
            self._update_fav_icon(btn, False)
            btn.set_sensitive(False)
            btn.set_visible(False)
        return
    for btn in buttons:
        btn.set_visible(True)
    if not user:
        for btn in buttons:
            self._update_fav_icon(btn, False)
            btn.set_sensitive(False)
        return

    track_id = str(track.id)
    for btn in buttons:
        btn.set_sensitive(False)

    def do():
        is_fav = self.backend.is_track_favorite(track_id)

        def apply():
            current = getattr(getattr(self, "playing_track", None), "id", None)
            if str(current) != track_id:
                return False
            for btn in _current_track_fav_buttons(self):
                self._update_fav_icon(btn, is_fav)
                btn.set_sensitive(True)
            return False

        GLib.idle_add(apply)

    submit_daemon(do)


def create_track_fav_button(self, track, css_classes=None):
    classes = css_classes or ["flat", "circular", "track-heart-btn"]
    btn = Gtk.Button(icon_name="hiresti-favorite-outline-symbolic", css_classes=classes, valign=Gtk.Align.CENTER)
    btn.set_tooltip_text("Favorite Track")
    btn._is_track_fav_btn = True
    track_id = getattr(track, "id", None)
    btn._track_fav_id = str(track_id) if track_id is not None else None
    btn._track_fav_track = track
    btn.connect("clicked", self.on_track_row_fav_clicked)
    self._refresh_track_fav_button(btn)
    return btn


def _refresh_track_fav_button(self, btn):
    track_id = getattr(btn, "_track_fav_id", None)
    user = getattr(self.backend, "user", None)
    if not track_id or not user:
        self._update_fav_icon(btn, False)
        btn.set_sensitive(False)
        return

    # is_track_favorite is a local set lookup (O(1)) — no daemon thread needed.
    is_fav = self.backend.is_track_favorite(track_id)
    self._update_fav_icon(btn, is_fav)
    btn.set_sensitive(True)


def _optimistically_remove_liked_track(self, track_id):
    track_key = str(track_id or "").strip()
    if not track_key:
        return
    cached = list(getattr(self, "liked_tracks_data", []) or [])
    if not cached:
        return
    pruned = [
        track
        for track in cached
        if str(getattr(track, "id", "") or "").strip() != track_key
    ]
    if len(pruned) == len(cached):
        return
    self.liked_tracks_data = pruned
    row = self.nav_list.get_selected_row() if getattr(self, "nav_list", None) is not None else None
    if row is not None and getattr(row, "nav_id", None) == "liked_songs":
        self.render_liked_songs_dashboard(pruned)


def _optimistically_add_liked_track(self, track):
    track_obj = track
    track_key = str(getattr(track_obj, "id", "") or "").strip()
    if not track_key:
        return
    cached = list(getattr(self, "liked_tracks_data", []) or [])
    updated = [track_obj]
    updated.extend(
        item
        for item in cached
        if str(getattr(item, "id", "") or "").strip() != track_key
    )
    self.liked_tracks_data = updated
    row = self.nav_list.get_selected_row() if getattr(self, "nav_list", None) is not None else None
    if row is not None and getattr(row, "nav_id", None) == "liked_songs":
        self.render_liked_songs_dashboard(updated)


def on_track_row_fav_clicked(self, btn):
    track_id = getattr(btn, "_track_fav_id", None)
    track_obj = getattr(btn, "_track_fav_track", None)
    if not track_id or not getattr(self.backend, "user", None):
        return

    is_currently_active = "active" in btn.get_css_classes()
    is_add = not is_currently_active
    btn.set_sensitive(False)

    def do():
        ok = self.backend.toggle_track_favorite(track_id, is_add)

        def apply():
            if getattr(btn, "_track_fav_id", None) != track_id:
                return False
            if ok:
                self._update_fav_icon(btn, is_add)
                if str(getattr(getattr(self, "playing_track", None), "id", "")) == track_id:
                    self.refresh_current_track_favorite_state()
                self.refresh_visible_track_fav_buttons()
                if is_add:
                    _optimistically_add_liked_track(self, track_obj)
                else:
                    _optimistically_remove_liked_track(self, track_id)
                self.refresh_liked_songs_dashboard(force=True)
            btn.set_sensitive(True)
            return False

        GLib.idle_add(apply)

    submit_daemon(do)


def refresh_visible_track_fav_buttons(self):
    roots = [
        getattr(self, "track_list", None),
        getattr(self, "playlist_track_list", None),
        getattr(self, "liked_track_list", None),
        getattr(self, "queue_track_list", None),
        getattr(self, "queue_drawer_list", None),
        getattr(self, "res_trk_list", None),
    ]

    def walk(widget):
        if widget is None:
            return
        if isinstance(widget, Gtk.Button) and getattr(widget, "_is_track_fav_btn", False):
            self._refresh_track_fav_button(widget)
        child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
        while child:
            walk(child)
            child = child.get_next_sibling()

    for root in roots:
        walk(root)


def on_track_fav_clicked(self, btn):
    track = getattr(self, "playing_track", None)
    if track is None or getattr(track, "id", None) is None or not getattr(self.backend, "user", None):
        return
    track_id = str(track.id)
    is_currently_active = "active" in btn.get_css_classes()
    is_add = not is_currently_active
    buttons = _current_track_fav_buttons(self)
    for target in buttons:
        target.set_sensitive(False)

    def do():
        ok = self.backend.toggle_track_favorite(track_id, is_add)

        def apply():
            current = getattr(getattr(self, "playing_track", None), "id", None)
            if str(current) != track_id:
                for target in _current_track_fav_buttons(self):
                    target.set_sensitive(True)
                return False
            if ok:
                self.refresh_current_track_favorite_state()
                self.refresh_visible_track_fav_buttons()
                if is_add:
                    _optimistically_add_liked_track(self, track)
                else:
                    _optimistically_remove_liked_track(self, track_id)
                self.refresh_liked_songs_dashboard(force=True)
            else:
                for target in _current_track_fav_buttons(self):
                    target.set_sensitive(True)
            return False

        GLib.idle_add(apply)

    submit_daemon(do)
