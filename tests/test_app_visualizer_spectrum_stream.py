import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from app import app_bootstrap
from app import app_visualizer as mod


class _Revealer:
    def __init__(self, reveal=False):
        self.reveal = bool(reveal)

    def get_reveal_child(self):
        return self.reveal

    def set_reveal_child(self, value):
        self.reveal = bool(value)


class _Button:
    def __init__(self):
        self.icon_name = None
        self.classes = set()

    def set_icon_name(self, value):
        self.icon_name = str(value)

    def add_css_class(self, value):
        self.classes.add(str(value))

    def remove_css_class(self, value):
        self.classes.discard(str(value))


def test_hidden_visualizer_disables_spectrum_stream():
    app = SimpleNamespace(
        player=object(),
        _is_viz_surface_visible=lambda: False,
        _viz_current_page="spectrum",
        settings={"lyrics_bg_motion": 1},
    )

    assert mod._should_enable_spectrum_stream(app) is False


def test_visible_spectrum_page_enables_spectrum_stream():
    app = SimpleNamespace(
        player=object(),
        _is_viz_surface_visible=lambda: True,
        _viz_current_page="spectrum",
        settings={"lyrics_bg_motion": 0},
    )

    assert mod._should_enable_spectrum_stream(app) is True


def test_visible_static_lyrics_page_disables_spectrum_stream():
    app = SimpleNamespace(
        player=object(),
        _is_viz_surface_visible=lambda: True,
        _viz_current_page="lyrics",
        settings={"lyrics_bg_motion": 0},
    )

    assert mod._should_enable_spectrum_stream(app) is False


def test_visible_motion_lyrics_page_enables_spectrum_stream():
    app = SimpleNamespace(
        player=object(),
        _is_viz_surface_visible=lambda: True,
        _viz_current_page="lyrics",
        settings={"lyrics_bg_motion": 1},
    )

    assert mod._should_enable_spectrum_stream(app) is True


def test_set_visualizer_expanded_false_syncs_spectrum_stream():
    calls = []
    app = SimpleNamespace(
        _viz_fullscreen_active=False,
        _viz_open_layout_source=0,
        _viz_open_stream_source=0,
        _viz_handle_settle_source=0,
        _viz_fade_source=0,
        _last_spectrum_frame=None,
        _viz_seed_frame=None,
        viz_revealer=_Revealer(reveal=True),
        viz_btn=_Button(),
        _apply_overlay_scroll_padding=lambda expanded: calls.append(("padding", bool(expanded))),
        _position_viz_handle=lambda expanded, animate=False: calls.append(("position", bool(expanded), bool(animate))),
        _stop_viz_placeholder=lambda: calls.append(("placeholder", "stop")),
        _sync_spectrum_stream_state=lambda: calls.append(("sync",)),
        _set_viz_content_opacity=lambda alpha: calls.append(("opacity", float(alpha))),
    )

    mod._set_visualizer_expanded(app, False)

    assert ("sync",) in calls
    assert app.viz_revealer.get_reveal_child() is False
    assert app.viz_btn.icon_name == "hiresti-pan-up-symbolic"


def test_run_post_activate_tasks_no_longer_schedules_hidden_spectrum_prewarm(monkeypatch):
    scheduled = []

    def _timeout_add(delay_ms, func):
        scheduled.append(int(delay_ms))
        return len(scheduled)

    monkeypatch.setattr(app_bootstrap.GLib, "timeout_add", _timeout_add)

    app = SimpleNamespace(
        _start_mpris_service=lambda: None,
        _start_remote_api_if_enabled=lambda: None,
        _restore_session_async=lambda: None,
        _schedule_update_ui_loop=lambda _delay: None,
        _schedule_output_status_loop=lambda _delay: None,
        _prewarm_visualizer_cold_start=lambda: False,
        _init_tray_icon=lambda: None,
        _ensure_overlay_handles_visible=lambda: None,
    )

    assert app_bootstrap._run_post_activate_tasks(app) is False
    assert 80 not in scheduled
    assert sorted(scheduled) == [0, 140, 220]


def test_prewarm_visualizer_cold_start_stops_after_success():
    calls = []
    app = SimpleNamespace(
        _viz_opened_once=False,
        _viz_cold_prewarm_source=7,
        _viz_cold_prewarm_attempts=0,
        viz=SimpleNamespace(prewarm_backends=lambda: calls.append(True) or True),
    )

    assert mod._prewarm_visualizer_cold_start(app) is False
    assert calls == [True]
    assert app._viz_cold_prewarm_source == 0
