import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from actions import audio_settings_actions as mod


class _Item:
    def __init__(self, text):
        self._text = text

    def get_string(self):
        return self._text


class _DD:
    def __init__(self, text):
        self._item = _Item(text)

    def get_selected_item(self):
        return self._item


class _PlayBtn:
    def __init__(self):
        self.icon_name = None

    def set_icon_name(self, name):
        self.icon_name = name


class _StatusBtn:
    def __init__(self):
        self.icon_name = None
        self.tooltip = None

    def set_icon_name(self, name):
        self.icon_name = name

    def set_tooltip_text(self, text):
        self.tooltip = text


def _make_app():
    app = SimpleNamespace()
    app.play_btn = _PlayBtn()
    app.driver_dd = _DD("ALSA")
    app.device_dd = _DD("USB DAC")
    app._last_disconnected_driver = ""
    app._last_disconnected_device_name = ""
    app.notices = []
    app.show_output_notice = lambda text, state, timeout: app.notices.append((text, state, timeout))
    return app


def _make_status_app(player=None, settings=None):
    return SimpleNamespace(
        playback_status_btn=_StatusBtn(),
        now_playing_status_btn=_StatusBtn(),
        player=player,
        settings=settings or {},
    )


def test_output_transition_switching(monkeypatch):
    app = _make_app()
    touched = []
    monkeypatch.setattr(mod, "_touch_output_probe_burst", lambda _app, seconds: touched.append(seconds))

    mod.on_output_state_transition(app, "active", "switching", None)

    assert touched == [30]
    assert app.notices[-1][1] == "switching"


def test_output_transition_active_after_fallback():
    app = _make_app()

    mod.on_output_state_transition(app, "fallback", "active", None)

    assert app.notices[-1][0] == "Audio output reconnected"
    assert app.notices[-1][1] == "ok"


def test_output_transition_fallback_disconnected(monkeypatch):
    app = _make_app()
    touched = []
    refreshed = []
    watched = []
    monkeypatch.setattr(mod, "_touch_output_probe_burst", lambda _app, seconds: touched.append(seconds))
    monkeypatch.setattr(
        mod,
        "refresh_devices_keep_driver_select_first",
        lambda _app, reason: refreshed.append(reason),
    )
    monkeypatch.setattr(
        mod,
        "start_output_hotplug_watch",
        lambda _app, seconds, interval_ms, slow_interval_ms: watched.append((seconds, interval_ms, slow_interval_ms)),
    )

    mod.on_output_state_transition(app, "active", "fallback", "USB disconnected")

    assert touched == [60]
    assert app.play_btn.icon_name == "media-playback-start-symbolic"
    assert app._last_disconnected_driver == "ALSA"
    assert app._last_disconnected_device_name == "USB DAC"
    assert refreshed == ["usb-disconnect"]
    assert watched == [(60, 1000, 5000)]
    assert app.notices[-1][1] == "warn"


def test_output_transition_error(monkeypatch):
    app = _make_app()
    touched = []
    monkeypatch.setattr(mod, "_touch_output_probe_burst", lambda _app, seconds: touched.append(seconds))

    mod.on_output_state_transition(app, "active", "error", "boom")

    assert touched == [45]
    assert app.play_btn.icon_name == "media-playback-start-symbolic"
    assert "boom" in app.notices[-1][0]
    assert app.notices[-1][1] == "error"


def test_sync_playback_status_icon_prefers_exclusive_over_bit_perfect():
    app = _make_status_app(
        player=SimpleNamespace(
            exclusive_lock_mode=True,
            bit_perfect_mode=True,
            dsp_enabled=False,
            peq_enabled=False,
            convolver_enabled=False,
            convolver_ir_path="",
            limiter_enabled=False,
            resampler_enabled=False,
            tape_enabled=False,
            tube_enabled=False,
            widener_enabled=False,
            lv2_slots={},
        ),
    )

    mod._sync_playback_status_icon(app)

    assert app.playback_status_btn.icon_name == "hiresti-status-exclusive-symbolic"
    assert app.playback_status_btn.tooltip == "Exclusive Mode Active"
    assert app.now_playing_status_btn.icon_name == "hiresti-status-exclusive-symbolic"


def test_sync_playback_status_icon_shows_dsp_only_when_processing_is_active():
    dsp_app = _make_status_app(
        player=SimpleNamespace(
            exclusive_lock_mode=False,
            bit_perfect_mode=False,
            dsp_enabled=True,
            peq_enabled=True,
            convolver_enabled=False,
            convolver_ir_path="",
            limiter_enabled=False,
            resampler_enabled=False,
            tape_enabled=False,
            tube_enabled=False,
            widener_enabled=False,
            lv2_slots={},
        ),
    )

    mod._sync_playback_status_icon(dsp_app)

    assert dsp_app.playback_status_btn.icon_name == "hiresti-status-dsp-symbolic"
    assert dsp_app.playback_status_btn.tooltip == "DSP Processing Active"

    normal_app = _make_status_app(
        player=SimpleNamespace(
            exclusive_lock_mode=False,
            bit_perfect_mode=False,
            dsp_enabled=True,
            peq_enabled=False,
            convolver_enabled=False,
            convolver_ir_path="",
            limiter_enabled=False,
            resampler_enabled=False,
            tape_enabled=False,
            tube_enabled=False,
            widener_enabled=False,
            lv2_slots={},
        ),
    )

    mod._sync_playback_status_icon(normal_app)

    assert normal_app.playback_status_btn.icon_name == "hiresti-status-normal-symbolic"
    assert normal_app.playback_status_btn.tooltip == "Normal Mode"
