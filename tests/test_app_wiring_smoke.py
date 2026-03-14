import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_wire_tidal_app_binds_core_methods():
    pytest.importorskip("gi")

    from app.app_wiring import wire_tidal_app
    from main import TidalApp

    wire_tidal_app(TidalApp)

    required = [
        "on_play_pause",
        "on_next_track",
        "on_prev_track",
        "get_next_index",
        "_build_header",
        "_build_body",
        "_build_grid_view",
        "_build_settings_page",
        "_queue_rebuild_dsp_overview_chain",
        "_schedule_output_status_loop",
        "update_tech_label",
        "_restore_session_async",
        "on_window_close_request",
        "toggle_queue_drawer",
        "on_playlist_card_clicked",
        "on_search",
    ]
    for name in required:
        assert hasattr(TidalApp, name), f"missing binding: {name}"
