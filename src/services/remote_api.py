"""HTTP JSON-RPC remote-control service."""

from __future__ import annotations

import ipaddress
import json
import logging
import queue
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from services.remote_dispatch import RemoteDispatchError, dispatch_rpc
from services.remote_mcp import MCP_PROTOCOL_VERSION, handle_mcp_request

logger = logging.getLogger(__name__)


def parse_allowed_cidrs(values):
    items = []
    raw_values = values if isinstance(values, list) else [values]
    for raw in raw_values:
        if raw is None:
            continue
        if isinstance(raw, str):
            chunks = raw.split(",")
        else:
            chunks = [str(raw)]
        for chunk in chunks:
            text = str(chunk or "").strip()
            if not text:
                continue
            items.append(str(ipaddress.ip_network(text, strict=False)))
    return items


def _client_allowed(client_ip: str, allowed_cidrs) -> bool:
    if not allowed_cidrs:
        return True
    try:
        addr = ipaddress.ip_address(str(client_ip or "").strip())
    except ValueError:
        return False
    for cidr in allowed_cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def _bearer_token(headers) -> str:
    auth = str(headers.get("Authorization", "") or "").strip()
    if not auth.lower().startswith("bearer "):
        return ""
    return auth[7:].strip()


def _mcp_origin_allowed(headers, server_host="") -> bool:
    origin = str(headers.get("Origin", "") or "").strip()
    if not origin:
        return True
    parsed = urlsplit(origin)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    request_host = str(headers.get("Host", "") or "").strip().lower()
    if request_host:
        return parsed.netloc.lower() == request_host
    fallback_host = str(server_host or "").strip().lower()
    if not fallback_host:
        return False
    origin_host = str(parsed.hostname or "").strip().lower()
    server_hostname = fallback_host.split(":", 1)[0]
    return bool(origin_host) and origin_host == server_hostname


def _dispatch_mcp_http_request(app, payload):
    if not isinstance(payload, dict):
        return 400, {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid request."}, "id": None}

    try:
        response = handle_mcp_request(
            lambda method, params=None: dispatch_rpc(app, method, params),
            payload,
        )
    except Exception:
        logger.exception("MCP request failed")
        return 500, {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Internal error."}, "id": payload.get("id")}

    if response is None:
        return 202, None
    return 200, response


class _RemoteHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host, port, app, api_key, allowed_cidrs):
        self.app = app
        self.api_key = str(api_key or "")
        self.allowed_cidrs = list(allowed_cidrs or [])
        self._active_handlers = set()
        self._active_handlers_lock = threading.Lock()
        super().__init__((host, int(port)), _RemoteRequestHandler)

    def register_handler(self, handler):
        with self._active_handlers_lock:
            self._active_handlers.add(handler)

    def unregister_handler(self, handler):
        with self._active_handlers_lock:
            self._active_handlers.discard(handler)

    def close_active_connections(self):
        with self._active_handlers_lock:
            handlers = list(self._active_handlers)
        for handler in handlers:
            conn = getattr(handler, "connection", None)
            if conn is None:
                continue
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass


class _RemoteRequestHandler(BaseHTTPRequestHandler):
    server_version = "HiresTIRemoteAPI/1.0"

    def setup(self):
        super().setup()
        server = getattr(self, "server", None)
        if server is not None and hasattr(server, "register_handler"):
            try:
                server.register_handler(self)
            except Exception:
                pass

    def finish(self):
        try:
            super().finish()
        finally:
            server = getattr(self, "server", None)
            if server is not None and hasattr(server, "unregister_handler"):
                try:
                    server.unregister_handler(self)
                except Exception:
                    pass

    def log_message(self, fmt, *args):
        logger.debug("Remote API %s - %s", self.address_string(), fmt % args)

    def _write_json(self, status_code, payload, extra_headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(int(status_code))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in dict(extra_headers or {}).items():
            self.send_header(str(key), str(value))
        self.end_headers()
        self.wfile.write(body)

    def _write_empty(self, status_code, extra_headers=None):
        self.send_response(int(status_code))
        self.send_header("Content-Length", "0")
        for key, value in dict(extra_headers or {}).items():
            self.send_header(str(key), str(value))
        self.end_headers()

    def _write_sse(self, event_name, payload, event_id=None):
        chunks = []
        if event_id is not None:
            chunks.append(f"id: {event_id}\n")
        if event_name:
            chunks.append(f"event: {event_name}\n")
        body = json.dumps(payload if isinstance(payload, dict) else {})
        for line in body.splitlines() or ["{}"]:
            chunks.append(f"data: {line}\n")
        chunks.append("\n")
        self.wfile.write("".join(chunks).encode("utf-8"))
        self.wfile.flush()

    def _request_path(self):
        return urlsplit(self.path).path.rstrip("/") or "/"

    def _check_access(self):
        client_ip = self.client_address[0] if self.client_address else ""
        if not _client_allowed(client_ip, getattr(self.server, "allowed_cidrs", [])):
            self._write_json(403, {"error": "client_not_allowed"})
            return False
        token = _bearer_token(self.headers)
        if token != getattr(self.server, "api_key", ""):
            self._write_json(401, {"error": "invalid_api_key"})
            return False
        return True

    def _check_mcp_access(self):
        server_host = ""
        if getattr(self, "server", None) is not None:
            host, port = self.server.server_address[:2]
            server_host = f"{host}:{port}"
        if not _mcp_origin_allowed(self.headers, server_host=server_host):
            self._write_json(403, {"error": "origin_not_allowed"})
            return False
        return self._check_access()

    def do_GET(self):
        path = self._request_path()
        if path == "/mcp":
            if not self._check_mcp_access():
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("MCP-Protocol-Version", MCP_PROTOCOL_VERSION)
            self.end_headers()
            heartbeat = queue.Queue()
            last_keepalive = time.monotonic()
            try:
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        item = heartbeat.get(timeout=1.0)
                    except queue.Empty:
                        if (time.monotonic() - last_keepalive) >= 15.0:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                            last_keepalive = time.monotonic()
                        continue
                    if item is None:
                        break
                    if (time.monotonic() - last_keepalive) >= 15.0:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        last_keepalive = time.monotonic()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            return
        if path == "/events":
            if not self._check_access():
                return
            hub = getattr(getattr(self.server, "app", None), "_remote_event_hub", None)
            if hub is None or not hasattr(hub, "subscribe"):
                self._write_json(503, {"error": "event_stream_unavailable"})
                return
            subscription_id, event_queue = hub.subscribe()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            app = getattr(self.server, "app", None)
            self._write_sse(
                "ready",
                {
                    "ok": True,
                    "service": "hiresTI-remote-api",
                    "version": str(getattr(app, "app_version", "dev") or "dev"),
                },
                event_id="0",
            )
            try:
                last_keepalive = time.monotonic()
                while True:
                    try:
                        event = event_queue.get(timeout=15.0)
                    except queue.Empty:
                        if (time.monotonic() - last_keepalive) >= 15.0:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                            last_keepalive = time.monotonic()
                        continue
                    if event is None:
                        break
                    self._write_sse(
                        event.get("type", "message"),
                        event.get("payload", {}),
                        event_id=event.get("id"),
                    )
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                try:
                    hub.unsubscribe(subscription_id)
                except Exception:
                    pass
            return
        if path != "/health":
            self._write_json(404, {"error": "not_found"})
            return
        app = getattr(self.server, "app", None)
        payload = {
            "ok": True,
            "service": "hiresTI-remote-api",
            "version": str(getattr(app, "app_version", "dev") or "dev"),
        }
        self._write_json(200, payload)

    def do_POST(self):
        path = self._request_path()
        if path == "/mcp":
            if not self._check_mcp_access():
                return
        elif path != "/rpc":
            self._write_json(404, {"error": "not_found"})
            return
        elif not self._check_access():
            return

        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        if length <= 0:
            payload = {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Empty request."}, "id": None}
            if path == "/mcp":
                self._write_json(400, payload, extra_headers={"MCP-Protocol-Version": MCP_PROTOCOL_VERSION})
            else:
                self._write_json(400, payload)
            return

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            error = {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error."}, "id": None}
            if path == "/mcp":
                self._write_json(400, error, extra_headers={"MCP-Protocol-Version": MCP_PROTOCOL_VERSION})
            else:
                self._write_json(400, error)
            return

        if path == "/mcp":
            status_code, response = _dispatch_mcp_http_request(self.server.app, payload)
            headers = {"MCP-Protocol-Version": MCP_PROTOCOL_VERSION}
            if response is None:
                self._write_empty(status_code, extra_headers=headers)
            else:
                self._write_json(status_code, response, extra_headers=headers)
            return

        if not isinstance(payload, dict):
            self._write_json(400, {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Batch requests are not supported."}, "id": None})
            return

        req_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params")
        if payload.get("jsonrpc") != "2.0" or not isinstance(method, str) or not method.strip():
            self._write_json(400, {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid request."}, "id": req_id})
            return

        try:
            result = dispatch_rpc(self.server.app, method.strip(), params)
        except RemoteDispatchError as exc:
            error = {"code": exc.code, "message": exc.message}
            if exc.data is not None:
                error["data"] = exc.data
            self._write_json(400, {"jsonrpc": "2.0", "error": error, "id": req_id})
            return
        except Exception:
            logger.exception("Remote API method failed: %s", method)
            self._write_json(500, {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Internal error."}, "id": req_id})
            return

        if req_id is None:
            self._write_empty(204)
            return
        self._write_json(200, {"jsonrpc": "2.0", "result": result, "id": req_id})


class RemoteAPIService:
    def __init__(self, app, host: str, port: int, api_key: str, allowed_cidrs=None):
        self.app = app
        self.host = str(host or "127.0.0.1")
        self.port = int(port)
        self.api_key = str(api_key or "")
        self.allowed_cidrs = parse_allowed_cidrs(allowed_cidrs or [])
        self._httpd = None
        self._thread = None

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/rpc"

    @property
    def mcp_endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/mcp"

    def start(self):
        if self._httpd is not None:
            return
        self._httpd = _RemoteHTTPServer(
            self.host,
            self.port,
            self.app,
            self.api_key,
            self.allowed_cidrs,
        )
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": 0.2},
            daemon=True,
            name="hiresTI-remote-api",
        )
        self._thread.start()
        logger.info(
            "Remote API listening on %s:%s (allowlist=%s)",
            self.host,
            self.port,
            ",".join(self.allowed_cidrs) if self.allowed_cidrs else "*",
        )

    def stop(self):
        httpd = self._httpd
        thread = self._thread
        self._httpd = None
        self._thread = None
        if httpd is None:
            return
        try:
            hub = getattr(self.app, "_remote_event_hub", None)
            if hub is not None and hasattr(hub, "close_all"):
                hub.close_all()
            if hasattr(httpd, "close_active_connections"):
                httpd.close_active_connections()
            httpd.shutdown()
        finally:
            try:
                httpd.server_close()
            except Exception:
                pass
        if thread is not None:
            thread.join(timeout=2.0)
