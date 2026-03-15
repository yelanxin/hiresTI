from __future__ import annotations

import os
import requests
import hashlib
import logging
import time
import tempfile
import cairo
from pathlib import Path
from threading import Thread, Lock
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Callable, Any
from gi.repository import GLib, GdkPixbuf, Gdk

from core.http_session import get_global_session

logger = logging.getLogger(__name__)

# Bounded thread pool for image loading — prevents thread explosion on large pages.
_IMG_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="img-load")
_CACHE_LOCK_GUARD = Lock()
_CACHE_FILE_LOCKS: dict[str, Lock] = {}

# Unified cover/artwork display size (px) — change here to resize all non-track/non-artist covers.
# This value is updated at startup by set_ui_scale() based on the display scale factor.
COVER_SIZE = 170


def set_ui_scale(scale_factor: int) -> None:
    """Adjust UI element sizes for the display's scale factor.

    At HiDPI (scale ≥ 2) GTK doubles all logical pixels automatically, so the
    base sizes are correct.  At 1x the same logical sizes render physically
    smaller; we compensate by scaling up.

    Call once from app startup before any UI is built.
    """
    global COVER_SIZE
    # Target: match the physical appearance of a 2x HiDPI display.
    # Cap at 1.4× to avoid overflowing the default window width.
    ui_scale = max(1.0, min(1.4, 2.0 / max(1, scale_factor)))
    COVER_SIZE = int(170 * ui_scale)
    logger.debug("Display scale=%d → ui_scale=%.2f, COVER_SIZE=%d", scale_factor, ui_scale, COVER_SIZE)

_TIDAL_IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://listen.tidal.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def _cache_file_lock(path: str) -> Lock:
    key = str(path or "")
    with _CACHE_LOCK_GUARD:
        lock = _CACHE_FILE_LOCKS.get(key)
        if lock is None:
            lock = Lock()
            _CACHE_FILE_LOCKS[key] = lock
        return lock


def _has_cached_file(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def _download_bytes(url: str, headers: dict | None = None, timeout: int = 10) -> bytes:
    sess = get_global_session()
    req_headers = dict(headers or {})
    if "resources.tidal.com/" in url:
        req_headers = {**_TIDAL_IMAGE_HEADERS, **req_headers}
    r = sess.get(url, timeout=timeout, headers=req_headers)
    r.raise_for_status()
    data = bytes(r.content or b"")
    if not data:
        raise ValueError(f"downloaded empty payload for {url}")
    return data


def _write_atomic_bytes(path: str, data: bytes) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _cover_crop_rect(
    src_w: int,
    src_h: int,
    target_w: int,
    target_h: int,
    *,
    anchor_x: float = 0.5,
    anchor_y: float = 0.5,
) -> tuple[int, int, int, int]:
    src_w = max(1, int(src_w or 0))
    src_h = max(1, int(src_h or 0))
    target_w = max(1, int(target_w or 0))
    target_h = max(1, int(target_h or 0))
    ax = max(0.0, min(1.0, float(anchor_x)))
    ay = max(0.0, min(1.0, float(anchor_y)))

    src_ratio = float(src_w) / float(src_h)
    target_ratio = float(target_w) / float(target_h)

    if src_ratio > target_ratio:
        crop_w = max(1, min(src_w, int(round(src_h * target_ratio))))
        crop_h = src_h
        max_x = max(0, src_w - crop_w)
        x = int(round(max_x * ax))
        y = 0
    else:
        crop_w = src_w
        crop_h = max(1, min(src_h, int(round(src_w / target_ratio))))
        max_y = max(0, src_h - crop_h)
        x = 0
        y = int(round(max_y * ay))

    x = max(0, min(x, max(0, src_w - crop_w)))
    y = max(0, min(y, max(0, src_h - crop_h)))
    return x, y, crop_w, crop_h


def download_to_cache(url: str, cache_dir: str, filename: str = None, headers: dict = None, timeout: int = 10) -> str | None:
    """
    Download a file to cache directory.

    Args:
        url: URL to download
        cache_dir: Directory to save the file
        filename: Optional filename, otherwise derived from URL hash
        headers: Optional HTTP headers
        timeout: Request timeout in seconds

    Returns:
        Path to downloaded file, or None on failure
    """
    if not url or not cache_dir:
        return None

    os.makedirs(cache_dir, exist_ok=True)

    if not filename:
        filename = hashlib.md5(url.encode()).hexdigest()
    f_path = os.path.join(cache_dir, filename)

    if _has_cached_file(f_path):
        return f_path

    with _cache_file_lock(f_path):
        if _has_cached_file(f_path):
            return f_path
        try:
            if os.path.exists(f_path):
                os.remove(f_path)
        except OSError:
            pass

        try:
            data = _download_bytes(url, headers=headers, timeout=timeout)
            _write_atomic_bytes(f_path, data)
            return f_path
        except (requests.RequestException, ValueError, OSError) as e:
            logger.debug("download_to_cache failed (url=%s): %s", url, e)
            return None


def prune_image_cache(cache_dir: str, max_bytes: int = 300 * 1024 * 1024, max_age_days: int = 30) -> None:
    """
    Prune cover cache by age and total size.
    - Remove files older than max_age_days.
    - If cache still exceeds max_bytes, remove oldest files first.
    """
    try:
        if not os.path.isdir(cache_dir):
            return

        now = int(time.time())
        ttl_seconds = max_age_days * 24 * 60 * 60
        entries = []
        total_size = 0

        for entry in os.scandir(cache_dir):
            if not entry.is_file():
                continue
            try:
                st = entry.stat()
            except FileNotFoundError:
                continue
            age = now - int(st.st_mtime)
            if age > ttl_seconds:
                try:
                    os.remove(entry.path)
                except OSError as e:
                    logger.debug("Failed to remove expired cache file %s: %s", entry.path, e)
                continue
            total_size += st.st_size
            entries.append((entry.path, st.st_mtime, st.st_size))

        if total_size <= max_bytes:
            return

        # Oldest files first.
        entries.sort(key=lambda x: x[1])
        for path, _, size in entries:
            if total_size <= max_bytes:
                break
            try:
                os.remove(path)
                total_size -= size
            except OSError as e:
                logger.debug("Failed to trim cache file %s: %s", path, e)
    except Exception as e:
        logger.warning("Cache pruning failed: %s", e)


def _rounded_pixbuf(pb, radius):
    try:
        w = pb.get_width()
        h = pb.get_height()
        if w <= 0 or h <= 0:
            return pb

        r = max(0.0, min(float(radius), min(w, h) / 2.0))
        if r <= 0:
            return pb

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)

        # Rounded rectangle clip path.
        cr.new_path()
        cr.arc(w - r, r, r, -1.5708, 0.0)
        cr.arc(w - r, h - r, r, 0.0, 1.5708)
        cr.arc(r, h - r, r, 1.5708, 3.1416)
        cr.arc(r, r, r, 3.1416, 4.7124)
        cr.close_path()
        cr.clip()

        Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
        cr.paint()
        return Gdk.pixbuf_get_from_surface(surface, 0, 0, w, h)
    except Exception as e:
        logger.warning("Rounded pixbuf generation failed: %s", e)
        return pb


def _get_rounded_radius(classes: set, size: int) -> int:
    """根据 CSS 类返回圆角半径"""
    if "circular-avatar" in classes:
        return size // 2
    if "playback-art" in classes:
        return 12
    if "header-art" in classes:
        return 14
    if "album-cover-img" in classes:
        return 10
    return 0


def load_img(widget: Any, url_provider: Callable[[], str] | str, cache_dir: str, size: int = 84) -> None:
    widget.set_size_request(size, size)

    def fetch():
        try:
            u = url_provider() if callable(url_provider) else url_provider
            if not u:
                return

            widget._target_url = u
            f_path = u if (isinstance(u, str) and os.path.exists(u)) else None
            if f_path is None:
                f_name = hashlib.md5(str(u).encode()).hexdigest()
                f_path = download_to_cache(str(u), cache_dir, filename=f_name, timeout=10)
                if not f_path:
                    logger.warning("load_img: download failed (url=%s): cache path unavailable", u)
                    return
            elif not _has_cached_file(f_path):
                logger.warning("load_img: cache file is empty or unreadable (path=%s)", f_path)
                return

            w_type = type(widget).__name__
            classes = set(widget.get_css_classes()) if hasattr(widget, "get_css_classes") else set()
            radius = _get_rounded_radius(classes, size)

            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(f_path)
                if not pb:
                    return

                scaled = pb.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
                if scaled and radius > 0:
                    scaled = _rounded_pixbuf(scaled, radius)

                if w_type == 'Picture':
                    texture = Gdk.Texture.new_for_pixbuf(scaled or pb)
                    def apply_pic():
                        if hasattr(widget, '_target_url') and widget._target_url == u:
                            widget.set_size_request(size, size)
                            widget._loaded_pixbuf = scaled or pb
                            widget.set_paintable(texture)
                    GLib.idle_add(apply_pic)
                else:
                    def apply_img():
                        if hasattr(widget, '_target_url') and widget._target_url == u:
                            widget.set_pixel_size(size)
                            widget._loaded_pixbuf = scaled or pb
                            widget.set_from_pixbuf(scaled)
                    GLib.idle_add(apply_img)
            except Exception as e:
                logger.warning("load_img: failed to apply image from %s: %s", f_path, e)

        except Exception as e:
            logger.warning("load_img: unexpected error: %s", e)

    _IMG_EXECUTOR.submit(fetch)


def load_picture_cover_crop(
    picture: Any,
    url_provider: Callable[[], str] | str,
    cache_dir: str,
    *,
    target_width: int,
    target_height: int,
    anchor_x: float = 0.5,
    anchor_y: float = 0.5,
) -> None:
    if hasattr(picture, "set_paintable"):
        picture.set_paintable(None)

    def fetch():
        try:
            u = url_provider() if callable(url_provider) else url_provider
            if not u:
                return

            picture._target_url = u
            f_path = u if (isinstance(u, str) and _has_cached_file(u)) else None
            if f_path is None:
                f_name = hashlib.md5(str(u).encode()).hexdigest()
                f_path = download_to_cache(str(u), cache_dir, filename=f_name, timeout=10)
                if not f_path:
                    return

            pb = GdkPixbuf.Pixbuf.new_from_file(f_path)
            if not pb:
                return

            crop_x, crop_y, crop_w, crop_h = _cover_crop_rect(
                pb.get_width(),
                pb.get_height(),
                target_width,
                target_height,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
            )
            cropped = pb.new_subpixbuf(crop_x, crop_y, crop_w, crop_h)
            scaled = cropped.scale_simple(
                max(1, int(target_width)),
                max(1, int(target_height)),
                GdkPixbuf.InterpType.BILINEAR,
            )
            texture = Gdk.Texture.new_for_pixbuf(scaled or cropped)

            def apply():
                if getattr(picture, "_target_url", None) != u:
                    return False
                try:
                    picture.set_size_request(int(target_width), int(target_height))
                except Exception:
                    pass
                picture.set_paintable(texture)
                picture._loaded_pixbuf = scaled or cropped
                return False

            GLib.idle_add(apply)
        except Exception as e:
            logger.warning("load_picture_cover_crop: failed (target=%sx%s): %s", target_width, target_height, e)

    _IMG_EXECUTOR.submit(fetch)

def set_pointer_cursor(widget, enable):
    try:
        cursor_name = "pointer" if enable else "default"
        cursor = Gdk.Cursor.new_from_name(cursor_name, None)
        widget.set_cursor(cursor)
    except Exception as e:
        logger.debug("Failed to set cursor: %s", e)


def set_resize_cursor(widget, enable):
    try:
        cursor_name = "ew-resize" if enable else "default"
        cursor = Gdk.Cursor.new_from_name(cursor_name, None)
        widget.set_cursor(cursor)
    except Exception as e:
        logger.debug("Failed to set resize cursor: %s", e)


def _ensure_image_local_path(image_ref, cache_dir):
    """Ensure image is available locally, downloading if needed."""
    if not image_ref:
        return None
    if isinstance(image_ref, str) and os.path.exists(image_ref):
        return image_ref
    if not (isinstance(image_ref, str) and image_ref.startswith("http")):
        return None
    return download_to_cache(image_ref, cache_dir)


def _paint_cover_fill(cr, pb, x, y, w, h):
    try:
        src_w = pb.get_width()
        src_h = pb.get_height()
        if src_w <= 0 or src_h <= 0:
            return
        scale = max(float(w) / float(src_w), float(h) / float(src_h))
        scaled_w = max(1, int(src_w * scale))
        scaled_h = max(1, int(src_h * scale))
        scaled = pb.scale_simple(scaled_w, scaled_h, GdkPixbuf.InterpType.BILINEAR)
        if scaled is None:
            return
        off_x = x - int((scaled_w - w) / 2)
        off_y = y - int((scaled_h - h) / 2)
        Gdk.cairo_set_source_pixbuf(cr, scaled, off_x, off_y)
        cr.rectangle(x, y, w, h)
        cr.fill()
    except Exception as e:
        logger.debug("Failed to paint collage cell: %s", e)


def generate_auto_collage_cover(
    image_refs: list,
    image_cache_dir: str,
    collage_cache_dir: str,
    key_prefix: str = "playlist",
    size: int = 512,
    overlay_alpha: float = 0.0,
    overlay_style: str = "flat",
):
    """
    Generate a cached playlist cover:
    - 1 cover: full
    - 2 covers: left/right split
    - 3 covers: top split + bottom full
    - 4+ covers: 2x2 grid
    Returns local collage image path or None.
    """
    if not image_refs:
        return None

    unique_refs = []
    seen = set()
    for ref in image_refs:
        if not ref:
            continue
        s = str(ref)
        if s in seen:
            continue
        seen.add(s)
        unique_refs.append(s)
        if len(unique_refs) >= 4:
            break

    if not unique_refs:
        return None

    if len(unique_refs) == 1:
        return _ensure_image_local_path(unique_refs[0], image_cache_dir)

    os.makedirs(collage_cache_dir, exist_ok=True)
    digest = hashlib.md5(
        ("|".join(unique_refs) + f"|{size}|{overlay_alpha:.3f}|{overlay_style}").encode()
    ).hexdigest()
    out_path = os.path.join(collage_cache_dir, f"{key_prefix}_{digest}.png")
    if os.path.exists(out_path):
        return out_path

    paths = []
    for ref in unique_refs:
        p = _ensure_image_local_path(ref, image_cache_dir)
        if p:
            paths.append(p)

    if not paths:
        return None

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    cr.set_source_rgba(0.18, 0.18, 0.18, 1.0)
    cr.paint()

    n = min(len(paths), 4)
    slots = []
    if n == 1:
        slots = [(0, 0, size, size)]
    elif n == 2:
        half = size // 2
        slots = [
            (0, 0, half, size),
            (half, 0, size - half, size),
        ]
    elif n == 3:
        half_h = size // 2
        half_w = size // 2
        slots = [
            (0, 0, half_w, half_h),
            (half_w, 0, size - half_w, half_h),
            (0, half_h, size, size - half_h),
        ]
    else:
        gap = max(2, size // 64)
        cell = (size - gap) // 2
        slots = [
            (0, 0, cell, cell),
            (cell + gap, 0, cell, cell),
            (0, cell + gap, cell, cell),
            (cell + gap, cell + gap, cell, cell),
        ]

    for idx, path in enumerate(paths[:n]):
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file(path)
            if pb is None:
                continue
            x, y, w, h = slots[idx]
            _paint_cover_fill(cr, pb, x, y, w, h)
        except Exception as e:
            logger.debug("Failed to load collage source %s: %s", path, e)

    try:
        alpha = float(overlay_alpha or 0.0)
    except Exception:
        alpha = 0.0
    if alpha > 0:
        alpha = max(0.0, min(0.65, alpha))
        style = str(overlay_style or "flat").lower()
        if style == "mix":
            # Official-mix-like warm gold treatment:
            # base tint + vertical gold/amber gradient + center glow + edge darkening.
            cr.set_source_rgba(0.86, 0.67, 0.20, alpha * 0.52)
            cr.rectangle(0, 0, size, size)
            cr.fill()

            grad = cairo.LinearGradient(0, 0, 0, size)
            grad.add_color_stop_rgba(0.0, 0.99, 0.83, 0.34, alpha * 0.44)
            grad.add_color_stop_rgba(0.38, 0.93, 0.72, 0.23, alpha * 0.58)
            grad.add_color_stop_rgba(0.72, 0.79, 0.53, 0.15, alpha * 0.74)
            grad.add_color_stop_rgba(1.0, 0.52, 0.30, 0.10, alpha * 0.98)
            cr.set_source(grad)
            cr.rectangle(0, 0, size, size)
            cr.fill()

            glow = cairo.RadialGradient(size * 0.5, size * 0.36, size * 0.06, size * 0.5, size * 0.36, size * 0.62)
            glow.add_color_stop_rgba(0.0, 1.0, 0.92, 0.62, alpha * 0.36)
            glow.add_color_stop_rgba(1.0, 1.0, 0.92, 0.62, 0.0)
            cr.set_source(glow)
            cr.rectangle(0, 0, size, size)
            cr.fill()

            vignette = cairo.RadialGradient(size / 2.0, size / 2.0, size * 0.20, size / 2.0, size / 2.0, size * 0.76)
            vignette.add_color_stop_rgba(0.0, 0.0, 0.0, 0.0, 0.0)
            vignette.add_color_stop_rgba(1.0, 0.26, 0.15, 0.04, alpha * 0.44)
            cr.set_source(vignette)
            cr.rectangle(0, 0, size, size)
            cr.fill()
        else:
            cr.set_source_rgba(0.0, 0.0, 0.0, alpha)
            cr.rectangle(0, 0, size, size)
            cr.fill()

    try:
        surface.write_to_png(out_path)
        return out_path
    except Exception as e:
        logger.debug("Failed to write collage cover: %s", e)
        return None


def _audio_cache_file(cache_dir, track_id, quality_key):
    if not cache_dir or track_id is None:
        return None
    safe_q = str(quality_key or "default").replace("/", "_").replace("\\", "_")
    return os.path.join(cache_dir, f"{track_id}_{safe_q}.bin")


def get_cached_audio_uri(cache_dir, track_id, quality_key):
    path = _audio_cache_file(cache_dir, track_id, quality_key)
    if not path or not os.path.exists(path):
        return None
    try:
        os.utime(path, None)
    except OSError:
        pass
    try:
        return Path(path).resolve().as_uri()
    except Exception:
        return None


def cache_audio_from_url(cache_dir, track_id, quality_key, stream_url, timeout=20):
    if not cache_dir or track_id is None or not stream_url:
        return None
    os.makedirs(cache_dir, exist_ok=True)
    target = _audio_cache_file(cache_dir, track_id, quality_key)
    if not target:
        return None
    if os.path.exists(target):
        try:
            os.utime(target, None)
        except OSError:
            pass
        return target

    tmp = f"{target}.tmp"
    try:
        sess = get_global_session()
        with sess.get(stream_url, timeout=timeout, stream=True) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
        os.replace(tmp, target)
        return target
    except Exception as e:
        logger.debug("Audio cache download failed for %s: %s", track_id, e)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return None


def prune_audio_cache(cache_dir, max_tracks=20):
    try:
        if not cache_dir or not os.path.isdir(cache_dir):
            return
        files = []
        for entry in os.scandir(cache_dir):
            if not entry.is_file():
                continue
            if not entry.name.endswith(".bin"):
                continue
            try:
                st = entry.stat()
            except FileNotFoundError:
                continue
            files.append((entry.path, st.st_mtime))
        if max_tracks <= 0:
            for path, _ in files:
                try:
                    os.remove(path)
                except OSError:
                    pass
            return
        if len(files) <= max_tracks:
            return
        files.sort(key=lambda x: x[1], reverse=True)
        for path, _ in files[max_tracks:]:
            try:
                os.remove(path)
            except OSError:
                pass
    except Exception as e:
        logger.debug("Audio cache prune failed: %s", e)
