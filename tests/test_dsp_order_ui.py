import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app_builders as mod


def test_apply_dsp_order_persists_and_rebuilds():
    calls = []

    class _Player:
        def set_dsp_order(self, order):
            calls.append(("player", list(order)))
            return True

    app = SimpleNamespace(
        player=_Player(),
        settings={},
        schedule_save_settings=lambda: calls.append(("save",)),
        _rebuild_dsp_overview_chain=lambda: calls.append(("rebuild",)),
        _update_dsp_ui_state=lambda: calls.append(("ui",)),
    )

    assert mod._apply_dsp_order(app, ["tube", "peq", "widener", "convolver", "tape"]) is True
    assert app.settings["dsp_order"] == ["tube", "peq", "widener", "convolver", "tape"]
    assert calls == [
        ("player", ["tube", "peq", "widener", "convolver", "tape"]),
        ("save",),
        ("rebuild",),
        ("ui",),
    ]


def test_on_dsp_order_drop_updates_pending_only_while_editing():
    calls = []
    app = SimpleNamespace(
        settings={"dsp_order": ["peq", "convolver", "tape", "tube", "widener"]},
        _dsp_order_editing=True,
        _dsp_order_pending=["peq", "convolver", "tape", "tube", "widener"],
        _rebuild_dsp_overview_chain=lambda: calls.append(("rebuild",)),
        _refresh_dsp_order_edit_ui=lambda: calls.append(("refresh",)),
        _update_dsp_ui_state=lambda: calls.append(("ui",)),
    )

    assert mod._on_dsp_order_drop(app, "tube", "convolver") is True
    assert app._dsp_order_pending == ["peq", "tube", "convolver", "tape", "widener"]
    assert calls == [("rebuild",), ("refresh",), ("ui",)]


def test_on_dsp_order_drop_moves_forward_after_target():
    calls = []
    app = SimpleNamespace(
        settings={"dsp_order": ["peq", "convolver", "tape", "tube", "widener"]},
        _dsp_order_editing=True,
        _dsp_order_pending=["peq", "convolver", "tape", "tube", "widener"],
        _rebuild_dsp_overview_chain=lambda: calls.append(("rebuild",)),
        _refresh_dsp_order_edit_ui=lambda: calls.append(("refresh",)),
        _update_dsp_ui_state=lambda: calls.append(("ui",)),
    )

    assert mod._on_dsp_order_drop(app, "peq", "tube") is True
    assert app._dsp_order_pending == ["convolver", "tape", "tube", "peq", "widener"]
    assert calls == [("rebuild",), ("refresh",), ("ui",)]


def test_on_dsp_order_drop_ignored_when_not_editing():
    app = SimpleNamespace(
        settings={"dsp_order": ["peq", "convolver", "tape", "tube", "widener"]},
        _dsp_order_editing=False,
        _dsp_order_pending=["peq", "convolver", "tape", "tube", "widener"],
    )

    assert mod._on_dsp_order_drop(app, "peq", "tube") is False
    assert app._dsp_order_pending == ["peq", "convolver", "tape", "tube", "widener"]


def test_save_dsp_order_edit_applies_pending_once():
    calls = []

    app = SimpleNamespace(
        _dsp_order_editing=True,
        _dsp_order_pending=["tube", "peq", "widener", "convolver", "tape"],
        _apply_dsp_order=lambda order, save=True: calls.append(("apply", list(order), bool(save))) or True,
        _rebuild_dsp_overview_chain=lambda: calls.append(("rebuild",)),
        _refresh_dsp_order_edit_ui=lambda: calls.append(("refresh",)),
        _update_dsp_ui_state=lambda: calls.append(("ui",)),
        show_output_notice=lambda text, state, timeout: calls.append(("notice", text, state, timeout)),
    )

    mod._save_dsp_order_edit(app)

    assert app._dsp_order_editing is False
    assert app._dsp_order_pending is None
    assert calls == [
        ("apply", ["tube", "peq", "widener", "convolver", "tape"], True),
        ("rebuild",),
        ("refresh",),
        ("ui",),
        ("notice", "DSP chain order saved", "ok", 2200),
    ]
