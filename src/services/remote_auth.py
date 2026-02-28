"""Remote-control secret storage helpers."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def load_secret(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_secret(path: str, data: dict) -> dict:
    payload = dict(data or {})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(temp_path, path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return payload


def ensure_secret(path: str, regenerate: bool = False) -> dict:
    payload = load_secret(path)
    key = str(payload.get("api_key") or "").strip()
    if key and not regenerate:
        return payload

    now = _utc_now_iso()
    payload["api_key"] = generate_api_key()
    payload["last_rotated_at"] = now
    payload.setdefault("created_at", now)
    return save_secret(path, payload)
