from threading import Thread
import logging
import time

from gi.repository import GLib, Gtk
from actions import ui_actions

logger = logging.getLogger(__name__)


def _artists_nav_is_selected(app):
    nav_list = getattr(app, "nav_list", None)
    row = nav_list.get_selected_row() if nav_list is not None and hasattr(nav_list, "get_selected_row") else None
    return str(getattr(row, "nav_id", "") or "") == "artists"


def _cancel_artist_albums_view(app, clear_selected=True):
    try:
        old_vadj = getattr(app, "_artist_albums_vadj", None)
        old_hid = int(getattr(app, "_artist_albums_vadj_handler_id", 0) or 0)
        if old_vadj is not None and old_hid:
            old_vadj.disconnect(old_hid)
    except Exception:
        pass
    try:
        src = int(getattr(app, "_artist_detail_layout_sync_source", 0) or 0)
        if src:
            GLib.source_remove(src)
    except Exception:
        pass
    for widget, hid in list(getattr(app, "_artist_detail_layout_handler_ids", []) or []):
        try:
            widget.disconnect(hid)
        except Exception:
            pass
    app._artist_detail_layout_handler_ids = []
    pending_src = int(getattr(app, "_artist_hero_layout_pending_src", 0) or 0)
    if pending_src:
        try:
            GLib.source_remove(pending_src)
        except Exception:
            pass
    app._artist_hero_layout_pending_src = 0
    app._artist_detail_layout_sync_source = 0
    app._artist_detail_layout_refresh = None
    app._artist_albums_vadj = None
    app._artist_albums_vadj_handler_id = 0
    app._artist_albums_render_token = int(getattr(app, "_artist_albums_render_token", 0) or 0) + 1
    if clear_selected:
        app.current_selected_artist = None


def _restore_collection_content_margins(app):
    content_box = getattr(app, "collection_content_box", None)
    if content_box is None:
        return
    try:
        content_box.set_margin_start(int(getattr(app, "collection_base_margin_start", 20) or 20))
        content_box.set_margin_end(int(getattr(app, "collection_base_margin_end", 20) or 20))
        content_box.set_margin_bottom(int(getattr(app, "collection_base_margin_bottom", 32) or 32))
    except Exception:
        pass


def _capture_artists_page_state(app):
    if not _artists_nav_is_selected(app):
        return
    content_box = getattr(app, "collection_content_box", None)
    if content_box is None or not hasattr(content_box, "get_first_child"):
        return

    children = []
    child = content_box.get_first_child()
    while child:
        children.append(child)
        child = child.get_next_sibling()
    if not children:
        return

    scroll_y = 0.0
    try:
        vadj = app.alb_scroll.get_vadjustment() if getattr(app, "alb_scroll", None) else None
        if vadj is not None:
            scroll_y = float(vadj.get_value())
    except Exception:
        scroll_y = 0.0

    title = ""
    if hasattr(app, "grid_title_label") and app.grid_title_label is not None and hasattr(app.grid_title_label, "get_text"):
        title = str(app.grid_title_label.get_text() or "")
    subtitle = ""
    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None and hasattr(app.grid_subtitle_label, "get_text"):
        subtitle = str(app.grid_subtitle_label.get_text() or "")

    app._artists_page_state = {
        "children": children,
        "main_flow": getattr(app, "main_flow", None),
        "scroll_y": scroll_y,
        "title": title,
        "subtitle": subtitle,
        "margin_start": int(getattr(content_box, "get_margin_start", lambda: getattr(app, "collection_base_margin_start", 20))() or 0),
        "margin_end": int(getattr(content_box, "get_margin_end", lambda: getattr(app, "collection_base_margin_end", 20))() or 0),
        "margin_bottom": int(getattr(content_box, "get_margin_bottom", lambda: getattr(app, "collection_base_margin_bottom", 32))() or 0),
    }


def _restore_artists_page_state(app):
    state = getattr(app, "_artists_page_state", None)
    if not isinstance(state, dict):
        return False
    children = list(state.get("children") or [])
    content_box = getattr(app, "collection_content_box", None)
    if content_box is None or not children:
        return False

    while c := content_box.get_first_child():
        content_box.remove(c)
    for child in children:
        content_box.append(child)

    try:
        content_box.set_margin_start(int(state.get("margin_start", getattr(app, "collection_base_margin_start", 20)) or 0))
        content_box.set_margin_end(int(state.get("margin_end", getattr(app, "collection_base_margin_end", 20)) or 0))
        content_box.set_margin_bottom(int(state.get("margin_bottom", getattr(app, "collection_base_margin_bottom", 32)) or 0))
    except Exception:
        pass

    app.main_flow = state.get("main_flow")
    if hasattr(app, "grid_title_box") and app.grid_title_box is not None and hasattr(app.grid_title_box, "set_visible"):
        app.grid_title_box.set_visible(True)
    if hasattr(app, "grid_title_label") and app.grid_title_label is not None and hasattr(app.grid_title_label, "set_visible"):
        app.grid_title_label.set_visible(True)
    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None and hasattr(app.grid_subtitle_label, "set_visible"):
        app.grid_subtitle_label.set_visible(True)

    if hasattr(app, "grid_title_label") and app.grid_title_label is not None:
        app.grid_title_label.set_text(str(state.get("title") or "Favorite Artists"))
    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
        app.grid_subtitle_label.set_text(str(state.get("subtitle") or "Artists you follow and love"))

    scroll_y = float(state.get("scroll_y", 0.0) or 0.0)

    def _apply_scroll():
        try:
            vadj = app.alb_scroll.get_vadjustment() if getattr(app, "alb_scroll", None) else None
            if vadj is None:
                return False
            max_value = max(0.0, float(vadj.get_upper()) - float(vadj.get_page_size()))
            vadj.set_value(max(0.0, min(scroll_y, max_value)))
        except Exception:
            pass
        return False

    GLib.idle_add(_apply_scroll)
    return True


def on_nav_selected(app, box, row):
    if not row:
        return

    _cancel_artist_albums_view(app)
    _restore_collection_content_margins(app)
    app._artists_dashboard_token = int(getattr(app, "_artists_dashboard_token", 0) or 0) + 1
    app._artists_page_state = None
    if hasattr(row, "nav_id") and hasattr(app, "_remember_last_nav"):
        app._remember_last_nav(row.nav_id)

    if hasattr(app, "grid_title_label") and app.grid_title_label is not None:
        app.grid_title_label.set_visible(True)
    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
        app.grid_subtitle_label.set_visible(True)
    if hasattr(app, "grid_title_box") and app.grid_title_box is not None:
        app.grid_title_box.set_visible(True)

    app.nav_history.clear()
    app.artist_fav_btn.set_visible(False)
    app.right_stack.set_visible_child_name("grid_view")
    if hasattr(app, "_remember_last_view"):
        app._remember_last_view("grid_view")
    app.back_btn.set_sensitive(False)

    while c := app.collection_content_box.get_first_child():
        app.collection_content_box.remove(c)
    app.queue_track_list = None
    app.liked_track_list = None

    if row.nav_id == "home":
        app.grid_title_label.set_text("Home")
        if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
            app.grid_subtitle_label.set_text("Fresh picks and playlists tailored to your listening")
        if app.backend.user:
            cached_sections = getattr(app, "_home_sections_cache", None)
            if cached_sections:
                app.batch_load_home(cached_sections)
                return

            loading = Gtk.Label(
                label="Loading Home...",
                xalign=0,
                css_classes=["dim-label"],
                margin_start=8,
                margin_top=8,
            )
            app.collection_content_box.append(loading)

            def task():
                sections = app.backend.get_home_page()

                def apply_home():
                    while c := app.collection_content_box.get_first_child():
                        app.collection_content_box.remove(c)
                    app._home_sections_cache = sections
                    app.batch_load_home(sections)
                    return False

                GLib.idle_add(apply_home)
                if not getattr(app, "_top_sections_cache", None):
                    try:
                        app._top_sections_cache = list(app.backend.get_top_page() or [])
                        app._top_sections_cache_time = time.monotonic()
                    except Exception:
                        pass
                if not getattr(app, "_new_sections_cache", None):
                    try:
                        app._new_sections_cache = list(app.backend.get_new_page() or [])
                        app._new_sections_cache_time = time.monotonic()
                    except Exception:
                        pass

            Thread(target=task, daemon=True).start()
        return

    if row.nav_id == "new":
        app.grid_title_label.set_text("New")
        if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
            app.grid_subtitle_label.set_text("Official TIDAL new releases and fresh picks")
        app.render_new_dashboard()
        return

    if row.nav_id == "top":
        app.grid_title_label.set_text("Top")
        if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
            app.grid_subtitle_label.set_text("Official TIDAL platform charts and top lists")
        app.render_top_dashboard()
        return

    if row.nav_id == "collection":
        app.grid_title_label.set_text("My Albums")
        if app.backend.user:
            cached = list(getattr(app.backend, "_cached_albums", []) or [])
            now = time.time()
            last_ts = float(getattr(app.backend, "_cached_albums_ts", 0.0) or 0.0)
            # Only show cached data for instant first paint if it is very fresh
            # (fetched within the last 15 s).  Older caches may not reflect
            # changes made on other devices (e.g. unfavoriting on mobile), so
            # we skip the stale first-render and show a loading indicator
            # instead, then always fetch from the server.
            INSTANT_RENDER_TTL = 15.0
            cache_age = now - last_ts
            show_cached = cached and cache_age < INSTANT_RENDER_TTL

            if show_cached:
                if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
                    app.grid_subtitle_label.set_text(f"{len(cached)} saved albums")
                app.render_collection_dashboard([], cached)
            else:
                loading = Gtk.Label(
                    label="Loading albums...",
                    xalign=0,
                    css_classes=["dim-label"],
                    margin_start=8,
                    margin_top=8,
                )
                app.collection_content_box.append(loading)

            # Always refresh from the server so external changes (e.g. a
            # favourite removed on mobile) are picked up on every navigation.
            # Pre-compute cached IDs in the main thread for later comparison.
            cached_ids = [str(getattr(a, "id", "")) for a in cached] if show_cached else None

            def task():
                albums = list(app.backend.get_recent_albums())
                album_count = len(albums)
                fresh_ids = [str(getattr(a, "id", "")) for a in albums]
                def update():
                    # Skip re-render when the cached first-paint already shows
                    # exactly the same albums — avoids a visible double-flash.
                    if cached_ids is not None and fresh_ids == cached_ids:
                        return False
                    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
                        app.grid_subtitle_label.set_text(f"{album_count} saved albums")
                    app.render_collection_dashboard([], albums)
                    return False
                GLib.idle_add(update)
            Thread(target=task, daemon=True).start()
        else:
            if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
                app.grid_subtitle_label.set_text("0 saved albums")
            app.render_collection_dashboard([], [])
        return

    if row.nav_id == "liked_songs":
        app.grid_title_label.set_text("Liked Songs")
        if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
            app.grid_subtitle_label.set_text("Your TIDAL favorite tracks")
        # Instant first paint: render cached/skeleton UI immediately, then refresh async.
        cached_tracks = list(getattr(app, "liked_tracks_data", []) or [])
        app.render_liked_songs_dashboard(cached_tracks)
        app.refresh_liked_songs_dashboard(_initial_render_done=True)
        return

    if row.nav_id == "playlists":
        app.grid_title_label.set_text("Playlists")
        if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
            app.grid_subtitle_label.set_text("Create and manage your own playlists")
        app.current_playlist_folder = None
        app.current_playlist_folder_stack = []
        app.render_playlists_home()
        return

    if row.nav_id == "queue":
        app.grid_title_label.set_text("Queue")
        if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
            app.grid_subtitle_label.set_text("Current play queue and upcoming tracks")
        app.render_queue_dashboard()
        return

    if row.nav_id == "daily_mix":
        app.grid_title_label.set_text("Daily Mix")
        if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
            app.grid_subtitle_label.set_text("Auto-generated from your listening history, refreshed every day")
        while c := app.collection_content_box.get_first_child():
            app.collection_content_box.remove(c)
        loading = Gtk.Label(
            label="Generating daily playlists...",
            xalign=0,
            css_classes=["dim-label"],
            margin_start=8,
            margin_top=8,
        )
        app.collection_content_box.append(loading)

        def task():
            mixes = app.build_daily_mixes()

            def apply_daily():
                app.render_daily_mixes(mixes)
                return False

            GLib.idle_add(apply_daily)

        Thread(target=task, daemon=True).start()
        return

    if row.nav_id == "history":
        app.grid_title_label.set_text("History")
        if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
            app.grid_subtitle_label.set_text("Recent plays and your most replayed tracks")
        app.render_history_dashboard()
        return

    if row.nav_id == "artists":
        app.grid_title_label.set_text("Favorite Artists")
        if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
            app.grid_subtitle_label.set_text("Artists you follow and love")
        ui_actions.render_artists_dashboard(app)
        return


def on_artist_clicked(app, artist):
    current_view = app.right_stack.get_visible_child_name()
    if current_view:
        app.nav_history.append(current_view)
    _capture_artists_page_state(app)

    app.current_selected_artist = artist
    app.right_stack.set_visible_child_name("grid_view")
    if hasattr(app, "_remember_last_view"):
        app._remember_last_view("grid_view")
    if hasattr(app, "grid_title_box") and app.grid_title_box is not None:
        app.grid_title_box.set_visible(False)
    app.grid_title_label.set_text(str(getattr(artist, "name", "") or "Artist"))
    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
        app.grid_subtitle_label.set_text("Top tracks, albums and EP & singles")
    app.back_btn.set_sensitive(True)
    app.artist_fav_btn.set_visible(False)

    _cancel_artist_albums_view(app, clear_selected=False)

    render_token = int(getattr(app, "_artist_albums_render_token", 0) or 0) + 1
    app._artist_albums_render_token = render_token
    ui_actions.render_artist_detail(app, artist, render_token=render_token)


def on_back_clicked(app, btn):
    # Highest priority: when currently inside playlist detail, always go back to playlist list.
    if getattr(app, "current_remote_playlist", None) is not None:
        app.current_remote_playlist = None
        app.right_stack.set_visible_child_name("grid_view")
        row = app.nav_list.get_selected_row()
        nav_id = str(getattr(row, "nav_id", "") or "")
        if nav_id == "top":
            app.render_top_dashboard(prefer_cache=True)
            btn.set_sensitive(False)
        elif nav_id == "new":
            app.render_new_dashboard(prefer_cache=True)
            btn.set_sensitive(False)
        elif nav_id == "home":
            cached_sections = getattr(app, "_home_sections_cache", None)
            if cached_sections:
                app.batch_load_home(cached_sections)
            else:
                app.on_nav_selected(None, row)
            btn.set_sensitive(False)
        else:
            app.render_playlists_home()
            btn.set_sensitive(bool(getattr(app, "current_playlist_folder_stack", []) or []))
        return

    if getattr(app, "current_playlist_id", None):
        app.current_playlist_id = None
        app.playlist_edit_mode = False
        app.playlist_rename_mode = False
        app.render_playlists_home()
        btn.set_sensitive(bool(getattr(app, "current_playlist_folder_stack", []) or []))
        return

    row = app.nav_list.get_selected_row()
    # Fallback: if we're in playlists nav and currently on tracks detail view,
    # always return to playlists list even when detail state fields were lost.
    if row and hasattr(row, "nav_id") and row.nav_id == "playlists":
        if getattr(app.right_stack, "get_visible_child_name", None):
            if app.right_stack.get_visible_child_name() == "tracks":
                app.current_remote_playlist = None
                app.current_playlist_id = None
                app.playlist_edit_mode = False
                app.playlist_rename_mode = False
                app.right_stack.set_visible_child_name("grid_view")
                app.render_playlists_home()
                btn.set_sensitive(bool(getattr(app, "current_playlist_folder_stack", []) or []))
                return

    if row and hasattr(row, "nav_id") and row.nav_id == "playlists":
        # In playlists list view: navigate folder hierarchy upwards.
        folder_stack = list(getattr(app, "current_playlist_folder_stack", []) or [])
        if folder_stack:
            app.on_playlist_folder_up_clicked()
            btn.set_sensitive(bool(getattr(app, "current_playlist_folder_stack", []) or []))
            return

    if app.nav_history:
        target_view = app.nav_history.pop()
        app.right_stack.set_visible_child_name(target_view)
        if hasattr(app, "_remember_last_view"):
            app._remember_last_view(target_view)
        if target_view == "search_view":
            return

        if not app.nav_history and target_view == "grid_view":
            btn.set_sensitive(False)
            app.artist_fav_btn.set_visible(False)
            _cancel_artist_albums_view(app)
            if _artists_nav_is_selected(app) and _restore_artists_page_state(app):
                return
            selected = app.nav_list.get_selected_row()
            if selected:
                app.on_nav_selected(None, selected)
            else:
                child = app.nav_list.get_first_child()
                while child:
                    if hasattr(child, "nav_id") and child.nav_id == "home":
                        app.nav_list.select_row(child)
                        app.on_nav_selected(None, child)
                        break
                    child = child.get_next_sibling()
        return

    app.right_stack.set_visible_child_name("grid_view")
    if hasattr(app, "_remember_last_view"):
        app._remember_last_view("grid_view")
    btn.set_sensitive(False)
    app.artist_fav_btn.set_visible(False)

    row = app.nav_list.get_selected_row()
    if row:
        app.on_nav_selected(None, row)
        return

    child = app.nav_list.get_first_child()
    while child:
        if hasattr(child, "nav_id") and child.nav_id == "home":
            app.nav_list.select_row(child)
            app.on_nav_selected(None, child)
            break
        child = child.get_next_sibling()
