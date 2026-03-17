"""
Level Monitor — DR + LUFS overlay for the Spectrum panel.

Layout (top → bottom):
  ┌──────────────────────┐
  │   L bar   R bar      │  level bars (peak tick + RMS fill, from FFT)
  ├──────────────────────┤
  │ M   -18.3            │  Momentary LUFS  (400 ms)
  │ S   -20.1            │  Short-term LUFS (3 s)
  │ I   -14.2            │  Integrated LUFS (full track, gated)
  │ LRA   8.2            │  Loudness Range  (LRA)
  ├──────────────────────┤
  │       DR 09          │  Dynamic Range (colour-coded)
  └──────────────────────┘

LUFS / LRA values are computed by the Rust DSP LUFS meter using proper
K-weighting filters (EBU R128 / ITU-R BS.1770-4) on the PCM audio stream.
They are pushed via set_lufs() each time the UI polls the backend.

Level bars are derived from the FFT magnitude arrays:
  - Level bars : per-frame mean power (smoothed EMA), peak tick with hold

DR is computed by the Rust DSP meter from time-domain PCM samples:
  - DR = peak_dBFS − rms_dBFS over a ~4 s window (40 × 100 ms blocks)
"""

import math

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk


_NEG_INF = -70.0   # display floor for FFT-derived dB values


class LevelMonitor(Gtk.DrawingArea):
    # ---- geometry ----
    _W = 84          # widget width (px)

    # ---- smoothing / windows (frames at ~40 fps) ----
    _LEVEL_ALPHA  = 0.22   # bar fill (mean power)
    _PEAK_ATTACK  = 0.92
    _PEAK_RELEASE = 0.07

    def __init__(self):
        super().__init__()
        # Level bar display state
        self._level_l = _NEG_INF
        self._level_r = _NEG_INF
        self._peak_l  = _NEG_INF
        self._peak_r  = _NEG_INF

        # LUFS + DR display values — set by set_lufs() from the Rust backend
        self._m_lufs  = float('-inf')
        self._s_lufs  = float('-inf')
        self._i_lufs  = float('-inf')
        self._lra     = 0.0
        self._dr_val  = 0

        self.set_size_request(self._W, -1)
        self.set_hexpand(False)
        self.set_vexpand(True)
        self.set_can_target(False)
        self.set_draw_func(self._draw)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, left_mags, right_mags):
        """Update level bars from FFT magnitude arrays (called each frame)."""
        raw_peak_l = self._bins_max(left_mags)
        raw_peak_r = self._bins_max(right_mags)
        raw_mean_l = self._mean_power_db(left_mags)
        raw_mean_r = self._mean_power_db(right_mags)

        # Level bar (mean power, smoothed)
        a = self._LEVEL_ALPHA
        self._level_l = a * raw_mean_l + (1.0 - a) * self._level_l
        self._level_r = a * raw_mean_r + (1.0 - a) * self._level_r

        # Peak tick (max bin, fast attack / slow release)
        al = self._PEAK_ATTACK  if raw_peak_l > self._peak_l else self._PEAK_RELEASE
        ar = self._PEAK_ATTACK  if raw_peak_r > self._peak_r else self._PEAK_RELEASE
        self._peak_l = al * raw_peak_l + (1.0 - al) * self._peak_l
        self._peak_r = ar * raw_peak_r + (1.0 - ar) * self._peak_r

        self.queue_draw()

    def set_lufs(self, m, s, i, lra, dr=0.0):
        """Update LUFS and DR display values from the Rust backend.

        m/s/i: LUFS floats; use float('-inf') for unavailable.
        lra: LU float.
        dr:  Dynamic Range in dB (time-domain, accurate).
        """
        self._m_lufs = float(m)
        self._s_lufs = float(s)
        self._i_lufs = float(i)
        self._lra    = max(0.0, float(lra))
        self._dr_val = int(round(max(0.0, float(dr))))
        self.queue_draw()

    def reset(self):
        self._level_l = _NEG_INF
        self._level_r = _NEG_INF
        self._peak_l  = _NEG_INF
        self._peak_r  = _NEG_INF
        self._m_lufs  = float('-inf')
        self._s_lufs  = float('-inf')
        self._i_lufs  = float('-inf')
        self._lra     = 0.0
        self._dr_val  = 0
        self.queue_draw()

    # ------------------------------------------------------------------
    # Computation helpers (FFT-based, for level bars and DR only)
    # ------------------------------------------------------------------

    def _bins_max(self, mags):
        if not mags:
            return _NEG_INF
        return max(_NEG_INF, max(float(m) for m in mags))

    def _mean_power_db(self, mags):
        if not mags:
            return _NEG_INF
        lin_sum = sum(10.0 ** (max(_NEG_INF, float(m)) / 10.0) for m in mags)
        mean = lin_sum / len(mags)
        return 10.0 * math.log10(mean) if mean > 0.0 else _NEG_INF

    # ------------------------------------------------------------------
    # Layout constants (computed from actual height)
    # ------------------------------------------------------------------

    def _layout(self, width, height):
        DR_H     = 22
        SEP      = 4
        PAD_V    = 4
        LABEL_H  = 13
        LUFS_ROW = 15
        N_LUFS   = 4           # M, S, I, LRA

        lufs_section = LUFS_ROW * N_LUFS + SEP
        bar_avail    = height - LABEL_H - SEP - lufs_section - SEP - DR_H - PAD_V
        bar_h        = max(8, bar_avail)

        bar_w = 18
        gap   = 6
        x_l   = (width - (bar_w * 2 + gap)) // 2
        x_r   = x_l + bar_w + gap

        bar_top   = LABEL_H
        lufs_top  = bar_top + bar_h + SEP
        dr_top    = lufs_top + lufs_section + SEP

        return dict(
            bar_w=bar_w, gap=gap, x_l=x_l, x_r=x_r,
            bar_top=bar_top, bar_h=bar_h,
            lufs_top=lufs_top, lufs_row=LUFS_ROW,
            dr_top=dr_top,
        )

    # ------------------------------------------------------------------
    # Cairo draw
    # ------------------------------------------------------------------

    def _db_to_ratio(self, db, floor=_NEG_INF, ceil=0.0):
        return (max(floor, min(ceil, db)) - floor) / (ceil - floor)

    def _lufs_str(self, val):
        """Format a LUFS value; returns '  ---' for -inf / unavailable."""
        try:
            if not math.isfinite(val) or val <= _NEG_INF + 1:
                return "  ---"
        except (TypeError, ValueError):
            return "  ---"
        return f"{val:+.1f}"

    def _draw(self, _da, cr, width, height):
        g = self._layout(width, height)
        if g["bar_h"] < 4:
            return

        # Background
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.52)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # ---- Level bars ----
        for ch_idx, (level_db, peak_db, label) in enumerate([
            (self._level_l, self._peak_l, "L"),
            (self._level_r, self._peak_r, "R"),
        ]):
            bx = g["x_l"] if ch_idx == 0 else g["x_r"]
            bt = g["bar_top"]
            bh = g["bar_h"]
            bw = g["bar_w"]

            # Channel label
            cr.set_source_rgba(0.60, 0.60, 0.60, 0.85)
            cr.select_font_face("monospace", 0, 0)
            cr.set_font_size(9)
            ext = cr.text_extents(label)
            cr.move_to(bx + (bw - ext[2]) / 2 - ext[0], bt - 2)
            cr.show_text(label)

            # Track
            cr.set_source_rgba(0.11, 0.11, 0.11, 0.92)
            cr.rectangle(bx, bt, bw, bh)
            cr.fill()

            # Fill
            lvl_ratio = self._db_to_ratio(level_db)
            lvl_px    = lvl_ratio * bh
            lvl_y     = bt + (bh - lvl_px)
            # Colour by LUFS M (accurate loudness) rather than FFT mean power,
            # because FFT mean across all bins is ~30 dB lower than true loudness
            # and would otherwise always stay green.
            m = self._m_lufs
            if math.isfinite(m) and m > -9.0:
                r, g_, b = 1.0, 0.20, 0.20   # too hot
            elif math.isfinite(m) and m > -18.0:
                r, g_, b = 1.0, 0.75, 0.00   # normal loud
            else:
                r, g_, b = 0.18, 0.72, 0.40  # quiet / unavailable
            cr.set_source_rgba(r, g_, b, 0.88)
            cr.rectangle(bx, lvl_y, bw, lvl_px)
            cr.fill()

            # Peak tick
            pk_y = bt + (1.0 - self._db_to_ratio(peak_db)) * bh
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.90)
            cr.rectangle(bx, max(bt, pk_y - 1), bw, 2)
            cr.fill()

        # ---- Separator ----
        sep_y = g["bar_top"] + g["bar_h"] + 3
        cr.set_source_rgba(0.35, 0.35, 0.35, 0.50)
        cr.rectangle(6, sep_y, width - 12, 1)
        cr.fill()

        # ---- LUFS rows ----
        cr.select_font_face("monospace", 0, 0)
        cr.set_font_size(10)
        row_h   = g["lufs_row"]
        label_x = 6
        val_x   = width - 6

        rows = [
            ("M",   self._m_lufs),
            ("S",   self._s_lufs),
            ("I",   self._i_lufs),
            ("LRA", self._lra),
        ]

        for i, (lbl, val) in enumerate(rows):
            y = g["lufs_top"] + i * row_h + row_h - 3

            # Label
            cr.set_source_rgba(0.55, 0.55, 0.55, 0.90)
            cr.move_to(label_x, y)
            cr.show_text(lbl)

            # Value — colour by proximity to -14 LUFS streaming target
            if lbl == "LRA":
                val_str = f"{val:.1f}" if val > 0.01 else "---"
                cr.set_source_rgba(0.75, 0.75, 0.75, 1.0)
            else:
                val_str = self._lufs_str(val)
                unavail = not math.isfinite(val) or val <= _NEG_INF + 1
                if unavail:
                    cr.set_source_rgba(0.45, 0.45, 0.45, 1.0)
                elif val > -9.0:
                    cr.set_source_rgba(1.00, 0.28, 0.20, 1.0)   # too hot
                elif val > -16.0:
                    cr.set_source_rgba(0.20, 0.88, 0.45, 1.0)   # target zone
                else:
                    cr.set_source_rgba(0.75, 0.75, 0.75, 1.0)   # quiet

            ext = cr.text_extents(val_str)
            cr.move_to(val_x - ext[2] - ext[0], y)
            cr.show_text(val_str)

        # ---- Separator ----
        sep2_y = g["lufs_top"] + row_h * len(rows) + 2
        cr.set_source_rgba(0.35, 0.35, 0.35, 0.50)
        cr.rectangle(6, sep2_y, width - 12, 1)
        cr.fill()

        # ---- DR value ----
        dr_str = f"DR{self._dr_val:02d}"
        if self._dr_val >= 10:
            cr.set_source_rgba(0.20, 0.88, 0.45, 1.0)
        elif self._dr_val >= 6:
            cr.set_source_rgba(1.00, 0.78, 0.00, 1.0)
        else:
            cr.set_source_rgba(1.00, 0.28, 0.20, 1.0)
        cr.select_font_face("monospace", 0, 1)
        cr.set_font_size(12)
        ext = cr.text_extents(dr_str)
        cr.move_to((width - ext[2]) / 2 - ext[0], g["dr_top"] + 14)
        cr.show_text(dr_str)
