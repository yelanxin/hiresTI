import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.remote_mcp import MCP_PROTOCOL_VERSION, handle_mcp_request


def test_handle_mcp_initialize_returns_server_info():
    response = handle_mcp_request(
        lambda method, params=None: {"method": method, "params": params},
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )

    assert response["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert response["result"]["serverInfo"]["name"] == "hiresTI Remote MCP"
    assert response["result"]["capabilities"]["tools"]["listChanged"] is False


def test_handle_mcp_tools_call_returns_structured_content():
    calls = []

    def _rpc_call(method, params=None):
        calls.append((method, params))
        return {"queue_size": 3, "ok": True}

    response = handle_mcp_request(
        _rpc_call,
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "queue_get",
                "arguments": {},
            },
        },
    )

    assert calls == [("queue.get", {})]
    assert response["result"]["structuredContent"]["queue_size"] == 3
    assert '"queue_size": 3' in response["result"]["content"][0]["text"]


def test_handle_mcp_notification_returns_no_response():
    response = handle_mcp_request(
        lambda method, params=None: {"ok": True},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    )

    assert response is None
