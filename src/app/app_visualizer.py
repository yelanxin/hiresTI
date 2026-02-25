"""
Visualizer control for TidalApp.
Contains spectrum/visualizer related methods.
"""
import os
import time
import math
import random
import logging

from gi.repository import Gtk, GLib
from viz.visualizer import SpectrumVisualizer
from viz.visualizer_glarea import SpectrumVisualizerGLArea
from viz.visualizer_gpu import SpectrumVisualizerGPU

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scroll padding (called when viz panel expands/collapses)
# ---------------------------------------------------------------------------

def _apply_overlay_scroll_padding(self, expanded):
    extra = 0
    if expanded:
        breathing_px = 12
        overlay_h = 0
        if hasattr(self, "viz_stack") and self.viz_stack is not None:
            overlay_h = self.viz_stack.get_height()
        if overlay_h <= 1:
            overlay_h = 250
        extra = overlay_h + breathing_px
    if hasattr(self, "collection_content_box") and self.collection_content_box is not None:
        self.collection_content_box.set_margin_bottom(self.collection_base_margin_bottom + extra)
    if self.track_list is not None:
        self.track_list.set_margin_bottom(self.track_list_base_margin_bottom + extra)
    if self.search_content_box is not None:
        self.search_content_box.set_margin_bottom(self.search_base_margin_bottom + extra)


def _ensure_overlay_handles_visible(self):
    """Ensure overlay handles are visible after UI is fully built."""
    viz_handle_box = getattr(self, "viz_handle_box", None)
    if viz_handle_box is not None:
        viz_handle_box.set_visible(True)
        viz_handle_box.queue_resize()
    queue_anchor = getattr(self, "queue_anchor", None)
    if queue_anchor is not None:
        queue_anchor.set_visible(True)
        queue_anchor.queue_resize()
    return GLib.SOURCE_REMOVE


# ---------------------------------------------------------------------------
# Viz sync / latency
# ---------------------------------------------------------------------------

def _viz_sync_key(self, driver, device_id=None, device_name=None):
    drv = str(driver or "Auto").strip() or "Auto"
    dev = str(device_id or "").strip()
    if not dev:
        dev = str(device_name or self.settings.get("device") or "default").strip() or "default"
    return f"{drv}|{dev}"


def _get_viz_offset_from_latency_profile(self):
    profile = str(self.settings.get("latency_profile", "Standard (100ms)") or "").strip()
    if profile in self.LATENCY_MAP:
        buf_ms, _lat_ms = self.LATENCY_MAP[profile]
        return int(max(0, min(500, buf_ms)))
    return 100


def _apply_viz_sync_offset_for_device(self, driver, device_id=None, device_name=None):
    key = self._viz_sync_key(driver, device_id=device_id, device_name=device_name)
    self._viz_sync_device_key = key
    profile_off = self._get_viz_offset_from_latency_profile()
    self.player.visual_sync_offset_ms = profile_off
    self.settings["viz_sync_offset_ms"] = profile_off
    if hasattr(self.player, "visual_sync_auto_offset_ms"):
        self.player.visual_sync_auto_offset_ms = 0.0
    self._viz_sync_last_saved_ms = profile_off
    logger.info(
        "Viz sync offset applied: %dms (source=output-change key=%s)",
        int(profile_off),
        key,
    )


def on_viz_sync_offset_update(self, learned_offset_ms):
    # Disabled: runtime auto-learning should not persist to settings.
    return False


# ---------------------------------------------------------------------------
# Dropdown helpers
# ---------------------------------------------------------------------------

def _drop_down_names(self, dd):
    names = []
    if dd is None:
        return names
    model = dd.get_model()
    if model is None:
        return names
    n = model.get_n_items()
    for i in range(n):
        try:
            names.append(model.get_string(i))
        except Exception:
            pass
    return names


def _selected_name_from_dropdown(self, dd):
    names = self._drop_down_names(dd)
    if not names:
        return None
    idx = int(dd.get_selected())
    if idx < 0 or idx >= len(names):
        return None
    return names[idx]


# ---------------------------------------------------------------------------
# Backend selection & rebuild
# ---------------------------------------------------------------------------

def _build_visualizer_for_backend(self, backend_key):
    order = []
    if backend_key == "cairo":
        order = [("cairo", SpectrumVisualizer), ("gl", SpectrumVisualizerGLArea), ("gpu", SpectrumVisualizerGPU)]
    elif backend_key == "gpu":
        order = [("gpu", SpectrumVisualizerGPU), ("gl", SpectrumVisualizerGLArea), ("cairo", SpectrumVisualizer)]
    else:
        order = [("gl", SpectrumVisualizerGLArea), ("gpu", SpectrumVisualizerGPU), ("cairo", SpectrumVisualizer)]
    for key, ctor in order:
        try:
            return ctor(), key
        except Exception as e:
            logger.warning("Visualizer backend %s unavailable, falling back: %s", key, e)
    raise RuntimeError("No visualizer backend available")


def _resolve_viz_backend_key(self, effect_name=None):
    if not effect_name:
        effect_name = self._selected_name_from_dropdown(self.viz_effect_dd)
    # Force Bars to GL shader path to avoid Cairo/pixman composition overhead.
    # If GL is unavailable, backend rebuild will gracefully fall back.
    if effect_name == "Bars":
        return "gl"
    try:
        idx = int(self.settings.get("viz_backend_policy", 0))
    except Exception:
        idx = 0
    idx = max(0, min(len(self.VIZ_BACKEND_POLICIES) - 1, idx))
    policy = self.VIZ_BACKEND_POLICIES[idx]
    if policy.startswith("Quality"):
        return "cairo"
    if policy.startswith("Performance"):
        return "gl"
    return "gl"


def _sync_viz_dropdown_models(self, theme_name=None, effect_name=None, profile_name=None):
    self._viz_ui_syncing = True
    try:
        if self.viz_theme_dd is not None:
            t_names = self.viz.get_theme_names() or []
            self.viz_theme_dd.set_model(Gtk.StringList.new(t_names))
            if t_names:
                idx = t_names.index(theme_name) if theme_name in t_names else 0
                self.viz_theme_dd.set_selected(idx)
        if self.viz_effect_dd is not None:
            e_names = self.viz.get_effect_names() or []
            self.viz_effect_dd.set_model(Gtk.StringList.new(e_names))
            if e_names:
                idx = e_names.index(effect_name) if effect_name in e_names else 0
                self.viz_effect_dd.set_selected(idx)
        if self.viz_profile_dd is not None:
            p_names = self.viz.get_profile_names() or []
            self.viz_profile_dd.set_model(Gtk.StringList.new(p_names))
            if p_names:
                idx = p_names.index(profile_name) if profile_name in p_names else min(1, len(p_names) - 1)
                self.viz_profile_dd.set_selected(idx)
    finally:
        self._viz_ui_syncing = False


def _rebuild_visualizer_backend(self, backend_key, effect_name=None):
    if self.viz_stack is None:
        return
    if effect_name is None:
        effect_name = self._selected_name_from_dropdown(self.viz_effect_dd)
    theme_name = self._selected_name_from_dropdown(self.viz_theme_dd)
    profile_name = self._selected_name_from_dropdown(self.viz_profile_dd)
    bar_count = int(self.settings.get("viz_bar_count", 32) or 32)
    vis_name = self.viz_stack.get_visible_child_name() if self.viz_stack is not None else "spectrum"

    new_viz, actual_key = self._build_visualizer_for_backend(backend_key)
    new_viz.set_num_bars(bar_count)
    new_viz.set_valign(Gtk.Align.FILL)
    if theme_name and theme_name in (new_viz.get_theme_names() or []):
        new_viz.set_theme(theme_name)
    if profile_name and profile_name in (new_viz.get_profile_names() or []):
        new_viz.set_profile(profile_name)
    if effect_name and effect_name in (new_viz.get_effect_names() or []):
        new_viz.set_effect(effect_name)

    if self.viz is not None:
        try:
            self.viz_stack.remove(self.viz)
        except Exception:
            pass
    self.viz = new_viz
    self._viz_backend_key = actual_key
    self.viz_stack.add_titled(self.viz, "spectrum", "Spectrum")
    if vis_name:
        self.viz_stack.set_visible_child_name(vis_name)
    self._sync_viz_tab_runtime_state()
    self._sync_viz_dropdown_models(theme_name=theme_name, effect_name=effect_name, profile_name=profile_name)
    logger.info("Visualizer backend switched: %s (requested=%s effect=%s)", actual_key, backend_key, effect_name)


def _apply_viz_backend_policy_by_index(self, idx, update_dropdown=False):
    if not isinstance(idx, int) or idx < 0 or idx >= len(self.VIZ_BACKEND_POLICIES):
        idx = 0
    self.settings["viz_backend_policy"] = idx
    if update_dropdown and self.viz_policy_dd is not None:
        self._viz_ui_syncing = True
        try:
            self.viz_policy_dd.set_selected(idx)
        finally:
            self._viz_ui_syncing = False
    effect_name = self._selected_name_from_dropdown(self.viz_effect_dd)
    desired = self._resolve_viz_backend_key(effect_name)
    if desired != self._viz_backend_key:
        self._rebuild_visualizer_backend(desired, effect_name=effect_name)


# ---------------------------------------------------------------------------
# Dropdown event handlers
# ---------------------------------------------------------------------------

def on_viz_bars_changed(self, dd, _param):
    if self._viz_ui_syncing:
        return
    idx = dd.get_selected()
    if idx < 0 or idx >= len(self.VIZ_BAR_OPTIONS):
        return
    self._apply_viz_bars_by_count(self.VIZ_BAR_OPTIONS[idx], update_dropdown=False)
    self.schedule_save_settings()


def _apply_viz_bars_by_count(self, count, update_dropdown=False):
    try:
        c = int(count)
    except Exception:
        c = 64
    if c not in self.VIZ_BAR_OPTIONS:
        c = 64
    if self.viz is not None:
        self.viz.set_num_bars(c)
    self.settings["viz_bar_count"] = c
    if update_dropdown and self.viz_bars_dd is not None:
        self.viz_bars_dd.set_selected(self.VIZ_BAR_OPTIONS.index(c))


def _apply_spectrum_theme_by_index(self, idx, update_dropdown=False):
    if self.viz is None:
        return
    names = self.viz.get_theme_names()
    if not names:
        return
    if not isinstance(idx, int) or idx < 0 or idx >= len(names):
        idx = 0
    self.viz.set_theme(names[idx])
    self.settings["spectrum_theme"] = idx
    if update_dropdown and self.viz_theme_dd is not None:
        self.viz_theme_dd.set_selected(idx)


def _apply_viz_effect_by_index(self, idx, update_dropdown=False):
    if self.viz is None:
        return
    names = self.viz.get_effect_names()
    if not names:
        return
    if not isinstance(idx, int):
        idx = 0
    effect_name = None
    dd_names = self._drop_down_names(self.viz_effect_dd)
    if 0 <= idx < len(dd_names):
        effect_name = dd_names[idx]
    if not effect_name:
        if idx < 0 or idx >= len(names):
            idx = 0
        effect_name = names[idx]
    desired = self._resolve_viz_backend_key(effect_name)
    if desired != self._viz_backend_key:
        self._rebuild_visualizer_backend(desired, effect_name=effect_name)
        names = self.viz.get_effect_names() or []
    if effect_name not in names:
        effect_name = names[0] if names else None
    if effect_name:
        self.viz.set_effect(effect_name)
        eff_idx = names.index(effect_name)
    else:
        eff_idx = 0
    self.settings["viz_effect"] = eff_idx
    if update_dropdown and self.viz_effect_dd is not None:
        self._viz_ui_syncing = True
        try:
            self.viz_effect_dd.set_selected(eff_idx)
        finally:
            self._viz_ui_syncing = False


def on_viz_effect_changed(self, dd, _param):
    if self._viz_ui_syncing:
        return
    idx = dd.get_selected()
    if self._viz_effect_apply_source:
        try:
            GLib.source_remove(self._viz_effect_apply_source)
        except Exception:
            pass
        self._viz_effect_apply_source = None

    def _apply_effect_later():
        self._viz_effect_apply_source = None
        if self._viz_ui_syncing:
            return False
        logger.debug("Applying visualizer effect (deferred): idx=%s", idx)
        self._apply_viz_effect_by_index(idx, update_dropdown=False)
        self.schedule_save_settings()
        return False

    # Avoid mutating dropdown model/stack synchronously in GTK activate callback.
    self._viz_effect_apply_source = GLib.idle_add(_apply_effect_later)


def _apply_viz_profile_by_index(self, idx, update_dropdown=False):
    if self.viz is None:
        return
    names = self.viz.get_profile_names()
    if not names:
        return
    if not isinstance(idx, int) or idx < 0 or idx >= len(names):
        idx = 1 if len(names) > 1 else 0
    self.viz.set_profile(names[idx])
    self.settings["viz_profile"] = idx
    if update_dropdown and self.viz_profile_dd is not None:
        self.viz_profile_dd.set_selected(idx)


def on_viz_profile_changed(self, dd, _param):
    if self._viz_ui_syncing:
        return
    idx = dd.get_selected()
    if self._viz_profile_apply_source:
        try:
            GLib.source_remove(self._viz_profile_apply_source)
        except Exception:
            pass
        self._viz_profile_apply_source = None

    def _apply_profile_later():
        self._viz_profile_apply_source = None
        if self._viz_ui_syncing:
            return False
        logger.debug("Applying visualizer profile (deferred): idx=%s", idx)
        self._apply_viz_profile_by_index(idx, update_dropdown=False)
        self.schedule_save_settings()
        return False

    self._viz_profile_apply_source = GLib.idle_add(_apply_profile_later)


def on_spectrum_theme_changed(self, dd, _param):
    if self._viz_ui_syncing:
        return
    idx = dd.get_selected()
    if self._viz_theme_apply_source:
        try:
            GLib.source_remove(self._viz_theme_apply_source)
        except Exception:
            pass
        self._viz_theme_apply_source = None

    def _apply_theme_later():
        self._viz_theme_apply_source = None
        if self._viz_ui_syncing:
            return False
        logger.debug("Applying visualizer theme (deferred): idx=%s", idx)
        self._apply_spectrum_theme_by_index(idx, update_dropdown=False)
        self.schedule_save_settings()
        return False

    self._viz_theme_apply_source = GLib.idle_add(_apply_theme_later)


def on_viz_backend_policy_changed(self, dd, _param):
    if self._viz_ui_syncing:
        return
    idx = dd.get_selected()
    if self._viz_policy_apply_source:
        try:
            GLib.source_remove(self._viz_policy_apply_source)
        except Exception:
            pass
        self._viz_policy_apply_source = None

    def _apply_policy_later():
        self._viz_policy_apply_source = None
        if self._viz_ui_syncing:
            return False
        logger.debug("Applying visualizer policy (deferred): idx=%s", idx)
        self._apply_viz_backend_policy_by_index(idx, update_dropdown=False)
        self.schedule_save_settings()
        return False

    self._viz_policy_apply_source = GLib.idle_add(_apply_policy_later)


# ---------------------------------------------------------------------------
# Page / tab state
# ---------------------------------------------------------------------------

def on_viz_page_changed(self, stack, _param):
    if self.viz_theme_dd is None:
        return
    page = stack.get_visible_child_name() if stack is not None else ""
    self._viz_current_page = page or "spectrum"
    is_spectrum = page == "spectrum"
    is_lyrics = page == "lyrics"
    self.viz_theme_dd.set_visible(is_spectrum)
    if self.viz_bars_dd is not None:
        self.viz_bars_dd.set_visible(is_spectrum)
    if self.viz_policy_dd is not None:
        self.viz_policy_dd.set_visible(is_spectrum)
    if self.viz_profile_dd is not None:
        self.viz_profile_dd.set_visible(is_spectrum)
    if self.viz_effect_dd is not None:
        self.viz_effect_dd.set_visible(is_spectrum)
    if self.lyrics_font_label is not None:
        self.lyrics_font_label.set_visible(is_lyrics)
    if self.lyrics_font_dd is not None:
        self.lyrics_font_dd.set_visible(is_lyrics)
    if self.lyrics_motion_dd is not None:
        self.lyrics_motion_dd.set_visible(is_lyrics)
    if hasattr(self, "lyrics_ctrl_box") and self.lyrics_ctrl_box is not None:
        self.lyrics_ctrl_box.set_visible(is_lyrics)
    if hasattr(self, "lyrics_offset_box") and self.lyrics_offset_box is not None:
        self.lyrics_offset_box.set_visible(is_lyrics)
    self._sync_viz_tab_runtime_state()
    self._sync_spectrum_stream_state()


def _sync_viz_tab_runtime_state(self):
    revealer = getattr(self, "viz_revealer", None)
    is_open = bool(revealer is not None and revealer.get_reveal_child())
    page = str(getattr(self, "_viz_current_page", "spectrum") or "spectrum")
    spectrum_active = bool(is_open and page == "spectrum")
    lyrics_active = bool(is_open and page == "lyrics")
    if getattr(self, "viz", None) is not None and hasattr(self.viz, "set_active"):
        try:
            self.viz.set_active(spectrum_active)
        except Exception:
            pass
    if getattr(self, "bg_viz", None) is not None and hasattr(self.bg_viz, "set_active"):
        try:
            self.bg_viz.set_active(lyrics_active)
        except Exception:
            pass


def _should_enable_spectrum_stream(self):
    # Keep the spectrum stream alive regardless of viz visibility so that
    # _last_spectrum_frame stays fresh and the viz opens instantly without
    # a 0.5-1 s FFT-restart stutter.  on_spectrum_data() already skips
    # rendering (early-return) when the revealer is closed, so no extra
    # draw work is done while the viz is hidden.
    if getattr(self, "player", None) is None:
        return False
    # Lyrics static mode genuinely needs no live data.
    page = str(getattr(self, "_viz_current_page", "spectrum") or "spectrum")
    if page == "lyrics":
        revealer = getattr(self, "viz_revealer", None)
        if revealer is not None and revealer.get_reveal_child():
            motion_idx = int(self.settings.get("lyrics_bg_motion", 1) or 0)
            if motion_idx == 0:
                return False
    return True


def _sync_spectrum_stream_state(self):
    self._sync_viz_tab_runtime_state()
    if self.player is not None and hasattr(self.player, "set_spectrum_enabled"):
        self.player.set_spectrum_enabled(self._should_enable_spectrum_stream())


# ---------------------------------------------------------------------------
# Prewarm (called once from do_activate)
# ---------------------------------------------------------------------------

def _prewarm_gl_visualizer_once(self):
    # Warm up GLArea realize/shader path once without visible drawer motion.
    if bool(getattr(self, "_viz_gl_prewarm_done", False)):
        return False
    if str(getattr(self, "_viz_backend_key", "")) != "gl":
        return False
    revealer = getattr(self, "viz_revealer", None)
    root = getattr(self, "viz_root", None)
    handle = getattr(self, "viz_handle_box", None)
    if revealer is None or root is None:
        return False
    if bool(revealer.get_reveal_child()):
        return False

    self._viz_gl_prewarm_done = True
    try:
        old_dur = int(revealer.get_transition_duration() or 0)
    except Exception:
        old_dur = 0
    try:
        old_opacity = float(root.get_opacity() or 1.0)
    except Exception:
        old_opacity = 1.0
    old_handle_visible = bool(handle.get_visible()) if handle is not None else True

    try:
        revealer.set_transition_duration(0)
        root.set_opacity(0.0)
        if handle is not None:
            handle.set_visible(False)
        revealer.set_reveal_child(True)
    except Exception:
        # Best-effort only; never block startup.
        try:
            revealer.set_transition_duration(old_dur)
        except Exception:
            pass
        if handle is not None:
            handle.set_visible(old_handle_visible)
        root.set_opacity(old_opacity)
        return False

    def _finish():
        try:
            revealer.set_reveal_child(False)
            root.set_opacity(old_opacity)
            revealer.set_transition_duration(old_dur)
            if handle is not None:
                handle.set_visible(old_handle_visible)
        except Exception:
            pass
        return False

    GLib.timeout_add(70, _finish)
    return False


def _start_spectrum_stream_prewarm(self):
    # Warm up spectrum pipeline once in background to avoid first-open hitch.
    if self.player is None or (not hasattr(self.player, "set_spectrum_enabled")):
        return False
    revealer = getattr(self, "viz_revealer", None)
    if revealer is not None and bool(revealer.get_reveal_child()):
        return False
    try:
        self.player.set_spectrum_enabled(True)
    except Exception:
        return False

    if self._viz_stream_prewarm_source:
        GLib.source_remove(self._viz_stream_prewarm_source)
        self._viz_stream_prewarm_source = 0

    def _finish():
        self._viz_stream_prewarm_source = 0
        self._sync_spectrum_stream_state()
        return False

    # Keep warm briefly, then restore to intended state.
    self._viz_stream_prewarm_source = GLib.timeout_add(900, _finish)
    return False


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

def _apply_viz_panel_theme(self):
    if self.viz_stack_box is None:
        return
    is_dark = self.style_manager.get_dark()
    self.viz_stack_box.remove_css_class("viz-panel-dark")
    self.viz_stack_box.remove_css_class("viz-panel-light")
    if getattr(self, "viz_handle_box", None) is not None:
        self.viz_handle_box.remove_css_class("viz-handle-dark")
        self.viz_handle_box.remove_css_class("viz-handle-light")
    if getattr(self, "queue_anchor", None) is not None:
        self.queue_anchor.remove_css_class("queue-handle-dark")
        self.queue_anchor.remove_css_class("queue-handle-light")
    if getattr(self, "viz_root", None) is not None:
        self.viz_root.remove_css_class("viz-surface-dark")
        self.viz_root.remove_css_class("viz-surface-light")
    if is_dark:
        self.viz_stack_box.add_css_class("viz-panel-dark")
        if getattr(self, "viz_handle_box", None) is not None:
            self.viz_handle_box.add_css_class("viz-handle-dark")
        if getattr(self, "queue_anchor", None) is not None:
            self.queue_anchor.add_css_class("queue-handle-dark")
        if getattr(self, "viz_root", None) is not None:
            self.viz_root.add_css_class("viz-surface-dark")
    else:
        self.viz_stack_box.add_css_class("viz-panel-light")
        if getattr(self, "viz_handle_box", None) is not None:
            self.viz_handle_box.add_css_class("viz-handle-light")
        if getattr(self, "queue_anchor", None) is not None:
            self.queue_anchor.add_css_class("queue-handle-light")
        if getattr(self, "viz_root", None) is not None:
            self.viz_root.add_css_class("viz-surface-light")
    if self.lyrics_vbox is not None:
        self.lyrics_vbox.remove_css_class("lyrics-theme-dark")
        self.lyrics_vbox.remove_css_class("lyrics-theme-light")
        self.lyrics_vbox.add_css_class("lyrics-theme-dark" if is_dark else "lyrics-theme-light")
    if self.bg_viz is not None:
        self.bg_viz.set_theme_mode(is_dark)


# ---------------------------------------------------------------------------
# Spectrum data callback & frame blending
# ---------------------------------------------------------------------------

def on_spectrum_data(self, magnitudes, position_s=None):
    if not magnitudes:
        return
    trace = str(os.getenv("HIRESTI_VIZ_TRACE", "0")).strip().lower() in ("1", "true", "yes", "on")
    now_cb = time.monotonic()
    frame = magnitudes if isinstance(magnitudes, list) else list(magnitudes)
    self._last_spectrum_frame = frame
    self._last_spectrum_ts = now_cb
    if trace:
        if self._viz_trace_open_ts > 0.0 and (not self._viz_trace_first_real_logged):
            self._viz_trace_first_real_logged = True
            logger.info(
                "VIZ TRACE first-real: delta_open=%.1fms len=%d page=%s",
                (now_cb - self._viz_trace_open_ts) * 1000.0,
                len(frame),
                str(getattr(self, "_viz_current_page", "spectrum")),
            )
        if self._viz_trace_last_cb_ts > 0.0:
            gap_ms = (now_cb - self._viz_trace_last_cb_ts) * 1000.0
            if gap_ms >= 80.0:
                logger.info("VIZ TRACE callback-gap: %.1fms", gap_ms)
        self._viz_trace_last_cb_ts = now_cb
    # Soft handoff: don't cut placeholder on first real frame.
    # Wait for a short real-frame streak and blend from current placeholder frame.
    if int(getattr(self, "_viz_placeholder_source", 0) or 0):
        self._viz_real_frame_streak = int(getattr(self, "_viz_real_frame_streak", 0) or 0) + 1
        if self._viz_real_frame_streak == 1 and self._viz_placeholder_frame:
            self._viz_seed_frame = list(self._viz_placeholder_frame)
            self._viz_warmup_until = time.monotonic() + 0.32
        if self._viz_real_frame_streak >= 4:
            self._stop_viz_placeholder()
    else:
        self._viz_real_frame_streak = 0
    revealer = self.viz_revealer
    if revealer is None or (not revealer.get_reveal_child()):
        return
    now = time.monotonic()
    if self._viz_warmup_until > now and self._viz_seed_frame:
        t = 1.0 - ((self._viz_warmup_until - now) / max(1e-6, float(self._viz_warmup_duration_s)))
        t = max(0.0, min(1.0, t))
        frame = self._blend_spectrum_frames(self._viz_seed_frame, frame, t)
    elif self._viz_warmup_until <= now:
        self._viz_seed_frame = None
        self._viz_warmup_until = 0.0
    self._apply_viz_frame(frame)


def _apply_viz_frame(self, frame):
    if not frame:
        return
    current_page = self._viz_current_page
    if current_page == "lyrics" and self.bg_viz is not None:
        self.bg_viz.update_energy(frame)
    if current_page == "spectrum" and self.viz is not None:
        self.viz.update_data(frame)


def _stop_viz_placeholder(self):
    src = int(getattr(self, "_viz_placeholder_source", 0) or 0)
    if src:
        GLib.source_remove(src)
        self._viz_placeholder_source = 0
    self._viz_real_frame_streak = 0


def _start_viz_placeholder_if_needed(self):
    self._stop_viz_placeholder()
    revealer = getattr(self, "viz_revealer", None)
    if revealer is None or (not revealer.get_reveal_child()):
        return
    # With the always-on stream policy, _last_spectrum_ts is kept current
    # while audio is playing.  If a fresh frame arrived recently, skip the
    # synthetic placeholder entirely — real callbacks will flow right away.
    now = time.monotonic()
    if (now - float(getattr(self, "_last_spectrum_ts", 0.0) or 0.0)) < 0.35:
        return

    try:
        n = int(self.settings.get("viz_bar_count", 32) or 32)
    except Exception:
        n = 32
    n = max(8, min(128, n))
    if not self._viz_placeholder_frame or len(self._viz_placeholder_frame) != n:
        self._viz_placeholder_frame = [-60.0] * n
    self._viz_placeholder_phase = 0.0
    self._viz_real_frame_streak = 0
    start_ts = now
    duration_s = 2.0
    end_ts = start_ts + duration_s

    def _tick():
        rev = getattr(self, "viz_revealer", None)
        if rev is None or (not rev.get_reveal_child()):
            self._viz_placeholder_source = 0
            return False
        # Real data arrived steadily -> handoff in on_spectrum_data.
        if int(getattr(self, "_viz_real_frame_streak", 0) or 0) >= 4:
            self._viz_placeholder_source = 0
            return False
        if time.monotonic() > end_ts:
            self._viz_placeholder_source = 0
            return False

        now_tick = time.monotonic()
        life = max(0.0, min(1.0, (end_ts - now_tick) / max(1e-6, duration_s)))
        # Keep lively at beginning, then fade toward floor.
        energy_gate = pow(life, 0.80)

        self._viz_placeholder_phase += 0.24
        ph = self._viz_placeholder_phase
        frame = self._viz_placeholder_frame
        nn = len(frame)
        center1 = 0.14 + (0.06 * math.sin(ph * 0.23))
        center2 = 0.38 + (0.10 * math.sin((ph * 0.15) + 1.2))
        sigma1 = 0.10
        sigma2 = 0.16
        for i in range(nn):
            x = i / float(max(1, nn - 1))
            # Low-end dominant envelope + moving "energy hills".
            low_tilt = 0.36 * pow(max(0.0, 1.0 - x), 1.22)
            g1 = math.exp(-((x - center1) ** 2) / (2.0 * sigma1 * sigma1))
            g2 = math.exp(-((x - center2) ** 2) / (2.0 * sigma2 * sigma2))
            ripple = 0.042 * math.sin((x * 17.0) + (ph * 0.8))
            # Add jagged per-bin variation so neighbouring bars are less "too smooth".
            jagged = (0.030 * math.sin((i * 3.5) + (ph * 2.8))) + ((random.random() - 0.5) * 0.11)
            noise = (random.random() - 0.5) * 0.060

            target = 0.022 + low_tilt + (0.28 * g1) + (0.18 * g2) + ripple + jagged + noise
            # Rare transient peaks so placeholder feels alive, not static.
            if random.random() < 0.040:
                target += 0.28 * random.random()
            target = max(0.0, min(0.82, target * energy_gate))
            # Convert to dB-like spectrum values expected by visualizer path.
            # Keep in realistic range to avoid full-screen "max level" look.
            target_db = -60.0 + (target * 48.0)  # ~[-60 dB, -12 dB]
            # Slightly faster response, and progressively pull to floor near the end.
            blend = 0.34 if life > 0.45 else 0.24
            floor_pull = (1.0 - life) * 0.22
            frame[i] = (frame[i] * (1.0 - blend)) + (target_db * blend)
            frame[i] = (frame[i] * (1.0 - floor_pull)) + (-60.0 * floor_pull)
        self._apply_viz_frame(frame)
        return True

    self._viz_placeholder_source = GLib.timeout_add(33, _tick)


def _blend_spectrum_frames(self, seed, live, t):
    if not seed:
        return list(live or [])
    if not live:
        return list(seed)
    a = list(seed)
    b = list(live)
    n = max(len(a), len(b))
    if len(a) < n:
        a.extend([a[-1] if a else 0.0] * (n - len(a)))
    if len(b) < n:
        b.extend([b[-1] if b else 0.0] * (n - len(b)))
    k = max(0.0, min(1.0, float(t)))
    return [a[i] + ((b[i] - a[i]) * k) for i in range(n)]


# ---------------------------------------------------------------------------
# Handle alignment & animation
# ---------------------------------------------------------------------------

def _schedule_viz_handle_realign(self, animate=True):
    # Immediate pass + delayed retries to survive fullscreen/restore re-allocation jitter.
    expanded = bool(getattr(self, "viz_revealer", None) is not None and self.viz_revealer.get_reveal_child())
    self._position_viz_handle(expanded, animate=animate)

    if self._viz_handle_resize_source:
        GLib.source_remove(self._viz_handle_resize_source)
        self._viz_handle_resize_source = 0

    self._viz_handle_resize_retries = 2

    def _retry():
        expanded_now = bool(getattr(self, "viz_revealer", None) is not None and self.viz_revealer.get_reveal_child())
        self._position_viz_handle(expanded_now, animate=animate)
        self._viz_handle_resize_retries -= 1
        if self._viz_handle_resize_retries <= 0:
            self._viz_handle_resize_source = 0
            return False
        return True

    self._viz_handle_resize_source = GLib.timeout_add(120, _retry)
    return False


def toggle_visualizer(self, btn):
    """
    [Overlay 适配版]
    """
    is_visible = self.viz_revealer.get_reveal_child()
    target_state = not is_visible
    self._set_visualizer_expanded(target_state)
    self.settings["viz_expanded"] = target_state
    self.schedule_save_settings()


def _set_visualizer_expanded(self, expanded):
    trace = str(os.getenv("HIRESTI_VIZ_TRACE", "0")).strip().lower() in ("1", "true", "yes", "on")
    if expanded:
        self._viz_trace_open_ts = time.monotonic()
        self._viz_trace_last_cb_ts = 0.0
        self._viz_trace_first_real_logged = False
        self._viz_seed_frame = list(self._last_spectrum_frame) if self._last_spectrum_frame else None
        # If the stream was kept alive (always-on policy), _last_spectrum_frame
        # is fresh (<= 0.5 s old) — no blending warmup is needed.  Only warm up
        # when opening from a cold state (first ever open, or after a long pause
        # where no spectrum callbacks arrived).
        now_open = time.monotonic()
        last_ts = float(getattr(self, "_last_spectrum_ts", 0.0) or 0.0)
        frame_is_fresh = self._viz_seed_frame and ((now_open - last_ts) < 0.5)
        if frame_is_fresh:
            self._viz_warmup_until = 0.0  # skip warmup; real data is already flowing
        else:
            self._viz_warmup_until = now_open + float(self._viz_warmup_duration_s)
        if trace:
            logger.info(
                "VIZ TRACE drawer-open: seed=%s fresh=%s warmup=%.2fs page=%s",
                bool(self._viz_seed_frame),
                frame_is_fresh,
                max(0.0, self._viz_warmup_until - now_open),
                str(getattr(self, "_viz_current_page", "spectrum")),
            )
    if self._viz_open_layout_source:
        GLib.source_remove(self._viz_open_layout_source)
        self._viz_open_layout_source = 0
    if self._viz_open_stream_source:
        GLib.source_remove(self._viz_open_stream_source)
        self._viz_open_stream_source = 0
    if self._viz_handle_settle_source:
        GLib.source_remove(self._viz_handle_settle_source)
        self._viz_handle_settle_source = 0
    # 触发 Revealer 动画 (上下滑动)
    self.viz_revealer.set_reveal_child(expanded)
    if expanded:
        self._start_viz_handle_follow_transition()
    if expanded:
        # Stream is kept alive (always-on policy), so _sync here is a no-op
        # in the normal case.  Call it anyway as a safety net for edge cases
        # (first open, lyrics-static mode change, etc.).
        self._sync_spectrum_stream_state()
        # Layout padding / handle position can be deferred (not latency-critical).
        def _defer_open_layout():
            self._viz_open_layout_source = 0
            self._apply_overlay_scroll_padding(True)
            self._position_viz_handle(True, animate=False)
            return False

        self._viz_open_layout_source = GLib.timeout_add(220, _defer_open_layout)

        # Seed the visualizer immediately with the last known frame so the
        # animation tick has something to draw right away.
        if self._viz_seed_frame:
            page = str(getattr(self, "_viz_current_page", "spectrum") or "spectrum")
            if page == "spectrum" and getattr(self, "viz", None) is not None:
                self.viz.update_data(self._viz_seed_frame)
            if page == "lyrics" and getattr(self, "bg_viz", None) is not None:
                self.bg_viz.update_energy(self._viz_seed_frame)

        # Placeholder is only needed when there is no fresh real frame yet
        # (e.g. app just started, no audio ever played).
        self._start_viz_placeholder_if_needed()
    else:
        # Keep the spectrum stream running (always-on) so _last_spectrum_frame
        # stays fresh for instant re-open.  We only clean up layout and the
        # placeholder animation — no need to call _sync_spectrum_stream_state()
        # which would (no longer) disable the stream anyway.
        self._apply_overlay_scroll_padding(False)
        self._position_viz_handle(False)
        self._stop_viz_placeholder()
        if trace:
            logger.info("VIZ TRACE drawer-close")
    if expanded:
        # Temporarily disable visualizer content fade-in for latency A/B test.
        if self._viz_fade_source:
            GLib.source_remove(self._viz_fade_source)
            self._viz_fade_source = 0
        self._set_viz_content_opacity(1.0)
        self._viz_opened_once = True

    # 图标切换
    if expanded:
        self.viz_btn.set_icon_name("hiresti-pan-down-symbolic")
        self.viz_btn.add_css_class("active")
    else:
        if self._last_spectrum_frame:
            self._viz_seed_frame = list(self._last_spectrum_frame)
        self.viz_btn.set_icon_name("hiresti-pan-up-symbolic")
        self.viz_btn.remove_css_class("active")
        if self._viz_fade_source:
            GLib.source_remove(self._viz_fade_source)
            self._viz_fade_source = 0
        self._set_viz_content_opacity(0.0)


def _set_viz_content_opacity(self, alpha):
    a = max(0.0, min(1.0, float(alpha)))
    if getattr(self, "viz", None) is not None:
        self.viz.set_opacity(a)
    if getattr(self, "bg_viz", None) is not None:
        # Keep lyrics background always visible enough; avoid "all black" when
        # fade state gets out of sync with GLArea rendering.
        self.bg_viz.set_opacity(max(0.35, a))


def _start_viz_fade_in(self, duration_ms=1000):
    if self._viz_fade_source:
        GLib.source_remove(self._viz_fade_source)
        self._viz_fade_source = 0
    start_us = GLib.get_monotonic_time()
    duration_us = max(1, int(duration_ms) * 1000)

    def _tick():
        revealer = getattr(self, "viz_revealer", None)
        if revealer is None or not revealer.get_reveal_child():
            self._viz_fade_source = 0
            return False
        elapsed = GLib.get_monotonic_time() - start_us
        t = max(0.0, min(1.0, elapsed / float(duration_us)))
        self._set_viz_content_opacity(t)
        if t >= 1.0:
            self._viz_fade_source = 0
            return False
        return True

    self._viz_fade_source = GLib.timeout_add(16, _tick)


def _position_viz_handle(self, expanded, animate=True):
    box = getattr(self, "viz_handle_box", None)
    if box is None:
        return
    self._align_viz_handle_to_play_button()
    base_bottom = 0
    target = 0
    if not expanded:
        if animate:
            self._animate_viz_handle_to(base_bottom, duration_ms=180)
        else:
            box.set_margin_bottom(base_bottom)
        return
    panel_h = 0
    revealer = getattr(self, "viz_revealer", None)
    if revealer is not None:
        # During reveal animation this is the live visible height.
        panel_h = int(revealer.get_height() or 0)
    if getattr(self, "viz_root", None) is not None:
        panel_h = max(panel_h, int(self.viz_root.get_height() or 0))
    if panel_h <= 1 and getattr(self, "viz_stack", None) is not None:
        stack_h = int(self.viz_stack.get_height() or 0)
        if stack_h > 1:
            panel_h = stack_h + 36
    if panel_h <= 1:
        panel_h = 286
    target = max(base_bottom, panel_h - 24 + base_bottom - 12 - 7)
    if animate:
        self._animate_viz_handle_to(target, duration_ms=180)
    else:
        box.set_margin_bottom(target)


def _start_viz_handle_follow_transition(self):
    if self._viz_handle_settle_source:
        GLib.source_remove(self._viz_handle_settle_source)
        self._viz_handle_settle_source = 0
    if self._viz_handle_anim_source:
        GLib.source_remove(self._viz_handle_anim_source)
        self._viz_handle_anim_source = 0
    revealer = getattr(self, "viz_revealer", None)
    box = getattr(self, "viz_handle_box", None)
    if revealer is None:
        return
    if box is None:
        return
    duration_ms = int(revealer.get_transition_duration() or 220)
    start_us = GLib.get_monotonic_time()
    # Keep watcher alive a bit beyond revealer transition; position is
    # computed from live revealer height every frame, so no lag drift.
    span_us = max(120_000, (duration_ms + 120) * 1000)

    def _tick():
        rev = getattr(self, "viz_revealer", None)
        if rev is None or (not rev.get_reveal_child()):
            self._viz_handle_settle_source = 0
            return False
        live_h = int(rev.get_height() or 0)
        if live_h <= 1:
            live_h = int(getattr(self, "viz_root", None).get_height() or 0) if getattr(self, "viz_root", None) is not None else 0
        cur = max(0, live_h - 24 - 12 - 7)
        self._align_viz_handle_to_play_button()
        box.set_margin_bottom(max(0, cur))
        elapsed = GLib.get_monotonic_time() - start_us
        if elapsed >= span_us:
            self._viz_handle_settle_source = 0
            # Final settle to exact layout target.
            self._position_viz_handle(True, animate=False)
            return False
        return True

    self._viz_handle_settle_source = GLib.timeout_add(16, _tick)


def _align_viz_handle_to_play_button(self):
    box = getattr(self, "viz_handle_box", None)
    play_btn = getattr(self, "play_btn", None)
    overlay = getattr(self, "body_overlay", None)
    if box is None or play_btn is None or overlay is None:
        return
    try:
        ok, rect = play_btn.compute_bounds(overlay)
    except Exception:
        return
    if not ok or rect is None:
        return
    viz_btn = getattr(self, "viz_btn", None)
    handle_w = int(box.get_width() or (viz_btn.get_width() if viz_btn is not None else 0) or 50)
    overlay_w = int(overlay.get_width() or 0)
    center_x = float(rect.get_x()) + (float(rect.get_width()) / 2.0)
    target_start = int(round(center_x - (handle_w / 2.0)))
    if overlay_w > 0:
        target_start = max(0, min(max(0, overlay_w - handle_w), target_start))
    target_start = max(0, target_start)
    box.set_halign(Gtk.Align.START)
    box.set_margin_start(target_start)
    box.set_margin_end(0)


def _animate_viz_handle_to(self, target_bottom, duration_ms=180):
    box = getattr(self, "viz_handle_box", None)
    if box is None:
        return
    try:
        target = int(target_bottom)
    except Exception:
        target = 0
    target = max(0, min(2000, target))
    start = int(box.get_margin_bottom() or 0)
    if self._viz_handle_anim_source:
        GLib.source_remove(self._viz_handle_anim_source)
        self._viz_handle_anim_source = 0
    if duration_ms <= 0 or start == target:
        box.set_margin_bottom(target)
        return

    start_us = GLib.get_monotonic_time()
    span_us = max(1, int(duration_ms) * 1000)

    def _tick():
        elapsed = GLib.get_monotonic_time() - start_us
        t = min(1.0, max(0.0, float(elapsed) / float(span_us)))
        # Ease-out curve for a natural "pushed out" feeling.
        eased = 1.0 - ((1.0 - t) * (1.0 - t))
        cur = int(round(start + (target - start) * eased))
        box.set_margin_bottom(max(0, cur))
        if t >= 1.0:
            self._viz_handle_anim_source = 0
            return False
        return True

    self._viz_handle_anim_source = GLib.timeout_add(16, _tick)
