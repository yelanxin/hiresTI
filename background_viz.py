import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
import cairo
import math
import random #
import os
import hashlib
from threading import Thread
import requests
from gi.repository import GdkPixbuf
import logging

logger = logging.getLogger(__name__)

class BackgroundVisualizer(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_draw_func(self._draw_callback, None)
        
        self.current_energy = 0.0
        self.target_energy = 0.0
        self.phase = 0.0
        self.base_bg_rgb = (0.04, 0.04, 0.06)
        self._last_cover_key = None
        self.motion_mode = "Soft"
        self.motion_profiles = {
            "Static": {"energy_gain": 0.0, "phase_speed": 0.0, "smoothing": 0.10},
            "Soft": {"energy_gain": 0.72, "phase_speed": 0.016, "smoothing": 0.18},
            "Dynamic": {"energy_gain": 1.15, "phase_speed": 0.034, "smoothing": 0.36},
        }
        
        # [新增] 初始随机颜色
        self.randomize_colors()
        
        GLib.timeout_add(16, self._tick)

    def get_motion_mode_names(self):
        return list(self.motion_profiles.keys())

    def set_motion_mode(self, mode_name):
        if mode_name in self.motion_profiles:
            self.motion_mode = mode_name
            if mode_name == "Static":
                self.target_energy = 0.0
                self.current_energy = 0.0
            self.queue_draw()

    def set_theme_mode(self, is_dark):
        self.base_bg_rgb = (0.04, 0.04, 0.06) if is_dark else (0.90, 0.91, 0.93)
        self.queue_draw()

    def randomize_colors(self):
        """
        [新增] 随机生成两组美观的 RGB 颜色
        使用 uniform(0.1, 0.8) 确保颜色不会太黑或全白
        """
        self.color_a = (random.uniform(0.1, 0.9), random.uniform(0.1, 0.9), random.uniform(0.1, 0.9))
        self.color_b = (random.uniform(0.1, 0.9), random.uniform(0.1, 0.9), random.uniform(0.1, 0.9))
        logger.debug("Background random colors: A=%s, B=%s", self.color_a, self.color_b)

    def _dominant_rgb_from_pixbuf(self, pb):
        if pb is None:
            return None
        pixels = pb.get_pixels()
        rowstride = pb.get_rowstride()
        n_channels = pb.get_n_channels()
        width = pb.get_width()
        height = pb.get_height()
        if width <= 0 or height <= 0:
            return None
        step = 2
        rs = gs = bs = 0.0
        count = 0
        for y in range(0, height, step):
            base = y * rowstride
            for x in range(0, width, step):
                idx = base + (x * n_channels)
                rs += pixels[idx]
                gs += pixels[idx + 1]
                bs += pixels[idx + 2]
                count += 1
        if count <= 0:
            return None
        return (rs / count / 255.0, gs / count / 255.0, bs / count / 255.0)

    def set_colors_from_cover(self, cover_url, cache_dir):
        if not cover_url or not cache_dir:
            self.randomize_colors()
            return

        cover_key = hashlib.md5(cover_url.encode()).hexdigest()
        if self._last_cover_key == cover_key:
            return
        self._last_cover_key = cover_key

        def task():
            try:
                os.makedirs(cache_dir, exist_ok=True)
                f_path = os.path.join(cache_dir, cover_key)
                if not os.path.exists(f_path):
                    r = requests.get(cover_url, timeout=8)
                    r.raise_for_status()
                    with open(f_path, "wb") as f:
                        f.write(r.content)

                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(f_path, 48, 48, True)
                rgb = self._dominant_rgb_from_pixbuf(pb)
                if rgb is None:
                    GLib.idle_add(self.randomize_colors)
                    return

                def apply_colors():
                    r, g, b = rgb
                    # Keep tone similar to the old simple visualizer.
                    self.color_a = (min(1.0, r + 0.06), min(1.0, g + 0.06), min(1.0, b + 0.06))
                    self.color_b = (max(0.0, r - 0.06), min(1.0, g + 0.03), max(0.0, b - 0.03))
                    self.queue_draw()
                    return False

                GLib.idle_add(apply_colors)
            except Exception as e:
                logger.debug("Failed to derive background colors from cover: %s", e)
                GLib.idle_add(self.randomize_colors)

        Thread(target=task, daemon=True).start()

    def update_energy(self, magnitudes):
        profile = self.motion_profiles.get(self.motion_mode, self.motion_profiles["Soft"])
        if profile["energy_gain"] <= 0.0:
            self.target_energy = 0.0
            return
        if not magnitudes or len(magnitudes) < 12:
            self.target_energy = 0
            return
        bass_sum = sum(magnitudes[:6]) / 6.0
        energy = (bass_sum + 60) / 30.0
        raw_energy = max(0.0, min(1.0, energy))
        self.target_energy = math.pow(raw_energy, 1.2) * profile["energy_gain"]
        self.target_energy = max(0.0, min(1.0, self.target_energy))

    def _tick(self):
        profile = self.motion_profiles.get(self.motion_mode, self.motion_profiles["Soft"])
        diff = self.target_energy - self.current_energy
        if abs(diff) > 0.001:
            self.current_energy += diff * profile["smoothing"]
        self.phase += profile["phase_speed"]
        self.queue_draw()
        return True

    def _draw_callback(self, area, cr, width, height, data=None):
        cr.set_source_rgb(*self.base_bg_rgb)
        cr.paint()
        if self.current_energy < 0.005: return

        off_x = math.sin(self.phase) * 50
        off_y = math.cos(self.phase * 0.7) * 40
        cx, cy = width/2 + off_x, height/2 + off_y

        # 使用随机色 A
        base_radius = (min(width, height) * 0.6) + (width * 0.8 * self.current_energy)
        base_alpha = 0.12 + (0.35 * self.current_energy)
        grad_base = cairo.RadialGradient(cx, cy, 0, cx, cy, base_radius)
        grad_base.add_color_stop_rgba(0, *self.color_a, base_alpha)
        grad_base.add_color_stop_rgba(0.7, *self.color_a, base_alpha * 0.3)
        grad_base.add_color_stop_rgba(1.0, *self.color_a, 0)
        cr.set_source(grad_base)
        cr.paint()

        # 使用随机色 B
        core_radius = (min(width, height) * 0.3) + (width * 0.5 * self.current_energy)
        core_alpha = 0.10 + (0.40 * self.current_energy)
        grad_core = cairo.RadialGradient(cx - off_x*2, cy - off_y*2, 0, cx - off_x*2, cy - off_y*2, core_radius)
        grad_core.add_color_stop_rgba(0, *self.color_b, core_alpha)
        grad_core.add_color_stop_rgba(0.5, *self.color_b, core_alpha * 0.2)
        grad_core.add_color_stop_rgba(1.0, *self.color_b, 0)
        cr.set_source(grad_core)
        cr.paint()
