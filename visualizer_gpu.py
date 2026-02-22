import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gtk, GLib, Gdk, Graphene
import math
import logging
from copy import deepcopy
from visualizer import SpectrumVisualizer
from rust_viz import RustVizCore

logger = logging.getLogger(__name__)


class SpectrumVisualizerGPU(Gtk.Widget):
    def __init__(self):
        super().__init__()
        self.set_size_request(-1, 0)
        self.theme_name = "Aurora (Default)"
        self.effect_name = "Bars"
        self._native_effects = [
            "Bars",
            "Mirror",
            "Peak",
            "Pulse",
        ]
        self._cairo_renderer = SpectrumVisualizer()
        self._cairo_only_effects = [e for e in self._cairo_renderer.effects if e not in self._native_effects]
        self.effects = self._native_effects + self._cairo_only_effects
        self.profile_name = "Dynamic"
        self.profiles = {
            "Soft": {
                "gain_mul": 0.84,
                "spacing_mul": 1.08,
                "smooth": 0.30,
                "trail_decay": 0.93,
                "peak_hold_frames": 12,
                "peak_fall": 0.014,
            },
            "Dynamic": {
                "gain_mul": 1.0,
                "spacing_mul": 1.0,
                "smooth": 0.45,
                "trail_decay": 0.90,
                "peak_hold_frames": 8,
                "peak_fall": 0.02,
            },
            "Extreme": {
                "gain_mul": 1.18,
                "spacing_mul": 0.92,
                "smooth": 0.56,
                "trail_decay": 0.87,
                "peak_hold_frames": 6,
                "peak_fall": 0.03,
            },
            "Insane": {
                "gain_mul": 1.32,
                "spacing_mul": 0.88,
                "smooth": 0.62,
                "trail_decay": 0.84,
                "peak_hold_frames": 4,
                "peak_fall": 0.04,
            },
        }
        self.themes = deepcopy(self._cairo_renderer.themes)
        self.num_bars = 64
        self.target_heights = [0.0] * self.num_bars
        self.current_heights = [0.0] * self.num_bars
        self.trail_heights = [0.0] * self.num_bars
        self.peak_holds = [0.0] * self.num_bars
        self.peak_ttl = [0] * self.num_bars
        self.pro_heat_history = []
        self._pro_fall_history_tick = 0
        self.phase = 0.0
        self._rust_core = RustVizCore()
        self._logged_rust_path = False
        self._logged_python_fallback = False
        self._logged_rust_bins = False
        self._logged_python_bins = False
        self._cairo_renderer.set_num_bars(self.num_bars)
        self._active = False
        self._anim_source = None

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return (100, 100, -1, -1)
        return (180, 250, -1, -1)

    def get_theme_names(self):
        return list(self.themes.keys())

    def get_effect_names(self):
        return list(self.effects)

    def get_profile_names(self):
        return list(self.profiles.keys())

    def set_active(self, active):
        new_active = bool(active)
        if self._active == new_active:
            return
        self._active = new_active
        if self._active:
            if self._anim_source is None:
                self._anim_source = GLib.timeout_add(16, self._on_animation_tick)
            self.queue_draw()
        else:
            if self._anim_source:
                try:
                    GLib.source_remove(self._anim_source)
                except Exception:
                    pass
                self._anim_source = None

    def set_theme(self, theme_name):
        if theme_name in self.themes:
            self.theme_name = theme_name
            self.queue_draw()

    def set_effect(self, effect_name):
        if effect_name in self.effects:
            self.effect_name = effect_name
            if effect_name != "Pro Fall":
                self.pro_heat_history = []
                self._pro_fall_history_tick = 0
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
        self.pro_heat_history = []
        self._pro_fall_history_tick = 0
        self.queue_draw()

    def update_data(self, magnitudes):
        if not magnitudes:
            return
        vals = list(magnitudes)
        out = None
        if self._rust_core.available:
            if not self._logged_rust_path:
                logger.info("Spectrum preprocessing path: Rust (Snapshot GPU)")
                self._logged_rust_path = True
            out = self._rust_core.process_spectrum(vals, self.num_bars, db_min=-60.0, db_range=60.0)
        if out is None:
            if not self._logged_python_fallback:
                logger.info("Spectrum preprocessing path: Python (Snapshot GPU fallback)")
                self._logged_python_fallback = True
            actual = min(len(vals), self.num_bars)
            db_min = -60.0
            db_range = 60.0
            out = []
            for i in range(actual):
                v = vals[i]
                if v <= db_min:
                    h = 0.0
                else:
                    h = (v - db_min) / db_range
                out.append(max(0.0, min(1.0, h)))
            while len(out) < self.num_bars:
                out.append(0.0)
        self.target_heights = out

    def _on_animation_tick(self):
        if not self._active:
            self._anim_source = None
            return False
        profile = self.profiles.get(self.profile_name, self.profiles["Dynamic"])
        changed = False
        self.phase += 0.045
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
        if changed:
            self.queue_draw()
        return True

    def do_snapshot(self, snapshot):
        width = float(self.get_width() or 0)
        height = float(self.get_height() or 0)
        if width <= 1 or height <= 1:
            return
        if self.effect_name in self._cairo_only_effects:
            self._snapshot_with_cairo(snapshot, width, height)
            return

        theme = self.themes.get(self.theme_name, self.themes["Aurora (Default)"])
        profile = self.profiles.get(self.profile_name, self.profiles["Dynamic"])
        spacing = max(0.8, float(theme["bar_spacing"]) * float(profile["spacing_mul"]))
        gain = float(theme["height_gain"]) * float(profile["gain_mul"])
        n = max(1, self.num_bars)
        bar_w = max(1.0, (width - (n - 1) * spacing) / n)
        grad = theme.get("gradient")
        c0 = self._color_from_gradient(grad, 0.0)

        bg = Gdk.RGBA()
        bg.parse("rgba(10,12,18,0.90)")
        snapshot.append_color(bg, Graphene.Rect().init(0, 0, width, height))

        effect = self.effect_name

        pulse_mul = 0.0
        if effect == "Pulse":
            bass = sum(self.current_heights[: max(1, n // 12)]) / float(max(1, n // 12))
            pulse_mul = bass
            glow = Gdk.RGBA()
            glow.red, glow.green, glow.blue, glow.alpha = c0[0], c0[1], c0[2], 0.08 + (0.18 * pulse_mul)
            snapshot.append_color(glow, Graphene.Rect().init(0, 0, width, height))

        for i in range(n):
            t = i / float(max(1, n - 1))
            r, g, b, _a = self._color_from_gradient(grad, t)
            lvl = max(0.0, min(self.current_heights[i] * gain, 1.0))
            if lvl < 0.001:
                continue
            h = max(1.0, lvl * height)
            x = i * (bar_w + spacing)
            y = height - h

            col = Gdk.RGBA()
            col.red, col.green, col.blue = r, g, b
            col.alpha = 0.85

            if effect == "Mirror":
                mid = height * 0.5
                mh = max(1.0, min(lvl * height * 0.48, mid))
                snapshot.append_color(col, Graphene.Rect().init(x, mid - mh, bar_w, mh))
                snapshot.append_color(col, Graphene.Rect().init(x, mid, bar_w, mh))
            elif effect == "Wave":
                # Wave-like look using thin vertical samples.
                wave_h = h * (0.70 + 0.30 * math.sin((self.phase * 2.0) + (i * 0.12)))
                yy = max(0.0, height - wave_h)
                snapshot.append_color(col, Graphene.Rect().init(x, yy, bar_w, max(1.0, wave_h)))
            elif effect == "Fill":
                # Filled-wave look: vertical slices from wave contour down to bottom.
                wave_h = h * (0.82 + 0.18 * math.sin((self.phase * 1.6) + (i * 0.10)))
                yy = max(0.0, height - wave_h)
                fill_col = Gdk.RGBA()
                fill_col.red, fill_col.green, fill_col.blue, fill_col.alpha = r, g, b, 0.72
                snapshot.append_color(fill_col, Graphene.Rect().init(x, yy, bar_w, max(1.0, height - yy)))
                # Light crest highlight to match Cairo filled-wave top edge feel.
                crest = Gdk.RGBA()
                crest.parse("rgba(255,255,255,0.14)")
                snapshot.append_color(crest, Graphene.Rect().init(x, yy, bar_w, 1.2))
            elif effect == "Trail":
                trail = Gdk.RGBA()
                trail.red, trail.green, trail.blue, trail.alpha = r, g, b, 0.22
                th = max(1.0, min(self.trail_heights[i] * gain, 1.0) * height)
                ty = height - th
                snapshot.append_color(trail, Graphene.Rect().init(x, ty, bar_w, th))
                snapshot.append_color(col, Graphene.Rect().init(x, y, bar_w, h))
            elif effect == "Peak":
                snapshot.append_color(col, Graphene.Rect().init(x, y, bar_w, h))
                py = height - max(1.0, min(self.peak_holds[i] * gain, 1.0) * height)
                cap = Gdk.RGBA()
                cap.parse("rgba(255,255,255,0.75)")
                snapshot.append_color(cap, Graphene.Rect().init(x, py, bar_w, 2.0))
            elif effect == "Dots":
                # Match Cairo dot-matrix look: fixed dot height and gap.
                dot_h = 4.0
                gap = 1.2
                h_dots = max(1.0, min(lvl * height, height))
                y0 = height - dot_h
                drawn = 0.0
                while drawn < h_dots:
                    yy = y0 - drawn
                    if yy < 0:
                        break
                    snapshot.append_color(col, Graphene.Rect().init(x, yy, bar_w, dot_h))
                    drawn += dot_h + gap
            else:
                snapshot.append_color(col, Graphene.Rect().init(x, y, bar_w, h))

    def _snapshot_with_cairo(self, snapshot, width, height):
        rect = Graphene.Rect()
        rect.init(0, 0, width, height)
        cr = snapshot.append_cairo(rect)

        r = self._cairo_renderer
        if self.theme_name in r.themes:
            r.theme_name = self.theme_name
        if self.profile_name in r.profiles:
            r.profile_name = self.profile_name
        r.effect_name = self.effect_name
        if r.num_bars != self.num_bars:
            r.set_num_bars(self.num_bars)
        r.current_heights = list(self.current_heights)
        r.target_heights = list(self.target_heights)
        r.trail_heights = list(self.trail_heights)
        r.peak_holds = list(self.peak_holds)
        r.peak_ttl = list(self.peak_ttl)
        r.phase = self.phase
        r._draw_callback(None, cr, int(width), int(height), None)

    def _color_from_gradient(self, gradient, t):
        if not gradient:
            return (0.2, 0.7, 1.0, 1.0)
        t = max(0.0, min(1.0, t))
        left = gradient[0]
        right = gradient[-1]
        for i in range(len(gradient) - 1):
            a = gradient[i]
            b = gradient[i + 1]
            if a[0] <= t <= b[0]:
                left, right = a, b
                break
        x0, c0 = left
        x1, c1 = right
        if x1 <= x0:
            return c0
        k = (t - x0) / (x1 - x0)
        return (
            c0[0] + (c1[0] - c0[0]) * k,
            c0[1] + (c1[1] - c0[1]) * k,
            c0[2] + (c1[2] - c0[2]) * k,
            c0[3] + (c1[3] - c0[3]) * k,
        )

    def _build_log_bins(self, values, out_count):
        if self._rust_core.available:
            out = self._rust_core.build_log_bins(values, out_count)
            if out is not None:
                if not self._logged_rust_bins:
                    logger.info("Log-bin preprocessing path: Rust (Snapshot GPU)")
                    self._logged_rust_bins = True
                return out
        if not self._logged_python_bins:
            logger.info("Log-bin preprocessing path: Python (Snapshot GPU fallback)")
            self._logged_python_bins = True
        n = len(values)
        if n <= 0 or out_count <= 0:
            return [0.0] * max(0, out_count)
        out = [0.0] * out_count
        lo = math.log(1.0)
        hi = math.log(float(n))
        for i in range(out_count):
            a = i / float(out_count)
            b = (i + 1) / float(out_count)
            sa = int(round(math.exp(lo + ((hi - lo) * a)) - 1.0))
            sb = int(round(math.exp(lo + ((hi - lo) * b)) - 1.0))
            sa = max(0, min(n - 1, sa))
            sb = max(sa + 1, min(n, sb))
            seg = values[sa:sb]
            if seg:
                v = sum(seg) / float(len(seg))
            else:
                v = 0.0
            tilt = 0.92 + (0.16 * (i / float(max(1, out_count - 1))))
            out[i] = max(0.0, min(1.0, pow(v, 0.84) * tilt))
        return out

    def _draw_pro_fall_native(self, snapshot, width, height, gain, grad):
        if not self.pro_heat_history:
            return
        step_x = 4.8
        cols = max(1, int(width // step_x))
        frames = self.pro_heat_history[-cols:]
        rows = len(frames[-1]) if frames else 0
        if rows <= 0:
            return
        cell_h = max(1.0, height / float(rows))
        palette_n = 64
        palette = [self._color_from_gradient(grad, i / float(max(1, palette_n - 1))) for i in range(palette_n)]
        for c, bins in enumerate(reversed(frames)):
            x = width - ((c + 1) * step_x)
            age = 1.0 - (c / float(max(1, cols)))
            age = pow(max(0.0, age), 1.25)
            for r, raw in enumerate(bins):
                lvl = max(0.0, min(raw * gain, 1.0))
                if lvl < 0.008:
                    continue
                y = height - ((r + 1) * cell_h)
                idx = int(pow(lvl, 0.86) * (palette_n - 1))
                rr, gg, bb, aa = palette[idx]
                col = Gdk.RGBA()
                col.red, col.green, col.blue, col.alpha = rr, gg, bb, max(0.03, aa * age)
                snapshot.append_color(col, Graphene.Rect().init(x, y, step_x + 0.18, cell_h + 0.12))
