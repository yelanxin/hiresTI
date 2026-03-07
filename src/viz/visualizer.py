import gi
import os
import sys

_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
import cairo
import math
import logging
from _rust.viz import RustVizCore

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
            "Fall",
            "Orbit",
            "Shards",
            "Stereo Mirror",
            "Lissajous",
            "Stereo Scope",
            "Balance Wave",
            "Center Side",
            "Phase Flower",
            "Stereo Meter",
        ]
        self.profile_name = "Dynamic"
        self._effect_code_map = {
            "Bars": 0,
            "Wave": 1,
            "Fill": 2,
            "Mirror": 3,
            "Dots": 4,
            "Neon": 5,
            "Peak": 6,
            "Trail": 7,
            "Pulse": 8,
            "Stereo": 9,
            "Burst": 10,
            "Stars": 11,
            "Ribbon": 12,
            "Spiral": 13,
            "Fall": 16,
            "Orbit": 17,
            "Shards": 18,
            "Stereo Mirror": 19,
            "Lissajous": 20,
            "Stereo Scope": 21,
            "Balance Wave": 22,
            "Center Side": 23,
            "Phase Flower": 24,
            "Stereo Meter": 26,
            "Dual Fall": 25,
        }
        self.profiles = {
            "Gentle": {
                "gain_mul": 0.72,
                "spacing_mul": 1.10,
                "grid_mul": 0.78,
                "smooth": 0.22,
                "trail_decay": 0.95,
                "peak_hold_frames": 14,
                "peak_fall": 0.010,
                "beat_mul": 0.66,
            },
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
            "Stereo Red Blue": {
                "grid_alpha": 0.024,
                "bar_spacing": 1.46,
                "height_gain": 1.62,
                "gradient": (
                    (0.0, (1.0, 0.20, 0.18, 0.98)),   # hot red
                    (0.48, (0.60, 0.22, 0.98, 0.92)), # bridge violet
                    (1.0, (0.18, 0.62, 1.0, 0.88)),   # electric blue
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
        self.target_left_channel_heights = [0.0] * self.num_bars
        self.target_right_channel_heights = [0.0] * self.num_bars
        self.left_channel_heights = [0.0] * self.num_bars
        self.right_channel_heights = [0.0] * self.num_bars
        self.left_peak_holds = [0.0] * self.num_bars
        self.right_peak_holds = [0.0] * self.num_bars
        self.left_peak_ttl = [0] * self.num_bars
        self.right_peak_ttl = [0] * self.num_bars
        self.trail_heights = [0.0] * self.num_bars
        self.peak_holds = [0.0] * self.num_bars
        self.peak_ttl = [0] * self.num_bars
        self.heat_history = []
        self.left_heat_history = []
        self.right_heat_history = []
        self.left_log_heat_history = []
        self.right_log_heat_history = []
        self.pro_heat_history = []
        self.pro_fall_history = []
        self.star_seeds = self._gen_star_seeds(260)
        self._bass_target = 0.0
        self.bass_level = 0.0
        self.phase = 0.0
        self._rust_core = RustVizCore()
        self._rust_bars_rgba_enabled = str(os.getenv("HIRESTI_RUST_BARS_RGBA", "1") or "1").strip().lower() in ("1", "true", "yes", "on")
        self._rust_bars_renderer = None
        self._bars_color_cache_key = None
        self._bars_color_cache = None
        self._bars_img_cache_key = None
        self._bars_img_cache_pack = None
        self._bars_img_last_ts = 0.0
        self._fall_body_env = []
        self._fall_core_env = []
        self._fall_edge_env = []
        self._fall_body_smooth = []
        self._fall_core_smooth = []
        self._fall_outline_env = []
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
        self._logged_rust_bars_img = False
        self._logged_python_bars_img = False
        self._theme_cfg = self.themes["Aurora (Default)"]
        self._profile_cfg = self.profiles["Dynamic"]
        self._effect_code = 0
        self._refresh_theme_cache()
        self._refresh_profile_cache()
        self._refresh_effect_cache()
        self._active = False
        self._anim_source = None

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

    def get_theme_names(self):
        return list(self.themes.keys())

    def get_effect_names(self):
        return list(self.effects)

    def get_profile_names(self):
        return list(self.profiles.keys())

    def _refresh_theme_cache(self):
        self._theme_cfg = self.themes[self.theme_name] if self.theme_name in self.themes else self.themes["Aurora (Default)"]

    def _refresh_profile_cache(self):
        self._profile_cfg = self.profiles[self.profile_name] if self.profile_name in self.profiles else self.profiles["Dynamic"]

    def _refresh_effect_cache(self):
        self._effect_code = int(self._effect_code_map.get(self.effect_name, 0))

    def set_theme(self, theme_name):
        if theme_name in self.themes:
            self.theme_name = theme_name
            self._refresh_theme_cache()
            self.queue_draw()

    def set_effect(self, effect_name):
        effect_name = {
            "Pro Bars": "Bars",
            "Pro Line": "Wave",
            "Pro Fall": "Fall",
        }.get(effect_name, effect_name)
        if effect_name in self.effects:
            self.effect_name = effect_name
            self._refresh_effect_cache()
            self.queue_draw()

    def set_profile(self, profile_name):
        if profile_name in self.profiles:
            self.profile_name = profile_name
            self._refresh_profile_cache()
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
        self.target_left_channel_heights = [0.0] * n
        self.target_right_channel_heights = [0.0] * n
        self.left_channel_heights = [0.0] * n
        self.right_channel_heights = [0.0] * n
        self.left_peak_holds = [0.0] * n
        self.right_peak_holds = [0.0] * n
        self.left_peak_ttl = [0] * n
        self.right_peak_ttl = [0] * n
        self.trail_heights = [0.0] * n
        self.peak_holds = [0.0] * n
        self.peak_ttl = [0] * n
        self.heat_history = []
        self.left_heat_history = []
        self.right_heat_history = []
        self.left_log_heat_history = []
        self.right_log_heat_history = []
        self.pro_heat_history = []
        self.pro_fall_history = []
        self.queue_draw()

    def _map_magnitudes_to_heights(self, magnitudes, use_rust=False, log_rust=False):
        vals = list(magnitudes or [])
        if not vals:
            return [0.0] * self.num_bars
        if use_rust and self._rust_core.available:
            out = self._rust_core.process_spectrum(
                vals,
                self.num_bars,
                db_min=-60.0,
                db_range=60.0,
            )
            if out is not None:
                if log_rust and not self._logged_rust_path:
                    logger.info("Spectrum preprocessing path: Rust")
                    self._logged_rust_path = True
                return out
        if not self._logged_python_fallback:
            logger.info("Spectrum preprocessing path: Python fallback")
            self._logged_python_fallback = True
        db_min = -60.0
        db_range = 60.0
        in_count = len(vals)
        out = [0.0] * self.num_bars
        for i in range(self.num_bars):
            t0 = i / float(self.num_bars)
            t1 = (i + 1) / float(self.num_bars)
            x0 = int(t0 * in_count)
            x1 = int(t1 * in_count)
            if x0 >= in_count:
                x0 = in_count - 1
            if x1 <= x0:
                x1 = min(in_count, x0 + 1)
            elif x1 > in_count:
                x1 = in_count
            s = 0.0
            c = 0
            for j in range(x0, x1):
                val = vals[j]
                if val <= db_min:
                    h = 0.0
                else:
                    h = (val - db_min) / db_range
                h = max(0.0, min(1.0, h))
                s += h
                c += 1
            out[i] = (s / float(c)) if c > 0 else 0.0
        return out

    def _resample_channel_heights(self, values, out_count):
        vals = list(values or [])
        if out_count <= 0:
            return []
        if not vals:
            return [0.0] * out_count
        in_count = len(vals)
        out = [0.0] * out_count
        for i in range(out_count):
            t0 = i / float(out_count)
            t1 = (i + 1) / float(out_count)
            x0 = int(t0 * in_count)
            x1 = int(t1 * in_count)
            if x0 >= in_count:
                x0 = in_count - 1
            if x1 <= x0:
                x1 = min(in_count, x0 + 1)
            elif x1 > in_count:
                x1 = in_count
            s = 0.0
            c = 0
            for j in range(x0, x1):
                s += vals[j]
                c += 1
            out[i] = (s / float(c)) if c > 0 else 0.0
        return out

    def update_data(self, magnitudes):
        if not magnitudes:
            return

        if isinstance(magnitudes, dict):
            mono_vals = list(magnitudes.get("mono") or magnitudes.get("left") or magnitudes.get("right") or [])
            left_vals = list(magnitudes.get("left") or mono_vals)
            right_vals = list(magnitudes.get("right") or mono_vals)
        else:
            mono_vals = list(magnitudes)
            left_vals = list(mono_vals)
            right_vals = list(mono_vals)

        actual_count = len(mono_vals)
        new_heights = self._map_magnitudes_to_heights(mono_vals, use_rust=True, log_rust=True)
        self.target_left_channel_heights = self._map_magnitudes_to_heights(left_vals, use_rust=False)
        self.target_right_channel_heights = self._map_magnitudes_to_heights(right_vals, use_rust=False)
        self.target_heights = new_heights
        bass_count = max(1, min(len(new_heights), self.num_bars // 8))
        self._bass_target = sum(new_heights[:bass_count]) / float(bass_count)

    def _on_animation_tick(self):
        if not self._active:
            self._anim_source = None
            return False
        profile = self._profile_cfg
        changed = False
        self.phase += 0.045
        bass_response = max(0.12, min(0.62, 0.28 * float(profile["beat_mul"])))
        self.bass_level += (self._bass_target - self.bass_level) * bass_response
        for i in range(self.num_bars):
            diff = self.target_heights[i] - self.current_heights[i]
            if abs(diff) > 0.001:
                self.current_heights[i] += diff * float(profile["smooth"])
                changed = True
            ldiff = self.target_left_channel_heights[i] - self.left_channel_heights[i]
            if abs(ldiff) > 0.001:
                self.left_channel_heights[i] += ldiff * float(profile["smooth"])
                changed = True
            rdiff = self.target_right_channel_heights[i] - self.right_channel_heights[i]
            if abs(rdiff) > 0.001:
                self.right_channel_heights[i] += rdiff * float(profile["smooth"])
                changed = True
            lcur = self.left_channel_heights[i]
            if lcur >= self.left_peak_holds[i]:
                self.left_peak_holds[i] = lcur
                self.left_peak_ttl[i] = int(profile["peak_hold_frames"])
            else:
                if self.left_peak_ttl[i] > 0:
                    self.left_peak_ttl[i] -= 1
                else:
                    self.left_peak_holds[i] = max(0.0, self.left_peak_holds[i] - float(profile["peak_fall"]))
            rcur = self.right_channel_heights[i]
            if rcur >= self.right_peak_holds[i]:
                self.right_peak_holds[i] = rcur
                self.right_peak_ttl[i] = int(profile["peak_hold_frames"])
            else:
                if self.right_peak_ttl[i] > 0:
                    self.right_peak_ttl[i] -= 1
                else:
                    self.right_peak_holds[i] = max(0.0, self.right_peak_holds[i] - float(profile["peak_fall"]))
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
        self.left_heat_history.append(list(self.left_channel_heights))
        self.right_heat_history.append(list(self.right_channel_heights))
        dual_rows = max(8, min(self.num_bars, 48))
        self.left_log_heat_history.append(self._build_log_bins(self.left_channel_heights, dual_rows))
        self.right_log_heat_history.append(self._build_log_bins(self.right_channel_heights, dual_rows))
        if len(self.heat_history) > 800:
            self.heat_history = self.heat_history[-800:]
        if len(self.left_heat_history) > 800:
            self.left_heat_history = self.left_heat_history[-800:]
        if len(self.right_heat_history) > 800:
            self.right_heat_history = self.right_heat_history[-800:]
        if len(self.left_log_heat_history) > 800:
            self.left_log_heat_history = self.left_log_heat_history[-800:]
        if len(self.right_log_heat_history) > 800:
            self.right_log_heat_history = self.right_log_heat_history[-800:]
        # Pre-binned history for Pro Analyzer Waterfall (avoids heavy per-draw binning).
        pro_rows = max(4, min(self.num_bars, 64))
        pro_bins = self._build_log_bins(self.current_heights, pro_rows)
        self.pro_heat_history.append(pro_bins)
        self.pro_fall_history.append(self._summarize_pro_fall_bins(pro_bins))
        if len(self.pro_heat_history) > 900:
            self.pro_heat_history = self.pro_heat_history[-900:]
        if len(self.pro_fall_history) > 900:
            self.pro_fall_history = self.pro_fall_history[-900:]
        if changed:
            self.queue_draw()
        return True

    def _draw_callback(self, area, cr, width, height, data=None):
        theme = self._theme_cfg
        profile = self._profile_cfg
        if width <= 0 or height <= 0:
            return

        n = self.num_bars
        spacing = max(0.8, theme["bar_spacing"] * float(profile["spacing_mul"]))
        gain = theme["height_gain"] * float(profile["gain_mul"])
        bar_w = max(1.0, (width - (n - 1) * spacing) / n)
        effect = self._effect_code
        if effect not in (14, 15, 16, 17, 18, 20, 21, 22, 23, 24, 25, 26):
            grid_alpha = max(0.0, min(1.0, theme["grid_alpha"] * float(profile["grid_mul"])))
            self._draw_grid(cr, width, height, grid_alpha)
        if effect == 0:
            gradient = self._make_gradient(height, theme)
            self._draw_bars(cr, width, height, gain, gradient, bar_w, spacing)
        elif effect == 1:
            gradient = self._make_gradient(height, theme)
            self._draw_wave_line(cr, width, height, gain, gradient, filled=False)
        elif effect == 2:
            gradient = self._make_gradient(height, theme)
            self._draw_wave_line(cr, width, height, gain, gradient, filled=True)
        elif effect == 3:
            gradient = self._make_gradient(height, theme)
            self._draw_mirror_bars(cr, width, height, gain, gradient, bar_w, spacing)
        elif effect == 4:
            self._draw_dot_matrix(cr, width, height, gain, bar_w, spacing, theme["gradient"])
        elif effect == 5:
            self._draw_neon_tunnel(cr, width, height, gain, theme["gradient"])
        elif effect == 6:
            gradient = self._make_gradient(height, theme)
            self._draw_bars(cr, width, height, gain, gradient, bar_w, spacing)
            self._draw_peak_caps(cr, width, height, gain, bar_w, spacing)
        elif effect == 7:
            gradient = self._make_gradient(height, theme)
            self._draw_trail_glow(cr, width, height, gain, bar_w, spacing)
            self._draw_bars(cr, width, height, gain, gradient, bar_w, spacing)
        elif effect == 8:
            gradient = self._make_gradient(height, theme)
            self._draw_beat_pulse_bg(cr, width, height, theme, float(profile["beat_mul"]))
            self._draw_bars(cr, width, height, gain, gradient, bar_w, spacing)
        elif effect == 9:
            self._draw_split_stereo(cr, width, height, gain, theme["gradient"])
        elif effect == 10:
            self._draw_particle_burst(cr, width, height, gain, theme["gradient"])
        elif effect == 11:
            self._draw_starscape(cr, width, height, gain, theme["gradient"])
        elif effect == 12:
            self._draw_ribbon(cr, width, height, gain, theme["gradient"])
        elif effect == 13:
            self._draw_spiral(cr, width, height, gain, theme["gradient"])
        elif effect == 14:
            self._draw_pro_analyzer(cr, width, height, gain, theme["gradient"])
        elif effect == 15:
            self._draw_pro_analyzer_line(cr, width, height, gain, theme["gradient"])
        elif effect == 16:
            self._draw_pro_analyzer_waterfall(cr, width, height, gain, theme["gradient"])
        elif effect == 17:
            self._draw_orbit(cr, width, height, gain, theme["gradient"])
        elif effect == 18:
            self._draw_shards(cr, width, height, gain, theme["gradient"])
        elif effect == 19:
            gradient = self._make_gradient(height, theme)
            self._draw_stereo_mirror_bars(cr, width, height, gain, gradient, bar_w, spacing)
        elif effect == 20:
            self._draw_lissajous(cr, width, height, gain, theme["gradient"])
        elif effect == 21:
            self._draw_stereo_scope(cr, width, height, gain, theme["gradient"])
        elif effect == 22:
            self._draw_balance_wave(cr, width, height, gain, theme["gradient"])
        elif effect == 23:
            self._draw_center_side(cr, width, height, gain, theme["gradient"])
        elif effect == 24:
            self._draw_phase_flower(cr, width, height, gain, theme["gradient"])
        elif effect == 26:
            self._draw_stereo_meter(cr, width, height, gain, theme["gradient"])
        elif effect == 25:
            self._draw_dual_fall(cr, width, height, gain, theme["gradient"])
        else:
            gradient = self._make_gradient(height, theme)
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
        # Rust fast path: generate full RGBA frame, then single Cairo paint.
        if self._rust_core.available and self._rust_bars_rgba_enabled:
            n = self.num_bars
            # Cache per-theme/per-bar-count colors to avoid heavy per-frame gradient sampling.
            bars_key = (self.theme_name, n)
            if self._bars_color_cache_key != bars_key or self._bars_color_cache is None:
                grad_src = self._theme_cfg["gradient"]
                self._bars_color_cache = [
                    self._color_from_gradient(grad_src, i / float(max(1, n - 1)))
                    for i in range(n)
                ]
                self._bars_color_cache_key = bars_key
            bar_colors = self._bars_color_cache
            # Render in device pixels to avoid extra compositor scaling on HiDPI/fractional setups.
            scale_factor = int(max(1, getattr(self, "get_scale_factor", lambda: 1)() or 1))
            img_w = int(max(1, width * scale_factor))
            img_h = int(max(1, height * scale_factor))
            bars_img_key = (int(img_w), int(img_h), int(n), int(scale_factor))
            if self._bars_img_cache_key != bars_img_key or self._rust_bars_renderer is None:
                try:
                    if self._rust_bars_renderer is not None:
                        self._rust_bars_renderer.close()
                except Exception:
                    pass
                self._rust_bars_renderer = self._rust_core.create_bars_renderer(int(img_w), int(img_h), int(n))
                self._bars_img_cache_key = bars_img_key
                self._bars_color_cache = None
            if self._rust_bars_renderer is not None:
                try:
                    self._rust_bars_renderer.set_colors(bar_colors)
                    self._rust_bars_renderer.render(
                        self.current_heights,
                        float(gain),
                        int(max(1, round(bar_w * scale_factor))),
                        int(max(0, round(spacing * scale_factor))),
                    )
                    frame = self._rust_bars_renderer.get_frame()
                except Exception:
                    frame = None
            else:
                frame = None
            if frame is not None:
                if not self._logged_rust_bars_img:
                    logger.info("Bars image-generation path: Rust")
                    self._logged_rust_bars_img = True
                rgba_buf, img_w, img_h, stride, _seq = frame
                try:
                    surf = cairo.ImageSurface.create_for_data(
                        rgba_buf,
                        cairo.FORMAT_ARGB32,
                        img_w,
                        img_h,
                        stride,
                    )
                    if img_h == int(max(1, height * scale_factor)):
                        # Zero-scale path: avoids pixman resampling entirely.
                        try:
                            surf.set_device_scale(float(scale_factor), float(scale_factor))
                        except Exception:
                            pass
                        cr.set_source_surface(surf, 0.0, 0.0)
                        src = cr.get_source()
                        try:
                            src.set_filter(cairo.FILTER_NEAREST)
                        except Exception:
                            pass
                        cr.paint()
                    else:
                        cr.save()
                        scale_y = height / float(max(1, img_h))
                        cr.scale(1.0, scale_y)
                        try:
                            surf.set_device_scale(float(scale_factor), float(scale_factor))
                        except Exception:
                            pass
                        cr.set_source_surface(surf, 0.0, 0.0)
                        src = cr.get_source()
                        try:
                            # Prefer cheaper filters than bilinear in this hot path.
                            if scale_y > 1.08:
                                src.set_filter(cairo.FILTER_NEAREST)
                            elif scale_y < 0.95:
                                src.set_filter(cairo.FILTER_FAST)
                            else:
                                src.set_filter(cairo.FILTER_NEAREST)
                        except Exception:
                            pass
                        cr.paint()
                        cr.restore()
                    return
                except Exception:
                    pass
        if not self._logged_python_bars_img:
            logger.info("Bars image-generation path: Python fallback")
            self._logged_python_bars_img = True
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

    def _draw_stereo_mirror_bars(self, cr, width, height, gain, gradient, bar_w, spacing):
        mid = height * 0.5
        left_bins = self._resample_channel_heights(self.left_channel_heights, self.num_bars)
        right_bins = self._resample_channel_heights(self.right_channel_heights, self.num_bars)
        top_src = self._color_from_gradient(self._theme_cfg["gradient"], 0.82)
        bottom_src = self._color_from_gradient(self._theme_cfg["gradient"], 0.12)
        top_col = (top_src[0], top_src[1], top_src[2], min(0.98, max(0.76, top_src[3])))
        bottom_col = (bottom_src[0], bottom_src[1], bottom_src[2], min(0.98, max(0.76, bottom_src[3])))
        for i in range(self.num_bars):
            x = i * (bar_w + spacing)

            lh = max(0.0, min(left_bins[i] * gain, 1.0))
            if lh > 0.001:
                h = max(1.0, min(lh * height * 0.48, mid))
                cr.set_source_rgba(*top_col)
                cr.rectangle(x, mid - h, bar_w, h)
                cr.fill()

            rh = max(0.0, min(right_bins[i] * gain, 1.0))
            if rh > 0.001:
                h = max(1.0, min(rh * height * 0.48, mid))
                cr.set_source_rgba(*bottom_col)
                cr.rectangle(x, mid, bar_w, h)
                cr.fill()

    def _draw_lissajous(self, cr, width, height, gain, grad):
        point_count = max(24, min(96, self.num_bars))
        left = self._resample_channel_heights(self.left_channel_heights, point_count)
        right = self._resample_channel_heights(self.right_channel_heights, point_count)
        if not left or not right:
            return

        cx = width * 0.5
        cy = height * 0.54
        scope_w = width * 0.36
        scope_h = height * 0.34
        left_avg = sum(left) / float(max(1, len(left)))
        right_avg = sum(right) / float(max(1, len(right)))

        bg = cairo.RadialGradient(cx, cy, min(width, height) * 0.05, cx, cy, max(width, height) * 0.62)
        c0 = self._color_from_gradient(grad, 0.82)
        c1 = self._color_from_gradient(grad, 0.18)
        bg.add_color_stop_rgba(0.0, c1[0] * 0.08, c1[1] * 0.08, c1[2] * 0.08, 0.98)
        bg.add_color_stop_rgba(1.0, c0[0] * 0.03, c0[1] * 0.03, c0[2] * 0.05, 0.98)
        cr.set_source(bg)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Scope guides.
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
        cr.set_line_width(1.0)
        cr.move_to(cx - scope_w, cy)
        cr.line_to(cx + scope_w, cy)
        cr.stroke()
        cr.move_to(cx, cy - scope_h)
        cr.line_to(cx, cy + scope_h)
        cr.stroke()
        cr.rectangle(cx - scope_w, cy - scope_h, scope_w * 2.0, scope_h * 2.0)
        cr.stroke()

        pts = []
        for i in range(point_count):
            lx = (left[i] - left_avg) * 2.7
            ry = (right[i] - right_avg) * 2.7
            x = cx + (lx * scope_w)
            y = cy - (ry * scope_h)
            pts.append((x, y))

        if len(pts) < 2:
            return

        glow_col = self._color_from_gradient(grad, 0.34)
        cr.new_path()
        cr.move_to(pts[0][0], pts[0][1])
        for x, y in pts[1:]:
            cr.line_to(x, y)
        cr.set_source_rgba(glow_col[0], glow_col[1], glow_col[2], 0.16)
        cr.set_line_width(5.6)
        cr.stroke_preserve()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.14)
        cr.set_line_width(2.2)
        cr.stroke_preserve()

        line_grad = cairo.LinearGradient(cx - scope_w, cy - scope_h, cx + scope_w, cy + scope_h)
        line_grad.add_color_stop_rgba(0.0, c0[0], c0[1], c0[2], 0.82)
        line_grad.add_color_stop_rgba(1.0, c1[0], c1[1], c1[2], 0.82)
        cr.set_source(line_grad)
        cr.set_line_width(1.2)
        cr.stroke()

        # Hot current point.
        px, py = pts[-1]
        cr.set_source_rgba(c1[0], c1[1], c1[2], 0.22)
        cr.arc(px, py, 7.0, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.72)
        cr.arc(px, py, 2.4, 0, 2 * math.pi)
        cr.fill()

    def _draw_stereo_scope(self, cr, width, height, gain, grad):
        row_count = max(12, min(28, self.num_bars))
        left_bins = self._resample_channel_heights(self.left_channel_heights, row_count)
        right_bins = self._resample_channel_heights(self.right_channel_heights, row_count)
        left_peaks = self._resample_channel_heights(self.left_peak_holds, row_count)
        right_peaks = self._resample_channel_heights(self.right_peak_holds, row_count)
        if not left_bins or not right_bins:
            return

        cx = width * 0.5
        top = height * 0.10
        bottom = height * 0.94
        scope_h = max(40.0, bottom - top)
        gap = 2.0
        row_h = max(2.0, (scope_h - ((row_count - 1) * gap)) / float(row_count))
        max_half_w = width * 0.42
        stereo_rb = self.theme_name == "Stereo Red Blue"
        if stereo_rb:
            left_col = (0.04, 0.22, 0.88, 0.94)
            right_col = (0.90, 0.04, 0.08, 0.94)
        else:
            lc = self._color_from_gradient(grad, 0.82)
            rc = self._color_from_gradient(grad, 0.12)
            left_col = (lc[0], lc[1], lc[2], min(0.98, max(0.78, lc[3])))
            right_col = (rc[0], rc[1], rc[2], min(0.98, max(0.78, rc[3])))

        bg = cairo.LinearGradient(0, top, 0, bottom)
        bg.add_color_stop_rgba(0.0, left_col[0] * 0.06, left_col[1] * 0.06, left_col[2] * 0.08, 0.98)
        bg.add_color_stop_rgba(1.0, right_col[0] * 0.06, right_col[1] * 0.06, right_col[2] * 0.08, 0.98)
        cr.set_source(bg)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Analyzer guides.
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
        cr.set_line_width(1.0)
        for frac in (0.25, 0.5, 0.75):
            x = width * frac
            cr.move_to(x, top)
            cr.line_to(x, bottom)
            cr.stroke()
        cr.move_to(cx, top)
        cr.line_to(cx, bottom)
        cr.stroke()

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11.0)
        cr.set_source_rgba(left_col[0], left_col[1], left_col[2], 0.78)
        cr.move_to(cx - 24.0, top - 8.0)
        cr.show_text("L")
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.52)
        cr.move_to(cx - 3.5, top - 8.0)
        cr.show_text("C")
        cr.set_source_rgba(right_col[0], right_col[1], right_col[2], 0.78)
        cr.move_to(cx + 14.0, top - 8.0)
        cr.show_text("R")

        left_avg = sum(left_bins) / float(max(1, len(left_bins)))
        right_avg = sum(right_bins) / float(max(1, len(right_bins)))
        balance = 0.0
        if (left_avg + right_avg) > 1e-6:
            balance = (right_avg - left_avg) / max(1e-6, left_avg + right_avg)
        marker_y = top - 4.0
        marker_x = cx + (balance * (width * 0.12))
        marker_col = right_col if balance >= 0.0 else left_col
        cr.set_source_rgba(marker_col[0], marker_col[1], marker_col[2], 0.20)
        cr.arc(marker_x, marker_y, 6.0, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.68)
        cr.arc(marker_x, marker_y, 2.1, 0, 2 * math.pi)
        cr.fill()

        # Average level rulers.
        avg_y = top + 10.0
        left_avg_w = max_half_w * max(0.0, min(left_avg * gain, 1.0))
        right_avg_w = max_half_w * max(0.0, min(right_avg * gain, 1.0))
        cr.set_source_rgba(left_col[0], left_col[1], left_col[2], 0.44)
        cr.set_line_width(2.0)
        cr.move_to(cx - left_avg_w, avg_y)
        cr.line_to(cx - 2.0, avg_y)
        cr.stroke()
        cr.set_source_rgba(right_col[0], right_col[1], right_col[2], 0.44)
        cr.move_to(cx + 2.0, avg_y)
        cr.line_to(cx + right_avg_w, avg_y)
        cr.stroke()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.20)
        cr.set_line_width(1.0)
        for frac in (0.25, 0.5, 0.75, 1.0):
            lx = cx - (max_half_w * frac)
            rx = cx + (max_half_w * frac)
            cr.move_to(lx, avg_y - 4.0)
            cr.line_to(lx, avg_y + 4.0)
            cr.move_to(rx, avg_y - 4.0)
            cr.line_to(rx, avg_y + 4.0)
        cr.stroke()

        # Numeric readouts.
        left_txt = f"{int(max(0.0, min(1.0, left_avg * gain)) * 100):02d}"
        right_txt = f"{int(max(0.0, min(1.0, right_avg * gain)) * 100):02d}"
        cr.set_font_size(10.0)
        cr.set_source_rgba(left_col[0], left_col[1], left_col[2], 0.74)
        cr.move_to(cx - max_half_w - 6.0, avg_y + 3.5)
        cr.show_text(left_txt)
        rt_ext = cr.text_extents(right_txt)
        cr.set_source_rgba(right_col[0], right_col[1], right_col[2], 0.74)
        cr.move_to(cx + max_half_w + 6.0 - rt_ext.width, avg_y + 3.5)
        cr.show_text(right_txt)

        for row in range(row_count):
            idx = row_count - 1 - row
            y = bottom - ((row + 1) * row_h) - (row * gap)
            lh = max(0.0, min(left_bins[idx] * gain, 1.0))
            rh = max(0.0, min(right_bins[idx] * gain, 1.0))
            lpeak = max(0.0, min(left_peaks[idx] * gain, 1.0))
            rpeak = max(0.0, min(right_peaks[idx] * gain, 1.0))
            if lh > 0.001:
                w = max(1.0, min(max_half_w, lh * max_half_w))
                cr.set_source_rgba(*left_col)
                cr.rectangle(cx - w, y, w - 1.0, row_h)
                cr.fill_preserve()
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.10 + (0.12 * lh))
                cr.set_line_width(0.8)
                cr.stroke()
                if lpeak > 0.001:
                    px = cx - min(max_half_w, lpeak * max_half_w)
                    cr.set_source_rgba(1.0, 1.0, 1.0, 0.56)
                    cr.set_line_width(1.0)
                    cr.move_to(px, y - 0.4)
                    cr.line_to(px, y + row_h + 0.4)
                    cr.stroke()
            if rh > 0.001:
                w = max(1.0, min(max_half_w, rh * max_half_w))
                cr.set_source_rgba(*right_col)
                cr.rectangle(cx + 1.0, y, w - 1.0, row_h)
                cr.fill_preserve()
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.10 + (0.12 * rh))
                cr.set_line_width(0.8)
                cr.stroke()
                if rpeak > 0.001:
                    px = cx + min(max_half_w, rpeak * max_half_w)
                    cr.set_source_rgba(1.0, 1.0, 1.0, 0.56)
                    cr.set_line_width(1.0)
                    cr.move_to(px, y - 0.4)
                    cr.line_to(px, y + row_h + 0.4)
                    cr.stroke()

        # Outer frame accents for a hardware analyzer feel.
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.06)
        cr.set_line_width(1.0)
        cr.rectangle(cx - max_half_w, top, max_half_w * 2.0, scope_h)
        cr.stroke()

    def _draw_balance_wave(self, cr, width, height, gain, grad):
        point_count = max(24, min(96, self.num_bars))
        left = self._resample_channel_heights(self.left_channel_heights, point_count)
        right = self._resample_channel_heights(self.right_channel_heights, point_count)
        if not left or not right:
            return

        cx = width * 0.5
        top_mid = height * 0.34
        bot_mid = height * 0.70
        amp = height * 0.20
        left_col = self._color_from_gradient(grad, 0.82)
        right_col = self._color_from_gradient(grad, 0.12)

        cr.set_source_rgba(1.0, 1.0, 1.0, 0.06)
        cr.set_line_width(1.0)
        cr.move_to(0, top_mid)
        cr.line_to(width, top_mid)
        cr.move_to(0, bot_mid)
        cr.line_to(width, bot_mid)
        cr.stroke()

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11.0)
        cr.set_source_rgba(left_col[0], left_col[1], left_col[2], 0.78)
        cr.move_to(14.0, top_mid - amp - 8.0)
        cr.show_text("L")
        cr.set_source_rgba(right_col[0], right_col[1], right_col[2], 0.78)
        cr.move_to(14.0, bot_mid - amp - 8.0)
        cr.show_text("R")

        def _points(vals, mid_y):
            pts = []
            step_x = width / float(max(1, point_count - 1))
            for i in range(point_count):
                lvl = max(0.0, min(vals[i] * gain, 1.0))
                x = i * step_x
                y = mid_y - ((lvl - 0.5) * 2.0 * amp)
                pts.append((x, y))
            return pts

        left_pts = _points(left, top_mid)
        right_pts = _points(right, bot_mid)

        for pts, col, fill_alpha in (
            (left_pts, left_col, 0.18),
            (right_pts, right_col, 0.18),
        ):
            fill = cairo.LinearGradient(0, min(y for _, y in pts), 0, max(y for _, y in pts))
            fill.add_color_stop_rgba(0.0, col[0], col[1], col[2], fill_alpha)
            fill.add_color_stop_rgba(1.0, col[0], col[1], col[2], 0.02)
            cr.new_path()
            cr.move_to(pts[0][0], pts[0][1])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            base_y = top_mid if pts is left_pts else bot_mid
            cr.line_to(width, base_y)
            cr.line_to(0, base_y)
            cr.close_path()
            cr.set_source(fill)
            cr.fill()

            cr.new_path()
            cr.move_to(pts[0][0], pts[0][1])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.12)
            cr.set_line_width(2.2)
            cr.stroke_preserve()
            cr.set_source_rgba(col[0], col[1], col[2], 0.90)
            cr.set_line_width(1.2)
            cr.stroke()

        # Current-point dots.
        for pts, col in ((left_pts, left_col), (right_pts, right_col)):
            px, py = pts[-1]
            cr.set_source_rgba(col[0], col[1], col[2], 0.20)
            cr.arc(px, py, 6.0, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.70)
            cr.arc(px, py, 2.0, 0, 2 * math.pi)
            cr.fill()

    def _draw_center_side(self, cr, width, height, gain, grad):
        point_count = max(24, min(96, self.num_bars))
        left = self._resample_channel_heights(self.left_channel_heights, point_count)
        right = self._resample_channel_heights(self.right_channel_heights, point_count)
        if not left or not right:
            return

        mid_vals = []
        side_vals = []
        for i in range(point_count):
            lv = max(0.0, min(left[i], 1.0))
            rv = max(0.0, min(right[i], 1.0))
            mid_vals.append((lv + rv) * 0.5)
            side_vals.append(abs(lv - rv))

        top_mid = height * 0.33
        bot_mid = height * 0.72
        amp = height * 0.18
        mid_col = self._color_from_gradient(grad, 0.72)
        side_col = self._color_from_gradient(grad, 0.14)

        bg = cairo.LinearGradient(0, 0, 0, height)
        bg.add_color_stop_rgba(0.0, mid_col[0] * 0.05, mid_col[1] * 0.05, mid_col[2] * 0.07, 0.98)
        bg.add_color_stop_rgba(1.0, side_col[0] * 0.05, side_col[1] * 0.05, side_col[2] * 0.07, 0.98)
        cr.set_source(bg)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        cr.set_source_rgba(1.0, 1.0, 1.0, 0.06)
        cr.set_line_width(1.0)
        cr.move_to(0, top_mid)
        cr.line_to(width, top_mid)
        cr.move_to(0, bot_mid)
        cr.line_to(width, bot_mid)
        cr.stroke()

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11.0)
        cr.set_source_rgba(mid_col[0], mid_col[1], mid_col[2], 0.76)
        cr.move_to(14.0, top_mid - amp - 8.0)
        cr.show_text("MID")
        cr.set_source_rgba(side_col[0], side_col[1], side_col[2], 0.76)
        cr.move_to(14.0, bot_mid - amp - 8.0)
        cr.show_text("SIDE")

        def _points(vals, mid_y):
            pts = []
            step_x = width / float(max(1, point_count - 1))
            for i in range(point_count):
                lvl = max(0.0, min(vals[i] * gain, 1.0))
                x = i * step_x
                y = mid_y - (lvl * amp)
                pts.append((x, y))
            return pts

        mid_pts = _points(mid_vals, top_mid)
        side_pts = _points(side_vals, bot_mid)

        for pts, mid_y, col in (
            (mid_pts, top_mid, mid_col),
            (side_pts, bot_mid, side_col),
        ):
            fill = cairo.LinearGradient(0, min(y for _, y in pts), 0, mid_y)
            fill.add_color_stop_rgba(0.0, col[0], col[1], col[2], 0.22)
            fill.add_color_stop_rgba(1.0, col[0], col[1], col[2], 0.02)
            cr.new_path()
            cr.move_to(pts[0][0], pts[0][1])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            cr.line_to(width, mid_y)
            cr.line_to(0, mid_y)
            cr.close_path()
            cr.set_source(fill)
            cr.fill()

            cr.new_path()
            cr.move_to(pts[0][0], pts[0][1])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.10)
            cr.set_line_width(2.0)
            cr.stroke_preserve()
            cr.set_source_rgba(col[0], col[1], col[2], 0.92)
            cr.set_line_width(1.2)
            cr.stroke()

    def _draw_phase_flower(self, cr, width, height, gain, grad):
        point_count = max(24, min(96, self.num_bars))
        left = self._resample_channel_heights(self.left_channel_heights, point_count)
        right = self._resample_channel_heights(self.right_channel_heights, point_count)
        if not left or not right:
            return

        cx = width * 0.5
        cy = height * 0.54
        min_side = min(width, height)
        base_r = min_side * 0.04
        max_rx = width * 0.40
        max_ry = height * 0.36
        bass = max(0.0, min(1.0, self.bass_level * 1.35))
        c0 = self._color_from_gradient(grad, 0.82)
        c1 = self._color_from_gradient(grad, 0.18)

        bg = cairo.RadialGradient(cx, cy, min_side * 0.06, cx, cy, max(max_rx, max_ry) * 1.25)
        bg.add_color_stop_rgba(0.0, c1[0] * 0.08, c1[1] * 0.08, c1[2] * 0.10, 0.98)
        bg.add_color_stop_rgba(1.0, c0[0] * 0.03, c0[1] * 0.03, c0[2] * 0.05, 0.98)
        cr.set_source(bg)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Polar guides.
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.05)
        cr.set_line_width(1.0)
        for frac in (0.32, 0.58, 0.84):
            cr.save()
            cr.translate(cx, cy)
            cr.scale(base_r + ((max_rx - base_r) * frac), base_r + ((max_ry - base_r) * frac))
            cr.arc(0, 0, 1.0, 0, 2 * math.pi)
            cr.restore()
            cr.stroke()

        pts = []
        for i in range(point_count):
            lv = max(0.0, min(left[i] * gain, 1.0))
            rv = max(0.0, min(right[i] * gain, 1.0))
            t = i / float(max(1, point_count - 1))
            diff = rv - lv
            side = abs(diff)
            mono = (lv + rv) * 0.5
            side_emph = pow(min(1.0, side * 4.8), 0.68)
            angle = (t * (2.0 * math.pi * 3.2)) + (self.phase * 0.45) + (diff * 2.8) + (math.sin((t * 9.0) + self.phase) * side_emph * 0.28)
            spread = 0.12 + (mono * 0.18) + (side_emph * 0.94)
            rx = base_r + ((max_rx - base_r) * spread)
            ry = base_r + ((max_ry - base_r) * spread)
            x = cx + (math.cos(angle) * rx)
            y = cy + (math.sin(angle) * ry)
            pts.append((x, y, side_emph, t))

        if len(pts) < 2:
            return

        # Petal path.
        cr.new_path()
        cr.move_to(pts[0][0], pts[0][1])
        for x, y, _d, _t in pts[1:]:
            cr.line_to(x, y)
        cr.close_path()
        fill = cairo.RadialGradient(cx, cy, base_r * 0.25, cx, cy, max(max_rx, max_ry))
        fill.add_color_stop_rgba(0.0, c1[0], c1[1], c1[2], 0.16 + (0.08 * bass))
        fill.add_color_stop_rgba(1.0, c0[0], c0[1], c0[2], 0.03)
        cr.set_source(fill)
        cr.fill_preserve()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
        cr.set_line_width(2.2)
        cr.stroke_preserve()
        line = cairo.LinearGradient(cx - max_rx, cy - max_ry, cx + max_rx, cy + max_ry)
        line.add_color_stop_rgba(0.0, c0[0], c0[1], c0[2], 0.80)
        line.add_color_stop_rgba(1.0, c1[0], c1[1], c1[2], 0.80)
        cr.set_source(line)
        cr.set_line_width(1.2)
        cr.stroke()

        # Accent dots on high-difference points.
        for x, y, diff_abs, t in pts[:: max(1, point_count // 14)]:
            if diff_abs < 0.02:
                continue
            col = self._color_from_gradient(grad, t)
            r = 1.2 + (diff_abs * 4.0)
            cr.set_source_rgba(col[0], col[1], col[2], 0.18 + (diff_abs * 0.24))
            cr.arc(x, y, r * 2.0, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.58)
            cr.arc(x, y, r * 0.55, 0, 2 * math.pi)
            cr.fill()

        # Core emitter.
        core = cairo.RadialGradient(cx, cy, 0, cx, cy, base_r * 1.8)
        core.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.52 + (0.12 * bass))
        core.add_color_stop_rgba(0.38, c1[0], c1[1], c1[2], 0.26 + (0.10 * bass))
        core.add_color_stop_rgba(1.0, c1[0], c1[1], c1[2], 0.0)
        cr.set_source(core)
        cr.arc(cx, cy, base_r * 1.8, 0, 2 * math.pi)
        cr.fill()

    def _draw_stereo_meter(self, cr, width, height, gain, grad):
        left_rms = math.sqrt(
            sum(v * v for v in self.left_channel_heights) / float(max(1, len(self.left_channel_heights)))
        )
        right_rms = math.sqrt(
            sum(v * v for v in self.right_channel_heights) / float(max(1, len(self.right_channel_heights)))
        )
        left_peak = max(self.left_peak_holds) if self.left_peak_holds else 0.0
        right_peak = max(self.right_peak_holds) if self.right_peak_holds else 0.0
        left_lvl = max(0.0, min(pow(left_rms * gain, 0.82) * 1.35, 1.0))
        right_lvl = max(0.0, min(pow(right_rms * gain, 0.82) * 1.35, 1.0))
        left_peak = max(0.0, min(left_peak * gain, 1.0))
        right_peak = max(0.0, min(right_peak * gain, 1.0))

        top = height * 0.12
        bottom = height * 0.90
        meter_h = max(40.0, bottom - top)
        meter_w = min(64.0, width * 0.10)
        gap = min(72.0, width * 0.10)
        cx = width * 0.5
        left_x = cx - gap - meter_w
        right_x = cx + gap
        left_col = self._color_from_gradient(grad, 0.82)
        right_col = self._color_from_gradient(grad, 0.12)
        seg_count = 18
        seg_gap = 3.0
        seg_h = max(2.0, (meter_h - ((seg_count - 1) * seg_gap)) / float(seg_count))

        bg = cairo.LinearGradient(0, 0, 0, height)
        bg.add_color_stop_rgba(0.0, left_col[0] * 0.05, left_col[1] * 0.05, left_col[2] * 0.07, 0.98)
        bg.add_color_stop_rgba(1.0, right_col[0] * 0.05, right_col[1] * 0.05, right_col[2] * 0.07, 0.98)
        cr.set_source(bg)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(12.0)
        cr.set_source_rgba(left_col[0], left_col[1], left_col[2], 0.82)
        cr.move_to(left_x + 6.0, top - 10.0)
        cr.show_text("L")
        cr.set_source_rgba(right_col[0], right_col[1], right_col[2], 0.82)
        cr.move_to(right_x + 6.0, top - 10.0)
        cr.show_text("R")

        def _draw_meter(x, lvl, peak, color):
            # Meter frame.
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
            cr.set_line_width(1.0)
            cr.rectangle(x, top, meter_w, meter_h)
            cr.stroke()

            active_segments = int(round(lvl * seg_count))
            for si in range(seg_count):
                y = bottom - ((si + 1) * seg_h) - (si * seg_gap)
                frac = (si + 1) / float(seg_count)
                seg_alpha = 0.10
                if si < active_segments:
                    seg_alpha = 0.22 + (0.64 * frac)
                cr.set_source_rgba(color[0], color[1], color[2], seg_alpha)
                cr.rectangle(x + 3.0, y, meter_w - 6.0, seg_h)
                cr.fill()

            peak_y = bottom - (peak * meter_h)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.74)
            cr.set_line_width(1.2)
            cr.move_to(x + 2.0, peak_y)
            cr.line_to(x + meter_w - 2.0, peak_y)
            cr.stroke()

        _draw_meter(left_x, left_lvl, left_peak, left_col)
        _draw_meter(right_x, right_lvl, right_peak, right_col)

        # Center balance ball.
        balance = 0.0
        if (left_lvl + right_lvl) > 1e-6:
            balance = (right_lvl - left_lvl) / max(1e-6, left_lvl + right_lvl)
        meter_y = top + (meter_h * 0.18)
        meter_wid = min(120.0, width * 0.18)
        meter_x = cx - (meter_wid * 0.5)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.10)
        cr.set_line_width(1.0)
        cr.move_to(meter_x, meter_y)
        cr.line_to(meter_x + meter_wid, meter_y)
        cr.stroke()
        mark_x = meter_x + ((balance + 1.0) * 0.5 * meter_wid)
        mark_col = right_col if balance >= 0.0 else left_col
        cr.set_source_rgba(mark_col[0], mark_col[1], mark_col[2], 0.24)
        cr.arc(mark_x, meter_y, 6.0, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.70)
        cr.arc(mark_x, meter_y, 2.2, 0, 2 * math.pi)
        cr.fill()

    def _draw_dual_fall(self, cr, width, height, gain, grad):
        if not self.left_log_heat_history or not self.right_log_heat_history:
            return

        cols = max(1, min(len(self.left_log_heat_history), int(max(1, width // 5.0))))
        left_frames = self.left_log_heat_history[-cols:]
        right_frames = self.right_log_heat_history[-cols:]
        bins = len(left_frames[-1]) if left_frames and left_frames[-1] else max(8, min(self.num_bars, 32))
        gap_rows = 6
        img_w = cols
        img_h = (bins * 2) + gap_rows
        top_col = self._color_from_gradient(grad, 0.82)
        bottom_col = self._color_from_gradient(grad, 0.12)
        bg_top = (
            int(max(0, min(255, round(top_col[0] * 0.06 * 255)))),
            int(max(0, min(255, round(top_col[1] * 0.06 * 255)))),
            int(max(0, min(255, round(top_col[2] * 0.08 * 255)))),
        )
        bg_bot = (
            int(max(0, min(255, round(bottom_col[0] * 0.06 * 255)))),
            int(max(0, min(255, round(bottom_col[1] * 0.06 * 255)))),
            int(max(0, min(255, round(bottom_col[2] * 0.08 * 255)))),
        )
        top_rgb = (
            int(max(0, min(255, round(top_col[0] * 255)))),
            int(max(0, min(255, round(top_col[1] * 255)))),
            int(max(0, min(255, round(top_col[2] * 255)))),
        )
        bottom_rgb = (
            int(max(0, min(255, round(bottom_col[0] * 255)))),
            int(max(0, min(255, round(bottom_col[1] * 255)))),
            int(max(0, min(255, round(bottom_col[2] * 255)))),
        )

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, img_w, img_h)
        data = surface.get_data()
        stride = surface.get_stride()

        for y in range(img_h):
            bg = bg_top if y < bins else bg_bot
            row = y * stride
            for x in range(img_w):
                off = row + (x * 4)
                data[off + 0] = bg[2]
                data[off + 1] = bg[1]
                data[off + 2] = bg[0]
                data[off + 3] = 255

        def _blend_pixel(x, y, color_rgb, base_rgb, alpha):
            a = max(0.0, min(1.0, alpha))
            row = y * stride
            off = row + (x * 4)
            rr = int(base_rgb[0] + ((color_rgb[0] - base_rgb[0]) * a))
            gg = int(base_rgb[1] + ((color_rgb[1] - base_rgb[1]) * a))
            bb = int(base_rgb[2] + ((color_rgb[2] - base_rgb[2]) * a))
            data[off + 0] = bb
            data[off + 1] = gg
            data[off + 2] = rr
            data[off + 3] = 255

        def _paint_band(frames, y_base, color_rgb, base_rgb):
            frame_count = len(frames)
            for col_idx, frame in enumerate(frames):
                age = (col_idx + 1) / float(max(1, frame_count))
                alpha_mul = 0.24 + (0.76 * age)
                x = col_idx
                for bi, raw in enumerate(frame):
                    lvl = max(0.0, min(raw * gain, 1.0))
                    if lvl < 0.015:
                        continue
                    y = y_base + (bins - 1 - bi)
                    _blend_pixel(x, y, color_rgb, base_rgb, min(0.96, (0.08 + (lvl * 0.88)) * alpha_mul))

        _paint_band(left_frames, 0, top_rgb, bg_top)
        _paint_band(right_frames, bins + gap_rows, bottom_rgb, bg_bot)
        surface.mark_dirty()

        cr.save()
        cr.scale(width / float(max(1, img_w)), height / float(max(1, img_h)))
        cr.set_source_surface(surface, 0.0, 0.0)
        src = cr.get_source()
        try:
            src.set_filter(cairo.FILTER_NEAREST)
        except Exception:
            pass
        cr.paint()
        cr.restore()

        gap_y = height * ((bins + (gap_rows * 0.5)) / float(max(1, img_h)))
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.06)
        cr.set_line_width(1.0)
        cr.move_to(0, gap_y)
        cr.line_to(width, gap_y)
        cr.stroke()

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11.0)
        cr.set_source_rgba(top_col[0], top_col[1], top_col[2], 0.80)
        cr.move_to(14.0, 18.0)
        cr.show_text("L")
        cr.set_source_rgba(bottom_col[0], bottom_col[1], bottom_col[2], 0.80)
        cr.move_to(14.0, gap_y + 18.0)
        cr.show_text("R")

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
            "Gentle": 0.56,
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
        left_bins = self._resample_channel_heights(self.left_channel_heights, bars_per_side)
        right_bins = self._resample_channel_heights(self.right_channel_heights, bars_per_side)
        left_avg = (sum(left_bins) / float(max(1, len(left_bins)))) if left_bins else 0.0
        right_avg = (sum(right_bins) / float(max(1, len(right_bins)))) if right_bins else 0.0
        stereo_rb = self.theme_name == "Stereo Red Blue"

        # Center split guide + balance indicator so the stereo image reads clearly.
        mid_x = width * 0.5
        guide_top = height * 0.12
        guide_bot = height * 0.94
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
        cr.set_line_width(1.0)
        cr.move_to(mid_x, guide_top)
        cr.line_to(mid_x, guide_bot)
        cr.stroke()

        # L / R labels like a channel analyzer.
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11.0)
        cr.set_source_rgba(0.80, 0.92, 1.0, 0.70)
        text_ext = cr.text_extents("L")
        cr.move_to((width * 0.5) - 18.0 - text_ext.width, guide_top - 6.0)
        cr.show_text("L")
        cr.set_source_rgba(1.0, 0.88, 0.66, 0.70)
        cr.move_to((width * 0.5) + 18.0, guide_top - 6.0)
        cr.show_text("R")

        balance = 0.0
        if (left_avg + right_avg) > 1e-6:
            balance = (right_avg - left_avg) / max(1e-6, left_avg + right_avg)
        meter_w = min(120.0, width * 0.16)
        meter_y = height * 0.10
        meter_x = mid_x - (meter_w * 0.5)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
        cr.set_line_width(1.0)
        cr.move_to(meter_x, meter_y)
        cr.line_to(meter_x + meter_w, meter_y)
        cr.stroke()
        cr.move_to(mid_x, meter_y - 5.0)
        cr.line_to(mid_x, meter_y + 5.0)
        cr.stroke()
        marker_x = meter_x + ((balance + 1.0) * 0.5 * meter_w)
        if stereo_rb:
            marker_col = (0.86, 0.04, 0.08, 1.0) if balance >= 0.0 else (0.04, 0.22, 0.88, 1.0)
        else:
            marker_col = self._color_from_gradient(grad, 0.18 if balance >= 0.0 else 0.82)
        cr.set_source_rgba(marker_col[0], marker_col[1], marker_col[2], 0.22)
        cr.arc(marker_x, meter_y, 6.0, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.58)
        cr.arc(marker_x, meter_y, 2.3, 0, 2 * math.pi)
        cr.fill()

        for i in range(bars_per_side):
            lh = max(0.0, min(left_bins[i] * gain, 1.0))
            rh = max(0.0, min(right_bins[i] * gain, 1.0))
            if lh > 0.001:
                h = max(1.0, min(lh * max_h, height))
                x = i * (left_w + spacing)
                y = height - h
                tt = i / float(max(1, bars_per_side - 1))
                if stereo_rb:
                    r = 0.04 + (0.03 * (1.0 - tt))
                    g = 0.18 + (0.06 * (1.0 - tt))
                    b = 0.82 + (0.10 * (1.0 - tt))
                    a = 0.96
                else:
                    r, g, b, a = self._color_from_gradient(grad, 0.64 - (0.18 * tt))
                    r = min(1.0, r * 1.06)
                    g = min(1.0, g * 1.08)
                    b = min(1.0, b * 1.12)
                cr.set_source_rgba(r, g, b, min(1.0, 0.20 + (a * 1.04)))
                cr.rectangle(x, y, left_w, h)
                cr.fill_preserve()
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.10 + (0.14 * lh))
                cr.set_line_width(0.8)
                cr.stroke()
            if rh > 0.001:
                h = max(1.0, min(rh * max_h, height))
                x = half_w + inner_gap + i * (right_w + spacing)
                y = height - h
                tt = i / float(max(1, bars_per_side - 1))
                if stereo_rb:
                    r = 0.86 + (0.08 * (1.0 - tt))
                    g = 0.04 + (0.04 * tt)
                    b = 0.08 + (0.04 * tt)
                    a = 0.96
                else:
                    r, g, b, a = self._color_from_gradient(grad, 0.06 + (0.26 * tt))
                cr.set_source_rgba(r, g, b, min(1.0, a * 0.96))
                cr.rectangle(x, y, right_w, h)
                cr.fill_preserve()
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.08 + (0.12 * rh))
                cr.set_line_width(0.8)
                cr.stroke()

    def _draw_particle_burst(self, cr, width, height, gain, grad):
        n = self.num_bars
        if n <= 0:
            return
        cx = width * 0.5
        cy = height * 0.5
        bass = max(0.0, min(1.0, self.bass_level * 1.35))
        min_side = min(width, height)
        hot = self._color_from_gradient(grad, 0.15)
        mid = self._color_from_gradient(grad, 0.48)
        cool = self._color_from_gradient(grad, 0.82)

        # Atmosphere fill so the whole canvas carries energy, not just the center.
        bg = cairo.LinearGradient(0, 0, 0, height)
        bg.add_color_stop_rgba(0.0, cool[0] * 0.04, cool[1] * 0.04, cool[2] * 0.06, 0.96)
        bg.add_color_stop_rgba(0.55, mid[0] * 0.03, mid[1] * 0.03, mid[2] * 0.04, 0.97)
        bg.add_color_stop_rgba(1.0, hot[0] * 0.03, hot[1] * 0.03, hot[2] * 0.03, 0.98)
        cr.set_source(bg)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Wide ambient haze.
        haze_r = min_side * (0.52 + (bass * 0.10))
        haze = cairo.RadialGradient(cx, cy, haze_r * 0.08, cx, cy, haze_r)
        haze.add_color_stop_rgba(0.0, hot[0], hot[1], hot[2], 0.08 + (0.05 * bass))
        haze.add_color_stop_rgba(0.58, mid[0], mid[1], mid[2], 0.035)
        haze.add_color_stop_rgba(1.0, cool[0], cool[1], cool[2], 0.0)
        cr.set_source(haze)
        cr.arc(cx, cy, haze_r, 0, 2 * math.pi)
        cr.fill()

        # Faint energy rings across the background.
        ring_count = 3
        for ridx in range(ring_count):
            rr = min_side * (0.18 + (ridx * 0.16) + (0.015 * math.sin((self.phase * 1.9) + ridx)))
            cr.set_source_rgba(mid[0], mid[1], mid[2], 0.035 - (ridx * 0.008) + (0.01 * bass))
            cr.set_line_width(max(0.8, 1.5 - (ridx * 0.2)))
            cr.arc(cx, cy, rr, 0, 2 * math.pi)
            cr.stroke()

        # Sparse ambient particles so the sides are not dead black.
        ambient_count = 18
        for i in range(ambient_count):
            ang = (i / float(ambient_count)) * (2.0 * math.pi) + (self.phase * (0.10 + ((i % 3) * 0.02)))
            dist = min_side * (0.24 + ((i % 7) * 0.08))
            px = cx + math.cos(ang) * dist
            py = cy + math.sin(ang * 1.13) * dist * 0.62
            pr = 0.9 + ((i % 4) * 0.35)
            alpha = 0.04 + ((i % 5) * 0.01) + (0.02 * bass)
            col = hot if (i % 2 == 0) else cool
            cr.set_source_rgba(col[0], col[1], col[2], alpha)
            cr.arc(px, py, pr, 0, 2 * math.pi)
            cr.fill()

        # Deep center bloom so the burst has a visible source, not just scattered dots.
        bloom_r = min_side * (0.11 + (bass * 0.08))
        bloom = cairo.RadialGradient(cx, cy, bloom_r * 0.18, cx, cy, bloom_r)
        bloom.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.22 + (0.16 * bass))
        bloom.add_color_stop_rgba(0.32, hot[0], hot[1], hot[2], 0.20 + (0.14 * bass))
        bloom.add_color_stop_rgba(1.0, mid[0], mid[1], mid[2], 0.0)
        cr.set_source(bloom)
        cr.arc(cx, cy, bloom_r, 0, 2 * math.pi)
        cr.fill()

        # Dual shockwave rings on stronger bass hits.
        if bass > 0.08:
            pulse_r = (height * 0.10) + (height * 0.26 * bass)
            ring = cairo.RadialGradient(cx, cy, pulse_r * 0.55, cx, cy, pulse_r)
            ring.add_color_stop_rgba(0.0, hot[0], hot[1], hot[2], 0.30 * bass)
            ring.add_color_stop_rgba(1.0, hot[0], hot[1], hot[2], 0.0)
            cr.set_source(ring)
            cr.arc(cx, cy, pulse_r, 0, 2 * math.pi)
            cr.fill()

            cr.set_source_rgba(hot[0], hot[1], hot[2], 0.20 * bass)
            cr.set_line_width(1.4 + (bass * 1.8))
            cr.arc(cx, cy, pulse_r * (1.08 + (0.04 * math.sin(self.phase * 3.2))), 0, 2 * math.pi)
            cr.stroke()

            cr.set_source_rgba(1.0, 1.0, 1.0, 0.10 * bass)
            cr.set_line_width(0.9 + (bass * 0.8))
            cr.arc(cx, cy, pulse_r * 0.84, 0, 2 * math.pi)
            cr.stroke()

        for i in range(n):
            lvl = max(0.0, min(self.current_heights[i] * gain, 1.0))
            if lvl < 0.02:
                continue
            base_angle = ((2.0 * math.pi) * (i / float(n))) + (self.phase * 0.52)
            base_dist = (height * 0.10) + (lvl * height * 0.48)
            r, g, b, a = self._color_from_gradient(grad, i / float(max(1, n - 1)))

            beam_start = min_side * (0.03 + (lvl * 0.03))
            beam_end = base_dist * (0.78 + (lvl * 0.16))
            sx = cx + math.cos(base_angle) * beam_start
            sy = cy + math.sin(base_angle) * beam_start * 0.92
            ex = cx + math.cos(base_angle) * beam_end
            ey = cy + math.sin(base_angle) * beam_end * 0.92

            # Main radial beam.
            cr.set_source_rgba(r, g, b, 0.10 + (0.18 * lvl) + (0.12 * bass))
            cr.set_line_width(0.8 + (lvl * 2.8))
            cr.move_to(sx, sy)
            cr.line_to(ex, ey)
            cr.stroke()

            # Hot white filament inside the beam.
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.05 + (0.14 * lvl))
            cr.set_line_width(max(0.6, 0.45 + (lvl * 1.1)))
            cr.move_to(sx, sy)
            cr.line_to(ex, ey)
            cr.stroke()

            # Spawn multiple sparks per bar to make burst richer.
            sparks = 2 + int(lvl * 4.0) + (1 if bass > 0.45 else 0)
            for s in range(sparks):
                jitter_a = (s - (sparks * 0.5)) * (0.055 + (0.03 * lvl))
                angle = base_angle + jitter_a
                dist = base_dist * (0.76 + (0.17 * s))
                px = cx + math.cos(angle) * dist
                py = cy + math.sin(angle) * dist * 0.90
                rad = 0.95 + (lvl * 2.6) - (s * 0.10)
                rad = max(0.65, rad)

                tail_len = (8.0 + (lvl * 18.0)) * (0.92 + (0.12 * s))
                tx = px - (math.cos(angle) * tail_len)
                ty = py - (math.sin(angle) * tail_len * 0.90)

                # Tapered shard behind the spark.
                cr.set_source_rgba(r, g, b, 0.08 + (a * 0.20))
                cr.set_line_width(max(0.6, rad * 0.92))
                cr.move_to(tx, ty)
                cr.line_to(px, py)
                cr.stroke()

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

                # Tiny outward fragment so the edge feels more explosive.
                frag_len = 4.0 + (lvl * 10.0)
                fx = px + (math.cos(angle) * frag_len)
                fy = py + (math.sin(angle) * frag_len * 0.90)
                cr.set_source_rgba(r, g, b, 0.18 + (a * 0.24))
                cr.set_line_width(max(0.5, rad * 0.48))
                cr.move_to(px, py)
                cr.line_to(fx, fy)
                cr.stroke()

        # Center hot core on top so everything radiates from a defined emitter.
        core_r = min_side * (0.018 + (bass * 0.014))
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.50 + (0.16 * bass))
        cr.arc(cx, cy, core_r, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(hot[0], hot[1], hot[2], 0.44 + (0.12 * bass))
        cr.arc(cx, cy, core_r * 1.9, 0, 2 * math.pi)
        cr.fill()

    def _draw_orbit(self, cr, width, height, gain, grad):
        bins = self._build_log_bins(self.current_heights, min(self.num_bars, 18))
        if not bins:
            return
        cx = width * 0.5
        cy = height * 0.5
        min_side = min(width, height)
        bass = max(0.0, min(1.0, self.bass_level * 1.30))
        hot = self._color_from_gradient(grad, 0.14)
        mid = self._color_from_gradient(grad, 0.46)
        cool = self._color_from_gradient(grad, 0.84)

        bg = cairo.RadialGradient(cx, cy, min_side * 0.08, cx, cy, min_side * 0.72)
        bg.add_color_stop_rgba(0.0, hot[0] * 0.12, hot[1] * 0.12, hot[2] * 0.12, 0.95)
        bg.add_color_stop_rgba(0.48, mid[0] * 0.08, mid[1] * 0.08, mid[2] * 0.10, 0.98)
        bg.add_color_stop_rgba(1.0, cool[0] * 0.03, cool[1] * 0.03, cool[2] * 0.05, 1.0)
        cr.set_source(bg)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        ring_count = min(8, len(bins))
        base_rx = width * 0.16
        gap_rx = width * 0.050
        base_ry = height * 0.11
        gap_ry = height * 0.034
        for i in range(ring_count):
            lvl = max(0.0, min(bins[i] * gain, 1.0))
            rx = base_rx + (i * gap_rx)
            ry = base_ry + (i * gap_ry)
            orbit_alpha = 0.05 + (0.015 * (1.0 - (i / float(max(1, ring_count - 1)))))
            cr.set_source_rgba(cool[0], cool[1], cool[2], orbit_alpha)
            cr.set_line_width(0.9 + (0.04 * i))
            cr.save()
            cr.translate(cx, cy)
            cr.scale(rx, ry)
            cr.arc(0, 0, 1.0, 0, 2 * math.pi)
            cr.restore()
            cr.stroke()

            if lvl < 0.015:
                continue
            direction = -1.0 if (i % 2) else 1.0
            sweep = 0.22 + (lvl * (1.10 + (0.16 * i)))
            start = (self.phase * (0.75 + (i * 0.07)) * direction) + (i * 0.78)
            end = start + (sweep * direction)
            cr.set_source_rgba(mid[0], mid[1], mid[2], 0.18 + (0.22 * lvl))
            cr.set_line_width(3.0 + (lvl * 5.0))
            cr.save()
            cr.translate(cx, cy)
            cr.scale(rx, ry)
            if direction > 0:
                cr.arc(0, 0, 1.0, start, end)
            else:
                cr.arc_negative(0, 0, 1.0, start, end)
            cr.restore()
            cr.stroke_preserve()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.08 + (0.14 * lvl))
            cr.set_line_width(1.0 + (lvl * 1.4))
            cr.stroke()

            node_angle = end
            nx = cx + (math.cos(node_angle) * rx)
            ny = cy + (math.sin(node_angle) * ry)
            node_r = 1.4 + (lvl * 3.4)
            cr.set_source_rgba(mid[0], mid[1], mid[2], 0.18 + (0.18 * lvl))
            cr.arc(nx, ny, node_r * 2.2, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.40 + (0.18 * lvl))
            cr.arc(nx, ny, node_r, 0, 2 * math.pi)
            cr.fill()

        spoke_count = min(len(bins), 10)
        for i in range(spoke_count):
            lvl = max(0.0, min(bins[-(i + 1)] * gain, 1.0))
            if lvl < 0.02:
                continue
            ang = (self.phase * 0.36) + (i * ((2.0 * math.pi) / float(max(1, spoke_count))))
            inner_rx = base_rx * 0.18
            inner_ry = base_ry * 0.18
            outer_rx = base_rx + ((ring_count - 1) * gap_rx * (0.82 + (0.36 * lvl)))
            outer_ry = base_ry + ((ring_count - 1) * gap_ry * (0.82 + (0.20 * lvl)))
            sx = cx + (math.cos(ang) * inner_rx)
            sy = cy + (math.sin(ang) * inner_ry)
            ex = cx + (math.cos(ang) * outer_rx)
            ey = cy + (math.sin(ang) * outer_ry)
            cr.set_source_rgba(hot[0], hot[1], hot[2], 0.04 + (0.12 * lvl) + (0.08 * bass))
            cr.set_line_width(0.8 + (lvl * 2.2))
            cr.move_to(sx, sy)
            cr.line_to(ex, ey)
            cr.stroke()

        core_r = min_side * (0.020 + (0.014 * bass))
        core = cairo.RadialGradient(cx, cy, 0, cx, cy, min_side * 0.11)
        core.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.68)
        core.add_color_stop_rgba(0.28, hot[0], hot[1], hot[2], 0.42 + (0.14 * bass))
        core.add_color_stop_rgba(1.0, hot[0], hot[1], hot[2], 0.0)
        cr.set_source(core)
        cr.arc(cx, cy, min_side * 0.11, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.72)
        cr.arc(cx, cy, core_r, 0, 2 * math.pi)
        cr.fill()

    def _draw_shards(self, cr, width, height, gain, grad):
        bins = self._build_log_bins(self.current_heights, min(self.num_bars, 40))
        if not bins:
            return
        cx = width * 0.5
        cy = height * 0.54
        min_side = min(width, height)
        bass = max(0.0, min(1.0, self.bass_level * 1.35))
        hot = self._color_from_gradient(grad, 0.12)
        mid = self._color_from_gradient(grad, 0.44)
        cool = self._color_from_gradient(grad, 0.84)

        bg = cairo.LinearGradient(0, 0, width, height)
        bg.add_color_stop_rgba(0.0, cool[0] * 0.05, cool[1] * 0.05, cool[2] * 0.08, 0.98)
        bg.add_color_stop_rgba(0.5, mid[0] * 0.04, mid[1] * 0.04, mid[2] * 0.05, 0.98)
        bg.add_color_stop_rgba(1.0, hot[0] * 0.05, hot[1] * 0.05, hot[2] * 0.04, 0.98)
        cr.set_source(bg)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        for i in range(10):
            streak_x = ((i + 0.5) / 10.0) * width
            swing = math.sin((self.phase * 0.22) + (i * 0.7)) * (width * 0.05)
            cr.set_source_rgba(cool[0], cool[1], cool[2], 0.025)
            cr.set_line_width(1.0)
            cr.move_to(streak_x + swing, 0)
            cr.line_to(streak_x - swing, height)
            cr.stroke()

        count = len(bins)
        for i, raw in enumerate(bins):
            lvl = max(0.0, min(raw * gain, 1.0))
            if lvl < 0.03:
                continue
            t = i / float(max(1, count - 1))
            spread = width * (0.16 + (t * 0.46))
            lean = 0.24 + (t * 0.78) + (0.05 * math.sin(self.phase + (i * 0.35)))
            length = min_side * (0.08 + (lvl * 0.24) + (t * 0.08)) + (width * (0.07 + (0.07 * t)))
            shard_w = 1.8 + (lvl * 9.5) + ((1.0 - t) * 3.4)
            color = self._color_from_gradient(grad, 0.12 + (0.76 * t))
            base_y = cy + ((t - 0.5) * min_side * 0.16)

            for side in (-1.0, 1.0):
                base_x = cx + (side * spread * (0.48 + (0.34 * t)))
                tip_x = base_x + (side * math.cos(lean) * length * 1.48)
                tip_y = base_y - (math.sin(lean) * length)

                cr.new_path()
                cr.move_to(base_x, base_y - shard_w)
                cr.line_to(base_x + (side * shard_w * 0.72), base_y + (shard_w * 0.36))
                cr.line_to(tip_x, tip_y)
                cr.line_to(base_x - (side * shard_w * 0.34), base_y + (shard_w * 0.98))
                cr.close_path()
                cr.set_source_rgba(color[0], color[1], color[2], 0.14 + (0.34 * lvl))
                cr.fill_preserve()
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.06 + (0.14 * lvl))
                cr.set_line_width(0.8)
                cr.stroke()

                cr.set_source_rgba(color[0], color[1], color[2], 0.06 + (0.18 * lvl))
                cr.move_to(base_x, base_y)
                cr.line_to(tip_x, tip_y)
                cr.set_line_width(max(0.7, shard_w * 0.22))
                cr.stroke()

                if lvl > 0.16:
                    refl_tip_y = base_y + ((base_y - tip_y) * 0.55)
                    cr.new_path()
                    cr.move_to(base_x, base_y + shard_w * 0.32)
                    cr.line_to(base_x + (side * shard_w * 0.42), base_y - (shard_w * 0.18))
                    cr.line_to(tip_x * 0.72 + (base_x * 0.28), refl_tip_y)
                    cr.line_to(base_x - (side * shard_w * 0.24), base_y - (shard_w * 0.50))
                    cr.close_path()
                    cr.set_source_rgba(color[0], color[1], color[2], 0.05 + (0.12 * lvl))
                    cr.fill()

                # Tip glow + side particles so the outer wings feel denser.
                cr.set_source_rgba(color[0], color[1], color[2], 0.14 + (0.18 * lvl))
                cr.arc(tip_x, tip_y, 1.2 + (lvl * 1.8), 0, 2 * math.pi)
                cr.fill()
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.16 + (0.16 * lvl))
                cr.arc(tip_x, tip_y, 0.45 + (lvl * 0.55), 0, 2 * math.pi)
                cr.fill()

                trail_count = 3 + int(lvl * 4.0)
                for p in range(trail_count):
                    tt = (p + 1) / float(trail_count + 1)
                    px = base_x + ((tip_x - base_x) * tt)
                    py = base_y + ((tip_y - base_y) * tt)
                    px += side * (6.0 + (10.0 * tt))
                    py += (0.5 - tt) * 5.0
                    pr = max(0.45, 1.2 - (tt * 0.45) + (lvl * 0.35))
                    cr.set_source_rgba(color[0], color[1], color[2], 0.06 + (0.08 * lvl) + ((1.0 - tt) * 0.04))
                    cr.arc(px, py, pr, 0, 2 * math.pi)
                    cr.fill()

                # Extra wing particles push the visual mass toward the far sides.
                wing_count = 4 + int((0.5 + t) * 4.0)
                for p in range(wing_count):
                    tt = (p + 1) / float(wing_count + 1)
                    wx = tip_x + (side * (width * (0.015 + (0.05 * tt) + (0.03 * t))))
                    wy = tip_y + ((tt - 0.5) * min_side * (0.03 + (0.03 * t)))
                    wr = max(0.35, 0.9 - (tt * 0.20) + (lvl * 0.22))
                    cr.set_source_rgba(color[0], color[1], color[2], 0.03 + (0.05 * lvl) + ((1.0 - tt) * 0.03))
                    cr.arc(wx, wy, wr, 0, 2 * math.pi)
                    cr.fill()

        avg_lvl = sum(bins) / float(max(1, len(bins)))
        pulse_lvl = max(0.0, min(1.0, (avg_lvl * gain * 0.75) + (bass * 0.65)))
        core_r = min_side * 0.078
        aura_r = min_side * (0.28 + (0.05 * pulse_lvl))
        core = cairo.RadialGradient(cx, cy, core_r * 0.10, cx, cy, aura_r)
        core.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.22 + (0.18 * pulse_lvl))
        core.add_color_stop_rgba(0.24, hot[0], hot[1], hot[2], 0.24 + (0.24 * pulse_lvl))
        core.add_color_stop_rgba(0.62, mid[0], mid[1], mid[2], 0.10 + (0.12 * pulse_lvl))
        core.add_color_stop_rgba(1.0, hot[0], hot[1], hot[2], 0.0)
        cr.set_source(core)
        cr.arc(cx, cy, aura_r, 0, 2 * math.pi)
        cr.fill()

        cr.set_source_rgba(hot[0], hot[1], hot[2], 0.42 + (0.30 * pulse_lvl))
        cr.arc(cx, cy, core_r, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.58 + (0.28 * pulse_lvl))
        cr.arc(cx, cy, core_r * 0.44, 0, 2 * math.pi)
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
        cr.set_source_rgba(c_lo[0] * 0.08, c_lo[1] * 0.08, c_lo[2] * 0.08, 0.94)
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

    def _summarize_pro_fall_bins(self, bins):
        vals = [max(0.0, min(float(v), 1.0)) for v in list(bins or [])]
        if not vals:
            return {
                "low": 0.0,
                "mid": 0.0,
                "high": 0.0,
                "avg": 0.0,
                "crest": 0.0,
                "motion": 0.0,
            }
        n = len(vals)
        low_n = max(1, int(n * 0.20))
        mid_end = max(low_n + 1, int(n * 0.65))
        low = sum(vals[:low_n]) / float(low_n)
        mid = sum(vals[low_n:mid_end]) / float(max(1, mid_end - low_n))
        high = sum(vals[mid_end:]) / float(max(1, n - mid_end))
        avg = sum(vals) / float(n)
        crest = max(vals)
        motion = sum(abs(vals[i] - vals[i - 1]) for i in range(1, n)) / float(max(1, n - 1))
        return {
            "low": low,
            "mid": mid,
            "high": high,
            "avg": avg,
            "crest": crest,
            "motion": motion,
        }

    def _shape_pro_fall_frame(self, summary, gain):
        mul = max(0.0, float(gain))
        low = max(0.0, min(summary.get("low", 0.0) * mul, 1.0))
        mid = max(0.0, min(summary.get("mid", 0.0) * mul, 1.0))
        high = max(0.0, min(summary.get("high", 0.0) * mul, 1.0))
        avg = max(0.0, min(summary.get("avg", 0.0) * mul, 1.0))
        crest = max(0.0, min(summary.get("crest", 0.0) * mul, 1.0))
        motion = max(0.0, min(summary.get("motion", 0.0) * mul, 1.0))
        body = max(0.0, min(1.0, (avg * 0.42) + (low * 0.26) + (mid * 0.16) + (crest * 0.16)))
        edge = max(0.0, min(1.0, (crest * 0.56) + (motion * 0.24) + (high * 0.20)))
        core = max(0.0, min(1.0, (low * 0.34) + (avg * 0.34) + (crest * 0.20) + (motion * 0.12)))
        return {
            "body": body,
            "edge": edge,
            "core": core,
        }

    def _smooth_pro_fall_series(self, values):
        vals = list(values or [])
        n = len(vals)
        if n <= 2:
            return vals
        out = [0.0] * n
        for i in range(n):
            prev_v = vals[i - 1] if i > 0 else vals[i]
            cur_v = vals[i]
            next_v = vals[i + 1] if i + 1 < n else vals[i]
            out[i] = (prev_v * 0.22) + (cur_v * 0.56) + (next_v * 0.22)
        return out

    def _ensure_pro_fall_buffers(self, size):
        if len(self._fall_body_env) != size:
            self._fall_body_env = [0.0] * size
            self._fall_core_env = [0.0] * size
            self._fall_edge_env = [0.0] * size
            self._fall_body_smooth = [0.0] * size
            self._fall_core_smooth = [0.0] * size
            self._fall_outline_env = [0.0] * size

    def _smooth_pro_fall_series_into(self, values, out):
        n = len(values)
        if n <= 2:
            for i in range(n):
                out[i] = values[i]
            return
        out[0] = (values[0] * 0.78) + (values[1] * 0.22)
        for i in range(1, n - 1):
            out[i] = (values[i - 1] * 0.22) + (values[i] * 0.56) + (values[i + 1] * 0.22)
        out[n - 1] = (values[n - 2] * 0.22) + (values[n - 1] * 0.78)

    def _trace_pro_fall_outline(self, cr, start_x, step_x, center_y, amps, invert=False):
        if not amps:
            return
        direction = -1.0 if not invert else 1.0
        cr.new_path()
        cr.move_to(start_x, center_y + (direction * amps[0]))
        for i in range(1, len(amps)):
            cr.line_to(start_x + (i * step_x), center_y + (direction * amps[i]))

    def _draw_pro_analyzer_waterfall(self, cr, width, height, gain, grad):
        self._draw_pro_background(cr, width, height, grad)
        if not self.pro_fall_history:
            return
        step_x = 2.0
        cols = max(1, int(math.ceil(width / step_x)))
        frames = self.pro_fall_history[-cols:]
        if not frames:
            return
        if not self._logged_python_pro_fall_img:
            logger.info("Fall image-generation path: Python scrolling waveform renderer")
            self._logged_python_pro_fall_img = True
        frame_count = len(frames)
        self._ensure_pro_fall_buffers(frame_count)
        center_y = height * 0.5
        max_amp = height * 0.42
        start_x = max(0.0, width - (frame_count * step_x))

        body_env = self._fall_body_env
        core_env = self._fall_core_env
        edge_env = self._fall_edge_env
        for i, frame in enumerate(frames):
            stats = self._shape_pro_fall_frame(frame, gain)
            body = pow(max(0.0, min(1.0, stats["body"])), 0.82)
            edge = pow(max(0.0, min(1.0, stats["edge"])), 0.92)
            core = pow(max(0.0, min(1.0, stats["core"])), 0.86)
            body_env[i] = max_amp * (0.05 + (body * 0.68) + (edge * 0.16))
            core_env[i] = max_amp * (0.02 + ((body * 0.20) + (core * 0.36))
            )
            edge_env[i] = max_amp * edge

        body_smooth = self._fall_body_smooth
        core_smooth = self._fall_core_smooth
        outline_env = self._fall_outline_env
        self._smooth_pro_fall_series_into(body_env, body_smooth)
        self._smooth_pro_fall_series_into(core_env, core_smooth)
        for i in range(frame_count):
            prev_v = body_env[i - 1] if i > 0 else body_env[i]
            next_v = body_env[i + 1] if i + 1 < frame_count else body_env[i]
            local_peak = max(0.0, body_env[i] - ((prev_v + next_v) * 0.5))
            spike = (edge_env[i] * 0.22) + (local_peak * 0.95)
            outline_env[i] = min(max_amp * 0.98, body_smooth[i] + spike)

        # Center line like a DAW waveform baseline.
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.10)
        cr.set_line_width(1.0)
        cr.move_to(0, center_y)
        cr.line_to(width, center_y)
        cr.stroke()

        c_new = self._color_from_gradient(grad, 0.16)

        cr.new_path()
        cr.move_to(start_x, center_y - body_smooth[0])
        for i in range(1, frame_count):
            cr.line_to(start_x + (i * step_x), center_y - body_smooth[i])
        for i in range(frame_count - 1, -1, -1):
            cr.line_to(start_x + (i * step_x), center_y + body_smooth[i])
        cr.close_path()
        cr.set_source_rgba(c_new[0], c_new[1], c_new[2], 0.42)
        cr.fill()

        cr.new_path()
        cr.move_to(start_x, center_y - core_smooth[0])
        for i in range(1, frame_count):
            cr.line_to(start_x + (i * step_x), center_y - core_smooth[i])
        for i in range(frame_count - 1, -1, -1):
            cr.line_to(start_x + (i * step_x), center_y + core_smooth[i])
        cr.close_path()
        cr.set_source_rgba(c_new[0] * 0.16, c_new[1] * 0.16, c_new[2] * 0.16, 0.34)
        cr.fill()

        for invert in (False, True):
            self._trace_pro_fall_outline(cr, start_x, step_x, center_y, outline_env, invert=invert)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.14)
            cr.set_line_width(2.2)
            cr.stroke_preserve()
            cr.set_source_rgba(c_new[0], c_new[1], c_new[2], 0.78)
            cr.set_line_width(1.15)
            cr.stroke()

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
