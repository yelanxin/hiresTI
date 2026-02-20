import ctypes
import os
import logging
import time
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)

class RustVizCore:
    def __init__(self):
        self._lib = self._load_library()
        if self._lib is None:
            logger.info("Rust viz core unavailable; falling back to Python spectrum path.")
            return
        logger.info("Rust viz core loaded successfully.")
        fn = self._lib.process_spectrum
        fn.argtypes = [
            ctypes.POINTER(ctypes.c_float),  # input ptr
            ctypes.c_size_t,                 # input len
            ctypes.c_size_t,                 # num bars
            ctypes.c_float,                  # db min
            ctypes.c_float,                  # db range
            ctypes.POINTER(ctypes.c_float),  # output ptr
            ctypes.c_size_t,                 # output len
        ]
        fn.restype = ctypes.c_size_t
        self._process_spectrum = fn

        self._build_log_bins = None
        try:
            bins = self._lib.build_log_bins
            bins.argtypes = [
                ctypes.POINTER(ctypes.c_float),  # input ptr
                ctypes.c_size_t,                 # input len
                ctypes.POINTER(ctypes.c_float),  # output ptr
                ctypes.c_size_t,                 # output len
            ]
            bins.restype = ctypes.c_size_t
            self._build_log_bins = bins
        except Exception:
            logger.info("Rust viz core lacks build_log_bins symbol; using Python fallback for log bins.")

        self._build_spiral_points = None
        try:
            spiral = self._lib.build_spiral_points
            spiral.argtypes = [
                ctypes.POINTER(ctypes.c_float),  # bins ptr
                ctypes.c_size_t,                 # bins len
                ctypes.c_float,                  # width
                ctypes.c_float,                  # height
                ctypes.c_float,                  # phase
                ctypes.c_float,                  # gain
                ctypes.POINTER(ctypes.c_float),  # output ptr
                ctypes.c_size_t,                 # output len
            ]
            spiral.restype = ctypes.c_size_t
            self._build_spiral_points = spiral
        except Exception:
            logger.info("Rust viz core lacks build_spiral_points symbol; using Python fallback for spiral points.")

        self._build_neon_spokes = None
        try:
            neon = self._lib.build_neon_spokes
            neon.argtypes = [
                ctypes.POINTER(ctypes.c_float),  # bins ptr
                ctypes.c_size_t,                 # bins len
                ctypes.c_float,                  # width
                ctypes.c_float,                  # height
                ctypes.c_float,                  # phase
                ctypes.c_float,                  # gain
                ctypes.POINTER(ctypes.c_float),  # output ptr
                ctypes.c_size_t,                 # output len
            ]
            neon.restype = ctypes.c_size_t
            self._build_neon_spokes = neon
        except Exception:
            logger.info("Rust viz core lacks build_neon_spokes symbol; using Python fallback for neon spokes.")

        self._build_neon_ring_points = None
        try:
            rings = self._lib.build_neon_ring_points
            rings.argtypes = [
                ctypes.c_size_t,                # ring count
                ctypes.c_float,                 # width
                ctypes.c_float,                 # height
                ctypes.c_float,                 # phase
                ctypes.c_float,                 # bass
                ctypes.POINTER(ctypes.c_float), # output ptr
                ctypes.c_size_t,                # output len
            ]
            rings.restype = ctypes.c_size_t
            self._build_neon_ring_points = rings
        except Exception:
            logger.info("Rust viz core lacks build_neon_ring_points symbol; using Python fallback for neon rings.")

        self._build_line_points = None
        try:
            line = self._lib.build_line_points
            line.argtypes = [
                ctypes.POINTER(ctypes.c_float),  # bins ptr
                ctypes.c_size_t,                 # bins len
                ctypes.c_float,                  # width
                ctypes.c_float,                  # height
                ctypes.c_float,                  # gain
                ctypes.POINTER(ctypes.c_float),  # output ptr
                ctypes.c_size_t,                 # output len
            ]
            line.restype = ctypes.c_size_t
            self._build_line_points = line
        except Exception:
            logger.info("Rust viz core lacks build_line_points symbol; using Python fallback for line points.")

        self._build_fall_cells = None
        try:
            fall = self._lib.build_fall_cells
            fall.argtypes = [
                ctypes.POINTER(ctypes.c_float),  # levels ptr
                ctypes.c_size_t,                 # levels len
                ctypes.c_float,                  # gain
                ctypes.c_float,                  # height
                ctypes.c_float,                  # step_y
                ctypes.c_size_t,                 # layers
                ctypes.POINTER(ctypes.c_float),  # output ptr
                ctypes.c_size_t,                 # output len
            ]
            fall.restype = ctypes.c_size_t
            self._build_fall_cells = fall
        except Exception:
            logger.info("Rust viz core lacks build_fall_cells symbol; using Python fallback for fall cells.")

        self._build_pro_fall_column = None
        try:
            pfc = self._lib.build_pro_fall_column
            pfc.argtypes = [
                ctypes.POINTER(ctypes.c_float),  # bins ptr
                ctypes.c_size_t,                 # bins len
                ctypes.c_float,                  # gain
                ctypes.POINTER(ctypes.c_float),  # output ptr
                ctypes.c_size_t,                 # output len
            ]
            pfc.restype = ctypes.c_size_t
            self._build_pro_fall_column = pfc
        except Exception:
            logger.info("Rust viz core lacks build_pro_fall_column symbol; using Python fallback for pro-fall column.")

        self._build_pro_fall_rgba = None
        try:
            pf_rgba = self._lib.build_pro_fall_rgba
            pf_rgba.argtypes = [
                ctypes.POINTER(ctypes.c_float),  # frames ptr (cols*rows)
                ctypes.c_size_t,                 # cols
                ctypes.c_size_t,                 # rows
                ctypes.c_float,                  # gain
                ctypes.POINTER(ctypes.c_float),  # palette ptr (palette_n*4)
                ctypes.c_size_t,                 # palette_n
                ctypes.POINTER(ctypes.c_ubyte),  # output rgba ptr
                ctypes.c_size_t,                 # output len bytes
            ]
            pf_rgba.restype = ctypes.c_size_t
            self._build_pro_fall_rgba = pf_rgba
        except Exception:
            logger.info("Rust viz core lacks build_pro_fall_rgba symbol; using Python fallback for pro-fall image.")

        self._build_fall_rgba = None
        try:
            fall_rgba = self._lib.build_fall_rgba
            fall_rgba.argtypes = [
                ctypes.POINTER(ctypes.c_float),  # levels ptr
                ctypes.c_size_t,                 # levels len
                ctypes.c_float,                  # gain
                ctypes.c_size_t,                 # height px
                ctypes.c_size_t,                 # step y px
                ctypes.c_size_t,                 # thickness px
                ctypes.POINTER(ctypes.c_float),  # bar colors ptr
                ctypes.c_size_t,                 # bar colors len
                ctypes.POINTER(ctypes.c_ubyte),  # output rgba ptr
                ctypes.c_size_t,                 # output len bytes
            ]
            fall_rgba.restype = ctypes.c_size_t
            self._build_fall_rgba = fall_rgba
        except Exception:
            logger.info("Rust viz core lacks build_fall_rgba symbol; using Python fallback for fall image.")

        self._build_dots_rgba = None
        try:
            dots_rgba = self._lib.build_dots_rgba
            dots_rgba.argtypes = [
                ctypes.POINTER(ctypes.c_float),  # levels ptr
                ctypes.c_size_t,                 # levels len
                ctypes.c_float,                  # gain
                ctypes.c_size_t,                 # canvas width px
                ctypes.c_size_t,                 # height px
                ctypes.c_size_t,                 # bar width px
                ctypes.c_size_t,                 # spacing px
                ctypes.c_size_t,                 # dot h px
                ctypes.c_size_t,                 # gap y px
                ctypes.POINTER(ctypes.c_float),  # bar colors ptr
                ctypes.c_size_t,                 # bar colors len
                ctypes.POINTER(ctypes.c_ubyte),  # output rgba ptr
                ctypes.c_size_t,                 # output len bytes
            ]
            dots_rgba.restype = ctypes.c_size_t
            self._build_dots_rgba = dots_rgba
        except Exception:
            logger.info("Rust viz core lacks build_dots_rgba symbol; using Python fallback for dots image.")

        newp = self._lib.viz_processor_new
        newp.argtypes = [
            ctypes.c_size_t,  # num bars
            ctypes.c_float,   # max hz
            ctypes.c_float,   # smooth
            ctypes.c_float,   # db min
            ctypes.c_float,   # db range
        ]
        newp.restype = ctypes.c_void_p
        self._viz_processor_new = newp

        freep = self._lib.viz_processor_free
        freep.argtypes = [ctypes.c_void_p]
        freep.restype = None
        self._viz_processor_free = freep

        resetp = self._lib.viz_processor_reset
        resetp.argtypes = [ctypes.c_void_p]
        resetp.restype = None
        self._viz_processor_reset = resetp

        proc = self._lib.viz_processor_process
        proc.argtypes = [
            ctypes.c_void_p,                 # processor
            ctypes.POINTER(ctypes.c_float),  # input ptr
            ctypes.c_size_t,                 # input len
            ctypes.c_double,                 # now ms
            ctypes.POINTER(ctypes.c_float),  # output ptr
            ctypes.c_size_t,                 # output len
        ]
        proc.restype = ctypes.c_size_t
        self._viz_processor_process = proc

    @property
    def available(self) -> bool:
        return self._lib is not None

    def process_spectrum(
        self,
        magnitudes: Iterable[float],
        num_bars: int,
        db_min: float = -60.0,
        db_range: float = 60.0,
    ) -> Optional[List[float]]:
        if self._lib is None:
            return None
        vals = [float(v) for v in magnitudes]
        if not vals or num_bars <= 0:
            return [0.0] * max(0, int(num_bars))

        in_len = len(vals)
        in_buf = (ctypes.c_float * in_len)(*vals)
        out_n = int(num_bars)
        out_buf = (ctypes.c_float * out_n)()
        written = int(
            self._process_spectrum(
                in_buf,
                in_len,
                out_n,
                ctypes.c_float(db_min),
                ctypes.c_float(db_range),
                out_buf,
                out_n,
            )
        )
        if written <= 0:
            return None
        out = [float(out_buf[i]) for i in range(min(written, out_n))]
        if len(out) < out_n:
            out.extend([0.0] * (out_n - len(out)))
        return out

    def create_processor(
        self,
        num_bars: int,
        max_hz: float = 24.0,
        smooth: float = 0.45,
        db_min: float = -60.0,
        db_range: float = 60.0,
    ) -> Optional["RustVizProcessor"]:
        if self._lib is None:
            return None
        ptr = self._viz_processor_new(
            int(num_bars),
            ctypes.c_float(max_hz),
            ctypes.c_float(smooth),
            ctypes.c_float(db_min),
            ctypes.c_float(db_range),
        )
        if not ptr:
            return None
        return RustVizProcessor(self, ptr, int(num_bars))

    def build_log_bins(self, values: Iterable[float], out_count: int) -> Optional[List[float]]:
        if self._lib is None:
            return None
        if self._build_log_bins is None:
            return None
        out_n = int(out_count)
        if out_n <= 0:
            return []
        vals = [float(v) for v in values]
        if not vals:
            return [0.0] * out_n
        in_len = len(vals)
        in_buf = (ctypes.c_float * in_len)(*vals)
        out_buf = (ctypes.c_float * out_n)()
        written = int(self._build_log_bins(in_buf, in_len, out_buf, out_n))
        if written <= 0:
            return None
        out = [float(out_buf[i]) for i in range(min(written, out_n))]
        if len(out) < out_n:
            out.extend([0.0] * (out_n - len(out)))
        return out

    def build_spiral_points(
        self,
        bins: Iterable[float],
        width: float,
        height: float,
        phase: float,
        gain: float,
        max_points: int = 240,
    ) -> Optional[List[tuple]]:
        if self._lib is None or self._build_spiral_points is None:
            return None
        vals = [float(v) for v in bins]
        if not vals:
            return []
        in_len = len(vals)
        in_buf = (ctypes.c_float * in_len)(*vals)
        out_floats = max(4, int(max_points) * 4)
        out_buf = (ctypes.c_float * out_floats)()
        written = int(
            self._build_spiral_points(
                in_buf,
                in_len,
                ctypes.c_float(float(width)),
                ctypes.c_float(float(height)),
                ctypes.c_float(float(phase)),
                ctypes.c_float(float(gain)),
                out_buf,
                out_floats,
            )
        )
        if written <= 0:
            return []
        points = []
        w = min(written, out_floats)
        i = 0
        while i + 3 < w:
            points.append((float(out_buf[i]), float(out_buf[i + 1]), float(out_buf[i + 2]), float(out_buf[i + 3])))
            i += 4
        return points

    def build_neon_spokes(
        self,
        bins: Iterable[float],
        width: float,
        height: float,
        phase: float,
        gain: float,
        max_points: int = 256,
    ) -> Optional[List[tuple]]:
        if self._lib is None or self._build_neon_spokes is None:
            return None
        vals = [float(v) for v in bins]
        if not vals:
            return []
        in_len = len(vals)
        in_buf = (ctypes.c_float * in_len)(*vals)
        out_floats = max(6, int(max_points) * 6)
        out_buf = (ctypes.c_float * out_floats)()
        written = int(
            self._build_neon_spokes(
                in_buf,
                in_len,
                ctypes.c_float(float(width)),
                ctypes.c_float(float(height)),
                ctypes.c_float(float(phase)),
                ctypes.c_float(float(gain)),
                out_buf,
                out_floats,
            )
        )
        if written <= 0:
            return []
        out = []
        w = min(written, out_floats)
        i = 0
        while i + 5 < w:
            out.append(
                (
                    float(out_buf[i]),
                    float(out_buf[i + 1]),
                    float(out_buf[i + 2]),
                    float(out_buf[i + 3]),
                    float(out_buf[i + 4]),
                    float(out_buf[i + 5]),
                )
            )
            i += 6
        return out

    def build_neon_ring_points(
        self,
        ring_count: int,
        width: float,
        height: float,
        phase: float,
        bass: float,
        seg_n: int = 180,
    ) -> Optional[List[tuple]]:
        if self._lib is None or self._build_neon_ring_points is None:
            return None
        rc = max(1, int(ring_count))
        out_floats = max(6, rc * max(8, int(seg_n)) * 6)
        out_buf = (ctypes.c_float * out_floats)()
        written = int(
            self._build_neon_ring_points(
                ctypes.c_size_t(rc),
                ctypes.c_float(float(width)),
                ctypes.c_float(float(height)),
                ctypes.c_float(float(phase)),
                ctypes.c_float(float(bass)),
                out_buf,
                ctypes.c_size_t(out_floats),
            )
        )
        if written <= 0:
            return []
        out = []
        w = min(written, out_floats)
        i = 0
        while i + 5 < w:
            out.append(
                (
                    float(out_buf[i]),
                    float(out_buf[i + 1]),
                    float(out_buf[i + 2]),
                    float(out_buf[i + 3]),
                    float(out_buf[i + 4]),
                    float(out_buf[i + 5]),
                )
            )
            i += 6
        return out

    def build_line_points(
        self,
        bins: Iterable[float],
        width: float,
        height: float,
        gain: float,
    ) -> Optional[List[tuple]]:
        if self._lib is None or self._build_line_points is None:
            return None
        vals = [float(v) for v in bins]
        if len(vals) < 2:
            return []
        in_len = len(vals)
        in_buf = (ctypes.c_float * in_len)(*vals)
        out_floats = max(2, in_len * 2)
        out_buf = (ctypes.c_float * out_floats)()
        written = int(
            self._build_line_points(
                in_buf,
                in_len,
                ctypes.c_float(float(width)),
                ctypes.c_float(float(height)),
                ctypes.c_float(float(gain)),
                out_buf,
                out_floats,
            )
        )
        if written <= 0:
            return []
        out = []
        w = min(written, out_floats)
        i = 0
        while i + 1 < w:
            out.append((float(out_buf[i]), float(out_buf[i + 1])))
            i += 2
        return out

    def build_fall_cells(
        self,
        levels: Iterable[float],
        gain: float,
        height: float,
        step_y: float,
        layers: int,
    ) -> Optional[List[tuple]]:
        if self._lib is None or self._build_fall_cells is None:
            return None
        vals = [float(v) for v in levels]
        if not vals:
            return []
        in_len = len(vals)
        in_buf = (ctypes.c_float * in_len)(*vals)
        max_cells = max(1, int(layers) * in_len)
        out_floats = max_cells * 3
        out_buf = (ctypes.c_float * out_floats)()
        written = int(
            self._build_fall_cells(
                in_buf,
                in_len,
                ctypes.c_float(float(gain)),
                ctypes.c_float(float(height)),
                ctypes.c_float(float(step_y)),
                ctypes.c_size_t(max(1, int(layers))),
                out_buf,
                ctypes.c_size_t(out_floats),
            )
        )
        if written <= 0:
            return []
        out = []
        w = min(written, out_floats)
        i = 0
        while i + 2 < w:
            out.append((int(out_buf[i]), float(out_buf[i + 1]), float(out_buf[i + 2])))
            i += 3
        return out

    def build_pro_fall_column(
        self,
        bins: Iterable[float],
        gain: float,
    ) -> Optional[List[tuple]]:
        if self._lib is None or self._build_pro_fall_column is None:
            return None
        vals = [float(v) for v in bins]
        if not vals:
            return []
        in_len = len(vals)
        in_buf = (ctypes.c_float * in_len)(*vals)
        out_floats = in_len * 2
        out_buf = (ctypes.c_float * out_floats)()
        written = int(
            self._build_pro_fall_column(
                in_buf,
                in_len,
                ctypes.c_float(float(gain)),
                out_buf,
                ctypes.c_size_t(out_floats),
            )
        )
        if written <= 0:
            return []
        out = []
        w = min(written, out_floats)
        i = 0
        while i + 1 < w:
            out.append((int(out_buf[i]), float(out_buf[i + 1])))
            i += 2
        return out

    def build_pro_fall_rgba(
        self,
        frames: Iterable[Iterable[float]],
        gain: float,
        palette_rgba: Iterable[Iterable[float]],
    ) -> Optional[tuple]:
        if self._lib is None or self._build_pro_fall_rgba is None:
            return None
        cols_data = [list(col) for col in frames]
        if not cols_data:
            return None
        cols = len(cols_data)
        rows = len(cols_data[0]) if cols_data[0] else 0
        if cols <= 0 or rows <= 0:
            return None
        flat_frames = []
        for c in cols_data:
            if len(c) < rows:
                c = c + [0.0] * (rows - len(c))
            elif len(c) > rows:
                c = c[:rows]
            flat_frames.extend(float(v) for v in c)
        frames_buf = (ctypes.c_float * (cols * rows))(*flat_frames)

        pal = [tuple(p) for p in palette_rgba]
        if not pal:
            return None
        palette_n = len(pal)
        flat_pal = []
        for p in pal:
            r, g, b, a = (float(p[0]), float(p[1]), float(p[2]), float(p[3]))
            flat_pal.extend([r, g, b, a])
        palette_buf = (ctypes.c_float * (palette_n * 4))(*flat_pal)

        out_len = cols * rows * 4
        out_arr = (ctypes.c_ubyte * out_len)()
        written = int(
            self._build_pro_fall_rgba(
                frames_buf,
                ctypes.c_size_t(cols),
                ctypes.c_size_t(rows),
                ctypes.c_float(float(gain)),
                palette_buf,
                ctypes.c_size_t(palette_n),
                out_arr,
                ctypes.c_size_t(out_len),
            )
        )
        if written <= 0:
            return None
        return (bytearray(out_arr[:written]), cols, rows)

    def build_fall_rgba(
        self,
        levels: Iterable[float],
        gain: float,
        height_px: int,
        step_y_px: int,
        thickness_px: int,
        bar_colors_rgba: Iterable[Iterable[float]],
    ) -> Optional[tuple]:
        if self._lib is None or self._build_fall_rgba is None:
            return None
        vals = [float(v) for v in levels]
        if not vals:
            return None
        width_px = len(vals)
        hpx = max(1, int(height_px))
        sy = max(1, int(step_y_px))
        th = max(1, int(thickness_px))

        colors = [tuple(c) for c in bar_colors_rgba]
        if len(colors) < width_px:
            if colors:
                last = colors[-1]
            else:
                last = (0.0, 0.7, 1.0, 1.0)
            colors.extend([last] * (width_px - len(colors)))
        elif len(colors) > width_px:
            colors = colors[:width_px]

        levels_buf = (ctypes.c_float * width_px)(*vals)
        flat_colors = []
        for c in colors:
            flat_colors.extend([float(c[0]), float(c[1]), float(c[2]), float(c[3])])
        color_len = width_px * 4
        colors_buf = (ctypes.c_float * color_len)(*flat_colors)
        out_len = width_px * hpx * 4
        out_arr = (ctypes.c_ubyte * out_len)()
        written = int(
            self._build_fall_rgba(
                levels_buf,
                ctypes.c_size_t(width_px),
                ctypes.c_float(float(gain)),
                ctypes.c_size_t(hpx),
                ctypes.c_size_t(sy),
                ctypes.c_size_t(th),
                colors_buf,
                ctypes.c_size_t(color_len),
                out_arr,
                ctypes.c_size_t(out_len),
            )
        )
        if written <= 0:
            return None
        return (bytearray(out_arr[:written]), width_px, hpx)

    def build_dots_rgba(
        self,
        levels: Iterable[float],
        gain: float,
        canvas_width_px: int,
        height_px: int,
        bar_w_px: int,
        spacing_px: int,
        dot_h_px: int,
        gap_y_px: int,
        bar_colors_rgba: Iterable[Iterable[float]],
    ) -> Optional[tuple]:
        if self._lib is None or self._build_dots_rgba is None:
            return None
        vals = [float(v) for v in levels]
        if not vals:
            return None
        width_px = max(1, int(canvas_width_px))
        hpx = max(1, int(height_px))
        bw = max(1, int(bar_w_px))
        sp = max(0, int(spacing_px))
        dh = max(1, int(dot_h_px))
        gp = max(0, int(gap_y_px))

        colors = [tuple(c) for c in bar_colors_rgba]
        if len(colors) < width_px:
            last = colors[-1] if colors else (0.0, 0.7, 1.0, 1.0)
            colors.extend([last] * (width_px - len(colors)))
        elif len(colors) > width_px:
            colors = colors[:width_px]

        levels_buf = (ctypes.c_float * width_px)(*vals)
        flat_colors = []
        for c in colors:
            flat_colors.extend([float(c[0]), float(c[1]), float(c[2]), float(c[3])])
        color_len = width_px * 4
        colors_buf = (ctypes.c_float * color_len)(*flat_colors)
        out_len = width_px * hpx * 4
        out_arr = (ctypes.c_ubyte * out_len)()
        written = int(
            self._build_dots_rgba(
                levels_buf,
                ctypes.c_size_t(len(vals)),
                ctypes.c_float(float(gain)),
                ctypes.c_size_t(width_px),
                ctypes.c_size_t(hpx),
                ctypes.c_size_t(bw),
                ctypes.c_size_t(sp),
                ctypes.c_size_t(dh),
                ctypes.c_size_t(gp),
                colors_buf,
                ctypes.c_size_t(color_len),
                out_arr,
                ctypes.c_size_t(out_len),
            )
        )
        if written <= 0:
            return None
        return (bytearray(out_arr[:written]), width_px, hpx)

    def _load_library(self):
        here = Path(__file__).resolve().parent
        env_path = os.environ.get("HIRESTI_RUST_VIZ_LIB")
        candidates = []
        if env_path:
            candidates.append(Path(env_path))
        candidates.extend(
            [
                here / "rust_viz_core" / "target" / "release" / "libviz_core.so",
                here / "rust_viz_core" / "target" / "release" / "libviz_core.dylib",
                here / "rust_viz_core" / "target" / "release" / "viz_core.dll",
            ]
        )
        for p in candidates:
            try:
                if p.exists():
                    return ctypes.CDLL(str(p))
            except Exception:
                continue
        return None


class RustVizProcessor:
    def __init__(self, core: RustVizCore, ptr: ctypes.c_void_p, num_bars: int):
        self._core = core
        self._ptr = ptr
        self._num_bars = max(1, int(num_bars))

    def close(self):
        if self._ptr:
            self._core._viz_processor_free(self._ptr)
            self._ptr = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def reset(self):
        if self._ptr:
            self._core._viz_processor_reset(self._ptr)

    def process(self, magnitudes: Iterable[float], now_ms: Optional[float] = None) -> Optional[List[float]]:
        if not self._ptr:
            return None
        vals = [float(v) for v in magnitudes]
        if not vals:
            return None
        if now_ms is None:
            now_ms = time.monotonic() * 1000.0
        in_len = len(vals)
        in_buf = (ctypes.c_float * in_len)(*vals)
        out_buf = (ctypes.c_float * self._num_bars)()
        written = int(
            self._core._viz_processor_process(
                self._ptr,
                in_buf,
                in_len,
                ctypes.c_double(float(now_ms)),
                out_buf,
                self._num_bars,
            )
        )
        if written <= 0:
            return None
        out = [float(out_buf[i]) for i in range(min(written, self._num_bars))]
        if len(out) < self._num_bars:
            out.extend([0.0] * (self._num_bars - len(out)))
        return out
