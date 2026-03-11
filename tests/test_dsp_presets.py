import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app_builders as mod


def test_current_eq_preset_name_detects_builtin_curve():
    app = SimpleNamespace(eq_band_values=list(mod._DSP_PRESETS["Bass Boost"]))

    assert mod._current_eq_preset_name(app) == "Bass Boost"


def test_current_eq_preset_name_falls_back_to_custom():
    app = SimpleNamespace(eq_band_values=[0.0] * 9 + [1.25])

    assert mod._current_eq_preset_name(app) == "Custom"


def test_apply_eq_preset_updates_values_and_enables_peq():
    calls = []

    class _Player:
        def set_peq_enabled(self, enabled):
            calls.append(("peq_enabled", enabled))
            return True

        def set_eq_band(self, idx, value):
            calls.append(("band", idx, value))
            return True

    sync_calls = []
    ui_calls = []
    app = SimpleNamespace(
        eq_band_values=[0.0] * 10,
        player=_Player(),
        _sync_eq_slider_groups=lambda source_scale=None: sync_calls.append(source_scale),
        _update_dsp_ui_state=lambda: ui_calls.append(True),
    )

    assert mod._apply_eq_preset(app, "Vocal") is True
    assert app.eq_band_values == list(mod._DSP_PRESETS["Vocal"])
    assert calls[0] == ("peq_enabled", True)
    assert len([c for c in calls if c[0] == "band"]) == 10
    assert sync_calls == [None]
    assert ui_calls == [True]


def test_apply_eq_preset_persists_peq_state():
    scheduled = []
    app = SimpleNamespace(
        eq_band_values=[0.0] * 10,
        settings={},
        player=SimpleNamespace(
            set_peq_enabled=lambda enabled: True,
            set_eq_band=lambda idx, value: True,
        ),
        _sync_eq_slider_groups=lambda source_scale=None: None,
        _update_dsp_ui_state=lambda: None,
        schedule_save_settings=lambda: scheduled.append(True),
    )

    assert mod._apply_eq_preset(app, "Bass Boost") is True
    assert app.settings["dsp_peq_enabled"] is True
    assert app.settings["dsp_peq_bands"] == list(mod._DSP_PRESETS["Bass Boost"])
    assert scheduled == [True]
