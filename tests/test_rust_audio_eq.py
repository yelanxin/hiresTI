import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from _rust import audio as rust_audio


class _FakeRust:
    def __init__(
        self,
        band_rc=0,
        reset_rc=0,
        dsp_rc=0,
        peq_rc=0,
        convolver_rc=0,
        load_rc=0,
        clear_rc=0,
        limiter_rc=0,
        limiter_threshold_rc=0,
        limiter_ratio_rc=0,
        tube_rc=0,
        tube_drive_rc=0,
        tube_bias_rc=0,
        tube_sag_rc=0,
        tube_air_rc=0,
        widener_rc=0,
        widener_width_rc=0,
        widener_bass_freq_rc=0,
        widener_bass_amount_rc=0,
        lv2_restore_rc=0,
        lv2_clear_slots_for_restore_rc=0,
        lv2_restore_slot_deferred_rc=0,
        lv2_finish_restore_slots_rc=0,
        lv2_set_slot_enabled_rc=0,
        lv2_set_port_value_rc=0,
    ):
        self.band_rc = band_rc
        self.reset_rc = reset_rc
        self.dsp_rc = dsp_rc
        self.peq_rc = peq_rc
        self.convolver_rc = convolver_rc
        self.load_rc = load_rc
        self.clear_rc = clear_rc
        self.limiter_rc = limiter_rc
        self.limiter_threshold_rc = limiter_threshold_rc
        self.limiter_ratio_rc = limiter_ratio_rc
        self.tube_rc = tube_rc
        self.tube_drive_rc = tube_drive_rc
        self.tube_bias_rc = tube_bias_rc
        self.tube_sag_rc = tube_sag_rc
        self.tube_air_rc = tube_air_rc
        self.widener_rc = widener_rc
        self.widener_width_rc = widener_width_rc
        self.widener_bass_freq_rc = widener_bass_freq_rc
        self.widener_bass_amount_rc = widener_bass_amount_rc
        self.lv2_restore_rc = lv2_restore_rc
        self.lv2_clear_slots_for_restore_rc = lv2_clear_slots_for_restore_rc
        self.lv2_restore_slot_deferred_rc = lv2_restore_slot_deferred_rc
        self.lv2_finish_restore_slots_rc = lv2_finish_restore_slots_rc
        self.lv2_set_slot_enabled_rc = lv2_set_slot_enabled_rc
        self.lv2_set_port_value_rc = lv2_set_port_value_rc
        self.calls = []

    def set_peq_band_gain(self, band_index, gain_db):
        self.calls.append(("band", band_index, gain_db))
        return self.band_rc

    def reset_peq(self):
        self.calls.append(("reset",))
        return self.reset_rc

    def set_dsp_enabled(self, enabled):
        self.calls.append(("dsp", enabled))
        return self.dsp_rc

    def set_volume(self, vol):
        self.calls.append(("volume", float(vol)))
        return 0

    def set_peq_enabled(self, enabled):
        self.calls.append(("peq", enabled))
        return self.peq_rc

    def set_convolver_enabled(self, enabled):
        self.calls.append(("convolver", enabled))
        return self.convolver_rc

    def load_convolver_ir(self, path):
        self.calls.append(("load_convolver", path))
        return self.load_rc

    def clear_convolver_ir(self):
        self.calls.append(("clear_convolver",))
        return self.clear_rc

    def set_limiter_enabled(self, enabled):
        self.calls.append(("limiter", enabled))
        return self.limiter_rc

    def set_limiter_threshold(self, threshold):
        self.calls.append(("limiter_threshold", threshold))
        return self.limiter_threshold_rc

    def set_limiter_ratio(self, ratio):
        self.calls.append(("limiter_ratio", ratio))
        return self.limiter_ratio_rc

    def set_tube_enabled(self, enabled):
        self.calls.append(("tube", enabled))
        return self.tube_rc

    def set_tube_drive(self, drive):
        self.calls.append(("tube_drive", drive))
        return self.tube_drive_rc

    def set_tube_bias(self, bias):
        self.calls.append(("tube_bias", bias))
        return self.tube_bias_rc

    def set_tube_sag(self, sag):
        self.calls.append(("tube_sag", sag))
        return self.tube_sag_rc

    def set_tube_air(self, air):
        self.calls.append(("tube_air", air))
        return self.tube_air_rc

    def set_widener_enabled(self, enabled):
        self.calls.append(("widener", enabled))
        return self.widener_rc

    def set_widener_width(self, width):
        self.calls.append(("widener_width", width))
        return self.widener_width_rc

    def set_widener_bass_mono_freq(self, freq):
        self.calls.append(("widener_bass_freq", freq))
        return self.widener_bass_freq_rc

    def set_widener_bass_mono_amount(self, amount):
        self.calls.append(("widener_bass_amount", amount))
        return self.widener_bass_amount_rc

    def lv2_restore_slot(self, slot_id, uri):
        self.calls.append(("lv2_restore_slot", slot_id, uri))
        return self.lv2_restore_rc

    def lv2_set_slot_enabled(self, slot_id, enabled):
        self.calls.append(("lv2_set_slot_enabled", slot_id, enabled))
        return self.lv2_set_slot_enabled_rc

    def lv2_set_port_value(self, slot_id, symbol, value):
        self.calls.append(("lv2_set_port_value", slot_id, symbol, value))
        return self.lv2_set_port_value_rc

    def lv2_clear_slots_for_restore(self):
        self.calls.append(("lv2_clear_slots_for_restore",))
        return self.lv2_clear_slots_for_restore_rc

    def lv2_restore_slot_deferred(self, slot_id, uri):
        self.calls.append(("lv2_restore_slot_deferred", slot_id, uri))
        return self.lv2_restore_slot_deferred_rc

    def lv2_finish_restore_slots(self):
        self.calls.append(("lv2_finish_restore_slots",))
        return self.lv2_finish_restore_slots_rc


def test_set_eq_band_forwards_to_rust_peq():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.peq_enabled = False

    assert adapter.set_eq_band(2, 3.5) is True
    assert adapter._rust.calls == [("band", 2, 3.5)]
    assert adapter.output_error is None
    assert adapter.peq_enabled is True


def test_set_eq_band_reports_failure_when_rust_rejects():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust(band_rc=-3)
    adapter.output_error = "boom"

    assert adapter.set_eq_band(1, -6.0) is False
    assert adapter._rust.calls == [("band", 1, -6.0)]
    assert adapter.output_error == "boom"


def test_reset_eq_forwards_to_rust_peq():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.peq_enabled = True

    assert adapter.reset_eq() is True
    assert adapter._rust.calls == [("reset",)]
    assert adapter.output_error is None
    assert adapter.peq_enabled is False


def test_set_dsp_enabled_forwards_to_rust():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.dsp_enabled = False

    assert adapter.set_dsp_enabled(True) is True
    assert adapter._rust.calls == [("dsp", True)]
    assert adapter.output_error is None
    assert adapter.dsp_enabled is True


def test_set_peq_enabled_forwards_to_rust():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.peq_enabled = False

    assert adapter.set_peq_enabled(True) is True
    assert adapter._rust.calls == [("peq", True)]
    assert adapter.output_error is None
    assert adapter.peq_enabled is True


def test_set_convolver_enabled_forwards_to_rust():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.convolver_enabled = False

    assert adapter.set_convolver_enabled(True) is True
    assert adapter._rust.calls == [("convolver", True)]
    assert adapter.output_error is None
    assert adapter.convolver_enabled is True


def test_load_convolver_ir_updates_loaded_path():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.convolver_ir_path = ""

    assert adapter.load_convolver_ir("/tmp/room.wav") is True
    assert adapter._rust.calls == [("load_convolver", "/tmp/room.wav")]
    assert adapter.output_error is None
    assert adapter.convolver_ir_path == "/tmp/room.wav"


def test_clear_convolver_ir_resets_state():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.convolver_enabled = True
    adapter.convolver_ir_path = "/tmp/room.wav"

    assert adapter.clear_convolver_ir() is True
    assert adapter._rust.calls == [("clear_convolver",)]
    assert adapter.output_error is None
    assert adapter.convolver_enabled is False
    assert adapter.convolver_ir_path == ""


def test_lv2_restore_slot_ignores_enabled_port_value():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.lv2_slots = {}

    assert adapter.lv2_restore_slot(
        "lv2_0",
        "http://example.com/plugin",
        enabled=False,
        port_values={"enabled": 0.0, "mix": 0.5},
    ) is True
    assert adapter._rust.calls == [
        ("lv2_restore_slot", "lv2_0", "http://example.com/plugin"),
        ("lv2_set_slot_enabled", "lv2_0", False),
        ("lv2_set_port_value", "lv2_0", "mix", 0.5),
    ]
    assert adapter.lv2_slots == {
        "lv2_0": {
            "uri": "http://example.com/plugin",
            "enabled": False,
            "port_values": {"mix": 0.5},
        }
    }
    assert adapter.output_error is None


def test_lv2_set_port_value_does_not_persist_enabled_symbol():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.lv2_slots = {"lv2_0": {"uri": "http://example.com/plugin", "enabled": True, "port_values": {}}}

    assert adapter.lv2_set_port_value("lv2_0", "enabled", 1.0) is True
    assert adapter._rust.calls == [("lv2_set_port_value", "lv2_0", "enabled", 1.0)]
    assert adapter.lv2_slots["lv2_0"]["port_values"] == {}
    assert adapter.output_error is None


def test_lv2_set_port_value_does_not_persist_enable_symbol():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.lv2_slots = {"lv2_0": {"uri": "http://example.com/plugin", "enabled": True, "port_values": {}}}

    assert adapter.lv2_set_port_value("lv2_0", "enable", 1.0) is True
    assert adapter._rust.calls == [("lv2_set_port_value", "lv2_0", "enable", 1.0)]
    assert adapter.lv2_slots["lv2_0"]["port_values"] == {}
    assert adapter.output_error is None


def test_lv2_restore_slots_batches_graph_restore():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter._rust.lib = SimpleNamespace(
        rac_lv2_clear_slots_for_restore=True,
        rac_lv2_restore_slot_deferred=True,
        rac_lv2_finish_restore_slots=True,
    )
    adapter.output_error = "boom"
    adapter.lv2_slots = {"old": {"uri": "http://old/plugin", "enabled": True, "port_values": {"mix": 0.2}}}

    assert adapter.lv2_restore_slots(
        [
            {
                "slot_id": "lv2_0",
                "uri": "http://example.com/plugin",
                "enabled": False,
                "port_values": {"enabled": 0.0, "mix": 0.5},
            }
        ]
    ) is True
    assert adapter._rust.calls == [
        ("lv2_clear_slots_for_restore",),
        ("lv2_restore_slot_deferred", "lv2_0", "http://example.com/plugin"),
        ("lv2_finish_restore_slots",),
        ("lv2_set_slot_enabled", "lv2_0", False),
        ("lv2_set_port_value", "lv2_0", "mix", 0.5),
    ]
    assert adapter.lv2_slots == {
        "lv2_0": {
            "uri": "http://example.com/plugin",
            "enabled": False,
            "port_values": {"mix": 0.5},
        }
    }
    assert adapter.output_error is None


def test_lv2_restore_slots_falls_back_when_batch_symbols_are_unavailable():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter._rust.lib = object()
    adapter.output_error = "boom"
    adapter.lv2_slots = {}

    assert adapter.lv2_restore_slots(
        [
            {
                "slot_id": "lv2_0",
                "uri": "http://example.com/plugin",
                "enabled": False,
                "port_values": {"mix": 0.5},
            }
        ]
    ) is True
    assert adapter._rust.calls == [
        ("lv2_restore_slot", "lv2_0", "http://example.com/plugin"),
        ("lv2_set_slot_enabled", "lv2_0", False),
        ("lv2_set_port_value", "lv2_0", "mix", 0.5),
    ]


def test_set_limiter_enabled_forwards_to_rust():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.limiter_enabled = False

    assert adapter.set_limiter_enabled(True) is True
    assert adapter._rust.calls == [("limiter", True)]
    assert adapter.output_error is None
    assert adapter.limiter_enabled is True


def test_set_limiter_threshold_forwards_to_rust():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.limiter_threshold = 0.85

    assert adapter.set_limiter_threshold(0.72) is True
    assert adapter._rust.calls == [("limiter_threshold", 0.72)]
    assert adapter.output_error is None
    assert adapter.limiter_threshold == 0.72


def test_set_limiter_ratio_forwards_to_rust():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.limiter_ratio = 20.0

    assert adapter.set_limiter_ratio(12.0) is True
    assert adapter._rust.calls == [("limiter_ratio", 12.0)]
    assert adapter.output_error is None
    assert adapter.limiter_ratio == 12.0


def test_not_negotiated_with_limiter_schedules_retry_without_limiter(monkeypatch):
    scheduled = []
    monkeypatch.setattr(rust_audio.GLib, "idle_add", lambda fn, *args: scheduled.append((fn, args)) or 1)

    calls = []
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter.limiter_enabled = True
    adapter._limiter_negotiation_retry_pending = False
    adapter._last_loaded_uri = "file:///tmp/test.flac"
    adapter.output_state = "idle"
    adapter.output_error = None
    adapter._rust_last_play_ts = time.monotonic()
    adapter.set_limiter_enabled = lambda enabled: calls.append(("limiter", enabled)) or True
    adapter.set_uri = lambda uri: calls.append(("uri", uri))
    adapter.play = lambda: calls.append(("play",))

    rust_audio.RustAudioPlayerAdapter._apply_rust_error_policy(
        adapter,
        "codec",
        "streaming stopped, reason not-negotiated (-4)",
    )

    assert adapter.output_state == "fallback"
    assert adapter.output_error == "Limiter disabled: incompatible with current stream; retrying"
    assert len(scheduled) == 1

    fn, args = scheduled[0]
    fn(*args)

    assert calls == [
        ("limiter", False),
        ("uri", "file:///tmp/test.flac"),
        ("play",),
    ]
    assert adapter._limiter_negotiation_retry_pending is False


def test_set_tube_enabled_forwards_to_rust():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.tube_enabled = False

    assert adapter.set_tube_enabled(True) is True
    assert adapter._rust.calls == [("tube", True)]
    assert adapter.output_error is None
    assert adapter.tube_enabled is True


def test_set_tube_drive_forwards_to_rust():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"

    assert adapter.set_tube_drive(42) is True
    assert adapter._rust.calls == [("tube_drive", 42)]
    assert adapter.output_error is None
    assert adapter.tube_drive == 42


def test_set_tube_bias_sag_air_forward_to_rust():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"

    assert adapter.set_tube_bias(61) is True
    assert adapter.set_tube_sag(17) is True
    assert adapter.set_tube_air(73) is True
    assert adapter._rust.calls == [
        ("tube_bias", 61),
        ("tube_sag", 17),
        ("tube_air", 73),
    ]
    assert adapter.tube_bias == 61
    assert adapter.tube_sag == 17
    assert adapter.tube_air == 73


def test_set_widener_enabled_and_width_forward_to_rust():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.widener_enabled = False
    adapter.widener_width = 125

    assert adapter.set_widener_enabled(True) is True
    assert adapter.set_widener_width(140) is True
    assert adapter._rust.calls == [("widener", True), ("widener_width", 140)]
    assert adapter.output_error is None
    assert adapter.widener_enabled is True
    assert adapter.widener_width == 140


def test_set_widener_bass_mono_controls_forward_to_rust():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.widener_bass_mono_freq = 120
    adapter.widener_bass_mono_amount = 100

    assert adapter.set_widener_bass_mono_freq(90) is True
    assert adapter.set_widener_bass_mono_amount(75) is True
    assert adapter._rust.calls == [("widener_bass_freq", 90), ("widener_bass_amount", 75)]
    assert adapter.output_error is None
    assert adapter.widener_bass_mono_freq == 90
    assert adapter.widener_bass_mono_amount == 75


def test_set_volume_is_ignored_while_bit_perfect_mode_is_active():
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = _FakeRust()
    adapter.output_error = "boom"
    adapter.bit_perfect_mode = True
    mark_calls = []
    adapter._mark_transport_error = lambda *args, **kwargs: mark_calls.append((args, kwargs))

    adapter.set_volume(0.35)

    assert adapter._rust.calls == []
    assert mark_calls == []
    assert adapter.output_error is None
