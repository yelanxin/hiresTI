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

    def __init__(self, cached_pos, target=None, hold_for=4.0, stale_pos=None,
                 hard_for=8.0, engine_pos=None, restart_seen=False):
        self._cached_pos_s = cached_pos
        self._cached_dur_s = 240.0
        self._seek_target_s = target
        self._seek_hold_until = time.monotonic() + hold_for
        self._seek_hold_hard_until = time.monotonic() + hard_for
        self._seek_stale_pos_s = stale_pos
        self._seek_restart_seen = restart_seen
        # Engine-truth position served when the cache is force-refreshed
        # (None = leave the cached value untouched, like a fresh cache).
        self._engine_pos = engine_pos
        self.forced_refreshes = 0

    def _refresh_rust_cache(self, force=False):
        if force:
            self.forced_refreshes += 1
            if self._engine_pos is not None:
                self._cached_pos_s = self._engine_pos


def test_pins_target_before_restart_event_regardless_of_engine_value():
    # Until the post-seek decode run starts, every engine position belongs
    # to the pre-seek world — backward seek, short forward seek, or even a
    # value that coincidentally matches the target must all stay pinned.
    for engine_value in (180.0, 60.5, 30.0, 0.0):
        shim = _Shim(cached_pos=engine_value, target=30.0, restart_seen=False)
        pos, _dur = shim.get_position()
        assert pos == 30.0, f"engine={engine_value}"
        assert shim._seek_target_s == 30.0  # hold intact


def test_optimistic_cache_write_cannot_fake_convergence():
    # seek() writes the target into _cached_pos_s optimistically; without
    # the restart event that value must not release the hold.
    shim = _Shim(cached_pos=60.0, target=60.0, engine_pos=180.0, restart_seen=False)
    pos, _dur = shim.get_position()
    assert shim.forced_refreshes == 1  # hold forces a real engine read
    assert pos == 60.0
    assert shim._seek_target_s == 60.0


def test_converges_after_restart_event():
    shim = _Shim(cached_pos=30.4, target=30.0, restart_seen=True)
    pos, _dur = shim.get_position()
    assert pos == 30.4  # engine value, handed off seamlessly
    assert shim._seek_target_s is None


def test_no_convergence_after_restart_until_engine_reaches_target():
    # Restarted but the engine still reports the old spot (e.g. cache lag):
    # keep pinning until it actually lands near the target.
    shim = _Shim(cached_pos=180.0, target=30.0, restart_seen=True)
    pos, _dur = shim.get_position()
    assert pos == 30.0
    assert shim._seek_target_s == 30.0


def test_soft_expiry_trusts_engine_after_restart():
    # Restart happened but the engine never converged (e.g. seek clamped
    # at EOF) — after the soft deadline, show what actually plays.
    shim = _Shim(cached_pos=200.0, target=230.0, hold_for=-0.1, restart_seen=True)
    pos, _dur = shim.get_position()
    assert pos == 200.0
    assert shim._seek_target_s is None


def test_soft_expiry_keeps_pinning_without_restart_event():
    # Slow seek: soft deadline passed but the decode run has not restarted
    # yet — the engine value is still pre-seek and must stay hidden.
    shim = _Shim(cached_pos=180.0, target=30.0, hold_for=-0.1, restart_seen=False)
    pos, _dur = shim.get_position()
    assert pos == 30.0
    assert shim._seek_target_s == 30.0


def test_hard_expiry_gives_up_even_without_restart_event():
    shim = _Shim(cached_pos=180.0, target=30.0, hold_for=-0.1, hard_for=-0.1,
                 restart_seen=False)
    pos, _dur = shim.get_position()
    assert pos == 180.0
    assert shim._seek_target_s is None


def test_no_hold_passes_engine_position_through():
    shim = _Shim(cached_pos=42.0, target=None)
    pos, dur = shim.get_position()
    assert (pos, dur) == (42.0, 240.0)
    assert shim.forced_refreshes == 0  # no seek -> normal cached refresh


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
