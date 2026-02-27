"""Home/dashboard and daily-mix handlers extracted from app_handlers."""

import logging
import os
import time
from datetime import datetime, timedelta

from gi.repository import Gtk, GLib

from core.executor import submit_daemon

logger = logging.getLogger(__name__)


def refresh_liked_songs_dashboard(self, _initial_render_done=False, force=False):
    from actions import ui_actions
    row = self.nav_list.get_selected_row() if self.nav_list is not None else None
    if not row or getattr(row, "nav_id", None) != "liked_songs":
        return False

    if not getattr(self.backend, "user", None):
        self.render_liked_songs_dashboard([])
        return False

    cached_tracks = list(getattr(self, "liked_tracks_data", []) or [])
    now = time.time()
    ttl = float(getattr(self, "liked_tracks_cache_ttl_sec", 30.0) or 30.0)
    last_ts = float(getattr(self, "liked_tracks_last_fetch_ts", 0.0) or 0.0)
    if cached_tracks:
        if not _initial_render_done:
            self.render_liked_songs_dashboard(cached_tracks)
        if not force and now - last_ts <= max(0.0, ttl):
            return False

    req_id = int(getattr(self, "_liked_tracks_request_id", 0) or 0) + 1
    self._liked_tracks_request_id = req_id

    def _is_stale():
        return req_id != int(getattr(self, "_liked_tracks_request_id", 0) or 0)

    def _liked_view_active():
        current = self.nav_list.get_selected_row() if self.nav_list is not None else None
        return bool(current and getattr(current, "nav_id", None) == "liked_songs")

    def _apply_if_active(tracks):
        current = self.nav_list.get_selected_row() if self.nav_list is not None else None
        if not current or getattr(current, "nav_id", None) != "liked_songs":
            return False
        if _is_stale():
            return False
        self.render_liked_songs_dashboard(tracks)
        return False

    def task():
        if _is_stale() or (not _liked_view_active()):
            return
        if len(cached_tracks) < 100:
            head_tracks = list(self.backend.get_favorite_tracks(limit=100))
            if head_tracks and not _is_stale():
                if len(head_tracks) > len(cached_tracks):
                    GLib.idle_add(lambda: _apply_if_active(head_tracks))

        if _is_stale() or (not _liked_view_active()):
            return
        tracks = list(self.backend.get_favorite_tracks(limit=20000))
        if _is_stale():
            return
        try:
            self.backend.fav_track_ids = {
                str(getattr(t, "id", ""))
                for t in tracks
                if getattr(t, "id", None) is not None
            }
        except Exception:
            pass
        self.liked_tracks_last_fetch_ts = time.time()
        GLib.idle_add(lambda: _apply_if_active(tracks))

    submit_daemon(task)
    return False


def on_history_album_clicked(self, album):
    if album is None:
        return
    self.show_album_details(album)


def on_history_track_clicked(self, tracks, index):
    if not tracks or index < 0 or index >= len(tracks):
        return
    self.current_track_list = tracks
    self._set_play_queue(tracks)
    self._debug_dump_button_metrics("history-click:before-play")
    self.play_track(index)
    GLib.timeout_add(120, lambda: self._debug_dump_button_metrics("history-click:after-play"))


def _debug_dump_button_metrics(self, tag="ui"):
    if os.getenv("HIRES_DEBUG_BUTTONS", "0") != "1":
        return False
    if not getattr(self, "win", None):
        return False

    rows = []

    def _walk(widget):
        if isinstance(widget, Gtk.Button):
            classes = ",".join(widget.get_css_classes() or [])
            try:
                min_h, nat_h, _min_b, _nat_b = widget.measure(Gtk.Orientation.VERTICAL, -1)
            except Exception:
                min_h, nat_h = -1, -1
            try:
                alloc_h = widget.get_allocated_height()
            except Exception:
                alloc_h = -1
            ptr = hex(hash(widget))
            rows.append((ptr, classes, min_h, nat_h, alloc_h))
        child = widget.get_first_child()
        while child is not None:
            _walk(child)
            child = child.get_next_sibling()

    try:
        _walk(self.win)
    except Exception as e:
        logger.warning("BTNDBG %s failed: %s", tag, e)
        return False

    rows.sort(key=lambda r: (r[2], r[3], r[4]))
    logger.warning("BTNDBG %s count=%d", tag, len(rows))
    for ptr, classes, min_h, nat_h, alloc_h in rows:
        if nat_h <= 32 or min_h <= 32 or alloc_h <= 32:
            logger.warning(
                "BTNDBG %s ptr=%s cls=[%s] min_h=%s nat_h=%s alloc_h=%s",
                tag,
                ptr,
                classes,
                min_h,
                nat_h,
                alloc_h,
            )
    return False


def build_daily_mixes(self, days=7, per_day=8):
    per_day = max(6, int(per_day))
    entries = []
    if hasattr(self, "history_mgr") and self.history_mgr is not None:
        entries = self.history_mgr.get_recent_track_entries(limit=400)
        if not entries and getattr(self.backend, "user", None):
            for alb in self.history_mgr.get_albums()[:24]:
                tracks = self.backend.get_tracks(alb) or []
                for t in tracks[:10]:
                    entries.append(
                        {
                            "track_id": getattr(t, "id", None),
                            "track_name": getattr(t, "name", "Unknown Track"),
                            "duration": getattr(t, "duration", 0) or 0,
                            "album_id": getattr(getattr(t, "album", None), "id", getattr(alb, "id", None)),
                            "album_name": getattr(getattr(t, "album", None), "name", getattr(alb, "name", "Unknown Album")),
                            "artist": getattr(getattr(t, "artist", None), "name", "Unknown"),
                            "artist_id": getattr(getattr(t, "artist", None), "id", None),
                            "cover": getattr(getattr(t, "album", None), "cover", getattr(alb, "cover_url", None)),
                        }
                    )
                if len(entries) >= 400:
                    break
    if not entries:
        self.daily_mix_data = []
        return []

    track_stats = {}
    artist_stats = {}
    album_stats = {}
    meta_by_track = {}
    total = max(1, len(entries))

    for idx, e in enumerate(entries):
        tid = str(e.get("track_id"))
        if not tid:
            continue
        recency = max(0.2, 1.0 - (idx / total))
        track_stats[tid] = track_stats.get(tid, 0.0) + 1.6 + recency

        artist_key = str(e.get("artist_id") or e.get("artist") or "")
        if artist_key:
            artist_stats[artist_key] = artist_stats.get(artist_key, 0.0) + 1.0 + recency * 0.4

        album_key = str(e.get("album_id") or "")
        if album_key:
            album_stats[album_key] = album_stats.get(album_key, 0.0) + 0.8 + recency * 0.3

        if tid not in meta_by_track:
            meta_by_track[tid] = e

    if not meta_by_track:
        self.daily_mix_data = []
        return []

    def _score(tid):
        meta = meta_by_track[tid]
        artist_key = str(meta.get("artist_id") or meta.get("artist") or "")
        album_key = str(meta.get("album_id") or "")
        return (
            track_stats.get(tid, 0.0)
            + 0.9 * artist_stats.get(artist_key, 0.0)
            + 0.5 * album_stats.get(album_key, 0.0)
        )

    sorted_ids = sorted(meta_by_track.keys(), key=_score, reverse=True)
    mixes = []
    today = datetime.now().date()
    used_track_ids = set()

    for day_offset in range(days):
        day = today - timedelta(days=day_offset)
        day_seed = int(day.strftime("%Y%m%d"))
        if not sorted_ids:
            break
        rot = day_seed % len(sorted_ids)
        rotated = sorted_ids[rot:] + sorted_ids[:rot]
        pick_ids = []
        for tid in rotated:
            if tid in used_track_ids:
                continue
            pick_ids.append(tid)
            if len(pick_ids) >= per_day:
                break
        if len(pick_ids) < 6:
            break
        tracks = []
        for tid in pick_ids:
            local_track = self.history_mgr.to_local_track(meta_by_track[tid])
            if local_track is not None:
                tracks.append(local_track)
        if len(tracks) >= 6:
            used_track_ids.update(pick_ids)
            mixes.append(
                {
                    "date_label": day.strftime("%Y-%m-%d"),
                    "title": "Daily Mix",
                    "tracks": tracks,
                }
            )

    self.daily_mix_data = mixes
    return mixes


def render_daily_mixes(self, mixes=None):
    from actions import ui_actions
    if mixes is None:
        mixes = self.build_daily_mixes()
    ui_actions.render_daily_mixes(self, mixes)


def on_daily_mix_track_selected(self, box, row):
    if not row:
        return
    track_index = getattr(row, "daily_track_index", -1)
    daily_tracks = getattr(box, "daily_tracks", None)
    if not daily_tracks or track_index < 0 or track_index >= len(daily_tracks):
        return
    self.current_track_list = daily_tracks
    self._set_play_queue(daily_tracks)
    self.play_track(track_index)


def on_daily_mix_item_activated(self, flow, child):
    if child is None:
        return
    track_index = getattr(child, "daily_track_index", -1)
    daily_tracks = getattr(flow, "daily_tracks", None)
    if not daily_tracks or track_index < 0 or track_index >= len(daily_tracks):
        return
    self.current_track_list = daily_tracks
    self._set_play_queue(daily_tracks)
    self.play_track(track_index)
