import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_tidalapp_constructs_after_wiring(monkeypatch):
    pytest.importorskip("gi")

    from app import app_init_runtime
    from app.app_wiring import wire_tidal_app
    from main import TidalApp

    monkeypatch.setattr(app_init_runtime, "init_runtime", lambda self: None)
    wire_tidal_app(TidalApp)

    app = TidalApp()
    assert app is not None
    assert hasattr(TidalApp, "do_activate")
    assert hasattr(TidalApp, "on_play_pause")
