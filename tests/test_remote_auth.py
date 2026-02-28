import os
import stat
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services import remote_auth


def test_ensure_secret_creates_and_persists_api_key(tmp_path):
    path = tmp_path / "remote_api_secret.json"

    first = remote_auth.ensure_secret(str(path))
    second = remote_auth.ensure_secret(str(path))

    assert first["api_key"]
    assert second["api_key"] == first["api_key"]
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_ensure_secret_regenerate_rotates_key(tmp_path):
    path = tmp_path / "remote_api_secret.json"

    first = remote_auth.ensure_secret(str(path))
    second = remote_auth.ensure_secret(str(path), regenerate=True)

    assert first["api_key"] != second["api_key"]
    assert second["created_at"]
    assert second["last_rotated_at"]
