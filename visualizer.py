import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
import cairo
import math

class SpectrumVisualizer(Gtk.DrawingArea):
    """
    HiresTI 高灵敏度频谱可视化组件 (已修复 NameError)
    """
    def __init__(self):
        super().__init__()
        self.set_draw_func(self._draw_callback, None)
        self.set_size_request(-1, 0) # 允许 Revealer 完全折叠
        
        self.num_bars = 128
        self.target_heights = [0.0] * self.num_bars
        self.current_heights = [0.0] * self.num_bars
        
        # 启动动画循环 (约 60fps)
        GLib.timeout_add(16, self._on_animation_tick)

    def update_data(self, magnitudes):
        if not magnitudes: return
        
        # 1. 强制转列表并反转 (解决高频在左的问题)
        magnitudes = list(magnitudes)
        
        # [调试诊断] 打印当前的最大音量值
        # 如果终端里一直打印 -60 左右，说明数据正常，只是声音小
        # 如果什么都不打印，说明数据传输断了 (audio_player.py 有问题)
        peak = max(magnitudes)
        # print(f"DEBUG: Peak dB = {peak:.2f}") # 如果需要调试可以取消这行的注释

        new_heights = []
        actual_count = min(len(magnitudes), self.num_bars)

        # 2. [宽容模式] 
        # 将底线设为 -90dB，确保 -60dB 的声音也能显示出来
        db_min = -60.0
        db_range = 60.0 # 范围 -90 到 0

        for i in range(actual_count):
            val = magnitudes[i]
            
            # 3. 简单暴力的映射逻辑
            if val <= db_min:
                h = 0.0
            else:
                # 公式：(当前值 + 90) / 90
                # 如果 val 是 -60，结果就是 30/90 = 0.33 (能看见！)
                h = (val - db_min) / db_range
            
            # 4. 视觉优化
            # 次方越小(0.6)，小声音显示得越高
            h = math.pow(max(0.0, h), 1) 
            
            new_heights.append(max(0.0, min(1.0, h)))

        while len(new_heights) < self.num_bars:
            new_heights.append(0.0)

        self.target_heights = new_heights

    def _on_animation_tick(self):
        changed = False
        for i in range(self.num_bars):
            diff = self.target_heights[i] - self.current_heights[i]
            if abs(diff) > 0.001:
                # 响应系数 0.45，保证波形跟手同步
                self.current_heights[i] += diff * 0.45 
                changed = True
        if changed:
            self.queue_draw()
        return True

    def _draw_callback(self, area, cr, width, height, data=None):
        cr.set_line_width(1.0)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.02)

        # 第一条线：位于顶部 1/3 处 (高音量区参考)
        y1 = height * 0.20
        cr.move_to(0, y1)
        cr.line_to(width, y1)
        cr.stroke()

        # 第二条线：位于顶部 2/3 处 (中音量区参考)
        y2 = height * 0.40
        cr.move_to(0, y2)
        cr.line_to(width, y2)
        cr.stroke()

        y3 = height * 0.60
        cr.move_to(0, y3)
        cr.line_to(width, y3)
        cr.stroke()

        y4 = height * 0.80
        cr.move_to(0, y4)
        cr.line_to(width, y4)
        cr.stroke()
        # --- [核心修复点] ---
        # 必须在这里定义 n，否则下面的 range(n) 会报错
        n = self.num_bars 
        # --------------------
        
        spacing = 1.5
        bar_w = max(1.0, (width - (n - 1) * spacing) / n)
        
        # 定义渐变色
        gradient = cairo.LinearGradient(0, 0, 0, height)
        gradient.add_color_stop_rgba(0.0, 0.0, 1.0, 1.0, 1.0) # 顶：亮青
        gradient.add_color_stop_rgba(0.5, 0.0, 0.5, 1.0, 0.9) # 中：蓝紫
        gradient.add_color_stop_rgba(1.0, 0.2, 0.0, 0.5, 0.6) # 底：深紫
        cr.set_source(gradient)

        for i in range(n):
            h_ratio = self.current_heights[i]
            
            # 静音时不绘制
            if h_ratio < 0.001:
                continue
                
            # 视觉高度增益
            h = h_ratio * height * 1.6
            h = max(1.0, min(h, height))
            
            x = i * (bar_w + spacing)
            y = max(0.0, height - h)
            
            # 绘制圆角柱子
            radius = bar_w / 2
            if h > bar_w:
                cr.move_to(x + radius, y)
                cr.line_to(x + bar_w - radius, y)
                cr.arc(x + bar_w - radius, y + radius, radius, -math.pi/2, 0)
                cr.line_to(x + bar_w, height)
                cr.line_to(x, height)
                cr.line_to(x, y + radius)
                cr.arc(x + radius, y + radius, radius, math.pi, 1.5*math.pi)
            else:
                cr.rectangle(x, y, bar_w, h)
            
            cr.fill()
