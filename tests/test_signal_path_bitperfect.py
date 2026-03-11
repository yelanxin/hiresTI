import logging
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.signal_path import AudioSignalPathWindow


def _make_window(driver="ALSA", *, active=True, bit_perfect=True, exclusive=True):
    win = AudioSignalPathWindow.__new__(AudioSignalPathWindow)
    win.player = SimpleNamespace(
        output_state="active" if active else "idle",
        bit_perfect_mode=bool(bit_perfect),
        exclusive_lock_mode=bool(exclusive),
        current_driver=driver,
        _pipewire_rate_blocked=False,
    )
    win.app = SimpleNamespace(settings={"driver": driver})
    return win


def test_alsa_exclusive_allows_lossless_container_depth_widening():
    win = _make_window("ALSA", exclusive=True)

    format_match = win._compute_format_match("ALSA", "44.1kHz", "16-bit", "44.1kHz", "32-bit")
    verdict_ok, _style, reasons = win._compute_bitperfect_verdict(
        "active", "44.1kHz", "16-bit", "44.1kHz", "32-bit"
    )

    assert format_match is True
    assert verdict_ok is True
    assert reasons == []


def test_alsa_exclusive_rejects_narrower_output_depth():
    win = _make_window("ALSA", exclusive=True)

    format_match = win._compute_format_match("ALSA", "44.1kHz", "24-bit", "44.1kHz", "16-bit")
    verdict_ok, _style, reasons = win._compute_bitperfect_verdict(
        "active", "44.1kHz", "24-bit", "44.1kHz", "16-bit"
    )

    assert format_match is False
    assert verdict_ok is False
    assert "Output bit depth narrower than source" in reasons


def test_pipewire_allows_lossless_container_depth_widening():
    win = _make_window("PipeWire", exclusive=False)

    format_match = win._compute_format_match("PipeWire", "44.1kHz", "16-bit", "44.1kHz", "32-bit")
    verdict_ok, _style, reasons = win._compute_bitperfect_verdict(
        "active", "44.1kHz", "16-bit", "44.1kHz", "32-bit"
    )

    assert format_match is True
    assert verdict_ok is True
    assert reasons == []


def test_pipewire_rejects_narrower_output_depth():
    win = _make_window("PipeWire", exclusive=False)

    format_match = win._compute_format_match("PipeWire", "44.1kHz", "24-bit", "44.1kHz", "16-bit")
    verdict_ok, _style, reasons = win._compute_bitperfect_verdict(
        "active", "44.1kHz", "24-bit", "44.1kHz", "16-bit"
    )

    assert format_match is False
    assert verdict_ok is False
    assert "Output bit depth narrower than source" in reasons


def test_pipewire_verdict_help_mentions_system_mixer_and_volume():
    win = _make_window("PipeWire", exclusive=False)

    text = win._build_bitperfect_verdict_help_text()

    assert "shared PipeWire output still goes through the system mixer" in text
    assert "System volume changes" in text
    assert "ALSA（auto）/ALSA（mmap） + Exclusive" in text


def test_alsa_verdict_help_mentions_exclusive_requirement():
    win = _make_window("ALSA", exclusive=True)

    text = win._build_bitperfect_verdict_help_text()

    assert "ALSA also requires Exclusive mode" in text


def test_pipewire_latency_debug_log_dedupes_stable_state(caplog):
    win = _make_window("PipeWire", exclusive=False)
    snaps = [
        {"pipewire": {"latency_ms": 21.333333333333332, "force_rate": 44100, "allowed_rates_raw": "[ 44100 48000 ]"}},
        {"pipewire": {"latency_ms": 21.333333333333332, "force_rate": 44100, "allowed_rates_raw": "[ 44100 48000 ]"}},
        {"pipewire": {"latency_ms": 42.0, "force_rate": 48000, "allowed_rates_raw": "[ 44100 48000 ]"}},
    ]
    win.player._read_runtime_snapshot = lambda: snaps.pop(0)

    with caplog.at_level(logging.DEBUG, logger="signal_path"):
        first = win._get_pipewire_runtime_latency_ms()
        second = win._get_pipewire_runtime_latency_ms()
        third = win._get_pipewire_runtime_latency_ms()

    diag_msgs = [
        record
        for record in caplog.records
        if "SignalPath latency source:" in record.message
    ]

    assert round(first, 3) == 21.333
    assert round(second, 3) == 21.333
    assert third == 42.0
    assert len(diag_msgs) == 2
    assert all(record.levelno == logging.DEBUG for record in diag_msgs)


def test_summary_update_skips_rebuild_when_rows_are_unchanged():
    win = _make_window("ALSA", exclusive=True)
    win.bitperfect_verdict_help_pop = SimpleNamespace(get_visible=lambda: False)
    win._summary_last_signature = None

    render_calls = []
    refresh_calls = []

    win._refresh_bitperfect_help_text = lambda: refresh_calls.append(True)
    win._render_summary_rows = lambda rows: render_calls.append(tuple(rows))
    win._get_pipewire_clock_state = lambda: (0, [])
    win._read_runtime_snapshot_safe = lambda: {
        "source": {"rate": 44100, "depth": 16},
        "output": {"hardware_rate": 44100, "hardware_depth": 16},
    }
    win._compute_format_match = lambda *args: True
    win._compute_bitperfect_verdict = lambda *args: (True, "ok", [])

    win._update_summary()
    win._update_summary()

    assert len(render_calls) == 1
    assert len(refresh_calls) == 2
