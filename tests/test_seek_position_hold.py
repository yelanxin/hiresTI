import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from _rust import audio as audio_mod


class _Shim:
    """RustAudioPlayerAdapter.get_position bound to a plain object."""

    get_position = audio_mod.RustAudioPlayerAdapter.get_position

    def __init__(self, cached_pos, target=None, hold_for=1.0):
        self._cached_pos_s = cached_pos
        self._cached_dur_s = 240.0
        self._seek_target_s = target
        self._seek_hold_until = time.monotonic() + hold_for

    def _refresh_rust_cache(self, force=False):
        pass


def test_backward_seek_pins_to_target_while_engine_is_stale():
    # Seek 3:00 -> 1:00; engine still reports the pre-seek position.
    shim = _Shim(cached_pos=180.0, target=60.0)
    pos, _dur = shim.get_position()
    assert pos == 60.0
    assert shim._seek_target_s == 60.0  # still holding


def test_short_forward_seek_pins_to_target_while_engine_is_stale():
    # Seek 1:00 -> 1:10; the old rebound-only mask exposed the stale 60s.
    shim = _Shim(cached_pos=60.0, target=70.0)
    pos, _dur = shim.get_position()
    assert pos == 70.0


def test_hold_releases_when_engine_converges():
    shim = _Shim(cached_pos=60.4, target=60.0)
    pos, _dur = shim.get_position()
    assert pos == 60.4  # engine value, handed off seamlessly
    assert shim._seek_target_s is None


def test_hold_expires_after_deadline():
    shim = _Shim(cached_pos=180.0, target=60.0, hold_for=-0.1)
    pos, _dur = shim.get_position()
    assert pos == 180.0
    assert shim._seek_target_s is None


def test_no_hold_passes_engine_position_through():
    shim = _Shim(cached_pos=42.0, target=None)
    pos, dur = shim.get_position()
    assert (pos, dur) == (42.0, 240.0)
