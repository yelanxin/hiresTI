import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.remote_api import _dispatch_mcp_http_request, _mcp_origin_allowed


def test_mcp_origin_allowed_requires_exact_host_match():
    assert _mcp_origin_allowed({"Host": "127.0.0.1:18473"}, server_host="127.0.0.1:18473") is True
    assert _mcp_origin_allowed(
        {"Host": "127.0.0.1:18473", "Origin": "http://127.0.0.1:18473"},
        server_host="127.0.0.1:18473",
    ) is True
    assert _mcp_origin_allowed(
        {"Host": "127.0.0.1:18473", "Origin": "http://evil.example"},
        server_host="127.0.0.1:18473",
    ) is False


def test_dispatch_mcp_http_request_initialize_returns_response():
    app = SimpleNamespace()

    status, payload = _dispatch_mcp_http_request(
        app,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )

    assert status == 200
    assert payload["result"]["serverInfo"]["name"] == "hiresTI Remote MCP"


def test_dispatch_mcp_http_request_notification_returns_accepted():
    app = SimpleNamespace()

    status, payload = _dispatch_mcp_http_request(
        app,
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    )

    assert status == 202
    assert payload is None
