from threading import Thread
import logging

from gi.repository import GLib, Gtk
from actions import ui_actions

logger = logging.getLogger(__name__)


def on_nav_selected(app, box, row):
    if not row:
        return

    if hasattr(app, "grid_title_label") and app.grid_title_label is not None:
        app.grid_title_label.set_visible(True)
    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
        app.grid_subtitle_label.set_visible(True)

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

            Thread(target=task, daemon=True).start()
        return

    if row.nav_id == "collection":
        app.grid_title_label.set_text("My Albums")
        if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
            app.grid_subtitle_label.set_text("Your saved albums")
        loading = Gtk.Label(
            label="Loading albums...",
            xalign=0,
            css_classes=["dim-label"],
            margin_start=8,
            margin_top=8,
        )
        app.collection_content_box.append(loading)
        if app.backend.user:
            def task():
                albums = list(app.backend.get_recent_albums())
                GLib.idle_add(app.render_collection_dashboard, [], albums)

            Thread(target=task, daemon=True).start()
        else:
            app.render_collection_dashboard([], [])
        return

    if row.nav_id == "liked_songs":
        app.grid_title_label.set_text("Liked Songs")
        if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
            app.grid_subtitle_label.set_text("Your TIDAL favorite tracks")
        # Instant first paint: render cached/skeleton UI immediately, then refresh async.
        cached_tracks = list(getattr(app, "liked_tracks_data", []) or [])
        app.render_liked_songs_dashboard(cached_tracks)
        app.refresh_liked_songs_dashboard()
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
        app.create_album_flow()
        if app.backend.user:
            def task():
                artists = list(app.backend.get_favorites() or [])
                artists = ui_actions.sort_objects_by_name_fast(artists, context="favorite_artists")
                logger.info("Artists page prepared: total=%s", len(artists))
                GLib.idle_add(app.batch_load_artists, artists)

            Thread(target=task, daemon=True).start()


def on_artist_clicked(app, artist):
    if hasattr(app, "grid_title_label") and app.grid_title_label is not None:
        app.grid_title_label.set_visible(True)
    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
        app.grid_subtitle_label.set_visible(True)

    current_view = app.right_stack.get_visible_child_name()
    if current_view:
        app.nav_history.append(current_view)

    app.current_selected_artist = artist
    app.right_stack.set_visible_child_name("grid_view")
    if hasattr(app, "_remember_last_view"):
        app._remember_last_view("grid_view")
    app.grid_title_label.set_text(f"Albums by {artist.name}")
    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
        app.grid_subtitle_label.set_text("Discography and related releases")
    app.back_btn.set_sensitive(True)
    app.artist_fav_btn.set_visible(True)

    is_fav = app.backend.is_artist_favorite(artist.id)
    app._update_fav_icon(app.artist_fav_btn, is_fav)

    while c := app.collection_content_box.get_first_child():
        app.collection_content_box.remove(c)

    app.create_album_flow()
    def task():
        albums = list(app.backend.get_albums(artist) or [])
        albums = ui_actions.sort_objects_by_name_fast(albums, context="artist_albums")
        logger.info("Artist albums prepared: artist=%s total=%s", getattr(artist, "name", "Unknown"), len(albums))
        GLib.idle_add(app.batch_load_albums, albums)

    Thread(target=task, daemon=True).start()


def on_back_clicked(app, btn):
    # Highest priority: when currently inside playlist detail, always go back to playlist list.
    if getattr(app, "current_remote_playlist", None) is not None:
        app.current_remote_playlist = None
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
