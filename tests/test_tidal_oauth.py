import os
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


def test_invalid_ca_bundle_env_is_replaced_with_valid_path(monkeypatch):
    fake_obj = SimpleNamespace(
        verification_uri_complete="https://link.tidal.com/TRIKC",
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
    monkeypatch.setattr("tidal_backend.os.path.isfile", lambda p: p == "/tmp/fake-ca.pem")
    monkeypatch.setattr(
        "tidal_backend.TidalBackend._default_ca_bundle_candidates",
        lambda self: ["/tmp/fake-ca.pem"],
    )
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem")

    backend = TidalBackend()
    backend.start_oauth()
    assert backend is not None
    assert os.environ["REQUESTS_CA_BUNDLE"] == "/tmp/fake-ca.pem"
