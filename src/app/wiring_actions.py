"""Action-delegation wiring."""

from app.wiring_utils import bind_map


def bind_action_delegates(TidalApp, seen=None):
    from actions.audio_settings_actions import (
        on_device_changed,
        on_driver_changed,
        on_latency_changed,
        on_mmap_realtime_priority_changed,
        on_usb_clock_mode_changed,
        update_output_status_ui,
    )
    from actions.lyrics_playback_actions import (
        play_track,
        render_lyrics_list,
        scroll_to_lyric,
        update_ui_loop,
    )
    from actions.playback_actions import (
        get_next_index,
        on_next_track,
        on_play_pause,
        on_prev_track,
    )
    from actions.playback_stream_actions import (
        load_cover_art,
        on_quality_changed,
        restart_player_with_url,
    )
    from actions.ui_actions import (
        batch_load_albums,
        batch_load_artists,
        batch_load_home,
        clear_search_history,
        refresh_dashboard_playing_state,
        on_search,
        on_search_changed,
        populate_tracks,
        render_collection_dashboard,
        render_decades_dashboard,
        render_genres_dashboard,
        render_moods_dashboard,
        render_history_dashboard,
        render_hires_dashboard,
        render_liked_songs_dashboard,
        render_playlist_detail,
        render_playlists_home,
        render_queue_dashboard,
        render_queue_drawer,
        render_search_history,
        render_search_results,
        render_search_tracks_page,
        render_new_dashboard,
        render_top_dashboard,
        show_album_details,
    )
    from actions.ui_navigation import on_artist_clicked, on_back_clicked, on_nav_selected
    from ui.builders import build_body, build_header
    from ui.views_builders import build_grid_view, build_settings_page, build_tracks_view

    bind_map(TidalApp, [
        ("on_play_pause", on_play_pause),
        ("on_next_track", on_next_track),
        ("on_prev_track", on_prev_track),
        ("get_next_index", get_next_index),
        ("on_quality_changed", on_quality_changed),
        ("_restart_player_with_url", restart_player_with_url),
        ("show_album_details", show_album_details),
        ("populate_tracks", populate_tracks),
        ("on_artist_clicked", on_artist_clicked),
        ("batch_load_albums", batch_load_albums),
        ("batch_load_artists", batch_load_artists),
        ("batch_load_home", batch_load_home),
        ("render_history_dashboard", render_history_dashboard),
        ("render_top_dashboard", render_top_dashboard),
        ("render_hires_dashboard", render_hires_dashboard),
        ("render_genres_dashboard", render_genres_dashboard),
        ("render_moods_dashboard", render_moods_dashboard),
        ("render_decades_dashboard", render_decades_dashboard),
        ("render_collection_dashboard", render_collection_dashboard),
        ("render_liked_songs_dashboard", render_liked_songs_dashboard),
        ("render_queue_dashboard", render_queue_dashboard),
        ("render_queue_drawer", render_queue_drawer),
        ("render_playlists_home", render_playlists_home),
        ("render_playlist_detail", render_playlist_detail),
        ("render_search_tracks_page", render_search_tracks_page),
        ("on_nav_selected", on_nav_selected),
        ("on_back_clicked", on_back_clicked),
        ("_load_cover_art", load_cover_art),
        ("on_latency_changed", on_latency_changed),
        ("on_mmap_realtime_priority_changed", on_mmap_realtime_priority_changed),
        ("on_usb_clock_mode_changed", on_usb_clock_mode_changed),
        ("on_driver_changed", on_driver_changed),
        ("on_device_changed", on_device_changed),
        ("_refresh_output_status_loop", update_output_status_ui),
        ("_build_header", build_header),
        ("_build_tracks_view", build_tracks_view),
        ("_build_settings_page", build_settings_page),
        ("_build_body", build_body),
        ("_build_grid_view", build_grid_view),
        ("render_lyrics_list", render_lyrics_list),
        ("play_track", play_track),
        ("_scroll_to_lyric", scroll_to_lyric),
        ("update_ui_loop", update_ui_loop),
        ("render_search_history", render_search_history),
        ("on_search", on_search),
        ("on_search_changed", on_search_changed),
        ("clear_search_history", clear_search_history),
        ("render_search_results", render_search_results),
        ("render_new_dashboard", render_new_dashboard),
        ("refresh_dashboard_playing_state", refresh_dashboard_playing_state),
    ], seen=seen)


def bind_scrobble_actions(TidalApp, seen=None):
    from actions.scrobble_actions import (
        init_scrobble_settings_ui,
        on_lastfm_connect_clicked,
        on_lastfm_disconnect_clicked,
        on_lastfm_enabled_toggled,
        on_listenbrainz_enabled_toggled,
        on_listenbrainz_token_saved,
    )

    bind_map(TidalApp, [
        ("on_lastfm_enabled_toggled", on_lastfm_enabled_toggled),
        ("on_lastfm_connect_clicked", on_lastfm_connect_clicked),
        ("on_lastfm_disconnect_clicked", on_lastfm_disconnect_clicked),
        ("on_listenbrainz_enabled_toggled", on_listenbrainz_enabled_toggled),
        ("on_listenbrainz_token_saved", on_listenbrainz_token_saved),
        ("_init_scrobble_settings_ui", init_scrobble_settings_ui),
    ], seen=seen)


def bind_dsp_preset_actions(TidalApp, seen=None):
    from actions.dsp_preset_actions import (
        on_dsp_preset_delete_clicked,
        on_dsp_preset_load_clicked,
        on_dsp_preset_save_clicked,
        refresh_dsp_preset_list,
    )

    bind_map(TidalApp, [
        ("on_dsp_preset_save_clicked", on_dsp_preset_save_clicked),
        ("on_dsp_preset_load_clicked", on_dsp_preset_load_clicked),
        ("on_dsp_preset_delete_clicked", on_dsp_preset_delete_clicked),
        ("refresh_dsp_preset_list", refresh_dsp_preset_list),
    ], seen=seen)


def bind_audio_settings_extras(TidalApp, seen=None):
    from actions import audio_settings_actions
    from actions.audio_settings_actions import (
        on_bit_perfect_toggled,
        on_exclusive_toggled,
        on_auto_rebind_once_toggled,
        on_output_bit_depth_changed,
        _sync_playback_status_icon,
        _get_output_status_interval_ms,
        _refresh_driver_dropdown_options,
        _schedule_output_status_loop,
        _force_driver_selection,
        update_tech_label,
    )

    bind_map(TidalApp, [
        ("on_bit_perfect_toggled", on_bit_perfect_toggled),
        ("on_exclusive_toggled", on_exclusive_toggled),
        ("on_auto_rebind_once_toggled", on_auto_rebind_once_toggled),
        ("on_output_bit_depth_changed", on_output_bit_depth_changed),
        ("_sync_playback_status_icon", _sync_playback_status_icon),
        ("_get_output_status_interval_ms", _get_output_status_interval_ms),
        ("_refresh_driver_dropdown_options", _refresh_driver_dropdown_options),
        ("_schedule_output_status_loop", _schedule_output_status_loop),
        ("_force_driver_selection", _force_driver_selection),
        ("update_tech_label", update_tech_label),
        ("on_recover_output_clicked", lambda self, btn: audio_settings_actions.on_recover_output_clicked(self, btn)),
        ("on_usb_fix_permissions_clicked", lambda self, btn: audio_settings_actions.on_usb_fix_permissions_clicked(self, btn)),
    ], seen=seen)
