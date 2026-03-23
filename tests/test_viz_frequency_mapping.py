import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from viz.visualizer import (
    _build_log_spectrum_bins,
    _display_gain_multiplier,
    _linear_display_frequency_range,
    _log_display_frequency_range,
    _normalize_spectrum_magnitudes,
    _resample_linear_values,
)


def test_log_frequency_mapping_splits_low_bins_with_interpolation():
    # Monotonic input makes it easy to spot duplicated low-end buckets.
    raw = [float(-60 + i) for i in range(96)]
    mapped = _build_log_spectrum_bins(_normalize_spectrum_magnitudes(raw), 32)
    assert len(mapped) == 32
    assert mapped[0] < mapped[1] < mapped[2]


def test_log_frequency_mapping_handles_empty_input():
    assert _build_log_spectrum_bins([], 8) == [0.0] * 8


def test_log_frequency_range_covers_extended_audible_window():
    min_f, max_f = _log_display_frequency_range(512)
    assert min_f == 100.0
    assert max_f == 16000.0


def test_linear_frequency_range_starts_from_zero():
    min_f, max_f = _linear_display_frequency_range(96)
    assert min_f == 0.0
    assert max_f > 0.0


def test_linear_display_gain_multiplier_is_higher_than_log():
    assert _display_gain_multiplier("Linear") >= 1.0
    assert _display_gain_multiplier("Log") == 1.0


def test_linear_resample_mean_averages_bins():
    out = _resample_linear_values([0.0, 0.0, 1.0, 0.0], 1)
    assert len(out) == 1
    assert out[0] == 0.25


def test_linear_resample_peak_preserves_sparse_tones():
    # A single active bin among silent neighbours should not be diluted.
    out = _resample_linear_values([0.0, 0.0, 1.0, 0.0], 1, use_peak=True)
    assert len(out) == 1
    assert out[0] == 1.0
