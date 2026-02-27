"""
Search and track selection handlers for TidalApp.
Contains search batch actions, pagination, track selection and search view builder.
"""
import logging

from gi.repository import GLib

from core.executor import submit_daemon

logger = logging.getLogger(__name__)


def _build_search_view(self):
    from ui import views_builders as ui_views_builders
    from actions import ui_actions
    ui_views_builders.build_search_view(self)
    ui_actions.render_search_history(self)


def on_search_track_selected(self, box, row):
    if not row:
        return
    idx = getattr(row, "search_track_index", row.get_index())
    if idx < len(self.search_track_data):
        self.current_track_list = self.search_track_data
        self._set_play_queue(self.search_track_data)
        self.play_track(idx)


def on_search_history_track_selected(self, box, row):
    if not row:
        return
    idx = row.get_index()
    tracks = list(getattr(self, "search_history_track_data", []) or [])
    if idx < 0 or idx >= len(tracks):
        return
    self.current_track_list = tracks
    self._set_play_queue(tracks)
    self.play_track(idx)


def on_track_selected(self, box, row):
    if not row:
        return
    idx = row.get_index()
    self._set_play_queue(getattr(self, "current_track_list", []))
    self.play_track(idx)


def on_player_art_clicked(self, gest, n, x, y):
    if self.playing_track:
        track = self.playing_track
        if hasattr(track, 'album') and track.album:
            self.show_album_details(track.album)


def on_search_track_checkbox_toggled(self, _cb, track_index, checked):
    if not isinstance(getattr(self, "search_selected_indices", None), set):
        self.search_selected_indices = set()
    if checked:
        self.search_selected_indices.add(int(track_index))
    else:
        self.search_selected_indices.discard(int(track_index))
    self._update_search_batch_add_state()


def _update_search_batch_add_state(self):
    btn = getattr(self, "add_selected_tracks_btn", None)
    count = len(getattr(self, "search_selected_indices", set()) or set())
    user_ready = bool(getattr(self.backend, "user", None))
    if btn is not None:
        btn.set_sensitive(count > 0)
        btn.set_label(f"Add Selected ({count})" if count > 0 else "Add Selected")
    like_btn = getattr(self, "like_selected_tracks_btn", None)
    if like_btn is not None:
        like_btn.set_sensitive(user_ready and count > 0)
        like_btn.set_label(f"Like Selected ({count})" if count > 0 else "Like Selected")


def on_add_selected_search_tracks(self, _btn=None):
    selected = sorted(list(getattr(self, "search_selected_indices", set()) or []))
    tracks = []
    for idx in selected:
        if 0 <= idx < len(self.search_track_data):
            tracks.append(self.search_track_data[idx])
    if not tracks:
        return
    self.on_add_tracks_to_playlist(tracks)


def on_like_selected_search_tracks(self, _btn=None):
    if not getattr(self.backend, "user", None):
        return
    selected = sorted(list(getattr(self, "search_selected_indices", set()) or []))
    tracks = []
    for idx in selected:
        if 0 <= idx < len(self.search_track_data):
            tracks.append(self.search_track_data[idx])
    if not tracks:
        return

    add_btn = getattr(self, "add_selected_tracks_btn", None)
    like_btn = getattr(self, "like_selected_tracks_btn", None)
    if add_btn is not None:
        add_btn.set_sensitive(False)
    if like_btn is not None:
        like_btn.set_sensitive(False)

    def do():
        liked = 0
        skipped = 0
        failed = 0
        fav_ids = getattr(self.backend, "fav_track_ids", set()) or set()
        for t in tracks:
            track_id = str(getattr(t, "id", "") or "").strip()
            if not track_id:
                failed += 1
                continue
            if track_id in fav_ids:
                skipped += 1
                continue
            if self.backend.toggle_track_favorite(track_id, True):
                liked += 1
            else:
                failed += 1

        def apply():
            self.refresh_visible_track_fav_buttons()
            self.refresh_current_track_favorite_state()
            self._update_search_batch_add_state()
            msg = f"Liked {liked}"
            if skipped:
                msg += f", skipped {skipped}"
            if failed:
                msg += f", failed {failed}"
            self.show_output_notice(msg, "ok" if failed == 0 else "warn", 2800)
            return False

        GLib.idle_add(apply)

    submit_daemon(do)


def on_search_tracks_prev_page(self, _btn=None):
    from actions import ui_actions
    self.search_tracks_page = max(0, int(getattr(self, "search_tracks_page", 0) or 0) - 1)
    ui_actions.render_search_tracks_page(self)


def on_search_tracks_next_page(self, _btn=None):
    from actions import ui_actions
    self.search_tracks_page = int(getattr(self, "search_tracks_page", 0) or 0) + 1
    ui_actions.render_search_tracks_page(self)
