import json
import os
import socket
import sys
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.remote_api import RemoteAPIService


def _post_json(url, payload, headers=None):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for key, value in dict(headers or {}).items():
        req.add_header(str(key), str(value))
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else None


def _discover_non_loopback_ipv4():
    candidates = []
    try:
        host_ip = socket.gethostbyname(socket.gethostname())
        candidates.append(host_ip)
    except Exception:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("198.51.100.1", 1))
            candidates.append(sock.getsockname()[0])
    except Exception:
        pass
    for ip in candidates:
        if ip and not ip.startswith("127."):
            return ip
    return None


def _open_mcp_stream(host, port, api_key):
    sock = socket.create_connection((host, int(port)), timeout=2.0)
    sock.settimeout(2.0)
    request = (
        f"GET /mcp HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Authorization: Bearer {api_key}\r\n"
        f"Accept: text/event-stream\r\n"
        f"Connection: keep-alive\r\n"
        f"\r\n"
    ).encode("utf-8")
    sock.sendall(request)
    data = sock.recv(4096)
    return sock, data


def test_remote_api_rejects_invalid_bearer_key():
    service = RemoteAPIService(
        SimpleNamespace(app_version="test"),
        host="127.0.0.1",
        port=0,
        api_key="expected-key",
    )
    service.start()
    try:
        status, payload = _post_json(
            service.endpoint,
            {"jsonrpc": "2.0", "id": 1, "method": "auth.status", "params": {}},
            headers={"Authorization": "Bearer wrong-key"},
        )
    finally:
        service.stop()

    assert status == 401
    assert payload == {"error": "invalid_api_key"}


def test_remote_api_rejects_disallowed_client_ip_before_auth():
    service = RemoteAPIService(
        SimpleNamespace(app_version="test"),
        host="127.0.0.1",
        port=0,
        api_key="expected-key",
        allowed_cidrs=["127.0.0.2/32"],
    )
    service.start()
    try:
        status, payload = _post_json(
            service.endpoint,
            {"jsonrpc": "2.0", "id": 1, "method": "auth.status", "params": {}},
            headers={"Authorization": "Bearer expected-key"},
        )
    finally:
        service.stop()

    assert status == 403
    assert payload == {"error": "client_not_allowed"}


def test_remote_api_bound_to_loopback_is_not_reachable_via_non_loopback_ip():
    service = RemoteAPIService(
        SimpleNamespace(app_version="test"),
        host="127.0.0.1",
        port=0,
        api_key="expected-key",
    )
    service.start()
    try:
        assert service._httpd.server_address[0] == "127.0.0.1"
        port = int(service.port)
        with socket.create_connection(("127.0.0.1", port), timeout=2.0):
            pass

        non_loopback_ip = _discover_non_loopback_ipv4()
        if not non_loopback_ip:
            pytest.skip("No non-loopback IPv4 address available in this environment")

        with pytest.raises(OSError):
            with socket.create_connection((non_loopback_ip, port), timeout=1.0):
                pass
    finally:
        service.stop()


def test_remote_api_rotated_key_takes_effect_immediately_after_restart():
    app = SimpleNamespace(app_version="test")
    service = RemoteAPIService(
        app,
        host="127.0.0.1",
        port=0,
        api_key="old-key",
    )
    service.start()
    port = int(service.port)
    try:
        status, payload = _post_json(
            service.endpoint,
            {"jsonrpc": "2.0", "id": 1, "method": "auth.status", "params": {}},
            headers={"Authorization": "Bearer old-key"},
        )
        assert status == 200
        assert "result" in payload
    finally:
        service.stop()

    rotated = RemoteAPIService(
        app,
        host="127.0.0.1",
        port=port,
        api_key="new-key",
    )
    rotated.start()
    try:
        old_status, old_payload = _post_json(
            rotated.endpoint,
            {"jsonrpc": "2.0", "id": 2, "method": "auth.status", "params": {}},
            headers={"Authorization": "Bearer old-key"},
        )
        new_status, new_payload = _post_json(
            rotated.endpoint,
            {"jsonrpc": "2.0", "id": 3, "method": "auth.status", "params": {}},
            headers={"Authorization": "Bearer new-key"},
        )
    finally:
        rotated.stop()

    assert old_status == 401
    assert old_payload == {"error": "invalid_api_key"}
    assert new_status == 200
    assert "result" in new_payload


def test_remote_api_stop_closes_active_mcp_stream():
    service = RemoteAPIService(
        SimpleNamespace(app_version="test"),
        host="127.0.0.1",
        port=0,
        api_key="expected-key",
    )
    service.start()
    sock, initial = _open_mcp_stream("127.0.0.1", service.port, "expected-key")
    try:
        decoded = initial.decode("utf-8", errors="replace")
        assert "200 OK" in decoded
        if ": connected" not in decoded:
            decoded += sock.recv(4096).decode("utf-8", errors="replace")
        assert ": connected" in decoded

        service.stop()

        sock.settimeout(2.0)
        with pytest.raises((ConnectionResetError, OSError)):
            more = sock.recv(4096)
            if more == b"":
                raise OSError("stream closed")
    finally:
        try:
            sock.close()
        except Exception:
            pass
        try:
            service.stop()
        except Exception:
            pass
