import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_wire_tidal_app_is_idempotent_and_forceable():
    pytest.importorskip("gi")

    from app.app_wiring import is_tidal_app_wired, wire_tidal_app
    from main import TidalApp

    wire_tidal_app(TidalApp, force=True)
    assert is_tidal_app_wired(TidalApp) is True

    original = getattr(TidalApp, "on_play_pause")

    def _sentinel(_self, _btn):
        return None

    setattr(TidalApp, "on_play_pause", _sentinel)

    wire_tidal_app(TidalApp)
    assert getattr(TidalApp, "on_play_pause") is _sentinel

    wire_tidal_app(TidalApp, force=True)
    assert getattr(TidalApp, "on_play_pause") is original
