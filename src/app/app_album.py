"""
Album and track rendering for TidalApp.
Contains track list display, sort, playback helpers and album flow UI.
"""
import logging

from gi.repository import Gtk, GLib

from core.executor import submit_daemon

logger = logging.getLogger(__name__)


def on_grid_item_activated(self, flow, child):
    if not child:
        return
    data = getattr(child, "data_item", None)
    if not data:
        return
    obj = data.get("obj")

    if data["type"] == "Track":
        self._play_single_track(obj)
        return
    if data["type"] == "Artist":
        self.on_artist_clicked(obj)
        return
    self.show_album_details(obj)


def _play_single_track(self, track):
    self.current_track_list = [track]
    self._set_play_queue([track])
    self.play_track(0)


def _sort_tracks(self, tracks, field, asc=True):
    items = list(tracks or [])
    if not field:
        return items

    def _artist_name(t):
        return str(getattr(getattr(t, "artist", None), "name", "") or "").lower()

    def _album_name(t):
        return str(getattr(getattr(t, "album", None), "name", "") or "").lower()

    def _title(t):
        return str(getattr(t, "name", "") or "").lower()

    if field == "title":
        key_func = _title
    elif field == "artist":
        key_func = _artist_name
    elif field == "album":
        key_func = _album_name
    elif field == "time":
        key_func = lambda t: int(getattr(t, "duration", 0) or 0)
    else:
        return items
    return sorted(items, key=key_func, reverse=not asc)


def _format_sort_label(self, base, field, active_field, asc):
    if field != active_field:
        return base
    return f"{base} {'▲' if asc else '▼'}"


def _update_album_sort_headers(self):
    btns = getattr(self, "album_sort_buttons", {}) or {}
    if not btns:
        return
    labels = {
        "title": "Title",
        "artist": "Artist",
        "album": "Album",
        "time": "Time",
    }
    for field, btn in btns.items():
        if field in labels:
            text = self._format_sort_label(labels[field], field, self.album_sort_field, self.album_sort_asc)
            head_lbl = getattr(btn, "_head_label", None)
            if head_lbl is not None:
                head_lbl.set_text(text)
            elif hasattr(btn, "set_text"):
                btn.set_text(text)
            else:
                btn.set_label(text)


def load_album_tracks(self, tracks):
    self.album_track_source = list(tracks or [])
    self._render_album_tracks()


def _render_album_tracks(self):
    tracks = self._sort_tracks(self.album_track_source, self.album_sort_field, self.album_sort_asc)
    self.populate_tracks(tracks)
    self._update_album_sort_headers()


def on_album_sort_clicked(self, field):
    if self.album_sort_field == field:
        self.album_sort_asc = not self.album_sort_asc
    else:
        self.album_sort_field = field
        self.album_sort_asc = True
    self._render_album_tracks()


def _update_track_list_icon(self, target_list=None):
    """刷新列表图标：当前播放的显示 ▶，其他的显示数字"""
    if self.playing_track_id and not getattr(self, "_playing_pulse_source", 0):
        self._playing_pulse_source = GLib.timeout_add(1000, self._tick_playing_row_pulse)
    if not self.playing_track_id and getattr(self, "_playing_pulse_source", 0):
        GLib.source_remove(self._playing_pulse_source)
        self._playing_pulse_source = 0
        self._playing_pulse_on = False

    targets = []
    if target_list is not None:
        targets.append(target_list)
    else:
        if self.track_list is not None:
            targets.append(self.track_list)
        if getattr(self, "liked_track_list", None) is not None:
            targets.append(self.liked_track_list)
        if getattr(self, "playlist_track_list", None) is not None:
            targets.append(self.playlist_track_list)
        if getattr(self, "queue_track_list", None) is not None:
            targets.append(self.queue_track_list)
        if getattr(self, "queue_drawer_list", None) is not None:
            targets.append(self.queue_drawer_list)
        if not targets:
            return

    for tl in targets:
        row = tl.get_first_child()
        while row:
            if hasattr(row, "track_id"):
                box = row.get_child()
                if box:
                    stack = box.get_first_child()
                    if isinstance(stack, Gtk.Stack):
                        if row.track_id == self.playing_track_id:
                            stack.set_visible_child_name("icon")
                            row.add_css_class("playing-row")
                            if getattr(self, "_playing_pulse_on", False):
                                row.add_css_class("playing-row-pulse")
                            else:
                                row.remove_css_class("playing-row-pulse")
                        else:
                            stack.set_visible_child_name("num")
                            row.remove_css_class("playing-row")
                            row.remove_css_class("playing-row-pulse")
            row = row.get_next_sibling()


def _tick_playing_row_pulse(self):
    if not self.playing_track_id:
        self._playing_pulse_source = 0
        self._playing_pulse_on = False
        self._update_track_list_icon()
        return False
    self._playing_pulse_on = not self._playing_pulse_on
    self._update_track_list_icon()
    return True


def on_header_artist_clicked(self, gest, n, x, y):
    if self.current_album:
        artist_obj = None
        if hasattr(self.current_album, "artist") and self.current_album.artist:
            artist_obj = self.current_album.artist

        if not artist_obj or isinstance(artist_obj, str):
            return

        artist_id = getattr(artist_obj, "id", None)
        artist_name = getattr(artist_obj, "name", "").strip()
        if not artist_id and not artist_name:
            return

        def resolve_artist():
            resolved = self.backend.resolve_artist(artist_id=artist_id, artist_name=artist_name)
            if not resolved:
                logger.info("Artist resolve failed for history entry: id=%s name=%s", artist_id, artist_name)
                return
            GLib.idle_add(self.on_artist_clicked, resolved)

        submit_daemon(resolve_artist)


def create_album_flow(self):
    section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section", "home-generic-section"])
    self.main_flow = Gtk.FlowBox(
        valign=Gtk.Align.START,
        max_children_per_line=30,
        selection_mode=Gtk.SelectionMode.NONE,
        column_spacing=24,
        row_spacing=28,
        css_classes=["home-flow"],
    )
    self.main_flow.connect("child-activated", self.on_grid_item_activated)
    section_box.append(self.main_flow)
    self.collection_content_box.append(section_box)


def _update_list_ui(self, index):
    playing_id = getattr(self, "playing_track_id", None)
    if not playing_id:
        return
    candidates = [
        getattr(self, "track_list", None),
        getattr(self, "liked_track_list", None),
        getattr(self, "playlist_track_list", None),
    ]
    for track_list in candidates:
        if track_list is None:
            continue
        try:
            row = track_list.get_first_child()
            while row:
                if getattr(row, "track_id", None) == playing_id:
                    track_list.select_row(row)
                    break
                row = row.get_next_sibling()
        except Exception as e:
            logger.warning("List update failed: %s", e)


def _get_tidal_image_url(self, uuid, width=320, height=320):
    if not uuid:
        return None
    if isinstance(uuid, str) and ("http" in uuid or "file://" in uuid):
        return uuid
    try:
        path = uuid.replace("-", "/")
        return f"https://resources.tidal.com/images/{path}/{width}x{height}.jpg"
    except Exception as e:
        logger.warning("Failed to build TIDAL image URL from uuid '%s': %s", uuid, e)
        return None
