"""Initialization of app UI/runtime reference attributes."""

from core.constants import LikedTracksCache, VizWarmup


def _init_widget_refs(self):
    # Widgets created during do_activate/build steps.
    self.bp_label = None
    self.viz_stack_box = None
    self.vol_btn = None
    self.vol_scale = None
    self.vol_pop = None
    self.viz_revealer = None
    self.viz_theme_dd = None
    self.viz_bars_dd = None
    self.viz_effect_dd = None
    self.viz_profile_dd = None
    self.lyrics_font_dd = None
    self.lyrics_motion_dd = None
    self.lyrics_font_label = None
    self.lyrics_offset_label = None
    self.timeline_box = None
    self.scale_overlay = None
    self.scale_thumb = None
    self.vol_box = None
    self.tech_box = None
    self.bg_viz = None
    self.lyrics_tab_root = None
    self.viz = None
    self.eq_btn = None
    self.eq_pop = None
    self.mode_btn = None
    self.track_fav_btn = None
    self.track_list = None
    self.playlist_track_list = None
    self.liked_track_list = None
    self.queue_track_list = None
    self.queue_drawer_list = None
    self.queue_count_label = None
    self.queue_clear_btn = None
    self.queue_revealer = None
    self.queue_backdrop = None
    self.queue_btn = None
    self.viz_anchor = None
    self.viz_handle_box = None
    self.list_box = None
    self.output_status_label = None
    self.output_recover_btn = None
    self.output_notice_revealer = None
    self.output_notice_icon = None
    self.output_notice_label = None
    self.network_status_label = None
    self.decoder_status_label = None
    self.events_btn = None
    self.search_content_box = None
    self.search_suggest_popover = None
    self.add_playlist_btn = None
    self.remote_playlist_edit_btn = None
    self.remote_playlist_visibility_btn = None
    self.remote_playlist_more_btn = None
    self.remote_playlist_more_pop = None
    self.add_selected_tracks_btn = None
    self.like_selected_tracks_btn = None
    self.search_prev_page_btn = None
    self.search_next_page_btn = None
    self.search_tracks_page_label = None


def _init_viz_refs(self):
    self._viz_backend_key = None
    self._viz_ui_syncing = False
    self._viz_effect_apply_source = None
    self._viz_profile_apply_source = None
    self._viz_theme_apply_source = None
    self._viz_handle_anim_source = 0
    self._viz_handle_settle_source = 0
    self._viz_handle_resize_source = 0
    self._viz_handle_resize_retries = 0
    self._viz_open_layout_source = 0
    self._viz_fade_source = 0
    self._viz_open_stream_source = 0
    self._viz_stream_prewarm_source = 0
    self._viz_opened_once = False
    self._last_spectrum_frame = None
    self._last_spectrum_ts = 0.0
    self._viz_seed_frame = None
    self._viz_warmup_until = 0.0
    self._viz_warmup_duration_s = VizWarmup.DURATION_S
    self._viz_placeholder_source = 0
    self._viz_placeholder_phase = 0.0
    self._viz_placeholder_frame = []
    self._viz_real_frame_streak = 0
    self._viz_trace_open_ts = 0.0
    self._viz_trace_last_cb_ts = 0.0
    self._viz_trace_first_real_logged = False
    self._viz_current_page = "spectrum"


def _init_runtime_refs(self):
    self.liked_tracks_data = []
    self.liked_tracks_last_fetch_ts = 0.0
    self.liked_tracks_cache_ttl_sec = LikedTracksCache.TTL_SEC
    self.current_album = None
    self.current_remote_playlist = None
    self.current_playlist_folder = None
    self.current_playlist_folder_stack = []
    self.current_selected_artist = None
    self._output_notice_source = 0
    self._output_status_source = 0
    self._ui_loop_source = 0
    self._last_output_state = None
    self._last_output_error = None
    self._diag_events = []
    self._diag_health = {"network": "idle", "decoder": "idle", "output": "idle"}
    self._diag_pop = None
    self._diag_text = None
    self._login_in_progress = False
    self._login_attempt_id = None
    self._login_mode = None
    self._login_dialog = None
    self._login_qr_tempfile = None
    self._login_status_label = None
    self._session_restore_pending = False
    self.search_selected_indices = set()
    self.search_tracks_page = 0
    self.search_tracks_page_size = 50
    self.collection_base_margin_bottom = 32
    self.track_list_base_margin_bottom = 32
    self.search_base_margin_bottom = 32
    self.daily_mix_data = []
    self._tray_icon = None
    self._tray_ready = False
    self._allow_window_close = False
    self._mpris = None
    self._thumb_smooth_x = None
    self._seek_pending_value = None
    self._seek_commit_source = 0
    self._seek_user_interacting = False
    self._search_suggest_focus_check_source = 0


def init_ui_refs(self):
    _init_widget_refs(self)
    _init_viz_refs(self)
    _init_runtime_refs(self)
