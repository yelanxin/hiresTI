import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from viz.visualizer import (
    _build_log_spectrum_bins,
    _display_gain_multiplier,
    _linear_display_frequency_range,
    _log_display_eq_gain,
    _log_display_frequency_at_fraction,
    _log_display_frequency_to_fraction,
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


def test_log_frequency_mapping_keeps_dense_low_end_bars_contrasty():
    raw = [0.0] * 512
    raw[3] = 1.0
    mapped = _build_log_spectrum_bins(raw, 256)
    peak = max(mapped)
    assert peak > 0.0
    assert mapped[0] < (peak * 0.30)


def test_log_frequency_mapping_uses_rust_helper_for_high_bar_counts():
    class _RustCore:
        available = True

        def __init__(self):
            self.calls = []

        def build_log_bins(self, values, out_count):
            self.calls.append((list(values), int(out_count)))
            return [0.25] * int(out_count)

    raw = [float(-60 + i) for i in range(512)]
    rust_core = _RustCore()

    mapped = _build_log_spectrum_bins(
        _normalize_spectrum_magnitudes(raw),
        512,
        rust_core=rust_core,
    )

    assert len(mapped) == 512
    assert mapped[:3] == [0.25, 0.25, 0.25]
    assert rust_core.calls and rust_core.calls[0][1] == 512


def test_log_frequency_range_covers_extended_audible_window():
    min_f, max_f = _log_display_frequency_range(512)
    assert min_f == 0.0
    assert max_f == 16000.0


def test_log_frequency_scale_honors_requested_anchor_points():
    assert abs(_log_display_frequency_to_fraction(200.0, 512) - 0.15) < 0.01
    assert abs(_log_display_frequency_to_fraction(500.0, 512) - 0.32) < 0.01
    assert abs(_log_display_frequency_to_fraction(1000.0, 512) - 0.50) < 0.01
    assert abs(_log_display_frequency_to_fraction(4000.0, 512) - 0.70) < 0.01
    assert abs(_log_display_frequency_to_fraction(8000.0, 512) - 0.87) < 0.01
    assert abs(_log_display_frequency_to_fraction(12000.0, 512) - 0.95) < 0.01


def test_log_frequency_scale_round_trips_hybrid_positions():
    for freq in (0.0, 200.0, 500.0, 1000.0, 4000.0, 8000.0, 12000.0, 16000.0):
        pos = _log_display_frequency_to_fraction(freq, 512)
        rebuilt = _log_display_frequency_at_fraction(pos, 512)
        assert abs(rebuilt - freq) < max(1.0, freq * 0.01)


def test_log_frequency_eq_gain_honors_requested_anchors():
    assert abs(_log_display_eq_gain(20.0) - 0.50) < 1e-6
    assert abs(_log_display_eq_gain(100.0) - 0.70) < 1e-6
    assert abs(_log_display_eq_gain(200.0) - 1.00) < 1e-6
    assert abs(_log_display_eq_gain(1000.0) - 1.00) < 1e-6
    assert abs(_log_display_eq_gain(4000.0) - 1.20) < 1e-6
    assert abs(_log_display_eq_gain(8000.0) - 1.50) < 1e-6


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
