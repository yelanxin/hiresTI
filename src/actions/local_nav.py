"""UI handlers for LIBRARY / MUSIC sidebar groups (local-library sources).

Layout:
    LIBRARY  -> Local Folders  (manage scanned folders)
    MUSIC    -> Tracks / Albums / Artists  (browse scanned content)

Rendering is intentionally simple — we reuse existing album helpers where
possible (`_build_my_albums_style_button`, `show_album_details`) and write
a thin list view for tracks / artists.
"""

from __future__ import annotations

import logging
import os
from threading import Thread

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

logger = logging.getLogger(__name__)

_LOCAL_NAV_IDS = ("local_folders", "local_tracks", "local_albums", "local_artists")


def is_local_nav_id(nav_id: str) -> bool:
    return str(nav_id or "") in _LOCAL_NAV_IDS


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _clear(container) -> None:
    while child := container.get_first_child():
        container.remove(child)


def _set_grid_title(app, title: str, subtitle: str = "") -> None:
    if hasattr(app, "grid_title_label") and app.grid_title_label is not None:
        app.grid_title_label.set_text(title)
    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
        app.grid_subtitle_label.set_text(subtitle)


def _empty_state(container, title: str, hint: str = "") -> None:
    box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=6,
        margin_top=24,
        margin_start=8,
    )
    box.append(Gtk.Label(label=title, xalign=0, css_classes=["home-section-title"]))
    if hint:
        box.append(Gtk.Label(label=hint, xalign=0, css_classes=["dim-label"]))
    container.append(box)


def _format_duration(seconds: float) -> str:
    s = int(seconds or 0)
    if s <= 0:
        return ""
    m, s = divmod(s, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ----------------------------------------------------------------------
# Local Folders (LIBRARY section)
# ----------------------------------------------------------------------

def render_local_folders(app) -> None:
    _set_grid_title(app, "Local Folders", "Folders scanned into your local library")
    _clear(app.collection_content_box)

    lib = getattr(app, "local_library", None)
    if lib is None:
        _empty_state(
            app.collection_content_box,
            "Local library unavailable",
            "Scanner is disabled — check logs for initialization errors.",
        )
        return

    header = Gtk.Box(spacing=8, margin_top=4, margin_bottom=12)
    add_btn = Gtk.Button(label="Add folder…", css_classes=["suggested-action"])
    add_btn.connect("clicked", lambda _b: _on_add_folder_clicked(app))
    header.append(add_btn)

    rescan_all = Gtk.Button(label="Rescan all", css_classes=["flat"])
    rescan_all.connect("clicked", lambda _b: _on_rescan_all_clicked(app))
    header.append(rescan_all)

    app.collection_content_box.append(header)

    folders = lib.list_folders()
    if not folders:
        _empty_state(
            app.collection_content_box,
            "No folders yet",
            "Click \"Add folder…\" to scan a directory of music files.",
        )
        return

    list_box = Gtk.ListBox(css_classes=["boxed-list"])
    app.collection_content_box.append(list_box)

    for src in folders:
        row = _build_folder_row(app, src)
        list_box.append(row)


def _build_folder_row(app, src: dict) -> Gtk.ListBoxRow:
    row = Gtk.ListBoxRow()
    row.set_activatable(False)
    row.set_selectable(False)

    hb = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=12,
        margin_top=10, margin_bottom=10, margin_start=12, margin_end=12,
    )

    icon = Gtk.Image.new_from_icon_name("folder-music-symbolic")
    icon.set_pixel_size(24)
    hb.append(icon)

    meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
    name_lbl = Gtk.Label(
        label=str(src.get("name") or os.path.basename(str(src.get("location") or ""))),
        xalign=0,
        ellipsize=Pango.EllipsizeMode.END,
        css_classes=["heading"],
    )
    path_lbl = Gtk.Label(
        label=str(src.get("location") or ""),
        xalign=0,
        ellipsize=Pango.EllipsizeMode.MIDDLE,
        css_classes=["dim-label", "caption"],
    )
    path_lbl.set_tooltip_text(str(src.get("location") or ""))

    count = 0
    lib = getattr(app, "local_library", None)
    if lib is not None:
        try:
            count = lib.folder_track_count(int(src["id"]))
        except Exception:
            logger.debug("folder_track_count failed", exc_info=True)
    status_parts = [f"{count} tracks"]
    if src.get("last_scanned_at"):
        import datetime as _dt
        ts = _dt.datetime.fromtimestamp(float(src["last_scanned_at"]))
        status_parts.append("scanned " + ts.strftime("%Y-%m-%d %H:%M"))
    else:
        status_parts.append("never scanned")
    status_lbl = Gtk.Label(label=" • ".join(status_parts), xalign=0, css_classes=["dim-label", "caption"])

    meta.append(name_lbl)
    meta.append(path_lbl)
    meta.append(status_lbl)
    hb.append(meta)

    rescan_btn = Gtk.Button(label="Rescan", css_classes=["flat"])
    rescan_btn.connect("clicked", lambda _b, sid=int(src["id"]): _on_rescan_folder_clicked(app, sid))
    hb.append(rescan_btn)

    remove_btn = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat", "circular"])
    remove_btn.set_tooltip_text("Remove folder from library")
    remove_btn.connect("clicked", lambda _b, sid=int(src["id"]), name=str(src.get("name") or ""): _on_remove_folder_clicked(app, sid, name))
    hb.append(remove_btn)

    row.set_child(hb)
    return row


def _on_add_folder_clicked(app) -> None:
    dialog = Gtk.FileDialog(title="Choose a music folder")
    try:
        dialog.set_modal(True)
    except Exception:
        pass

    def _on_picked(dlg, result):
        try:
            folder = dlg.select_folder_finish(result)
        except GLib.Error as exc:
            logger.debug("folder dialog cancelled: %s", exc)
            return
        except Exception:
            logger.debug("folder dialog failed", exc_info=True)
            return
        if folder is None:
            return
        path = folder.get_path()
        if not path or not os.path.isdir(path):
            logger.info("picked folder is not a directory: %r", path)
            return
        _add_and_scan_folder(app, path)

    parent = getattr(app, "win", None)
    dialog.select_folder(parent, None, _on_picked)


def _add_and_scan_folder(app, path: str) -> None:
    lib = getattr(app, "local_library", None)
    if lib is None:
        return
    try:
        sid = lib.add_folder(path)
    except Exception:
        logger.exception("add_folder failed for %s", path)
        return
    logger.info("local source added: id=%s location=%s", sid, path)
    _start_scan(app, sid, path)
    render_local_folders(app)


def _on_rescan_folder_clicked(app, source_id: int) -> None:
    lib = getattr(app, "local_library", None)
    if lib is None:
        return
    folders = {int(s["id"]): s for s in lib.list_folders()}
    src = folders.get(int(source_id))
    if not src:
        return
    _start_scan(app, source_id, str(src.get("location") or ""))


def _on_rescan_all_clicked(app) -> None:
    lib = getattr(app, "local_library", None)
    if lib is None:
        return
    for src in lib.list_folders():
        _start_scan(app, int(src["id"]), str(src.get("location") or ""))


def _on_remove_folder_clicked(app, source_id: int, name: str) -> None:
    lib = getattr(app, "local_library", None)
    if lib is None:
        return

    parent = getattr(app, "win", None)
    dialog = Gtk.AlertDialog()
    try:
        dialog.set_modal(True)
    except Exception:
        pass
    dialog.set_message(f"Remove \"{name or 'this folder'}\" from library?")
    dialog.set_detail("The files on disk are not touched. All scanned tracks for this folder will be removed from the library.")
    dialog.set_buttons(["Cancel", "Remove"])
    dialog.set_cancel_button(0)
    dialog.set_default_button(1)

    def _on_done(dlg, result):
        try:
            idx = dlg.choose_finish(result)
        except Exception:
            idx = 0
        if idx == 1:
            try:
                lib.remove_folder(int(source_id))
            except Exception:
                logger.exception("remove_folder failed")
            render_local_folders(app)

    dialog.choose(parent, None, _on_done)


# ----------------------------------------------------------------------
# scanner progress UI
# ----------------------------------------------------------------------

def _start_scan(app, source_id: int, root: str) -> None:
    lib = getattr(app, "local_library", None)
    if lib is None:
        return

    state = getattr(app, "_local_scan_state", None)
    if state is None:
        state = {"active": 0, "totals": {}, "banner": None, "spinner": None,
                 "label": None, "cancel_events": {}}
        app._local_scan_state = state

    _ensure_scan_banner(app, state)
    state["active"] += 1
    state["totals"][int(source_id)] = {"total": 0, "current": "", "done": False}
    _update_scan_banner(app, state)

    def on_progress(summary: dict):
        state["totals"][int(source_id)] = {
            "total": int(summary.get("total") or 0),
            "current": str(summary.get("current") or ""),
            "done": bool(summary.get("done") or False),
        }
        _update_scan_banner(app, state)

    def on_done(summary: dict):
        logger.info(
            "local scan done: source=%s added=%s updated=%s removed=%s skipped=%s errors=%s total=%s",
            source_id,
            summary.get("added"), summary.get("updated"), summary.get("removed"),
            summary.get("skipped"), summary.get("errors"), summary.get("total"),
        )
        state["active"] = max(0, state["active"] - 1)
        state["totals"][int(source_id)] = {
            "total": int(summary.get("total") or 0),
            "current": "",
            "done": True,
        }
        _update_scan_banner(app, state)
        if state["active"] == 0:
            _hide_scan_banner(app, state)
            _refresh_current_local_view(app)

    handle = lib.rescan_folder(int(source_id), on_progress=on_progress, on_done=on_done)
    if handle is not None:
        thread, cancel_event = handle
        state["cancel_events"][int(source_id)] = cancel_event


def _ensure_scan_banner(app, state: dict) -> None:
    if state.get("banner") is not None:
        return
    container = getattr(app, "collection_content_box", None)
    parent = container.get_parent() if container is not None else None
    # Attach the banner to the grid view's outer column so it stays visible
    # across view navigations. Fallback: prepend to collection_content_box.
    banner = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=8,
        css_classes=["osd"],
        margin_start=12, margin_end=12, margin_top=8, margin_bottom=4,
    )
    spinner = Gtk.Spinner()
    spinner.start()
    label = Gtk.Label(label="Scanning…", xalign=0, hexpand=True,
                      ellipsize=Pango.EllipsizeMode.MIDDLE)
    banner.append(spinner)
    banner.append(label)
    state["banner"] = banner
    state["spinner"] = spinner
    state["label"] = label
    # Mount: insert banner at the top of the outer grid column if possible.
    grid_col = getattr(app, "grid_outer_vbox", None) or parent
    if grid_col is not None and hasattr(grid_col, "prepend"):
        try:
            grid_col.prepend(banner)
            return
        except Exception:
            pass
    if container is not None:
        container.prepend(banner)


def _hide_scan_banner(app, state: dict) -> None:
    banner = state.get("banner")
    spinner = state.get("spinner")
    if spinner is not None:
        try:
            spinner.stop()
        except Exception:
            pass
    if banner is not None and banner.get_parent() is not None:
        parent = banner.get_parent()
        try:
            parent.remove(banner)
        except Exception:
            pass
    state["banner"] = None
    state["spinner"] = None
    state["label"] = None


def _update_scan_banner(app, state: dict) -> None:
    label = state.get("label")
    if label is None:
        return
    totals = state.get("totals") or {}
    total = sum(int(v.get("total") or 0) for v in totals.values())
    current = ""
    for v in totals.values():
        cur = str(v.get("current") or "")
        if cur:
            current = cur
            break
    if current:
        label.set_text(f"Scanning… {total} files — {os.path.basename(current)}")
    else:
        label.set_text(f"Scanning… {total} files")


def _refresh_current_local_view(app) -> None:
    nav_list = getattr(app, "nav_list", None)
    row = nav_list.get_selected_row() if nav_list is not None else None
    nav_id = str(getattr(row, "nav_id", "") or "") if row is not None else ""
    if nav_id == "local_folders":
        render_local_folders(app)
    elif nav_id == "local_tracks":
        render_local_tracks(app)
    elif nav_id == "local_albums":
        render_local_albums(app)
    elif nav_id == "local_artists":
        render_local_artists(app)


# ----------------------------------------------------------------------
# Tracks / Albums / Artists (MUSIC section)
# ----------------------------------------------------------------------

def render_local_tracks(app) -> None:
    _set_grid_title(app, "Tracks", "All tracks from your local folders")
    _clear(app.collection_content_box)

    lib = getattr(app, "local_library", None)
    if lib is None:
        _empty_state(app.collection_content_box, "Local library unavailable")
        return

    loading = Gtk.Label(label="Loading…", xalign=0, css_classes=["dim-label"],
                        margin_start=8, margin_top=8)
    app.collection_content_box.append(loading)

    def _fetch():
        tracks = list(lib.get_tracks())
        GLib.idle_add(lambda: (_render_tracks_body(app, tracks), False)[1])

    Thread(target=_fetch, daemon=True).start()


def _render_tracks_body(app, tracks: list) -> None:
    _clear(app.collection_content_box)

    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
        app.grid_subtitle_label.set_text(f"{len(tracks)} tracks")

    if not tracks:
        _empty_state(
            app.collection_content_box,
            "No local tracks yet",
            "Add a folder under Library → Local Folders to get started.",
        )
        return

    toolbar = Gtk.Box(spacing=8, margin_top=4, margin_bottom=8)
    play_all = Gtk.Button(label="Play all", css_classes=["suggested-action"])
    play_all.connect("clicked", lambda _b: _play_tracks(app, tracks, 0))
    toolbar.append(play_all)
    shuffle = Gtk.Button(label="Shuffle", css_classes=["flat"])
    def _shuffle(_b):
        import random
        shuffled = list(tracks)
        random.shuffle(shuffled)
        _play_tracks(app, shuffled, 0)
    shuffle.connect("clicked", _shuffle)
    toolbar.append(shuffle)
    app.collection_content_box.append(toolbar)

    scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    list_box = Gtk.ListBox(css_classes=["tracks-list"])
    scroller.set_child(list_box)
    app.collection_content_box.append(scroller)

    for idx, t in enumerate(tracks):
        list_box.append(_build_track_row(app, tracks, idx))


def _build_track_row(app, tracks: list, idx: int) -> Gtk.ListBoxRow:
    t = tracks[idx]
    row = Gtk.ListBoxRow()
    row.add_css_class("track-row")

    box = Gtk.Box(
        spacing=10,
        margin_top=6, margin_bottom=6,
        margin_start=10, margin_end=10,
    )

    num = Gtk.Label(label=str(idx + 1), xalign=1, css_classes=["dim-label"])
    num.set_size_request(36, -1)
    box.append(num)

    title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
    title_lbl = Gtk.Label(
        label=str(getattr(t, "name", "") or ""),
        xalign=0,
        ellipsize=Pango.EllipsizeMode.END,
        css_classes=["track-title"],
    )
    artist_name = getattr(getattr(t, "artist", None), "name", "") or ""
    album_name = getattr(getattr(t, "album", None), "name", "") or ""
    sub_text = " — ".join(x for x in [artist_name, album_name] if x)
    sub_lbl = Gtk.Label(
        label=sub_text,
        xalign=0,
        ellipsize=Pango.EllipsizeMode.END,
        css_classes=["dim-label", "caption"],
    )
    title_box.append(title_lbl)
    title_box.append(sub_lbl)
    box.append(title_box)

    dur_text = _format_duration(float(getattr(t, "duration", 0) or 0))
    if dur_text:
        dur_lbl = Gtk.Label(label=dur_text, xalign=1, css_classes=["dim-label"])
        dur_lbl.set_size_request(60, -1)
        box.append(dur_lbl)

    play_btn = Gtk.Button(icon_name="media-playback-start-symbolic", css_classes=["flat", "circular"])
    play_btn.set_tooltip_text("Play from here")
    play_btn.connect("clicked", lambda _b, i=idx: _play_tracks(app, tracks, i))
    box.append(play_btn)

    row.set_child(box)
    return row


def _play_tracks(app, tracks: list, start_idx: int) -> None:
    if not tracks:
        return
    start_idx = max(0, min(int(start_idx), len(tracks) - 1))
    app.playback_source = {"type": "local", "scope": "tracks_view"}
    app.current_track_list = list(tracks)
    if hasattr(app, "_set_play_queue"):
        app._set_play_queue(list(tracks))
    else:
        app.play_queue = list(tracks)
    for attr in ("bottom_bar", "player_overlay"):
        widget = getattr(app, attr, None)
        if widget is not None:
            try:
                widget.set_visible(True)
            except Exception:
                pass
    if hasattr(app, "play_track"):
        app.play_track(start_idx)


def render_local_albums(app) -> None:
    _set_grid_title(app, "Albums", "All albums from your local folders")
    _clear(app.collection_content_box)

    lib = getattr(app, "local_library", None)
    if lib is None:
        _empty_state(app.collection_content_box, "Local library unavailable")
        return

    loading = Gtk.Label(label="Loading albums…", xalign=0, css_classes=["dim-label"],
                        margin_start=8, margin_top=8)
    app.collection_content_box.append(loading)

    def _fetch():
        albums = lib.get_albums()
        GLib.idle_add(lambda: (_render_albums_body(app, albums), False)[1])

    Thread(target=_fetch, daemon=True).start()


def _render_albums_body(app, albums: list) -> None:
    from actions import ui_actions

    _clear(app.collection_content_box)
    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
        app.grid_subtitle_label.set_text(f"{len(albums)} albums")

    if not albums:
        _empty_state(
            app.collection_content_box,
            "No albums yet",
            "Add a folder under Library → Local Folders to get started.",
        )
        return

    scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    flow = Gtk.FlowBox(
        homogeneous=True,
        min_children_per_line=4,
        max_children_per_line=10,
        column_spacing=16,
        row_spacing=16,
        margin_top=8, margin_bottom=24, margin_start=8, margin_end=8,
    )
    flow.set_selection_mode(Gtk.SelectionMode.NONE)
    scroller.set_child(flow)
    app.collection_content_box.append(scroller)

    for alb in albums:
        flow.append(ui_actions._build_my_albums_style_button(app, alb, app.show_album_details))


def render_local_artists(app) -> None:
    _set_grid_title(app, "Artists", "All artists from your local folders")
    _clear(app.collection_content_box)

    lib = getattr(app, "local_library", None)
    if lib is None:
        _empty_state(app.collection_content_box, "Local library unavailable")
        return

    loading = Gtk.Label(label="Loading artists…", xalign=0, css_classes=["dim-label"],
                        margin_start=8, margin_top=8)
    app.collection_content_box.append(loading)

    def _fetch():
        artists = lib.get_artists()
        GLib.idle_add(lambda: (_render_artists_body(app, artists), False)[1])

    Thread(target=_fetch, daemon=True).start()


def _render_artists_body(app, artists: list) -> None:
    _clear(app.collection_content_box)
    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
        app.grid_subtitle_label.set_text(f"{len(artists)} artists")

    if not artists:
        _empty_state(
            app.collection_content_box,
            "No artists yet",
            "Add a folder under Library → Local Folders to get started.",
        )
        return

    scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    list_box = Gtk.ListBox(css_classes=["boxed-list"])
    scroller.set_child(list_box)
    app.collection_content_box.append(scroller)

    for art in artists:
        row = _build_artist_row(app, art)
        list_box.append(row)


def _build_artist_row(app, artist) -> Gtk.ListBoxRow:
    row = Gtk.ListBoxRow()
    row.set_activatable(True)
    hb = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=12,
        margin_top=10, margin_bottom=10, margin_start=12, margin_end=12,
    )

    icon = Gtk.Image.new_from_icon_name("avatar-default-symbolic")
    icon.set_pixel_size(36)
    hb.append(icon)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
    name_lbl = Gtk.Label(
        label=str(getattr(artist, "name", "") or ""),
        xalign=0, ellipsize=Pango.EllipsizeMode.END,
        css_classes=["heading"],
    )
    stats = Gtk.Label(
        label=f"{getattr(artist, 'album_count', 0)} albums • {getattr(artist, 'track_count', 0)} tracks",
        xalign=0, css_classes=["dim-label", "caption"],
    )
    box.append(name_lbl)
    box.append(stats)
    hb.append(box)

    open_btn = Gtk.Button(label="Open", css_classes=["flat"])
    open_btn.connect("clicked", lambda _b, a=artist: _open_local_artist(app, a))
    hb.append(open_btn)

    row.set_child(hb)
    row.connect("activate", lambda _r: _open_local_artist(app, artist))
    return row


def _open_local_artist(app, artist) -> None:
    lib = getattr(app, "local_library", None)
    if lib is None:
        return
    name = str(getattr(artist, "name", "") or "")
    _set_grid_title(app, name, "")
    _clear(app.collection_content_box)

    loading = Gtk.Label(label="Loading…", xalign=0, css_classes=["dim-label"],
                        margin_start=8, margin_top=8)
    app.collection_content_box.append(loading)

    def _fetch():
        albums = lib.get_artist_albums(name)
        GLib.idle_add(lambda: (_render_albums_body(app, albums), False)[1])

    Thread(target=_fetch, daemon=True).start()


# ----------------------------------------------------------------------
# entry point — wired into on_nav_selected
# ----------------------------------------------------------------------

def dispatch_local_nav(app, nav_id: str) -> bool:
    """Handle a local-nav row. Returns True if dispatched."""
    nid = str(nav_id or "")
    if nid == "local_folders":
        render_local_folders(app)
        return True
    if nid == "local_tracks":
        render_local_tracks(app)
        return True
    if nid == "local_albums":
        render_local_albums(app)
        return True
    if nid == "local_artists":
        render_local_artists(app)
        return True
    return False
