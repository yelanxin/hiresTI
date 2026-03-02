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


def test_pipewire_keeps_strict_depth_match_requirement():
    win = _make_window("PipeWire", exclusive=False)

    format_match = win._compute_format_match("PipeWire", "44.1kHz", "16-bit", "44.1kHz", "32-bit")
    verdict_ok, _style, reasons = win._compute_bitperfect_verdict(
        "active", "44.1kHz", "16-bit", "44.1kHz", "32-bit"
    )

    assert format_match is False
    assert verdict_ok is False
    assert "Rate/depth mismatch" in reasons
