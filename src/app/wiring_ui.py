"""UI/lifecycle/tray related wiring."""

from app.wiring_utils import bind_map


def bind_tray(TidalApp, seen=None):
    from app.app_tray import (
        _get_tray_icon_path,
        _show_from_tray,
        _copy_share_url_to_clipboard,
        _share_from_tray,
        _quit_from_tray,
        _init_tray_icon,
        _stop_tray_icon,
        on_window_close_request,
    )

    bind_map(TidalApp, [
        ("_get_tray_icon_path", _get_tray_icon_path),
        ("_show_from_tray", _show_from_tray),
        ("_copy_share_url_to_clipboard", _copy_share_url_to_clipboard),
        ("_share_from_tray", _share_from_tray),
        ("_quit_from_tray", _quit_from_tray),
        ("_init_tray_icon", _init_tray_icon),
        ("_stop_tray_icon", _stop_tray_icon),
        ("on_window_close_request", on_window_close_request),
    ], seen=seen)


def bind_lifecycle(TidalApp, seen=None):
    from app.app_lifecycle import (
        _restore_session_async,
        _setup_theme_watch,
        _apply_app_theme_classes,
        _clear_initial_search_focus,
        _restore_last_view,
    )
    from app.app_mpris import (
        _start_mpris_service,
        _stop_mpris_service,
        _mpris_sync_all,
        _mpris_sync_metadata,
        _mpris_sync_playback,
        _mpris_sync_position,
        _mpris_sync_volume,
        _mpris_emit_seeked,
    )

    bind_map(TidalApp, [
        ("_restore_session_async", _restore_session_async),
        ("_setup_theme_watch", _setup_theme_watch),
        ("_apply_app_theme_classes", _apply_app_theme_classes),
        ("_clear_initial_search_focus", _clear_initial_search_focus),
        ("_restore_last_view", _restore_last_view),
        ("_start_mpris_service", _start_mpris_service),
        ("_stop_mpris_service", _stop_mpris_service),
        ("_mpris_sync_all", _mpris_sync_all),
        ("_mpris_sync_metadata", _mpris_sync_metadata),
        ("_mpris_sync_playback", _mpris_sync_playback),
        ("_mpris_sync_position", _mpris_sync_position),
        ("_mpris_sync_volume", _mpris_sync_volume),
        ("_mpris_emit_seeked", _mpris_emit_seeked),
    ], seen=seen)


def bind_album(TidalApp, seen=None):
    from app.app_album import (
        on_grid_item_activated,
        _play_single_track,
        _sort_tracks,
        _format_sort_label,
        _update_album_sort_headers,
        load_album_tracks,
        _render_album_tracks,
        on_album_sort_clicked,
        _update_track_list_icon,
        _tick_playing_row_pulse,
        on_header_artist_clicked,
        create_album_flow,
        _update_list_ui,
        _get_tidal_image_url,
    )

    bind_map(TidalApp, [
        ("on_grid_item_activated", on_grid_item_activated),
        ("_play_single_track", _play_single_track),
        ("_sort_tracks", _sort_tracks),
        ("_format_sort_label", _format_sort_label),
        ("_update_album_sort_headers", _update_album_sort_headers),
        ("load_album_tracks", load_album_tracks),
        ("_render_album_tracks", _render_album_tracks),
        ("on_album_sort_clicked", on_album_sort_clicked),
        ("_update_track_list_icon", _update_track_list_icon),
        ("_tick_playing_row_pulse", _tick_playing_row_pulse),
        ("on_header_artist_clicked", on_header_artist_clicked),
        ("create_album_flow", create_album_flow),
        ("_update_list_ui", _update_list_ui),
        ("_get_tidal_image_url", _get_tidal_image_url),
    ], seen=seen)


def bind_favorites(TidalApp, seen=None):
    from app.app_favorites import (
        _update_fav_icon,
        refresh_current_track_favorite_state,
        create_track_fav_button,
        _refresh_track_fav_button,
        on_track_row_fav_clicked,
        refresh_visible_track_fav_buttons,
        on_track_fav_clicked,
    )

    bind_map(TidalApp, [
        ("_update_fav_icon", _update_fav_icon),
        ("refresh_current_track_favorite_state", refresh_current_track_favorite_state),
        ("create_track_fav_button", create_track_fav_button),
        ("_refresh_track_fav_button", _refresh_track_fav_button),
        ("on_track_row_fav_clicked", on_track_row_fav_clicked),
        ("refresh_visible_track_fav_buttons", refresh_visible_track_fav_buttons),
        ("on_track_fav_clicked", on_track_fav_clicked),
    ], seen=seen)


def bind_ui_loop(TidalApp, seen=None):
    from app.app_ui_loop import (
        on_seek,
        _update_progress_thumb_position,
        _restore_paned_position_after_layout,
        _get_ui_loop_interval_ms,
        _schedule_update_ui_loop,
        update_layout_proportions,
        on_paned_position_changed,
    )

    bind_map(TidalApp, [
        ("on_seek", on_seek),
        ("_update_progress_thumb_position", _update_progress_thumb_position),
        ("_restore_paned_position_after_layout", _restore_paned_position_after_layout),
        ("_get_ui_loop_interval_ms", _get_ui_loop_interval_ms),
        ("_schedule_update_ui_loop", _schedule_update_ui_loop),
        ("update_layout_proportions", update_layout_proportions),
        ("on_paned_position_changed", on_paned_position_changed),
    ], seen=seen)


def bind_search(TidalApp, seen=None):
    from app.app_search import (
        _build_search_view,
        on_search_track_selected,
        on_search_history_track_selected,
        on_track_selected,
        on_player_art_clicked,
        on_search_track_checkbox_toggled,
        _update_search_batch_add_state,
        on_add_selected_search_tracks,
        on_like_selected_search_tracks,
        on_search_tracks_prev_page,
        on_search_tracks_next_page,
    )

    bind_map(TidalApp, [
        ("_build_search_view", _build_search_view),
        ("on_search_track_selected", on_search_track_selected),
        ("on_search_history_track_selected", on_search_history_track_selected),
        ("on_track_selected", on_track_selected),
        ("on_player_art_clicked", on_player_art_clicked),
        ("on_search_track_checkbox_toggled", on_search_track_checkbox_toggled),
        ("_update_search_batch_add_state", _update_search_batch_add_state),
        ("on_add_selected_search_tracks", on_add_selected_search_tracks),
        ("on_like_selected_search_tracks", on_like_selected_search_tracks),
        ("on_search_tracks_prev_page", on_search_tracks_prev_page),
        ("on_search_tracks_next_page", on_search_tracks_next_page),
    ], seen=seen)


def bind_now_playing(TidalApp, seen=None):
    from app.app_now_playing import (
        build_now_playing_overlay,
        hide_now_playing_overlay,
        is_now_playing_overlay_open,
        on_now_playing_open_album_clicked,
        on_now_playing_track_selected,
        show_now_playing_overlay,
        toggle_now_playing_overlay,
        _load_now_playing_album_tracks_async,
        _prime_now_playing_cover_color,
        _refresh_now_playing_from_track,
        _render_now_playing_queue,
        _render_now_playing_album_tracks,
        _render_now_playing_lyrics,
        _schedule_now_playing_surface_resync,
        _scroll_now_playing_to_lyric,
        _sync_now_playing_surface_size,
        _sync_now_playing_lyrics,
        _sync_now_playing_overlay_state,
    )

    bind_map(TidalApp, [
        ("_build_now_playing_overlay", build_now_playing_overlay),
        ("show_now_playing_overlay", show_now_playing_overlay),
        ("hide_now_playing_overlay", hide_now_playing_overlay),
        ("toggle_now_playing_overlay", toggle_now_playing_overlay),
        ("is_now_playing_overlay_open", is_now_playing_overlay_open),
        ("on_now_playing_open_album_clicked", on_now_playing_open_album_clicked),
        ("on_now_playing_track_selected", on_now_playing_track_selected),
        ("_prime_now_playing_cover_color", _prime_now_playing_cover_color),
        ("_refresh_now_playing_from_track", _refresh_now_playing_from_track),
        ("_load_now_playing_album_tracks_async", _load_now_playing_album_tracks_async),
        ("_render_now_playing_queue", _render_now_playing_queue),
        ("_render_now_playing_album_tracks", _render_now_playing_album_tracks),
        ("_render_now_playing_lyrics", _render_now_playing_lyrics),
        ("_schedule_now_playing_surface_resync", _schedule_now_playing_surface_resync),
        ("_scroll_now_playing_to_lyric", _scroll_now_playing_to_lyric),
        ("_sync_now_playing_surface_size", _sync_now_playing_surface_size),
        ("_sync_now_playing_lyrics", _sync_now_playing_lyrics),
        ("_sync_now_playing_overlay_state", _sync_now_playing_overlay_state),
    ], seen=seen)


def bind_builders(TidalApp, seen=None):
    from app.app_builders import (
        _build_volume_popover,
        _sync_volume_ui_state,
        on_key_pressed,
        toggle_mini_mode,
        _build_user_popover,
        _build_eq_popover,
        _sync_eq_slider_groups,
        _on_eq_slider_changed,
        _reset_eq_ui,
        _lock_volume_controls,
        _build_help_popover,
        _show_simple_dialog,
    )

    bind_map(TidalApp, [
        ("_build_volume_popover", _build_volume_popover),
        ("_sync_volume_ui_state", _sync_volume_ui_state),
        ("on_key_pressed", on_key_pressed),
        ("toggle_mini_mode", toggle_mini_mode),
        ("_build_user_popover", _build_user_popover),
        ("_build_eq_popover", _build_eq_popover),
        ("_sync_eq_slider_groups", _sync_eq_slider_groups),
        ("_on_eq_slider_changed", _on_eq_slider_changed),
        ("_reset_eq_ui", _reset_eq_ui),
        ("_lock_volume_controls", _lock_volume_controls),
        ("_build_help_popover", _build_help_popover),
        ("_show_simple_dialog", _show_simple_dialog),
    ], seen=seen)
