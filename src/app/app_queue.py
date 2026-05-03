"""Queue-related handlers extracted from app_handlers."""

import logging

from gi.repository import GLib, Gtk

logger = logging.getLogger(__name__)


def _get_active_queue(self):
    q = list(getattr(self, "play_queue", []) or [])
    if q:
        return q
    return list(getattr(self, "current_track_list", []) or [])


def _get_current_track_view_tracks(self):
    playlist_id = getattr(self, "current_playlist_id", None)
    if playlist_id is not None and hasattr(self, "get_sorted_playlist_tracks"):
        try:
            tracks = list(self.get_sorted_playlist_tracks(playlist_id) or [])
        except Exception:
            tracks = []
        if tracks:
            return tracks
    return list(getattr(self, "current_track_list", []) or [])


def _set_play_queue(self, tracks):
    self.play_queue = list(tracks or [])
    self.shuffle_indices = []
    if hasattr(self, "_render_now_playing_queue"):
        GLib.idle_add(lambda: (self._render_now_playing_queue(self._get_active_queue()), False)[1])
    if hasattr(self, "_mpris_sync_metadata"):
        self._mpris_sync_metadata()
    if hasattr(self, "_remote_publish_queue_event"):
        self._remote_publish_queue_event("queue_set")


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


_MINI_QUEUE_HEIGHT = 500
_MINI_BAR_HEIGHT = 85
_MINI_WIDTH = 390
_MINI_QUEUE_HEAD = 30   # header area


def toggle_mini_queue(self, _btn=None):
    """Toggle the mini-mode queue drawer open/closed."""
    revealer = getattr(self, "mini_queue_revealer", None)
    arrow = getattr(self, "mini_queue_arrow", None)
    if revealer is None:
        return
    opening = not revealer.get_reveal_child()
    if arrow is not None:
        arrow.set_icon_name("pan-up-symbolic" if opening else "pan-down-symbolic")
    if opening:
        self.render_mini_queue()
        self.bottom_bar.add_css_class("mini-queue-open")
        revealer.set_visible(True)
        revealer.set_reveal_child(True)
        self.win.set_size_request(_MINI_WIDTH, _MINI_BAR_HEIGHT + _MINI_QUEUE_HEIGHT + _MINI_QUEUE_HEAD)
    else:
        self.bottom_bar.remove_css_class("mini-queue-open")
        revealer.set_reveal_child(False)
        revealer.set_visible(False)
        self.win.set_size_request(_MINI_WIDTH, _MINI_BAR_HEIGHT)


def close_mini_queue(self):
    """Close the mini queue drawer if open."""
    revealer = getattr(self, "mini_queue_revealer", None)
    if revealer is not None and revealer.get_reveal_child():
        if getattr(self, "bottom_bar", None) is not None:
            self.bottom_bar.remove_css_class("mini-queue-open")
        revealer.set_reveal_child(False)
        revealer.set_visible(False)
        # Reset scroll height to default so it doesn't affect main mode layout.
        scroll = getattr(self, "mini_queue_scroll", None)
        if scroll is not None:
            scroll.set_size_request(-1, _MINI_QUEUE_HEIGHT)
        self.win.set_size_request(_MINI_WIDTH, _MINI_BAR_HEIGHT)
    arrow = getattr(self, "mini_queue_arrow", None)
    if arrow is not None:
        arrow.set_icon_name("pan-down-symbolic")


def _build_mini_queue_row(app, track, i, current_idx):
    """Build a two-line queue row: title on top, artist · album below."""
    row = Gtk.ListBoxRow(css_classes=["track-row"])
    row.queue_track_index = i
    row.track_id = getattr(track, "id", None)

    box = Gtk.Box(spacing=6, margin_top=2, margin_bottom=2)

    # Index / play icon stack
    stack = Gtk.Stack()
    stack.set_size_request(16, -1)
    stack.add_css_class("track-index-stack")
    num_lbl = Gtk.Label(label=str(i + 1), css_classes=["dim-label"])
    stack.add_named(num_lbl, "num")
    play_icon = Gtk.Image(icon_name="media-playback-start-symbolic")
    play_icon.add_css_class("accent")
    stack.add_named(play_icon, "icon")
    # Default to number; _update_track_list_icon will set the play icon by track_id.
    stack.set_visible_child_name("num")
    box.append(stack)

    # Title + subtitle (artist · album)
    info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1,
                   hexpand=True, valign=Gtk.Align.CENTER)
    title = getattr(track, "name", "Unknown Track")
    title_lbl = Gtk.Label(label=title, xalign=0, ellipsize=3,
                          css_classes=["track-title", "mini-queue-title"])
    title_lbl.set_tooltip_text(title)
    info.append(title_lbl)

    artist_name = getattr(getattr(track, "artist", None), "name", None) or ""
    album_name = getattr(getattr(track, "album", None), "name", None) or ""
    parts = [p for p in (artist_name, album_name) if p]
    if parts:
        sub_text = " · ".join(parts)
        sub_lbl = Gtk.Label(label=sub_text, xalign=0, ellipsize=3,
                            css_classes=["dim-label", "mini-queue-subtitle"])
        sub_lbl.set_tooltip_text(sub_text)
        info.append(sub_lbl)
    box.append(info)

    # Favorite button
    if hasattr(app, "create_track_fav_button"):
        fav_btn = app.create_track_fav_button(track)
        fav_btn.set_margin_start(2)
        fav_btn.set_margin_end(0)
        box.append(fav_btn)

    # Remove from queue button
    rm_btn = Gtk.Button(icon_name="list-remove-symbolic",
                        css_classes=["flat", "playlist-tool-btn", "queue-remove-btn"])
    rm_btn.set_tooltip_text("Remove from Queue")
    rm_btn.set_margin_start(0)
    rm_btn.set_margin_end(0)
    rm_btn.connect("clicked", lambda _b, idx=i: app.on_queue_remove_track_clicked(idx))
    box.append(rm_btn)

    row.set_child(box)
    return row


def render_mini_queue(self):
    """Populate the mini-mode queue drawer with compact track rows."""
    list_box = getattr(self, "mini_queue_list", None)
    if list_box is None:
        return
    tracks = self._get_active_queue()
    current_idx = int(getattr(self, "current_track_index", -1) or -1)

    count_lbl = getattr(self, "mini_queue_count_label", None)
    if count_lbl is not None:
        count_lbl.set_text(f"{len(tracks)} tracks")

    # Signature-based skip to avoid rebuilding unchanged queue.
    sig = (len(tracks), current_idx,
           tuple(str(getattr(t, "id", id(t))) for t in tracks[:200]))
    if getattr(self, "_mini_queue_sig", None) == sig and list_box.get_first_child() is not None:
        return

    # Clear existing rows.
    while True:
        child = list_box.get_first_child()
        if child is None:
            break
        list_box.remove(child)

    if not tracks:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        hint = Gtk.Label(
            label="Queue is empty.",
            xalign=0,
            css_classes=["dim-label"],
            margin_start=10, margin_end=10, margin_top=12, margin_bottom=12,
        )
        row.set_child(hint)
        list_box.append(row)
        self._mini_queue_sig = sig
        return

    # Show a window around the current track (max ~80 rows for performance).
    window_before, window_after = 20, 60
    total = len(tracks)
    anchor = max(0, min(current_idx, total - 1)) if total > 0 else 0
    start = max(0, anchor - window_before)
    end = min(total, anchor + window_after + 1)

    for i in range(start, end):
        row = _build_mini_queue_row(self, tracks[i], i, current_idx)
        list_box.append(row)

    # Scroll the current track into view after layout.
    if 0 <= current_idx < total:
        def _scroll_to_current():
            target_row = list_box.get_row_at_index(current_idx - start)
            if target_row is not None:
                target_row.grab_focus()
            return False
        GLib.timeout_add(80, _scroll_to_current)

    self._mini_queue_sig = sig
    if hasattr(self, "_update_track_list_icon"):
        self._update_track_list_icon(target_list=list_box)


def on_queue_track_selected(self, box, row):
    if not row:
        return
    idx = getattr(row, "queue_track_index", row.get_index())
    tracks = self._get_active_queue()
    if idx < 0 or idx >= len(tracks):
        return
    self.playback_source = {"type": "queue", "name": "Queue"}
    self.play_track(idx)


def _refresh_queue_views(self):
    if self._is_queue_nav_selected():
        self.render_queue_dashboard()
    if getattr(self, "queue_revealer", None) is not None and self.queue_revealer.get_reveal_child():
        self.render_queue_drawer()
    if hasattr(self, "_render_now_playing_queue"):
        self._render_now_playing_queue(self._get_active_queue())
    # Refresh the mini-mode queue drawer if it is currently open.
    rev = getattr(self, "mini_queue_revealer", None)
    if rev is not None and rev.get_reveal_child():
        self._mini_queue_sig = None  # force rebuild
        self.render_mini_queue()


def _play_tracks_now(self, tracks):
    queue = [track for track in list(tracks or []) if track is not None]
    if not queue:
        return {"queue_size": 0, "autoplay": False, "start_index": -1}
    self.current_track_list = list(queue)
    if hasattr(self, "_set_play_queue"):
        self._set_play_queue(queue)
    else:
        self.play_queue = list(queue)
    self.play_track(0)
    return {"queue_size": len(queue), "autoplay": True, "start_index": 0}


def _insert_queue_at(self, tracks, index, event_reason="queue_inserted"):
    additions = [track for track in list(tracks or []) if track is not None]
    base_queue = list(self._get_active_queue() if hasattr(self, "_get_active_queue") else [])
    insert_index = max(0, min(int(index), len(base_queue)))
    try:
        current_index = int(getattr(self, "current_track_index", -1))
    except Exception:
        current_index = -1

    if not additions:
        return {
            "queue_size": len(base_queue),
            "insert_index": insert_index,
            "inserted": 0,
            "current_index": current_index,
        }

    new_queue = base_queue[:insert_index] + additions + base_queue[insert_index:]
    if current_index >= insert_index:
        current_index += len(additions)

    self._remote_queue_event_suppression = int(getattr(self, "_remote_queue_event_suppression", 0) or 0) + 1
    try:
        if hasattr(self, "_set_play_queue"):
            self._set_play_queue(new_queue)
        else:
            self.play_queue = list(new_queue)
    finally:
        self._remote_queue_event_suppression = max(
            0,
            int(getattr(self, "_remote_queue_event_suppression", 1) or 1) - 1,
        )

    self.current_track_index = current_index if 0 <= current_index < len(new_queue) else -1
    if 0 <= self.current_track_index < len(new_queue):
        self.playing_track = new_queue[self.current_track_index]
        self.playing_track_id = getattr(self.playing_track, "id", None)

    if hasattr(self, "_refresh_queue_views"):
        GLib.idle_add(self._refresh_queue_views)
    if hasattr(self, "_mpris_sync_metadata"):
        self._mpris_sync_metadata()
    if hasattr(self, "_remote_publish_queue_event"):
        self._remote_publish_queue_event(str(event_reason or "queue_inserted"))

    return {
        "queue_size": len(new_queue),
        "insert_index": insert_index,
        "inserted": len(additions),
        "current_index": self.current_track_index,
    }


def _insert_queue_next(self, tracks):
    try:
        current_index = int(getattr(self, "current_track_index", -1))
    except Exception:
        current_index = -1
    base_queue = list(self._get_active_queue() if hasattr(self, "_get_active_queue") else [])
    insert_index = current_index + 1 if 0 <= current_index < len(base_queue) else 0
    return _insert_queue_at(self, tracks, insert_index)


def _show_play_next_notice(self, tracks, played_now=False):
    notice = getattr(self, "show_output_notice", None)
    if not callable(notice):
        return
    items = [track for track in list(tracks or []) if track is not None]
    if not items:
        return
    count = len(items)
    if count == 1:
        title = str(getattr(items[0], "name", "Unknown Track") or "Unknown Track")
        text = f"Playing now: {title}" if played_now else f"Queued next: {title}"
    else:
        text = f"Playing {count} tracks now" if played_now else f"Added {count} tracks to play next"
    notice(text, "ok", 2400)


def on_play_next_track_clicked(self, track):
    if track is None:
        return
    items = [track]
    if getattr(self, "playing_track", None) is None:
        _play_tracks_now(self, items)
        _show_play_next_notice(self, items, played_now=True)
        return
    _insert_queue_next(self, items)
    _show_play_next_notice(self, items, played_now=False)


def on_add_track_to_queue_clicked(self, track):
    if track is None:
        return
    items = [track]
    if getattr(self, "playing_track", None) is None:
        _play_tracks_now(self, items)
        _show_add_to_queue_notice(self, items, played_now=True)
        return
    base_queue = list(self._get_active_queue() if hasattr(self, "_get_active_queue") else [])
    _insert_queue_at(self, items, len(base_queue), event_reason="queue_appended")
    _show_add_to_queue_notice(self, items, played_now=False)


def _show_add_to_queue_notice(self, tracks, played_now=False):
    notice = getattr(self, "show_output_notice", None)
    if not callable(notice):
        return
    items = [track for track in list(tracks or []) if track is not None]
    if not items:
        return
    count = len(items)
    if count == 1:
        title = str(getattr(items[0], "name", "Unknown Track") or "Unknown Track")
        text = f"Playing now: {title}" if played_now else f"Added to queue: {title}"
    else:
        text = f"Playing {count} tracks now" if played_now else f"Added {count} tracks to queue"
    notice(text, "ok", 2400)


def on_play_next_current_tracks_clicked(self, _btn=None):
    tracks = _get_current_track_view_tracks(self)
    if not tracks:
        return
    if getattr(self, "playing_track", None) is None:
        _play_tracks_now(self, tracks)
        _show_play_next_notice(self, tracks, played_now=True)
        return
    _insert_queue_next(self, tracks)
    _show_play_next_notice(self, tracks, played_now=False)


def on_add_current_tracks_to_queue_clicked(self, _btn=None):
    tracks = _get_current_track_view_tracks(self)
    if not tracks:
        return
    if getattr(self, "playing_track", None) is None:
        _play_tracks_now(self, tracks)
        _show_add_to_queue_notice(self, tracks, played_now=True)
        return
    base_queue = list(self._get_active_queue() if hasattr(self, "_get_active_queue") else [])
    _insert_queue_at(self, tracks, len(base_queue), event_reason="queue_appended")
    _show_add_to_queue_notice(self, tracks, played_now=False)


def on_queue_remove_track_clicked(self, track_index):
    tracks = self._get_active_queue()
    idx = int(track_index)
    if idx < 0 or idx >= len(tracks):
        return
    removed_current = idx == int(getattr(self, "current_track_index", -1))
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
        if hasattr(self, "_remote_publish_queue_event"):
            self._remote_publish_queue_event("queue_removed")
        if hasattr(self, "_remote_publish_playback_event"):
            self._remote_publish_playback_event("queue_cleared")
        GLib.idle_add(self._refresh_queue_views)
        return

    if idx < self.current_track_index:
        self.current_track_index = max(0, self.current_track_index - 1)

    if removed_current:
        new_idx = min(idx, len(tracks) - 1)
        if hasattr(self, "_mpris_sync_metadata"):
            self._mpris_sync_metadata()
        if hasattr(self, "_remote_publish_queue_event"):
            self._remote_publish_queue_event("queue_removed")
        GLib.idle_add(self._refresh_queue_views)
        GLib.idle_add(lambda: self.play_track(new_idx) or False)
        return

    GLib.idle_add(self._refresh_queue_views)
    self._update_track_list_icon()
    if hasattr(self, "_mpris_sync_metadata"):
        self._mpris_sync_metadata()
    if hasattr(self, "_remote_publish_queue_event"):
        self._remote_publish_queue_event("queue_removed")


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
    if hasattr(self, "_remote_publish_queue_event"):
        self._remote_publish_queue_event("queue_cleared")
    if hasattr(self, "_remote_publish_playback_event"):
        self._remote_publish_playback_event("queue_cleared")
    GLib.idle_add(self._refresh_queue_views)
