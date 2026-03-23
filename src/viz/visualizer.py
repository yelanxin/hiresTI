import gi
import os
import sys
import ctypes

_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
import cairo
import math
import logging
from _rust.viz import RustVizCore

try:
    from OpenGL import GL
    from OpenGL.GL import shaders as gl_shaders
except Exception:
    GL = None
    gl_shaders = None

logger = logging.getLogger(__name__)

_FREQ_SCALE_LINEAR = "Linear"
_FREQ_SCALE_LOG = "Log"
_FREQ_SCALE_NAMES = [_FREQ_SCALE_LINEAR, _FREQ_SCALE_LOG]
_SPECTRUM_HALF_RATE_HZ = 22050.0
_DEFAULT_SPECTRUM_BANDS = 512
_LINEAR_ANALYSIS_BANDS = 512
_LINEAR_DISPLAY_ZOOM = 1.0
_LOG_DISPLAY_MIN_FREQ_HZ = 100.0
_LOG_DISPLAY_MAX_FREQ_HZ = 16000.0
_LEGACY_LOG_BIN_EXPONENT = 2.15


def _normalize_spectrum_magnitudes(values, db_min=-80.0, db_range=80.0):
    vals = list(values or [])
    if not vals:
        return []
    out = [0.0] * len(vals)
    for i, val in enumerate(vals):
        if val <= db_min:
            h = 0.0
        else:
            h = (val - db_min) / db_range
        # gamma=1.5: compresses the low-level noise floor toward zero while
        # keeping the main musical content range (~-30..0 dBFS) nearly identical
        # to the old linear -60/60 mapping.
        out[i] = max(0.0, min(1.0, h)) ** 1.5
    return out


def _resample_linear_values(values, out_count, use_peak=False):
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
        if use_peak:
            peak = 0.0
            for j in range(x0, x1):
                v = float(vals[j])
                if v > peak:
                    peak = v
            out[i] = peak
        else:
            s = 0.0
            c = 0
            for j in range(x0, x1):
                s += float(vals[j])
                c += 1
            out[i] = (s / float(c)) if c > 0 else 0.0
    return out


def _build_linear_spectrum_bins(
    values,
    out_count,
    rust_core=None,
    analysis_bands=_LINEAR_ANALYSIS_BANDS,
    db_min=-80.0,
    db_range=80.0,
    half_rate_hz=_SPECTRUM_HALF_RATE_HZ,
):
    vals = list(values or [])
    if out_count <= 0:
        return []
    if not vals:
        return [0.0] * out_count

    analysis_n = max(1, int(analysis_bands))
    base = None
    if rust_core is not None and getattr(rust_core, "available", False):
        try:
            base = rust_core.process_spectrum(
                vals,
                analysis_n,
                db_min=db_min,
                db_range=db_range,
            )
        except Exception:
            base = None
    if base is None:
        base = _resample_linear_values(
            _normalize_spectrum_magnitudes(vals, db_min=db_min, db_range=db_range),
            analysis_n,
        )
    if out_count == analysis_n:
        return list(base or [])
    # Blend peak and mean aggregation: peak preserves sparse mid/high-freq tones
    # while mean smooths out transient jumpiness.  60% peak + 40% mean gives
    # similar reactivity to log mode without fully diluting narrow-bin signals.
    out_peak = _resample_linear_values(base or [], out_count, use_peak=True)
    out_mean = _resample_linear_values(base or [], out_count, use_peak=False)
    out = [p * 0.6 + m * 0.4 for p, m in zip(out_peak, out_mean)]
    # Apply per-bar voicing: rolls off bass (prevents peak saturation) and
    # boosts mid/high (compensates for narrow-bin bandwidth vs 96-band FFT).
    for i in range(out_count):
        center_f = (i + 0.5) / float(out_count) * half_rate_hz
        out[i] = min(1.0, out[i] * _linear_display_voicing(center_f, half_rate_hz))
    return out


def _interpolate_series_value(values, pos):
    vals = list(values or [])
    if not vals:
        return 0.0
    if len(vals) == 1:
        return float(vals[0])
    p = max(0.0, min(float(len(vals) - 1), float(pos)))
    i0 = int(math.floor(p))
    i1 = min(len(vals) - 1, i0 + 1)
    frac = p - float(i0)
    return (float(vals[i0]) * (1.0 - frac)) + (float(vals[i1]) * frac)


def _spectrum_frequency_range(total_bands, half_rate_hz=_SPECTRUM_HALF_RATE_HZ):
    try:
        bands = int(total_bands)
    except Exception:
        bands = 0
    if bands <= 1:
        return (20.0, min(20000.0, float(half_rate_hz)))
    band_hz = float(half_rate_hz) / float(bands)
    min_f = max(20.0, band_hz)
    max_f = min(20000.0, band_hz * float(bands - 1))
    if max_f <= min_f:
        max_f = max(min_f, float(half_rate_hz))
    return (min_f, max_f)


def _linear_display_frequency_range(total_bands, half_rate_hz=_SPECTRUM_HALF_RATE_HZ):
    _base_min, base_max = _spectrum_frequency_range(total_bands, half_rate_hz=half_rate_hz)
    return (0.0, base_max)


def _display_gain_multiplier(freq_scale_name):
    if freq_scale_name == _FREQ_SCALE_LINEAR:
        return _LINEAR_DISPLAY_ZOOM
    return 1.0


def _linear_display_voicing(freq_hz, half_rate_hz=_SPECTRUM_HALF_RATE_HZ):
    """Per-bar frequency compensation for linear mode with 512-band FFT.

    512-band FFT bins are ~5x narrower than the 96-band bins the display was
    originally calibrated for.  Two opposing effects arise:
      - Bass: many adjacent dense bins → peak aggregation yields high values
              → needs rolloff to prevent clipping.
      - Mid/high: narrow sparse bins carry less energy than wide 96-band bins
              → needs a boost that grows with frequency.

    Curve: 0.55 at 20 Hz, 1.0 at 1 kHz, 2.0 at Nyquist.
    """
    f = max(20.0, float(freq_hz))
    if f < 1000.0:
        # Gentle bass rolloff: 20 Hz → 0.55, 1 kHz → 1.0
        t = math.log10(f / 20.0) / math.log10(1000.0 / 20.0)
        return 0.55 + 0.45 * t
    # High-end boost: 1 kHz → 1.0, Nyquist → 1.2
    log_max = math.log10(max(1001.0, float(half_rate_hz)) / 1000.0)
    t = math.log10(f / 1000.0) / log_max if log_max > 1e-9 else 0.0
    return 1.0 + 0.2 * min(1.0, t)


def _log_display_frequency_range(total_bands, half_rate_hz=_SPECTRUM_HALF_RATE_HZ):
    base_min, base_max = _spectrum_frequency_range(total_bands, half_rate_hz=half_rate_hz)
    min_f = max(base_min, _LOG_DISPLAY_MIN_FREQ_HZ)
    max_f = min(base_max, _LOG_DISPLAY_MAX_FREQ_HZ)
    if max_f <= min_f:
        return (base_min, base_max)
    return (min_f, max_f)


def _log_display_eq_gain(freq_hz):
    # Perceptual voicing: approximates the inverse of the equal-loudness
    # contour (ISO 226) at a comfortable listening level (~70 phon).
    # Reduces bass and very high frequencies, peaks around 3-4 kHz where
    # the human ear is most sensitive.
    f = max(20.0, float(freq_hz))
    if f < 200.0:
        # 50 Hz → 0.45, 200 Hz → 0.72 (log-interpolated)
        t = math.log10(f / 20.0) / math.log10(200.0 / 20.0)
        return 0.30 + 0.42 * t
    if f < 1000.0:
        # 200 Hz → 0.72, 1 kHz → 0.92
        t = math.log10(f / 200.0) / math.log10(1000.0 / 200.0)
        return 0.72 + 0.20 * t
    if f < 3500.0:
        # 1 kHz → 0.92, 3.5 kHz → 1.05 (ear sensitivity peak)
        t = math.log10(f / 1000.0) / math.log10(3500.0 / 1000.0)
        return 0.92 + 0.13 * t
    if f < 8000.0:
        # 3.5 kHz → 1.05, 8 kHz → 0.90
        t = math.log10(f / 3500.0) / math.log10(8000.0 / 3500.0)
        return 1.05 - 0.15 * t
    # 8 kHz → 0.90, 16 kHz → 0.68
    t = math.log10(f / 8000.0) / math.log10(16000.0 / 8000.0)
    return max(0.50, 0.90 - 0.22 * t)


def _draw_freq_axis_cairo(cr, width, height, frequency_scale_name,
                          input_band_count=_DEFAULT_SPECTRUM_BANDS):
    """Draw 9 evenly-spaced frequency tick marks and labels along the top edge.

    Standalone version of SpectrumVisualizer._draw_freq_axis so it can be
    reused by the GL overlay in HybridVisualizer.
    """
    TICKS = 9
    HALF_RATE = _SPECTRUM_HALF_RATE_HZ
    TOTAL_BANDS = float(max(2, int(input_band_count or _DEFAULT_SPECTRUM_BANDS)))
    if frequency_scale_name == _FREQ_SCALE_LOG:
        min_f, max_f = _log_display_frequency_range(int(TOTAL_BANDS), half_rate_hz=HALF_RATE)
        log_min = math.log10(min_f)
        log_span = math.log10(max_f) - log_min
    else:
        min_f, max_f = _linear_display_frequency_range(int(TOTAL_BANDS), half_rate_hz=HALF_RATE)

    TICK_H = 4.0
    LABEL_FONT = 9.0
    LABEL_Y = TICK_H + LABEL_FONT + 1.0
    TICK_ALPHA = 0.45
    LABEL_ALPHA = 0.60

    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(LABEL_FONT)

    for k in range(TICKS):
        p = k / float(TICKS - 1)
        x = p * width
        if frequency_scale_name == _FREQ_SCALE_LOG:
            freq = 10.0 ** (log_min + (p * log_span))
        else:
            freq = min_f + (p * (max_f - min_f))

        if freq >= 1000.0:
            kv = freq / 1000.0
            label = f"{kv:.0f}k" if kv >= 10.0 else f"{kv:.1f}k"
        else:
            label = f"{freq:.0f}"

        ext = cr.text_extents(label)
        tx = x - ext.width * 0.5
        tx = max(1.0, min(width - ext.width - 1.0, tx))

        cr.set_source_rgba(1.0, 1.0, 1.0, TICK_ALPHA)
        cr.set_line_width(1.0)
        cr.move_to(x, 0.0)
        cr.line_to(x, TICK_H)
        cr.stroke()

        cr.set_source_rgba(1.0, 1.0, 1.0, LABEL_ALPHA)
        cr.move_to(tx, LABEL_Y)
        cr.show_text(label)


def _build_log_spectrum_bins(values, out_count, half_rate_hz=_SPECTRUM_HALF_RATE_HZ):
    vals = list(values or [])
    if out_count <= 0:
        return []
    if not vals:
        return [0.0] * out_count
    if len(vals) <= 1:
        return [float(vals[0])] * out_count

    # Band 0 is the DC component. Keep log mode aligned with the normal
    # spectrum path by skipping it when real spectrum bands are provided.
    usable = vals[1:] if len(vals) > 1 else vals
    if not usable:
        return [0.0] * out_count
    if len(usable) == 1:
        return [float(usable[0])] * out_count

    total_bands = len(vals)
    band_hz = float(half_rate_hz) / max(1.0, float(total_bands))
    min_f, max_f = _log_display_frequency_range(total_bands, half_rate_hz=half_rate_hz)
    if max_f <= min_f:
        return _resample_linear_values(usable, out_count)

    log_min = math.log10(min_f)
    log_span = math.log10(max_f) - log_min
    if log_span <= 1e-9:
        return _resample_linear_values(usable, out_count)

    out = [0.0] * out_count
    for i in range(out_count):
        t0 = i / float(out_count)
        t1 = (i + 1) / float(out_count)
        log_f0 = log_min + (t0 * log_span)
        log_f1 = log_min + (t1 * log_span)
        f0 = 10.0 ** log_f0
        f1 = 10.0 ** log_f1
        pos0 = max(0.0, (f0 / band_hz) - 1.0)
        pos1 = max(pos0 + 1e-6, (f1 / band_hz) - 1.0)
        sample_count = max(4, min(48, int(math.ceil((pos1 - pos0) * 4.0))))
        sum_sq = 0.0
        peak = 0.0
        for s in range(sample_count):
            t = (s + 0.5) / float(sample_count)
            pos = pos0 + ((pos1 - pos0) * t)
            v = _interpolate_series_value(usable, pos)
            sum_sq += v * v
            if v > peak:
                peak = v
        rms = math.sqrt(sum_sq / float(sample_count))
        center_f = math.sqrt(f0 * f1)  # geometric mean → log-scale centre freq
        voiced = ((rms * 0.90) + (peak * 0.10)) * _log_display_eq_gain(center_f)
        out[i] = max(0.0, min(1.0, voiced))
    return out


def _build_log_bins_python(values, out_count):
    in_count = len(values)
    if in_count <= 0 or out_count <= 0:
        return []
    out = [0.0] * out_count
    for i in range(out_count):
        t0 = i / float(out_count)
        t1 = (i + 1) / float(out_count)
        x0 = int(pow(t0, _LEGACY_LOG_BIN_EXPONENT) * (in_count - 1))
        x1 = int(pow(t1, _LEGACY_LOG_BIN_EXPONENT) * (in_count - 1))
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
        self.frequency_scale_name = _FREQ_SCALE_LINEAR
        self.frequency_scale_names = list(_FREQ_SCALE_NAMES)
        self._input_band_count = _DEFAULT_SPECTRUM_BANDS
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
                "smooth": 0.12,
                "trail_decay": 0.975,
                "peak_hold_frames": 29,
                "peak_fall": 0.005,
                "beat_mul": 0.34,
            },
            "Soft": {
                "gain_mul": 0.84,
                "spacing_mul": 1.08,
                "grid_mul": 0.85,
                "smooth": 0.17,
                "trail_decay": 0.965,
                "peak_hold_frames": 25,
                "peak_fall": 0.007,
                "beat_mul": 0.41,
            },
            "Dynamic": {
                "gain_mul": 1.0,
                "spacing_mul": 1.0,
                "grid_mul": 1.0,
                "smooth": 0.26,
                "trail_decay": 0.951,
                "peak_hold_frames": 17,
                "peak_fall": 0.010,
                "beat_mul": 0.55,
            },
            "Extreme": {
                "gain_mul": 1.18,
                "spacing_mul": 0.92,
                "grid_mul": 1.18,
                "smooth": 0.34,
                "trail_decay": 0.935,
                "peak_hold_frames": 12,
                "peak_fall": 0.015,
                "beat_mul": 0.69,
            },
            "Insane": {
                "gain_mul": 1.32,
                "spacing_mul": 0.88,
                "grid_mul": 1.28,
                "smooth": 0.39,
                "trail_decay": 0.918,
                "peak_hold_frames": 8,
                "peak_fall": 0.019,
                "beat_mul": 0.80,
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

    def get_frequency_scale_names(self):
        return list(self.frequency_scale_names)

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

    def set_frequency_scale(self, scale_name):
        if scale_name in self.frequency_scale_names:
            self.frequency_scale_name = scale_name
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
        if self.frequency_scale_name == _FREQ_SCALE_LOG:
            return _build_log_spectrum_bins(_normalize_spectrum_magnitudes(vals), self.num_bars)
        if use_rust and self._rust_core.available and log_rust and not self._logged_rust_path:
            logger.info("Spectrum preprocessing path: Rust")
            self._logged_rust_path = True
        if (not use_rust or not self._rust_core.available) and not self._logged_python_fallback:
            logger.info("Spectrum preprocessing path: Python fallback")
            self._logged_python_fallback = True
        return _build_linear_spectrum_bins(
            vals,
            self.num_bars,
            rust_core=self._rust_core if use_rust else None,
            analysis_bands=_LINEAR_ANALYSIS_BANDS,
            db_min=-80.0,
            db_range=80.0,
        )

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
            mono_vals = magnitudes.get("mono") or magnitudes.get("left") or magnitudes.get("right") or ()
            left_vals = magnitudes.get("left") or mono_vals
            right_vals = magnitudes.get("right") or mono_vals
        else:
            mono_vals = magnitudes
            left_vals = magnitudes
            right_vals = magnitudes

        try:
            actual_count = int(len(mono_vals))
        except Exception:
            actual_count = 0
        if actual_count > 1:
            self._input_band_count = actual_count
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

        # Opaque black background (matches GL renderers).
        cr.set_source_rgba(0.0, 0.0, 0.0, 1.0)
        cr.paint()

        n = self.num_bars
        spacing = max(0.8, theme["bar_spacing"] * float(profile["spacing_mul"]))
        gain = theme["height_gain"] * float(profile["gain_mul"])
        gain *= _display_gain_multiplier(self.frequency_scale_name)
        bar_w = max(1.0, (width - (n - 1) * spacing) / n)
        effect = self._effect_code
        if effect not in (14, 15, 16, 17, 18, 20, 21, 22, 23, 24, 25, 26):
            self._draw_freq_axis(cr, width, height)
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

    def _draw_freq_axis(self, cr, width, height):
        band_count = int(getattr(self, "_input_band_count", _DEFAULT_SPECTRUM_BANDS) or _DEFAULT_SPECTRUM_BANDS)
        _draw_freq_axis_cairo(cr, width, height, self.frequency_scale_name, band_count)

    def _make_gradient(self, height, theme):
        key = (height, self.theme_name)
        if getattr(self, "_gradient_cache_key", None) != key:
            gradient = cairo.LinearGradient(0, 0, 0, height)
            for stop, rgba in theme["gradient"]:
                gradient.add_color_stop_rgba(stop, *rgba)
            self._gradient_cache = gradient
            self._gradient_cache_key = key
        return self._gradient_cache

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
        return _build_log_bins_python(values, out_count)

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


# ---------------------------------------------------------------------------
# GL-accelerated Dots visualizer
# ---------------------------------------------------------------------------

_DOTS_VERT_330 = """
#version 330 core
layout (location = 0) in vec2 aPos;
out vec2 vUV;
void main() {
    vUV = (aPos + 1.0) * 0.5;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

_DOTS_FRAG_330 = """
#version 330 core
in vec2 vUV;
out vec4 FragColor;
const int MAX_BARS = 512;
uniform int   uNumBars;
uniform float uHeights[MAX_BARS];
uniform vec4  uColors[MAX_BARS];
uniform float uGain;
uniform float uSpacingPx;
uniform vec2  uResolution;
const float DOT_H = 4.0;
const float GAP   = 3.0;
void main() {
    float x_px            = vUV.x * uResolution.x;
    float y_from_bot_px   = vUV.y * uResolution.y;
    float slot_w          = uResolution.x / float(uNumBars);
    int   bar_i           = int(x_px / slot_w);
    if (bar_i >= uNumBars) discard;
    float pos_in_slot     = x_px - float(bar_i) * slot_w;
    if (pos_in_slot >= max(1.0, slot_w - uSpacingPx)) discard;
    float h_px = clamp(uHeights[bar_i] * uResolution.y * uGain, 0.0, uResolution.y);
    if (y_from_bot_px >= h_px) discard;
    if (mod(y_from_bot_px, DOT_H + GAP) >= DOT_H) discard;
    FragColor = uColors[bar_i];
}
"""

_DOTS_VERT_300ES = """
#version 300 es
layout (location = 0) in vec2 aPos;
out vec2 vUV;
void main() {
    vUV = (aPos + 1.0) * 0.5;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

_DOTS_FRAG_300ES = """
#version 300 es
precision mediump float;
in vec2 vUV;
out vec4 FragColor;
const int MAX_BARS = 512;
uniform int   uNumBars;
uniform float uHeights[MAX_BARS];
uniform vec4  uColors[MAX_BARS];
uniform float uGain;
uniform float uSpacingPx;
uniform vec2  uResolution;
const float DOT_H = 4.0;
const float GAP   = 3.0;
void main() {
    float x_px          = vUV.x * uResolution.x;
    float y_from_bot_px = vUV.y * uResolution.y;
    float slot_w        = uResolution.x / float(uNumBars);
    int   bar_i         = int(x_px / slot_w);
    if (bar_i >= uNumBars) discard;
    float pos_in_slot   = x_px - float(bar_i) * slot_w;
    if (pos_in_slot >= max(1.0, slot_w - uSpacingPx)) discard;
    float h_px = clamp(uHeights[bar_i] * uResolution.y * uGain, 0.0, uResolution.y);
    if (y_from_bot_px >= h_px) discard;
    if (mod(y_from_bot_px, DOT_H + GAP) >= DOT_H) discard;
    FragColor = uColors[bar_i];
}
"""


class DotsGLVisualizer(Gtk.GLArea):
    """
    GL-accelerated Dots spectrum visualizer.
    Implements the same public interface as SpectrumVisualizer so it can be
    used as a drop-in replacement when testing GL rendering performance.
    Falls back to raising RuntimeError on construction if PyOpenGL is absent.
    """

    # Reuse the same theme/profile tables as SpectrumVisualizer.
    _THEMES = None   # populated lazily from SpectrumVisualizer instance
    _PROFILES = None

    def __init__(self):
        if GL is None or gl_shaders is None:
            raise RuntimeError("PyOpenGL not available for DotsGLVisualizer")
        super().__init__()

        # Borrow theme/profile data from SpectrumVisualizer without rendering.
        _sv = SpectrumVisualizer.__new__(SpectrumVisualizer)
        _sv.__init__()          # full init so themes/profiles are populated
        self.themes   = _sv.themes
        self.profiles = _sv.profiles
        self._rust_core = _sv._rust_core

        self.num_bars     = 32
        self.theme_name   = "Aurora (Default)"
        self.profile_name = "Dynamic"
        self.frequency_scale_name = _FREQ_SCALE_LINEAR
        self.frequency_scale_names = list(_FREQ_SCALE_NAMES)
        self._input_band_count = _DEFAULT_SPECTRUM_BANDS
        self._theme_cfg   = self.themes[self.theme_name]
        self._profile_cfg = self.profiles[self.profile_name]

        self.target_heights  = [0.0] * 512
        self.current_heights = [0.0] * 512
        self._active      = False
        self._anim_source = None

        # GL state
        self._program     = None
        self._vao         = None
        self._vbo         = None
        self._gl_failed   = False
        self._u_num_bars  = -1
        self._u_heights   = -1
        self._u_colors    = -1
        self._u_gain      = -1
        self._u_spacing   = -1
        self._u_resolution = -1

        # Precomputed per-bar colors (invalidated on theme/num_bars change)
        self._color_cache     = None
        self._color_cache_key = None
        self._logged_rust_bins = False
        self._logged_python_bins = False

        # Pre-allocated ctypes arrays reused every frame to avoid GC churn
        self._h_arr = (ctypes.c_float * 512)(*([0.0] * 512))
        self._c_arr = (ctypes.c_float * 2048)(*([0.0] * 2048))

        # Cached per-frame scalars — recomputed only on theme/profile change
        self._cached_gain    = 0.0
        self._cached_spacing = 0.0
        self._cached_w       = -1
        self._cached_h       = -1
        # True when num_bars/colors/gain/spacing need re-upload to GPU
        self._dirty_static   = True

        self.set_auto_render(False)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.connect("realize",   self._on_realize)
        self.connect("unrealize", self._on_unrealize)
        self.connect("render",    self._on_render)
        logger.info("Visualizer backend selected: GL (Dots)")

    # ------------------------------------------------------------------
    # GL lifecycle
    # ------------------------------------------------------------------

    def _on_realize(self, _area):
        self.make_current()
        if self.get_error() is not None:
            logger.warning("DotsGL realize error: %s", self.get_error())
            self._gl_failed = True
            return
        try:
            self._setup_gl()
            self._update_render_cache()
        except Exception:
            logger.exception("DotsGL setup failed")
            self._gl_failed = True

    def _on_unrealize(self, _area):
        self.make_current()
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
        err = None
        for label, vs, fs in [
            ("330 core", _DOTS_VERT_330, _DOTS_FRAG_330),
            ("300 es",   _DOTS_VERT_300ES, _DOTS_FRAG_300ES),
        ]:
            try:
                self._program = gl_shaders.compileProgram(
                    gl_shaders.compileShader(vs, GL.GL_VERTEX_SHADER),
                    gl_shaders.compileShader(fs, GL.GL_FRAGMENT_SHADER),
                )
                logger.info("DotsGL shader: GLSL %s", label)
                break
            except Exception as e:
                err = e
        if self._program is None:
            raise RuntimeError(f"DotsGL shader compile failed: {err}")

        p = self._program
        self._u_num_bars   = GL.glGetUniformLocation(p, "uNumBars")
        self._u_heights    = GL.glGetUniformLocation(p, "uHeights")
        self._u_colors     = GL.glGetUniformLocation(p, "uColors")
        self._u_gain       = GL.glGetUniformLocation(p, "uGain")
        self._u_spacing    = GL.glGetUniformLocation(p, "uSpacingPx")
        self._u_resolution = GL.glGetUniformLocation(p, "uResolution")

        # Fullscreen quad
        verts = (-1.0, -1.0, 1.0, -1.0, -1.0, 1.0, 1.0, 1.0)
        arr   = (ctypes.c_float * 8)(*verts)
        self._vao = GL.glGenVertexArrays(1)
        self._vbo = GL.glGenBuffers(1)
        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, ctypes.sizeof(arr), arr, GL.GL_STATIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glBindVertexArray(0)

    def _on_render(self, _area, _context):
        if self._gl_failed or self._program is None:
            return True
        w = int(self.get_width()  or 0)
        h = int(self.get_height() or 0)
        if w < 1 or h < 1:
            return True

        scale = max(1, int(self.get_scale_factor() or 1))
        GL.glViewport(0, 0, w * scale, h * scale)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        GL.glUseProgram(self._program)

        # Re-upload static uniforms only when theme/profile/size changed
        if self._dirty_static or w != self._cached_w or h != self._cached_h:
            self._cached_w = w
            self._cached_h = h
            self._get_colors()   # rebuilds _c_arr if theme/bars changed
            GL.glUniform1i (self._u_num_bars,   self.num_bars)
            GL.glUniform4fv(self._u_colors,     512, self._c_arr)
            GL.glUniform1f (self._u_gain,       self._cached_gain)
            GL.glUniform1f (self._u_spacing,    self._cached_spacing)
            GL.glUniform2f (self._u_resolution, float(w), float(h))
            self._dirty_static = False

        # Heights change every animated frame
        self._h_arr[:512] = self.current_heights[:512]
        GL.glUniform1fv(self._u_heights, 512, self._h_arr)

        GL.glBindVertexArray(self._vao)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glBindVertexArray(0)
        GL.glUseProgram(0)
        return True

    # ------------------------------------------------------------------
    # Animation tick (height smoothing, same rate as SpectrumVisualizer)
    # ------------------------------------------------------------------

    def _on_animation_tick(self):
        if not self._active:
            self._anim_source = None
            return False
        smooth = float(self._profile_cfg["smooth"])
        changed = False
        for i in range(self.num_bars):
            diff = self.target_heights[i] - self.current_heights[i]
            if abs(diff) > 0.001:
                self.current_heights[i] += diff * smooth
                changed = True
        if changed:
            self.queue_render()
        return True

    # ------------------------------------------------------------------
    # Color cache
    # ------------------------------------------------------------------

    def _get_colors(self):
        key = (self.theme_name, self.num_bars)
        if self._color_cache_key != key or self._color_cache is None:
            grad = self._theme_cfg["gradient"]
            n    = self.num_bars
            self._color_cache = [
                self._color_from_gradient(grad, i / float(max(1, n - 1)))
                for i in range(n)
            ]
            self._color_cache_key = key
            # Rebuild the pre-allocated flat ctypes array (vec4 × 512)
            off = 0
            for r, g, b, a in self._color_cache:
                self._c_arr[off]     = r
                self._c_arr[off + 1] = g
                self._c_arr[off + 2] = b
                self._c_arr[off + 3] = a
                off += 4
            # Zero-pad remaining slots
            for i in range(off, 2048):
                self._c_arr[i] = 0.0
        return self._color_cache

    @staticmethod
    def _color_from_gradient(gradient, t):
        t = max(0.0, min(1.0, t))
        prev_stop, prev_rgba = gradient[0]
        for stop, rgba in gradient[1:]:
            if t <= stop:
                span = max(1e-6, stop - prev_stop)
                w = (t - prev_stop) / span
                return tuple(prev_rgba[i] + (rgba[i] - prev_rgba[i]) * w for i in range(4))
            prev_stop, prev_rgba = stop, rgba
        return gradient[-1][1]

    # ------------------------------------------------------------------
    # Public API (mirrors SpectrumVisualizer)
    # ------------------------------------------------------------------

    def set_active(self, active):
        active = bool(active)
        if self._active == active:
            return
        self._active = active
        if active:
            if self._anim_source is None:
                self._anim_source = GLib.timeout_add(16, self._on_animation_tick)
            self.queue_render()
        else:
            if self._anim_source:
                try:
                    GLib.source_remove(self._anim_source)
                except Exception:
                    pass
                self._anim_source = None

    def update_data(self, magnitudes):
        if not magnitudes:
            return
        if isinstance(magnitudes, dict):
            vals = magnitudes.get("mono") or magnitudes.get("left") or ()
        else:
            vals = magnitudes
        vals = list(vals or [])
        if len(vals) > 1:
            self._input_band_count = len(vals)
        if self.frequency_scale_name == _FREQ_SCALE_LOG:
            new_heights = _build_log_spectrum_bins(_normalize_spectrum_magnitudes(vals), self.num_bars)
            self.target_heights[:self.num_bars] = new_heights[:self.num_bars]
            return
        new_heights = _build_linear_spectrum_bins(
            vals,
            self.num_bars,
            rust_core=self._rust_core,
            analysis_bands=_LINEAR_ANALYSIS_BANDS,
            db_min=-80.0,
            db_range=80.0,
        )
        self.target_heights[:self.num_bars] = new_heights[:self.num_bars]

    def _build_log_bins(self, values, out_count):
        if self._rust_core.available:
            out = self._rust_core.build_log_bins(values, out_count)
            if out is not None:
                if not self._logged_rust_bins:
                    logger.info("DotsGL log-bin preprocessing path: Rust")
                    self._logged_rust_bins = True
                return out
        if not self._logged_python_bins:
            logger.info("DotsGL log-bin preprocessing path: Python fallback")
            self._logged_python_bins = True
        return _build_log_bins_python(values, out_count)

    def _update_render_cache(self):
        """Recompute cached scalars and mark static uniforms dirty."""
        self._cached_gain    = (
            float(self._theme_cfg["height_gain"])
            * float(self._profile_cfg["gain_mul"])
            * _display_gain_multiplier(self.frequency_scale_name)
        )
        self._cached_spacing = max(0.8, float(self._theme_cfg["bar_spacing"]) * float(self._profile_cfg["spacing_mul"]))
        self._dirty_static   = True

    def set_num_bars(self, count):
        try:
            n = int(count)
        except Exception:
            return
        if n <= 0 or n == self.num_bars:
            return
        self.num_bars = min(n, 512)
        self.target_heights  = [0.0] * 512
        self.current_heights = [0.0] * 512
        self._color_cache    = None
        self._dirty_static   = True

    def set_theme(self, name):
        if name in self.themes:
            self.theme_name = name
            self._theme_cfg = self.themes[name]
            self._color_cache = None
            self._update_render_cache()

    def set_effect(self, _name):
        pass   # DotsGLVisualizer only renders Dots

    def set_frequency_scale(self, name):
        if name in self.frequency_scale_names:
            self.frequency_scale_name = name
            self._update_render_cache()
            self.queue_render()

    def set_profile(self, name):
        if name in self.profiles:
            self.profile_name = name
            self._profile_cfg = self.profiles[name]
            self._update_render_cache()

    def get_theme_names(self):
        return list(self.themes.keys())

    def get_effect_names(self):
        return ["Dots"]

    def get_profile_names(self):
        return list(self.profiles.keys())

    def get_frequency_scale_names(self):
        return list(self.frequency_scale_names)


# ---------------------------------------------------------------------------
# GL-accelerated Bars / Peak / Trail visualizer
# ---------------------------------------------------------------------------

# Vertex shader is identical to Dots — fullscreen NDC quad passthrough.
_BARS_VERT_330 = """
#version 330 core
layout (location = 0) in vec2 aPos;
out vec2 vUV;
void main() {
    vUV = (aPos + 1.0) * 0.5;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

_BARS_FRAG_330 = """
#version 330 core
in vec2 vUV;
out vec4 FragColor;
const int MAX_BARS = 512;
uniform int   uNumBars;
uniform float uHeights[MAX_BARS];
uniform float uPeakHeights[MAX_BARS];
uniform float uTrailHeights[MAX_BARS];
uniform float uLeftHeights[MAX_BARS];
uniform float uRightHeights[MAX_BARS];
uniform vec4  uColors[MAX_BARS];
uniform vec4  uTopColor;
uniform vec4  uBottomColor;
uniform vec4  uPulseColor;
uniform float uGain;
uniform float uSpacingPx;
uniform float uBassLevel;
uniform vec2  uResolution;
uniform float uBalance;
uniform int   uMode;  // 0=Bars 1=Peak 2=Trail 3=Mirror 4=Wave 5=Fill 6=Pulse 7=StereoMirror 8=Stereo 9=Burst 10=BalanceWave 11=CenterSide
const float CAP_H   = 3.0;
const float WAVE_HW = 2.0;
const float PI      = 3.14159265;
// Pixel-font glyphs: 5 rows x 4 cols packed as row0 in bits[3:0], row1 in bits[7:4], ...
// Within each row: bit3=leftmost col, bit0=rightmost col.
const int CHAR_L = 1017992;  // rows: 8,8,8,8,15
const int CHAR_R = 642718;   // rows: 14,9,14,12,9
const int CHAR_M = 629241;   // rows: 9,15,9,9,9
const int CHAR_I = 934990;   // rows: 14,4,4,4,14
const int CHAR_D = 956830;   // rows: 14,9,9,9,14
const int CHAR_S = 923271;   // rows: 7,8,6,1,14
const int CHAR_E = 1019535;  // rows: 15,8,14,8,15
// Returns 1.0 if pixel (px,py) falls on glyph drawn at (cx, cy_bot) with pixel scale sc.
float sampleGlyph(float px, float py, float cx, float cy_bot, float sc, int glyph) {
    float lx = (px - cx) / sc;
    float ly = (cy_bot + 5.0*sc - py) / sc;  // row 0 = top
    if (lx < 0.0 || lx >= 4.0 || ly < 0.0 || ly >= 5.0) return 0.0;
    int bit = (3 - int(lx)) + int(ly) * 4;
    return float((glyph >> bit) & 1);
}
void main() {
    float x_px          = vUV.x * uResolution.x;
    float y_from_bot_px = vUV.y * uResolution.y;
    // Stereo: L channel left half, R channel right half, balance ball at top
    if (uMode == 8) {
        float half8  = uResolution.x * 0.5;
        float gap8   = 8.0;
        int   half_n = max(1, uNumBars / 2);
        float bars_w = half8 - gap8;
        float max_h8 = uResolution.y * 0.92;
        // Balance ball and meter (drawn on top of everything)
        float meter_w  = min(120.0, uResolution.x * 0.16);
        float meter_y  = uResolution.y * 0.92;
        float marker_x = half8 + uBalance * meter_w * 0.5;
        float ball_d   = length(vec2(x_px - marker_x, y_from_bot_px - meter_y));
        if (ball_d < 4.5) {
            FragColor = vec4(1.0, 1.0, 1.0, 0.72);
            return;
        }
        if (ball_d < 10.0) {
            vec4 gc = uBalance >= 0.0 ? uTopColor : uBottomColor;
            FragColor = vec4(gc.rgb, 0.22 * (1.0 - (ball_d - 4.5) / 5.5));
            return;
        }
        // Meter track line
        float meter_l = half8 - meter_w * 0.5;
        float meter_r = half8 + meter_w * 0.5;
        if (abs(y_from_bot_px - meter_y) < 0.5 && x_px >= meter_l && x_px <= meter_r) {
            FragColor = vec4(1.0, 1.0, 1.0, 0.10);
            return;
        }
        // Center tick on meter
        if (abs(x_px - half8) < 0.5 && abs(y_from_bot_px - meter_y) < 5.0) {
            FragColor = vec4(1.0, 1.0, 1.0, 0.10);
            return;
        }
        // Center divider line
        if (abs(x_px - half8) < 0.5) {
            FragColor = vec4(1.0, 1.0, 1.0, 0.08);
            return;
        }
        // L bars (uTopColor)
        if (x_px < half8 - gap8) {
            float sw8 = bars_w / float(half_n);
            int   bi8 = int(x_px / sw8);
            if (bi8 >= half_n) discard;
            if (x_px - float(bi8) * sw8 >= max(1.0, sw8 - uSpacingPx)) discard;
            if (y_from_bot_px >= clamp(uLeftHeights[bi8] * uGain, 0.0, 1.0) * max_h8) discard;
            FragColor = uTopColor;
        // R bars (uBottomColor)
        } else if (x_px > half8 + gap8) {
            float local_x = x_px - (half8 + gap8);
            float sw8 = bars_w / float(half_n);
            int   bi8 = int(local_x / sw8);
            if (bi8 >= half_n) discard;
            if (local_x - float(bi8) * sw8 >= max(1.0, sw8 - uSpacingPx)) discard;
            if (y_from_bot_px >= clamp(uRightHeights[bi8] * uGain, 0.0, 1.0) * max_h8) discard;
            FragColor = uBottomColor;
        } else { discard; }
        return;
    }
    // Burst: radial spokes from center
    if (uMode == 9) {
        vec2  center9 = uResolution * 0.5;
        vec2  delta9  = vec2(x_px, y_from_bot_px) - center9;
        float dist9   = length(delta9);
        float t9      = (atan(delta9.y, delta9.x) + PI) / (2.0 * PI);
        int   bi9     = clamp(int(t9 * float(uNumBars)), 0, uNumBars - 1);
        float max_r9  = min(uResolution.x, uResolution.y) * 0.46;
        float h9      = clamp(uHeights[bi9] * uGain, 0.0, 1.0) * max_r9;
        if (dist9 >= h9 || h9 < 2.0) discard;
        FragColor = uColors[bi9];
        return;
    }
    // Balance Wave: L (uTopColor) upper lane, R (uBottomColor) lower lane
    if (uMode == 10) {
        float step_bw = uResolution.x / float(max(uNumBars - 1, 1));
        float t_bw    = x_px / step_bw;
        int   i0_bw   = clamp(int(t_bw),     0, uNumBars - 1);
        int   i1_bw   = clamp(int(t_bw) + 1, 0, uNumBars - 1);
        float frac_bw = t_bw - float(i0_bw);
        float lv      = mix(clamp(uLeftHeights[i0_bw]  * uGain, 0.0, 1.0),
                            clamp(uLeftHeights[i1_bw]  * uGain, 0.0, 1.0), frac_bw);
        float rv      = mix(clamp(uRightHeights[i0_bw] * uGain, 0.0, 1.0),
                            clamp(uRightHeights[i1_bw] * uGain, 0.0, 1.0), frac_bw);
        float amp_bw  = uResolution.y * 0.20;
        float tmid_bw = uResolution.y * 0.66;
        float bmid_bw = uResolution.y * 0.30;
        float wave_l  = tmid_bw + (lv - 0.5) * 2.0 * amp_bw;
        float wave_r  = bmid_bw + (rv - 0.5) * 2.0 * amp_bw;
        if (abs(y_from_bot_px - tmid_bw) < 0.6 || abs(y_from_bot_px - bmid_bw) < 0.6) {
            FragColor = vec4(1.0, 1.0, 1.0, 0.06);
            return;
        }
        if (abs(y_from_bot_px - wave_l) <= WAVE_HW) {
            FragColor = vec4(uTopColor.rgb, 0.90);
            return;
        }
        float l_lo = min(wave_l, tmid_bw);
        float l_hi = max(wave_l, tmid_bw);
        if (y_from_bot_px >= l_lo && y_from_bot_px < l_hi) {
            float t_lf = (l_hi - l_lo) > 0.5 ? abs(y_from_bot_px - wave_l) / (l_hi - l_lo) : 0.5;
            FragColor = vec4(uTopColor.rgb, mix(0.18, 0.02, t_lf));
            return;
        }
        if (abs(y_from_bot_px - wave_r) <= WAVE_HW) {
            FragColor = vec4(uBottomColor.rgb, 0.90);
            return;
        }
        float r_lo = min(wave_r, bmid_bw);
        float r_hi = max(wave_r, bmid_bw);
        if (y_from_bot_px >= r_lo && y_from_bot_px < r_hi) {
            float t_rf = (r_hi - r_lo) > 0.5 ? abs(y_from_bot_px - wave_r) / (r_hi - r_lo) : 0.5;
            FragColor = vec4(uBottomColor.rgb, mix(0.18, 0.02, t_rf));
            return;
        }
        float lbl_sc   = 2.0;
        float lbl_cy_l = tmid_bw + amp_bw + 8.0;
        float lbl_cy_r = bmid_bw + amp_bw + 8.0;
        if (sampleGlyph(x_px, y_from_bot_px, 14.0, lbl_cy_l, lbl_sc, CHAR_L) > 0.5) {
            FragColor = vec4(uTopColor.rgb, 0.78);
            return;
        }
        if (sampleGlyph(x_px, y_from_bot_px, 14.0, lbl_cy_r, lbl_sc, CHAR_R) > 0.5) {
            FragColor = vec4(uBottomColor.rgb, 0.78);
            return;
        }
        discard;
        return;
    }
    // Center Side: Mid=(L+R)*0.5 upper lane, Side=|L-R| lower lane
    if (uMode == 11) {
        float step_cs = uResolution.x / float(max(uNumBars - 1, 1));
        float t_cs    = x_px / step_cs;
        int   i0_cs   = clamp(int(t_cs),     0, uNumBars - 1);
        int   i1_cs   = clamp(int(t_cs) + 1, 0, uNumBars - 1);
        float frac_cs = t_cs - float(i0_cs);
        float lv_cs   = mix(clamp(uLeftHeights[i0_cs]  * uGain, 0.0, 1.0),
                            clamp(uLeftHeights[i1_cs]  * uGain, 0.0, 1.0), frac_cs);
        float rv_cs   = mix(clamp(uRightHeights[i0_cs] * uGain, 0.0, 1.0),
                            clamp(uRightHeights[i1_cs] * uGain, 0.0, 1.0), frac_cs);
        float mid_v   = (lv_cs + rv_cs) * 0.5;
        float side_v  = abs(lv_cs - rv_cs);
        float amp_cs  = uResolution.y * 0.18;
        float tmid_cs = uResolution.y * 0.67;
        float bmid_cs = uResolution.y * 0.28;
        float wave_m  = tmid_cs + mid_v  * amp_cs;
        float wave_s  = bmid_cs + side_v * amp_cs;
        if (abs(y_from_bot_px - tmid_cs) < 0.6 || abs(y_from_bot_px - bmid_cs) < 0.6) {
            FragColor = vec4(1.0, 1.0, 1.0, 0.06);
            return;
        }
        if (abs(y_from_bot_px - wave_m) <= WAVE_HW) {
            FragColor = vec4(uTopColor.rgb, 0.92);
            return;
        }
        if (y_from_bot_px >= tmid_cs && y_from_bot_px < wave_m) {
            float t_mf = (wave_m - tmid_cs) > 0.5 ? (y_from_bot_px - tmid_cs) / (wave_m - tmid_cs) : 0.5;
            FragColor = vec4(uTopColor.rgb, mix(0.02, 0.22, t_mf));
            return;
        }
        if (abs(y_from_bot_px - wave_s) <= WAVE_HW) {
            FragColor = vec4(uBottomColor.rgb, 0.92);
            return;
        }
        if (y_from_bot_px >= bmid_cs && y_from_bot_px < wave_s) {
            float t_sf = (wave_s - bmid_cs) > 0.5 ? (y_from_bot_px - bmid_cs) / (wave_s - bmid_cs) : 0.5;
            FragColor = vec4(uBottomColor.rgb, mix(0.02, 0.22, t_sf));
            return;
        }
        float lbl_sc   = 2.0;
        float adv      = 4.0*lbl_sc + 2.0;
        float lbl_cy_m = tmid_cs + amp_cs + 8.0;
        float lbl_cy_s = bmid_cs + amp_cs + 8.0;
        if (sampleGlyph(x_px, y_from_bot_px, 14.0,         lbl_cy_m, lbl_sc, CHAR_M) > 0.5 ||
            sampleGlyph(x_px, y_from_bot_px, 14.0+adv,     lbl_cy_m, lbl_sc, CHAR_I) > 0.5 ||
            sampleGlyph(x_px, y_from_bot_px, 14.0+2.0*adv, lbl_cy_m, lbl_sc, CHAR_D) > 0.5) {
            FragColor = vec4(uTopColor.rgb, 0.78);
            return;
        }
        if (sampleGlyph(x_px, y_from_bot_px, 14.0,         lbl_cy_s, lbl_sc, CHAR_S) > 0.5 ||
            sampleGlyph(x_px, y_from_bot_px, 14.0+adv,     lbl_cy_s, lbl_sc, CHAR_I) > 0.5 ||
            sampleGlyph(x_px, y_from_bot_px, 14.0+2.0*adv, lbl_cy_s, lbl_sc, CHAR_D) > 0.5 ||
            sampleGlyph(x_px, y_from_bot_px, 14.0+3.0*adv, lbl_cy_s, lbl_sc, CHAR_E) > 0.5) {
            FragColor = vec4(uBottomColor.rgb, 0.78);
            return;
        }
        discard;
        return;
    }
    // Wave / Fill: step-based x
    if (uMode == 4 || uMode == 5) {
        float step_x   = uResolution.x / float(max(uNumBars - 1, 1));
        float t_global = x_px / step_x;
        int   i0 = clamp(int(t_global),     0, uNumBars - 1);
        int   i1 = clamp(int(t_global) + 1, 0, uNumBars - 1);
        float frac   = t_global - float(i0);
        float h0     = clamp(uHeights[i0] * uGain, 0.0, 1.0) * uResolution.y;
        float h1     = clamp(uHeights[i1] * uGain, 0.0, 1.0) * uResolution.y;
        float wave_h = mix(h0, h1, frac);
        vec4  col    = mix(uColors[i0], uColors[i1], frac);
        if (uMode == 4) {
            if (abs(y_from_bot_px - wave_h) > WAVE_HW) discard;
            FragColor = col;
        } else {
            if (y_from_bot_px >= wave_h) discard;
            FragColor = col;
        }
        return;
    }
    // Pulse: radial glow background + bars on top
    if (uMode == 6) {
        vec2  center_px = vec2(uResolution.x * 0.5, uResolution.y * 0.58);
        float r_px      = min(uResolution.x, uResolution.y) * (0.16 + 0.18 * uBassLevel);
        float dist      = length(vec2(x_px, y_from_bot_px) - center_px);
        vec4  bg        = vec4(0.0);
        if (dist < r_px && uBassLevel > 0.02) {
            float fade = 1.0 - smoothstep(r_px * 0.35, r_px, dist);
            bg = vec4(uPulseColor.rgb, uPulseColor.a * 0.24 * uBassLevel * fade);
        }
        float slot_w2     = uResolution.x / float(uNumBars);
        int   bar_i2      = int(x_px / slot_w2);
        bool  in_bar      = false;
        vec4  bar_col     = vec4(0.0);
        if (bar_i2 < uNumBars) {
            float pos2 = x_px - float(bar_i2) * slot_w2;
            float bw2  = max(1.0, slot_w2 - uSpacingPx);
            float hp2  = clamp(uHeights[bar_i2] * uGain, 0.0, 1.0) * uResolution.y;
            if (pos2 < bw2 && y_from_bot_px < hp2) {
                in_bar  = true;
                bar_col = uColors[bar_i2];
            }
        }
        if (in_bar) {
            FragColor = vec4(mix(bg.rgb, bar_col.rgb, bar_col.a), 1.0);
        } else if (bg.a > 0.004) {
            FragColor = bg;
        } else {
            discard;
        }
        return;
    }
    // Stereo Mirror: L channel above center, R channel below
    if (uMode == 7) {
        float slot_w3 = uResolution.x / float(uNumBars);
        int   bar_i3  = int(x_px / slot_w3);
        if (bar_i3 >= uNumBars) discard;
        float pos3 = x_px - float(bar_i3) * slot_w3;
        float bw3  = max(1.0, slot_w3 - uSpacingPx);
        if (pos3 >= bw3) discard;
        float center = uResolution.y * 0.5;
        if (y_from_bot_px >= center) {
            float lh = clamp(uLeftHeights[bar_i3] * uGain, 0.0, 1.0) * uResolution.y * 0.48;
            if ((y_from_bot_px - center) >= lh) discard;
            FragColor = uTopColor;
        } else {
            float rh = clamp(uRightHeights[bar_i3] * uGain, 0.0, 1.0) * uResolution.y * 0.48;
            if ((center - y_from_bot_px) >= rh) discard;
            FragColor = uBottomColor;
        }
        return;
    }
    // Slot-based x (Bars, Peak, Trail, Mirror)
    float slot_w = uResolution.x / float(uNumBars);
    int   bar_i  = int(x_px / slot_w);
    if (bar_i >= uNumBars) discard;
    float pos_in_slot = x_px - float(bar_i) * slot_w;
    float bar_w       = max(1.0, slot_w - uSpacingPx);
    if (pos_in_slot >= bar_w) discard;
    vec4  col  = uColors[bar_i];
    float h_px = clamp(uHeights[bar_i] * uGain, 0.0, 1.0) * uResolution.y;
    if (uMode == 3) {
        float center = uResolution.y * 0.5;
        float h_half = clamp(uHeights[bar_i] * uGain, 0.0, 1.0) * uResolution.y * 0.48;
        if (abs(y_from_bot_px - center) >= h_half) discard;
        FragColor = col;
        return;
    }
    if (uMode == 2) {
        float tr_px = clamp(uTrailHeights[bar_i] * uGain, 0.0, 1.0) * uResolution.y;
        if (y_from_bot_px >= h_px && y_from_bot_px < tr_px) {
            FragColor = vec4(col.rgb, col.a * 0.35);
            return;
        }
    }
    if (uMode == 1) {
        float ph_px = clamp(uPeakHeights[bar_i] * uGain, 0.0, 1.0) * uResolution.y;
        if (ph_px > h_px + 1.0 && y_from_bot_px >= ph_px && y_from_bot_px < ph_px + CAP_H) {
            FragColor = col;
            return;
        }
    }
    if (y_from_bot_px >= h_px) discard;
    FragColor = col;
}
"""

_BARS_VERT_300ES = """
#version 300 es
layout (location = 0) in vec2 aPos;
out vec2 vUV;
void main() {
    vUV = (aPos + 1.0) * 0.5;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

_BARS_FRAG_300ES = """
#version 300 es
precision mediump float;
in vec2 vUV;
out vec4 FragColor;
const int MAX_BARS = 512;
uniform int   uNumBars;
uniform float uHeights[MAX_BARS];
uniform float uPeakHeights[MAX_BARS];
uniform float uTrailHeights[MAX_BARS];
uniform float uLeftHeights[MAX_BARS];
uniform float uRightHeights[MAX_BARS];
uniform vec4  uColors[MAX_BARS];
uniform vec4  uTopColor;
uniform vec4  uBottomColor;
uniform vec4  uPulseColor;
uniform float uGain;
uniform float uSpacingPx;
uniform float uBassLevel;
uniform vec2  uResolution;
uniform float uBalance;
uniform int   uMode;
const float CAP_H   = 3.0;
const float WAVE_HW = 2.0;
const float PI      = 3.14159265;
const int CHAR_L = 1017992;
const int CHAR_R = 642718;
const int CHAR_M = 629241;
const int CHAR_I = 934990;
const int CHAR_D = 956830;
const int CHAR_S = 923271;
const int CHAR_E = 1019535;
float sampleGlyph(float px, float py, float cx, float cy_bot, float sc, int glyph) {
    float lx = (px - cx) / sc;
    float ly = (cy_bot + 5.0*sc - py) / sc;
    if (lx < 0.0 || lx >= 4.0 || ly < 0.0 || ly >= 5.0) return 0.0;
    int bit = (3 - int(lx)) + int(ly) * 4;
    return float((glyph >> bit) & 1);
}
void main() {
    float x_px          = vUV.x * uResolution.x;
    float y_from_bot_px = vUV.y * uResolution.y;
    if (uMode == 8) {
        float half8  = uResolution.x * 0.5;
        float gap8   = 8.0;
        int   half_n = max(1, uNumBars / 2);
        float bars_w = half8 - gap8;
        float max_h8 = uResolution.y * 0.92;
        float meter_w  = min(120.0, uResolution.x * 0.16);
        float meter_y  = uResolution.y * 0.92;
        float marker_x = half8 + uBalance * meter_w * 0.5;
        float ball_d   = length(vec2(x_px - marker_x, y_from_bot_px - meter_y));
        if (ball_d < 4.5) {
            FragColor = vec4(1.0, 1.0, 1.0, 0.72);
            return;
        }
        if (ball_d < 10.0) {
            vec4 gc = uBalance >= 0.0 ? uTopColor : uBottomColor;
            FragColor = vec4(gc.rgb, 0.22 * (1.0 - (ball_d - 4.5) / 5.5));
            return;
        }
        float meter_l = half8 - meter_w * 0.5;
        float meter_r = half8 + meter_w * 0.5;
        if (abs(y_from_bot_px - meter_y) < 0.5 && x_px >= meter_l && x_px <= meter_r) {
            FragColor = vec4(1.0, 1.0, 1.0, 0.10);
            return;
        }
        if (abs(x_px - half8) < 0.5 && abs(y_from_bot_px - meter_y) < 5.0) {
            FragColor = vec4(1.0, 1.0, 1.0, 0.10);
            return;
        }
        if (abs(x_px - half8) < 0.5) {
            FragColor = vec4(1.0, 1.0, 1.0, 0.08);
            return;
        }
        if (x_px < half8 - gap8) {
            float sw8 = bars_w / float(half_n);
            int   bi8 = int(x_px / sw8);
            if (bi8 >= half_n) discard;
            if (x_px - float(bi8) * sw8 >= max(1.0, sw8 - uSpacingPx)) discard;
            if (y_from_bot_px >= clamp(uLeftHeights[bi8] * uGain, 0.0, 1.0) * max_h8) discard;
            FragColor = uTopColor;
        } else if (x_px > half8 + gap8) {
            float local_x = x_px - (half8 + gap8);
            float sw8 = bars_w / float(half_n);
            int   bi8 = int(local_x / sw8);
            if (bi8 >= half_n) discard;
            if (local_x - float(bi8) * sw8 >= max(1.0, sw8 - uSpacingPx)) discard;
            if (y_from_bot_px >= clamp(uRightHeights[bi8] * uGain, 0.0, 1.0) * max_h8) discard;
            FragColor = uBottomColor;
        } else { discard; }
        return;
    }
    if (uMode == 9) {
        vec2  center9 = uResolution * 0.5;
        vec2  delta9  = vec2(x_px, y_from_bot_px) - center9;
        float dist9   = length(delta9);
        float t9      = (atan(delta9.y, delta9.x) + PI) / (2.0 * PI);
        int   bi9     = clamp(int(t9 * float(uNumBars)), 0, uNumBars - 1);
        float max_r9  = min(uResolution.x, uResolution.y) * 0.46;
        float h9      = clamp(uHeights[bi9] * uGain, 0.0, 1.0) * max_r9;
        if (dist9 >= h9 || h9 < 2.0) discard;
        FragColor = uColors[bi9];
        return;
    }
    if (uMode == 10) {
        float step_bw = uResolution.x / float(max(uNumBars - 1, 1));
        float t_bw    = x_px / step_bw;
        int   i0_bw   = clamp(int(t_bw),     0, uNumBars - 1);
        int   i1_bw   = clamp(int(t_bw) + 1, 0, uNumBars - 1);
        float frac_bw = t_bw - float(i0_bw);
        float lv      = mix(clamp(uLeftHeights[i0_bw]  * uGain, 0.0, 1.0),
                            clamp(uLeftHeights[i1_bw]  * uGain, 0.0, 1.0), frac_bw);
        float rv      = mix(clamp(uRightHeights[i0_bw] * uGain, 0.0, 1.0),
                            clamp(uRightHeights[i1_bw] * uGain, 0.0, 1.0), frac_bw);
        float amp_bw  = uResolution.y * 0.20;
        float tmid_bw = uResolution.y * 0.66;
        float bmid_bw = uResolution.y * 0.30;
        float wave_l  = tmid_bw + (lv - 0.5) * 2.0 * amp_bw;
        float wave_r  = bmid_bw + (rv - 0.5) * 2.0 * amp_bw;
        if (abs(y_from_bot_px - tmid_bw) < 0.6 || abs(y_from_bot_px - bmid_bw) < 0.6) {
            FragColor = vec4(1.0, 1.0, 1.0, 0.06);
            return;
        }
        if (abs(y_from_bot_px - wave_l) <= WAVE_HW) {
            FragColor = vec4(uTopColor.rgb, 0.90);
            return;
        }
        float l_lo = min(wave_l, tmid_bw);
        float l_hi = max(wave_l, tmid_bw);
        if (y_from_bot_px >= l_lo && y_from_bot_px < l_hi) {
            float t_lf = (l_hi - l_lo) > 0.5 ? abs(y_from_bot_px - wave_l) / (l_hi - l_lo) : 0.5;
            FragColor = vec4(uTopColor.rgb, mix(0.18, 0.02, t_lf));
            return;
        }
        if (abs(y_from_bot_px - wave_r) <= WAVE_HW) {
            FragColor = vec4(uBottomColor.rgb, 0.90);
            return;
        }
        float r_lo = min(wave_r, bmid_bw);
        float r_hi = max(wave_r, bmid_bw);
        if (y_from_bot_px >= r_lo && y_from_bot_px < r_hi) {
            float t_rf = (r_hi - r_lo) > 0.5 ? abs(y_from_bot_px - wave_r) / (r_hi - r_lo) : 0.5;
            FragColor = vec4(uBottomColor.rgb, mix(0.18, 0.02, t_rf));
            return;
        }
        float lbl_sc   = 2.0;
        float lbl_cy_l = tmid_bw + amp_bw + 8.0;
        float lbl_cy_r = bmid_bw + amp_bw + 8.0;
        if (sampleGlyph(x_px, y_from_bot_px, 14.0, lbl_cy_l, lbl_sc, CHAR_L) > 0.5) {
            FragColor = vec4(uTopColor.rgb, 0.78);
            return;
        }
        if (sampleGlyph(x_px, y_from_bot_px, 14.0, lbl_cy_r, lbl_sc, CHAR_R) > 0.5) {
            FragColor = vec4(uBottomColor.rgb, 0.78);
            return;
        }
        discard;
        return;
    }
    if (uMode == 11) {
        float step_cs = uResolution.x / float(max(uNumBars - 1, 1));
        float t_cs    = x_px / step_cs;
        int   i0_cs   = clamp(int(t_cs),     0, uNumBars - 1);
        int   i1_cs   = clamp(int(t_cs) + 1, 0, uNumBars - 1);
        float frac_cs = t_cs - float(i0_cs);
        float lv_cs   = mix(clamp(uLeftHeights[i0_cs]  * uGain, 0.0, 1.0),
                            clamp(uLeftHeights[i1_cs]  * uGain, 0.0, 1.0), frac_cs);
        float rv_cs   = mix(clamp(uRightHeights[i0_cs] * uGain, 0.0, 1.0),
                            clamp(uRightHeights[i1_cs] * uGain, 0.0, 1.0), frac_cs);
        float mid_v   = (lv_cs + rv_cs) * 0.5;
        float side_v  = abs(lv_cs - rv_cs);
        float amp_cs  = uResolution.y * 0.18;
        float tmid_cs = uResolution.y * 0.67;
        float bmid_cs = uResolution.y * 0.28;
        float wave_m  = tmid_cs + mid_v  * amp_cs;
        float wave_s  = bmid_cs + side_v * amp_cs;
        if (abs(y_from_bot_px - tmid_cs) < 0.6 || abs(y_from_bot_px - bmid_cs) < 0.6) {
            FragColor = vec4(1.0, 1.0, 1.0, 0.06);
            return;
        }
        if (abs(y_from_bot_px - wave_m) <= WAVE_HW) {
            FragColor = vec4(uTopColor.rgb, 0.92);
            return;
        }
        if (y_from_bot_px >= tmid_cs && y_from_bot_px < wave_m) {
            float t_mf = (wave_m - tmid_cs) > 0.5 ? (y_from_bot_px - tmid_cs) / (wave_m - tmid_cs) : 0.5;
            FragColor = vec4(uTopColor.rgb, mix(0.02, 0.22, t_mf));
            return;
        }
        if (abs(y_from_bot_px - wave_s) <= WAVE_HW) {
            FragColor = vec4(uBottomColor.rgb, 0.92);
            return;
        }
        if (y_from_bot_px >= bmid_cs && y_from_bot_px < wave_s) {
            float t_sf = (wave_s - bmid_cs) > 0.5 ? (y_from_bot_px - bmid_cs) / (wave_s - bmid_cs) : 0.5;
            FragColor = vec4(uBottomColor.rgb, mix(0.02, 0.22, t_sf));
            return;
        }
        float lbl_sc   = 2.0;
        float adv      = 4.0*lbl_sc + 2.0;
        float lbl_cy_m = tmid_cs + amp_cs + 8.0;
        float lbl_cy_s = bmid_cs + amp_cs + 8.0;
        if (sampleGlyph(x_px, y_from_bot_px, 14.0,         lbl_cy_m, lbl_sc, CHAR_M) > 0.5 ||
            sampleGlyph(x_px, y_from_bot_px, 14.0+adv,     lbl_cy_m, lbl_sc, CHAR_I) > 0.5 ||
            sampleGlyph(x_px, y_from_bot_px, 14.0+2.0*adv, lbl_cy_m, lbl_sc, CHAR_D) > 0.5) {
            FragColor = vec4(uTopColor.rgb, 0.78);
            return;
        }
        if (sampleGlyph(x_px, y_from_bot_px, 14.0,         lbl_cy_s, lbl_sc, CHAR_S) > 0.5 ||
            sampleGlyph(x_px, y_from_bot_px, 14.0+adv,     lbl_cy_s, lbl_sc, CHAR_I) > 0.5 ||
            sampleGlyph(x_px, y_from_bot_px, 14.0+2.0*adv, lbl_cy_s, lbl_sc, CHAR_D) > 0.5 ||
            sampleGlyph(x_px, y_from_bot_px, 14.0+3.0*adv, lbl_cy_s, lbl_sc, CHAR_E) > 0.5) {
            FragColor = vec4(uBottomColor.rgb, 0.78);
            return;
        }
        discard;
        return;
    }
    if (uMode == 4 || uMode == 5) {
        float step_x   = uResolution.x / float(max(uNumBars - 1, 1));
        float t_global = x_px / step_x;
        int   i0 = clamp(int(t_global),     0, uNumBars - 1);
        int   i1 = clamp(int(t_global) + 1, 0, uNumBars - 1);
        float frac   = t_global - float(i0);
        float h0     = clamp(uHeights[i0] * uGain, 0.0, 1.0) * uResolution.y;
        float h1     = clamp(uHeights[i1] * uGain, 0.0, 1.0) * uResolution.y;
        float wave_h = mix(h0, h1, frac);
        vec4  col    = mix(uColors[i0], uColors[i1], frac);
        if (uMode == 4) {
            if (abs(y_from_bot_px - wave_h) > WAVE_HW) discard;
            FragColor = col;
        } else {
            if (y_from_bot_px >= wave_h) discard;
            FragColor = col;
        }
        return;
    }
    if (uMode == 6) {
        vec2  center_px = vec2(uResolution.x * 0.5, uResolution.y * 0.58);
        float r_px      = min(uResolution.x, uResolution.y) * (0.16 + 0.18 * uBassLevel);
        float dist      = length(vec2(x_px, y_from_bot_px) - center_px);
        vec4  bg        = vec4(0.0);
        if (dist < r_px && uBassLevel > 0.02) {
            float fade = 1.0 - smoothstep(r_px * 0.35, r_px, dist);
            bg = vec4(uPulseColor.rgb, uPulseColor.a * 0.24 * uBassLevel * fade);
        }
        float slot_w2 = uResolution.x / float(uNumBars);
        int   bar_i2  = int(x_px / slot_w2);
        bool  in_bar  = false;
        vec4  bar_col = vec4(0.0);
        if (bar_i2 < uNumBars) {
            float pos2 = x_px - float(bar_i2) * slot_w2;
            float bw2  = max(1.0, slot_w2 - uSpacingPx);
            float hp2  = clamp(uHeights[bar_i2] * uGain, 0.0, 1.0) * uResolution.y;
            if (pos2 < bw2 && y_from_bot_px < hp2) {
                in_bar  = true;
                bar_col = uColors[bar_i2];
            }
        }
        if (in_bar) {
            FragColor = vec4(mix(bg.rgb, bar_col.rgb, bar_col.a), 1.0);
        } else if (bg.a > 0.004) {
            FragColor = bg;
        } else {
            discard;
        }
        return;
    }
    if (uMode == 7) {
        float slot_w3 = uResolution.x / float(uNumBars);
        int   bar_i3  = int(x_px / slot_w3);
        if (bar_i3 >= uNumBars) discard;
        float pos3 = x_px - float(bar_i3) * slot_w3;
        float bw3  = max(1.0, slot_w3 - uSpacingPx);
        if (pos3 >= bw3) discard;
        float center = uResolution.y * 0.5;
        if (y_from_bot_px >= center) {
            float lh = clamp(uLeftHeights[bar_i3] * uGain, 0.0, 1.0) * uResolution.y * 0.48;
            if ((y_from_bot_px - center) >= lh) discard;
            FragColor = uTopColor;
        } else {
            float rh = clamp(uRightHeights[bar_i3] * uGain, 0.0, 1.0) * uResolution.y * 0.48;
            if ((center - y_from_bot_px) >= rh) discard;
            FragColor = uBottomColor;
        }
        return;
    }
    float slot_w = uResolution.x / float(uNumBars);
    int   bar_i  = int(x_px / slot_w);
    if (bar_i >= uNumBars) discard;
    float pos_in_slot = x_px - float(bar_i) * slot_w;
    float bar_w       = max(1.0, slot_w - uSpacingPx);
    if (pos_in_slot >= bar_w) discard;
    vec4  col  = uColors[bar_i];
    float h_px = clamp(uHeights[bar_i] * uGain, 0.0, 1.0) * uResolution.y;
    if (uMode == 3) {
        float center = uResolution.y * 0.5;
        float h_half = clamp(uHeights[bar_i] * uGain, 0.0, 1.0) * uResolution.y * 0.48;
        if (abs(y_from_bot_px - center) >= h_half) discard;
        FragColor = col;
        return;
    }
    if (uMode == 2) {
        float tr_px = clamp(uTrailHeights[bar_i] * uGain, 0.0, 1.0) * uResolution.y;
        if (y_from_bot_px >= h_px && y_from_bot_px < tr_px) {
            FragColor = vec4(col.rgb, col.a * 0.35);
            return;
        }
    }
    if (uMode == 1) {
        float ph_px = clamp(uPeakHeights[bar_i] * uGain, 0.0, 1.0) * uResolution.y;
        if (ph_px > h_px + 1.0 && y_from_bot_px >= ph_px && y_from_bot_px < ph_px + CAP_H) {
            FragColor = col;
            return;
        }
    }
    if (y_from_bot_px >= h_px) discard;
    FragColor = col;
}
"""

# Effect name → uMode integer
_BARS_GL_EFFECT_MODES = {
    "Bars":          0,
    "Peak":          1,
    "Trail":         2,
    "Mirror":        3,
    "Wave":          4,
    "Fill":          5,
    "Pulse":         6,
    "Stereo Mirror": 7,
    "Burst":         9,
    "Balance Wave":  10,
    "Center Side":   11,
}


class BarsGLVisualizer(Gtk.GLArea):
    """GL-accelerated visualizer for Bars, Peak, and Trail effects."""

    def __init__(self):
        if GL is None:
            raise RuntimeError("PyOpenGL not available")
        super().__init__()

        proto = SpectrumVisualizer()
        self.themes               = proto.themes
        self.profiles             = proto.profiles
        self._color_from_gradient = proto._color_from_gradient

        self.num_bars            = 32
        self.theme_name          = "Aurora (Default)"
        self.profile_name        = "Dynamic"
        self.frequency_scale_name = _FREQ_SCALE_LINEAR
        self.frequency_scale_names = list(_FREQ_SCALE_NAMES)
        self.effect_mode         = 0   # 0=Bars 1=Peak 2=Trail

        self._profile_cfg = self.profiles["Dynamic"]
        self._theme_cfg   = self.themes["Aurora (Default)"]
        self._cached_gain    = float(self._theme_cfg["height_gain"]) * float(self._profile_cfg["gain_mul"])
        self._cached_spacing = max(0.8, float(self._theme_cfg["bar_spacing"]) * float(self._profile_cfg["spacing_mul"]))

        self.target_heights       = [0.0] * 512
        self.current_heights      = [0.0] * 512
        self.peak_holds           = [0.0] * 512
        self.peak_ttl             = [0]   * 512
        self.trail_heights        = [0.0] * 512
        self.target_left_heights  = [0.0] * 512
        self.target_right_heights = [0.0] * 512
        self.left_heights         = [0.0] * 512
        self.right_heights        = [0.0] * 512
        self.bass_level           = 0.0
        self._bass_target         = 0.0
        self.balance              = 0.0
        self._balance_target      = 0.0

        self._h_arr  = (ctypes.c_float * 512)(*([0.0] * 512))
        self._ph_arr = (ctypes.c_float * 512)(*([0.0] * 512))
        self._tr_arr = (ctypes.c_float * 512)(*([0.0] * 512))
        self._lh_arr = (ctypes.c_float * 512)(*([0.0] * 512))
        self._rh_arr = (ctypes.c_float * 512)(*([0.0] * 512))
        self._c_arr  = (ctypes.c_float * 2048)(*([0.0] * 2048))

        self._program      = None
        self._vao          = None
        self._vbo          = None
        self._gl_failed    = False
        self._color_cache  = None
        self._color_cache_key = None
        self._dirty_static = True
        self._cached_w     = 0
        self._cached_h     = 0

        self._active       = False
        self._anim_source  = None

        self.set_auto_render(False)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.connect("realize",   self._on_realize)
        self.connect("unrealize", self._on_unrealize)
        self.connect("render",    self._on_render)
        logger.info("Visualizer backend selected: GL (Bars/Peak/Trail)")

    # ------------------------------------------------------------------
    # GL lifecycle
    # ------------------------------------------------------------------

    def _on_realize(self, _area):
        self.make_current()
        try:
            self._setup_gl()
        except Exception:
            logger.warning("BarsGL shader setup failed", exc_info=True)
            self._gl_failed = True

    def _on_unrealize(self, _area):
        self.make_current()
        if self._vbo:
            GL.glDeleteBuffers(1, [self._vbo])
        if self._vao:
            GL.glDeleteVertexArrays(1, [self._vao])
        self._vbo = self._vao = self._program = None

    def _setup_gl(self):
        self._program = None
        err = None
        for label, vs, fs in [
            ("330 core", _BARS_VERT_330,   _BARS_FRAG_330),
            ("300 es",   _BARS_VERT_300ES, _BARS_FRAG_300ES),
        ]:
            try:
                self._program = gl_shaders.compileProgram(
                    gl_shaders.compileShader(vs, GL.GL_VERTEX_SHADER),
                    gl_shaders.compileShader(fs, GL.GL_FRAGMENT_SHADER),
                )
                logger.info("BarsGL shader: GLSL %s", label)
                break
            except Exception as e:
                err = e
        if self._program is None:
            raise RuntimeError(f"BarsGL shader compile failed: {err}")

        p = self._program
        self._u_num_bars     = GL.glGetUniformLocation(p, "uNumBars")
        self._u_heights      = GL.glGetUniformLocation(p, "uHeights")
        self._u_peak_heights = GL.glGetUniformLocation(p, "uPeakHeights")
        self._u_trail_heights= GL.glGetUniformLocation(p, "uTrailHeights")
        self._u_left_heights = GL.glGetUniformLocation(p, "uLeftHeights")
        self._u_right_heights= GL.glGetUniformLocation(p, "uRightHeights")
        self._u_colors       = GL.glGetUniformLocation(p, "uColors")
        self._u_top_color    = GL.glGetUniformLocation(p, "uTopColor")
        self._u_bottom_color = GL.glGetUniformLocation(p, "uBottomColor")
        self._u_pulse_color  = GL.glGetUniformLocation(p, "uPulseColor")
        self._u_gain         = GL.glGetUniformLocation(p, "uGain")
        self._u_spacing      = GL.glGetUniformLocation(p, "uSpacingPx")
        self._u_bass_level   = GL.glGetUniformLocation(p, "uBassLevel")
        self._u_balance      = GL.glGetUniformLocation(p, "uBalance")
        self._u_resolution   = GL.glGetUniformLocation(p, "uResolution")
        self._u_mode         = GL.glGetUniformLocation(p, "uMode")

        verts = (-1.0, -1.0, 1.0, -1.0, -1.0, 1.0, 1.0, 1.0)
        arr   = (ctypes.c_float * 8)(*verts)
        self._vao = GL.glGenVertexArrays(1)
        self._vbo = GL.glGenBuffers(1)
        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, ctypes.sizeof(arr), arr, GL.GL_STATIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glBindVertexArray(0)

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _get_colors(self):
        key = (self.theme_name, self.num_bars)
        if self._color_cache_key == key and self._color_cache is not None:
            return
        grad = self._theme_cfg.get("gradient", [])
        n    = self.num_bars
        arr  = self._c_arr
        for i in range(n):
            t = i / float(max(1, n - 1))
            r, g, b, a = self._color_from_gradient(grad, t)
            base = i * 4
            arr[base]     = r
            arr[base + 1] = g
            arr[base + 2] = b
            arr[base + 3] = a
        for i in range(n, 512):
            base = i * 4
            arr[base] = arr[base+1] = arr[base+2] = arr[base+3] = 0.0
        self._color_cache_key = key
        self._color_cache     = True

    def _on_render(self, _area, _context):
        if self._gl_failed or self._program is None:
            return True
        w = int(self.get_width()  or 0)
        h = int(self.get_height() or 0)
        if w < 1 or h < 1:
            return True
        sf = int(max(1, getattr(self, "get_scale_factor", lambda: 1)() or 1))
        pw, ph = w * sf, h * sf
        GL.glViewport(0, 0, pw, ph)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glUseProgram(self._program)
        if self._dirty_static or pw != self._cached_w or ph != self._cached_h:
            self._get_colors()
            grad = self._theme_cfg.get("gradient", [])
            tc = self._color_from_gradient(grad, 0.82)
            bc = self._color_from_gradient(grad, 0.12)
            pc = self._color_from_gradient(grad, 0.0)
            GL.glUniform1i(self._u_num_bars,    self.num_bars)
            GL.glUniform4fv(self._u_colors,     512, self._c_arr)
            GL.glUniform4f(self._u_top_color,   *tc)
            GL.glUniform4f(self._u_bottom_color,*bc)
            GL.glUniform4f(self._u_pulse_color, *pc)
            GL.glUniform1f(self._u_gain,        self._cached_gain)
            GL.glUniform1f(self._u_spacing,     self._cached_spacing)
            GL.glUniform2f(self._u_resolution,  float(pw), float(ph))
            GL.glUniform1i(self._u_mode,        self.effect_mode)
            self._cached_w     = pw
            self._cached_h     = ph
            self._dirty_static = False
        self._h_arr[:512]  = self.current_heights[:512]
        self._ph_arr[:512] = self.peak_holds[:512]
        self._tr_arr[:512] = self.trail_heights[:512]
        self._lh_arr[:512] = self.left_heights[:512]
        self._rh_arr[:512] = self.right_heights[:512]
        GL.glUniform1fv(self._u_heights,        512, self._h_arr)
        GL.glUniform1fv(self._u_peak_heights,   512, self._ph_arr)
        GL.glUniform1fv(self._u_trail_heights,  512, self._tr_arr)
        GL.glUniform1fv(self._u_left_heights,   512, self._lh_arr)
        GL.glUniform1fv(self._u_right_heights,  512, self._rh_arr)
        GL.glUniform1f(self._u_bass_level,      self.bass_level)
        GL.glUniform1f(self._u_balance,         self.balance)
        GL.glBindVertexArray(self._vao)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glBindVertexArray(0)
        return True

    # ------------------------------------------------------------------
    # Animation tick
    # ------------------------------------------------------------------

    def _on_animation_tick(self):
        if not self._active:
            self._anim_source = None
            return False
        profile = self._profile_cfg
        smooth      = float(profile["smooth"])
        trail_decay = float(profile["trail_decay"])
        peak_fall   = float(profile["peak_fall"])
        peak_hold_f = int(profile["peak_hold_frames"])
        bass_resp   = max(0.12, min(0.62, 0.28 * float(profile["beat_mul"])))
        changed = False
        for i in range(self.num_bars):
            diff = self.target_heights[i] - self.current_heights[i]
            if abs(diff) > 0.001:
                self.current_heights[i] += diff * smooth
                changed = True
            ldiff = self.target_left_heights[i] - self.left_heights[i]
            if abs(ldiff) > 0.001:
                self.left_heights[i] += ldiff * smooth
                changed = True
            rdiff = self.target_right_heights[i] - self.right_heights[i]
            if abs(rdiff) > 0.001:
                self.right_heights[i] += rdiff * smooth
                changed = True
            cur = self.current_heights[i]
            self.trail_heights[i] = max(cur, self.trail_heights[i] * trail_decay)
            if cur >= self.peak_holds[i]:
                self.peak_holds[i] = cur
                self.peak_ttl[i]   = peak_hold_f
            else:
                if self.peak_ttl[i] > 0:
                    self.peak_ttl[i] -= 1
                else:
                    self.peak_holds[i] = max(0.0, self.peak_holds[i] - peak_fall)
        self.bass_level += (self._bass_target - self.bass_level) * bass_resp
        self.balance    += (self._balance_target - self.balance) * smooth
        if changed:
            self.queue_render()
        return True

    def set_active(self, active):
        if self._active == active:
            return
        self._active = active
        if active:
            if self._anim_source is None:
                self._anim_source = GLib.timeout_add(16, self._on_animation_tick)
            self.queue_render()
        else:
            if self._anim_source:
                try:
                    GLib.source_remove(self._anim_source)
                except Exception:
                    pass
            self._anim_source = None

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def update_data(self, magnitudes):
        if not magnitudes:
            return
        if isinstance(magnitudes, dict):
            mono_vals  = magnitudes.get("mono") or magnitudes.get("left") or ()
            left_vals  = magnitudes.get("left")  or mono_vals
            right_vals = magnitudes.get("right") or mono_vals
        else:
            mono_vals = left_vals = right_vals = magnitudes
        mono_vals  = list(mono_vals  or [])
        left_vals  = list(left_vals  or [])
        right_vals = list(right_vals or [])

        def _build(vals):
            if self.frequency_scale_name == _FREQ_SCALE_LOG:
                return _build_log_spectrum_bins(_normalize_spectrum_magnitudes(vals), self.num_bars)
            return _build_linear_spectrum_bins(
                vals, self.num_bars,
                rust_core=None,
                analysis_bands=_LINEAR_ANALYSIS_BANDS,
                db_min=-80.0, db_range=80.0,
            )

        new_heights  = _build(mono_vals)
        self.target_heights[:self.num_bars] = new_heights[:self.num_bars]

        lh = _build(left_vals)
        rh = _build(right_vals)
        self.target_left_heights[:self.num_bars]  = lh[:self.num_bars]
        self.target_right_heights[:self.num_bars] = rh[:self.num_bars]

        bass_count = max(1, min(len(new_heights), self.num_bars // 8))
        self._bass_target = sum(new_heights[:bass_count]) / float(bass_count)

        left_avg  = sum(lh) / float(max(1, len(lh))) if lh else 0.0
        right_avg = sum(rh) / float(max(1, len(rh))) if rh else 0.0
        total = left_avg + right_avg
        # Amplify so small L/R differences produce visible ball movement.
        raw = (right_avg - left_avg) / total if total > 1e-6 else 0.0
        self._balance_target = max(-1.0, min(1.0, raw * 5.0))

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _update_render_cache(self):
        self._cached_gain    = (
            float(self._theme_cfg["height_gain"])
            * float(self._profile_cfg["gain_mul"])
            * _display_gain_multiplier(self.frequency_scale_name)
        )
        self._cached_spacing = max(0.8, float(self._theme_cfg["bar_spacing"]) * float(self._profile_cfg["spacing_mul"]))
        self._dirty_static   = True

    def set_num_bars(self, count):
        try:
            n = int(count)
        except Exception:
            return
        if n <= 0 or n == self.num_bars:
            return
        self.num_bars        = min(n, 512)
        self.target_heights  = [0.0] * 512
        self.current_heights = [0.0] * 512
        self.peak_holds      = [0.0] * 512
        self.peak_ttl        = [0]   * 512
        self.trail_heights   = [0.0] * 512
        self._color_cache    = None
        self._dirty_static   = True

    def set_theme(self, name):
        if name in self.themes:
            self.theme_name   = name
            self._theme_cfg   = self.themes[name]
            self._color_cache = None
            self._update_render_cache()

    def set_effect(self, name):
        mode = _BARS_GL_EFFECT_MODES.get(name, 0)
        if mode != self.effect_mode:
            self.effect_mode   = mode
            self._dirty_static = True

    def set_profile(self, name):
        if name in self.profiles:
            self.profile_name = name
            self._profile_cfg = self.profiles[name]
            self._update_render_cache()

    def set_frequency_scale(self, name):
        if name in self.frequency_scale_names:
            self.frequency_scale_name = name
            self._update_render_cache()

    def get_theme_names(self):
        return list(self.themes.keys())

    def get_effect_names(self):
        return list(_BARS_GL_EFFECT_MODES.keys())

    def get_profile_names(self):
        return list(self.profiles.keys())

    def get_frequency_scale_names(self):
        return list(self.frequency_scale_names)


class HybridVisualizer(Gtk.Overlay):
    """
    Combined visualizer that keeps the Cairo renderer available for the full
    effect list while exposing the GL dots path as an extra selectable effect.

    Uses a Gtk.Overlay so a transparent frequency-axis DrawingArea can be
    layered on top of the GL renderers (which cannot draw text natively).
    The Cairo renderer draws its own axis, so the overlay is hidden when the
    Cairo backend is active.
    """

    GL_EFFECT_NAME   = "Dots"
    _CAIRO_CHILD_NAME = "cairo"
    _GL_CHILD_NAME    = "gl"
    _BARS_GL_CHILD_NAME = "bars_gl"
    # Effects routed to BarsGLVisualizer
    _BARS_GL_EFFECTS = frozenset(_BARS_GL_EFFECT_MODES.keys())

    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)

        # Internal stack holds Cairo / GL / BarsGL backends.
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)
        self.set_child(self._stack)

        self._cairo_viz = SpectrumVisualizer()
        self._cairo_viz.set_hexpand(True)
        self._cairo_viz.set_vexpand(True)
        self._stack.add_named(self._cairo_viz, self._CAIRO_CHILD_NAME)

        self._gl_viz      = None
        self._bars_gl_viz = None
        self._last_frame  = None
        self._active      = False
        self._freq_scale_name = _FREQ_SCALE_LINEAR
        self._theme_name   = str(getattr(self._cairo_viz, "theme_name",   "Aurora (Default)") or "Aurora (Default)")
        self._profile_name = str(getattr(self._cairo_viz, "profile_name", "Dynamic") or "Dynamic")
        self._effect_name  = str(getattr(self._cairo_viz, "effect_name",  "Bars") or "Bars")
        try:
            self._num_bars = int(getattr(self._cairo_viz, "num_bars", 32) or 32)
        except Exception:
            self._num_bars = 32

        try:
            self._gl_viz = DotsGLVisualizer()
            self._gl_viz.set_hexpand(True)
            self._gl_viz.set_vexpand(True)
            self._gl_viz.set_num_bars(self._num_bars)
            self._gl_viz.set_theme(self._theme_name)
            self._gl_viz.set_profile(self._profile_name)
            self._stack.add_named(self._gl_viz, self._GL_CHILD_NAME)
        except Exception:
            self._gl_viz = None
            logger.warning("DotsGL backend unavailable", exc_info=True)

        try:
            self._bars_gl_viz = BarsGLVisualizer()
            self._bars_gl_viz.set_hexpand(True)
            self._bars_gl_viz.set_vexpand(True)
            self._bars_gl_viz.set_num_bars(self._num_bars)
            self._bars_gl_viz.set_theme(self._theme_name)
            self._bars_gl_viz.set_profile(self._profile_name)
            self._bars_gl_viz.set_effect(self._effect_name)
            self._stack.add_named(self._bars_gl_viz, self._BARS_GL_CHILD_NAME)
            logger.info("Visualizer backend selected: hybrid (cairo + gl + bars_gl)")
        except Exception:
            self._bars_gl_viz = None
            logger.warning("BarsGL backend unavailable", exc_info=True)

        # Transparent frequency-axis overlay — visible only when a GL backend
        # is active (the Cairo renderer draws its own axis).
        self._freq_axis_da = Gtk.DrawingArea()
        self._freq_axis_da.set_hexpand(True)
        self._freq_axis_da.set_vexpand(True)
        self._freq_axis_da.set_draw_func(self._draw_freq_axis_overlay)
        self._freq_axis_da.set_can_target(False)  # pass-through mouse events
        self._freq_axis_da.set_visible(False)
        self.add_overlay(self._freq_axis_da)

        self._stack.set_visible_child_name(self._CAIRO_CHILD_NAME)
        self._sync_backend_state(seed_visible=False)

    @staticmethod
    def _copy_frame(frame):
        if isinstance(frame, dict):
            mono = list(frame.get("mono") or [])
            left = list(frame.get("left") or mono)
            right = list(frame.get("right") or mono)
            return {"mono": mono, "left": left, "right": right}
        return list(frame or [])

    def _draw_freq_axis_overlay(self, _da, cr, width, height):
        """Draw frequency ticks on the transparent overlay above GL backends."""
        _draw_freq_axis_cairo(cr, width, height, self._freq_scale_name)

    def _active_child_name(self):
        if self._effect_name == self.GL_EFFECT_NAME and self._gl_viz is not None:
            return self._GL_CHILD_NAME
        if self._effect_name in self._BARS_GL_EFFECTS and self._bars_gl_viz is not None:
            return self._BARS_GL_CHILD_NAME
        return self._CAIRO_CHILD_NAME

    def _visible_backend(self):
        name = self._active_child_name()
        if name == self._GL_CHILD_NAME:
            return self._gl_viz
        if name == self._BARS_GL_CHILD_NAME:
            return self._bars_gl_viz
        return self._cairo_viz

    def _sync_backend_state(self, seed_visible=True):
        child_name = self._active_child_name()
        if self._stack.get_visible_child_name() != child_name:
            self._stack.set_visible_child_name(child_name)

        use_cairo   = child_name == self._CAIRO_CHILD_NAME
        use_gl      = child_name == self._GL_CHILD_NAME
        use_bars_gl = child_name == self._BARS_GL_CHILD_NAME

        # Show the frequency axis overlay only for GL backends (Cairo draws
        # its own axis).
        self._freq_axis_da.set_visible(use_gl or use_bars_gl)

        self._cairo_viz.set_active(bool(self._active and use_cairo))
        if self._gl_viz is not None:
            self._gl_viz.set_active(bool(self._active and use_gl))
        if self._bars_gl_viz is not None:
            self._bars_gl_viz.set_active(bool(self._active and use_bars_gl))

        if seed_visible and self._last_frame:
            backend = self._visible_backend()
            if backend is not None:
                try:
                    backend.update_data(self._last_frame)
                except Exception:
                    pass

    def _reseed_visible_backend(self):
        backend = self._visible_backend()
        if backend is None or not self._last_frame:
            return
        try:
            backend.update_data(self._last_frame)
        except Exception:
            pass

    def set_active(self, active):
        self._active = bool(active)
        self._sync_backend_state(seed_visible=False)

    def update_data(self, magnitudes):
        if not magnitudes:
            return
        frame = self._copy_frame(magnitudes)
        self._last_frame = frame
        backend = self._visible_backend()
        if backend is not None:
            backend.update_data(frame)

    def set_num_bars(self, count):
        try:
            num_bars = int(count)
        except Exception:
            return
        if num_bars <= 0:
            return
        self._num_bars = num_bars
        self._cairo_viz.set_num_bars(self._num_bars)
        if self._gl_viz is not None:
            self._gl_viz.set_num_bars(self._num_bars)
        if self._bars_gl_viz is not None:
            self._bars_gl_viz.set_num_bars(self._num_bars)
        self._reseed_visible_backend()

    def set_theme(self, name):
        theme_name = str(name or "")
        if theme_name not in (self._cairo_viz.get_theme_names() or []):
            return
        self._theme_name = theme_name
        self._cairo_viz.set_theme(self._theme_name)
        if self._gl_viz is not None:
            self._gl_viz.set_theme(self._theme_name)
        if self._bars_gl_viz is not None:
            self._bars_gl_viz.set_theme(self._theme_name)

    def set_profile(self, name):
        profile_name = str(name or "")
        if profile_name not in (self._cairo_viz.get_profile_names() or []):
            return
        self._profile_name = profile_name
        self._cairo_viz.set_profile(self._profile_name)
        if self._gl_viz is not None:
            self._gl_viz.set_profile(self._profile_name)
        if self._bars_gl_viz is not None:
            self._bars_gl_viz.set_profile(self._profile_name)

    def set_frequency_scale(self, name):
        scale_name = str(name or "")
        if scale_name not in (self._cairo_viz.get_frequency_scale_names() or []):
            return
        self._freq_scale_name = scale_name
        self._cairo_viz.set_frequency_scale(scale_name)
        if self._gl_viz is not None:
            self._gl_viz.set_frequency_scale(scale_name)
        if self._bars_gl_viz is not None:
            self._bars_gl_viz.set_frequency_scale(scale_name)
        self._freq_axis_da.queue_draw()
        self._reseed_visible_backend()

    def set_effect(self, effect_name):
        effect_name = str(effect_name or "")
        if effect_name == self.GL_EFFECT_NAME and self._gl_viz is not None:
            self._effect_name = self.GL_EFFECT_NAME
            self._sync_backend_state(seed_visible=True)
            return

        if effect_name in self._BARS_GL_EFFECTS and self._bars_gl_viz is not None:
            self._effect_name = effect_name
            self._bars_gl_viz.set_effect(effect_name)
            self._sync_backend_state(seed_visible=True)
            return

        cairo_effects = self._cairo_viz.get_effect_names() or []
        mapped_name = {
            "Pro Bars": "Bars",
            "Pro Line": "Wave",
            "Pro Fall": "Fall",
        }.get(effect_name, effect_name)
        if mapped_name in cairo_effects:
            self._effect_name = mapped_name
            self._cairo_viz.set_effect(mapped_name)
            self._sync_backend_state(seed_visible=True)

    def get_theme_names(self):
        return list(self._cairo_viz.get_theme_names() or [])

    def get_effect_names(self):
        names = list(self._cairo_viz.get_effect_names() or [])
        # Remove Cairo duplicates for GL-backed effects (Bars/Peak/Trail/Mirror/Wave/Fill + Dots)
        if self._bars_gl_viz is not None:
            names = [n for n in names if n not in self._BARS_GL_EFFECTS]
            names = list(_BARS_GL_EFFECT_MODES.keys()) + names
        if self._gl_viz is not None:
            names = [n for n in names if n != self.GL_EFFECT_NAME]
            names.append(self.GL_EFFECT_NAME)
        return sorted(names)

    def get_profile_names(self):
        return list(self._cairo_viz.get_profile_names() or [])

    def get_frequency_scale_names(self):
        return list(self._cairo_viz.get_frequency_scale_names() or [])
