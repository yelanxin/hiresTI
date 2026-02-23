from __future__ import annotations


def classify_exception(exc: Exception) -> str:
    text = str(exc).lower()
    if any(k in text for k in ("401", "403", "unauthorized", "forbidden", "login", "session expired", "token")):
        return "auth"
    if any(k in text for k in ("500", "502", "503", "504", "internal server error", "bad gateway", "service unavailable")):
        return "server"
    if any(k in text for k in ("timeout", "timed out", "connection", "network", "dns", "unreachable")):
        return "network"
    if any(k in text for k in ("404", "not found", "no such")):
        return "not_found"
    if any(k in text for k in ("busy", "in use", "resource busy")):
        return "busy"
    if any(k in text for k in ("json", "decode", "parse", "invalid")):
        return "parse"
    return "unknown"


def user_message(kind: str, context: str = "general") -> str:
    if context == "search":
        mapping = {
            "auth": "Search unavailable. Please login again.",
            "server": "Search temporarily unavailable on server side. Please retry.",
            "network": "Search failed due to network issue. Please retry.",
            "not_found": "No matching results found.",
            "parse": "Search response format error. Please retry.",
            "unknown": "Search failed. Please retry.",
        }
        return mapping.get(kind, mapping["unknown"])

    if context == "playback":
        mapping = {
            "auth": "Playback unavailable. Please login again.",
            "server": "Playback service is busy on server side. Please retry shortly.",
            "network": "Playback failed due to network issue.",
            "busy": "Output device is busy. Try another device.",
            "not_found": "Track stream is unavailable.",
            "unknown": "Playback failed. Please retry.",
        }
        return mapping.get(kind, mapping["unknown"])

    if context == "lyrics":
        mapping = {
            "auth": "Lyrics unavailable. Please login again.",
            "server": "Lyrics service is temporarily unavailable.",
            "network": "Lyrics request timed out. Please retry.",
            "not_found": "No lyrics available for this track.",
            "parse": "Lyrics format is not supported.",
            "unknown": "Lyrics unavailable right now.",
        }
        return mapping.get(kind, mapping["unknown"])

    return "Operation failed. Please retry."
