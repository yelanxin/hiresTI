import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")
pytest.importorskip("cairo")

from viz import visualizer as mod


class _RecordingContext:
    """Minimal cairo-like context that records tick x positions."""

    def __init__(self):
        self.tick_xs = []
        self._pending_x = None

    def select_font_face(self, *args):
        pass

    def set_font_size(self, *args):
        pass

    def set_source_rgba(self, *args):
        pass

    def set_line_width(self, *args):
        pass

    def move_to(self, x, _y):
        self._pending_x = x

    def line_to(self, x, _y):
        pass

    def stroke(self):
        self.tick_xs.append(self._pending_x)

    def show_text(self, _label):
        self._pending_x = None

    def text_extents(self, label):
        class _Ext:
            width = 6.0 * len(label)

        return _Ext()


def test_full_width_axis_spans_whole_widget():
    cr = _RecordingContext()
    mod._draw_freq_axis_cairo(cr, 1000, 18, "Linear", 256)

    assert len(cr.tick_xs) == 9
    assert cr.tick_xs[0] == 0.0
    assert cr.tick_xs[-1] == 1000.0


def test_split_stereo_axis_repeats_per_half():
    width = 1000
    cr = _RecordingContext()
    regions = mod._split_stereo_band_regions(width)
    mod._draw_freq_axis_cairo(cr, width, 18, "Linear", 256, regions=regions)

    (l0, l1), (r0, r1) = regions
    left = [x for x in cr.tick_xs if x <= l1]
    right = [x for x in cr.tick_xs if x >= r0]
    # Every tick falls inside one of the two band regions; none in the gap.
    assert len(left) + len(right) == len(cr.tick_xs)
    # Both halves carry their own full 0..max sweep.
    assert left[0] == l0 and left[-1] == l1
    assert right[0] == r0 and right[-1] == r1
    # Half-width panes below the crowding threshold thin to every other tick.
    assert len(left) == len(right) == 5


def test_split_stereo_axis_keeps_all_ticks_when_wide():
    width = 2000
    cr = _RecordingContext()
    regions = mod._split_stereo_band_regions(width)
    mod._draw_freq_axis_cairo(cr, width, 18, "Linear", 256, regions=regions)

    assert len(cr.tick_xs) == 18


def test_linear_temporal_smoothing_reduces_jitter():
    state = {}
    first = mod._smooth_linear_bins_temporal(state, "mono", [0.0] * 8)
    assert first == [0.0] * 8
    # A full-scale jump only moves the displayed bin by alpha.
    second = mod._smooth_linear_bins_temporal(state, "mono", [1.0] * 8)
    assert all(abs(v - mod._LINEAR_TEMPORAL_ALPHA) < 1e-9 for v in second)
    # Converges toward the target across frames.
    third = mod._smooth_linear_bins_temporal(state, "mono", [1.0] * 8)
    assert all(third[i] > second[i] for i in range(8))


def test_linear_temporal_smoothing_is_per_channel():
    state = {}
    mod._smooth_linear_bins_temporal(state, "left", [1.0] * 4)
    right = mod._smooth_linear_bins_temporal(state, "right", [0.5] * 4)
    # First frame for "right" must not be influenced by "left" history.
    assert right == [0.5] * 4


def test_linear_temporal_smoothing_resets_on_length_change():
    state = {}
    mod._smooth_linear_bins_temporal(state, "mono", [1.0] * 4)
    out = mod._smooth_linear_bins_temporal(state, "mono", [0.2] * 8)
    # Bar-count change: no blend against mismatched history.
    assert out == [0.2] * 8
