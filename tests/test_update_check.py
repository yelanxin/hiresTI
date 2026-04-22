import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_parse_version_supports_beta_and_stable_formats():
    pytest.importorskip("gi")
    from services import update_check as mod

    parsed_beta = mod.parse_version("1.9.0 Beta 4")
    parsed_stable = mod.parse_version("v1.9.0")
    parsed_legacy = mod.parse_version("1.9.0beta1.1")

    assert parsed_beta["normalized"] == "1.9.0-beta4"
    assert parsed_beta["is_prerelease"] is True
    assert parsed_stable["normalized"] == "1.9.0"
    assert parsed_stable["is_prerelease"] is False
    assert parsed_legacy["stage"] == "beta"
    assert parsed_legacy["stage_num"] == 1
    assert parsed_legacy["stage_parts"] == (1, 1)
    assert parsed_legacy["normalized"] == "1.9.0-beta1.1"


def test_compute_update_available_supports_prerelease_point_releases():
    pytest.importorskip("gi")
    from services import update_check as mod

    assert mod._compute_update_available("1.9.0 Beta 4", "v1.9.0-beta4.1") is True
    assert mod._compute_update_available("1.9.0beta1.1", "1.9.0beta1.2") is True
    assert mod._compute_update_available("1.9.0beta4.1", "v1.9.0-beta4") is False


def test_fetch_update_state_ignores_prerelease_for_stable_build(monkeypatch):
    pytest.importorskip("gi")
    from services import update_check as mod

    payload = [
        {
            "tag_name": "v1.9.1-beta1",
            "name": "1.9.1 Beta 1",
            "html_url": "https://example.invalid/beta",
            "published_at": "2026-04-20T12:00:00Z",
            "prerelease": True,
            "draft": False,
            "body": "Beta notes",
        }
    ]

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class _Session:
        def get(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr(mod, "get_global_session", lambda: _Session())

    state = mod._fetch_update_state("1.9.0")

    assert state["update_available"] is False
    assert state["latest_version"] == ""


def test_init_update_check_state_recomputes_cached_beta_visibility():
    pytest.importorskip("gi")
    from services import update_check as mod

    app = SimpleNamespace(
        app_version="1.9.0",
        settings={
            "update_check": {
                "latest_version": "1.9.1-beta1",
                "latest_name": "1.9.1 Beta 1",
                "latest_url": "https://example.invalid/beta",
                "last_checked_at": 123,
            }
        },
    )

    mod.init_update_check_state(app)

    assert app._update_check_state["current_version"] == "1.9.0"
    assert app._update_check_state["latest_version"] == "1.9.1-beta1"
    assert app._update_check_state["update_available"] is False
