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
        self._bars_rgba_buffers = {}
        self._bars_rgba_colors_cache = {}
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

        self._build_bars_rgba = None
        try:
            bars_rgba = self._lib.build_bars_rgba
            bars_rgba.argtypes = [
                ctypes.POINTER(ctypes.c_float),  # levels ptr
                ctypes.c_size_t,                 # levels len
                ctypes.c_float,                  # gain
                ctypes.c_size_t,                 # canvas width px
                ctypes.c_size_t,                 # height px
                ctypes.c_size_t,                 # bar width px
                ctypes.c_size_t,                 # spacing px
                ctypes.POINTER(ctypes.c_float),  # bar colors ptr
                ctypes.c_size_t,                 # bar colors len
                ctypes.POINTER(ctypes.c_ubyte),  # output rgba ptr
                ctypes.c_size_t,                 # output len bytes
            ]
            bars_rgba.restype = ctypes.c_size_t
            self._build_bars_rgba = bars_rgba
        except Exception:
            logger.info("Rust viz core lacks build_bars_rgba symbol; using Python fallback for bars image.")
        self._bars_renderer_new = None
        self._bars_renderer_free = None
        self._bars_renderer_set_colors = None
        self._bars_renderer_render = None
        self._bars_renderer_get_frame = None
        try:
            br_new = self._lib.viz_bars_renderer_new
            br_new.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t]
            br_new.restype = ctypes.c_void_p
            br_free = self._lib.viz_bars_renderer_free
            br_free.argtypes = [ctypes.c_void_p]
            br_free.restype = None
            br_set = self._lib.viz_bars_renderer_set_colors
            br_set.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_size_t]
            br_set.restype = ctypes.c_int
            br_render = self._lib.viz_bars_renderer_render
            br_render.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_float),
                ctypes.c_size_t,
                ctypes.c_float,
                ctypes.c_size_t,
                ctypes.c_size_t,
            ]
            br_render.restype = ctypes.c_int
            br_get = self._lib.viz_bars_renderer_get_frame
            br_get.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.POINTER(ctypes.c_uint64),
            ]
            br_get.restype = ctypes.c_int
            self._bars_renderer_new = br_new
            self._bars_renderer_free = br_free
            self._bars_renderer_set_colors = br_set
            self._bars_renderer_render = br_render
            self._bars_renderer_get_frame = br_get
        except Exception:
            logger.info("Rust viz core lacks bars renderer object API; using bars_rgba fallback.")

        self._count_artist_keys = None
        try:
            count_keys = self._lib.count_artist_keys
            count_keys.argtypes = [
                ctypes.POINTER(ctypes.c_uint64),  # keys ptr
                ctypes.c_size_t,                  # keys len
                ctypes.POINTER(ctypes.c_uint64),  # out keys ptr
                ctypes.POINTER(ctypes.c_uint32),  # out counts ptr
                ctypes.c_size_t,                  # out len
            ]
            count_keys.restype = ctypes.c_size_t
            self._count_artist_keys = count_keys
        except Exception:
            logger.info("Rust viz core lacks count_artist_keys symbol; using Python fallback for artist counts.")

        self._filter_sort_indices_no_query = None
        try:
            filt = self._lib.filter_sort_indices_no_query
            filt.argtypes = [
                ctypes.POINTER(ctypes.c_uint64),  # artist keys ptr
                ctypes.POINTER(ctypes.c_uint32),  # title rank ptr
                ctypes.POINTER(ctypes.c_uint32),  # artist rank ptr
                ctypes.POINTER(ctypes.c_uint32),  # album rank ptr
                ctypes.POINTER(ctypes.c_uint32),  # durations ptr
                ctypes.c_size_t,                  # len
                ctypes.c_uint32,                  # sort mode
                ctypes.c_uint64,                  # artist filter key
                ctypes.c_uint8,                   # use artist filter
                ctypes.POINTER(ctypes.c_uint32),  # out indices ptr
                ctypes.c_size_t,                  # out len
            ]
            filt.restype = ctypes.c_size_t
            self._filter_sort_indices_no_query = filt
        except Exception:
            logger.info("Rust viz core lacks filter_sort_indices_no_query symbol; using Python fallback for collection filters.")

        self._filter_sort_indices_with_query = None
        try:
            filtq = self._lib.filter_sort_indices_with_query
            filtq.argtypes = [
                ctypes.POINTER(ctypes.c_ubyte),   # search blob ptr
                ctypes.c_size_t,                  # search blob len
                ctypes.POINTER(ctypes.c_uint32),  # search offsets ptr
                ctypes.POINTER(ctypes.c_uint32),  # search lens ptr
                ctypes.POINTER(ctypes.c_uint64),  # artist keys ptr
                ctypes.POINTER(ctypes.c_uint32),  # title rank ptr
                ctypes.POINTER(ctypes.c_uint32),  # artist rank ptr
                ctypes.POINTER(ctypes.c_uint32),  # album rank ptr
                ctypes.POINTER(ctypes.c_uint32),  # durations ptr
                ctypes.c_size_t,                  # len
                ctypes.c_uint32,                  # sort mode
                ctypes.c_uint64,                  # artist filter key
                ctypes.c_uint8,                   # use artist filter
                ctypes.POINTER(ctypes.c_ubyte),   # query ptr
                ctypes.c_size_t,                  # query len
                ctypes.POINTER(ctypes.c_uint32),  # out indices ptr
                ctypes.c_size_t,                  # out len
            ]
            filtq.restype = ctypes.c_size_t
            self._filter_sort_indices_with_query = filtq
        except Exception:
            logger.info("Rust viz core lacks filter_sort_indices_with_query symbol; using Python fallback for query filters.")

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

        self._viz_state_new = None
        self._viz_state_free = None
        self._viz_state_reset = None
        self._viz_state_set_params = None
        self._viz_state_set_target = None
        self._viz_state_tick_copy = None
        try:
            st_new = self._lib.viz_state_new
            st_new.argtypes = [
                ctypes.c_size_t,  # num bars
                ctypes.c_float,   # smooth
                ctypes.c_float,   # trail decay
                ctypes.c_size_t,  # peak hold frames
                ctypes.c_float,   # peak fall
                ctypes.c_float,   # bass smooth
            ]
            st_new.restype = ctypes.c_void_p
            st_free = self._lib.viz_state_free
            st_free.argtypes = [ctypes.c_void_p]
            st_free.restype = None
            st_reset = self._lib.viz_state_reset
            st_reset.argtypes = [ctypes.c_void_p]
            st_reset.restype = None
            st_setp = self._lib.viz_state_set_params
            st_setp.argtypes = [
                ctypes.c_void_p,
                ctypes.c_float,
                ctypes.c_float,
                ctypes.c_size_t,
                ctypes.c_float,
                ctypes.c_float,
            ]
            st_setp.restype = ctypes.c_int
            st_sett = self._lib.viz_state_set_target
            st_sett.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_size_t]
            st_sett.restype = ctypes.c_size_t
            st_tick = self._lib.viz_state_tick_copy
            st_tick.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_float),
                ctypes.POINTER(ctypes.c_float),
                ctypes.POINTER(ctypes.c_float),
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_float),
            ]
            st_tick.restype = ctypes.c_size_t
            self._viz_state_new = st_new
            self._viz_state_free = st_free
            self._viz_state_reset = st_reset
            self._viz_state_set_params = st_setp
            self._viz_state_set_target = st_sett
            self._viz_state_tick_copy = st_tick
        except Exception:
            logger.info("Rust viz core lacks viz_state_* symbols; using Python animation fallback.")

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

    def create_state_engine(
        self,
        num_bars: int,
        smooth: float = 0.45,
        trail_decay: float = 0.90,
        peak_hold_frames: int = 8,
        peak_fall: float = 0.02,
        bass_smooth: float = 0.22,
    ) -> Optional["RustVizStateEngine"]:
        if self._lib is None or self._viz_state_new is None:
            return None
        ptr = self._viz_state_new(
            int(num_bars),
            ctypes.c_float(float(smooth)),
            ctypes.c_float(float(trail_decay)),
            ctypes.c_size_t(max(0, int(peak_hold_frames))),
            ctypes.c_float(float(peak_fall)),
            ctypes.c_float(float(bass_smooth)),
        )
        if not ptr:
            return None
        return RustVizStateEngine(self, ptr, int(num_bars))

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

    def build_bars_rgba(
        self,
        levels: Iterable[float],
        gain: float,
        canvas_width_px: int,
        height_px: int,
        bar_w_px: int,
        spacing_px: int,
        bar_colors_rgba: Iterable[Iterable[float]],
    ) -> Optional[tuple]:
        if self._lib is None or self._build_bars_rgba is None:
            return None
        vals = [float(v) for v in levels]
        if not vals:
            return None
        width_px = max(1, int(canvas_width_px))
        hpx = max(1, int(height_px))
        bw = max(1, int(bar_w_px))
        sp = max(0, int(spacing_px))

        colors = [tuple(c) for c in bar_colors_rgba]
        needed = len(vals)
        if len(colors) < needed:
            last = colors[-1] if colors else (0.0, 0.7, 1.0, 1.0)
            colors.extend([last] * (needed - len(colors)))
        elif len(colors) > needed:
            colors = colors[:needed]
        color_len = needed * 4
        out_len = width_px * hpx * 4
        buf_key = (needed, width_px, hpx)
        bufs = self._bars_rgba_buffers.get(buf_key)
        if bufs is None:
            bufs = {
                "levels_buf": (ctypes.c_float * needed)(),
                "colors_buf": (ctypes.c_float * color_len)(),
                "out_arr": (ctypes.c_ubyte * out_len)(),
            }
            self._bars_rgba_buffers[buf_key] = bufs
        levels_buf = bufs["levels_buf"]
        colors_buf = bufs["colors_buf"]
        out_arr = bufs["out_arr"]

        for i, v in enumerate(vals):
            levels_buf[i] = float(v)

        colors_sig = (buf_key, id(bar_colors_rgba))
        cached_sig = self._bars_rgba_colors_cache.get(buf_key)
        if cached_sig != colors_sig:
            j = 0
            for c in colors:
                colors_buf[j] = float(c[0]); j += 1
                colors_buf[j] = float(c[1]); j += 1
                colors_buf[j] = float(c[2]); j += 1
                colors_buf[j] = float(c[3]); j += 1
            self._bars_rgba_colors_cache[buf_key] = colors_sig
        written = int(
            self._build_bars_rgba(
                levels_buf,
                ctypes.c_size_t(needed),
                ctypes.c_float(float(gain)),
                ctypes.c_size_t(width_px),
                ctypes.c_size_t(hpx),
                ctypes.c_size_t(bw),
                ctypes.c_size_t(sp),
                colors_buf,
                ctypes.c_size_t(color_len),
                out_arr,
                ctypes.c_size_t(out_len),
            )
        )
        if written <= 0:
            return None
        return (memoryview(out_arr)[:written], width_px, hpx)

    def count_artist_keys(self, keys: Iterable[int]) -> Optional[List[tuple]]:
        if self._lib is None or self._count_artist_keys is None:
            return None
        vals = [int(v) & ((1 << 64) - 1) for v in (keys or [])]
        if not vals:
            return []
        n = len(vals)
        in_buf = (ctypes.c_uint64 * n)(*vals)
        out_keys = (ctypes.c_uint64 * n)()
        out_counts = (ctypes.c_uint32 * n)()
        written = int(self._count_artist_keys(in_buf, n, out_keys, out_counts, n))
        if written <= 0:
            return []
        out = []
        for i in range(min(written, n)):
            out.append((int(out_keys[i]), int(out_counts[i])))
        return out

    def filter_sort_indices_no_query(
        self,
        artist_keys: Iterable[int],
        title_rank: Iterable[int],
        artist_rank: Iterable[int],
        album_rank: Iterable[int],
        durations: Iterable[int],
        sort_mode: int,
        artist_filter_key: int = 0,
        use_artist_filter: bool = False,
    ) -> Optional[List[int]]:
        if self._lib is None or self._filter_sort_indices_no_query is None:
            return None
        keys = [int(v) & ((1 << 64) - 1) for v in (artist_keys or [])]
        n = len(keys)
        if n <= 0:
            return []
        title_vals = [int(v) & 0xFFFFFFFF for v in (title_rank or [])]
        artist_vals = [int(v) & 0xFFFFFFFF for v in (artist_rank or [])]
        album_vals = [int(v) & 0xFFFFFFFF for v in (album_rank or [])]
        dur_vals = [int(v) & 0xFFFFFFFF for v in (durations or [])]
        if len(title_vals) != n or len(artist_vals) != n or len(album_vals) != n or len(dur_vals) != n:
            return None
        keys_buf = (ctypes.c_uint64 * n)(*keys)
        title_buf = (ctypes.c_uint32 * n)(*title_vals)
        artist_buf = (ctypes.c_uint32 * n)(*artist_vals)
        album_buf = (ctypes.c_uint32 * n)(*album_vals)
        dur_buf = (ctypes.c_uint32 * n)(*dur_vals)
        out_buf = (ctypes.c_uint32 * n)()
        written = int(
            self._filter_sort_indices_no_query(
                keys_buf,
                title_buf,
                artist_buf,
                album_buf,
                dur_buf,
                ctypes.c_size_t(n),
                ctypes.c_uint32(int(sort_mode) & 0xFFFFFFFF),
                ctypes.c_uint64(int(artist_filter_key) & ((1 << 64) - 1)),
                ctypes.c_uint8(1 if use_artist_filter else 0),
                out_buf,
                ctypes.c_size_t(n),
            )
        )
        if written <= 0:
            return []
        return [int(out_buf[i]) for i in range(min(written, n))]

    def filter_sort_indices_with_query(
        self,
        search_blob: bytes,
        search_offsets: Iterable[int],
        search_lens: Iterable[int],
        artist_keys: Iterable[int],
        title_rank: Iterable[int],
        artist_rank: Iterable[int],
        album_rank: Iterable[int],
        durations: Iterable[int],
        sort_mode: int,
        query: str,
        artist_filter_key: int = 0,
        use_artist_filter: bool = False,
    ) -> Optional[List[int]]:
        if self._lib is None or self._filter_sort_indices_with_query is None:
            return None
        blob = bytes(search_blob or b"")
        query_bytes = str(query or "").encode("utf-8", "ignore")
        if not blob or not query_bytes:
            return None

        offsets = [int(v) & 0xFFFFFFFF for v in (search_offsets or [])]
        lens = [int(v) & 0xFFFFFFFF for v in (search_lens or [])]
        keys = [int(v) & ((1 << 64) - 1) for v in (artist_keys or [])]
        n = len(keys)
        if n <= 0 or len(offsets) != n or len(lens) != n:
            return None

        title_vals = [int(v) & 0xFFFFFFFF for v in (title_rank or [])]
        artist_vals = [int(v) & 0xFFFFFFFF for v in (artist_rank or [])]
        album_vals = [int(v) & 0xFFFFFFFF for v in (album_rank or [])]
        dur_vals = [int(v) & 0xFFFFFFFF for v in (durations or [])]
        if len(title_vals) != n or len(artist_vals) != n or len(album_vals) != n or len(dur_vals) != n:
            return None

        blob_len = len(blob)
        blob_buf = (ctypes.c_ubyte * blob_len).from_buffer_copy(blob)
        query_len = len(query_bytes)
        query_buf = (ctypes.c_ubyte * query_len).from_buffer_copy(query_bytes)
        off_buf = (ctypes.c_uint32 * n)(*offsets)
        len_buf = (ctypes.c_uint32 * n)(*lens)
        keys_buf = (ctypes.c_uint64 * n)(*keys)
        title_buf = (ctypes.c_uint32 * n)(*title_vals)
        artist_buf = (ctypes.c_uint32 * n)(*artist_vals)
        album_buf = (ctypes.c_uint32 * n)(*album_vals)
        dur_buf = (ctypes.c_uint32 * n)(*dur_vals)
        out_buf = (ctypes.c_uint32 * n)()

        written = int(
            self._filter_sort_indices_with_query(
                blob_buf,
                ctypes.c_size_t(blob_len),
                off_buf,
                len_buf,
                keys_buf,
                title_buf,
                artist_buf,
                album_buf,
                dur_buf,
                ctypes.c_size_t(n),
                ctypes.c_uint32(int(sort_mode) & 0xFFFFFFFF),
                ctypes.c_uint64(int(artist_filter_key) & ((1 << 64) - 1)),
                ctypes.c_uint8(1 if use_artist_filter else 0),
                query_buf,
                ctypes.c_size_t(query_len),
                out_buf,
                ctypes.c_size_t(n),
            )
        )
        if written <= 0:
            return []
        return [int(out_buf[i]) for i in range(min(written, n))]

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

    def create_bars_renderer(self, width: int, height: int, num_bars: int):
        if self._lib is None or self._bars_renderer_new is None:
            return None
        ptr = self._bars_renderer_new(
            ctypes.c_size_t(max(1, int(width))),
            ctypes.c_size_t(max(1, int(height))),
            ctypes.c_size_t(max(1, int(num_bars))),
        )
        if not ptr:
            return None
        return RustBarsRenderer(self, ctypes.c_void_p(ptr), int(num_bars))


class RustBarsRenderer:
    def __init__(self, core: RustVizCore, ptr: ctypes.c_void_p, num_bars: int):
        self._core = core
        self._ptr = ptr
        self._num_bars = max(1, int(num_bars))
        self._levels_buf = (ctypes.c_float * self._num_bars)()
        self._colors_buf = (ctypes.c_float * (self._num_bars * 4))()
        self._frame_ptr = ctypes.c_void_p()
        self._frame_len = ctypes.c_size_t(0)
        self._frame_w = ctypes.c_size_t(0)
        self._frame_h = ctypes.c_size_t(0)
        self._frame_stride = ctypes.c_size_t(0)
        self._frame_seq = ctypes.c_uint64(0)
        self._frame_buf_obj = None
        self._last_seq = -1

    def close(self):
        if self._ptr:
            self._core._bars_renderer_free(self._ptr)
            self._ptr = None
            self._frame_buf_obj = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def set_colors(self, bar_colors_rgba: Iterable[Iterable[float]]) -> bool:
        if not self._ptr:
            return False
        colors = [tuple(c) for c in bar_colors_rgba]
        if len(colors) < self._num_bars:
            last = colors[-1] if colors else (0.0, 0.72, 1.0, 1.0)
            colors.extend([last] * (self._num_bars - len(colors)))
        elif len(colors) > self._num_bars:
            colors = colors[:self._num_bars]
        j = 0
        for c in colors:
            self._colors_buf[j] = float(c[0]); j += 1
            self._colors_buf[j] = float(c[1]); j += 1
            self._colors_buf[j] = float(c[2]); j += 1
            self._colors_buf[j] = float(c[3]); j += 1
        rc = int(
            self._core._bars_renderer_set_colors(
                self._ptr,
                self._colors_buf,
                ctypes.c_size_t(self._num_bars * 4),
            )
        )
        return rc == 0

    def render(self, levels: Iterable[float], gain: float, bar_w_px: int, spacing_px: int) -> bool:
        if not self._ptr:
            return False
        vals = [float(v) for v in levels]
        if len(vals) < self._num_bars:
            vals.extend([0.0] * (self._num_bars - len(vals)))
        elif len(vals) > self._num_bars:
            vals = vals[:self._num_bars]
        for i, v in enumerate(vals):
            self._levels_buf[i] = v
        rc = int(
            self._core._bars_renderer_render(
                self._ptr,
                self._levels_buf,
                ctypes.c_size_t(self._num_bars),
                ctypes.c_float(float(gain)),
                ctypes.c_size_t(max(1, int(bar_w_px))),
                ctypes.c_size_t(max(0, int(spacing_px))),
            )
        )
        return rc == 0

    def get_frame(self):
        if not self._ptr:
            return None
        rc = int(
            self._core._bars_renderer_get_frame(
                self._ptr,
                ctypes.byref(self._frame_ptr),
                ctypes.byref(self._frame_len),
                ctypes.byref(self._frame_w),
                ctypes.byref(self._frame_h),
                ctypes.byref(self._frame_stride),
                ctypes.byref(self._frame_seq),
            )
        )
        if rc != 0 or not self._frame_ptr.value or self._frame_len.value <= 0:
            return None
        if int(self._frame_seq.value) != self._last_seq:
            self._last_seq = int(self._frame_seq.value)
            arr_t = ctypes.c_ubyte * int(self._frame_len.value)
            self._frame_buf_obj = arr_t.from_address(int(self._frame_ptr.value))
        return (
            self._frame_buf_obj,
            int(self._frame_w.value),
            int(self._frame_h.value),
            int(self._frame_stride.value),
            int(self._frame_seq.value),
        )


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


class RustVizStateEngine:
    def __init__(self, core: RustVizCore, ptr: ctypes.c_void_p, num_bars: int):
        self._core = core
        self._ptr = ptr
        self._num_bars = max(1, int(num_bars))
        self._target_buf = (ctypes.c_float * self._num_bars)()
        self._bass_buf = ctypes.c_float(0.0)

    def close(self):
        if self._ptr:
            self._core._viz_state_free(self._ptr)
            self._ptr = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def reset(self):
        if self._ptr:
            self._core._viz_state_reset(self._ptr)

    def set_params(
        self,
        smooth: float,
        trail_decay: float,
        peak_hold_frames: int,
        peak_fall: float,
        bass_smooth: float = 0.22,
    ) -> bool:
        if not self._ptr:
            return False
        rc = int(
            self._core._viz_state_set_params(
                self._ptr,
                ctypes.c_float(float(smooth)),
                ctypes.c_float(float(trail_decay)),
                ctypes.c_size_t(max(0, int(peak_hold_frames))),
                ctypes.c_float(float(peak_fall)),
                ctypes.c_float(float(bass_smooth)),
            )
        )
        return rc == 0

    def set_target(self, levels: Iterable[float]) -> int:
        if not self._ptr:
            return 0
        vals = [float(v) for v in levels]
        if len(vals) < self._num_bars:
            vals.extend([0.0] * (self._num_bars - len(vals)))
        elif len(vals) > self._num_bars:
            vals = vals[:self._num_bars]
        for i, v in enumerate(vals):
            self._target_buf[i] = v
        return int(self._core._viz_state_set_target(self._ptr, self._target_buf, self._num_bars))


    def tick_copy(
        self,
        cur_out,
        trail_out,
        peak_out,
    ):
        if not self._ptr:
            return 0, 0.0
        out_len = min(self._num_bars, len(cur_out), len(trail_out), len(peak_out))
        if out_len <= 0:
            return 0, 0.0
        written = int(
            self._core._viz_state_tick_copy(
                self._ptr,
                cur_out,
                trail_out,
                peak_out,
                ctypes.c_size_t(out_len),
                ctypes.byref(self._bass_buf),
            )
        )
        return written, float(self._bass_buf.value)
