from types import SimpleNamespace

from tidal_backend import TidalBackend


def test_normalize_oauth_url_adds_https_for_tidal_link():
    backend = TidalBackend()
    normalized, changed = backend._normalize_oauth_url("link.tidal.com/EWTHR")
    assert normalized == "https://link.tidal.com/EWTHR"
    assert changed is True


def test_start_oauth_returns_structured_context(monkeypatch):
    fake_obj = SimpleNamespace(
        verification_uri_complete="link.tidal.com/TRIKC",
        verification_uri="https://link.tidal.com",
        user_code="TRIKC",
    )
    fake_future = object()

    class FakeSession:
        def __init__(self):
            self.config = SimpleNamespace()

        def login_oauth(self):
            return fake_obj, fake_future

    monkeypatch.setattr("tidal_backend.tidalapi.Session", FakeSession)

    backend = TidalBackend()
    ctx = backend.start_oauth()
    assert ctx["url"] == "https://link.tidal.com/TRIKC"
    assert ctx["future"] is fake_future
    assert ctx["user_code"] == "TRIKC"
    assert ctx["normalized"] is True
