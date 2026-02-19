import os
import requests
import hashlib
import logging
import time
import cairo
from pathlib import Path
from threading import Thread
from gi.repository import GLib, GdkPixbuf, Gdk

logger = logging.getLogger(__name__)
_TIDAL_IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://listen.tidal.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def prune_image_cache(cache_dir, max_bytes=300 * 1024 * 1024, max_age_days=30):
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
        logger.debug("Rounded pixbuf generation failed: %s", e)
        return pb


def load_img(widget, url_provider, cache_dir, size=84):
    """
    [混合修复版]
    - Gtk.Picture: 使用 Texture，自适应 (适合大图)。
    - Gtk.Image: 使用 set_pixel_size 强力锁死尺寸 (适合图标/封面)。
    """
    # 预设尺寸请求 (作为保底)
    widget.set_size_request(size, size)
    
    # 清空内容
    if hasattr(widget, 'set_paintable'): widget.set_paintable(None)
    elif hasattr(widget, 'set_from_pixbuf'): widget.set_from_pixbuf(None)
    
    def fetch():
        try:
            u = url_provider() if callable(url_provider) else url_provider
            if not u:
                logger.info("load_img: empty image source (widget=%s, size=%s)", type(widget).__name__, size)
                return
            logger.info("load_img: start (widget=%s, size=%s, source=%s)", type(widget).__name__, size, u)
            
            widget._target_url = u
            f_path = None
            if isinstance(u, str) and os.path.exists(u):
                # Local file path (e.g. generated playlist collage cover)
                f_path = u
            else:
                f_name = hashlib.md5(str(u).encode()).hexdigest()
                f_path = os.path.join(cache_dir, f_name)
            
            # 下载
            if not os.path.exists(f_path):
                try:
                    req_kwargs = {"timeout": 10}
                    if isinstance(u, str) and "resources.tidal.com/" in u:
                        req_kwargs["headers"] = _TIDAL_IMAGE_HEADERS
                    r = requests.get(u, **req_kwargs)
                    r.raise_for_status()
                    with open(f_path, 'wb') as f:
                        f.write(r.content)
                except requests.RequestException as e:
                    logger.warning("load_img: download failed (url=%s): %s", u, e)
                    return

            # 判断控件类型
            w_type = type(widget).__name__
            classes = set(widget.get_css_classes()) if hasattr(widget, "get_css_classes") else set()
            is_avatar = "circular-avatar" in classes
            is_album_cover = "album-cover-img" in classes
            is_playback_art = "playback-art" in classes
            is_header_art = "header-art" in classes
            
            # --- 情况 A: Gtk.Picture (用于详情页大图) ---
            if w_type == 'Picture':
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file(f_path)
                    scaled_pb = pb.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR) if pb else None
                    render_pb = scaled_pb or pb
                    if render_pb:
                        if is_avatar:
                            render_pb = _rounded_pixbuf(render_pb, size // 2)
                        elif is_playback_art:
                            render_pb = _rounded_pixbuf(render_pb, 12)
                        elif is_header_art:
                            render_pb = _rounded_pixbuf(render_pb, 14)
                        elif is_album_cover:
                            render_pb = _rounded_pixbuf(render_pb, 10)
                    texture = Gdk.Texture.new_for_pixbuf(render_pb)
                    def apply_pic():
                        if hasattr(widget, '_target_url') and widget._target_url == u:
                            widget.set_size_request(size, size)
                            widget.set_paintable(texture)
                            logger.info("load_img: applied picture (source=%s)", u)
                    GLib.idle_add(apply_pic)
                except Exception as e:
                    logger.warning("load_img: failed to apply picture texture from %s: %s", f_path, e)

            # --- 情况 B: Gtk.Image (用于播放栏/列表) ---
            else:
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file(f_path)
                    if pb:
                        # 直接按目标尺寸缩放，避免大图先闪一下再回落。
                        scaled = pb.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
                        if scaled:
                            if is_avatar:
                                scaled = _rounded_pixbuf(scaled, size // 2)
                            elif is_playback_art:
                                scaled = _rounded_pixbuf(scaled, 12)
                            elif is_header_art:
                                scaled = _rounded_pixbuf(scaled, 14)
                            elif is_album_cover:
                                scaled = _rounded_pixbuf(scaled, 10)
                        
                        def apply_img():
                            if hasattr(widget, '_target_url') and widget._target_url == u:
                                # 强制锁定逻辑显示尺寸
                                widget.set_pixel_size(size) 
                                widget.set_from_pixbuf(scaled)
                                logger.info("load_img: applied image (source=%s)", u)
                        GLib.idle_add(apply_img)
                except Exception as e:
                    logger.warning("load_img: failed to apply image pixbuf from %s: %s", f_path, e)

        except Exception as e:
            logger.warning("load_img: unexpected error: %s", e)
            
    Thread(target=fetch, daemon=True).start()

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
    if not image_ref:
        return None
    if isinstance(image_ref, str) and os.path.exists(image_ref):
        return image_ref
    if not (isinstance(image_ref, str) and image_ref.startswith("http")):
        return None

    os.makedirs(cache_dir, exist_ok=True)
    f_name = hashlib.md5(image_ref.encode()).hexdigest()
    f_path = os.path.join(cache_dir, f_name)
    if os.path.exists(f_path):
        return f_path

    try:
        req_kwargs = {"timeout": 10}
        if isinstance(image_ref, str) and "resources.tidal.com/" in image_ref:
            req_kwargs["headers"] = _TIDAL_IMAGE_HEADERS
        r = requests.get(image_ref, **req_kwargs)
        r.raise_for_status()
        with open(f_path, "wb") as f:
            f.write(r.content)
        return f_path
    except requests.RequestException as e:
        logger.debug("Failed to fetch collage source image: %s", e)
        return None


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
    image_refs,
    image_cache_dir,
    collage_cache_dir,
    key_prefix="playlist",
    size=512,
    overlay_alpha=0.0,
    overlay_style="flat",
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
        with requests.get(stream_url, timeout=timeout, stream=True) as r:
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
