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

    def __init__(self, cached_pos, target=None, hold_for=1.0, stale_pos=None,
                 hard_for=8.0, engine_pos=None):
        self._cached_pos_s = cached_pos
        self._cached_dur_s = 240.0
        self._seek_target_s = target
        self._seek_hold_until = time.monotonic() + hold_for
        self._seek_hold_hard_until = time.monotonic() + hard_for
        self._seek_stale_pos_s = stale_pos
        # Engine-truth position served when the cache is force-refreshed
        # (None = leave the cached value untouched, like a fresh cache).
        self._engine_pos = engine_pos
        self.forced_refreshes = 0

    def _refresh_rust_cache(self, force=False):
        if force:
            self.forced_refreshes += 1
            if self._engine_pos is not None:
                self._cached_pos_s = self._engine_pos


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


def test_soft_expiry_keeps_pinning_while_engine_is_parked_at_pre_seek_pos():
    # Slow USB+DASH seek: soft deadline passed but the engine still reports
    # the pre-seek position — showing that stale value is never right.
    shim = _Shim(cached_pos=180.0, target=60.0, hold_for=-0.1, stale_pos=180.0)
    pos, _dur = shim.get_position()
    assert pos == 60.0
    assert shim._seek_target_s == 60.0


def test_soft_expiry_releases_once_engine_moved_elsewhere():
    # Engine restarted somewhere that is neither the stale spot nor the
    # target (e.g. seek clamped) — trust it after the soft deadline.
    shim = _Shim(cached_pos=100.0, target=60.0, hold_for=-0.1, stale_pos=180.0)
    pos, _dur = shim.get_position()
    assert pos == 100.0
    assert shim._seek_target_s is None


def test_hard_expiry_gives_up_even_if_engine_never_moved():
    shim = _Shim(cached_pos=180.0, target=60.0, hold_for=-0.1, stale_pos=180.0, hard_for=-0.1)
    pos, _dur = shim.get_position()
    assert pos == 180.0
    assert shim._seek_target_s is None


def test_no_hold_passes_engine_position_through():
    shim = _Shim(cached_pos=42.0, target=None)
    pos, dur = shim.get_position()
    assert (pos, dur) == (42.0, 240.0)
    assert shim.forced_refreshes == 0  # no seek -> normal cached refresh


def test_optimistic_cache_write_cannot_fake_convergence():
    # seek() writes the target into _cached_pos_s optimistically. If the
    # convergence check reads that value back (fresh-cache early return),
    # the hold is dropped while the engine still reports the pre-seek
    # position — the dot bounces on the next tick. The hold must force a
    # real engine read instead.
    shim = _Shim(cached_pos=60.0, target=60.0, stale_pos=180.0, engine_pos=180.0)
    pos, _dur = shim.get_position()
    assert shim.forced_refreshes == 1
    assert pos == 60.0                 # pinned to target
    assert shim._seek_target_s == 60.0  # hold NOT dropped by the fake value


from types import SimpleNamespace

from actions.lyrics_playback_actions import _position_poll_due


def test_ui_cache_bypassed_while_seek_hold_active():
    app = SimpleNamespace(player=SimpleNamespace(_seek_target_s=60.0))
    # Cache is fresh, but a seek hold is active -> must poll anyway.
    assert _position_poll_due(app, now=10.0, last_poll=9.9, poll_interval=0.45, cached_pd=(180.0, 240.0))


def test_ui_cache_used_when_fresh_and_no_seek():
    app = SimpleNamespace(player=SimpleNamespace(_seek_target_s=None))
    assert not _position_poll_due(app, now=10.0, last_poll=9.9, poll_interval=0.45, cached_pd=(60.0, 240.0))
    assert _position_poll_due(app, now=10.5, last_poll=9.9, poll_interval=0.45, cached_pd=(60.0, 240.0))
    assert _position_poll_due(app, now=10.0, last_poll=9.9, poll_interval=0.45, cached_pd=None)


def test_ui_cache_poll_due_tolerates_players_without_hold_state():
    app = SimpleNamespace(player=SimpleNamespace())
    assert not _position_poll_due(app, now=10.0, last_poll=9.9, poll_interval=0.45, cached_pd=(60.0, 240.0))
