"""HTTP JSON-RPC remote-control service."""

from __future__ import annotations

import ipaddress
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from services.remote_dispatch import RemoteDispatchError, dispatch_rpc

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


class _RemoteHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host, port, app, api_key, allowed_cidrs):
        self.app = app
        self.api_key = str(api_key or "")
        self.allowed_cidrs = list(allowed_cidrs or [])
        super().__init__((host, int(port)), _RemoteRequestHandler)


class _RemoteRequestHandler(BaseHTTPRequestHandler):
    server_version = "HiresTIRemoteAPI/1.0"

    def log_message(self, fmt, *args):
        logger.debug("Remote API %s - %s", self.address_string(), fmt % args)

    def _write_json(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(int(status_code))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_empty(self, status_code):
        self.send_response(int(status_code))
        self.send_header("Content-Length", "0")
        self.end_headers()

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

    def do_GET(self):
        if self.path.rstrip("/") != "/health":
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
        if self.path.rstrip("/") != "/rpc":
            self._write_json(404, {"error": "not_found"})
            return
        if not self._check_access():
            return

        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        if length <= 0:
            self._write_json(400, {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Empty request."}, "id": None})
            return

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._write_json(400, {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error."}, "id": None})
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
            httpd.shutdown()
        finally:
            try:
                httpd.server_close()
            except Exception:
                pass
        if thread is not None:
            thread.join(timeout=2.0)
