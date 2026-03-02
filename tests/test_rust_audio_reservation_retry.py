import logging
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from _rust import audio as rust_audio


class _FakeReservation:
    def __init__(self, card_num):
        self.card_num = int(card_num)
        self.acquired = False

    def acquire(self):
        self.acquired = True
        return True


class _ImmediateThread:
    def __init__(self, target=None, daemon=None):
        self._target = target
        self.daemon = bool(daemon)

    def start(self):
        if self._target is not None:
            self._target()


def test_alsa_reservation_retry_idle_add_runs_once(monkeypatch):
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._alsa_reservation = None

    set_output_calls = []

    def _set_output(driver, device_id=None):
        set_output_calls.append((driver, device_id))
        return True

    adapter.set_output = _set_output

    monkeypatch.setitem(
        sys.modules,
        "services.alsa_reserve",
        SimpleNamespace(AlsaDeviceReservation=_FakeReservation),
    )
    monkeypatch.setattr(rust_audio.threading, "Thread", _ImmediateThread)

    idle_iterations = []

    def _idle_add(func, *args):
        count = 0
        while True:
            count += 1
            keep = bool(func(*args))
            if not keep:
                break
            if count > 5:
                raise AssertionError("idle callback kept rescheduling")
        idle_iterations.append(count)
        return 1

    monkeypatch.setattr(rust_audio.GLib, "idle_add", _idle_add)

    adapter._start_alsa_reservation_async("ALSA", "hw:2,0", 2)

    assert set_output_calls == [("ALSA", "hw:2,0")]
    assert idle_iterations == [1]
    assert adapter._alsa_reservation is not None
    assert adapter._alsa_reservation.acquired is True


class _FakeRustCore:
    def __init__(self, rc, last_error=""):
        self._rc = int(rc)
        self._last_error = str(last_error)
        self.calls = []

    def set_output(self, driver, device_id, buffer_us=0, latency_us=0, exclusive=False):
        self.calls.append(
            {
                "driver": driver,
                "device_id": device_id,
                "buffer_us": int(buffer_us),
                "latency_us": int(latency_us),
                "exclusive": bool(exclusive),
            }
        )
        return self._rc

    def get_last_error(self):
        return self._last_error


def _make_switch_adapter(rc, last_error=""):
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRustCore(rc, last_error=last_error)
    adapter.requested_driver = None
    adapter.requested_device_id = None
    adapter.current_driver = "Auto (Default)"
    adapter.current_device_id = None
    adapter.output_state = "idle"
    adapter.output_error = None
    adapter.alsa_buffer_time = 20000
    adapter.alsa_latency_time = 2000
    adapter.exclusive_lock_mode = True
    adapter._alsa_reservation = None
    return adapter


def test_apply_output_switch_alsa_exclusive_success_skips_reservation():
    adapter = _make_switch_adapter(0)
    reservation_calls = []
    release_calls = []
    adapter._start_alsa_reservation_async = (
        lambda driver, device_id, card_num: reservation_calls.append((driver, device_id, card_num))
    )
    adapter._release_alsa_reservation = lambda: release_calls.append(True)

    ok = rust_audio.RustAudioPlayerAdapter._apply_output_switch_once(adapter, "ALSA", "hw:2,0")

    assert ok is True
    assert adapter.output_state == "active"
    assert adapter.output_error is None
    assert reservation_calls == []
    assert release_calls == []
    assert adapter._rust.calls == [
        {
            "driver": "ALSA",
            "device_id": "hw:2,0",
            "buffer_us": 20000,
            "latency_us": 2000,
            "exclusive": True,
        }
    ]


def test_apply_output_switch_alsa_exclusive_failure_triggers_reservation_retry():
    adapter = _make_switch_adapter(-4, last_error="Device or resource busy")
    reservation_calls = []
    release_calls = []
    adapter._start_alsa_reservation_async = (
        lambda driver, device_id, card_num: reservation_calls.append((driver, device_id, card_num))
    )
    adapter._release_alsa_reservation = lambda: release_calls.append(True)

    ok = rust_audio.RustAudioPlayerAdapter._apply_output_switch_once(adapter, "ALSA", "hw:2,0")

    assert ok is True
    assert adapter.output_state == "switching"
    assert adapter.output_error is None
    assert reservation_calls == [("ALSA", "hw:2,0", 2)]
    assert release_calls == []
    assert adapter._rust.calls == [
        {
            "driver": "ALSA",
            "device_id": "hw:2,0",
            "buffer_us": 20000,
            "latency_us": 2000,
            "exclusive": True,
        }
    ]


def test_read_active_alsa_hw_details_prefers_running_substream(tmp_path):
    proc_root = tmp_path / "asound"
    sub0 = proc_root / "card2" / "pcm0p" / "sub0"
    sub1 = proc_root / "card2" / "pcm0p" / "sub1"
    sub0.mkdir(parents=True)
    sub1.mkdir(parents=True)
    (sub0 / "status").write_text("state: CLOSED\n", encoding="utf-8")
    (sub0 / "hw_params").write_text("format: S16_LE\nrate: 44100\n", encoding="utf-8")
    (sub1 / "status").write_text("state: RUNNING\n", encoding="utf-8")
    (sub1 / "hw_params").write_text(
        "access: RW_INTERLEAVED\nformat: S32_LE\nrate: 44100\nperiod_size: 5513\nbuffer_size: 22050\n",
        encoding="utf-8",
    )

    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter.current_device_id = "hw:2,0"
    adapter._alsa_proc_root = proc_root

    details = rust_audio.RustAudioPlayerAdapter._read_active_alsa_hw_details(adapter)

    assert details == {
        "access": "RW_INTERLEAVED",
        "format": "S32_LE",
        "rate": "44100",
        "period_size": "5513",
        "buffer_size": "22050",
    }


def test_container_adapter_runtime_log_includes_hw_params_and_dedupes(tmp_path, caplog):
    proc_root = tmp_path / "asound"
    sub0 = proc_root / "card2" / "pcm0p" / "sub0"
    sub0.mkdir(parents=True)
    (sub0 / "status").write_text("state: RUNNING\n", encoding="utf-8")
    (sub0 / "hw_params").write_text(
        "access: RW_INTERLEAVED\nformat: S32_LE\nrate: 44100\nperiod_size: 5513\nbuffer_size: 22050\n",
        encoding="utf-8",
    )

    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter.current_driver = "ALSA"
    adapter.current_device_id = "hw:2,0"
    adapter.exclusive_lock_mode = True
    adapter.stream_info = {"source_depth": 16}
    adapter._alsa_proc_root = proc_root
    adapter._alsa_container_adapter_active = False
    adapter._alsa_container_adapter_format = ""
    adapter._alsa_container_adapter_diag_sig = ""

    with caplog.at_level(logging.INFO, logger=rust_audio.logger.name):
        rust_audio.RustAudioPlayerAdapter._on_rust_event(
            adapter,
            rust_audio._RustAudioCore.EVENT_STATE,
            "alsa-exclusive container-adapter format=S32LE device=hw:2,0",
        )
        rust_audio.RustAudioPlayerAdapter._maybe_log_alsa_container_adapter_runtime(adapter)

    diag_msgs = [
        record.message
        for record in caplog.records
        if "ALSA exclusive container adapter runtime:" in record.message
    ]

    assert adapter._alsa_container_adapter_active is True
    assert adapter._alsa_container_adapter_format == "S32LE"
    assert len(diag_msgs) == 1
    assert "device=hw:2,0" in diag_msgs[0]
    assert "adapter_format=S32LE" in diag_msgs[0]
    assert "source_depth=16" in diag_msgs[0]
    assert "hw_format=S32_LE" in diag_msgs[0]
    assert "hw_rate=44100" in diag_msgs[0]
