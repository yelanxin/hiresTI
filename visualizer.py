import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
import cairo
import math
import logging
from rust_viz import RustVizCore

logger = logging.getLogger(__name__)

class SpectrumVisualizer(Gtk.DrawingArea):
    """
    HiresTI 高灵敏度频谱可视化组件 (已修复 NameError)
    """
    def __init__(self):
        super().__init__()
        self.set_draw_func(self._draw_callback, None)
        self.set_size_request(-1, 0) # 允许 Revealer 完全折叠
        self.theme_name = "Aurora (Default)"
        self.effect_name = "Dots"
        self.effects = [
            "Bars",
            "Wave",
            "Fill",
            "Mirror",
            "Dots",
            "Neon",
            "Peak",
            "Trail",
            "Pulse",
            "Stereo",
            "Burst",
            "Stars",
            "Ribbon",
            "Spiral",
            "Pro Bars",
            "Pro Line",
            "Pro Fall",
        ]
        self.profile_name = "Dynamic"
        self.profiles = {
            "Soft": {
                "gain_mul": 0.84,
                "spacing_mul": 1.08,
                "grid_mul": 0.85,
                "smooth": 0.30,
                "trail_decay": 0.93,
                "peak_hold_frames": 12,
                "peak_fall": 0.014,
                "beat_mul": 0.78,
            },
            "Dynamic": {
                "gain_mul": 1.0,
                "spacing_mul": 1.0,
                "grid_mul": 1.0,
                "smooth": 0.45,
                "trail_decay": 0.90,
                "peak_hold_frames": 8,
                "peak_fall": 0.02,
                "beat_mul": 1.0,
            },
            "Extreme": {
                "gain_mul": 1.18,
                "spacing_mul": 0.92,
                "grid_mul": 1.18,
                "smooth": 0.56,
                "trail_decay": 0.87,
                "peak_hold_frames": 6,
                "peak_fall": 0.03,
                "beat_mul": 1.24,
            },
            "Insane": {
                "gain_mul": 1.32,
                "spacing_mul": 0.88,
                "grid_mul": 1.28,
                "smooth": 0.62,
                "trail_decay": 0.84,
                "peak_hold_frames": 4,
                "peak_fall": 0.04,
                "beat_mul": 1.42,
            },
        }
        self.themes = {
            # Keep existing look as the default theme.
            "Aurora (Default)": {
                "grid_alpha": 0.02,
                "bar_spacing": 1.5,
                "height_gain": 1.6,
                "gradient": (
                    (0.0, (0.0, 1.0, 1.0, 1.0)),   # cyan
                    (0.5, (0.0, 0.5, 1.0, 0.9)),   # blue-purple
                    (1.0, (0.2, 0.0, 0.5, 0.6)),   # deep purple
                ),
            },
            "Amber Pulse": {
                "grid_alpha": 0.028,
                "bar_spacing": 1.6,
                "height_gain": 1.55,
                "gradient": (
                    (0.0, (1.0, 0.87, 0.25, 0.95)),  # warm gold
                    (0.55, (1.0, 0.55, 0.1, 0.88)),  # amber
                    (1.0, (0.65, 0.2, 0.05, 0.62)),  # copper
                ),
            },
            "Emerald Flow": {
                "grid_alpha": 0.022,
                "bar_spacing": 1.4,
                "height_gain": 1.62,
                "gradient": (
                    (0.0, (0.52, 1.0, 0.82, 0.98)),  # mint
                    (0.52, (0.1, 0.82, 0.64, 0.9)),  # teal-green
                    (1.0, (0.02, 0.43, 0.36, 0.62)), # deep green
                ),
            },
            "Crimson Drive": {
                "grid_alpha": 0.024,
                "bar_spacing": 1.5,
                "height_gain": 1.58,
                "gradient": (
                    (0.0, (1.0, 0.48, 0.56, 0.98)),  # rose
                    (0.5, (0.9, 0.16, 0.33, 0.9)),   # crimson
                    (1.0, (0.42, 0.06, 0.16, 0.65)), # wine
                ),
            },
            "Ice Beam": {
                "grid_alpha": 0.02,
                "bar_spacing": 1.45,
                "height_gain": 1.64,
                "gradient": (
                    (0.0, (0.82, 0.96, 1.0, 1.0)),   # ice white
                    (0.52, (0.48, 0.78, 1.0, 0.9)),  # sky blue
                    (1.0, (0.12, 0.28, 0.58, 0.62)), # deep blue
                ),
            },
            "Mono Steel": {
                "grid_alpha": 0.03,
                "bar_spacing": 1.55,
                "height_gain": 1.52,
                "gradient": (
                    (0.0, (0.92, 0.92, 0.92, 0.96)), # light gray
                    (0.55, (0.62, 0.65, 0.7, 0.88)), # steel
                    (1.0, (0.22, 0.24, 0.28, 0.66)), # graphite
                ),
            },
            "Neon Rush": {
                "grid_alpha": 0.026,
                "bar_spacing": 1.35,
                "height_gain": 1.78,
                "gradient": (
                    (0.0, (0.25, 1.0, 0.92, 0.98)),   # neon mint
                    (0.45, (0.0, 0.78, 1.0, 0.95)),   # electric cyan
                    (0.78, (0.54, 0.28, 1.0, 0.92)),  # vivid violet
                    (1.0, (1.0, 0.18, 0.62, 0.82)),   # hot pink
                ),
            },
            "Inferno Boost": {
                "grid_alpha": 0.03,
                "bar_spacing": 1.25,
                "height_gain": 1.85,
                "gradient": (
                    (0.0, (1.0, 0.95, 0.48, 1.0)),    # bright yellow
                    (0.38, (1.0, 0.62, 0.12, 0.96)),  # blaze orange
                    (0.72, (1.0, 0.20, 0.08, 0.92)),  # hot red
                    (1.0, (0.45, 0.02, 0.06, 0.78)),  # deep ember
                ),
            },
            "Blue Violet Blaze": {
                "grid_alpha": 0.028,
                "bar_spacing": 1.3,
                "height_gain": 1.82,
                "gradient": (
                    (0.0, (0.74, 0.90, 1.0, 1.0)),    # icy blue
                    (0.34, (0.36, 0.68, 1.0, 0.96)),  # azure flame
                    (0.68, (0.42, 0.24, 1.0, 0.94)),  # violet core
                    (1.0, (0.16, 0.05, 0.42, 0.82)),  # deep indigo
                ),
            },
            "Plasma Storm": {
                "grid_alpha": 0.027,
                "bar_spacing": 1.28,
                "height_gain": 1.8,
                "gradient": (
                    (0.0, (0.86, 0.97, 1.0, 1.0)),    # plasma white-blue
                    (0.32, (0.30, 0.78, 1.0, 0.96)),  # electric blue
                    (0.64, (0.58, 0.30, 1.0, 0.94)),  # bright violet
                    (1.0, (0.92, 0.16, 0.62, 0.84)),  # magenta flare
                ),
            },
            "Pure Cyan": {
                "grid_alpha": 0.025,
                "bar_spacing": 1.35,
                "height_gain": 1.72,
                "gradient": (
                    (0.0, (0.10, 0.95, 1.0, 0.98)),
                    (1.0, (0.10, 0.95, 1.0, 0.78)),
                ),
            },
            "Pure Red": {
                "grid_alpha": 0.025,
                "bar_spacing": 1.35,
                "height_gain": 1.72,
                "gradient": (
                    (0.0, (1.0, 0.18, 0.18, 0.98)),
                    (1.0, (1.0, 0.18, 0.18, 0.78)),
                ),
            },
            "Pure White": {
                "grid_alpha": 0.03,
                "bar_spacing": 1.35,
                "height_gain": 1.7,
                "gradient": (
                    (0.0, (1.0, 1.0, 1.0, 0.98)),
                    (1.0, (1.0, 1.0, 1.0, 0.80)),
                ),
            },
            "Soft Dark Gold": {
                "grid_alpha": 0.028,
                "bar_spacing": 1.36,
                "height_gain": 1.74,
                "gradient": (
                    (0.0, (0.92, 0.78, 0.36, 0.96)),
                    (1.0, (0.92, 0.78, 0.36, 0.76)),
                ),
            },
            "Silver Sheen": {
                "grid_alpha": 0.03,
                "bar_spacing": 1.34,
                "height_gain": 1.72,
                "gradient": (
                    (0.0, (0.90, 0.93, 0.98, 0.98)),
                    (1.0, (0.90, 0.93, 0.98, 0.78)),
                ),
            },
            "Dark Gold Shadow": {
                "grid_alpha": 0.028,
                "bar_spacing": 1.34,
                "height_gain": 1.76,
                "gradient": (
                    (0.0, (0.93, 0.80, 0.38, 0.98)),   # bright dark-gold top
                    (0.55, (0.62, 0.46, 0.18, 0.90)),  # mid bronze
                    (1.0, (0.08, 0.06, 0.03, 0.82)),   # near-black bottom
                ),
            },
            "Infrared": {
                "grid_alpha": 0.03,
                "bar_spacing": 1.3,
                "height_gain": 1.8,
                "gradient": (
                    (0.00, (0.98, 0.98, 0.72, 1.00)),  # hot yellow
                    (0.35, (1.00, 0.48, 0.08, 0.95)),  # orange
                    (0.72, (0.82, 0.12, 0.06, 0.92)),  # deep red
                    (1.00, (0.16, 0.02, 0.02, 0.86)),  # dark ember
                ),
            },
            "Stars BWR": {
                "grid_alpha": 0.0,
                "bar_spacing": 1.35,
                "height_gain": 1.7,
                "gradient": (
                    (0.00, (0.12, 0.42, 1.00, 0.95)),  # blue
                    (0.52, (1.00, 1.00, 1.00, 0.98)),  # white
                    (1.00, (1.00, 0.18, 0.18, 0.95)),  # red
                ),
            },
        }
        
        self.num_bars = 128
        self.target_heights = [0.0] * self.num_bars
        self.current_heights = [0.0] * self.num_bars
        self.trail_heights = [0.0] * self.num_bars
        self.peak_holds = [0.0] * self.num_bars
        self.peak_ttl = [0] * self.num_bars
        self.heat_history = []
        self.pro_heat_history = []
        self.star_seeds = self._gen_star_seeds(260)
        self._bass_target = 0.0
        self.bass_level = 0.0
        self.phase = 0.0
        self._rust_core = RustVizCore()
        self._logged_rust_path = False
        self._logged_python_fallback = False
        self._logged_rust_bins = False
        self._logged_python_bins = False
        self._logged_rust_spiral = False
        self._logged_python_spiral = False
        self._logged_rust_neon = False
        self._logged_python_neon = False
        self._logged_rust_neon_rings = False
        self._logged_python_neon_rings = False
        self._logged_rust_line = False
        self._logged_python_line = False
        self._logged_rust_fall = False
        self._logged_python_fall = False
        self._logged_rust_pro_fall = False
        self._logged_python_pro_fall = False
        self._logged_rust_pro_fall_img = False
        self._logged_python_pro_fall_img = False
        self._logged_rust_fall_img = False
        self._logged_python_fall_img = False
        self._logged_rust_dots_img = False
        self._logged_python_dots_img = False
        
        # 启动动画循环 (约 60fps)
        GLib.timeout_add(16, self._on_animation_tick)

    def get_theme_names(self):
        return list(self.themes.keys())

    def get_effect_names(self):
        return list(self.effects)

    def get_profile_names(self):
        return list(self.profiles.keys())

    def set_theme(self, theme_name):
        if theme_name in self.themes:
            self.theme_name = theme_name
            self.queue_draw()

    def set_effect(self, effect_name):
        if effect_name in self.effects:
            self.effect_name = effect_name
            self.queue_draw()

    def set_profile(self, profile_name):
        if profile_name in self.profiles:
            self.profile_name = profile_name
            self.queue_draw()

    def set_num_bars(self, count):
        try:
            n = int(count)
        except Exception:
            return
        if n <= 0 or n == self.num_bars:
            return
        self.num_bars = n
        self.target_heights = [0.0] * n
        self.current_heights = [0.0] * n
        self.trail_heights = [0.0] * n
        self.peak_holds = [0.0] * n
        self.peak_ttl = [0] * n
        self.heat_history = []
        self.pro_heat_history = []
        self.queue_draw()

    def update_data(self, magnitudes):
        if not magnitudes: return
        
        # 1. 强制转列表并反转 (解决高频在左的问题)
        magnitudes = list(magnitudes)
        actual_count = min(len(magnitudes), self.num_bars)
        new_heights = None
        if self._rust_core.available:
            if not self._logged_rust_path:
                logger.info("Spectrum preprocessing path: Rust")
                self._logged_rust_path = True
            new_heights = self._rust_core.process_spectrum(
                magnitudes,
                self.num_bars,
                db_min=-60.0,
                db_range=60.0,
            )
        if new_heights is None:
            if not self._logged_python_fallback:
                logger.info("Spectrum preprocessing path: Python fallback")
                self._logged_python_fallback = True
            new_heights = []
            db_min = -60.0
            db_range = 60.0
            for i in range(actual_count):
                val = magnitudes[i]
                if val <= db_min:
                    h = 0.0
                else:
                    h = (val - db_min) / db_range
                h = math.pow(max(0.0, h), 1)
                new_heights.append(max(0.0, min(1.0, h)))
            while len(new_heights) < self.num_bars:
                new_heights.append(0.0)

        self.target_heights = new_heights
        bass_count = max(1, min(actual_count, self.num_bars // 8))
        self._bass_target = sum(new_heights[:bass_count]) / float(bass_count)

    def _on_animation_tick(self):
        profile = self.profiles.get(self.profile_name, self.profiles["Dynamic"])
        changed = False
        self.phase += 0.045
        bass_response = max(0.12, min(0.62, 0.28 * float(profile["beat_mul"])))
        self.bass_level += (self._bass_target - self.bass_level) * bass_response
        for i in range(self.num_bars):
            diff = self.target_heights[i] - self.current_heights[i]
            if abs(diff) > 0.001:
                self.current_heights[i] += diff * float(profile["smooth"])
                changed = True
            cur = self.current_heights[i]
            self.trail_heights[i] = max(cur, self.trail_heights[i] * float(profile["trail_decay"]))
            if cur >= self.peak_holds[i]:
                self.peak_holds[i] = cur
                self.peak_ttl[i] = int(profile["peak_hold_frames"])
            else:
                if self.peak_ttl[i] > 0:
                    self.peak_ttl[i] -= 1
                else:
                    self.peak_holds[i] = max(0.0, self.peak_holds[i] - float(profile["peak_fall"]))
        # Keep short history for waterfall-style effects.
        self.heat_history.append(list(self.current_heights))
        if len(self.heat_history) > 800:
            self.heat_history = self.heat_history[-800:]
        # Pre-binned history for Pro Analyzer Waterfall (avoids heavy per-draw binning).
        pro_rows = max(4, min(self.num_bars, 64))
        self.pro_heat_history.append(self._build_log_bins(self.current_heights, pro_rows))
        if len(self.pro_heat_history) > 900:
            self.pro_heat_history = self.pro_heat_history[-900:]
        if changed:
            self.queue_draw()
        return True

    def _draw_callback(self, area, cr, width, height, data=None):
        theme = self.themes.get(self.theme_name, self.themes["Aurora (Default)"])
        profile = self.profiles.get(self.profile_name, self.profiles["Dynamic"])
        if width <= 0 or height <= 0:
            return

        grid_alpha = max(0.0, min(1.0, theme["grid_alpha"] * float(profile["grid_mul"])))
        self._draw_grid(cr, width, height, grid_alpha)
        n = self.num_bars
        spacing = max(0.8, theme["bar_spacing"] * float(profile["spacing_mul"]))
        gain = theme["height_gain"] * float(profile["gain_mul"])
        bar_w = max(1.0, (width - (n - 1) * spacing) / n)
        gradient = self._make_gradient(height, theme)

        effect = self.effect_name
        if effect == "Bars":
            self._draw_bars(cr, width, height, gain, gradient, bar_w, spacing)
        elif effect == "Wave":
            self._draw_wave_line(cr, width, height, gain, gradient, filled=False)
        elif effect == "Fill":
            self._draw_wave_line(cr, width, height, gain, gradient, filled=True)
        elif effect == "Mirror":
            self._draw_mirror_bars(cr, width, height, gain, gradient, bar_w, spacing)
        elif effect == "Dots":
            self._draw_dot_matrix(cr, width, height, gain, bar_w, spacing, theme["gradient"])
        elif effect == "Neon":
            self._draw_neon_tunnel(cr, width, height, gain, theme["gradient"])
        elif effect == "Peak":
            self._draw_bars(cr, width, height, gain, gradient, bar_w, spacing)
            self._draw_peak_caps(cr, width, height, gain, bar_w, spacing)
        elif effect == "Trail":
            self._draw_trail_glow(cr, width, height, gain, bar_w, spacing)
            self._draw_bars(cr, width, height, gain, gradient, bar_w, spacing)
        elif effect == "Pulse":
            self._draw_beat_pulse_bg(cr, width, height, theme, float(profile["beat_mul"]))
            self._draw_bars(cr, width, height, gain, gradient, bar_w, spacing)
        elif effect == "Stereo":
            self._draw_split_stereo(cr, width, height, gain, theme["gradient"])
        elif effect == "Burst":
            self._draw_particle_burst(cr, width, height, gain, theme["gradient"])
        elif effect == "Stars":
            self._draw_starscape(cr, width, height, gain, theme["gradient"])
        elif effect == "Ribbon":
            self._draw_ribbon(cr, width, height, gain, theme["gradient"])
        elif effect == "Spiral":
            self._draw_spiral(cr, width, height, gain, theme["gradient"])
        elif effect == "Pro Bars":
            self._draw_pro_analyzer(cr, width, height, gain, theme["gradient"])
        elif effect == "Pro Line":
            self._draw_pro_analyzer_line(cr, width, height, gain, theme["gradient"])
        elif effect == "Pro Fall":
            self._draw_pro_analyzer_waterfall(cr, width, height, gain, theme["gradient"])
        else:
            self._draw_bars(cr, width, height, gain, gradient, bar_w, spacing)

    def _draw_grid(self, cr, width, height, alpha):
        cr.set_line_width(1.0)
        cr.set_source_rgba(1.0, 1.0, 1.0, alpha)
        for r in (0.2, 0.4, 0.6, 0.8):
            y = height * r
            cr.move_to(0, y)
            cr.line_to(width, y)
            cr.stroke()

    def _make_gradient(self, height, theme):
        gradient = cairo.LinearGradient(0, 0, 0, height)
        for stop, rgba in theme["gradient"]:
            gradient.add_color_stop_rgba(stop, *rgba)
        return gradient

    def _draw_rounded_top_bar(self, cr, x, y, bar_w, h, base_y):
        radius = min(bar_w * 0.28, h * 0.45)
        if radius < 0.8:
            cr.rectangle(x, y, bar_w, h)
            return
        cr.new_path()
        cr.move_to(x, base_y)
        cr.line_to(x, y + radius)
        cr.arc(x + radius, y + radius, radius, math.pi, 1.5 * math.pi)
        cr.line_to(x + bar_w - radius, y)
        cr.arc(x + bar_w - radius, y + radius, radius, -math.pi / 2, 0)
        cr.line_to(x + bar_w, base_y)
        cr.close_path()

    def _draw_bars(self, cr, width, height, gain, gradient, bar_w, spacing):
        cr.set_source(gradient)
        for i in range(self.num_bars):
            h_ratio = self.current_heights[i]
            if h_ratio < 0.001:
                continue
            h = max(1.0, min(h_ratio * height * gain, height))
            x = i * (bar_w + spacing)
            y = max(0.0, height - h)
            self._draw_rounded_top_bar(cr, x, y, bar_w, h, height)
            cr.fill()

    def _draw_wave_line(self, cr, width, height, gain, gradient, filled=False):
        n = self.num_bars
        if n <= 1:
            return
        step_x = width / float(max(1, n - 1))
        points = []
        for i in range(n):
            h = max(0.0, min(self.current_heights[i] * gain, 1.0))
            y = height - (h * height)
            points.append((i * step_x, y))
        if filled:
            cr.new_path()
            cr.move_to(0, height)
            for x, y in points:
                cr.line_to(x, y)
            cr.line_to(width, height)
            cr.close_path()
            cr.set_source(gradient)
            cr.fill_preserve()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.16)
            cr.set_line_width(1.2)
            cr.stroke()
            return
        cr.new_path()
        x0, y0 = points[0]
        cr.move_to(x0, y0)
        for x, y in points[1:]:
            cr.line_to(x, y)
        cr.set_source(gradient)
        cr.set_line_width(2.2)
        cr.stroke()

    def _draw_mirror_bars(self, cr, width, height, gain, gradient, bar_w, spacing):
        mid = height * 0.5
        cr.set_source(gradient)
        for i in range(self.num_bars):
            h_ratio = self.current_heights[i]
            if h_ratio < 0.001:
                continue
            h = max(1.0, min(h_ratio * height * gain * 0.48, mid))
            x = i * (bar_w + spacing)
            cr.rectangle(x, mid - h, bar_w, h)
            cr.rectangle(x, mid, bar_w, h)
            cr.fill()

    def _draw_dot_matrix(self, cr, width, height, gain, bar_w, spacing, grad):
        n = self.num_bars
        if n <= 0:
            return
        # Keep Dots on classic Cairo path: lower CPU than full-frame image synthesis.
        dot_h = 4.0
        gap = 3.0
        for i in range(self.num_bars):
            h_ratio = self.current_heights[i]
            if h_ratio < 0.001:
                continue
            h = max(1.0, min(h_ratio * height * gain, height))
            x = i * (bar_w + spacing)
            y = height - dot_h
            t = i / float(max(1, self.num_bars - 1))
            r, g, b, a = self._color_from_gradient(grad, t)
            cr.set_source_rgba(r, g, b, a)
            drawn = 0.0
            while drawn < h:
                cr.rectangle(x, y - drawn, bar_w, dot_h)
                cr.fill()
                drawn += dot_h + gap

    def _draw_radial(self, cr, width, height, gain, theme):
        cx, cy = width * 0.5, height * 0.52
        base = min(width, height) * 0.20
        max_len = min(width, height) * 0.34
        grad = theme["gradient"]
        n = self.num_bars
        for i in range(n):
            ratio = self.current_heights[i]
            if ratio < 0.001:
                continue
            angle = ((2.0 * math.pi) * (i / float(n))) - (math.pi / 2.0)
            seg = max(1.0, ratio * max_len * gain * 0.7)
            x1 = cx + math.cos(angle) * base
            y1 = cy + math.sin(angle) * base
            x2 = cx + math.cos(angle) * (base + seg)
            y2 = cy + math.sin(angle) * (base + seg)
            r, g, b, a = self._color_from_gradient(grad, i / float(max(1, n - 1)))
            cr.set_source_rgba(r, g, b, a)
            cr.set_line_width(2.0)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

    def _draw_neon_tunnel(self, cr, width, height, gain, grad):
        n = self.num_bars
        if n <= 0:
            return
        curve_mul = {
            "Soft": 0.70,
            "Dynamic": 1.00,
            "Extreme": 1.38,
        }.get(self.profile_name, 1.00)
        cx = width * 0.5
        cy = height * 0.54
        bass = max(0.0, min(1.0, self.bass_level * 1.25))
        size = min(width, height)
        full_span = math.hypot(width, height)

        # Subtle vignette for the classic neon tunnel contrast.
        bg = cairo.RadialGradient(cx, cy, size * 0.08, cx, cy, full_span * 0.72)
        c0 = self._color_from_gradient(grad, 0.72)
        c1 = self._color_from_gradient(grad, 0.95)
        bg.add_color_stop_rgba(0.0, c0[0] * 0.10, c0[1] * 0.08, c0[2] * 0.14, 0.22)
        bg.add_color_stop_rgba(1.0, c1[0] * 0.02, c1[1] * 0.02, c1[2] * 0.03, 0.0)
        cr.set_source(bg)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Fluid "paint-mix" streams converging towards the tunnel center.
        flow_layers = 8
        outer_r = full_span * 0.60
        inner_r = size * 0.06
        seg_n = 64
        for li in range(flow_layers):
            t = li / float(max(1, flow_layers - 1))
            c = self._color_from_gradient(grad, (0.12 + (0.78 * t)) % 1.0)
            alpha = 0.040 + (0.050 * (1.0 - t)) + (0.020 * bass)
            base_ang = (li * (2.0 * math.pi / flow_layers)) + (self.phase * 0.10)
            lane_w = (0.22 + (0.08 * math.sin((self.phase * 0.35) + li))) * (1.0 - (0.25 * t)) * (0.90 + (0.35 * curve_mul))
            phase1 = (self.phase * (0.62 + (0.06 * li))) + (li * 1.17)
            phase2 = (self.phase * (0.47 + (0.05 * li))) - (li * 0.83)

            cr.new_path()
            for si in range(seg_n + 1):
                s = si / float(seg_n)
                r = outer_r - ((outer_r - inner_r) * (s ** 1.10))
                twist = (
                    (1.55 * (1.0 - s))
                    + (0.42 * math.sin((s * 8.0) + phase1))
                    + (0.18 * math.sin((s * 17.0) + phase2))
                ) * curve_mul
                ang_center = base_ang + twist
                spread = lane_w * (0.32 + (0.68 * (1.0 - s)))
                ang = ang_center - spread
                x = cx + (math.cos(ang) * r)
                y = cy + (math.sin(ang) * r)
                if si == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            for si in range(seg_n, -1, -1):
                s = si / float(seg_n)
                r = outer_r - ((outer_r - inner_r) * (s ** 1.10))
                twist = (
                    (1.55 * (1.0 - s))
                    + (0.42 * math.sin((s * 8.0) + phase1))
                    + (0.18 * math.sin((s * 17.0) + phase2))
                ) * curve_mul
                ang_center = base_ang + twist
                spread = lane_w * (0.32 + (0.68 * (1.0 - s)))
                ang = ang_center + spread
                x = cx + (math.cos(ang) * r)
                y = cy + (math.sin(ang) * r)
                cr.line_to(x, y)
            cr.close_path()
            cr.set_source_rgba(c[0], c[1], c[2], alpha)
            cr.fill()

        # Tunnel rings.
        ring_count = max(6, int(self.num_bars))
        base = size * 0.04
        depth_span = full_span * 0.62
        drift = self.phase * 0.85
        ring_points = None
        if self._rust_core.available:
            ring_points = self._rust_core.build_neon_ring_points(
                ring_count=ring_count,
                width=float(width),
                height=float(height),
                phase=float(self.phase),
                bass=float(bass * curve_mul),
                seg_n=180,
            )
            if ring_points is not None and not self._logged_rust_neon_rings:
                logger.info("Neon ring-generation path: Rust")
                self._logged_rust_neon_rings = True
        if ring_points:
            cr.set_line_join(cairo.LineJoin.ROUND)
            cr.set_line_cap(cairo.LineCap.ROUND)
            open_path = False
            cur_style = None
            for px, py, alpha, lw, color_t, start_flag in ring_points:
                style = (alpha, lw, color_t)
                if start_flag >= 0.5:
                    if open_path:
                        cr.close_path()
                        cr.stroke()
                    col = self._color_from_gradient(grad, color_t)
                    cr.set_source_rgba(col[0], col[1], col[2], min(0.68, alpha))
                    cr.set_line_width(lw)
                    cr.new_path()
                    cr.move_to(px, py)
                    open_path = True
                    cur_style = style
                else:
                    if not open_path:
                        col = self._color_from_gradient(grad, color_t)
                        cr.set_source_rgba(col[0], col[1], col[2], min(0.68, alpha))
                        cr.set_line_width(lw)
                        cr.new_path()
                        cr.move_to(px, py)
                        open_path = True
                        cur_style = style
                    elif style != cur_style:
                        cr.close_path()
                        cr.stroke()
                        col = self._color_from_gradient(grad, color_t)
                        cr.set_source_rgba(col[0], col[1], col[2], min(0.68, alpha))
                        cr.set_line_width(lw)
                        cr.new_path()
                        cr.move_to(px, py)
                        cur_style = style
                    else:
                        cr.line_to(px, py)
            if open_path:
                cr.close_path()
                cr.stroke()
        else:
            if not self._logged_python_neon_rings:
                logger.info("Neon ring-generation path: Python fallback")
                self._logged_python_neon_rings = True
            for ri in range(ring_count):
                z = ((ri / float(ring_count)) + (drift * 0.10)) % 1.0
                radius = base + ((1.0 - z) ** 1.65) * depth_span
                t = 1.0 - z
                col = self._color_from_gradient(grad, 0.05 + (0.90 * t))
                alpha = 0.10 + (0.42 * (t ** 1.8)) + (0.10 * bass * t)
                lw = 0.8 + (2.6 * (t ** 1.4))
                cr.set_source_rgba(col[0], col[1], col[2], min(0.68, alpha))
                cr.set_line_width(lw)
                cr.set_line_join(cairo.LineJoin.ROUND)
                cr.set_line_cap(cairo.LineCap.ROUND)
                seg_n = 180
                warp_amp = (10.0 + (42.0 * t)) * (1.0 + (1.10 * bass)) * curve_mul
                f1 = 2.6 + (2.8 * t)
                f2 = 6.4 + (4.4 * (1.0 - t))
                phase = (self.phase * (1.2 + (0.25 * t))) + (ri * 0.19)
                start_a = (
                    (ri * 2.399963229728653)
                    + (self.phase * 0.17)
                    + (t * 1.1)
                ) % (2.0 * math.pi)
                cr.new_path()
                for si in range(seg_n):
                    a = start_a + ((2.0 * math.pi) * (si / float(seg_n)))
                    wobble_raw = (
                        math.sin((a * f1) + phase) * warp_amp
                        + math.sin((a * f2) - (phase * 1.35)) * (warp_amp * 0.72)
                    )
                    wobble = max(-radius * 0.34, min(radius * 0.34, wobble_raw))
                    rr = max(2.0, radius + wobble)
                    px = cx + (math.cos(a) * rr)
                    py = cy + (math.sin(a) * rr)
                    if si == 0:
                        cr.move_to(px, py)
                    else:
                        cr.line_to(px, py)
                cr.close_path()
                cr.stroke()

        # Beat pulse in tunnel center.
        if bass > 0.03:
            pr = base * (1.2 + (2.8 * bass))
            pulse = cairo.RadialGradient(cx, cy, pr * 0.25, cx, cy, pr)
            hot = self._color_from_gradient(grad, 0.18)
            pulse.add_color_stop_rgba(0.0, hot[0], hot[1], hot[2], 0.42 * bass)
            pulse.add_color_stop_rgba(1.0, hot[0], hot[1], hot[2], 0.0)
            cr.set_source(pulse)
            cr.arc(cx, cy, pr, 0, 2 * math.pi)
            cr.fill()

        # Radial spokes driven by spectrum bins.
        spokes = None
        if self._rust_core.available:
            spokes = self._rust_core.build_neon_spokes(
                bins=self.current_heights,
                width=float(width),
                height=float(height),
                phase=float(self.phase),
                gain=float(gain),
                max_points=max(64, n),
            )
            if spokes is not None and not self._logged_rust_neon:
                logger.info("Neon spoke-generation path: Rust")
                self._logged_rust_neon = True
        if spokes is None:
            if not self._logged_python_neon:
                logger.info("Neon spoke-generation path: Python fallback")
                self._logged_python_neon = True
            max_len = full_span * 0.62
            spokes = []
            for i in range(n):
                lvl = max(0.0, min(self.current_heights[i] * gain, 1.0))
                if lvl < 0.02:
                    continue
                angle = ((2.0 * math.pi) * (i / float(n))) + (self.phase * 0.30)
                ln = (size * 0.06) + (lvl * max_len)
                x2 = cx + math.cos(angle) * ln
                y2 = cy + math.sin(angle) * ln
                tt = i / float(max(1, n - 1))
                spokes.append((cx, cy, x2, y2, lvl, tt))

        for x1, y1, x2, y2, lvl, tt in spokes:
            col = self._color_from_gradient(grad, tt)
            a = min(0.95, 0.20 + (0.78 * lvl))
            cr.set_source_rgba(col[0], col[1], col[2], a)
            cr.set_line_width(1.0 + (1.6 * lvl))
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

    def _draw_peak_caps(self, cr, width, height, gain, bar_w, spacing):
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.75)
        for i in range(self.num_bars):
            peak = self.peak_holds[i]
            if peak < 0.005:
                continue
            h = max(1.0, min(peak * height * gain, height))
            x = i * (bar_w + spacing)
            y = max(0.0, height - h)
            cr.rectangle(x, y, bar_w, 2.0)
            cr.fill()

    def _draw_trail_glow(self, cr, width, height, gain, bar_w, spacing):
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.14)
        for i in range(self.num_bars):
            h_ratio = self.trail_heights[i]
            if h_ratio < 0.001:
                continue
            h = max(1.0, min(h_ratio * height * gain, height))
            x = i * (bar_w + spacing)
            y = max(0.0, height - h)
            cr.rectangle(x, y, bar_w, h)
            cr.fill()

    def _draw_beat_pulse_bg(self, cr, width, height, theme, beat_mul=1.0):
        lvl = max(0.0, min(1.0, self.bass_level * max(0.6, beat_mul)))
        if lvl < 0.02:
            return
        cx, cy = width * 0.5, height * 0.58
        r = min(width, height) * (0.16 + (0.18 * lvl))
        grad = cairo.RadialGradient(cx, cy, r * 0.35, cx, cy, r)
        top = theme["gradient"][0][1]
        grad.add_color_stop_rgba(0.0, top[0], top[1], top[2], 0.24 * lvl)
        grad.add_color_stop_rgba(1.0, top[0], top[1], top[2], 0.0)
        cr.set_source(grad)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()

    def _draw_split_stereo(self, cr, width, height, gain, grad):
        n = self.num_bars
        if n <= 0:
            return
        half_w = width * 0.5
        inner_gap = 10.0
        bars_per_side = max(1, n // 2)
        spacing = 1.2
        left_w = max(1.0, (half_w - inner_gap - (bars_per_side - 1) * spacing) / bars_per_side)
        right_w = left_w
        max_h = height * 0.92
        for i in range(bars_per_side):
            li = i
            ri = min(n - 1, i + bars_per_side)
            lh = max(0.0, min(self.current_heights[li] * gain, 1.0))
            rh = max(0.0, min(self.current_heights[ri] * gain, 1.0))
            if lh > 0.001:
                h = max(1.0, min(lh * max_h, height))
                x = i * (left_w + spacing)
                y = height - h
                r, g, b, a = self._color_from_gradient(grad, i / float(max(1, bars_per_side - 1)))
                cr.set_source_rgba(r, g, b, a)
                self._draw_rounded_top_bar(cr, x, y, left_w, h, height)
                cr.fill()
            if rh > 0.001:
                h = max(1.0, min(rh * max_h, height))
                x = half_w + inner_gap + i * (right_w + spacing)
                y = height - h
                r, g, b, a = self._color_from_gradient(grad, i / float(max(1, bars_per_side - 1)))
                cr.set_source_rgba(r, g, b, a)
                self._draw_rounded_top_bar(cr, x, y, right_w, h, height)
                cr.fill()

    def _draw_particle_burst(self, cr, width, height, gain, grad):
        n = self.num_bars
        if n <= 0:
            return
        cx = width * 0.5
        cy = height * 0.80
        bass = max(0.0, min(1.0, self.bass_level * 1.35))

        # Shockwave ring on stronger bass hits.
        if bass > 0.08:
            pulse_r = (height * 0.10) + (height * 0.26 * bass)
            ring = cairo.RadialGradient(cx, cy, pulse_r * 0.55, cx, cy, pulse_r)
            hot = self._color_from_gradient(grad, 0.15)
            ring.add_color_stop_rgba(0.0, hot[0], hot[1], hot[2], 0.30 * bass)
            ring.add_color_stop_rgba(1.0, hot[0], hot[1], hot[2], 0.0)
            cr.set_source(ring)
            cr.arc(cx, cy, pulse_r, 0, 2 * math.pi)
            cr.fill()

        for i in range(n):
            lvl = max(0.0, min(self.current_heights[i] * gain, 1.0))
            if lvl < 0.02:
                continue
            base_angle = ((2.0 * math.pi) * (i / float(n))) + (self.phase * 0.52)
            base_dist = (height * 0.08) + (lvl * height * 0.54)
            r, g, b, a = self._color_from_gradient(grad, i / float(max(1, n - 1)))

            # Spawn multiple sparks per bar to make burst richer.
            sparks = 1 + int(lvl * 4.0) + (1 if bass > 0.45 else 0)
            for s in range(sparks):
                jitter_a = (s - (sparks * 0.5)) * (0.055 + (0.03 * lvl))
                angle = base_angle + jitter_a
                dist = base_dist * (0.86 + (0.18 * s))
                px = cx + math.cos(angle) * dist
                py = cy + math.sin(angle) * dist * 0.72
                rad = 0.95 + (lvl * 2.6) - (s * 0.10)
                rad = max(0.65, rad)

                # Core spark.
                cr.set_source_rgba(r, g, b, min(1.0, 0.34 + (a * 0.72)))
                cr.arc(px, py, rad, 0, 2 * math.pi)
                cr.fill()

                # Hot center highlight.
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.18 + (0.28 * lvl))
                cr.arc(px, py, rad * 0.42, 0, 2 * math.pi)
                cr.fill()

                # Soft plume.
                cr.set_source_rgba(r, g, b, 0.10 + (a * 0.20))
                cr.arc(px, py, rad * 2.4, 0, 2 * math.pi)
                cr.fill()

    def _gen_star_seeds(self, count):
        seeds = []
        for i in range(max(0, count)):
            # Deterministic pseudo-random sequence (stable, no runtime random dependency).
            a = math.sin((i + 1) * 12.9898) * 43758.5453
            b = math.sin((i + 1) * 78.233) * 24634.6345
            c = math.sin((i + 1) * 39.425) * 12414.1337
            d = math.sin((i + 1) * 17.719) * 53124.6179
            nx = abs(a - math.floor(a))
            ny = abs(b - math.floor(b))
            sz = 0.6 + (abs(c - math.floor(c)) * 1.8)
            ph = abs(d - math.floor(d))
            band = i % max(1, self.num_bars)
            depth = 0.2 + (0.8 * ((i % 17) / 16.0))
            seeds.append((nx, ny, sz, ph, band, depth))
        return seeds

    def _draw_starscape(self, cr, width, height, gain, grad):
        n = self.num_bars
        if n <= 0:
            return
        bass = max(0.0, min(1.0, self.bass_level * 1.45))
        is_bwr = (self.theme_name == "Stars BWR")

        # Space background.
        if is_bwr:
            cr.set_source_rgba(0.0, 0.0, 0.0, 1.0)  # pure black
        else:
            top = self._color_from_gradient(grad, 0.85)
            mid = self._color_from_gradient(grad, 0.45)
            bot = self._color_from_gradient(grad, 0.10)
            bg = cairo.LinearGradient(0, 0, 0, height)
            bg.add_color_stop_rgba(0.0, top[0] * 0.06, top[1] * 0.06, top[2] * 0.10, 0.98)
            bg.add_color_stop_rgba(0.55, mid[0] * 0.05, mid[1] * 0.05, mid[2] * 0.08, 0.96)
            bg.add_color_stop_rgba(1.0, bot[0] * 0.03, bot[1] * 0.03, bot[2] * 0.05, 0.98)
            cr.set_source(bg)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Nebula pulse.
        neb_r = min(width, height) * (0.30 + (0.08 * bass))
        neb = cairo.RadialGradient(width * 0.52, height * 0.58, neb_r * 0.25, width * 0.52, height * 0.58, neb_r)
        if is_bwr:
            neb_c = (0.16, 0.28, 0.95, 1.0)
        else:
            neb_c = self._color_from_gradient(grad, 0.30)
        neb.add_color_stop_rgba(0.0, neb_c[0], neb_c[1], neb_c[2], 0.14 + (0.08 * bass))
        neb.add_color_stop_rgba(1.0, neb_c[0], neb_c[1], neb_c[2], 0.0)
        cr.set_source(neb)
        cr.arc(width * 0.52, height * 0.58, neb_r, 0, 2 * math.pi)
        cr.fill()

        # Star field driven by spectrum bands.
        for nx, ny, base_sz, ph, band, depth in self.star_seeds:
            idx = min(n - 1, band)
            lvl = max(0.0, min(self.current_heights[idx] * gain, 1.0))
            tw = 0.5 + (0.5 * math.sin((self.phase * 2.2) + (ph * 6.283) + (band * 0.11)))
            pulse = max(0.0, min(1.0, (lvl * 1.45) + (bass * 0.45 * depth)))
            alpha = 0.05 + (0.40 * tw * (0.35 + pulse))
            if alpha < 0.07:
                continue

            drift = 1.2 + (5.2 * bass * depth)
            x = (nx * width) + (math.sin((self.phase * 0.55) + (ph * 4.2)) * drift)
            y = (ny * height) + (math.cos((self.phase * 0.37) + (ph * 3.1)) * (drift * 0.75))
            if x < -4 or x > width + 4 or y < -4 or y > height + 4:
                continue

            sz = max(0.5, base_sz * (0.75 + (1.8 * pulse)))
            if is_bwr:
                # Pure blue / white / red stars.
                if depth < 0.34:
                    c = (0.12, 0.42, 1.0, 1.0)
                elif depth < 0.67:
                    c = (1.0, 1.0, 1.0, 1.0)
                else:
                    c = (1.0, 0.18, 0.18, 1.0)
            else:
                c = self._color_from_gradient(grad, 0.12 + (0.78 * depth))

            # Glow
            cr.set_source_rgba(c[0], c[1], c[2], alpha * 0.42)
            cr.arc(x, y, sz * 2.5, 0, 2 * math.pi)
            cr.fill()
            # Core
            cr.set_source_rgba(c[0], c[1], c[2], alpha)
            cr.arc(x, y, sz, 0, 2 * math.pi)
            cr.fill()
            # Hot center
            cr.set_source_rgba(1.0, 1.0, 1.0, min(0.92, alpha * 1.25))
            cr.arc(x, y, max(0.35, sz * 0.35), 0, 2 * math.pi)
            cr.fill()

    def _draw_ribbon(self, cr, width, height, gain, grad):
        n = self.num_bars
        if n <= 2:
            return
        step_x = width / float(max(1, n - 1))
        center_y = height * 0.58
        amp = height * 0.44
        top_points = []
        bot_points = []
        for i in range(n):
            lvl = max(0.0, min(self.current_heights[i] * gain, 1.0))
            x = i * step_x
            offset = lvl * amp
            thickness = 6.0 + (lvl * 9.0)
            y = center_y - offset
            top_points.append((x, y - thickness))
            bot_points.append((x, y + thickness))
        cr.new_path()
        x0, y0 = top_points[0]
        cr.move_to(x0, y0)
        for x, y in top_points[1:]:
            cr.line_to(x, y)
        for x, y in reversed(bot_points):
            cr.line_to(x, y)
        cr.close_path()
        rg = cairo.LinearGradient(0, 0, width, 0)
        for i, (stop, rgba) in enumerate(grad):
            # spread palette horizontally across ribbon
            rg.add_color_stop_rgba(min(1.0, stop + (0.08 * i)), rgba[0], rgba[1], rgba[2], max(0.35, rgba[3] * 0.95))
        cr.set_source(rg)
        cr.fill_preserve()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.18)
        cr.set_line_width(1.0)
        cr.stroke()

    def _draw_waterfall(self, cr, width, height, gain, grad):
        n = self.num_bars
        if n <= 0:
            return
        spacing = 1.0
        bar_w = max(1.0, (width - (n - 1) * spacing) / n)
        step_y = 4.0
        layers = int(max(8, min(36, height // step_y)))

        # Rust fast path: generate full RGBA frame, then single Cairo paint.
        if self._rust_core.available:
            bar_colors = [self._color_from_gradient(grad, i / float(max(1, n - 1))) for i in range(n)]
            rgba_pack = self._rust_core.build_fall_rgba(
                levels=self.current_heights,
                gain=float(gain),
                height_px=int(max(1, height)),
                step_y_px=int(step_y),
                thickness_px=2,
                bar_colors_rgba=bar_colors,
            )
            if rgba_pack is not None:
                if not self._logged_rust_fall_img:
                    logger.info("Fall image-generation path: Rust")
                    self._logged_rust_fall_img = True
                rgba_bytes, img_w, img_h = rgba_pack
                stride = img_w * 4
                try:
                    surf = cairo.ImageSurface.create_for_data(
                        rgba_bytes,
                        cairo.FORMAT_ARGB32,
                        img_w,
                        img_h,
                        stride,
                    )
                    cr.save()
                    cr.scale(width / float(max(1, img_w)), 1.0)
                    cr.set_source_surface(surf, 0.0, 0.0)
                    src = cr.get_source()
                    try:
                        src.set_filter(cairo.FILTER_NEAREST)
                    except Exception:
                        pass
                    cr.paint()
                    cr.restore()
                    return
                except Exception:
                    pass
        if not self._logged_python_fall_img:
            logger.info("Fall image-generation path: Python fallback")
            self._logged_python_fall_img = True

        cells = None
        if self._rust_core.available:
            cells = self._rust_core.build_fall_cells(
                levels=self.current_heights,
                gain=float(gain),
                height=float(height),
                step_y=float(step_y),
                layers=int(layers),
            )
            if cells is not None and not self._logged_rust_fall:
                logger.info("Fall cell-generation path: Rust")
                self._logged_rust_fall = True
        if cells is None:
            if not self._logged_python_fall:
                logger.info("Fall cell-generation path: Python fallback")
                self._logged_python_fall = True
            cells = []
            for l in range(layers):
                fade = 1.0 - (l / float(max(1, layers - 1)))
                y_off = l * step_y
                for i in range(n):
                    lvl = max(0.0, min(self.current_heights[i] * gain, 1.0))
                    if lvl < 0.01:
                        continue
                    active = lvl * height
                    if y_off > active:
                        continue
                    y = height - y_off - 2.0
                    if y < 0:
                        continue
                    cells.append((i, y, fade))

        for i, y, fade in cells:
            if i < 0 or i >= n:
                continue
            x = i * (bar_w + spacing)
            r, g, b, a = self._color_from_gradient(grad, i / float(max(1, n - 1)))
            cr.set_source_rgba(r, g, b, max(0.05, a * 0.55 * fade))
            cr.rectangle(x, y, bar_w, 2.0)
            cr.fill()

    def _draw_spiral(self, cr, width, height, gain, grad):
        if self.num_bars <= 0:
            return
        bins = self._build_log_bins(self.current_heights, 64)
        n = len(bins)
        if n <= 0:
            return
        cx, cy = width * 0.5, height * 0.54
        full_span = math.hypot(width, height)
        points = None
        if self._rust_core.available:
            points = self._rust_core.build_spiral_points(
                bins=bins,
                width=float(width),
                height=float(height),
                phase=float(self.phase),
                gain=float(gain),
                max_points=240,
            )
            if points is not None and not self._logged_rust_spiral:
                logger.info("Spiral point-generation path: Rust")
                self._logged_rust_spiral = True
        if points is None:
            if not self._logged_python_spiral:
                logger.info("Spiral point-generation path: Python fallback")
                self._logged_python_spiral = True
            base = min(width, height) * 0.015
            span = full_span * 0.52
            sample_n = 240
            max_bin = max(0.001, max(bins))
            points = []
            for si in range(sample_n):
                t = si / float(max(1, sample_n - 1))
                src = min(n - 1, int(t * n))
                raw = max(0.0, min(bins[src] * gain, 1.0))
                lvl = max(0.0, min(raw / max_bin, 1.0))
                if lvl < 0.004:
                    continue
                angle = (self.phase * 1.2) + (t * 14.0 * math.pi)
                radius = base + (t * span * (0.42 + (lvl * 0.72)))
                x = cx + math.cos(angle) * radius
                y = cy + math.sin(angle) * radius
                points.append((x, y, lvl, t))

        # Paint-mix swirl background rotating with the spiral.
        swirl_layers = 6
        seg_n = 96
        outer_r = full_span * 0.42
        inner_r = min(width, height) * 0.05
        for li in range(swirl_layers):
            lt = li / float(max(1, swirl_layers - 1))
            col = self._color_from_gradient(grad, (0.12 + (0.76 * lt)) % 1.0)
            alpha = 0.03 + (0.045 * (1.0 - lt))
            phase = (self.phase * (0.58 + (0.08 * li))) + (li * 1.03)
            lane = 0.18 + (0.08 * (1.0 - lt))
            cr.new_path()
            for si in range(seg_n + 1):
                s = si / float(seg_n)
                r = outer_r - ((outer_r - inner_r) * (s ** 1.08))
                ang_c = phase + (s * (8.4 + (2.2 * lt))) + (math.sin((s * 12.0) + phase) * 0.28)
                spread = lane * (0.32 + (0.68 * (1.0 - s)))
                a = ang_c - spread
                x = cx + (math.cos(a) * r)
                y = cy + (math.sin(a) * r)
                if si == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            for si in range(seg_n, -1, -1):
                s = si / float(seg_n)
                r = outer_r - ((outer_r - inner_r) * (s ** 1.08))
                ang_c = phase + (s * (8.4 + (2.2 * lt))) + (math.sin((s * 12.0) + phase) * 0.28)
                spread = lane * (0.32 + (0.68 * (1.0 - s)))
                a = ang_c + spread
                cr.line_to(cx + (math.cos(a) * r), cy + (math.sin(a) * r))
            cr.close_path()
            cr.set_source_rgba(col[0], col[1], col[2], alpha)
            cr.fill()

        for x, y, lvl, t in points:
            r, g, b, a = self._color_from_gradient(grad, t)
            dot = 0.8 + (lvl * 2.0)
            cr.set_source_rgba(r, g, b, max(0.11, a * 0.70))
            cr.arc(x, y, dot, 0, 2 * math.pi)
            cr.fill()

    def _build_log_bins(self, values, out_count):
        if self._rust_core.available:
            out = self._rust_core.build_log_bins(values, out_count)
            if out is not None:
                if not self._logged_rust_bins:
                    logger.info("Log-bin preprocessing path: Rust")
                    self._logged_rust_bins = True
                return out
        if not self._logged_python_bins:
            logger.info("Log-bin preprocessing path: Python fallback")
            self._logged_python_bins = True
        in_count = len(values)
        if in_count <= 0 or out_count <= 0:
            return []
        out = [0.0] * out_count
        for i in range(out_count):
            t0 = i / float(out_count)
            t1 = (i + 1) / float(out_count)
            x0 = int(pow(t0, 2.15) * (in_count - 1))
            x1 = int(pow(t1, 2.15) * (in_count - 1))
            if x1 <= x0:
                x1 = min(in_count - 1, x0 + 1)
            s = 0.0
            c = 0
            for j in range(x0, x1 + 1):
                s += values[j]
                c += 1
            v = (s / float(max(1, c))) if c > 0 else 0.0
            # slight lift for high band readability while keeping low-end weight
            tilt = 0.92 + (0.16 * (i / float(max(1, out_count - 1))))
            out[i] = max(0.0, min(1.0, pow(v, 0.84) * tilt))
        return out

    def _draw_pro_background(self, cr, width, height, grad):
        c_lo = self._color_from_gradient(grad, 0.85)
        c_mid = self._color_from_gradient(grad, 0.45)
        c_hi = self._color_from_gradient(grad, 0.10)
        bg = cairo.LinearGradient(0, 0, 0, height)
        bg.add_color_stop_rgba(0.0, c_hi[0] * 0.08, c_hi[1] * 0.08, c_hi[2] * 0.08, 0.92)
        bg.add_color_stop_rgba(0.58, c_mid[0] * 0.10, c_mid[1] * 0.10, c_mid[2] * 0.10, 0.86)
        bg.add_color_stop_rgba(1.0, c_lo[0] * 0.08, c_lo[1] * 0.08, c_lo[2] * 0.08, 0.96)
        cr.set_source(bg)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Analyzer-like dB guides.
        for i in range(6):
            t = i / 5.0
            y = height * t
            alpha = 0.03 + (0.03 * (1.0 - t))
            cr.set_source_rgba(1.0, 1.0, 1.0, alpha)
            cr.set_line_width(1.0)
            cr.move_to(0, y)
            cr.line_to(width, y)
            cr.stroke()

    def _draw_pro_analyzer(self, cr, width, height, gain, grad):
        self._draw_pro_background(cr, width, height, grad)
        bins = self._build_log_bins(self.current_heights, self.num_bars)
        peaks = self._build_log_bins(self.peak_holds, self.num_bars)
        n = len(bins)
        if n <= 0:
            return
        spacing = 1.0
        bar_w = max(1.0, (width - ((n - 1) * spacing)) / float(n))
        for i in range(n):
            lvl = max(0.0, min(bins[i] * gain, 1.0))
            if lvl < 0.002:
                continue
            h = max(1.0, lvl * height)
            x = i * (bar_w + spacing)
            y = height - h
            r, g, b, a = self._color_from_gradient(grad, i / float(max(1, n - 1)))
            cr.set_source_rgba(r, g, b, max(0.38, a * 0.95))
            self._draw_rounded_top_bar(cr, x, y, bar_w, h, height)
            cr.fill()

            # Subtle glow column.
            cr.set_source_rgba(r, g, b, 0.12)
            cr.rectangle(x, y, bar_w, h)
            cr.fill()

            peak = max(0.0, min(peaks[i] * gain, 1.0))
            if peak > 0.01:
                py = height - (peak * height)
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.62)
                cr.rectangle(x, py, bar_w, 1.8)
                cr.fill()

    def _draw_pro_analyzer_line(self, cr, width, height, gain, grad):
        self._draw_pro_background(cr, width, height, grad)
        bins = self._build_log_bins(self.current_heights, self.num_bars)
        n = len(bins)
        if n <= 1:
            return
        points = None
        if self._rust_core.available:
            points = self._rust_core.build_line_points(
                bins=bins,
                width=float(width),
                height=float(height),
                gain=float(gain),
            )
            if points is not None and not self._logged_rust_line:
                logger.info("Pro Line point-generation path: Rust")
                self._logged_rust_line = True
        if points is None:
            if not self._logged_python_line:
                logger.info("Pro Line point-generation path: Python fallback")
                self._logged_python_line = True
            step_x = width / float(max(1, n - 1))
            points = []
            for i in range(n):
                lvl = max(0.0, min(bins[i] * gain, 1.0))
                x = i * step_x
                y = height - (lvl * height)
                points.append((x, y))

        fill_grad = cairo.LinearGradient(0, 0, 0, height)
        c0 = self._color_from_gradient(grad, 0.20)
        c1 = self._color_from_gradient(grad, 0.82)
        fill_grad.add_color_stop_rgba(0.0, c0[0], c0[1], c0[2], 0.42)
        fill_grad.add_color_stop_rgba(1.0, c1[0], c1[1], c1[2], 0.06)
        cr.new_path()
        cr.move_to(0, height)
        for x, y in points:
            cr.line_to(x, y)
        cr.line_to(width, height)
        cr.close_path()
        cr.set_source(fill_grad)
        cr.fill()

        cr.new_path()
        cr.move_to(points[0][0], points[0][1])
        for x, y in points[1:]:
            cr.line_to(x, y)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.78)
        cr.set_line_width(2.0)
        cr.stroke_preserve()

        line_grad = cairo.LinearGradient(0, 0, width, 0)
        for stop, rgba in grad:
            line_grad.add_color_stop_rgba(stop, rgba[0], rgba[1], rgba[2], max(0.65, rgba[3]))
        cr.set_source(line_grad)
        cr.set_line_width(1.25)
        cr.stroke()

    def _draw_pro_analyzer_waterfall(self, cr, width, height, gain, grad):
        self._draw_pro_background(cr, width, height, grad)
        if not self.pro_heat_history:
            return
        step_x = 2.8
        cols = max(1, int(width // step_x))
        frames = self.pro_heat_history[-cols:]
        rows = len(frames[-1]) if frames else 0
        if rows <= 0:
            return
        cell_h = max(1.0, height / float(rows))
        # Palette LUT to avoid repeated gradient interpolation per cell.
        palette_n = 96
        palette = [self._color_from_gradient(grad, i / float(palette_n - 1)) for i in range(palette_n)]

        # Rust fast path: generate full RGBA frame, then single Cairo paint.
        if self._rust_core.available:
            rgba_pack = self._rust_core.build_pro_fall_rgba(frames, float(gain), palette)
            if rgba_pack is not None:
                if not self._logged_rust_pro_fall_img:
                    logger.info("Pro Fall image-generation path: Rust")
                    self._logged_rust_pro_fall_img = True
                rgba_bytes, img_w, img_h = rgba_pack
                stride = img_w * 4
                try:
                    surf = cairo.ImageSurface.create_for_data(
                        rgba_bytes,
                        cairo.FORMAT_ARGB32,
                        img_w,
                        img_h,
                        stride,
                    )
                    cr.save()
                    cr.scale(width / float(max(1, img_w)), height / float(max(1, img_h)))
                    cr.set_source_surface(surf, 0.0, 0.0)
                    src = cr.get_source()
                    try:
                        src.set_filter(cairo.FILTER_BILINEAR)
                    except Exception:
                        pass
                    cr.paint()
                    cr.restore()
                    return
                except Exception:
                    # Fall through to Python path.
                    pass

        if not self._logged_python_pro_fall_img:
            logger.info("Pro Fall image-generation path: Python fallback")
            self._logged_python_pro_fall_img = True
        for c, bins in enumerate(reversed(frames)):
            x = width - ((c + 1) * step_x)
            age = 1.0 - (c / float(max(1, cols)))
            age = pow(max(0.0, age), 1.25)
            active_rows = None
            if self._rust_core.available:
                active_rows = self._rust_core.build_pro_fall_column(bins, float(gain))
                if active_rows is not None and not self._logged_rust_pro_fall:
                    logger.info("Pro Fall column-generation path: Rust")
                    self._logged_rust_pro_fall = True
            if active_rows is None:
                if not self._logged_python_pro_fall:
                    logger.info("Pro Fall column-generation path: Python fallback")
                    self._logged_python_pro_fall = True
                active_rows = []
                for r, raw in enumerate(bins):
                    lvl = max(0.0, min(raw * gain, 1.0))
                    if lvl < 0.008:
                        continue
                    active_rows.append((r, lvl))
            for r, lvl in active_rows:
                y = height - ((r + 1) * cell_h)
                idx = int(pow(lvl, 0.86) * (palette_n - 1))
                rr, gg, bb, aa = palette[idx]
                cr.set_source_rgba(rr, gg, bb, max(0.03, aa * age))
                cr.rectangle(x, y, step_x + 0.22, cell_h + 0.15)
                cr.fill()

    def _color_from_gradient(self, gradient, t):
        t = max(0.0, min(1.0, t))
        prev_stop, prev_rgba = gradient[0]
        for stop, rgba in gradient[1:]:
            if t <= stop:
                span = max(1e-6, stop - prev_stop)
                w = (t - prev_stop) / span
                return tuple(prev_rgba[i] + ((rgba[i] - prev_rgba[i]) * w) for i in range(4))
            prev_stop, prev_rgba = stop, rgba
        return gradient[-1][1]
