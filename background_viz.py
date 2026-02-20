import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, GdkPixbuf

import cairo
import hashlib
import logging
import math
import os
import random
from threading import Thread

import requests

logger = logging.getLogger(__name__)

try:
    from OpenGL import GL
    from OpenGL.GL import shaders as gl_shaders
except Exception:  # pragma: no cover - optional runtime dependency
    GL = None
    gl_shaders = None


VERTEX_SHADER_SRC_330 = """
#version 330 core
layout (location = 0) in vec2 aPos;
out vec2 vUV;
void main() {
    vUV = (aPos + 1.0) * 0.5;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""


FRAGMENT_SHADER_SRC_330 = """
#version 330 core
in vec2 vUV;
out vec4 FragColor;

uniform vec3 uBaseBg;
uniform vec3 uColorA;
uniform vec3 uColorB;
uniform float uEnergy;
uniform float uPhase;
uniform float uAspect;

void main() {
    vec2 uv = vUV;
    float e = max(0.0, min(1.0, uEnergy));
    vec3 col = uBaseBg;
    // Subtle vertical base gradient so the background is not visually "flat black".
    col *= (0.96 + (uv.y * 0.24));

    // Keep a small animated ambient glow so lyrics page never looks "dead black".
    float ambientPulse = 0.5 + (0.5 * sin(uPhase * 0.9));
    float ambientA = 0.12 + (0.10 * ambientPulse);
    col += mix(uColorA, uColorB, uv.x) * ambientA;

    float ee = max(e, 0.08);
    if (ee > 0.0001) {
        // Single large halo, very slow drift: less "ripple", more smooth glow.
        float offx = sin(uPhase * 0.35) * 0.04;
        float offy = cos(uPhase * 0.28) * 0.03;
        vec2 c = vec2(0.5 + offx, 0.5 + offy);

        vec2 dv = vec2((uv.x - c.x) * uAspect, (uv.y - c.y));
        float d = length(dv);
        float r = 0.62 + (0.40 * ee);
        float a = smoothstep(r, 0.0, d) * (0.18 + (0.48 * ee));

        vec3 halo = mix(uColorA, uColorB, 0.45);
        col += halo * a;
    }

    FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""

VERTEX_SHADER_SRC_300_ES = """
#version 300 es
precision mediump float;
layout (location = 0) in vec2 aPos;
out vec2 vUV;
void main() {
    vUV = (aPos + 1.0) * 0.5;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""


FRAGMENT_SHADER_SRC_300_ES = """
#version 300 es
precision highp float;
in vec2 vUV;
out vec4 FragColor;

uniform vec3 uBaseBg;
uniform vec3 uColorA;
uniform vec3 uColorB;
uniform float uEnergy;
uniform float uPhase;
uniform float uAspect;

float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 345.45));
    p += dot(p, p + 34.345);
    return fract(p.x * p.y);
}

void main() {
    vec2 uv = vUV;
    float e = max(0.0, min(1.0, uEnergy));
    vec3 col = uBaseBg;
    col *= (0.96 + (uv.y * 0.24));

    float ambientPulse = 0.5 + (0.5 * sin(uPhase * 0.9));
    float ambientA = 0.12 + (0.10 * ambientPulse);
    col += mix(uColorA, uColorB, uv.x) * ambientA;

    float ee = max(e, 0.08);
    if (ee > 0.0001) {
        float offx = sin(uPhase * 0.35) * 0.04;
        float offy = cos(uPhase * 0.28) * 0.03;
        vec2 c = vec2(0.5 + offx, 0.5 + offy);

        vec2 dv = vec2((uv.x - c.x) * uAspect, (uv.y - c.y));
        float d = length(dv);
        float r = 0.62 + (0.40 * ee);
        float a = smoothstep(r, 0.0, d) * (0.18 + (0.48 * ee));

        vec3 halo = mix(uColorA, uColorB, 0.45);
        col += halo * a;
    }

    // Tiny dithering to reduce visible gradient banding ("fake ripple").
    float n = (hash21((uv * vec2(1920.0, 1080.0)) + vec2(uPhase * 7.0, uPhase * 3.0)) - 0.5) / 255.0;
    col += vec3(n);
    FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


class _BackgroundCommon:
    def _init_state(self):
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
        self._frame_interval_active_ms = 33
        self._last_draw_energy = 0.0
        self._last_draw_phase = 0.0
        self.randomize_colors()
        GLib.timeout_add(self._frame_interval_active_ms, self._tick)

    def _request_redraw(self):
        if hasattr(self, "queue_render"):
            self.queue_render()
        else:
            self.queue_draw()

    def get_motion_mode_names(self):
        return list(self.motion_profiles.keys())

    def set_motion_mode(self, mode_name):
        if mode_name in self.motion_profiles:
            self.motion_mode = mode_name
            if mode_name == "Static":
                self.target_energy = 0.0
                self.current_energy = 0.0
            self._request_redraw()

    def set_theme_mode(self, is_dark):
        self.base_bg_rgb = (0.04, 0.04, 0.06) if is_dark else (0.90, 0.91, 0.93)
        self._request_redraw()

    def randomize_colors(self):
        self.color_a = (
            random.uniform(0.1, 0.9),
            random.uniform(0.1, 0.9),
            random.uniform(0.1, 0.9),
        )
        self.color_b = (
            random.uniform(0.1, 0.9),
            random.uniform(0.1, 0.9),
            random.uniform(0.1, 0.9),
        )
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
                    # Boost very dark covers so the lyrics background remains visible.
                    peak = max(r, g, b, 1e-6)
                    gain = 1.0
                    if peak < 0.40:
                        gain = min(2.2, 0.40 / peak)
                    rr = min(1.0, r * gain)
                    gg = min(1.0, g * gain)
                    bb = min(1.0, b * gain)
                    self.color_a = (min(1.0, rr + 0.12), min(1.0, gg + 0.12), min(1.0, bb + 0.12))
                    self.color_b = (max(0.0, rr - 0.04), min(1.0, gg + 0.06), max(0.0, bb - 0.02))
                    self._request_redraw()
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
            self.target_energy = 0.08
            return
        bass_sum = sum(magnitudes[:6]) / 6.0
        energy = (bass_sum + 60) / 30.0
        raw_energy = max(0.0, min(1.0, energy))
        self.target_energy = math.pow(raw_energy, 1.2) * profile["energy_gain"]
        self.target_energy = max(0.08, min(1.0, self.target_energy))

    def _tick(self):
        profile = self.motion_profiles.get(self.motion_mode, self.motion_profiles["Soft"])
        is_visible = bool(self.get_visible() and self.get_mapped() and self.get_opacity() > 0.01)
        if not is_visible:
            if self.current_energy > 0.001:
                self.current_energy *= 0.96
            return True

        diff = self.target_energy - self.current_energy
        if abs(diff) > 0.001:
            self.current_energy += diff * profile["smoothing"]
        phase_speed = float(profile.get("phase_speed", 0.0))
        if self.current_energy <= 0.006 and self.target_energy <= 0.006:
            self.phase += phase_speed * 0.10
        else:
            self.phase += phase_speed

        energy_changed = abs(self.current_energy - self._last_draw_energy) > 0.002
        phase_changed = abs(self.phase - self._last_draw_phase) > 0.010
        if energy_changed or phase_changed:
            self._last_draw_energy = self.current_energy
            self._last_draw_phase = self.phase
            self._request_redraw()
        return True


class _BackgroundVisualizerCairo(Gtk.DrawingArea, _BackgroundCommon):
    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._draw_callback, None)
        self._init_state()

    def _draw_callback(self, area, cr, width, height, data=None):
        cr.set_source_rgb(*self.base_bg_rgb)
        cr.paint()
        if self.current_energy < 0.005:
            return

        off_x = math.sin(self.phase) * 50
        off_y = math.cos(self.phase * 0.7) * 40
        cx, cy = width / 2 + off_x, height / 2 + off_y

        base_radius = (min(width, height) * 0.6) + (width * 0.8 * self.current_energy)
        base_alpha = 0.12 + (0.35 * self.current_energy)
        grad_base = cairo.RadialGradient(cx, cy, 0, cx, cy, base_radius)
        grad_base.add_color_stop_rgba(0, *self.color_a, base_alpha)
        grad_base.add_color_stop_rgba(0.7, *self.color_a, base_alpha * 0.3)
        grad_base.add_color_stop_rgba(1.0, *self.color_a, 0)
        cr.set_source(grad_base)
        cr.paint()

        core_radius = (min(width, height) * 0.3) + (width * 0.5 * self.current_energy)
        core_alpha = 0.10 + (0.40 * self.current_energy)
        grad_core = cairo.RadialGradient(cx - off_x * 2, cy - off_y * 2, 0, cx - off_x * 2, cy - off_y * 2, core_radius)
        grad_core.add_color_stop_rgba(0, *self.color_b, core_alpha)
        grad_core.add_color_stop_rgba(0.5, *self.color_b, core_alpha * 0.2)
        grad_core.add_color_stop_rgba(1.0, *self.color_b, 0)
        cr.set_source(grad_core)
        cr.paint()


class _BackgroundVisualizerGL(Gtk.GLArea, _BackgroundCommon):
    def __init__(self):
        if GL is None or gl_shaders is None:
            raise RuntimeError("PyOpenGL unavailable for background GL visualizer")
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_auto_render(False)
        self.connect("realize", self._on_realize)
        self.connect("unrealize", self._on_unrealize)
        self.connect("render", self._on_render)

        self._program = None
        self._vao = None
        self._vbo = None
        self._u_base = -1
        self._u_a = -1
        self._u_b = -1
        self._u_energy = -1
        self._u_phase = -1
        self._u_aspect = -1
        self._gl_failed = False
        self._init_state()
        logger.info("Lyrics background renderer: GL")

    def _on_realize(self, _area):
        self.make_current()
        if self.get_error() is not None:
            logger.warning("Lyrics background GL realize failed: %s", self.get_error())
            self._gl_failed = True
            return
        try:
            self._setup_gl()
        except Exception:
            logger.exception("Background GL setup failed")
            self._gl_failed = True

    def _on_unrealize(self, _area):
        if self._vbo is not None:
            GL.glDeleteBuffers(1, [self._vbo])
            self._vbo = None
        if self._vao is not None:
            GL.glDeleteVertexArrays(1, [self._vao])
            self._vao = None
        if self._program is not None:
            GL.glDeleteProgram(self._program)
            self._program = None

    def _setup_gl(self):
        if self._program is not None:
            return
        last_err = None
        shader_variants = [
            ("GLSL 330 core", VERTEX_SHADER_SRC_330, FRAGMENT_SHADER_SRC_330),
            ("GLSL 300 es", VERTEX_SHADER_SRC_300_ES, FRAGMENT_SHADER_SRC_300_ES),
        ]
        for label, vs_src, fs_src in shader_variants:
            try:
                self._program = gl_shaders.compileProgram(
                    gl_shaders.compileShader(vs_src, GL.GL_VERTEX_SHADER),
                    gl_shaders.compileShader(fs_src, GL.GL_FRAGMENT_SHADER),
                )
                logger.info("Lyrics background GL shader selected: %s", label)
                break
            except Exception as e:
                last_err = e
        if self._program is None:
            raise RuntimeError(f"Failed to compile background GL shaders: {last_err}")

        self._u_base = GL.glGetUniformLocation(self._program, "uBaseBg")
        self._u_a = GL.glGetUniformLocation(self._program, "uColorA")
        self._u_b = GL.glGetUniformLocation(self._program, "uColorB")
        self._u_energy = GL.glGetUniformLocation(self._program, "uEnergy")
        self._u_phase = GL.glGetUniformLocation(self._program, "uPhase")
        self._u_aspect = GL.glGetUniformLocation(self._program, "uAspect")

        import ctypes

        self._vao = GL.glGenVertexArrays(1)
        self._vbo = GL.glGenBuffers(1)
        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        verts = [-1.0, -1.0, 1.0, -1.0, -1.0, 1.0, 1.0, 1.0]
        arr = (ctypes.c_float * len(verts))(*verts)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, ctypes.sizeof(arr), arr, GL.GL_STATIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glBindVertexArray(0)

    def _on_render(self, _area, _context):
        if self._gl_failed or self._program is None:
            return True
        w = int(self.get_width() or 0)
        h = int(self.get_height() or 0)
        if w <= 1 or h <= 1:
            return True

        scale = max(1, int(self.get_scale_factor() or 1))
        GL.glViewport(0, 0, w * scale, h * scale)
        GL.glUseProgram(self._program)
        GL.glUniform3f(self._u_base, float(self.base_bg_rgb[0]), float(self.base_bg_rgb[1]), float(self.base_bg_rgb[2]))
        GL.glUniform3f(self._u_a, float(self.color_a[0]), float(self.color_a[1]), float(self.color_a[2]))
        GL.glUniform3f(self._u_b, float(self.color_b[0]), float(self.color_b[1]), float(self.color_b[2]))
        GL.glUniform1f(self._u_energy, float(max(0.0, min(1.0, self.current_energy))))
        GL.glUniform1f(self._u_phase, float(self.phase))
        GL.glUniform1f(self._u_aspect, float(w) / float(max(1, h)))

        GL.glBindVertexArray(self._vao)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glBindVertexArray(0)
        GL.glUseProgram(0)
        return True


if GL is not None and gl_shaders is not None:
    BackgroundVisualizer = _BackgroundVisualizerGL
else:
    logger.info("Lyrics background renderer: Cairo (GL unavailable)")
    BackgroundVisualizer = _BackgroundVisualizerCairo
