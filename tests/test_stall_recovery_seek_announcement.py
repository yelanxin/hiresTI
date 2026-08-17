import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from types import SimpleNamespace

import pytest

pytest.importorskip("gi")

from app import app_init_runtime


def test_internal_seek_callback_is_wired_to_mpris():
    player = SimpleNamespace()
    app = SimpleNamespace(
        player=player,
        _mpris_emit_seeked=lambda seconds: None,
    )

    app_init_runtime._wire_player_callbacks(app)

    assert player._on_internal_seek_callback is app._mpris_emit_seeked


def test_internal_seek_callback_is_skipped_when_mpris_is_absent():
    player = SimpleNamespace()
    app = SimpleNamespace(player=player)

    app_init_runtime._wire_player_callbacks(app)

    assert not hasattr(player, "_on_internal_seek_callback")
