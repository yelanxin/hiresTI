import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
import math
import time
import os
import logging
import ctypes
from collections import deque
from rust_viz import RustVizCore

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

uniform int uMode;          // 0: bars, 1: wave, 2: dots, 3: mirror, 4: pro fall, 5: peak, 6: pulse, 7: trail, 8+: extended
uniform int uNumBars;
uniform sampler2D uBandsTex; // x: bar index, y=0, rgb=(height,trail,peak)
uniform vec3 uColorA;
uniform vec3 uColorB;
uniform float uDotPeriod;   // normalized period in Y
uniform float uDotFill;     // 0..1 fill inside each period
uniform float uBarFill;     // 0..1 filled width in each bin
uniform sampler2D uWaterTex;
uniform float uWaterHeadNorm;
uniform float uWaterGain;
uniform float uBass;
uniform float uTime;
uniform float uAspect;

float sample_height(float x) {
    float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
    int idx = int(floor(fx));
    idx = clamp(idx, 0, uNumBars - 1);
    return texelFetch(uBandsTex, ivec2(idx, 0), 0).r;
}

float sample_height_smooth(float x) {
    float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
    int i0 = int(floor(fx));
    i0 = clamp(i0, 0, uNumBars - 1);
    int i1 = min(uNumBars - 1, i0 + 1);
    float t = fract(fx);
    float h0 = texelFetch(uBandsTex, ivec2(i0, 0), 0).r;
    float h1 = texelFetch(uBandsTex, ivec2(i1, 0), 0).r;
    return mix(h0, h1, t);
}

float sample_height_soft(float x) {
    float w = 1.0 / float(max(1, uNumBars));
    float a = sample_height_smooth(x - w);
    float b = sample_height_smooth(x);
    float c = sample_height_smooth(x + w);
    return (a + (2.0 * b) + c) * 0.25;
}

float rounded_bar_mask_bottom(float local, float y, float h, float fill) {
    if (y < 0.0 || y > h || local < 0.0 || local > fill) {
        return 0.0;
    }
    float rx = min(0.18, fill * 0.35);
    float ry = min(0.045, h * 0.55);
    if (rx <= 0.00001 || ry <= 0.00001) {
        return 1.0;
    }
    float y_cap_start = h - ry;
    if (y <= y_cap_start) {
        return 1.0;
    }
    if (local >= rx && local <= (fill - rx)) {
        return 1.0;
    }
    float cx = (local < rx) ? rx : (fill - rx);
    float cy = y_cap_start;
    float dx = (local - cx) / max(rx, 0.00001);
    float dy = (y - cy) / max(ry, 0.00001);
    return ((dx * dx) + (dy * dy) <= 1.0) ? 1.0 : 0.0;
}


void main() {
    vec2 uv = vUV;
    float x = uv.x;
    float y = uv.y;
    float gy = 1.0 - y; // match Cairo vertical gradient: top->bottom
    vec3 col = mix(uColorA, uColorB, gy);
    float alpha = 0.0;

    if (uMode == 4) {
        float sx = fract(uWaterHeadNorm - (1.0 - x));
        float v = texture(uWaterTex, vec2(sx, 1.0 - y)).r;
        float age = pow(clamp(x, 0.0, 1.0), 1.25);
        float lv = clamp(v * uWaterGain, 0.0, 1.0);
        float a = lv * age;
        vec3 wcol = mix(uColorB, uColorA, pow(lv, 0.86));
        vec3 bg = vec3(0.04, 0.05, 0.08);
        vec3 finalCol = mix(bg, wcol, a);
        FragColor = vec4(finalCol, 1.0);
        return;
    } else if (uMode == 5) {
        float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
        int idx = int(floor(fx));
        idx = clamp(idx, 0, uNumBars - 1);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(idx, 0), 0).r;
        float p = texelFetch(uBandsTex, ivec2(idx, 0), 0).b;
        float barFill = 1.0 - step(uBarFill, local);
        float bar = rounded_bar_mask_bottom(local, y, h, uBarFill);
        float cap = smoothstep(0.012, 0.0, abs(y - p));
        vec3 bg = vec3(0.04, 0.05, 0.08);
        vec3 baseCol = mix(bg, col, bar * 0.92);
        vec3 capCol = mix(baseCol, vec3(1.0), cap * barFill * 0.9);
        FragColor = vec4(capCol, 1.0);
        return;
    } else if (uMode == 6) {
        float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
        int idx = int(floor(fx));
        idx = clamp(idx, 0, uNumBars - 1);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(idx, 0), 0).r;
        float barFill = 1.0 - step(uBarFill, local);
        float bar = rounded_bar_mask_bottom(local, y, h, uBarFill);
        vec2 p2 = vec2(x - 0.5, y - 0.58);
        float glow = exp(-dot(p2, p2) * (18.0 - 10.0 * clamp(uBass, 0.0, 1.0)));
        float pulse = clamp(uBass * 0.45 * glow, 0.0, 0.45);
        vec3 bg = vec3(0.04, 0.05, 0.08) + (col * pulse);
        vec3 finalCol = mix(bg, col, bar * 0.92);
        FragColor = vec4(finalCol, 1.0);
        return;
    } else if (uMode == 7) {
        float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
        int idx = int(floor(fx));
        idx = clamp(idx, 0, uNumBars - 1);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(idx, 0), 0).r;
        float t = texelFetch(uBandsTex, ivec2(idx, 0), 0).g;
        float barFill = 1.0 - step(uBarFill, local);
        float bar = rounded_bar_mask_bottom(local, y, h, uBarFill);
        float trail = rounded_bar_mask_bottom(local, y, t, uBarFill);
        vec3 bg = vec3(0.04, 0.05, 0.08);
        float ghost = smoothstep(0.0, 1.0, t) * (1.0 - step(y, h));
        vec3 trailCol = mix(bg, col, trail * 0.38);
        trailCol += col * ghost * 0.14;
        vec3 finalCol = mix(trailCol, col, bar * 0.96);
        FragColor = vec4(finalCol, 1.0);
        return;
    } else if (uMode == 9) {
        int halfN = max(1, uNumBars / 2);
        float hx = (x < 0.5) ? (x * 2.0) : ((x - 0.5) * 2.0);
        float fx = clamp(hx, 0.0, 0.999999) * float(halfN);
        int i = int(floor(fx));
        i = clamp(i, 0, halfN - 1);
        int src = (x < 0.5) ? i : min(uNumBars - 1, i + halfN);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(src, 0), 0).r;
        float barFill = 1.0 - step(uBarFill, local);
        float bar = rounded_bar_mask_bottom(local, y, h, uBarFill);
        float notch = step(0.496, x) * (1.0 - step(0.504, x)); // thin center split only
        float gap = 1.0 - notch;
        vec3 bg = vec3(0.04, 0.05, 0.08);
        vec3 finalCol = mix(bg, col, bar * gap * 0.94);
        FragColor = vec4(finalCol, 1.0);
        return;
    } else if (uMode == 16) {
        float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
        int idx = int(floor(fx));
        idx = clamp(idx, 0, uNumBars - 1);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(idx, 0), 0).r;
        float p = texelFetch(uBandsTex, ivec2(idx, 0), 0).b;
        float barFill = 1.0 - step(uBarFill, local);
        float bar = rounded_bar_mask_bottom(local, y, h, uBarFill);
        float core = bar;
        float cap = smoothstep(0.010, 0.0, abs(y - p)) * barFill;
        vec3 bg = vec3(0.04, 0.05, 0.08);
        vec3 body = mix(bg, col, core * 0.96);
        body += vec3(1.0) * cap * 0.32;
        FragColor = vec4(body, 1.0);
        return;
    } else if (uMode == 8) {
        float h = sample_height_soft(x);
        float edge = smoothstep(0.016, 0.0, abs(y - h));
        float body = step(y, h) * 0.72;
        float crest = smoothstep(0.010, 0.0, abs(y - h)) * 0.22;
        alpha = max(body, max(edge * 0.92, crest));
    } else if (uMode == 10) {
        vec2 p = vec2(x - 0.5, y - 0.52);
        float r = length(p);
        float a01 = fract((atan(p.y, p.x) + 3.14159265) / (6.2831853));
        float lvl = sample_height_soft(a01);
        float warp = sin((a01 * 24.0) + (uTime * 0.8)) * 0.015 * (0.3 + lvl);
        float target = 0.10 + (0.36 * lvl) + warp;
        float ring = smoothstep(0.012, 0.0, abs(r - target));
        float spokeBand = abs(fract((a01 * float(max(4, uNumBars / 2))) - (uTime * 0.05)) - 0.5);
        float spokes = smoothstep(0.11, 0.0, spokeBand) * step(r, target) * 0.42;
        alpha = max(ring * 0.96, spokes);
    } else if (uMode == 11) {
        vec2 p = vec2(x - 0.5, y - 0.52);
        float r = length(p);
        float ang = atan(p.y, p.x);
        float a01 = fract((ang + 3.14159265) / (6.2831853));
        float lvl = sample_height_soft(a01);

        // 1) Fluid paint-like converging lanes.
        float lanes = 0.0; // paint-mix layer disabled for A/B comparison

        // 2) Warped tunnel rings with perspective depth.
        float warp = (
            sin((ang * (2.6 + (2.2 * (1.0 - r)))) + (uTime * (1.0 + (0.4 * r))))
            + sin((ang * (6.4 - (2.2 * r))) - (uTime * 1.35))
        ) * 0.028 * (1.0 + (1.1 * uBass));
        float rr = r + warp;
        float depth = 1.0 - smoothstep(0.06, 0.92, rr);
        float band = abs(fract((rr * 20.0) - (uTime * 0.20)) - 0.5);
        float rings = smoothstep(0.10, 0.0, band) * depth;

        // 3) Spectrum spokes from center.
        float spokeBand = abs(fract((a01 * float(max(12, uNumBars))) + (uTime * 0.04)) - 0.5);
        float spoke = smoothstep(0.06, 0.0, spokeBand) * smoothstep(0.02, 0.76, r) * (0.30 + (0.70 * lvl));

        // 4) Center pulse.
        float pulse = exp(-r * 26.0) * (0.25 + (0.75 * uBass));

        alpha = max(rings * (0.38 + (0.62 * lvl)), max(lanes * 0.44, max(spoke * 0.72, pulse * 0.88)));
    } else if (uMode == 12) {
        vec2 p = vec2(x - 0.5, y - 0.80);
        float r = length(p);
        float a = atan(p.y, p.x);
        float t = fract((a + 3.14159265) / (6.2831853));
        float lvl = sample_height_smooth(t);
        float shock = smoothstep(0.010, 0.0, abs(r - (0.06 + (uBass * 0.22))));
        float spark = smoothstep(0.014, 0.0, abs(r - (0.12 + (lvl * 0.56) + (0.01 * sin(uTime + (t * 18.0))))));
        alpha = max(shock * 0.55, spark * 0.95);
    } else if (uMode == 13) {
        float sx = fract(uWaterHeadNorm - (1.0 - x));
        float v = texture(uWaterTex, vec2(sx, 1.0 - y)).r;
        float lv = clamp(v * uWaterGain, 0.0, 1.0);
        float fade = pow(clamp(y, 0.0, 1.0), 1.4); // emphasize top like classic waterfall
        alpha = lv * fade * 0.95;
    } else if (uMode == 14) {
        float h = sample_height_soft(x);
        float c1 = 0.58 + ((h - 0.5) * 0.26) + (0.04 * sin((x * 10.0) + (uTime * 1.3)));
        float c2 = 0.42 - ((h - 0.5) * 0.20) + (0.03 * sin((x * 13.0) - (uTime * 1.1)));
        float d1 = abs(y - c1);
        float d2 = abs(y - c2);
        float b1 = smoothstep(0.028, 0.0, d1) * 0.85;
        float b2 = smoothstep(0.022, 0.0, d2) * 0.65;
        alpha = max(b1, b2);
    } else if (uMode == 15) {
        vec2 p = vec2(x - 0.5, y - 0.52);
        float r = length(p);
        float ang = atan(p.y, p.x);
        float t = fract((ang + 3.14159265) / (6.2831853));
        float lvl = sample_height_soft(t);

        // Spiral dotted arms (240-like dense samples look)
        float turns = 7.0;
        float armPhase = fract((ang / 6.2831853) + (r * turns) - (uTime * 0.11));
        float armCore = smoothstep(0.070, 0.0, abs(armPhase - 0.5));
        float armFine = smoothstep(0.034, 0.0, abs(armPhase - 0.5));
        float dotGate = smoothstep(0.78, 0.98, abs(sin((ang * 38.0) + (r * 120.0) - (uTime * 1.2))));
        float arms = (armCore * 0.55 + armFine * 0.45) * dotGate * smoothstep(0.90, 0.04, r);
        alpha = arms * (0.35 + (0.65 * lvl));
    } else if (uMode == 17) {
        float h = sample_height_soft(x);
        float d = abs(y - h);
        float line = smoothstep(0.012, 0.0, d);
        float glow = smoothstep(0.038, 0.0, d) * 0.40;
        float stem = step(y, h) * 0.12;
        alpha = max(line * 0.96, glow + stem);
    } else if (uMode == 18) {
        // Cairo-like starscape: neighbor sampling avoids cell-block artifacts.
        vec2 grid = vec2(36.0, 20.0);
        vec2 gid = floor(uv * grid);
        float starAlpha = 0.0;
        vec3 starAccum = vec3(0.0);
        for (int oy = -1; oy <= 1; oy++) {
            for (int ox = -1; ox <= 1; ox++) {
                vec2 cell = gid + vec2(float(ox), float(oy));
                float hid = fract(sin(dot(cell, vec2(127.1, 311.7))) * 43758.5453);
                if (hid <= 0.58) { continue; }
                float sx = fract(sin(dot(cell + vec2(5.2, 1.3), vec2(269.5, 183.3))) * 43758.5453);
                float sy = fract(sin(dot(cell + vec2(2.7, 9.2), vec2(419.2, 371.9))) * 43758.5453);
                float depth = fract(sin(dot(cell + vec2(7.3, 4.1), vec2(193.7, 97.1))) * 43758.5453);
                vec2 p = vec2(sx, sy);
                float drift = (0.004 + (0.006 * depth)) * (0.25 + (0.75 * uBass));
                p.x += sin((uTime * (0.35 + (0.25 * depth))) + (hid * 15.0)) * drift;
                p.y += cos((uTime * (0.27 + (0.20 * depth))) + (hid * 11.0)) * drift * 0.8;
                vec2 starPos = (cell + p) / grid;
                vec2 sd = vec2((uv.x - starPos.x) * uAspect, (uv.y - starPos.y));
                float d = length(sd);
                float coreR = 0.010 + (0.006 * depth);
                float haloR = 0.030 + (0.014 * depth);
                float core = smoothstep(coreR, 0.0, d);
                float halo = smoothstep(haloR, 0.0, d) * 0.55;
                float amp = sample_height_smooth(fract(starPos.x));
                float tw1 = 0.5 + (0.5 * sin((uTime * (4.8 + (3.4 * depth))) + (hid * 23.0)));
                float tw2 = 0.5 + (0.5 * sin((uTime * (9.6 + (5.2 * depth))) + (hid * 37.0)));
                // Wider dynamic range: darker lows, brighter peaks.
                float twinkle = (0.08 + (0.92 * pow(tw1, 2.8))) * (0.70 + (0.55 * tw2));
                float c = (core + halo) * (0.12 + (0.88 * amp)) * twinkle * 1.18;
                vec3 sc = (depth < 0.34) ? uColorA : ((depth < 0.67) ? vec3(1.0) : uColorB);
                starAccum += sc * c;
                starAlpha = max(starAlpha, c);
            }
        }
        alpha = clamp(starAlpha, 0.0, 1.0);
        if (alpha > 0.0001) {
            col = clamp(starAccum / max(starAlpha, 0.0001), 0.0, 1.0);
        } else {
            col = vec3(0.0);
        }
    } else if (uMode == 3) {
        float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
        int idx = int(floor(fx));
        idx = clamp(idx, 0, uNumBars - 1);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(idx, 0), 0).r * 0.48;
        float mid = 0.5;
        float top = step(mid - h, y) * (1.0 - step(mid, y));
        float bot = step(mid, y) * (1.0 - step(mid + h, y));
        float bar = max(top, bot);
        float barFill = 1.0 - step(uBarFill, local);
        alpha = bar * barFill * 0.92;
    } else if (uMode == 0 || uMode == 2) {
        float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
        int idx = int(floor(fx));
        idx = clamp(idx, 0, uNumBars - 1);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(idx, 0), 0).r;
        float barFill = 1.0 - step(uBarFill, local); // left-aligned bar, right gap
        float bar = (uMode == 2) ? step(y, h) : rounded_bar_mask_bottom(local, y, h, uBarFill);
        if (uMode == 2) {
            // Match Cairo Dots: horizontal gradient by bar index (left -> right).
            col = mix(uColorA, uColorB, x);
            float ycell = fract(y / max(0.00001, uDotPeriod));
            float dot = 1.0 - step(uDotFill, ycell); // rectangular dot rows
            alpha = bar * barFill * dot * 0.98;
        } else {
            alpha = bar * 0.92;
        }
    } else {
        float h = sample_height_soft(x);
        float d = abs(y - h);
        float core = smoothstep(0.010, 0.0, d);
        float glow = smoothstep(0.032, 0.0, d) * 0.45;
        alpha = max(core * 0.95, glow);
    }

    // dark panel-like base
    vec3 bg = vec3(0.04, 0.05, 0.08);
    vec3 finalCol = mix(bg, col, alpha);
    FragColor = vec4(finalCol, 1.0);
}
"""

VERTEX_SHADER_SRC_300ES = """
#version 300 es
precision mediump float;
layout (location = 0) in vec2 aPos;
out vec2 vUV;
void main() {
    vUV = (aPos + 1.0) * 0.5;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

FRAGMENT_SHADER_SRC_300ES = """
#version 300 es
precision mediump float;
in vec2 vUV;
out vec4 FragColor;

uniform int uMode;          // 0: bars, 1: wave, 2: dots, 3: mirror, 4: pro fall, 5: peak, 6: pulse, 7: trail, 8+: extended
uniform int uNumBars;
uniform sampler2D uBandsTex; // x: bar index, y=0, rgb=(height,trail,peak)
uniform vec3 uColorA;
uniform vec3 uColorB;
uniform float uDotPeriod;
uniform float uDotFill;
uniform float uBarFill;
uniform sampler2D uWaterTex;
uniform float uWaterHeadNorm;
uniform float uWaterGain;
uniform float uBass;
uniform float uTime;
uniform float uAspect;

float sample_height(float x) {
    float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
    int idx = int(floor(fx));
    idx = clamp(idx, 0, uNumBars - 1);
    return texelFetch(uBandsTex, ivec2(idx, 0), 0).r;
}

float sample_height_smooth(float x) {
    float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
    int i0 = int(floor(fx));
    i0 = clamp(i0, 0, uNumBars - 1);
    int i1 = min(uNumBars - 1, i0 + 1);
    float t = fract(fx);
    float h0 = texelFetch(uBandsTex, ivec2(i0, 0), 0).r;
    float h1 = texelFetch(uBandsTex, ivec2(i1, 0), 0).r;
    return mix(h0, h1, t);
}

float sample_height_soft(float x) {
    float w = 1.0 / float(max(1, uNumBars));
    float a = sample_height_smooth(x - w);
    float b = sample_height_smooth(x);
    float c = sample_height_smooth(x + w);
    return (a + (2.0 * b) + c) * 0.25;
}

float rounded_bar_mask_bottom(float local, float y, float h, float fill) {
    if (y < 0.0 || y > h || local < 0.0 || local > fill) {
        return 0.0;
    }
    float rx = min(0.18, fill * 0.35);
    float ry = min(0.045, h * 0.55);
    if (rx <= 0.00001 || ry <= 0.00001) {
        return 1.0;
    }
    float y_cap_start = h - ry;
    if (y <= y_cap_start) {
        return 1.0;
    }
    if (local >= rx && local <= (fill - rx)) {
        return 1.0;
    }
    float cx = (local < rx) ? rx : (fill - rx);
    float cy = y_cap_start;
    float dx = (local - cx) / max(rx, 0.00001);
    float dy = (y - cy) / max(ry, 0.00001);
    return ((dx * dx) + (dy * dy) <= 1.0) ? 1.0 : 0.0;
}


void main() {
    vec2 uv = vUV;
    float x = uv.x;
    float y = uv.y;
    float gy = 1.0 - y; // match Cairo vertical gradient: top->bottom
    vec3 col = mix(uColorA, uColorB, gy);
    float alpha = 0.0;

    if (uMode == 4) {
        float sx = fract(uWaterHeadNorm - (1.0 - x));
        float v = texture(uWaterTex, vec2(sx, 1.0 - y)).r;
        float age = pow(clamp(x, 0.0, 1.0), 1.25);
        float lv = clamp(v * uWaterGain, 0.0, 1.0);
        float a = lv * age;
        vec3 wcol = mix(uColorB, uColorA, pow(lv, 0.86));
        vec3 bg = vec3(0.04, 0.05, 0.08);
        vec3 finalCol = mix(bg, wcol, a);
        FragColor = vec4(finalCol, 1.0);
        return;
    } else if (uMode == 5) {
        float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
        int idx = int(floor(fx));
        idx = clamp(idx, 0, uNumBars - 1);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(idx, 0), 0).r;
        float p = texelFetch(uBandsTex, ivec2(idx, 0), 0).b;
        float barFill = 1.0 - step(uBarFill, local);
        float bar = rounded_bar_mask_bottom(local, y, h, uBarFill);
        float cap = smoothstep(0.012, 0.0, abs(y - p));
        vec3 bg = vec3(0.04, 0.05, 0.08);
        vec3 baseCol = mix(bg, col, bar * 0.92);
        vec3 capCol = mix(baseCol, vec3(1.0), cap * barFill * 0.9);
        FragColor = vec4(capCol, 1.0);
        return;
    } else if (uMode == 6) {
        float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
        int idx = int(floor(fx));
        idx = clamp(idx, 0, uNumBars - 1);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(idx, 0), 0).r;
        float barFill = 1.0 - step(uBarFill, local);
        float bar = rounded_bar_mask_bottom(local, y, h, uBarFill);
        vec2 p2 = vec2(x - 0.5, y - 0.58);
        float glow = exp(-dot(p2, p2) * (18.0 - 10.0 * clamp(uBass, 0.0, 1.0)));
        float pulse = clamp(uBass * 0.45 * glow, 0.0, 0.45);
        vec3 bg = vec3(0.04, 0.05, 0.08) + (col * pulse);
        vec3 finalCol = mix(bg, col, bar * 0.92);
        FragColor = vec4(finalCol, 1.0);
        return;
    } else if (uMode == 7) {
        float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
        int idx = int(floor(fx));
        idx = clamp(idx, 0, uNumBars - 1);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(idx, 0), 0).r;
        float t = texelFetch(uBandsTex, ivec2(idx, 0), 0).g;
        float barFill = 1.0 - step(uBarFill, local);
        float bar = rounded_bar_mask_bottom(local, y, h, uBarFill);
        float trail = rounded_bar_mask_bottom(local, y, t, uBarFill);
        vec3 bg = vec3(0.04, 0.05, 0.08);
        float ghost = smoothstep(0.0, 1.0, t) * (1.0 - step(y, h));
        vec3 trailCol = mix(bg, col, trail * 0.38);
        trailCol += col * ghost * 0.14;
        vec3 finalCol = mix(trailCol, col, bar * 0.96);
        FragColor = vec4(finalCol, 1.0);
        return;
    } else if (uMode == 9) {
        int halfN = max(1, uNumBars / 2);
        float hx = (x < 0.5) ? (x * 2.0) : ((x - 0.5) * 2.0);
        float fx = clamp(hx, 0.0, 0.999999) * float(halfN);
        int i = int(floor(fx));
        i = clamp(i, 0, halfN - 1);
        int src = (x < 0.5) ? i : min(uNumBars - 1, i + halfN);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(src, 0), 0).r;
        float barFill = 1.0 - step(uBarFill, local);
        float bar = rounded_bar_mask_bottom(local, y, h, uBarFill);
        float notch = step(0.496, x) * (1.0 - step(0.504, x));
        float gap = 1.0 - notch;
        vec3 bg = vec3(0.04, 0.05, 0.08);
        vec3 finalCol = mix(bg, col, bar * gap * 0.94);
        FragColor = vec4(finalCol, 1.0);
        return;
    } else if (uMode == 16) {
        float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
        int idx = int(floor(fx));
        idx = clamp(idx, 0, uNumBars - 1);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(idx, 0), 0).r;
        float p = texelFetch(uBandsTex, ivec2(idx, 0), 0).b;
        float barFill = 1.0 - step(uBarFill, local);
        float bar = rounded_bar_mask_bottom(local, y, h, uBarFill);
        float core = bar;
        float cap = smoothstep(0.010, 0.0, abs(y - p)) * barFill;
        vec3 bg = vec3(0.04, 0.05, 0.08);
        vec3 body = mix(bg, col, core * 0.96);
        body += vec3(1.0) * cap * 0.32;
        FragColor = vec4(body, 1.0);
        return;
    } else if (uMode == 8) {
        float h = sample_height_soft(x);
        float edge = smoothstep(0.016, 0.0, abs(y - h));
        float body = step(y, h) * 0.72;
        float crest = smoothstep(0.010, 0.0, abs(y - h)) * 0.22;
        alpha = max(body, max(edge * 0.92, crest));
    } else if (uMode == 10) {
        vec2 p = vec2(x - 0.5, y - 0.52);
        float r = length(p);
        float a01 = fract((atan(p.y, p.x) + 3.14159265) / (6.2831853));
        float lvl = sample_height_soft(a01);
        float warp = sin((a01 * 24.0) + (uTime * 0.8)) * 0.015 * (0.3 + lvl);
        float target = 0.10 + (0.36 * lvl) + warp;
        float ring = smoothstep(0.012, 0.0, abs(r - target));
        float spokeBand = abs(fract((a01 * float(max(4, uNumBars / 2))) - (uTime * 0.05)) - 0.5);
        float spokes = smoothstep(0.11, 0.0, spokeBand) * step(r, target) * 0.42;
        alpha = max(ring * 0.96, spokes);
    } else if (uMode == 11) {
        vec2 p = vec2(x - 0.5, y - 0.52);
        float r = length(p);
        float ang = atan(p.y, p.x);
        float a01 = fract((ang + 3.14159265) / (6.2831853));
        float lvl = sample_height_soft(a01);

        float lanes = 0.0; // paint-mix layer disabled for A/B comparison

        float warp = (
            sin((ang * (2.6 + (2.2 * (1.0 - r)))) + (uTime * (1.0 + (0.4 * r))))
            + sin((ang * (6.4 - (2.2 * r))) - (uTime * 1.35))
        ) * 0.028 * (1.0 + (1.1 * uBass));
        float rr = r + warp;
        float depth = 1.0 - smoothstep(0.06, 0.92, rr);
        float band = abs(fract((rr * 20.0) - (uTime * 0.20)) - 0.5);
        float rings = smoothstep(0.10, 0.0, band) * depth;

        float spokeBand = abs(fract((a01 * float(max(12, uNumBars))) + (uTime * 0.04)) - 0.5);
        float spoke = smoothstep(0.06, 0.0, spokeBand) * smoothstep(0.02, 0.76, r) * (0.30 + (0.70 * lvl));

        float pulse = exp(-r * 26.0) * (0.25 + (0.75 * uBass));

        alpha = max(rings * (0.38 + (0.62 * lvl)), max(lanes * 0.44, max(spoke * 0.72, pulse * 0.88)));
    } else if (uMode == 12) {
        vec2 p = vec2(x - 0.5, y - 0.80);
        float r = length(p);
        float a = atan(p.y, p.x);
        float t = fract((a + 3.14159265) / (6.2831853));
        float lvl = sample_height_smooth(t);
        float shock = smoothstep(0.010, 0.0, abs(r - (0.06 + (uBass * 0.22))));
        float spark = smoothstep(0.014, 0.0, abs(r - (0.12 + (lvl * 0.56) + (0.01 * sin(uTime + (t * 18.0))))));
        alpha = max(shock * 0.55, spark * 0.95);
    } else if (uMode == 13) {
        float sx = fract(uWaterHeadNorm - (1.0 - x));
        float v = texture(uWaterTex, vec2(sx, 1.0 - y)).r;
        float lv = clamp(v * uWaterGain, 0.0, 1.0);
        float fade = pow(clamp(y, 0.0, 1.0), 1.4);
        alpha = lv * fade * 0.95;
    } else if (uMode == 14) {
        float h = sample_height_soft(x);
        float c1 = 0.58 + ((h - 0.5) * 0.26) + (0.04 * sin((x * 10.0) + (uTime * 1.3)));
        float c2 = 0.42 - ((h - 0.5) * 0.20) + (0.03 * sin((x * 13.0) - (uTime * 1.1)));
        float d1 = abs(y - c1);
        float d2 = abs(y - c2);
        float b1 = smoothstep(0.028, 0.0, d1) * 0.85;
        float b2 = smoothstep(0.022, 0.0, d2) * 0.65;
        alpha = max(b1, b2);
    } else if (uMode == 15) {
        vec2 p = vec2(x - 0.5, y - 0.52);
        float r = length(p);
        float ang = atan(p.y, p.x);
        float t = fract((ang + 3.14159265) / (6.2831853));
        float lvl = sample_height_soft(t);

        float turns = 7.0;
        float armPhase = fract((ang / 6.2831853) + (r * turns) - (uTime * 0.11));
        float armCore = smoothstep(0.070, 0.0, abs(armPhase - 0.5));
        float armFine = smoothstep(0.034, 0.0, abs(armPhase - 0.5));
        float dotGate = smoothstep(0.78, 0.98, abs(sin((ang * 38.0) + (r * 120.0) - (uTime * 1.2))));
        float arms = (armCore * 0.55 + armFine * 0.45) * dotGate * smoothstep(0.90, 0.04, r);
        alpha = arms * (0.35 + (0.65 * lvl));
    } else if (uMode == 17) {
        float h = sample_height_soft(x);
        float d = abs(y - h);
        float line = smoothstep(0.012, 0.0, d);
        float glow = smoothstep(0.038, 0.0, d) * 0.40;
        float stem = step(y, h) * 0.12;
        alpha = max(line * 0.96, glow + stem);
    } else if (uMode == 18) {
        // Cairo-like starscape: neighbor sampling avoids cell-block artifacts.
        vec2 grid = vec2(36.0, 20.0);
        vec2 gid = floor(uv * grid);
        float starAlpha = 0.0;
        vec3 starAccum = vec3(0.0);
        for (int oy = -1; oy <= 1; oy++) {
            for (int ox = -1; ox <= 1; ox++) {
                vec2 cell = gid + vec2(float(ox), float(oy));
                float hid = fract(sin(dot(cell, vec2(127.1, 311.7))) * 43758.5453);
                if (hid <= 0.58) { continue; }
                float sx = fract(sin(dot(cell + vec2(5.2, 1.3), vec2(269.5, 183.3))) * 43758.5453);
                float sy = fract(sin(dot(cell + vec2(2.7, 9.2), vec2(419.2, 371.9))) * 43758.5453);
                float depth = fract(sin(dot(cell + vec2(7.3, 4.1), vec2(193.7, 97.1))) * 43758.5453);
                vec2 p = vec2(sx, sy);
                float drift = (0.004 + (0.006 * depth)) * (0.25 + (0.75 * uBass));
                p.x += sin((uTime * (0.35 + (0.25 * depth))) + (hid * 15.0)) * drift;
                p.y += cos((uTime * (0.27 + (0.20 * depth))) + (hid * 11.0)) * drift * 0.8;
                vec2 starPos = (cell + p) / grid;
                vec2 sd = vec2((uv.x - starPos.x) * uAspect, (uv.y - starPos.y));
                float d = length(sd);
                float coreR = 0.010 + (0.006 * depth);
                float haloR = 0.030 + (0.014 * depth);
                float core = smoothstep(coreR, 0.0, d);
                float halo = smoothstep(haloR, 0.0, d) * 0.55;
                float amp = sample_height_smooth(fract(starPos.x));
                float tw1 = 0.5 + (0.5 * sin((uTime * (4.8 + (3.4 * depth))) + (hid * 23.0)));
                float tw2 = 0.5 + (0.5 * sin((uTime * (9.6 + (5.2 * depth))) + (hid * 37.0)));
                // Wider dynamic range: darker lows, brighter peaks.
                float twinkle = (0.08 + (0.92 * pow(tw1, 2.8))) * (0.70 + (0.55 * tw2));
                float c = (core + halo) * (0.12 + (0.88 * amp)) * twinkle * 1.18;
                vec3 sc = (depth < 0.34) ? uColorA : ((depth < 0.67) ? vec3(1.0) : uColorB);
                starAccum += sc * c;
                starAlpha = max(starAlpha, c);
            }
        }
        alpha = clamp(starAlpha, 0.0, 1.0);
        if (alpha > 0.0001) {
            col = clamp(starAccum / max(starAlpha, 0.0001), 0.0, 1.0);
        } else {
            col = vec3(0.0);
        }
    } else if (uMode == 3) {
        float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
        int idx = int(floor(fx));
        idx = clamp(idx, 0, uNumBars - 1);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(idx, 0), 0).r * 0.48;
        float mid = 0.5;
        float top = step(mid - h, y) * (1.0 - step(mid, y));
        float bot = step(mid, y) * (1.0 - step(mid + h, y));
        float bar = max(top, bot);
        float barFill = 1.0 - step(uBarFill, local);
        alpha = bar * barFill * 0.92;
    } else if (uMode == 0 || uMode == 2) {
        float fx = clamp(x, 0.0, 0.999999) * float(uNumBars);
        int idx = int(floor(fx));
        idx = clamp(idx, 0, uNumBars - 1);
        float local = fract(fx);
        float h = texelFetch(uBandsTex, ivec2(idx, 0), 0).r;
        float barFill = 1.0 - step(uBarFill, local);
        float bar = (uMode == 2) ? step(y, h) : rounded_bar_mask_bottom(local, y, h, uBarFill);
        if (uMode == 2) {
            // Match Cairo Dots: horizontal gradient by bar index (left -> right).
            col = mix(uColorA, uColorB, x);
            float ycell = fract(y / max(0.00001, uDotPeriod));
            float dot = 1.0 - step(uDotFill, ycell);
            alpha = bar * barFill * dot * 0.98;
        } else {
            alpha = bar * 0.92;
        }
    } else {
        float h = sample_height_soft(x);
        float d = abs(y - h);
        float core = smoothstep(0.010, 0.0, d);
        float glow = smoothstep(0.032, 0.0, d) * 0.45;
        alpha = max(core * 0.95, glow);
    }

    vec3 bg = vec3(0.04, 0.05, 0.08);
    vec3 finalCol = mix(bg, col, alpha);
    FragColor = vec4(finalCol, 1.0);
}
"""


class SpectrumVisualizerGLArea(Gtk.GLArea):
    EFFECT_MODE_MAP = {
        "Bars": 0,
        "Wave": 1,
        "Dots": 2,
        "Mirror": 3,
        "Pro Fall": 4,
        "Peak": 5,
        "Pulse": 6,
        "Trail": 7,
        "Fill": 8,
        "Stereo": 9,
        "Burst": 12,
        "Ribbon": 14,
        "Spiral": 15,
        "Pro Bars": 16,
        "Pro Line": 17,
        "Stars": 18,
        "Neon": 11,
    }

    def __init__(self):
        if GL is None or gl_shaders is None:
            raise RuntimeError("PyOpenGL is required for GLArea visualizer")
        super().__init__()
        self.set_size_request(-1, 0)
        self.set_auto_render(False)
        self.connect("realize", self._on_realize)
        self.connect("unrealize", self._on_unrealize)
        self.connect("render", self._on_render)

        self.theme_name = "Aurora (Default)"
        self.effect_name = "Bars"
        # Full GL effect list (phased migration from Cairo path).
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
                "smooth": 0.30,
                "trail_decay": 0.93,
                "peak_hold_frames": 12,
                "peak_fall": 0.014,
            },
            "Dynamic": {
                "gain_mul": 1.0,
                "smooth": 0.45,
                "trail_decay": 0.90,
                "peak_hold_frames": 8,
                "peak_fall": 0.02,
            },
            "Extreme": {
                "gain_mul": 1.18,
                "smooth": 0.56,
                "trail_decay": 0.87,
                "peak_hold_frames": 6,
                "peak_fall": 0.03,
            },
            "Insane": {
                "gain_mul": 1.32,
                "smooth": 0.62,
                "trail_decay": 0.84,
                "peak_hold_frames": 4,
                "peak_fall": 0.04,
            },
        }
        self.themes = {
            "Aurora (Default)": {"height_gain": 1.6, "c0": (0.0, 1.0, 1.0), "c1": (0.2, 0.0, 0.5)},
            "Amber Pulse": {"height_gain": 1.55, "c0": (1.0, 0.87, 0.25), "c1": (0.65, 0.2, 0.05)},
            "Emerald Flow": {"height_gain": 1.62, "c0": (0.52, 1.0, 0.82), "c1": (0.02, 0.43, 0.36)},
            "Crimson Drive": {"height_gain": 1.58, "c0": (1.0, 0.48, 0.56), "c1": (0.42, 0.06, 0.16)},
            "Ice Beam": {"height_gain": 1.64, "c0": (0.82, 0.96, 1.0), "c1": (0.12, 0.28, 0.58)},
            "Mono Steel": {"height_gain": 1.52, "c0": (0.92, 0.92, 0.92), "c1": (0.22, 0.24, 0.28)},
            "Neon Rush": {"height_gain": 1.78, "c0": (0.25, 1.0, 0.92), "c1": (1.0, 0.18, 0.62)},
            "Inferno Boost": {"height_gain": 1.85, "c0": (1.0, 0.95, 0.48), "c1": (0.45, 0.02, 0.06)},
            "Blue Violet Blaze": {"height_gain": 1.82, "c0": (0.74, 0.9, 1.0), "c1": (0.16, 0.05, 0.42)},
            "Plasma Storm": {"height_gain": 1.8, "c0": (0.86, 0.97, 1.0), "c1": (0.92, 0.16, 0.62)},
            "Pure Cyan": {"height_gain": 1.72, "c0": (0.1, 0.95, 1.0), "c1": (0.1, 0.95, 1.0)},
            "Pure Red": {"height_gain": 1.72, "c0": (1.0, 0.18, 0.18), "c1": (1.0, 0.18, 0.18)},
            "Pure White": {"height_gain": 1.7, "c0": (1.0, 1.0, 1.0), "c1": (1.0, 1.0, 1.0)},
            "Soft Dark Gold": {"height_gain": 1.74, "c0": (0.92, 0.78, 0.36), "c1": (0.92, 0.78, 0.36)},
            "Silver Sheen": {"height_gain": 1.72, "c0": (0.9, 0.93, 0.98), "c1": (0.9, 0.93, 0.98)},
            "Dark Gold Shadow": {"height_gain": 1.76, "c0": (0.93, 0.8, 0.38), "c1": (0.08, 0.06, 0.03)},
            "Infrared": {"height_gain": 1.8, "c0": (0.98, 0.98, 0.72), "c1": (0.16, 0.02, 0.02)},
            "Stars BWR": {"height_gain": 1.7, "c0": (0.12, 0.42, 1.0), "c1": (1.0, 0.18, 0.18)},
        }

        self.num_bars = 64
        self.target_heights = [0.0] * self.num_bars
        self.current_heights = [0.0] * self.num_bars
        self.trail_heights = [0.0] * self.num_bars
        self.peak_holds = [0.0] * self.num_bars
        self.peak_ttl = [0] * self.num_bars
        self.bass_level = 0.0
        self._display_target_heights = [0.0] * self.num_bars

        self._program = None
        self._vao = None
        self._vbo = None
        self._u_mode = -1
        self._u_num = -1
        self._u_bands_tex = -1
        self._u_c0 = -1
        self._u_c1 = -1
        self._u_dot_period = -1
        self._u_dot_fill = -1
        self._u_bar_fill = -1
        self._u_water_tex = -1
        self._u_water_head = -1
        self._u_water_gain = -1
        self._u_bass = -1
        self._u_time = -1
        self._u_aspect = -1
        self._water_tex = None
        self._bands_tex = None
        self._water_w = 512
        self._water_h = 64
        self._water_head_idx = 0
        self._water_dirty = True
        self._water_data = bytearray(self._water_w * self._water_h * 4)
        self._gl_failed = False
        self._sensitivity = 1.0
        self._render_lag_ms = 0.0
        self._frame_queue = deque()
        self._frame_interval_ms = 16  # ~60fps render interpolation
        self._last_logged_mode = None
        self._logged_rust_anim = False
        self._logged_python_anim = False
        self.phase = 0.0
        # Reused GL uniform buffers to avoid per-frame Python allocations.
        self._u_heights_buf = (ctypes.c_float * 128)()
        self._u_trail_buf = (ctypes.c_float * 128)()
        self._u_peak_buf = (ctypes.c_float * 128)()
        self._bands_tex_buf = (ctypes.c_float * (128 * 4))()
        self._state_cur_buf = (ctypes.c_float * 128)()
        self._state_trail_buf = (ctypes.c_float * 128)()
        self._state_peak_buf = (ctypes.c_float * 128)()
        self._uploaded_count = 0
        self._viz_trace_enabled = str(os.getenv("HIRESTI_VIZ_TRACE", "0")).strip().lower() in ("1", "true", "yes", "on")
        self._viz_trace_last_render_ts = 0.0
        # Cached profile fields used in hot paths.
        self._prof_smooth = 0.45
        self._prof_trail_decay = 0.90
        self._prof_peak_hold = 8
        self._prof_peak_fall = 0.02
        self._prof_gain_mul = 1.0
        self._theme_height_gain = 1.6
        self._theme_c0 = (0.0, 1.0, 1.0)
        self._theme_c1 = (0.2, 0.0, 0.5)
        self._effect_mode = 0
        self._active = False
        self._anim_source = None
        self._refresh_theme_cache()
        self._refresh_profile_cache()
        self._refresh_effect_cache()
        self._rust_core = RustVizCore()
        self._rust_processor = self._build_rust_processor()
        self._rust_state = self._build_rust_state()

    def set_active(self, active):
        new_active = bool(active)
        if self._active == new_active:
            return
        self._active = new_active
        if self._active:
            if self._anim_source is None:
                self._anim_source = GLib.timeout_add(self._frame_interval_ms, self._on_animation_tick)
            self.queue_render()
        else:
            if self._anim_source:
                try:
                    GLib.source_remove(self._anim_source)
                except Exception:
                    pass
                self._anim_source = None

    def _refresh_profile_cache(self):
        p = self.profiles[self.profile_name] if self.profile_name in self.profiles else self.profiles["Dynamic"]
        self._prof_smooth = float(p.get("smooth", 0.45))
        self._prof_trail_decay = float(p.get("trail_decay", 0.90))
        self._prof_peak_hold = int(p.get("peak_hold_frames", 8))
        self._prof_peak_fall = float(p.get("peak_fall", 0.02))
        self._prof_gain_mul = float(p.get("gain_mul", 1.0))

    def _refresh_theme_cache(self):
        t = self.themes[self.theme_name] if self.theme_name in self.themes else self.themes["Aurora (Default)"]
        self._theme_height_gain = float(t.get("height_gain", 1.6))
        self._theme_c0 = t.get("c0", (0.0, 1.0, 1.0))
        self._theme_c1 = t.get("c1", (0.2, 0.0, 0.5))

    def _refresh_effect_cache(self):
        self._effect_mode = int(self.EFFECT_MODE_MAP.get(self.effect_name, 0))

    def _build_rust_processor(self):
        if not self._rust_core.available:
            return None
        smooth = self._prof_smooth
        return self._rust_core.create_processor(
            num_bars=self.num_bars,
            max_hz=24.0,
            smooth=smooth,
            db_min=-60.0,
            db_range=60.0,
        )

    def _build_rust_state(self):
        if not self._rust_core.available:
            return None
        return self._rust_core.create_state_engine(
            num_bars=self.num_bars,
            smooth=self._prof_smooth,
            trail_decay=self._prof_trail_decay,
            peak_hold_frames=self._prof_peak_hold,
            peak_fall=self._prof_peak_fall,
            bass_smooth=0.22,
        )

    def _rebuild_rust_processor(self):
        if self._rust_processor is not None:
            self._rust_processor.close()
            self._rust_processor = None
        self._rust_processor = self._build_rust_processor()
        if self._rust_state is not None:
            self._rust_state.close()
            self._rust_state = None
        self._rust_state = self._build_rust_state()

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

    def set_theme(self, theme_name):
        if theme_name in self.themes:
            self.theme_name = theme_name
            self._refresh_theme_cache()
            self.queue_render()

    def set_effect(self, effect_name):
        if effect_name in self.effects:
            self.effect_name = effect_name
            self._refresh_effect_cache()
            if effect_name == "Pro Fall" and self._water_data:
                self._water_data[:] = b"\x00" * len(self._water_data)
                self._water_head_idx = 0
                self._water_dirty = True
            self.queue_render()

    def set_profile(self, profile_name):
        if profile_name in self.profiles:
            self.profile_name = profile_name
            self._refresh_profile_cache()
            self._rebuild_rust_processor()
            if self._rust_state is not None:
                self._rust_state.set_params(
                    smooth=self._prof_smooth,
                    trail_decay=self._prof_trail_decay,
                    peak_hold_frames=self._prof_peak_hold,
                    peak_fall=self._prof_peak_fall,
                    bass_smooth=0.22,
                )
            self.queue_render()

    def set_num_bars(self, count):
        try:
            n = int(count)
        except Exception:
            return
        n = max(4, min(128, n))
        if n == self.num_bars:
            return
        self.num_bars = n
        self.target_heights = [0.0] * n
        self.current_heights = [0.0] * n
        self.trail_heights = [0.0] * n
        self.peak_holds = [0.0] * n
        self.peak_ttl = [0] * n
        self._display_target_heights = [0.0] * n
        self._frame_queue.clear()
        self._rebuild_rust_processor()
        self.queue_render()

    def update_data(self, magnitudes):
        if not magnitudes:
            return
        out = None
        if self._rust_processor is not None:
            out = self._rust_processor.process(magnitudes)
        if out is None:
            vals = list(magnitudes)
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

        # Fast path: no lag compensation requested, avoid queue churn.
        if self._render_lag_ms <= 0.01:
            chosen = out
        else:
            now_ms = time.monotonic() * 1000.0
            self._frame_queue.append((now_ms, out))
            while len(self._frame_queue) > 64:
                self._frame_queue.popleft()
            target_ts = now_ms - self._render_lag_ms
            chosen = None
            while self._frame_queue and self._frame_queue[0][0] <= target_ts:
                _ts, chosen = self._frame_queue.popleft()
            if chosen is None:
                return

        self.target_heights = chosen
        self._display_target_heights = chosen
        if self._rust_state is not None:
            self._rust_state.set_target(chosen)
        self._push_waterfall_column(chosen)

    def _build_log_bins_py(self, values, out_count):
        in_count = len(values)
        if in_count <= 0 or out_count <= 0:
            return [0.0] * max(0, out_count)
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
            tilt = 0.92 + (0.16 * (i / float(max(1, out_count - 1))))
            out[i] = max(0.0, min(1.0, pow(v, 0.84) * tilt))
        return out

    def _push_waterfall_column(self, heights):
        vals = list(heights or [])
        if not vals:
            return
        bins = None
        if self._rust_core.available:
            bins = self._rust_core.build_log_bins(vals, self._water_h)
        if bins is None:
            bins = self._build_log_bins_py(vals, self._water_h)
        self._water_head_idx = (self._water_head_idx + 1) % self._water_w
        x = self._water_head_idx
        for r in range(self._water_h):
            lv = max(0.0, min(1.0, float(bins[r] if r < len(bins) else 0.0)))
            y = self._water_h - 1 - r
            off = (y * self._water_w + x) * 4
            v = int(lv * 255.0)
            self._water_data[off] = v
            self._water_data[off + 1] = v
            self._water_data[off + 2] = v
            self._water_data[off + 3] = 255
        self._water_dirty = True

    def _on_animation_tick(self):
        if not self._active:
            self._anim_source = None
            return False
        self.phase += 0.045
        if self._rust_state is not None:
            if not self._logged_rust_anim:
                logger.info("GLArea animation state path: Rust")
                self._logged_rust_anim = True
            n = min(self.num_bars, 128)
            written, bass = self._rust_state.tick_copy(
                self._state_cur_buf,
                self._state_trail_buf,
                self._state_peak_buf,
            )
            if written > 0:
                self.bass_level = bass
                self.queue_render()
            return True

        if not self._logged_python_anim:
            logger.info("GLArea animation state path: Python fallback")
            self._logged_python_anim = True
        changed = False
        n = self.num_bars
        smooth = self._prof_smooth
        trail_decay = self._prof_trail_decay
        peak_hold_frames = self._prof_peak_hold
        peak_fall = self._prof_peak_fall
        bass_acc = 0.0
        bass_n = max(1, n // 10)
        for i in range(n):
            tgt = self._display_target_heights[i]
            cur = self.current_heights[i]
            d = tgt - cur
            if abs(d) > 0.0008:
                self.current_heights[i] = cur + (d * smooth)
                changed = True
            h = self.current_heights[i]
            self.trail_heights[i] = max(h, self.trail_heights[i] * trail_decay)
            if h >= self.peak_holds[i]:
                self.peak_holds[i] = h
                self.peak_ttl[i] = peak_hold_frames
            else:
                if self.peak_ttl[i] > 0:
                    self.peak_ttl[i] -= 1
                else:
                    self.peak_holds[i] = max(0.0, self.peak_holds[i] - peak_fall)
            if i < bass_n:
                bass_acc += h
        bass_tgt = bass_acc / float(bass_n)
        self.bass_level += (bass_tgt - self.bass_level) * 0.22
        if changed:
            self.queue_render()
        return True

    def _on_realize(self, area):
        self.make_current()
        if self.get_error() is not None:
            return
        try:
            self._setup_gl()
        except Exception:
            logger.exception("GLArea setup failed")
            self._gl_failed = True

    def _on_unrealize(self, area):
        if self._vbo is not None:
            GL.glDeleteBuffers(1, [self._vbo])
            self._vbo = None
        if self._vao is not None:
            GL.glDeleteVertexArrays(1, [self._vao])
            self._vao = None
        if self._program is not None:
            GL.glDeleteProgram(self._program)
            self._program = None
        if self._bands_tex is not None:
            GL.glDeleteTextures([self._bands_tex])
            self._bands_tex = None
        if self._water_tex is not None:
            GL.glDeleteTextures([self._water_tex])
            self._water_tex = None

    def _setup_gl(self):
        if self._program is not None:
            return
        last_err = None
        shader_pairs = [
            (VERTEX_SHADER_SRC_330, FRAGMENT_SHADER_SRC_330),
            (VERTEX_SHADER_SRC_300ES, FRAGMENT_SHADER_SRC_300ES),
        ]
        for vs, fs in shader_pairs:
            try:
                self._program = gl_shaders.compileProgram(
                    gl_shaders.compileShader(vs, GL.GL_VERTEX_SHADER),
                    gl_shaders.compileShader(fs, GL.GL_FRAGMENT_SHADER),
                )
                last_err = None
                break
            except Exception as e:
                last_err = e
                self._program = None
        if self._program is None:
            raise RuntimeError(f"Failed to compile GL shaders: {last_err}")
        self._u_mode = GL.glGetUniformLocation(self._program, "uMode")
        self._u_num = GL.glGetUniformLocation(self._program, "uNumBars")
        self._u_bands_tex = GL.glGetUniformLocation(self._program, "uBandsTex")
        self._u_c0 = GL.glGetUniformLocation(self._program, "uColorA")
        self._u_c1 = GL.glGetUniformLocation(self._program, "uColorB")
        self._u_dot_period = GL.glGetUniformLocation(self._program, "uDotPeriod")
        self._u_dot_fill = GL.glGetUniformLocation(self._program, "uDotFill")
        self._u_bar_fill = GL.glGetUniformLocation(self._program, "uBarFill")
        self._u_water_tex = GL.glGetUniformLocation(self._program, "uWaterTex")
        self._u_water_head = GL.glGetUniformLocation(self._program, "uWaterHeadNorm")
        self._u_water_gain = GL.glGetUniformLocation(self._program, "uWaterGain")
        self._u_bass = GL.glGetUniformLocation(self._program, "uBass")
        self._u_time = GL.glGetUniformLocation(self._program, "uTime")
        self._u_aspect = GL.glGetUniformLocation(self._program, "uAspect")

        self._vao = GL.glGenVertexArrays(1)
        self._vbo = GL.glGenBuffers(1)
        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)

        verts = [
            -1.0, -1.0,
             1.0, -1.0,
            -1.0,  1.0,
             1.0,  1.0,
        ]
        import ctypes
        arr = (ctypes.c_float * len(verts))(*verts)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, ctypes.sizeof(arr), arr, GL.GL_STATIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glBindVertexArray(0)

        # Bands texture (x=bar index, rgb=(height,trail,peak)).
        self._bands_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._bands_tex)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D,
            0,
            GL.GL_RGBA32F,
            128,
            1,
            0,
            GL.GL_RGBA,
            GL.GL_FLOAT,
            self._bands_tex_buf,
        )
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

        # Waterfall texture (single-channel intensity packed into RGBA bytes).
        self._water_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._water_tex)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        import ctypes
        tex_arr = (ctypes.c_ubyte * len(self._water_data)).from_buffer_copy(self._water_data)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D,
            0,
            GL.GL_RGBA,
            self._water_w,
            self._water_h,
            0,
            GL.GL_RGBA,
            GL.GL_UNSIGNED_BYTE,
            tex_arr,
        )
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

    def _on_render(self, area, context):
        if self._gl_failed:
            return True
        if self._program is None:
            return True
        if self._viz_trace_enabled:
            now = time.monotonic()
            if self._viz_trace_last_render_ts > 0.0:
                gap_ms = (now - self._viz_trace_last_render_ts) * 1000.0
                if gap_ms >= 70.0:
                    logger.info("VIZ TRACE gl-render-gap: %.1fms", gap_ms)
            self._viz_trace_last_render_ts = now
        w = int(self.get_width() or 0)
        h = int(self.get_height() or 0)
        if w <= 1 or h <= 1:
            return True

        scale = max(1, int(self.get_scale_factor() or 1))
        GL.glViewport(0, 0, w * scale, h * scale)
        GL.glClearColor(0.03, 0.04, 0.07, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        GL.glUseProgram(self._program)
        mode = self._effect_mode
        if self._last_logged_mode != mode:
            logger.info("GLArea effect mode: %s (%s)", mode, self.effect_name)
            self._last_logged_mode = mode
        GL.glUniform1i(self._u_mode, mode)
        GL.glUniform1i(self._u_num, int(self.num_bars))

        gain = self._theme_height_gain * self._prof_gain_mul

        h_buf = self._u_heights_buf
        t_buf = self._u_trail_buf
        p_buf = self._u_peak_buf
        n_local = min(self.num_bars, 128)
        sens = self._sensitivity
        cur = self._state_cur_buf if self._rust_state is not None else self.current_heights
        tr = self._state_trail_buf if self._rust_state is not None else self.trail_heights
        pk = self._state_peak_buf if self._rust_state is not None else self.peak_holds
        for i in range(n_local):
            h_buf[i] = max(0.0, min(1.0, cur[i] * gain * sens))
            t_buf[i] = max(0.0, min(1.0, tr[i] * gain * sens))
            p_buf[i] = max(0.0, min(1.0, pk[i] * gain * sens))
        # Clear tail only when needed (bar-count dropped).
        if self._uploaded_count > n_local:
            for i in range(n_local, self._uploaded_count):
                h_buf[i] = 0.0
                t_buf[i] = 0.0
                p_buf[i] = 0.0
        self._uploaded_count = n_local
        # Upload bands as texture (rgb = height/trail/peak), reducing uniform call overhead.
        btex = self._bands_tex_buf
        for i in range(128):
            base = i * 4
            btex[base] = h_buf[i]
            btex[base + 1] = t_buf[i]
            btex[base + 2] = p_buf[i]
            btex[base + 3] = 0.0
        if self._bands_tex is not None and self._u_bands_tex >= 0:
            GL.glActiveTexture(GL.GL_TEXTURE1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._bands_tex)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            GL.glTexSubImage2D(
                GL.GL_TEXTURE_2D,
                0,
                0,
                0,
                128,
                1,
                GL.GL_RGBA,
                GL.GL_FLOAT,
                btex,
            )
            GL.glUniform1i(self._u_bands_tex, 1)
        c0 = self._theme_c0
        c1 = self._theme_c1
        GL.glUniform3f(self._u_c0, float(c0[0]), float(c0[1]), float(c0[2]))
        GL.glUniform3f(self._u_c1, float(c1[0]), float(c1[1]), float(c1[2]))
        GL.glUniform1f(self._u_bass, float(max(0.0, min(1.0, self.bass_level))))
        GL.glUniform1f(self._u_time, float(self.phase))
        GL.glUniform1f(self._u_aspect, float(w) / float(max(1, h)))
        # Dot matrix cell period in normalized Y.
        period = 9.0 / float(max(1, h))
        GL.glUniform1f(self._u_dot_period, float(period))
        # GL dots brick height = 5px (period 9px).
        GL.glUniform1f(self._u_dot_fill, float(5.0 / 9.0))
        # Dots uses tighter horizontal gap; others keep default spacing.
        spacing_px = 1.5 if mode == 2 else 1.5
        fill = 1.0 - (((max(1, self.num_bars) - 1) * spacing_px) / float(max(1, w)))
        fill = max(0.55, min(0.99, fill))
        GL.glUniform1f(self._u_bar_fill, float(fill))

        if mode in (4, 13) and self._water_tex is not None:
            if self._water_dirty:
                import ctypes
                arr = (ctypes.c_ubyte * len(self._water_data)).from_buffer_copy(self._water_data)
                GL.glActiveTexture(GL.GL_TEXTURE0)
                GL.glBindTexture(GL.GL_TEXTURE_2D, self._water_tex)
                GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
                GL.glTexSubImage2D(
                    GL.GL_TEXTURE_2D,
                    0,
                    0,
                    0,
                    self._water_w,
                    self._water_h,
                    GL.GL_RGBA,
                    GL.GL_UNSIGNED_BYTE,
                    arr,
                )
                self._water_dirty = False
            else:
                GL.glActiveTexture(GL.GL_TEXTURE0)
                GL.glBindTexture(GL.GL_TEXTURE_2D, self._water_tex)
            GL.glUniform1i(self._u_water_tex, 0)
            GL.glUniform1f(self._u_water_head, float(self._water_head_idx) / float(max(1, self._water_w)))
            GL.glUniform1f(self._u_water_gain, 1.0)
        else:
            GL.glUniform1f(self._u_water_head, 0.0)
            GL.glUniform1f(self._u_water_gain, 1.0)

        GL.glBindVertexArray(self._vao)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glBindVertexArray(0)
        GL.glActiveTexture(GL.GL_TEXTURE1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        GL.glUseProgram(0)
        return True
