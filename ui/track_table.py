import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


LAYOUT = {
    "index_width": 30,
    "artist_width": 130,
    "album_width": 170,
    "time_width": 64,
    "col_gap": 16,
    "head_margin_x": 32,
    "head_margin_bottom": 6,
    "row_margin_y": 6,
    "row_margin_x": 12,
    "cell_margin_end": 12,
}


def create_head_click_label(text, on_click, xalign=0.0, hexpand=False, extra_classes=None):
    classes = ["tracks-head-label", "tracks-head-click"]
    if extra_classes:
        classes.extend(extra_classes)
    lbl = Gtk.Label(label=text, xalign=xalign, css_classes=classes)
    if hexpand:
        lbl.set_hexpand(True)
        lbl.set_halign(Gtk.Align.FILL)
    tap = Gtk.GestureClick()
    tap.connect("pressed", lambda *_args: on_click(None))
    lbl.add_controller(tap)
    return lbl


def build_tracks_header(
    *,
    on_sort_title,
    on_sort_artist,
    on_sort_album,
    on_sort_time,
    title_text="Title",
    artist_text="Artist",
    album_text="Album",
    time_text="Time",
):
    head = Gtk.Box(
        spacing=LAYOUT["col_gap"],
        margin_start=LAYOUT["head_margin_x"],
        margin_end=LAYOUT["head_margin_x"],
        margin_bottom=LAYOUT["head_margin_bottom"],
        css_classes=["tracks-table-head"],
    )
    idx_head = Gtk.Label(label="#", xalign=0, css_classes=["tracks-head-label", "tracks-head-index"])
    idx_head.set_size_request(LAYOUT["index_width"], -1)
    title_head = create_head_click_label(title_text, on_sort_title, xalign=0.0, hexpand=True)
    title_head.set_halign(Gtk.Align.FILL)
    artist_head = create_head_click_label(artist_text, on_sort_artist, xalign=0.0)
    artist_head.set_size_request(LAYOUT["artist_width"], -1)
    artist_head.set_margin_end(LAYOUT["cell_margin_end"])
    album_head = create_head_click_label(album_text, on_sort_album, xalign=0.0)
    album_head.set_size_request(LAYOUT["album_width"], -1)
    album_head.set_margin_end(LAYOUT["cell_margin_end"])
    dur_head = create_head_click_label(time_text, on_sort_time, xalign=1.0, extra_classes=["tracks-head-time"])
    dur_head.set_halign(Gtk.Align.END)
    dur_head.set_size_request(LAYOUT["time_width"], -1)
    head.append(idx_head)
    head.append(title_head)
    head.append(artist_head)
    head.append(album_head)
    head.append(dur_head)
    return head, {"title": title_head, "artist": artist_head, "album": album_head, "time": dur_head}
