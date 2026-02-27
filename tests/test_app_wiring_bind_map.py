import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app_wiring


def test_bind_map_warns_on_duplicate_key(caplog):
    class _C:
        pass

    seen = set()
    with caplog.at_level("WARNING"):
        app_wiring._bind_map(_C, {"foo": lambda self: 1}, seen=seen)
        app_wiring._bind_map(_C, {"foo": lambda self: 2}, seen=seen)

    assert any("Duplicate wiring target detected: foo" in r.message for r in caplog.records)


def test_bind_map_warns_on_duplicate_key_in_same_block(caplog):
    class _C:
        pass

    with caplog.at_level("WARNING"):
        app_wiring._bind_map(_C, [("foo", lambda self: 1), ("foo", lambda self: 2)])

    assert any("Duplicate wiring target detected in block: foo" in r.message for r in caplog.records)
