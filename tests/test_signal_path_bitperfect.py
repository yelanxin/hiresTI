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


def test_alsa_nonexclusive_reports_format_match_when_rate_and_depth_are_equal():
    win = _make_window("ALSA", exclusive=False, bit_perfect=False)

    format_match = win._compute_format_match("ALSA", "44.1kHz", "16-bit", "44.1kHz", "16-bit")
    verdict_ok, _style, reasons = win._compute_bitperfect_verdict(
        "active", "44.1kHz", "16-bit", "44.1kHz", "16-bit"
    )

    assert format_match is True
    assert verdict_ok is False
    assert "Bit-Perfect mode disabled" in reasons


def test_alsa_nonexclusive_allows_output_depth_widening_for_format_match():
    win = _make_window("ALSA", exclusive=False, bit_perfect=False)

    format_match = win._compute_format_match("ALSA", "44.1kHz", "24-bit", "44.1kHz", "32-bit")

    assert format_match is True


def test_alsa_nonexclusive_allows_bitperfect_verdict_when_rate_and_depth_match():
    win = _make_window("ALSA", exclusive=False, bit_perfect=True)

    verdict_ok, _style, reasons = win._compute_bitperfect_verdict(
        "active", "44.1kHz", "24-bit", "44.1kHz", "32-bit"
    )

    assert verdict_ok is True
    assert reasons == []


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
    assert "opens the selected hw:* device directly" in text


def test_alsa_verdict_help_mentions_direct_hw_without_exclusive_requirement():
    win = _make_window("ALSA", exclusive=True)

    text = win._build_bitperfect_verdict_help_text()

    assert "opens the selected hw:* device directly" in text
    assert "without requiring the Exclusive toggle" in text


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


def test_dsp_snapshot_reports_master_active_state():
    win = AudioSignalPathWindow.__new__(AudioSignalPathWindow)
    win.player = SimpleNamespace(
        dsp_enabled=True,
        bit_perfect_mode=False,
    )
    win.app = SimpleNamespace(settings={})

    snapshot = win._build_dsp_snapshot()

    assert snapshot["master_active"] is True
    assert snapshot["master_state"] == "Active"


def test_summary_update_includes_dsp_rows_when_processing_is_active():
    win = _make_window("ALSA", exclusive=True, bit_perfect=False)
    win.player.dsp_enabled = True
    win.app = SimpleNamespace(settings={"driver": "ALSA"})
    win.bitperfect_verdict_help_pop = SimpleNamespace(get_visible=lambda: False)
    win._summary_last_signature = None

    render_calls = []
    win._refresh_bitperfect_help_text = lambda: None
    win._render_summary_rows = lambda rows: render_calls.append(tuple(rows))
    win._get_pipewire_clock_state = lambda: (0, [])
    win._read_runtime_snapshot_safe = lambda: {
        "source": {"rate": 44100, "depth": 16},
        "output": {"hardware_rate": 44100, "hardware_depth": 16},
    }

    win._update_summary()

    rows = render_calls[0]
    assert ("DSP Master", "Active", "ok") in rows


def test_summary_update_uses_displayed_output_format_for_rate_match_and_reasons():
    win = _make_window("ALSA", exclusive=False, bit_perfect=False)
    win.player.dsp_enabled = False
    win.player.stream_info = {"output_rate": 44100, "output_depth": 16}
    win.app = SimpleNamespace(settings={"driver": "ALSA"})
    win.bitperfect_verdict_help_pop = SimpleNamespace(get_visible=lambda: False)
    win._summary_last_signature = None

    render_calls = []
    win._refresh_bitperfect_help_text = lambda: None
    win._render_summary_rows = lambda rows: render_calls.append(tuple(rows))
    win._get_pipewire_clock_state = lambda: (0, [])
    win._read_runtime_snapshot_safe = lambda: {
        "source": {"rate": 44100, "depth": 16},
        "output": {},
    }

    win._update_summary()

    rows = render_calls[0]
    assert ("Rate Match", "Yes", "ok") in rows
    assert not any(key == "Reasons" and "Sample-rate mismatch" in value for key, value, _style in rows)


def test_diagnostics_text_includes_dsp_chain_details():
    win = _make_window("ALSA", exclusive=True, bit_perfect=False)
    win.player.dsp_enabled = True
    win.player.stream_info = {"output_depth": 16}
    win.app = SimpleNamespace(
        settings={"driver": "ALSA"},
        current_device_name="USB DAC",
    )
    win._read_runtime_snapshot_safe = lambda: {
        "source": {"codec": "FLAC", "bitrate": 1411200, "rate": 44100, "depth": 16},
        "output": {"hardware_rate": 44100, "hardware_depth": 16},
    }
    win._get_pipewire_clock_state = lambda: (0, "")

    text = win._build_diagnostics_text()

    assert "DSP Master: Active" in text
    assert "DSP Order:" not in text
    assert "DSP Chain:" not in text
    assert "Tube:" not in text
    assert "Source Format: 44.1kHz / 16-bit" in text
    assert "Output Format: 44.1kHz / 16-bit" in text


def test_display_output_rate_prefers_resampler_target_when_active():
    win = _make_window("ALSA", exclusive=True, bit_perfect=False)
    win.player.dsp_enabled = True
    win.player.resampler_enabled = True
    win.player.resampler_target_rate = 96000
    win.app = SimpleNamespace(settings={})

    assert win._display_output_rate("44.1kHz") == "96kHz"


def test_display_output_rate_keeps_runtime_rate_when_resampler_inactive():
    win = _make_window("ALSA", exclusive=True, bit_perfect=False)
    win.player.dsp_enabled = True
    win.player.resampler_enabled = False
    win.player.resampler_target_rate = 96000
    win.app = SimpleNamespace(settings={})

    assert win._display_output_rate("44.1kHz") == "44.1kHz"


def test_display_output_rate_falls_back_to_stream_output_rate_when_runtime_is_server_controlled():
    win = _make_window("ALSA", exclusive=False, bit_perfect=False)
    win.player.dsp_enabled = True
    win.player.resampler_enabled = False
    win.player.resampler_target_rate = 0
    win.player.stream_info = {"output_rate": 44100}
    win.app = SimpleNamespace(settings={})

    assert win._display_output_rate("Server Controlled") == "44.1kHz"


def test_display_output_depth_falls_back_to_stream_output_depth():
    win = _make_window("ALSA", exclusive=False, bit_perfect=False)
    win.player.stream_info = {"output_depth": 32}
    win.app = SimpleNamespace(settings={})

    assert win._display_output_depth("Unknown") == "32-bit"


def test_format_target_output_truncates_long_device_name():
    win = _make_window("PipeWire", exclusive=False, bit_perfect=False)

    text = win._format_target_output(
        "PipeWire",
        "alsa_output.usb-GuangZhou_FiiO_Electronics_Co._Ltd_FiiO_USB_DAC-E10-00.analog-stereo",
        max_chars=36,
    )

    assert "…" in text
    assert len(text) <= 36


def test_display_output_path_reports_shared_driver_path():
    win = _make_window("PipeWire", exclusive=False, bit_perfect=False)

    assert win._display_output_path("PipeWire", False) == "PipeWire Shared Graph"
    assert win._display_output_path("PulseAudio", False) == "PulseAudio Shared Server"
    assert win._display_output_path("ALSA（auto）", False, "hw:2,0") == "Direct ALSA Hardware"
    assert win._display_output_path("ALSA（auto）", False, "default") == "ALSA Shared Mixer"
