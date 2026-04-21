"""GitHub release-based update check helpers."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any

from gi.repository import GLib

from core.executor import submit_daemon
from core.http_session import get_global_session

logger = logging.getLogger(__name__)

_RELEASES_URL = "https://api.github.com/repos/yelanxin/hiresTI/releases?per_page=20"
_RELEASES_PAGE_URL = "https://github.com/yelanxin/hiresTI/releases"
_CACHE_TTL_SECONDS = 12 * 60 * 60
_STAGE_RANK = {
    "alpha": 0,
    "beta": 1,
    "rc": 2,
    "stable": 3,
}


def _default_update_state(current_version: str = "") -> dict[str, Any]:
    return {
        "current_version": str(current_version or "").strip() or "dev",
        "latest_version": "",
        "latest_name": "",
        "latest_url": _RELEASES_PAGE_URL,
        "latest_published_at": "",
        "latest_notes": "",
        "update_available": False,
        "last_checked_at": 0,
        "error": "",
    }


def _coerce_text(value: Any) -> str:
    return str(value or "").strip()


def _extract_release_notes(body: Any, max_lines: int = 6, max_chars: int = 520) -> str:
    lines = []
    for raw in str(body or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        if line.startswith(("-", "*")):
            line = line[1:].strip()
        if not line:
            continue
        lines.append(line)
        if len(lines) >= max_lines:
            break
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def _format_iso_date(value: Any) -> str:
    text = _coerce_text(value)
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return text


def parse_version(value: Any) -> dict[str, Any] | None:
    text = _coerce_text(value)
    if not text:
        return None
    compact = text.lower().replace(" ", "").replace("_", "-")
    compact = compact.lstrip("v")
    match = re.search(r"(\d+)(?:[.\-]?(\d+))?(?:[.\-]?(\d+))?", compact)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    remainder = compact[match.end():]
    stage = "stable"
    stage_num = 0
    stage_match = re.search(r"(alpha|a|beta|b|rc|pre|preview)[.\-]?(\d+)?", remainder)
    if stage_match:
        raw_stage = stage_match.group(1)
        if raw_stage in ("a", "alpha"):
            stage = "alpha"
        elif raw_stage in ("b", "beta"):
            stage = "beta"
        elif raw_stage in ("pre", "preview", "rc"):
            stage = "rc"
        stage_num = int(stage_match.group(2) or 0)
    normalized = f"{major}.{minor}.{patch}"
    if stage != "stable":
        normalized = f"{normalized}-{stage}{stage_num or 0}"
    return {
        "text": text,
        "normalized": normalized,
        "major": major,
        "minor": minor,
        "patch": patch,
        "stage": stage,
        "stage_num": stage_num,
        "is_prerelease": stage != "stable",
        "sort_key": (major, minor, patch, _STAGE_RANK[stage], stage_num),
    }


def _compute_update_available(current_version: str, latest_version: str) -> bool:
    parsed_current = parse_version(current_version)
    parsed_latest = parse_version(latest_version)
    if parsed_current is None or parsed_latest is None:
        return False
    if (not parsed_current["is_prerelease"]) and parsed_latest["is_prerelease"]:
        return False
    return parsed_latest["sort_key"] > parsed_current["sort_key"]


def init_update_check_state(app) -> None:
    settings = getattr(app, "settings", {}) or {}
    cached = settings.get("update_check") or {}
    state = _default_update_state(getattr(app, "app_version", "dev"))
    if isinstance(cached, dict):
        state["latest_version"] = _coerce_text(cached.get("latest_version"))
        state["latest_name"] = _coerce_text(cached.get("latest_name"))
        state["latest_url"] = _coerce_text(cached.get("latest_url")) or _RELEASES_PAGE_URL
        state["latest_published_at"] = _coerce_text(cached.get("latest_published_at"))
        state["latest_notes"] = _coerce_text(cached.get("latest_notes"))
        try:
            state["last_checked_at"] = int(cached.get("last_checked_at", 0) or 0)
        except Exception:
            state["last_checked_at"] = 0
        state["error"] = _coerce_text(cached.get("error"))
    state["update_available"] = _compute_update_available(
        state["current_version"],
        state["latest_version"],
    )
    app._update_check_state = state
    app._update_check_inflight = False
    app._update_check_source = 0


def _persist_update_state(app) -> None:
    settings = getattr(app, "settings", None)
    if not isinstance(settings, dict):
        return
    state = dict(getattr(app, "_update_check_state", {}) or {})
    settings["update_check"] = {
        "latest_version": _coerce_text(state.get("latest_version")),
        "latest_name": _coerce_text(state.get("latest_name")),
        "latest_url": _coerce_text(state.get("latest_url")) or _RELEASES_PAGE_URL,
        "latest_published_at": _coerce_text(state.get("latest_published_at")),
        "latest_notes": _coerce_text(state.get("latest_notes")),
        "last_checked_at": int(state.get("last_checked_at", 0) or 0),
        "error": _coerce_text(state.get("error")),
    }
    saver = getattr(app, "schedule_save_settings", None)
    if callable(saver):
        saver()


def _sync_update_widgets(app) -> None:
    try:
        from ui import builders as ui_builders

        ui_builders.refresh_update_widgets(app)
    except Exception:
        logger.debug("refresh_update_widgets failed", exc_info=True)


def _present_update_window(app) -> None:
    try:
        from ui import builders as ui_builders

        ui_builders.present_update_window(app)
    except Exception:
        logger.debug("present_update_window failed", exc_info=True)


def _is_cache_fresh(app, force: bool = False) -> bool:
    if force:
        return False
    state = getattr(app, "_update_check_state", {}) or {}
    try:
        last_checked = int(state.get("last_checked_at", 0) or 0)
    except Exception:
        last_checked = 0
    if last_checked <= 0:
        return False
    return (time.time() - last_checked) < _CACHE_TTL_SECONDS


def _select_latest_release(current_version: str, releases: list[dict[str, Any]]) -> dict[str, Any] | None:
    current = parse_version(current_version)
    if current is None:
        return None
    allow_prerelease = bool(current["is_prerelease"])
    selected = None
    selected_parsed = None
    for release in releases:
        if bool(release.get("draft")):
            continue
        if bool(release.get("prerelease")) and not allow_prerelease:
            continue
        version_text = _coerce_text(release.get("tag_name")) or _coerce_text(release.get("name"))
        parsed = parse_version(version_text)
        if parsed is None:
            continue
        if parsed["sort_key"] <= current["sort_key"]:
            continue
        if selected is None or parsed["sort_key"] > selected_parsed["sort_key"]:
            selected = release
            selected_parsed = parsed
    return selected


def _fetch_update_state(current_version: str) -> dict[str, Any]:
    state = _default_update_state(current_version)
    session = get_global_session()
    response = session.get(
        _RELEASES_URL,
        timeout=(4, 10),
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"HiresTI/{state['current_version']}",
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("Unexpected GitHub releases payload")
    latest = _select_latest_release(state["current_version"], payload)
    state["last_checked_at"] = int(time.time())
    if latest is None:
        state["error"] = ""
        return state
    version_text = _coerce_text(latest.get("tag_name")) or _coerce_text(latest.get("name"))
    state["latest_version"] = version_text
    state["latest_name"] = _coerce_text(latest.get("name")) or version_text
    state["latest_url"] = _coerce_text(latest.get("html_url")) or _RELEASES_PAGE_URL
    state["latest_published_at"] = _format_iso_date(latest.get("published_at"))
    state["latest_notes"] = _extract_release_notes(latest.get("body"))
    state["update_available"] = _compute_update_available(
        state["current_version"],
        state["latest_version"],
    )
    return state


def schedule_startup_update_check(app, delay_ms: int = 4200) -> None:
    pending = int(getattr(app, "_update_check_source", 0) or 0)
    if pending:
        GLib.source_remove(pending)
        app._update_check_source = 0

    def _run():
        app._update_check_source = 0
        check_for_updates_async(app, user_initiated=False, force=False, present_result=False)
        return False

    app._update_check_source = GLib.timeout_add(delay_ms, _run)


def check_for_updates_async(app, user_initiated: bool = False, force: bool = False, present_result: bool = False) -> bool:
    if bool(getattr(app, "_update_check_inflight", False)):
        if user_initiated and hasattr(app, "show_output_notice"):
            app.show_output_notice("Update check already in progress.", "info", 2200)
        return False

    if _is_cache_fresh(app, force=force):
        _sync_update_widgets(app)
        if present_result:
            GLib.idle_add(lambda: (_present_update_window(app), False)[1])
        return True

    app._update_check_inflight = True
    _sync_update_widgets(app)
    if user_initiated and hasattr(app, "show_output_notice"):
        app.show_output_notice("Checking GitHub releases...", "info", 2200)

    def _task():
        try:
            result = _fetch_update_state(getattr(app, "app_version", "dev"))
        except Exception as exc:
            logger.info("Update check failed: %s", exc)
            result = _default_update_state(getattr(app, "app_version", "dev"))
            old_state = getattr(app, "_update_check_state", {}) or {}
            if isinstance(old_state, dict):
                for key in ("latest_version", "latest_name", "latest_url", "latest_published_at", "latest_notes"):
                    result[key] = _coerce_text(old_state.get(key))
                result["update_available"] = _compute_update_available(
                    result["current_version"],
                    result["latest_version"],
                )
            result["last_checked_at"] = 0
            result["error"] = str(exc).strip() or "Update check failed"

        def _apply():
            app._update_check_inflight = False
            app._update_check_state = result
            _persist_update_state(app)
            _sync_update_widgets(app)
            if user_initiated:
                if result.get("error"):
                    notice = getattr(app, "show_output_notice", None)
                    if callable(notice):
                        notice("Update check failed.", "warn", 2600)
                elif bool(result.get("update_available")):
                    notice = getattr(app, "show_output_notice", None)
                    if callable(notice):
                        latest = _coerce_text(result.get("latest_version")) or "new version"
                        notice(f"Update available: {latest}", "ok", 2600)
                else:
                    notice = getattr(app, "show_output_notice", None)
                    if callable(notice):
                        notice("HiresTI is up to date.", "ok", 2200)
            if present_result:
                _present_update_window(app)
            return False

        GLib.idle_add(_apply)

    submit_daemon(_task)
    return True
