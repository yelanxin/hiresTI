import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app_auth


def test_build_qr_tempfile_prefers_svg_when_available(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(app_auth.GLib, "get_tmp_dir", lambda: tmpdir)
        monkeypatch.setattr(app_auth, "_build_qr_svg", lambda url, path: _write_file(path, "<svg/>"))
        monkeypatch.setattr(app_auth, "_build_qr_png", lambda url, path: False)
        monkeypatch.setattr(app_auth, "_build_qr_with_qrencode", lambda url, path: False)

        path = app_auth._build_qr_tempfile(object(), "https://link.tidal.com/abc", 42)

        assert path == os.path.join(tmpdir, "hiresti-login-qr-42.svg")
        assert os.path.exists(path)


def test_build_qr_tempfile_falls_back_to_qrencode(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(app_auth.GLib, "get_tmp_dir", lambda: tmpdir)
        monkeypatch.setattr(app_auth, "_build_qr_svg", lambda url, path: False)
        monkeypatch.setattr(app_auth, "_build_qr_png", lambda url, path: False)
        monkeypatch.setattr(
            app_auth,
            "_build_qr_with_qrencode",
            lambda url, path: _write_file(path, "png"),
        )

        path = app_auth._build_qr_tempfile(object(), "https://link.tidal.com/abc", 43)

        assert path == os.path.join(tmpdir, "hiresti-login-qr-43.png")
        assert os.path.exists(path)


def test_build_qr_tempfile_returns_none_when_all_generators_fail(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(app_auth.GLib, "get_tmp_dir", lambda: tmpdir)
        monkeypatch.setattr(app_auth, "_build_qr_svg", lambda url, path: False)
        monkeypatch.setattr(app_auth, "_build_qr_png", lambda url, path: False)
        monkeypatch.setattr(app_auth, "_build_qr_with_qrencode", lambda url, path: False)

        path = app_auth._build_qr_tempfile(object(), "https://link.tidal.com/abc", 44)

        assert path is None


def _write_file(path, content):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return True
