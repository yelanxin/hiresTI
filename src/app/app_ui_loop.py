"""
UI loop, seek and layout management for TidalApp.
Contains progress bar updates, paned layout, and the update loop scheduler.
"""
import logging

from gi.repository import GLib

from ui import config as ui_config

logger = logging.getLogger(__name__)


def on_seek(self, s):
    self._update_progress_thumb_position()
    if self.is_programmatic_update:
        return
    self._seek_user_interacting = True
    value = float(s.get_value())
    self._seek_pending_value = value
    try:
        self.lbl_current_time.set_text(f"{int(value // 60)}:{int(value % 60):02d}")
    except Exception:
        pass
    if self._seek_commit_source:
        GLib.source_remove(self._seek_commit_source)
        self._seek_commit_source = 0

    def _commit_seek():
        self._seek_commit_source = 0
        target = self._seek_pending_value
        self._seek_pending_value = None
        try:
            if target is not None:
                self.player.seek(float(target))
                if hasattr(self, "_mpris_emit_seeked"):
                    self._mpris_emit_seeked(float(target))
                if hasattr(self, "_mpris_sync_position"):
                    self._mpris_sync_position(force=True)
                if hasattr(self, "_remote_publish_playback_event"):
                    self._remote_publish_playback_event("seek")
        finally:
            # Never keep seek-interacting state latched on errors, otherwise
            # progress UI can appear frozen.
            self._seek_user_interacting = False
        return False

    # Commit only after dragging value settles.
    self._seek_commit_source = GLib.timeout_add(120, _commit_seek)


def _update_progress_thumb_position(self):
    if self.scale is None or self.scale_thumb is None:
        return
    try:
        adj = self.scale.get_adjustment()
        lower = float(adj.get_lower())
        upper = float(adj.get_upper())
        value = float(self.scale.get_value())
        width = int(self.scale.get_width())
        if upper <= lower or width <= 0:
            self.scale_thumb.set_margin_start(0)
            self._thumb_smooth_x = None
            return
        ratio = (value - lower) / (upper - lower)
        ratio = max(0.0, min(1.0, ratio))
        thumb_w = 14
        max_x = float(max(0, width - thumb_w))
        raw_x = float(ratio * max_x)

        prev_x = self._thumb_smooth_x
        if prev_x is None:
            smooth_x = raw_x
        elif not self.is_programmatic_update:
            # User drag/seek: follow cursor immediately.
            smooth_x = raw_x
        else:
            # Playback tick: smooth motion and suppress tiny backward jitter.
            if raw_x < prev_x and (prev_x - raw_x) <= 1.5:
                raw_x = prev_x
            if abs(raw_x - prev_x) > 56.0:
                # Track switch / hard seek: snap to new position.
                smooth_x = raw_x
            else:
                smooth_x = prev_x + (raw_x - prev_x) * 0.38
                if abs(smooth_x - prev_x) < 0.30:
                    smooth_x = prev_x

        smooth_x = max(0.0, min(max_x, smooth_x))
        self._thumb_smooth_x = smooth_x
        self.scale_thumb.set_margin_start(int(round(smooth_x)))
    except Exception:
        pass


def _restore_paned_position_after_layout(self):
    if self.paned is None:
        return False
    win_w = (self.win.get_width() if self.win else 0) or ui_config.WINDOW_WIDTH
    sidebar_px = int(max(120, win_w * float(ui_config.SIDEBAR_RATIO)))
    if self.paned.get_position() != sidebar_px:
        self.paned.set_position(sidebar_px)
    return False


def _get_ui_loop_interval_ms(self):
    is_playing = False
    try:
        is_playing = bool(self.player.is_playing())
    except Exception:
        is_playing = False

    if not self.playing_track_id:
        return 280
    if not is_playing:
        if hasattr(self, "_is_viz_surface_visible") and self._is_viz_surface_visible():
            return 120
        return 220
    if hasattr(self, "_is_viz_surface_visible") and self._is_viz_surface_visible():
        if self._viz_current_page == "lyrics":
            return 25
        return 40
    # No visualizer/lyrics drawer visible: keep UI updates responsive but reduce idle wakeups.
    return 160


def _schedule_update_ui_loop(self, delay_ms=None):
    source = getattr(self, "_ui_loop_source", 0)
    if source:
        GLib.source_remove(source)
        self._ui_loop_source = 0
    next_delay = int(delay_ms if delay_ms is not None else self._get_ui_loop_interval_ms())

    def _tick():
        self._ui_loop_source = 0
        try:
            keep_running = bool(self.update_ui_loop())
        except Exception:
            logger.exception("UI loop tick failed")
            keep_running = True
        if keep_running:
            self._schedule_update_ui_loop()
        return False

    self._ui_loop_source = GLib.timeout_add(max(20, next_delay), _tick)


def update_layout_proportions(self, w, p):
    # Don't touch paned position while the login screen is visible; doing so
    # would restore the saved sidebar width and leave right_stack too narrow
    # to fit the login card, producing a GtkStack measurement warning.
    login_box = getattr(self, "login_prompt_box", None)
    if login_box is not None and login_box.get_visible():
        GLib.idle_add(lambda: (self._schedule_viz_handle_realign(animate=False), False)[1])
        return
    s_px = int(max(120, self.win.get_width() * float(ui_config.SIDEBAR_RATIO)))
    self.paned.set_position(s_px)
    overlay_h = 0
    if getattr(self, "body_overlay", None) is not None:
        try:
            overlay_h = int(self.body_overlay.get_height() or 0)
        except Exception:
            overlay_h = 0
    if overlay_h <= 0 and getattr(self, "win", None) is not None:
        try:
            overlay_h = int(self.win.get_height() or 0)
        except Exception:
            overlay_h = 0
    if overlay_h <= 0:
        overlay_h = int(ui_config.WINDOW_HEIGHT)
    if hasattr(self, "_sync_viz_height_to_window"):
        self._sync_viz_height_to_window(available_h=overlay_h)
    if hasattr(self, "_schedule_viz_height_resync"):
        self._schedule_viz_height_resync(delay_ms=140)
    queue_gap = int(max(0, round(overlay_h * 0.10)))
    queue_anchor = getattr(self, "queue_anchor", None)
    if queue_anchor is not None:
        if int(queue_anchor.get_margin_top() or 0) != queue_gap:
            queue_anchor.set_margin_top(queue_gap)
        if int(queue_anchor.get_margin_bottom() or 0) != queue_gap:
            queue_anchor.set_margin_bottom(queue_gap)
    if hasattr(self, "_schedule_now_playing_surface_resync"):
        self._schedule_now_playing_surface_resync()
    elif hasattr(self, "_sync_now_playing_surface_size"):
        GLib.idle_add(lambda: (self._sync_now_playing_surface_size(), False)[1])
    GLib.idle_add(lambda: (self._schedule_viz_handle_realign(animate=False), False)[1])


def on_paned_position_changed(self, _paned, _param):
    if self.paned is None:
        return
    pos = self.paned.get_position()
    if not isinstance(pos, int) or pos <= 0:
        return
    self.settings["paned_position"] = pos
    self.schedule_save_settings()
