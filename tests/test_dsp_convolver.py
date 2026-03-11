import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app_builders as mod


class _Entry:
    def __init__(self, text=""):
        self.text = str(text)

    def get_text(self):
        return self.text

    def set_text(self, value):
        self.text = str(value)


class _Label:
    def __init__(self):
        self.text = ""

    def set_text(self, value):
        self.text = str(value)


class _Switch:
    def __init__(self):
        self.active = False
        self.sensitive = None
        self.tooltip = None

    def get_active(self):
        return bool(self.active)

    def set_active(self, value):
        self.active = bool(value)

    def set_sensitive(self, value):
        self.sensitive = bool(value)

    def set_tooltip_text(self, value):
        self.tooltip = value


class _Scale:
    def __init__(self, value=0.0):
        self.value = float(value)
        self.sensitive = None

    def get_value(self):
        return float(self.value)

    def set_value(self, value):
        self.value = float(value)

    def set_sensitive(self, value):
        self.sensitive = bool(value)


class _File:
    def __init__(self, path):
        self._path = path

    def get_path(self):
        return self._path


class _Dialog:
    def __init__(self, file_obj=None, raises=False):
        self.file_obj = file_obj
        self.raises = raises

    def open_finish(self, _result):
        if self.raises:
            raise RuntimeError("cancelled")
        return self.file_obj


def test_apply_dsp_convolver_path_loads_ir_and_enables_module():
    calls = []
    saved = []
    app = SimpleNamespace(
        player=SimpleNamespace(
            load_convolver_ir=lambda path: calls.append(("load", path)) or True,
            set_convolver_enabled=lambda enabled: calls.append(("enable", enabled)) or True,
        ),
        settings={},
        dsp_convolver_path_entry=_Entry("/tmp/room.wav"),
        schedule_save_settings=lambda: saved.append(True),
        _update_dsp_ui_state=lambda: calls.append(("ui",)),
        _release_bit_perfect_for_dsp=lambda: True,
        _dsp_convolver_last_error="",
    )

    assert mod._apply_dsp_convolver_path(app) is True
    assert calls == [("load", "/tmp/room.wav"), ("enable", True), ("ui",)]
    assert app.settings["dsp_convolver_path"] == "/tmp/room.wav"
    assert app.settings["dsp_convolver_enabled"] is True
    assert saved == [True]


def test_on_dsp_convolver_toggled_requires_ir_when_none_loaded():
    ui_calls = []
    app = SimpleNamespace(
        _dsp_ui_syncing=False,
        player=SimpleNamespace(convolver_ir_path=""),
        dsp_convolver_path_entry=_Entry(""),
        _dsp_convolver_last_error="",
        _update_dsp_ui_state=lambda: ui_calls.append(True),
    )

    assert mod._on_dsp_convolver_toggled(app, None, True) is True
    assert app._dsp_convolver_last_error == "Load an FIR / IR file first"
    assert ui_calls == [True]


def test_update_dsp_ui_state_reports_loaded_but_bypassed_convolver():
    status = _Label()
    entry = _Entry("")
    convolver_switch = _Switch()
    sync_calls = []
    app = SimpleNamespace(
        eq_band_values=[0.0] * 10,
        player=SimpleNamespace(
            dsp_enabled=True,
            peq_enabled=False,
            convolver_enabled=False,
            convolver_ir_path="/tmp/room.wav",
        ),
        settings={"bit_perfect": False, "dsp_convolver_path": ""},
        dsp_master_switch=None,
        dsp_master_summary_label=None,
        dsp_peq_enable_switch=None,
        dsp_peq_status_label=None,
        dsp_convolver_path_entry=entry,
        dsp_convolver_status_label=status,
        dsp_module_switches={"convolver": convolver_switch},
        dsp_btn=None,
        now_playing_dsp_btn=None,
        _sync_playback_status_icon=lambda: sync_calls.append(True),
        _dsp_convolver_last_error="",
    )

    mod._update_dsp_ui_state(app)

    assert entry.get_text() == "/tmp/room.wav"
    assert status.text == "Loaded: room.wav (bypassed)"
    assert convolver_switch.sensitive is True
    assert convolver_switch.tooltip == "Enable or bypass convolution"
    assert sync_calls == [True]


def test_update_dsp_ui_state_disables_convolver_switch_until_ir_loaded():
    convolver_switch = _Switch()
    app = SimpleNamespace(
        eq_band_values=[0.0] * 10,
        player=SimpleNamespace(
            dsp_enabled=True,
            peq_enabled=False,
            convolver_enabled=False,
            convolver_ir_path="",
        ),
        settings={"bit_perfect": False, "dsp_convolver_path": ""},
        dsp_master_switch=None,
        dsp_master_summary_label=None,
        dsp_peq_enable_switch=None,
        dsp_peq_status_label=None,
        dsp_convolver_path_entry=None,
        dsp_convolver_status_label=None,
        dsp_module_switches={"convolver": convolver_switch},
        dsp_btn=None,
        now_playing_dsp_btn=None,
        _dsp_convolver_last_error="",
    )

    mod._update_dsp_ui_state(app)

    assert convolver_switch.sensitive is False
    assert convolver_switch.tooltip == "Load a FIR / IR file first"


def test_on_dsp_convolver_file_selected_applies_path():
    calls = []
    app = SimpleNamespace(
        _apply_dsp_convolver_path=lambda path, enable_after_load=True: calls.append((path, enable_after_load)),
    )

    mod._on_dsp_convolver_file_selected(app, _Dialog(_File("/tmp/room.wav")), object())

    assert calls == [("/tmp/room.wav", True)]


def test_on_dsp_convolver_file_selected_ignores_cancelled_dialog():
    calls = []
    app = SimpleNamespace(
        _apply_dsp_convolver_path=lambda path, enable_after_load=True: calls.append((path, enable_after_load)),
    )

    mod._on_dsp_convolver_file_selected(app, _Dialog(raises=True), object())

    assert calls == []


def test_update_dsp_ui_state_reports_active_limiter():
    status = _Label()
    threshold = _Scale()
    ratio = _Scale()
    limiter_switch = _Switch()
    app = SimpleNamespace(
        eq_band_values=[0.0] * 10,
        player=SimpleNamespace(
            dsp_enabled=True,
            peq_enabled=False,
            convolver_enabled=False,
            convolver_ir_path="",
            limiter_enabled=True,
            limiter_threshold=0.76,
            limiter_ratio=18.0,
        ),
        settings={"bit_perfect": False, "dsp_convolver_path": ""},
        dsp_master_switch=None,
        dsp_master_summary_label=None,
        dsp_peq_enable_switch=None,
        dsp_peq_status_label=None,
        dsp_convolver_path_entry=None,
        dsp_convolver_status_label=None,
        dsp_limiter_threshold_scale=threshold,
        dsp_limiter_ratio_scale=ratio,
        dsp_limiter_status_label=status,
        dsp_module_switches={"limiter": limiter_switch},
        dsp_btn=None,
        now_playing_dsp_btn=None,
        _dsp_convolver_last_error="",
        _dsp_limiter_last_error="",
    )

    mod._update_dsp_ui_state(app)

    assert threshold.get_value() == 76.0
    assert ratio.get_value() == 18.0
    assert status.text == "Ceiling 76% / Ratio 18:1"
    assert limiter_switch.sensitive is True


def test_on_dsp_limiter_toggled_persists_state():
    ui_calls = []
    saved = []
    app = SimpleNamespace(
        _dsp_ui_syncing=False,
        player=SimpleNamespace(set_limiter_enabled=lambda enabled: True),
        _release_bit_perfect_for_dsp=lambda: True,
        _update_dsp_ui_state=lambda: ui_calls.append(True),
        settings={},
        schedule_save_settings=lambda: saved.append(True),
        _dsp_limiter_last_error="",
    )

    assert mod._on_dsp_limiter_toggled(app, None, True) is False
    assert app.settings["dsp_limiter_enabled"] is True
    assert saved == [True]
    assert ui_calls == [True]


def test_update_dsp_ui_state_reports_active_tube_stage():
    status = _Label()
    drive = _Scale()
    bias = _Scale()
    sag = _Scale()
    air = _Scale()
    tube_switch = _Switch()
    app = SimpleNamespace(
        eq_band_values=[0.0] * 10,
        player=SimpleNamespace(
            dsp_enabled=True,
            peq_enabled=False,
            convolver_enabled=False,
            convolver_ir_path="",
            limiter_enabled=False,
            tube_enabled=True,
            tube_drive=32,
            tube_bias=58,
            tube_sag=21,
            tube_air=49,
        ),
        settings={"bit_perfect": False, "dsp_convolver_path": ""},
        dsp_master_switch=None,
        dsp_master_summary_label=None,
        dsp_peq_enable_switch=None,
        dsp_peq_status_label=None,
        dsp_convolver_path_entry=None,
        dsp_convolver_status_label=None,
        dsp_limiter_threshold_scale=None,
        dsp_limiter_ratio_scale=None,
        dsp_limiter_status_label=None,
        dsp_tube_status_label=status,
        dsp_tube_drive_scale=drive,
        dsp_tube_bias_scale=bias,
        dsp_tube_sag_scale=sag,
        dsp_tube_air_scale=air,
        dsp_module_switches={"tube": tube_switch},
        dsp_btn=None,
        now_playing_dsp_btn=None,
        _dsp_convolver_last_error="",
        _dsp_limiter_last_error="",
    )

    mod._update_dsp_ui_state(app)

    assert status.text == "Active: Drive 32 / Bias 58 / Sag 21 / Air 49"
    assert drive.get_value() == 32.0
    assert bias.get_value() == 58.0
    assert sag.get_value() == 21.0
    assert air.get_value() == 49.0
    assert tube_switch.sensitive is True


def test_on_dsp_tube_preset_changed_applies_values():
    calls = []
    saved = []
    drive = _Scale()
    bias = _Scale()
    sag = _Scale()
    air = _Scale()

    class _Dropdown:
        def get_selected(self):
            return 1

    app = SimpleNamespace(
        _dsp_ui_syncing=False,
        dsp_tube_drive_scale=drive,
        dsp_tube_bias_scale=bias,
        dsp_tube_sag_scale=sag,
        dsp_tube_air_scale=air,
        player=SimpleNamespace(
            set_tube_drive=lambda value: calls.append(("drive", value)),
            set_tube_bias=lambda value: calls.append(("bias", value)),
            set_tube_sag=lambda value: calls.append(("sag", value)),
            set_tube_air=lambda value: calls.append(("air", value)),
        ),
        settings={},
        schedule_save_settings=lambda: saved.append(True),
    )

    mod._on_dsp_tube_preset_changed(app, _Dropdown(), None)

    assert drive.get_value() == float(mod._DSP_TUBE_PRESETS["Triode"][0])
    assert bias.get_value() == float(mod._DSP_TUBE_PRESETS["Triode"][1])
    assert sag.get_value() == float(mod._DSP_TUBE_PRESETS["Triode"][2])
    assert air.get_value() == float(mod._DSP_TUBE_PRESETS["Triode"][3])
    assert calls == [
        ("drive", mod._DSP_TUBE_PRESETS["Triode"][0]),
        ("bias", mod._DSP_TUBE_PRESETS["Triode"][1]),
        ("sag", mod._DSP_TUBE_PRESETS["Triode"][2]),
        ("air", mod._DSP_TUBE_PRESETS["Triode"][3]),
    ]
    assert saved == [True]


def test_update_dsp_ui_state_reports_active_widener():
    status = _Label()
    width = _Scale()
    bass_freq = _Scale()
    bass_amount = _Scale()
    widener_switch = _Switch()
    app = SimpleNamespace(
        eq_band_values=[0.0] * 10,
        player=SimpleNamespace(
            dsp_enabled=True,
            peq_enabled=False,
            convolver_enabled=False,
            convolver_ir_path="",
            limiter_enabled=False,
            widener_enabled=True,
            widener_width=140,
            widener_bass_mono_freq=90,
            widener_bass_mono_amount=75,
        ),
        settings={"bit_perfect": False, "dsp_convolver_path": ""},
        dsp_master_switch=None,
        dsp_master_summary_label=None,
        dsp_peq_enable_switch=None,
        dsp_peq_status_label=None,
        dsp_convolver_path_entry=None,
        dsp_convolver_status_label=None,
        dsp_limiter_threshold_scale=None,
        dsp_limiter_ratio_scale=None,
        dsp_limiter_status_label=None,
        dsp_tube_status_label=None,
        dsp_widener_status_label=status,
        dsp_widener_width_scale=width,
        dsp_widener_bass_mono_freq_scale=bass_freq,
        dsp_widener_bass_mono_amount_scale=bass_amount,
        dsp_module_switches={"widener": widener_switch},
        dsp_btn=None,
        now_playing_dsp_btn=None,
        _dsp_convolver_last_error="",
        _dsp_limiter_last_error="",
    )

    mod._update_dsp_ui_state(app)

    assert status.text == "Active: Width 140% / Bass Mono 90 Hz @ 75%"
    assert width.get_value() == 140.0
    assert bass_freq.get_value() == 90.0
    assert bass_amount.get_value() == 75.0
    assert widener_switch.sensitive is True


def test_on_dsp_widener_width_changed_updates_summary():
    ui_calls = []
    saved = []
    scale = _Scale(160)
    app = SimpleNamespace(
        _dsp_ui_syncing=False,
        player=SimpleNamespace(set_widener_width=lambda value: True),
        settings={},
        schedule_save_settings=lambda: saved.append(True),
        _update_dsp_ui_state=lambda: ui_calls.append(True),
    )

    mod._on_dsp_widener_width_changed(app, scale)

    assert app.settings["dsp_widener_width"] == 160
    assert saved == [True]
    assert ui_calls == [True]


def test_on_dsp_widener_bass_mono_controls_update_summary():
    ui_calls = []
    saved = []
    freq_scale = _Scale(95)
    amt_scale = _Scale(80)
    app = SimpleNamespace(
        _dsp_ui_syncing=False,
        player=SimpleNamespace(
            set_widener_bass_mono_freq=lambda value: True,
            set_widener_bass_mono_amount=lambda value: True,
        ),
        settings={},
        schedule_save_settings=lambda: saved.append(True),
        _update_dsp_ui_state=lambda: ui_calls.append(True),
    )

    mod._on_dsp_widener_bass_mono_freq_changed(app, freq_scale)
    mod._on_dsp_widener_bass_mono_amount_changed(app, amt_scale)

    assert app.settings["dsp_widener_bass_mono_freq"] == 95
    assert app.settings["dsp_widener_bass_mono_amount"] == 80
    assert saved == [True, True]
    assert ui_calls == [True, True]
