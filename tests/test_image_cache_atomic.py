import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from utils import helpers


class _Response:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


def test_download_to_cache_replaces_zero_byte_file(tmp_path, monkeypatch):
    calls = []

    class _Session:
        def get(self, url, timeout=10, headers=None):
            calls.append((url, timeout, dict(headers or {})))
            return _Response(b"image-bytes")

    monkeypatch.setattr(helpers, "get_global_session", lambda: _Session())

    cache_dir = str(tmp_path)
    target = tmp_path / "cover.bin"
    target.write_bytes(b"")

    result = helpers.download_to_cache("https://example.test/cover.jpg", cache_dir, filename="cover.bin")

    assert result == str(target)
    assert target.read_bytes() == b"image-bytes"
    assert len(calls) == 1


def test_download_to_cache_serializes_same_target_downloads(tmp_path, monkeypatch):
    call_count = 0
    call_lock = threading.Lock()

    class _Session:
        def get(self, url, timeout=10, headers=None):
            nonlocal call_count
            with call_lock:
                call_count += 1
            time.sleep(0.1)
            return _Response(b"parallel-image")

    monkeypatch.setattr(helpers, "get_global_session", lambda: _Session())

    cache_dir = str(tmp_path)
    results = []
    errors = []

    def _worker():
        try:
            results.append(
                helpers.download_to_cache("https://example.test/shared.jpg", cache_dir, filename="shared.bin")
            )
        except Exception as exc:  # pragma: no cover - should stay empty
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    target = tmp_path / "shared.bin"
    assert errors == []
    assert results == [str(target), str(target)]
    assert target.read_bytes() == b"parallel-image"
    assert call_count == 1


def test_cover_crop_rect_biases_horizontal_crop_to_requested_edge():
    assert helpers._cover_crop_rect(1200, 800, 200, 800, anchor_x=1.0) == (1000, 0, 200, 800)
    assert helpers._cover_crop_rect(1200, 800, 200, 800, anchor_x=0.0) == (0, 0, 200, 800)
