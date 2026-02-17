import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
import cairo
import math
import random #

class BackgroundVisualizer(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_draw_func(self._draw_callback, None)
        
        self.current_energy = 0.0
        self.target_energy = 0.0
        self.phase = 0.0
        
        # [新增] 初始随机颜色
        self.randomize_colors()
        
        GLib.timeout_add(16, self._tick)

    def randomize_colors(self):
        """
        [新增] 随机生成两组美观的 RGB 颜色
        使用 uniform(0.1, 0.8) 确保颜色不会太黑或全白
        """
        self.color_a = (random.uniform(0.1, 0.9), random.uniform(0.1, 0.9), random.uniform(0.1, 0.9))
        self.color_b = (random.uniform(0.1, 0.9), random.uniform(0.1, 0.9), random.uniform(0.1, 0.9))
        print(f"[Background] New Random Colors: A={self.color_a}, B={self.color_b}")

    def update_energy(self, magnitudes):
        if not magnitudes or len(magnitudes) < 12:
            self.target_energy = 0
            return
        bass_sum = sum(magnitudes[:6]) / 6.0
        energy = (bass_sum + 60) / 30.0
        raw_energy = max(0.0, min(1.0, energy))
        self.target_energy = math.pow(raw_energy, 1.2)

    def _tick(self):
        diff = self.target_energy - self.current_energy
        if abs(diff) > 0.001:
            self.current_energy += diff * 0.5
        self.phase += 0.03
        self.queue_draw()
        return True

    def _draw_callback(self, area, cr, width, height, data=None):
        cr.set_source_rgb(0.04, 0.04, 0.06)
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
