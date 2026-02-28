"""Minimal MCP stdio adapter that forwards to the remote JSON-RPC API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


TOOLS = [
    {
        "name": "player_get_state",
        "description": "Get the current playback state and active queue.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "rpcMethod": "player.get_state",
    },
    {
        "name": "player_play",
        "description": "Start playback of the current queue.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "rpcMethod": "player.play",
    },
    {
        "name": "player_pause",
        "description": "Pause playback.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "rpcMethod": "player.pause",
    },
    {
        "name": "player_next",
        "description": "Skip to the next track.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "rpcMethod": "player.next",
    },
    {
        "name": "queue_get",
        "description": "Return the active playback queue.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "rpcMethod": "queue.get",
    },
    {
        "name": "queue_replace_with_track_ids",
        "description": "Replace the playback queue with TIDAL track IDs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "track_ids": {"type": "array", "items": {"type": "string"}},
                "autoplay": {"type": "boolean"},
                "start_index": {"type": "integer"},
            },
            "required": ["track_ids"],
            "additionalProperties": False,
        },
        "rpcMethod": "queue.replace_with_track_ids",
    },
    {
        "name": "search_match_tracks",
        "description": "Match structured title/artist candidates to playable TIDAL track IDs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "artist": {"type": "string"},
                            "album": {"type": "string"},
                        },
                        "required": ["title"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        },
        "rpcMethod": "search.match_tracks",
    },
]


def _tool_map():
    return {item["name"]: item for item in TOOLS}


class RemoteRPCClient:
    def __init__(self, endpoint: str, api_key: str, timeout: float = 10.0):
        self.endpoint = str(endpoint or "").strip()
        self.api_key = str(api_key or "").strip()
        self.timeout = float(timeout or 10.0)
        self._req_id = 0

    def call(self, method: str, params=None):
        self._req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params or {},
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(raw or f"HTTP {exc.code}") from exc
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc
        if "error" in data:
            err = data["error"]
            raise RuntimeError(f'{err.get("code")}: {err.get("message")}')
        return data.get("result")


def _read_message(stream):
    headers = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        key, _, value = line.decode("utf-8").partition(":")
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0") or "0")
    if length <= 0:
        return None
    payload = stream.read(length)
    if not payload:
        return None
    return json.loads(payload.decode("utf-8"))


def _write_message(stream, payload):
    body = json.dumps(payload).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
    stream.write(header)
    stream.write(body)
    stream.flush()


def _jsonrpc_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _handle_request(client: RemoteRPCClient, request: dict):
    req_id = request.get("id")
    method = str(request.get("method", "") or "")
    params = request.get("params") or {}
    if method == "initialize":
        return _jsonrpc_result(
            req_id,
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "hiresTI Remote MCP", "version": "1.0"},
            },
        )
    if method == "tools/list":
        tools = [{k: v for k, v in item.items() if k != "rpcMethod"} for item in TOOLS]
        return _jsonrpc_result(req_id, {"tools": tools})
    if method == "tools/call":
        tool_name = str(params.get("name", "") or "")
        tool = _tool_map().get(tool_name)
        if tool is None:
            return _jsonrpc_error(req_id, -32601, f"Unknown tool: {tool_name}")
        arguments = params.get("arguments") or {}
        try:
            result = client.call(tool["rpcMethod"], arguments)
        except Exception as exc:
            return _jsonrpc_result(
                req_id,
                {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            )
        return _jsonrpc_result(
            req_id,
            {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
            },
        )
    if method == "ping":
        return _jsonrpc_result(req_id, {})
    if req_id is None:
        return None
    return _jsonrpc_error(req_id, -32601, f"Unknown method: {method}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="hiresTI MCP bridge")
    parser.add_argument("--endpoint", required=True, help="Remote JSON-RPC endpoint, e.g. http://192.168.1.10:18473/rpc")
    parser.add_argument("--api-key", required=True, help="Bearer API key for the remote JSON-RPC endpoint")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)

    client = RemoteRPCClient(args.endpoint, args.api_key, timeout=args.timeout)
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        request = _read_message(stdin)
        if request is None:
            break
        response = _handle_request(client, request)
        if response is not None:
            _write_message(stdout, response)


if __name__ == "__main__":
    main()
