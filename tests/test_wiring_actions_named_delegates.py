import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_action_delegate_bindings_are_named_functions():
    pytest.importorskip("gi")

    from app.app_wiring import wire_tidal_app
    from main import TidalApp

    wire_tidal_app(TidalApp)

    assert getattr(TidalApp, "on_play_pause").__name__ != "<lambda>"
    assert getattr(TidalApp, "_build_header").__name__ != "<lambda>"
    assert getattr(TidalApp, "render_search_results").__name__ != "<lambda>"
