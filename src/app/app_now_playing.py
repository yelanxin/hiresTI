"""Now playing overlay UI and state sync."""

import hashlib
import logging
import math
import os

import cairo

from gi.repository import GLib, Gtk, Pango, Gdk, GdkPixbuf

from actions.lyrics_playback_actions import (
    NO_LYRICS_BOTTOM_HINT,
    _karaoke_active_idx,
    _karaoke_markup,
    _split_bilingual_line,
)
from core.executor import submit_daemon
from utils.helpers import download_to_cache
from ui import config as ui_config

logger = logging.getLogger(__name__)

_NOW_PLAYING_LEFT_RADIUS = 24.0
_NOW_PLAYING_RIGHT_EDGE_RADIUS = 0.0
_NOW_PLAYING_LIST_BG_FALLBACK = (0.10, 0.11, 0.14)
_NOW_PLAYING_PANEL_SIDE_MARGIN = 25
_NOW_PLAYING_CONTENT_INSET = 22
_NOW_PLAYING_COVER_FRAME_SCALE = 1.00
_NOW_PLAYING_LEFT_RATIO = 0.60
_NOW_PLAYING_RIGHT_RATIO = 0.40
_NOW_PLAYING_TRACK_INFO_WIDTH = 170
_NOW_PLAYING_TRACK_ALBUM_WIDTH = 120
_NOW_PLAYING_TRACK_DURATION_WIDTH = 64
_NOW_PLAYING_REVEAL_DURATION_MS = 260
_NOW_PLAYING_LAYOUT_SETTLE_DELAYS_MS = (_NOW_PLAYING_REVEAL_DURATION_MS + 40, _NOW_PLAYING_REVEAL_DURATION_MS + 160)
_TNUM_ATTR_LIST = Pango.AttrList.from_string("font-features 'tnum=1'")
# Seconds to look ahead when highlighting the current lyric line, so the
# highlight arrives slightly before the word is sung rather than after.
_LYRICS_LOOKAHEAD_S = 0.3


def _normalize_now_playing_cover_key(cover_ref):
    key = str(cover_ref or "").strip()
    if not key:
        return ""
    marker = "resources.tidal.com/images/"
    if marker in key:
        try:
            tail = key.split(marker, 1)[1]
            tail = tail.split("?", 1)[0].split("#", 1)[0]
            parts = [part for part in tail.split("/") if part]
            if len(parts) >= 2 and "x" in parts[-1] and "." in parts[-1]:
                return "/".join(parts[:-1])
            return tail
        except Exception:
            return key
    return key


def _format_time(seconds):
    sec = max(0, int(round(float(seconds or 0.0))))
    mins, rem = divmod(sec, 60)
    return f"{mins}:{rem:02d}"


def _now_playing_track_album_name(track):
    return str(getattr(getattr(track, "album", None), "name", "") or "Unknown Album")


def _clamp01(value):
    return max(0.0, min(1.0, float(value or 0.0)))


def _build_now_playing_track_album_label(track):
    album_name = _now_playing_track_album_name(track)
    album_lbl = Gtk.Label(
        label=album_name,
        xalign=0,
        ellipsize=3,
        css_classes=["dim-label", "track-album", "now-playing-track-album"],
    )
    album_lbl.set_tooltip_text(album_name)
    album_lbl.set_size_request(_NOW_PLAYING_TRACK_ALBUM_WIDTH, -1)
    album_lbl.set_max_width_chars(14)
    album_lbl.set_valign(Gtk.Align.CENTER)
    return album_lbl


def _build_now_playing_track_row(track, idx):
    """Build a standard track list row for the now-playing queue/album panels."""
    row = Gtk.ListBoxRow(css_classes=["track-row", "now-playing-track-row"])
    row.track_id = getattr(track, "id", None)

    box = Gtk.Box(spacing=10, margin_top=8, margin_bottom=8, margin_start=10, margin_end=10)

    stack = Gtk.Stack()
    stack.set_size_request(18, -1)
    stack.add_css_class("track-index-stack")
    idx_lbl = Gtk.Label(label=str(idx + 1), css_classes=["dim-label"])
    stack.add_named(idx_lbl, "num")
    icon = Gtk.Image(icon_name="media-playback-start-symbolic")
    icon.add_css_class("accent")
    stack.add_named(icon, "icon")
    box.append(stack)

    info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=False)
    info.set_size_request(_NOW_PLAYING_TRACK_INFO_WIDTH, -1)
    title = str(getattr(track, "name", "") or "Unknown Track")
    title_lbl = Gtk.Label(label=title, xalign=0, ellipsize=3, css_classes=["track-title"])
    title_lbl.set_single_line_mode(True)
    title_lbl.set_width_chars(22)
    title_lbl.set_max_width_chars(22)
    title_lbl.set_tooltip_text(title)
    info.append(title_lbl)
    artist_name = str(getattr(getattr(track, "artist", None), "name", "") or "")
    if artist_name:
        artist_lbl = Gtk.Label(label=artist_name, xalign=0, ellipsize=3, css_classes=["dim-label", "track-artist"])
        artist_lbl.set_single_line_mode(True)
        artist_lbl.set_width_chars(22)
        artist_lbl.set_max_width_chars(22)
        artist_lbl.set_tooltip_text(artist_name)
        info.append(artist_lbl)
    box.append(info)

    box.append(Gtk.Box(hexpand=True))
    box.append(_build_now_playing_track_album_label(track))

    dur = int(getattr(track, "duration", 0) or 0)
    dur_lbl = Gtk.Label(label=_format_time(dur), xalign=1, css_classes=["dim-label", "track-duration"])
    dur_lbl.set_attributes(_TNUM_ATTR_LIST)
    dur_lbl.set_size_request(_NOW_PLAYING_TRACK_DURATION_WIDTH, -1)
    box.append(dur_lbl)

    row.set_child(box)
    return row


def _is_descendant(widget, ancestor):
    cur = widget
    while cur is not None:
        if cur is ancestor:
            return True
        try:
            cur = cur.get_parent()
        except Exception:
            return False
    return False


def _dominant_dark_rgb_from_pixbuf(pb):
    if pb is None:
        return None
    try:
        width = int(pb.get_width() or 0)
        height = int(pb.get_height() or 0)
        rowstride = int(pb.get_rowstride() or 0)
        n_channels = int(pb.get_n_channels() or 0)
        pixels = pb.get_pixels()
    except Exception:
        return None
    if width <= 0 or height <= 0 or rowstride <= 0 or n_channels < 3:
        return None

    step = max(1, min(width, height) // 24)
    rs = gs = bs = 0.0
    total_weight = 0.0
    for y in range(0, height, step):
        base = y * rowstride
        for x in range(0, width, step):
            idx = base + (x * n_channels)
            r = pixels[idx] / 255.0
            g = pixels[idx + 1] / 255.0
            b = pixels[idx + 2] / 255.0
            lum = (0.2126 * r) + (0.7152 * g) + (0.0722 * b)
            mx = max(r, g, b)
            mn = min(r, g, b)
            sat = 0.0 if mx <= 1e-6 else (mx - mn) / mx
            # Prefer darker, still-saturated pixels so the tint feels related
            # to the artwork without drifting into washed-out gray.
            weight = pow(max(0.0, 1.0 - lum), 1.9) * (0.55 + (sat * 0.90))
            if lum > 0.68:
                weight *= 0.08
            rs += r * weight
            gs += g * weight
            bs += b * weight
            total_weight += weight

    if total_weight <= 1e-6:
        return None

    r = rs / total_weight
    g = gs / total_weight
    b = bs / total_weight
    peak = max(r, g, b, 1e-6)
    target_peak = 0.24
    if peak > target_peak:
        scale = target_peak / peak
        r *= scale
        g *= scale
        b *= scale
    elif peak < 0.10:
        scale = 0.10 / peak
        r = min(1.0, r * scale)
        g = min(1.0, g * scale)
        b = min(1.0, b * scale)

    return (_clamp01(r), _clamp01(g), _clamp01(b))


def _apply_now_playing_dynamic_color(self, rgb=None):
    provider = getattr(self, "now_playing_dynamic_provider", None)
    if provider is None:
        try:
            provider = Gtk.CssProvider()
            display = Gdk.Display.get_default()
            if display is not None:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1,
                )
            self.now_playing_dynamic_provider = provider
        except Exception:
            return

    r, g, b = tuple(rgb or _NOW_PLAYING_LIST_BG_FALLBACK)
    r8 = int(round(_clamp01(r) * 255.0))
    g8 = int(round(_clamp01(g) * 255.0))
    b8 = int(round(_clamp01(b) * 255.0))

    # Skip CSS regeneration if the quantised colour hasn't changed.
    current_rgb8 = (r8, g8, b8)
    if getattr(self, "_now_playing_last_dynamic_rgb8", None) == current_rgb8:
        return
    self._now_playing_last_dynamic_rgb8 = current_rgb8

    # Derive a bright accent colour (same hue, high luminance) for artist
    # text and the progress bar fill.  The base dark_rgb peak is ~0.24, so
    # we scale up to target_bright to make it legible on the dark overlay.
    _peak = max(r, g, b, 1e-6)
    _scale = 0.82 / _peak
    rb8 = int(round(min(1.0, r * _scale) * 255.0))
    gb8 = int(round(min(1.0, g * _scale) * 255.0))
    bb8 = int(round(min(1.0, b * _scale) * 255.0))

    css = f"""
.now-playing-lyrics-page.lyrics-active {{
    background-image:
        linear-gradient(
            180deg,
            rgba({r8}, {g8}, {b8}, 0.30),
            rgba({r8}, {g8}, {b8}, 0.30)
        );
    background-color: transparent;
    border-radius: 18px;
    border-color: rgba({r8}, {g8}, {b8}, 0.32);
}}
.now-playing-lyrics-page.lyrics-active .now-playing-lyrics-scroller,
.now-playing-lyrics-page.lyrics-active .now-playing-lyrics-scroller viewport {{
    background-image: none;
    background-color: transparent;
}}
.tracks-list.now-playing-track-list {{
    background-image: none;
    background-color: rgba({r8}, {g8}, {b8}, 0.30);
    border-color: rgba({r8}, {g8}, {b8}, 0.32);
    box-shadow: none;
}}
.now-playing-switcher button {{
    background-image: none;
    background-color: rgba({r8}, {g8}, {b8}, 0.20);
    border-color: rgba({r8}, {g8}, {b8}, 0.96);
    box-shadow: none;
}}
.now-playing-switcher button:checked {{
    background-image: none;
    background-color: rgba({r8}, {g8}, {b8}, 0.20);
    box-shadow: inset 0 -2px 0 rgba(255, 255, 255, 0.28);
}}
.now-playing-switcher button:hover {{
    background-image: none;
    background-color: rgba({r8}, {g8}, {b8}, 0.28);
}}
.now-playing-controls .transport-main-btn {{
    background-image: none;
    background-color: rgba({r8}, {g8}, {b8}, 0.20);
    border-color: rgba({r8}, {g8}, {b8}, 0.96);
    box-shadow: none;
}}
.now-playing-controls .transport-main-btn:hover {{
    background-image: none;
    background-color: rgba({r8}, {g8}, {b8}, 0.28);
}}
.now-playing-controls .transport-main-btn:active {{
    background-image: none;
    background-color: rgba({r8}, {g8}, {b8}, 0.12);
}}
.now-playing-tool-btn {{
    background-image: none;
    background-color: rgba({r8}, {g8}, {b8}, 0.20);
    border-color: rgba({r8}, {g8}, {b8}, 0.96);
    box-shadow: none;
}}
.now-playing-tool-btn:hover {{
    background-image: none;
    background-color: rgba({r8}, {g8}, {b8}, 0.28);
}}
.now-playing-tool-btn:active {{
    background-image: none;
    background-color: rgba({r8}, {g8}, {b8}, 0.12);
}}
.now-playing-info-card {{
    background-image: none;
    background-color: rgba({r8}, {g8}, {b8}, 0.35);
    border-color: rgba({r8}, {g8}, {b8}, 0.34);
    box-shadow: none;
}}
.now-playing-artist {{
    color: rgb({rb8}, {gb8}, {bb8});
}}
.now-playing-progress progress {{
    background-color: rgb({rb8}, {gb8}, {bb8});
}}
.tracks-list.now-playing-track-list image.accent {{
    color: rgb({rb8}, {gb8}, {bb8});
}}
.tracks-list.now-playing-track-list row.playing-row {{
    background-color: rgba({rb8}, {gb8}, {bb8}, 0.15);
}}
.tracks-list.now-playing-track-list row.playing-row:hover {{
    background-color: rgba({rb8}, {gb8}, {bb8}, 0.22);
}}
"""
    try:
        provider.load_from_data(css.encode())
    except Exception:
        pass


def _apply_now_playing_scrim_css(self, visible_left_w):
    provider = getattr(self, "now_playing_scrim_provider", None)
    if provider is None:
        try:
            provider = Gtk.CssProvider()
            display = Gdk.Display.get_default()
            if display is not None:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1,
                )
            self.now_playing_scrim_provider = provider
        except Exception:
            return
    css = ".now-playing-left-scrim { background: none; background-color: transparent; }"
    try:
        provider.load_from_data(css.encode())
    except Exception:
        pass


def _suppress_search_focus_after_overlay_close(self, duration_ms=240):
    try:
        now_us = GLib.get_monotonic_time()
    except Exception:
        now_us = 0
    self._search_focus_suppressed_until_us = int(now_us) + (int(duration_ms) * 1000)

    pop = getattr(self, "search_suggest_popover", None)
    if pop is not None:
        try:
            pop.popdown()
        except Exception:
            pass

    def _clear_focus():
        win = getattr(self, "win", None)
        if win is not None:
            try:
                win.set_focus(None)
            except Exception:
                pass
        return False

    # Clear focus immediately, then repeat at mid-point and end of suppress
    # window to cover cases where GTK defers focus reassignment.
    _clear_focus()
    GLib.timeout_add(max(60, int(duration_ms // 2)), _clear_focus)
    GLib.timeout_add(int(duration_ms), _clear_focus)


def _on_now_playing_anchor_released(self, gesture, x, y):
    anchor = getattr(self, "now_playing_anchor", None)
    surface = getattr(self, "now_playing_surface", None)
    hit = None
    if anchor is not None:
        try:
            hit = anchor.pick(x, y, Gtk.PickFlags.DEFAULT)
        except Exception:
            hit = None
    if surface is not None and hit is not None and _is_descendant(hit, surface):
        return
    try:
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
    except Exception:
        pass
    hide_now_playing_overlay(self)


def _rounded_rect_path(cr, x, y, width, height, top_left, top_right, bottom_right, bottom_left):
    max_radius = min(float(width), float(height)) / 2.0
    tl = max(0.0, min(float(top_left), max_radius))
    tr = max(0.0, min(float(top_right), max_radius))
    br = max(0.0, min(float(bottom_right), max_radius))
    bl = max(0.0, min(float(bottom_left), max_radius))

    cr.new_sub_path()
    cr.move_to(x + tl, y)
    cr.line_to(x + width - tr, y)
    if tr > 0.0:
        cr.arc(x + width - tr, y + tr, tr, -math.pi / 2.0, 0.0)
    else:
        cr.line_to(x + width, y)
    cr.line_to(x + width, y + height - br)
    if br > 0.0:
        cr.arc(x + width - br, y + height - br, br, 0.0, math.pi / 2.0)
    else:
        cr.line_to(x + width, y + height)
    cr.line_to(x + bl, y + height)
    if bl > 0.0:
        cr.arc(x + bl, y + height - bl, bl, math.pi / 2.0, math.pi)
    else:
        cr.line_to(x, y + height)
    cr.line_to(x, y + tl)
    if tl > 0.0:
        cr.arc(x + tl, y + tl, tl, math.pi, (math.pi * 3.0) / 2.0)
    else:
        cr.line_to(x, y)
    cr.close_path()


def _now_playing_cover_rect(src_w, src_h, dst_w, dst_h, mode="cover", frame_scale=1.0, align_x="center", align_y="center"):
    src_w = int(src_w or 0)
    src_h = int(src_h or 0)
    dst_w = int(dst_w or 0)
    dst_h = int(dst_h or 0)
    if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
        return None

    scale_bias = max(0.50, float(frame_scale or 1.0))
    target_w = float(dst_w) * scale_bias
    target_h = float(dst_h) * scale_bias
    if str(mode or "cover").lower() == "contain":
        scale = min(target_w / float(src_w), target_h / float(src_h))
    else:
        scale = max(target_w / float(src_w), target_h / float(src_h))
    draw_w = float(src_w) * scale
    draw_h = float(src_h) * scale
    if str(align_x or "center").lower() == "start":
        x = 0.0
    elif str(align_x or "center").lower() == "end":
        x = float(dst_w) - draw_w
    else:
        x = (float(dst_w) - draw_w) / 2.0
    if str(align_y or "center").lower() == "start":
        y = 0.0
    elif str(align_y or "center").lower() == "end":
        y = float(dst_h) - draw_h
    else:
        y = (float(dst_h) - draw_h) / 2.0
    return (
        x,
        y,
        draw_w,
        draw_h,
    )


def _draw_pixbuf_to_rect(cr, pixbuf, rect, alpha=1.0):
    if rect is None:
        return
    src_w = int(pixbuf.get_width() or 0)
    src_h = int(pixbuf.get_height() or 0)
    if src_w <= 0 or src_h <= 0:
        return
    x, y, draw_w, draw_h = rect
    cr.save()
    cr.translate(float(x), float(y))
    cr.scale(float(draw_w) / float(src_w), float(draw_h) / float(src_h))
    Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
    if float(alpha) < 1.0:
        cr.paint_with_alpha(max(0.0, min(1.0, float(alpha))))
    else:
        cr.paint()
    cr.restore()


def _draw_cover_fill(cr, pixbuf, width, height, alpha=1.0):
    src_w = int(pixbuf.get_width() or 0)
    src_h = int(pixbuf.get_height() or 0)
    rect = _now_playing_cover_rect(src_w, src_h, width, height, mode="cover")
    if rect is None:
        return
    _draw_pixbuf_to_rect(cr, pixbuf, rect, alpha=alpha)


def _sample_cover_background_pixbuf(pixbuf, width, height):
    if pixbuf is None:
        return None
    try:
        sample_w = max(24, min(128, int(width // 6) or 24))
        sample_h = max(24, min(128, int(height // 6) or 24))
        return pixbuf.scale_simple(sample_w, sample_h, GdkPixbuf.InterpType.BILINEAR) or pixbuf
    except Exception:
        return pixbuf


def _mix_rgb(rgb, target, factor):
    factor = _clamp01(factor)
    return tuple(_clamp01((float(src) * (1.0 - factor)) + (float(dst) * factor)) for src, dst in zip(rgb, target))


def _draw_now_playing_cover_background(cr, pixbuf, width, height, dark_rgb=None):
    base_rgb = tuple(dark_rgb or _NOW_PLAYING_LIST_BG_FALLBACK)
    cr.rectangle(0.0, 0.0, float(width), float(height))
    cr.set_source_rgb(*_mix_rgb(base_rgb, (0.0, 0.0, 0.0), 0.10))
    cr.fill()

    if pixbuf is not None:
        blurred = _sample_cover_background_pixbuf(pixbuf, width, height)
        _draw_cover_fill(cr, blurred or pixbuf, width, height, alpha=0.98)

        image_wash = cairo.LinearGradient(0.0, 0.0, 0.0, float(height))
        image_wash.add_color_stop_rgba(0.00, base_rgb[0], base_rgb[1], base_rgb[2], 0.18)
        image_wash.add_color_stop_rgba(1.00, base_rgb[0], base_rgb[1], base_rgb[2], 0.30)
        cr.rectangle(0.0, 0.0, float(width), float(height))
        cr.set_source(image_wash)
        cr.fill()

    top_rgb = _mix_rgb(base_rgb, (1.0, 1.0, 1.0), 0.10)
    bottom_rgb = _mix_rgb(base_rgb, (0.0, 0.0, 0.0), 0.24)

    linear = cairo.LinearGradient(0.0, 0.0, 0.0, float(height))
    if pixbuf is not None:
        linear.add_color_stop_rgba(0.00, top_rgb[0], top_rgb[1], top_rgb[2], 0.16)
        linear.add_color_stop_rgba(1.00, bottom_rgb[0], bottom_rgb[1], bottom_rgb[2], 0.42)
    else:
        linear.add_color_stop_rgba(0.00, top_rgb[0], top_rgb[1], top_rgb[2], 0.82)
        linear.add_color_stop_rgba(1.00, bottom_rgb[0], bottom_rgb[1], bottom_rgb[2], 1.00)
    cr.rectangle(0.0, 0.0, float(width), float(height))
    cr.set_source(linear)
    cr.fill()

    glow_rgb = _mix_rgb(base_rgb, (1.0, 1.0, 1.0), 0.22)
    glow = cairo.RadialGradient(
        float(width) * 0.50,
        float(height) * 0.35,
        0.0,
        float(width) * 0.50,
        float(height) * 0.35,
        max(float(width), float(height)) * 0.85,
    )
    glow.add_color_stop_rgba(0.00, glow_rgb[0], glow_rgb[1], glow_rgb[2], 0.12 if pixbuf is not None else 0.18)
    glow.add_color_stop_rgba(1.00, glow_rgb[0], glow_rgb[1], glow_rgb[2], 0.00)
    cr.rectangle(0.0, 0.0, float(width), float(height))
    cr.set_source(glow)
    cr.fill()


def _draw_cover_contain(cr, pixbuf, width, height):
    src_w = int(pixbuf.get_width() or 0)
    src_h = int(pixbuf.get_height() or 0)
    # Draw into a centered square (min dimension) so a 1:1 cover fills it
    # completely. The blurred background layer covers any surrounding area.
    square = max(1, int(min(width, height) * float(_NOW_PLAYING_COVER_FRAME_SCALE or 1.0)))
    off_x = (width - square) / 2.0
    off_y = (height - square) / 2.0
    rect = _now_playing_cover_rect(src_w, src_h, square, square, mode="contain")
    if rect is None:
        return
    rx, ry, rw, rh = rect
    _draw_pixbuf_to_rect(cr, pixbuf, (rx + off_x, ry + off_y, rw, rh))


def _build_now_playing_cover_surface(pixbuf, width, height, dark_rgb=None):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cache_cr = cairo.Context(surface)
    cache_cr.set_operator(cairo.Operator.SOURCE)
    cache_cr.set_source_rgba(0.0, 0.0, 0.0, 0.0)
    cache_cr.paint()
    cache_cr.set_operator(cairo.Operator.OVER)

    _rounded_rect_path(
        cache_cr,
        0.0,
        0.0,
        float(width),
        float(height),
        _NOW_PLAYING_LEFT_RADIUS,
        _NOW_PLAYING_RIGHT_EDGE_RADIUS,
        0.0,
        0.0,
    )
    cache_cr.clip()

    cache_cr.push_group()
    _draw_now_playing_cover_background(cache_cr, pixbuf, width, height, dark_rgb)
    _draw_cover_contain(cache_cr, pixbuf, width, height)

    vertical_scrim = cairo.LinearGradient(0.0, 0.0, 0.0, float(height))
    vertical_scrim.add_color_stop_rgba(0.00, 0.0, 0.0, 0.0, 0.02)
    vertical_scrim.add_color_stop_rgba(0.54, 0.0, 0.0, 0.0, 0.08)
    vertical_scrim.add_color_stop_rgba(1.00, 0.0, 0.0, 0.0, 0.58)
    cache_cr.rectangle(0.0, 0.0, float(width), float(height))
    cache_cr.set_source(vertical_scrim)
    cache_cr.fill()

    cover_group = cache_cr.pop_group()
    cache_cr.set_source(cover_group)
    cache_cr.paint()

    return surface


def _draw_now_playing_cover(area, cr, width, height, _data=None):
    width = int(width or 0)
    height = int(height or 0)
    if width <= 0 or height <= 0:
        return

    pixbuf = getattr(area, "_cover_pixbuf", None)
    dark_rgb = getattr(area, "_cover_dark_rgb", None)
    if pixbuf is not None:
        # Use the source URL as the cache key — more stable than id(pixbuf)
        # which can be reused by the GC for a different object.
        url = getattr(area, "_target_url", None) or ""
        cache_key = (url if url else id(pixbuf), width, height, tuple(dark_rgb or ()))
        cache_surface = getattr(area, "_cover_cache_surface", None)
        if cache_surface is None or getattr(area, "_cover_cache_key", None) != cache_key:
            cache_surface = _build_now_playing_cover_surface(pixbuf, width, height, dark_rgb)
            area._cover_cache_key = cache_key
            area._cover_cache_surface = cache_surface
        cr.set_source_surface(cache_surface, 0.0, 0.0)
        cr.paint()
        return

    area._cover_cache_key = None
    area._cover_cache_surface = None
    _rounded_rect_path(
        cr,
        0.0,
        0.0,
        float(width),
        float(height),
        _NOW_PLAYING_LEFT_RADIUS,
        _NOW_PLAYING_RIGHT_EDGE_RADIUS,
        0.0,
        0.0,
    )
    cr.clip()
    _draw_now_playing_cover_background(cr, None, width, height, dark_rgb)


def _set_size_request_if_changed(widget, width, height):
    if widget is None:
        return False
    target_w = int(width)
    target_h = int(height)
    current_w = None
    current_h = None
    try:
        current_w = int(widget.get_width_request())
        current_h = int(widget.get_height_request())
    except Exception:
        current_w = None
        current_h = None
    if current_w == target_w and current_h == target_h:
        return False
    widget.set_size_request(target_w, target_h)
    return True


def _schedule_now_playing_surface_resync(self, include_settle=True):
    if not hasattr(self, "_sync_now_playing_surface_size"):
        return
    if getattr(self, "now_playing_surface", None) is None and getattr(self, "content_overlay", None) is None:
        return

    idle_source = int(getattr(self, "_now_playing_resize_idle_source", 0) or 0)
    if not idle_source:

        def _run_idle():
            self._now_playing_resize_idle_source = 0
            self._sync_now_playing_surface_size()
            return False

        self._now_playing_resize_idle_source = GLib.idle_add(_run_idle)

    if not include_settle:
        return

    # Window maximize/restore and revealer transitions can finish layout a bit
    # later than the first size notification, so keep one trailing correction.
    for attr_name, delay_ms in (
        ("_now_playing_resize_settle_source", _NOW_PLAYING_LAYOUT_SETTLE_DELAYS_MS[0]),
        ("_now_playing_resize_finish_source", _NOW_PLAYING_LAYOUT_SETTLE_DELAYS_MS[1]),
    ):
        source = int(getattr(self, attr_name, 0) or 0)
        if source:
            GLib.source_remove(source)
            setattr(self, attr_name, 0)

        def _run(attr=attr_name):
            setattr(self, attr, 0)
            self._sync_now_playing_surface_size()
            return False

        setattr(self, attr_name, GLib.timeout_add(int(delay_ms), _run))


def _now_playing_track_key(track):
    if track is None:
        return ""
    track_id = str(getattr(track, "id", "") or "")
    if track_id:
        return track_id
    return str(getattr(track, "name", "") or "")


def _widget_rect_in(widget, ancestor):
    if widget is None or ancestor is None:
        return None
    try:
        w = int(widget.get_width() or 0)
        h = int(widget.get_height() or 0)
        if w <= 0 or h <= 0:
            return None
        coords = widget.translate_coordinates(ancestor, 0, 0)
        if coords is None:
            return None
        x, y = coords
        return (float(x), float(y), float(w), float(h))
    except Exception:
        return None


def _now_playing_right_content_left_in_left_stage(self):
    surface = getattr(self, "now_playing_surface", None)
    right_panel = getattr(self, "now_playing_right_panel", None)
    if surface is None or right_panel is None:
        return None

    surface_w = 0
    right_panel_w = 0
    try:
        surface_w = int(surface.get_width() or 0)
    except Exception:
        surface_w = 0
    if surface_w <= 0:
        try:
            surface_w = int(surface.get_width_request() or 0)
        except Exception:
            surface_w = 0
    try:
        right_panel_w = int(right_panel.get_width_request() or 0)
    except Exception:
        right_panel_w = 0
    if right_panel_w <= 0:
        try:
            right_panel_w = int(right_panel.get_width() or 0)
        except Exception:
            right_panel_w = 0
    if surface_w <= 0 or right_panel_w <= 0:
        return None

    return max(0.0, float(surface_w - right_panel_w - _NOW_PLAYING_CONTENT_INSET))


_NOW_PLAYING_RIGHT_MIN_W = 340


def _now_playing_split_widths(surface_w, surface_h=0):
    available_w = max(0, int(surface_w) - _NOW_PLAYING_CONTENT_INSET)
    if surface_h > 0 and available_w > 0:
        # Target a square left panel (width = height) so a 1:1 cover fills it
        # completely at the default window size. Right panel gets the remainder,
        # clamped to a minimum usable width.
        left_w = min(int(surface_h), available_w)
        right_w = max(0, available_w - left_w)
        if right_w < _NOW_PLAYING_RIGHT_MIN_W and available_w > _NOW_PLAYING_RIGHT_MIN_W:
            right_w = _NOW_PLAYING_RIGHT_MIN_W
            left_w = max(0, available_w - right_w)
        return (left_w, right_w)
    ratio_sum = max(1e-6, float(_NOW_PLAYING_LEFT_RATIO) + float(_NOW_PLAYING_RIGHT_RATIO))
    right_ratio = float(_NOW_PLAYING_RIGHT_RATIO) / ratio_sum
    right_w = int(round(float(available_w) * right_ratio))
    right_w = max(0, min(available_w, right_w))
    left_w = max(0, available_w - right_w)
    return (left_w, right_w)


def _cached_cover_path_for_ref(cache_dir, cover_ref):
    ref = str(cover_ref or "")
    if not ref or not cache_dir:
        return None
    if os.path.exists(ref):
        return ref
    return os.path.join(cache_dir, hashlib.md5(ref.encode()).hexdigest())


def _sample_cached_cover_dark_rgb(cache_path):
    if not cache_path or not os.path.exists(cache_path):
        return None
    sample_pb = None
    try:
        loader = getattr(GdkPixbuf.Pixbuf, "new_from_file_at_scale", None)
        if callable(loader):
            sample_pb = loader(cache_path, 48, 48, True)
        else:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(cache_path)
            if pixbuf is not None:
                sample_pb = pixbuf.scale_simple(48, 48, GdkPixbuf.InterpType.BILINEAR) or pixbuf
    except Exception as exc:
        logger.debug("Now playing cached cover color load failed: %s", exc)
        sample_pb = None
    return _dominant_dark_rgb_from_pixbuf(sample_pb)


def _current_playing_cover_key(self):
    track = getattr(self, "playing_track", None)
    if track is None:
        return ""
    cover_ref = getattr(track, "cover", None) or getattr(getattr(track, "album", None), "cover", None)
    if not cover_ref and hasattr(self, "backend"):
        try:
            cover_ref = self.backend.get_artwork_url(track, 320)
        except Exception:
            cover_ref = None
    elif cover_ref and hasattr(self, "_get_tidal_image_url"):
        try:
            cover_ref = self._get_tidal_image_url(cover_ref)
        except Exception:
            cover_ref = cover_ref
    return _normalize_now_playing_cover_key(cover_ref)


def _get_now_playing_player_art_dark_rgb(self):
    cover_key = _current_playing_cover_key(self)
    if not cover_key:
        return None

    player_art = getattr(self, "art_img", None)
    if player_art is None:
        return None

    player_art_target = str(getattr(player_art, "_target_url", "") or "")
    if not player_art_target or _normalize_now_playing_cover_key(player_art_target) != cover_key:
        return None

    pixbuf = getattr(player_art, "_loaded_pixbuf", None)
    if pixbuf is None:
        return None

    dark_rgb = _dominant_dark_rgb_from_pixbuf(pixbuf)
    if dark_rgb is None:
        return None

    self.now_playing_cover_rgb_cache[cover_key] = tuple(dark_rgb)
    return tuple(dark_rgb)


def _get_now_playing_cached_cover_dark_rgb(self, cover_ref):
    cover_key = _normalize_now_playing_cover_key(cover_ref)
    if not cover_key:
        return None

    cache = getattr(self, "now_playing_cover_rgb_cache", {})
    cached_rgb = cache.get(cover_key)
    if cached_rgb is not None:
        return tuple(cached_rgb)

    cache_dir = str(getattr(self, "cache_dir", "") or "")
    if not cache_dir:
        return None

    candidate_refs = [str(cover_ref or "")]
    player_art = getattr(self, "art_img", None)
    player_art_target = str(getattr(player_art, "_target_url", "") or "")
    if player_art_target and _normalize_now_playing_cover_key(player_art_target) == cover_key:
        candidate_refs.append(player_art_target)

    for candidate_ref in candidate_refs:
        cached_path = _cached_cover_path_for_ref(cache_dir, candidate_ref)
        if not cached_path:
            continue
        dark_rgb = _sample_cached_cover_dark_rgb(cached_path)
        if dark_rgb is not None:
            cache[cover_key] = tuple(dark_rgb)
            return dark_rgb
    return None


def _sync_now_playing_dynamic_color_for_current_track(self):
    dark_rgb = _get_now_playing_player_art_dark_rgb(self)
    if dark_rgb is None:
        cover_key = _current_playing_cover_key(self)
        dark_rgb = getattr(self, "now_playing_cover_rgb_cache", {}).get(cover_key)
    _apply_now_playing_dynamic_color(self, dark_rgb or _NOW_PLAYING_LIST_BG_FALLBACK)


def _prime_now_playing_cover_color(self, cover_ref):
    cover_key = _normalize_now_playing_cover_key(cover_ref)
    if not cover_key:
        return

    cache = getattr(self, "now_playing_cover_rgb_cache", {})
    dark_rgb = cache.get(cover_key)
    if dark_rgb is None:
        cache_dir = str(getattr(self, "cache_dir", "") or "")
        if not cache_dir:
            return
        cache_path = _cached_cover_path_for_ref(cache_dir, cover_ref)
        if not cache_path or not os.path.exists(cache_path):
            try:
                cache_path = download_to_cache(str(cover_ref), cache_dir)
            except Exception as exc:
                logger.debug("Now playing cover color prime download failed: %s", exc)
                cache_path = None
        dark_rgb = _sample_cached_cover_dark_rgb(cache_path)
        if dark_rgb is None:
            return
        cache[cover_key] = tuple(dark_rgb)

    dark_rgb = tuple(dark_rgb)

    def apply():
        if _current_playing_cover_key(self) != cover_key:
            return False
        _apply_now_playing_dynamic_color(self, dark_rgb)
        return False

    GLib.idle_add(apply)


def _load_now_playing_cover(self, cover_ref):
    area = getattr(self, "now_playing_art_img", None)
    if area is None:
        return

    if not cover_ref:
        area._target_url = ""
        area._cover_pixbuf = None
        area._cover_dark_rgb = None
        area._cover_cache_key = None
        area._cover_cache_surface = None
        _apply_now_playing_dynamic_color(self, _NOW_PLAYING_LIST_BG_FALLBACK)
        area.queue_draw()
        return

    area._target_url = str(cover_ref)
    cover_key = _normalize_now_playing_cover_key(cover_ref)
    cached_dark_rgb = _get_now_playing_cached_cover_dark_rgb(self, cover_ref)
    if cached_dark_rgb is not None:
        area._cover_dark_rgb = tuple(cached_dark_rgb)
        _apply_now_playing_dynamic_color(self, cached_dark_rgb)

    def task():
        local_path = None
        pixbuf = None
        dark_rgb = None
        try:
            local_path = download_to_cache(str(cover_ref), self.cache_dir)
        except Exception as exc:
            logger.debug("Now playing cover download failed: %s", exc)
            local_path = None
        if local_path:
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(local_path)
                sample_pb = pixbuf
                try:
                    sample_pb = pixbuf.scale_simple(48, 48, GdkPixbuf.InterpType.BILINEAR) or pixbuf
                except Exception:
                    sample_pb = pixbuf
                dark_rgb = _dominant_dark_rgb_from_pixbuf(sample_pb)
            except Exception as exc:
                logger.debug("Now playing cover pixbuf load failed: %s", exc)
                pixbuf = None
                dark_rgb = None

        def apply():
            if getattr(area, "_target_url", "") != str(cover_ref):
                return False
            area._cover_pixbuf = pixbuf
            area._cover_dark_rgb = tuple(dark_rgb) if dark_rgb is not None else None
            area._cover_cache_key = None
            area._cover_cache_surface = None
            if dark_rgb is not None:
                self.now_playing_cover_rgb_cache[cover_key] = tuple(dark_rgb)
            _apply_now_playing_dynamic_color(self, dark_rgb or _NOW_PLAYING_LIST_BG_FALLBACK)
            area.queue_draw()
            return False

        GLib.idle_add(apply)

    submit_daemon(task)


def _sync_now_playing_surface_size(self):
    surface = getattr(self, "now_playing_surface", None)
    left_stage = getattr(self, "now_playing_left_stage", None)
    meta_panel = getattr(self, "now_playing_meta_panel", None)
    progress_box = getattr(self, "now_playing_progress_box", None)
    right_panel = getattr(self, "now_playing_right_panel", None)
    art_img = getattr(self, "now_playing_art_img", None)
    overlay = getattr(self, "content_overlay", None)
    if surface is None:
        return False

    overlay_h = 0
    overlay_w = 0
    if overlay is not None:
        try:
            overlay_h = int(overlay.get_height() or 0)
        except Exception:
            overlay_h = 0
        try:
            overlay_w = int(overlay.get_width() or 0)
        except Exception:
            overlay_w = 0
    if overlay_h <= 0 and getattr(self, "content_window_handle", None) is not None:
        try:
            overlay_h = int(self.content_window_handle.get_height() or 0)
        except Exception:
            overlay_h = 0
    if overlay_w <= 0 and getattr(self, "content_window_handle", None) is not None:
        try:
            overlay_w = int(self.content_window_handle.get_width() or 0)
        except Exception:
            overlay_w = 0
    if overlay_h <= 0 and getattr(self, "win", None) is not None:
        try:
            overlay_h = int(self.win.get_height() or 0)
        except Exception:
            overlay_h = 0
    if overlay_w <= 0 and getattr(self, "win", None) is not None:
        try:
            overlay_w = int(self.win.get_width() or 0)
        except Exception:
            overlay_w = 0
    if overlay_h <= 0:
        overlay_h = int(ui_config.WINDOW_HEIGHT)
    if overlay_w <= 0:
        overlay_w = int(ui_config.WINDOW_WIDTH)

    # Keep Now Playing width exactly aligned with the main bottom player bar.
    # Use the real rendered bar width and center-align the surface.
    bottom_bar = getattr(self, "bottom_bar", None)
    target_surface_w = max(420, int(overlay_w) - (2 * int(_NOW_PLAYING_PANEL_SIDE_MARGIN)))
    if overlay is not None and bottom_bar is not None:
        try:
            ok, rect = bottom_bar.compute_bounds(overlay)
        except Exception:
            ok, rect = False, None
        if ok and rect is not None:
            bar_w = int(round(float(rect.get_width() or 0.0)))
            if bar_w > 0:
                target_surface_w = max(420, bar_w)
    try:
        surface.set_halign(Gtk.Align.CENTER)
    except Exception:
        pass
    try:
        if int(surface.get_margin_start() or 0) != 0:
            surface.set_margin_start(0)
    except Exception:
        surface.set_margin_start(0)
    try:
        if int(surface.get_margin_end() or 0) != 0:
            surface.set_margin_end(0)
    except Exception:
        surface.set_margin_end(0)

    margin_top = 0
    margin_bottom = 0
    try:
        margin_top = int(surface.get_margin_top() or 0)
    except Exception:
        margin_top = 0
    try:
        margin_bottom = int(surface.get_margin_bottom() or 0)
    except Exception:
        margin_bottom = 0
    target_h = max(320, int(overlay_h) - margin_top - margin_bottom)
    _set_size_request_if_changed(surface, target_surface_w, target_h)
    surface_w = int(target_surface_w)
    left_target_w, right_panel_w = _now_playing_split_widths(surface_w, target_h)
    if right_panel is not None:
        _set_size_request_if_changed(right_panel, right_panel_w, -1)
    visible_left_w = None
    if left_stage is not None:
        visible_left_w = left_target_w
        _set_size_request_if_changed(left_stage, left_target_w, -1)
    self.now_playing_visible_left_w = visible_left_w or 0
    if meta_panel is not None:
        meta_target_w = max(280, int(surface_w * 0.36))
        if visible_left_w is not None:
            meta_target_w = max(280, int(visible_left_w * 0.80))
            meta_target_w = min(meta_target_w, max(260, visible_left_w - 56))
        try:
            if int(meta_panel.get_margin_start() or 0) != 0:
                meta_panel.set_margin_start(0)
        except Exception:
            meta_panel.set_margin_start(0)
        _set_size_request_if_changed(meta_panel, meta_target_w, -1)
        if progress_box is not None:
            _set_size_request_if_changed(progress_box, meta_target_w, -1)
    _apply_now_playing_scrim_css(self, visible_left_w or 0)
    return False


def _on_now_playing_stack_changed(self, *_args):
    stack = getattr(self, "now_playing_stack", None)
    right_panel = getattr(self, "now_playing_right_panel", None)
    lyrics_page = getattr(self, "now_playing_lyrics_page", None)
    if stack is None:
        return
    try:
        visible_name = stack.get_visible_child_name()
    except Exception:
        visible_name = None

    if right_panel is not None:
        try:
            right_panel.remove_css_class("lyrics-active")
        except Exception:
            pass
    if lyrics_page is not None:
        try:
            if visible_name == "lyrics":
                lyrics_page.add_css_class("lyrics-active")
            else:
                lyrics_page.remove_css_class("lyrics-active")
        except Exception:
            pass

    try:
        if visible_name == "lyrics":
            pos_s, _dur_s = self.player.get_position()
            self._sync_now_playing_lyrics(pos_s)
    except Exception:
        pass


def _build_now_playing_left_panel(self, layout):
    """Build the left half of the overlay: cover art, track info, and transport controls."""
    left = Gtk.Overlay(
        hexpand=False,
        vexpand=True,
        halign=Gtk.Align.CENTER,
        valign=Gtk.Align.FILL,
        css_classes=["now-playing-left"],
    )
    left.set_size_request(720, -1)
    self.now_playing_left_stage = left
    layout.append(left)

    self.now_playing_art_img = Gtk.DrawingArea(css_classes=["now-playing-cover"])
    self.now_playing_art_img.set_hexpand(True)
    self.now_playing_art_img.set_vexpand(True)
    self.now_playing_art_img.set_draw_func(_draw_now_playing_cover)
    left.set_child(self.now_playing_art_img)

    left_scrim = Gtk.Box(hexpand=True, vexpand=True, css_classes=["now-playing-left-scrim"])
    left.add_overlay(left_scrim)

    left_top = Gtk.Box(
        spacing=8,
        hexpand=True,
        halign=Gtk.Align.FILL,
        valign=Gtk.Align.START,
        css_classes=["now-playing-left-top"],
    )
    left_top.set_margin_top(_NOW_PLAYING_CONTENT_INSET)
    left_top.set_margin_start(_NOW_PLAYING_CONTENT_INSET)
    left_top.set_margin_end(_NOW_PLAYING_CONTENT_INSET)
    left_top.append(Gtk.Label(label="Now Playing", xalign=0, css_classes=["now-playing-kicker"], hexpand=True))
    left.add_overlay(left_top)

    meta_panel = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        hexpand=False,
        valign=Gtk.Align.END,
        halign=Gtk.Align.CENTER,
        css_classes=["now-playing-meta-panel"],
    )
    self.now_playing_meta_panel = meta_panel
    left.add_overlay(meta_panel)

    info_card = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        hexpand=True,
        halign=Gtk.Align.FILL,
        css_classes=["now-playing-info-card"],
    )
    meta_panel.append(info_card)

    meta_tool_band = Gtk.Overlay(hexpand=True, halign=Gtk.Align.FILL, valign=Gtk.Align.END)

    track_meta_box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=6,
        hexpand=True,
        halign=Gtk.Align.FILL,
    )
    track_meta_box.set_valign(Gtk.Align.END)
    # Reserve vertical room for the floating tool-row so long text grows upward
    # instead of overlapping the three action buttons.
    track_meta_box.set_margin_bottom(42)
    info_card.append(meta_tool_band)
    meta_tool_band.set_child(track_meta_box)

    self.now_playing_title_label = Gtk.Label(
        label="Nothing playing",
        xalign=0,
        wrap=True,
        hexpand=True,
        halign=Gtk.Align.FILL,
        css_classes=["now-playing-title"],
    )
    self.now_playing_title_label.set_max_width_chars(28)
    track_meta_box.append(self.now_playing_title_label)

    self.now_playing_artist_label = Gtk.Label(
        label="",
        xalign=0,
        wrap=True,
        hexpand=True,
        halign=Gtk.Align.FILL,
        css_classes=["now-playing-artist"],
    )
    track_meta_box.append(self.now_playing_artist_label)

    self.now_playing_album_label = Gtk.Label(
        label="",
        xalign=0,
        wrap=True,
        hexpand=True,
        halign=Gtk.Align.FILL,
        css_classes=["now-playing-album"],
    )
    track_meta_box.append(self.now_playing_album_label)

    controls_stack = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        hexpand=True,
        halign=Gtk.Align.FILL,
        css_classes=["now-playing-control-stack"],
    )
    controls_stack.set_vexpand(False)

    tool_row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, css_classes=["now-playing-tool-row"])
    tool_row.set_vexpand(False)
    tool_row.set_halign(Gtk.Align.CENTER)
    tool_row.set_valign(Gtk.Align.END)
    self.now_playing_tool_row = tool_row

    self.now_playing_track_fav_btn = Gtk.Button(
        icon_name="hiresti-favorite-outline-symbolic",
        css_classes=["flat", "circular", "player-side-btn", "now-playing-tool-btn", "now-playing-track-fav-btn"],
        valign=Gtk.Align.CENTER,
        visible=False,
        sensitive=False,
    )
    self.now_playing_track_fav_btn.set_tooltip_text("Favorite Track")
    self.now_playing_track_fav_btn.connect("clicked", self.on_track_fav_clicked)
    tool_row.append(self.now_playing_track_fav_btn)

    self.now_playing_mode_btn = Gtk.Button(
        icon_name=self.MODE_ICONS.get(self.play_mode, "hiresti-mode-loop-symbolic"),
        css_classes=["flat", "circular", "player-side-btn", "now-playing-tool-btn"],
    )
    self.now_playing_mode_btn.set_tooltip_text(self.MODE_TOOLTIPS.get(self.play_mode, "Loop All (Album/Playlist)"))
    self.now_playing_mode_btn.connect("clicked", self.on_toggle_mode)
    tool_row.append(self.now_playing_mode_btn)

    self.now_playing_status_btn = Gtk.Button(
        icon_name="hiresti-status-normal-symbolic",
        css_classes=["flat", "circular", "player-side-btn", "now-playing-tool-btn"],
    )
    self.now_playing_status_btn.set_focusable(False)
    self.now_playing_status_btn.set_tooltip_text("Normal Mode")
    tool_row.append(self.now_playing_status_btn)

    self.now_playing_dsp_btn = Gtk.Button(
        icon_name="hiresti-eq-symbolic",
        css_classes=["flat", "circular", "player-side-btn", "now-playing-tool-btn", "eq-btn"],
    )
    self.now_playing_dsp_btn.set_tooltip_text("Open DSP Workspace")
    self.now_playing_dsp_btn.connect("clicked", self.open_dsp_workspace)
    tool_row.append(self.now_playing_dsp_btn)

    self.now_playing_vol_btn = Gtk.Button(
        icon_name="hiresti-volume-high-symbolic",
        css_classes=["flat", "circular", "player-side-btn", "now-playing-tool-btn"],
    )
    self.now_playing_vol_btn.set_tooltip_text("Adjust Volume")
    self.now_playing_vol_pop = self._build_volume_popover(scale_attr="now_playing_vol_scale")
    self.now_playing_vol_pop.set_parent(self.now_playing_vol_btn)
    self.now_playing_vol_btn.connect("clicked", lambda _b: self.now_playing_vol_pop.popup())
    tool_row.append(self.now_playing_vol_btn)

    meta_tool_band.add_overlay(tool_row)

    progress_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, css_classes=["now-playing-progress-box"])
    progress_box.set_hexpand(True)
    progress_box.set_halign(Gtk.Align.FILL)
    self.now_playing_progress_box = progress_box
    self.now_playing_elapsed_label = Gtk.Label(label="0:00", xalign=0, css_classes=["dim-label"])
    self.now_playing_elapsed_label.set_attributes(_TNUM_ATTR_LIST)
    self.now_playing_elapsed_label.set_width_chars(5)
    progress_box.append(self.now_playing_elapsed_label)
    self.now_playing_progress = Gtk.ProgressBar(css_classes=["now-playing-progress"])
    self.now_playing_progress.set_hexpand(True)
    self.now_playing_progress.set_valign(Gtk.Align.CENTER)
    progress_box.append(self.now_playing_progress)
    self.now_playing_total_label = Gtk.Label(label="0:00", xalign=1, css_classes=["dim-label"])
    self.now_playing_total_label.set_attributes(_TNUM_ATTR_LIST)
    self.now_playing_total_label.set_width_chars(5)
    progress_box.append(self.now_playing_total_label)
    controls_stack.append(progress_box)

    ctrls = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER, css_classes=["now-playing-controls"])
    self.now_playing_controls_box = ctrls
    btn_prev = Gtk.Button(icon_name="media-skip-backward-symbolic", css_classes=["flat", "transport-btn"])
    btn_prev.connect("clicked", self.on_prev_track)
    ctrls.append(btn_prev)

    self.now_playing_play_btn = Gtk.Button(
        icon_name="media-playback-start-symbolic",
        css_classes=["transport-main-btn"],
    )
    self.now_playing_play_btn.connect("clicked", self.on_play_pause)
    ctrls.append(self.now_playing_play_btn)

    btn_next = Gtk.Button(icon_name="media-skip-forward-symbolic", css_classes=["flat", "transport-btn"])
    btn_next.connect("clicked", lambda _b: self.on_next_track())
    ctrls.append(btn_next)
    controls_stack.append(ctrls)

    info_card.append(controls_stack)

    # Collapse button — bottom-left corner of the left panel
    collapse_btn = Gtk.Button(
        icon_name="go-down-symbolic",
        css_classes=["flat", "circular", "now-playing-collapse-btn"],
        tooltip_text="Close Now Playing",
        halign=Gtk.Align.START,
        valign=Gtk.Align.END,
    )
    collapse_btn.set_margin_start(_NOW_PLAYING_CONTENT_INSET - 15)
    collapse_btn.set_margin_bottom(_NOW_PLAYING_CONTENT_INSET - 15)
    collapse_btn.connect("clicked", self.hide_now_playing_overlay)
    left.add_overlay(collapse_btn)
    self.now_playing_collapse_btn = collapse_btn


def _build_now_playing_right_panel(self, layout):
    """Build the right half of the overlay: tab switcher and Queue/Album/Lyrics pages."""
    right = Gtk.Overlay(
        hexpand=False,
        vexpand=True,
        halign=Gtk.Align.FILL,
        valign=Gtk.Align.FILL,
        css_classes=["now-playing-right"],
    )
    right.set_margin_top(0)
    right.set_margin_start(0)
    right.set_margin_end(0)
    right.set_size_request(420, -1)
    self.now_playing_right_panel = right
    layout.append(right)

    right_body = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=14,
        hexpand=True,
        vexpand=True,
        halign=Gtk.Align.FILL,
        valign=Gtk.Align.FILL,
    )
    right.set_child(right_body)

    right_head = Gtk.Box(
        hexpand=True,
        halign=Gtk.Align.FILL,
        valign=Gtk.Align.START,
    )
    right_head.set_margin_top(0)

    self.now_playing_switcher = Gtk.StackSwitcher()
    self.now_playing_switcher.add_css_class("now-playing-switcher")
    self.now_playing_switcher.set_halign(Gtk.Align.START)
    self.now_playing_switcher.set_valign(Gtk.Align.START)
    right_head.append(self.now_playing_switcher)

    self.now_playing_close_btn = Gtk.Button(icon_name="window-close-symbolic", css_classes=["flat", "circular"])
    self.now_playing_close_btn.set_tooltip_text("Close Now Playing")
    self.now_playing_close_btn.connect("clicked", self.hide_now_playing_overlay)
    self.now_playing_close_btn.set_halign(Gtk.Align.END)
    self.now_playing_close_btn.set_valign(Gtk.Align.START)
    self.now_playing_close_btn.set_margin_top(_NOW_PLAYING_CONTENT_INSET - 15)
    self.now_playing_close_btn.set_margin_end(_NOW_PLAYING_CONTENT_INSET - 15)
    right.add_overlay(self.now_playing_close_btn)
    right_body.append(right_head)

    self.now_playing_stack = Gtk.Stack(
        transition_type=Gtk.StackTransitionType.NONE,
        hexpand=True,
        vexpand=True,
    )
    self.now_playing_stack.add_css_class("now-playing-stack")
    self.now_playing_switcher.set_stack(self.now_playing_stack)

    queue_page = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=10,
        hexpand=True,
        vexpand=True,
        css_classes=["now-playing-stack-page"],
    )
    self.now_playing_queue_count_label = None

    self.now_playing_queue_list = Gtk.ListBox(css_classes=["tracks-list", "now-playing-track-list"])
    self.now_playing_queue_list.connect("row-activated", self.on_queue_track_selected)
    queue_shell = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        hexpand=True,
        vexpand=True,
        css_classes=["now-playing-list-shell"],
    )
    queue_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    queue_scroll.add_css_class("now-playing-track-scroll")
    queue_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    queue_scroll.set_child(self.now_playing_queue_list)
    queue_shell.append(queue_scroll)
    self.now_playing_queue_scroll = queue_scroll
    queue_page.append(queue_shell)

    album_page = Gtk.Overlay(
        hexpand=True,
        vexpand=True,
        css_classes=["now-playing-stack-page"],
    )
    self.now_playing_album_count_label = None

    self.now_playing_track_list = Gtk.ListBox(css_classes=["tracks-list", "now-playing-track-list"])
    self.now_playing_track_list.connect("row-activated", self.on_now_playing_track_selected)
    album_shell = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        hexpand=True,
        vexpand=True,
        css_classes=["now-playing-list-shell"],
    )
    album_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    album_scroll.add_css_class("now-playing-track-scroll")
    album_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    album_scroll.set_child(self.now_playing_track_list)
    album_shell.append(album_scroll)
    self.now_playing_album_scroll = album_scroll
    album_page.set_child(album_shell)

    # Floating action: jump from the album tab back into the main album page.
    self.now_playing_open_album_btn = Gtk.Button(
        css_classes=["flat", "circular", "now-playing-collapse-btn", "now-playing-open-album-btn"],
        halign=Gtk.Align.END,
        valign=Gtk.Align.END,
        sensitive=False,
    )
    self.now_playing_open_album_btn.set_child(Gtk.Image.new_from_icon_name("go-next-symbolic"))
    self.now_playing_open_album_btn.set_tooltip_text("Open Album in Main View")
    self.now_playing_open_album_btn.set_margin_end(58)
    self.now_playing_open_album_btn.set_margin_bottom(18)
    self.now_playing_open_album_btn.connect("clicked", self.on_now_playing_open_album_clicked)
    album_page.add_overlay(self.now_playing_open_album_btn)

    lyrics_page = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=10,
        hexpand=True,
        vexpand=True,
        css_classes=["now-playing-stack-page", "now-playing-lyrics-page"],
    )
    self.now_playing_lyrics_page = lyrics_page

    self.now_playing_lyrics_scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    self.now_playing_lyrics_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    self.now_playing_lyrics_scroller.add_css_class("lyrics-scroller")
    self.now_playing_lyrics_scroller.add_css_class("now-playing-lyrics-scroller")

    self.now_playing_lyrics_vbox = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=8,
        css_classes=["now-playing-lyrics-box", "lyrics-theme-dark", "lyrics-font-studio"],
    )
    self.now_playing_lyrics_vbox.set_halign(Gtk.Align.CENTER)
    self.now_playing_lyrics_vbox.set_margin_top(30)
    self.now_playing_lyrics_vbox.set_margin_bottom(30)
    self.now_playing_lyrics_scroller.set_child(self.now_playing_lyrics_vbox)
    lyrics_page.append(self.now_playing_lyrics_scroller)

    self.now_playing_stack.add_titled(queue_page, "queue", "Queue")
    self.now_playing_stack.add_titled(album_page, "album", "Album")
    self.now_playing_stack.add_titled(lyrics_page, "lyrics", "Lyrics")
    self.now_playing_stack.set_visible_child_name("queue")
    self.now_playing_stack.connect("notify::visible-child-name", lambda *_args: _on_now_playing_stack_changed(self))
    right_body.append(self.now_playing_stack)


def build_now_playing_overlay(self):
    overlay = getattr(self, "content_overlay", None)
    if overlay is None or getattr(self, "now_playing_revealer", None) is not None:
        return

    self.now_playing_backdrop = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        hexpand=True,
        vexpand=True,
        halign=Gtk.Align.FILL,
        valign=Gtk.Align.FILL,
        css_classes=["now-playing-shell"],
    )
    self.now_playing_backdrop.set_visible(False)
    self.now_playing_backdrop.set_can_target(False)
    overlay.add_overlay(self.now_playing_backdrop)

    self.now_playing_anchor = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=0,
        hexpand=True,
        vexpand=True,
        halign=Gtk.Align.FILL,
        valign=Gtk.Align.END,
    )
    self.now_playing_anchor.set_can_target(False)
    anchor_click = Gtk.GestureClick()
    anchor_click.set_button(0)
    anchor_click.connect(
        "released",
        lambda gesture, _n_press, x, y: _on_now_playing_anchor_released(self, gesture, x, y),
    )
    self.now_playing_anchor.add_controller(anchor_click)

    self.now_playing_revealer = Gtk.Revealer(
        transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
        transition_duration=_NOW_PLAYING_REVEAL_DURATION_MS,
    )
    self.now_playing_revealer.set_reveal_child(False)
    self.now_playing_revealer.set_hexpand(True)
    self.now_playing_revealer.set_vexpand(False)
    self.now_playing_revealer.set_halign(Gtk.Align.FILL)
    self.now_playing_revealer.set_valign(Gtk.Align.END)
    self.now_playing_revealer.set_visible(False)
    self.now_playing_revealer.set_can_target(False)
    try:
        self.now_playing_revealer.connect(
            "notify::child-revealed",
            lambda *_args: _schedule_now_playing_surface_resync(self, include_settle=False),
        )
    except Exception:
        pass

    surface = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=24,
        hexpand=True,
        vexpand=True,
        halign=Gtk.Align.FILL,
        valign=Gtk.Align.FILL,
        margin_top=0,
        margin_bottom=0,
        margin_start=_NOW_PLAYING_PANEL_SIDE_MARGIN,
        margin_end=_NOW_PLAYING_PANEL_SIDE_MARGIN,
        css_classes=["now-playing-surface"],
    )
    self.now_playing_surface = surface

    layout = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=_NOW_PLAYING_CONTENT_INSET,
        hexpand=True,
        vexpand=True,
        halign=Gtk.Align.FILL,
        valign=Gtk.Align.FILL,
        css_classes=["now-playing-layout"],
    )
    surface.append(layout)

    _build_now_playing_left_panel(self, layout)
    _build_now_playing_right_panel(self, layout)

    self.now_playing_revealer.set_child(surface)
    self.now_playing_anchor.append(self.now_playing_revealer)
    overlay.add_overlay(self.now_playing_anchor)
    # overlay width/height cover all normal resize events; fullscreened/maximized
    # are kept separately because state transitions may not immediately change
    # the overlay allocation (the settle timeouts handle the delayed re-layout).
    overlay.connect("notify::height", lambda *_args: _schedule_now_playing_surface_resync(self))
    overlay.connect("notify::width", lambda *_args: _schedule_now_playing_surface_resync(self))
    win = getattr(self, "win", None)
    if win is not None:
        for prop in ("fullscreened", "maximized"):
            try:
                win.connect(f"notify::{prop}", lambda *_args: _schedule_now_playing_surface_resync(self))
            except Exception:
                pass
    _schedule_now_playing_surface_resync(self)

    self.now_playing_cover_rgb_cache = {}

    self._render_now_playing_queue([])
    self._render_now_playing_album_tracks([])
    self._render_now_playing_lyrics(None, "Lyrics will appear for the current track.")
    _apply_now_playing_dynamic_color(self, _NOW_PLAYING_LIST_BG_FALLBACK)


def is_now_playing_overlay_open(self):
    revealer = getattr(self, "now_playing_revealer", None)
    return bool(revealer is not None and revealer.get_reveal_child())


def _now_playing_content_is_current(self):
    return _now_playing_track_key(getattr(self, "playing_track", None)) == str(
        getattr(self, "_now_playing_render_track_key", "") or ""
    )


def show_now_playing_overlay(self, _btn=None):
    if not getattr(self, "playing_track", None):
        return
    if getattr(self, "is_mini_mode", False):
        self.toggle_mini_mode(None)
    if hasattr(self, "close_queue_drawer"):
        self.close_queue_drawer()
    hide_source = int(getattr(self, "_now_playing_hide_source", 0) or 0)
    if hide_source:
        GLib.source_remove(hide_source)
        self._now_playing_hide_source = 0
    focus_source = int(getattr(self, "_now_playing_focus_source", 0) or 0)
    if focus_source:
        GLib.source_remove(focus_source)
        self._now_playing_focus_source = 0
    if self.now_playing_stack is not None:
        try:
            if self.now_playing_stack.get_visible_child_name() != "queue":
                self.now_playing_stack.set_visible_child_name("queue")
        except Exception:
            pass
    _sync_now_playing_dynamic_color_for_current_track(self)
    _schedule_now_playing_surface_resync(self)
    needs_refresh = not _now_playing_content_is_current(self)
    if self.now_playing_backdrop is not None:
        self.now_playing_backdrop.set_visible(True)
    if self.now_playing_anchor is not None:
        self.now_playing_anchor.set_can_target(True)
    if self.now_playing_revealer is not None:
        self.now_playing_revealer.set_visible(True)
        self.now_playing_revealer.set_can_target(True)
        revealer = self.now_playing_revealer

        def _begin_reveal():
            if getattr(self, "now_playing_revealer", None) is not revealer:
                return False
            revealer.set_reveal_child(True)
            self._sync_now_playing_surface_size()
            _schedule_now_playing_surface_resync(self)
            if needs_refresh:
                # Defer content rebuild to next idle so GTK can render the
                # first animation frame before doing the heavy queue rebuild.
                def _do_refresh():
                    if getattr(self, "now_playing_revealer", None) is not revealer:
                        return False
                    self._refresh_now_playing_from_track()
                    return False
                GLib.idle_add(_do_refresh)
            else:
                try:
                    pos_s, dur_s = self.player.get_position()
                    playing_now = bool(self.player.is_playing())
                except Exception:
                    pos_s, dur_s, playing_now = 0.0, float(getattr(getattr(self, "playing_track", None), "duration", 0) or 0.0), False
                self._sync_now_playing_overlay_state(pos_s, dur_s, playing_now)
            return False

        GLib.idle_add(_begin_reveal)
    if self.now_playing_close_btn is not None:
        focus_delay = max(140, int((self.now_playing_revealer.get_transition_duration() or _NOW_PLAYING_REVEAL_DURATION_MS) * 0.65))
        self._now_playing_focus_source = GLib.timeout_add(
            focus_delay,
            lambda: (
                setattr(self, "_now_playing_focus_source", 0),
                self.now_playing_close_btn.grab_focus(),
                False,
            )[2],
        )


def hide_now_playing_overlay(self, _btn=None):
    revealer = getattr(self, "now_playing_revealer", None)
    if revealer is not None:
        _suppress_search_focus_after_overlay_close(self)
        revealer.set_reveal_child(False)
        revealer.set_can_target(False)
        duration_ms = int(revealer.get_transition_duration() or 0)
        if getattr(self, "now_playing_anchor", None) is not None:
            self.now_playing_anchor.set_can_target(False)
        focus_source = int(getattr(self, "_now_playing_focus_source", 0) or 0)
        if focus_source:
            GLib.source_remove(focus_source)
            self._now_playing_focus_source = 0

        hide_source = int(getattr(self, "_now_playing_hide_source", 0) or 0)
        if hide_source:
            GLib.source_remove(hide_source)
            self._now_playing_hide_source = 0

        def _finish_hide():
            self._now_playing_hide_source = 0
            if getattr(self, "now_playing_revealer", None) is revealer and not revealer.get_reveal_child():
                revealer.set_visible(False)
                if getattr(self, "now_playing_backdrop", None) is not None:
                    self.now_playing_backdrop.set_visible(False)
            return False

        if duration_ms > 0:
            self._now_playing_hide_source = GLib.timeout_add(duration_ms, _finish_hide)
        else:
            revealer.set_visible(False)
            if getattr(self, "now_playing_backdrop", None) is not None:
                self.now_playing_backdrop.set_visible(False)


def toggle_now_playing_overlay(self, _btn=None):
    if is_now_playing_overlay_open(self):
        hide_now_playing_overlay(self)
    else:
        show_now_playing_overlay(self)


def _select_sidebar_nav_row(self, nav_id):
    nav_list = getattr(self, "nav_list", None)
    if nav_list is None:
        return False
    child = nav_list.get_first_child()
    while child:
        if getattr(child, "nav_id", None) == nav_id:
            try:
                nav_list.select_row(child)
            except Exception:
                return False
            remember = getattr(self, "_remember_last_nav", None)
            if callable(remember):
                remember(nav_id)
            return True
        child = child.get_next_sibling()
    return False


def on_now_playing_open_album_clicked(self, _btn=None):
    track = getattr(self, "playing_track", None)
    album = getattr(track, "album", None) if track is not None else None
    if album is None:
        return
    _select_sidebar_nav_row(self, "collection")
    hide_now_playing_overlay(self)
    self.show_album_details(album)


def on_now_playing_track_selected(self, _box, row):
    if row is None:
        return
    tracks = list(getattr(self, "now_playing_album_tracks", []) or [])
    idx = getattr(row, "now_playing_track_index", row.get_index())
    if idx < 0 or idx >= len(tracks):
        return
    self.current_track_list = tracks
    self._set_play_queue(tracks)
    self.play_track(idx)


def _refresh_now_playing_from_track(self):
    track = getattr(self, "playing_track", None)
    if track is None:
        self._now_playing_render_track_key = ""
        if self.now_playing_title_label is not None:
            self.now_playing_title_label.set_text("Nothing playing")
        if self.now_playing_artist_label is not None:
            self.now_playing_artist_label.set_text("")
        if self.now_playing_album_label is not None:
            self.now_playing_album_label.set_text("")
        if self.now_playing_open_album_btn is not None:
            self.now_playing_open_album_btn.set_sensitive(False)
        self._render_now_playing_queue([])
        self._render_now_playing_album_tracks([])
        self._render_now_playing_lyrics(None, "Lyrics will appear for the current track.")
        return

    title = str(getattr(track, "name", "") or "Unknown Track")
    artist = str(getattr(getattr(track, "artist", None), "name", "") or "Unknown Artist")
    album = str(getattr(getattr(track, "album", None), "name", "") or "Unknown Album")
    release_date = getattr(getattr(track, "album", None), "release_date", None)
    album_meta = album
    if getattr(release_date, "year", None):
        album_meta = f"{album}  •  {release_date.year}"
    self._now_playing_render_track_key = _now_playing_track_key(track)

    if self.now_playing_title_label is not None:
        self.now_playing_title_label.set_text(title)
        self.now_playing_title_label.set_tooltip_text(title)
    if self.now_playing_artist_label is not None:
        self.now_playing_artist_label.set_text(artist)
        self.now_playing_artist_label.set_tooltip_text(artist)
    if self.now_playing_album_label is not None:
        self.now_playing_album_label.set_text(album_meta)
        self.now_playing_album_label.set_tooltip_text(album_meta)
    if self.now_playing_open_album_btn is not None:
        self.now_playing_open_album_btn.set_sensitive(getattr(track, "album", None) is not None)

    self._render_now_playing_queue(self._get_active_queue())

    cover_ref = self.backend.get_artwork_url(track, 1280)
    if not cover_ref:
        cover_ref = getattr(track, "cover", None) or getattr(getattr(track, "album", None), "cover", None)
        cover_ref = self._get_tidal_image_url(cover_ref, width=1280, height=1280) if cover_ref else None
    _load_now_playing_cover(self, cover_ref)

    current_album = getattr(track, "album", None)
    album_id = str(getattr(current_album, "id", "") or "")
    if album_id and album_id == str(getattr(self, "now_playing_album_id", "") or "") and self.now_playing_album_tracks:
        self._render_now_playing_album_tracks(self.now_playing_album_tracks)
    else:
        self._load_now_playing_album_tracks_async(current_album)

    lyrics_obj = getattr(self, "lyrics_mgr", None)
    if lyrics_obj is not None and (bool(getattr(lyrics_obj, "raw_text", "")) or bool(getattr(lyrics_obj, "time_points", []))):
        self._render_now_playing_lyrics(lyrics_obj, None)
    else:
        self._render_now_playing_lyrics(None, "Loading Lyrics...")

    try:
        pos_s, dur_s = self.player.get_position()
        playing_now = bool(self.player.is_playing())
    except Exception:
        pos_s, dur_s, playing_now = 0.0, float(getattr(track, "duration", 0) or 0.0), False
    self._sync_now_playing_overlay_state(pos_s, dur_s, playing_now)


def _load_now_playing_album_tracks_async(self, album):
    track = getattr(self, "playing_track", None)
    album_id = str(getattr(album, "id", "") or "")

    if self.now_playing_album_count_label is not None:
        self.now_playing_album_count_label.set_text("Loading...")

    if album is None:
        tracks = [track] if track is not None else []
        self.now_playing_album_id = ""
        self.now_playing_album_tracks = list(tracks)
        self._render_now_playing_album_tracks(tracks)
        return

    if getattr(self, "current_album", None) is not None:
        current_album_id = str(getattr(getattr(self, "current_album", None), "id", "") or "")
        if current_album_id and current_album_id == album_id and list(getattr(self, "album_track_source", []) or []):
            tracks = list(getattr(self, "album_track_source", []) or [])
            self.now_playing_album_id = album_id
            self.now_playing_album_tracks = tracks
            self._render_now_playing_album_tracks(tracks)
            return

    self._now_playing_album_request_id = int(getattr(self, "_now_playing_album_request_id", 0) or 0) + 1
    request_id = self._now_playing_album_request_id

    def task():
        result_tracks = []
        try:
            result_tracks = list(self.backend.get_tracks(album) or [])
        except Exception as exc:
            logger.debug("Now playing album track load failed: %s", exc)
        if not result_tracks and track is not None:
            result_tracks = [track]

        def apply():
            if request_id != int(getattr(self, "_now_playing_album_request_id", 0) or 0):
                return False
            live_track = getattr(self, "playing_track", None)
            live_album_id = str(getattr(getattr(live_track, "album", None), "id", "") or "")
            if album_id and live_album_id and album_id != live_album_id:
                return False
            self.now_playing_album_id = album_id
            self.now_playing_album_tracks = list(result_tracks or [])
            self._render_now_playing_album_tracks(self.now_playing_album_tracks)
            return False

        GLib.idle_add(apply)

    submit_daemon(task)


def _npq_make_expand_row(label_text, on_click):
    """Create a non-selectable ListBoxRow containing an expand button."""
    ph = Gtk.ListBoxRow()
    ph.set_selectable(False)
    ph.set_activatable(False)
    btn = Gtk.Button(
        label=label_text,
        css_classes=["flat", "dim-label"],
        halign=Gtk.Align.START,
        margin_start=4, margin_top=2, margin_bottom=2,
    )
    btn.connect("clicked", lambda _b: on_click())
    ph.set_child(btn)
    return ph


def _npq_expand_above(self):
    """Incrementally prepend rows above the current window, preserving scroll."""
    state = getattr(self, "_npq_state", None)
    if state is None or self.now_playing_queue_list is None:
        return
    tracks    = state["tracks"]
    win_start = state["win_start"]
    win_end   = state["win_end"]
    _NPQ_EXPAND_STEP = 50
    if win_start <= 0:
        return
    new_start = max(0, win_start - _NPQ_EXPAND_STEP)
    # Remove the current "above" placeholder (first row)
    first = self.now_playing_queue_list.get_row_at_index(0)
    if first is not None:
        self.now_playing_queue_list.remove(first)
    # Insert new track rows at positions 0..N-1 (forward order preserves scroll)
    for offset, i in enumerate(range(new_start, win_start)):
        track = tracks[i]
        row = _build_now_playing_track_row(track, i)
        row.queue_track_index = i
        self.now_playing_queue_list.insert(row, offset)
    # Insert new "above" placeholder at position 0 if more tracks are still hidden
    if new_start > 0:
        ph = _npq_make_expand_row(
            f"… {new_start} track{'s' if new_start != 1 else ''} above — show more",
            lambda: _npq_expand_above(self),
        )
        self.now_playing_queue_list.insert(ph, 0)
    state["win_start"] = new_start
    if hasattr(self, "_update_track_list_icon"):
        self._update_track_list_icon(target_list=self.now_playing_queue_list)


def _npq_expand_below(self):
    """Incrementally append rows below the current window, preserving scroll."""
    state = getattr(self, "_npq_state", None)
    if state is None or self.now_playing_queue_list is None:
        return
    tracks    = state["tracks"]
    win_start = state["win_start"]
    win_end   = state["win_end"]
    total     = len(tracks)
    _NPQ_EXPAND_STEP = 50
    if win_end >= total:
        return
    new_end = min(total, win_end + _NPQ_EXPAND_STEP)
    # Remove the last row (the "more" placeholder)
    last = None
    idx = 0
    while True:
        r = self.now_playing_queue_list.get_row_at_index(idx)
        if r is None:
            break
        last = r
        idx += 1
    if last is not None:
        self.now_playing_queue_list.remove(last)
    # Append new track rows
    for i in range(win_end, new_end):
        track = tracks[i]
        row = _build_now_playing_track_row(track, i)
        row.queue_track_index = i
        self.now_playing_queue_list.append(row)
    # Append new "more" placeholder if tracks still hidden below
    tail = total - new_end
    if tail > 0:
        ph = _npq_make_expand_row(
            f"… {tail} more track{'s' if tail != 1 else ''} — show more",
            lambda: _npq_expand_below(self),
        )
        self.now_playing_queue_list.append(ph)
    state["win_end"] = new_end
    if hasattr(self, "_update_track_list_icon"):
        self._update_track_list_icon(target_list=self.now_playing_queue_list)


def _render_now_playing_queue_windowed(self, queue_tracks, win_start, win_end):
    """Re-render the queue list with an explicit window (called by expand buttons)."""
    if self.now_playing_queue_list is None:
        return
    self.now_playing_queue_list.remove_all()
    _render_now_playing_queue_body(self, queue_tracks, win_start=win_start, win_end=win_end)


def _render_now_playing_queue(self, tracks):
    if self.now_playing_queue_list is None:
        return

    self.now_playing_queue_list.remove_all()

    queue_tracks = list(tracks or [])
    if self.now_playing_queue_count_label is not None:
        count = len(queue_tracks)
        self.now_playing_queue_count_label.set_text(f"{count} track" if count == 1 else f"{count} tracks")

    _render_now_playing_queue_body(self, queue_tracks)


def _render_now_playing_queue_body(self, queue_tracks, win_start=None, win_end=None):
    if not queue_tracks:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        row.set_child(
            Gtk.Label(
                label="Queue is empty. Play an album, playlist, or track to build a queue.",
                xalign=0,
                wrap=True,
                css_classes=["dim-label"],
                margin_top=16,
                margin_bottom=16,
                margin_start=12,
                margin_end=12,
            )
        )
        self.now_playing_queue_list.append(row)
        return

    _NPQ_EXPAND_STEP = 50

    total = len(queue_tracks)
    current_idx = int(getattr(self, "current_track_index", -1) or -1)
    anchor = max(0, min(current_idx, total - 1)) if total > 0 else 0

    # Retrieve (or initialise) the current window bounds, reset when the
    # queue changes (different total or different anchor track).
    prev_anchor = getattr(self, "_npq_anchor", -1)
    prev_total  = getattr(self, "_npq_total",  -1)
    if win_start is None or total != prev_total or anchor != prev_anchor:
        win_start = max(0, anchor - 50)
        win_end   = min(total, anchor + 151)
        self._npq_anchor = anchor
        self._npq_total  = total

    win_start = max(0, min(win_start, total))
    win_end   = max(win_start, min(win_end, total))

    self._npq_state = {
        "tracks": queue_tracks,
        "win_start": win_start,
        "win_end": win_end,
    }

    if win_start > 0:
        ph = _npq_make_expand_row(
            f"… {win_start} track{'s' if win_start != 1 else ''} above — show more",
            lambda: _npq_expand_above(self),
        )
        self.now_playing_queue_list.append(ph)

    for idx in range(win_start, win_end):
        track = queue_tracks[idx]
        row = _build_now_playing_track_row(track, idx)
        row.queue_track_index = idx
        self.now_playing_queue_list.append(row)

    tail = total - win_end
    if tail > 0:
        ph = _npq_make_expand_row(
            f"… {tail} more track{'s' if tail != 1 else ''} — show more",
            lambda: _npq_expand_below(self),
        )
        self.now_playing_queue_list.append(ph)

    if hasattr(self, "_update_track_list_icon"):
        self._update_track_list_icon(target_list=self.now_playing_queue_list)
    # Do NOT call _update_list_ui here — it calls select_row() which makes GTK
    # scroll to keep the selected row visible, causing unwanted scroll-to-current
    # on every expand click. The "playing-row" CSS from _update_track_list_icon
    # is sufficient for visual highlighting.


def _render_now_playing_album_tracks(self, tracks):
    if self.now_playing_track_list is None:
        return

    self.now_playing_track_list.remove_all()

    track_items = list(tracks or [])
    self.now_playing_album_tracks = track_items
    if self.now_playing_album_count_label is not None:
        count = len(track_items)
        self.now_playing_album_count_label.set_text(f"{count} track" if count == 1 else f"{count} tracks")

    if not track_items:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        row.set_child(
            Gtk.Label(
                label="Album tracks will appear here once a track is playing.",
                xalign=0,
                wrap=True,
                css_classes=["dim-label"],
                margin_top=16,
                margin_bottom=16,
                margin_start=12,
                margin_end=12,
            )
        )
        self.now_playing_track_list.append(row)
        return

    for idx, track in enumerate(track_items):
        row = _build_now_playing_track_row(track, idx)
        row.now_playing_track_index = idx
        self.now_playing_track_list.append(row)

    if hasattr(self, "_update_track_list_icon"):
        self._update_track_list_icon(target_list=self.now_playing_track_list)
    if hasattr(self, "_update_list_ui"):
        self._update_list_ui(int(getattr(self, "current_track_index", -1) or -1))


def _render_now_playing_lyrics(self, lyrics_obj=None, status_msg=None):
    if self.now_playing_lyrics_vbox is None:
        return

    while child := self.now_playing_lyrics_vbox.get_first_child():
        self.now_playing_lyrics_vbox.remove(child)
    self.now_playing_lyric_widgets = []
    self.current_now_playing_lyric_index = -1
    self.now_playing_target_scroll_y = 0.0

    if status_msg:
        if status_msg == NO_LYRICS_BOTTOM_HINT:
            spacer = Gtk.Box(vexpand=True)
            self.now_playing_lyrics_vbox.append(spacer)
            bottom = Gtk.Label(label=status_msg, css_classes=["dim-label"], halign=Gtk.Align.CENTER)
            bottom.set_margin_bottom(20)
            self.now_playing_lyrics_vbox.append(bottom)
            return

        lbl = Gtk.Label(label=status_msg, css_classes=["title-4"], valign=Gtk.Align.CENTER)
        lbl.set_opacity(0.65)
        lbl.set_wrap(True)
        lbl.set_justify(Gtk.Justification.CENTER)
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, vexpand=True)
        center.append(lbl)
        self.now_playing_lyrics_vbox.append(center)
        return

    if not lyrics_obj:
        lbl = Gtk.Label(
            label="Lyrics will appear for the current track.",
            xalign=0.5,
            valign=Gtk.Align.CENTER,
            wrap=True,
            css_classes=["dim-label"],
        )
        lbl.set_margin_top(40)
        self.now_playing_lyrics_vbox.append(lbl)
        return

    source = lyrics_obj.time_points if lyrics_obj.has_synced else [0]
    for time_point in source:
        text = lyrics_obj.lyrics_map.get(time_point, "") if lyrics_obj.has_synced else lyrics_obj.raw_text
        if not text:
            text = " "

        karaoke_words = []
        if lyrics_obj.has_synced and hasattr(lyrics_obj, "karaoke_map"):
            karaoke_words = list(lyrics_obj.karaoke_map.get(time_point, []))

        if karaoke_words:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["lyric-row"])
            row.set_halign(Gtk.Align.CENTER)
            main_lbl = Gtk.Label(css_classes=["lyric-line"], wrap=True, max_width_chars=36)
            main_lbl.set_justify(Gtk.Justification.CENTER)
            main_lbl.set_use_markup(True)
            main_lbl.set_markup(_karaoke_markup(karaoke_words, -1))
            row.append(main_lbl)
            self.now_playing_lyrics_vbox.append(row)
            if lyrics_obj.has_synced:
                self.now_playing_lyric_widgets.append(
                    {
                        "time": time_point,
                        "widget": row,
                        "main": main_lbl,
                        "sub": None,
                        "is_active": False,
                        "karaoke_words": karaoke_words,
                        "karaoke_last_idx": -2,
                    }
                )
            continue

        primary, secondary = _split_bilingual_line(text)
        if not primary:
            primary = " "

        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["lyric-row"])
        row.set_halign(Gtk.Align.CENTER)

        main_lbl = Gtk.Label(label=primary, css_classes=["lyric-line"], wrap=True, max_width_chars=36)
        main_lbl.set_justify(Gtk.Justification.CENTER)
        row.append(main_lbl)

        sub_lbl = None
        if secondary:
            sub_lbl = Gtk.Label(label=secondary, css_classes=["lyric-sub-line"], wrap=True, max_width_chars=38)
            sub_lbl.set_justify(Gtk.Justification.CENTER)
            row.append(sub_lbl)

        self.now_playing_lyrics_vbox.append(row)
        if lyrics_obj.has_synced:
            self.now_playing_lyric_widgets.append(
                {
                    "time": time_point,
                    "widget": row,
                    "main": main_lbl,
                    "sub": sub_lbl,
                    "is_active": False,
                    "karaoke_words": [],
                    "karaoke_last_idx": -2,
                }
            )

    if hasattr(self, "_apply_lyrics_font_layout"):
        try:
            self._apply_lyrics_font_layout()
        except Exception as e:
            logger.debug("Now playing lyrics font layout apply failed: %s", e)

    try:
        pos_s, _dur_s = self.player.get_position()
    except Exception:
        pos_s = 0.0
    self._sync_now_playing_lyrics(pos_s)


def _scroll_now_playing_to_lyric(self, widget):
    if self.now_playing_lyrics_scroller is None or widget is None:
        return

    try:
        success, rect = widget.compute_bounds(self.now_playing_lyrics_vbox)
        if not success:
            return
        label_center_y = rect.origin.y + (rect.size.height / 2)
        viewport_h = self.now_playing_lyrics_scroller.get_height()
        anchor_ratio = 0.34
        target = label_center_y - (viewport_h * anchor_ratio)
        adj = self.now_playing_lyrics_scroller.get_vadjustment()
        max_scroll = adj.get_upper() - adj.get_page_size()
        self.now_playing_target_scroll_y = max(0, min(target, max_scroll))
    except Exception:
        pass


def _set_now_playing_lyric_active(item, active, current_time=None):
    if item is None:
        return
    active = bool(active)
    was_active = bool(item.get("is_active", False))
    widget = item.get("widget")
    main = item.get("main")
    sub = item.get("sub")
    karaoke_words = item.get("karaoke_words") or []

    if active != was_active:
        if widget is not None:
            if active:
                widget.add_css_class("active")
            else:
                widget.remove_css_class("active")
        if main is not None:
            if active:
                main.add_css_class("active")
            else:
                main.remove_css_class("active")
        if sub is not None:
            if active:
                sub.add_css_class("active")
            else:
                sub.remove_css_class("active")
        item["is_active"] = active

    if not karaoke_words or main is None:
        return

    if active:
        karaoke_idx = _karaoke_active_idx(karaoke_words, float(current_time or 0.0))
        if karaoke_idx != item.get("karaoke_last_idx", -2):
            main.set_markup(_karaoke_markup(karaoke_words, karaoke_idx))
            item["karaoke_last_idx"] = karaoke_idx
    else:
        if item.get("karaoke_last_idx", -2) != -1:
            main.set_markup(_karaoke_markup(karaoke_words, -1))
            item["karaoke_last_idx"] = -1


def _sync_now_playing_lyrics(self, current_position_s):
    if not is_now_playing_overlay_open(self):
        return
    stack = getattr(self, "now_playing_stack", None)
    if stack is None:
        return
    try:
        if stack.get_visible_child_name() != "lyrics":
            return
    except Exception:
        return
    lyrics_mgr = getattr(self, "lyrics_mgr", None)
    widgets = list(getattr(self, "now_playing_lyric_widgets", []) or [])
    if lyrics_mgr is None or not lyrics_mgr.has_synced or not widgets:
        return

    offset_ms = int(getattr(self, "lyrics_user_offset_ms", 0) or 0)
    current_time = float(current_position_s or 0.0) + _LYRICS_LOOKAHEAD_S + (offset_ms / 1000.0)
    active_idx = -1
    for idx, item in enumerate(widgets):
        if item["time"] <= current_time:
            active_idx = idx
        else:
            break

    current_idx = int(getattr(self, "current_now_playing_lyric_index", -1) or -1)
    if active_idx == current_idx:
        # Active line unchanged — only refresh karaoke word highlight within
        # the current line; still clear any stale duplicate active markers left
        # on other rows before skipping the full O(N) state rewrite.
        if 0 <= active_idx < len(widgets):
            _set_now_playing_lyric_active(widgets[active_idx], True, current_time)
        for idx, item in enumerate(widgets):
            if idx != active_idx and bool(item.get("is_active", False)):
                _set_now_playing_lyric_active(item, False, current_time)
    else:
        for idx, item in enumerate(widgets):
            _set_now_playing_lyric_active(item, idx == active_idx, current_time)

    if active_idx != current_idx and 0 <= active_idx < len(widgets):
        self._scroll_now_playing_to_lyric(widgets[active_idx].get("widget"))

    self.current_now_playing_lyric_index = active_idx

    if self.now_playing_lyrics_scroller is not None:
        adj = self.now_playing_lyrics_scroller.get_vadjustment()
        current_y = adj.get_value()
        target_y = float(getattr(self, "now_playing_target_scroll_y", 0.0) or 0.0)
        if abs(target_y - current_y) > 0.5:
            adj.set_value(current_y + ((target_y - current_y) * 0.10))


def _sync_now_playing_overlay_state(self, position_s, duration_s, playing_now):
    if not is_now_playing_overlay_open(self):
        return

    if self.now_playing_progress is not None:
        total = float(duration_s or 0.0)
        if total <= 0.0:
            total = float(getattr(getattr(self, "playing_track", None), "duration", 0) or 0.0)
        pos = max(0.0, float(position_s or 0.0))
        frac = 0.0 if total <= 0.0 else max(0.0, min(1.0, pos / total))
        last_frac = float(getattr(self, "_now_playing_last_progress_fraction", -1.0) or -1.0)
        if abs(last_frac - frac) >= 0.001 or frac in (0.0, 1.0):
            self.now_playing_progress.set_fraction(frac)
            self._now_playing_last_progress_fraction = frac
        if self.now_playing_elapsed_label is not None:
            elapsed_text = _format_time(pos)
            if elapsed_text != str(getattr(self, "_now_playing_last_elapsed_text", "") or ""):
                self.now_playing_elapsed_label.set_text(elapsed_text)
                self._now_playing_last_elapsed_text = elapsed_text
        if self.now_playing_total_label is not None:
            total_text = _format_time(total)
            if total_text != str(getattr(self, "_now_playing_last_total_text", "") or ""):
                self.now_playing_total_label.set_text(total_text)
                self._now_playing_last_total_text = total_text

    if self.now_playing_play_btn is not None:
        playing_state = bool(playing_now)
        if playing_state != getattr(self, "_now_playing_last_playing_state", None):
            self.now_playing_play_btn.set_icon_name(
                "media-playback-pause-symbolic" if playing_state else "media-playback-start-symbolic"
            )
            self._now_playing_last_playing_state = playing_state

    self._sync_now_playing_lyrics(position_s)
