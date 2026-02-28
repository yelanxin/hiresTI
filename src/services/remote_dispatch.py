"""Remote-control JSON-RPC dispatch helpers."""

from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher


class RemoteDispatchError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code = int(code)
        self.message = str(message)
        self.data = data


def _invoke_on_main(app, fn, *args, **kwargs):
    invoker = getattr(app, "_remote_invoke_on_main", None)
    if callable(invoker):
        return invoker(fn, *args, **kwargs)
    return fn(*args, **kwargs)


def _norm_text(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    for token in ('"', "'", ".", ",", "-", "_", "/", "(", ")", "[", "]", "{", "}", ":", ";"):
        text = text.replace(token, " ")
    return re.sub(r"\s+", " ", text).strip()


def _score_field(query: str, candidate: str) -> int:
    if not query or not candidate:
        return 0
    if query == candidate:
        return 100
    if candidate.startswith(query):
        return 84
    if query in candidate:
        return 72
    ratio = SequenceMatcher(None, query, candidate).ratio()
    if ratio >= 0.94:
        return 88
    if ratio >= 0.86:
        return 72
    if ratio >= 0.78:
        return 56
    return 0


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value, default=0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _track_title(track) -> str:
    return str(getattr(track, "name", "") or getattr(track, "title", "") or "Unknown Track")


def _track_artist_name(track) -> str:
    artist = getattr(track, "artist", None)
    return str(getattr(artist, "name", "") or "")


def _track_album_name(track) -> str:
    album = getattr(track, "album", None)
    return str(getattr(album, "name", "") or getattr(album, "title", "") or "")


def _serialize_track(track):
    if track is None:
        return None
    album = getattr(track, "album", None)
    artist = getattr(track, "artist", None)
    return {
        "id": str(getattr(track, "id", "") or ""),
        "title": _track_title(track),
        "artist": _track_artist_name(track),
        "album": _track_album_name(track),
        "duration_seconds": int(getattr(track, "duration", 0) or 0),
        "artist_id": str(getattr(artist, "id", "") or "") if artist is not None else "",
        "album_id": str(getattr(album, "id", "") or "") if album is not None else "",
        "cover": str(getattr(track, "cover", "") or getattr(album, "cover", "") or ""),
    }


def _queue_snapshot(app):
    queue = list(app._get_active_queue() if hasattr(app, "_get_active_queue") else (getattr(app, "play_queue", []) or []))
    current_index = _safe_int(
        getattr(app, "current_track_index", getattr(app, "current_index", -1)),
        -1,
    )
    return {
        "queue": queue,
        "current_index": current_index,
        "playing_track": getattr(app, "playing_track", None),
        "playing_track_id": str(getattr(app, "playing_track_id", "") or ""),
    }


def _play_mode_name(app) -> str:
    mode = _safe_int(getattr(app, "play_mode", 0), 0)
    mapping = {
        getattr(app, "MODE_LOOP", 0): "loop",
        getattr(app, "MODE_ONE", 1): "one",
        getattr(app, "MODE_SHUFFLE", 2): "shuffle",
        getattr(app, "MODE_SMART", 3): "smart",
    }
    return mapping.get(mode, str(mode))


def _player_state_snapshot(app):
    player = getattr(app, "player", None)
    is_playing = False
    position = 0.0
    duration = 0.0
    if player is not None:
        try:
            is_playing = bool(player.is_playing())
        except Exception:
            is_playing = False
        try:
            position, duration = player.get_position()
        except Exception:
            position = 0.0
            duration = 0.0
    queue_state = _queue_snapshot(app)
    current_track = queue_state["playing_track"]
    if current_track is None and 0 <= queue_state["current_index"] < len(queue_state["queue"]):
        current_track = queue_state["queue"][queue_state["current_index"]]
    return {
        "is_playing": is_playing,
        "position_seconds": round(_safe_float(position, 0.0), 3),
        "duration_seconds": round(_safe_float(duration, 0.0), 3),
        "volume_percent": _safe_int(getattr(app, "settings", {}).get("volume", 0), 0),
        "play_mode": _play_mode_name(app),
        "current_index": queue_state["current_index"],
        "queue_size": len(queue_state["queue"]),
        "track": _serialize_track(current_track),
        "queue": [_serialize_track(track) for track in queue_state["queue"]],
    }


def queue_public_snapshot(app):
    queue_state = _queue_snapshot(app)
    return {
        "current_index": queue_state["current_index"],
        "queue_size": len(queue_state["queue"]),
        "tracks": [_serialize_track(track) for track in queue_state["queue"]],
    }


def player_state_snapshot(app):
    return _player_state_snapshot(app)


def _require_dict_params(params):
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise RemoteDispatchError(-32602, "Params must be an object.")
    return params


def _get_login_state(app) -> bool:
    backend = getattr(app, "backend", None)
    session = getattr(backend, "session", None)
    if session is None:
        return False
    try:
        return bool(session.check_login())
    except Exception:
        return False


def _require_logged_in(app):
    if not _get_login_state(app):
        raise RemoteDispatchError(-32010, "TIDAL login required.")


def _resolve_tracks_by_ids(app, track_ids):
    backend = getattr(app, "backend", None)
    session = getattr(backend, "session", None)
    if session is None:
        raise RemoteDispatchError(-32030, "Playback backend unavailable.")
    _require_logged_in(app)
    tracks = []
    missing = []
    for raw_id in track_ids:
        track_id = str(raw_id or "").strip()
        if not track_id:
            continue
        try:
            tracks.append(session.track(track_id))
        except Exception:
            missing.append(track_id)
    return tracks, missing


def _rpc_ping(app, _params):
    return {
        "ok": True,
        "app": "hiresTI",
        "version": str(getattr(app, "app_version", "dev") or "dev"),
        "logged_in": _get_login_state(app),
    }


def _rpc_auth_status(app, _params):
    return {
        "logged_in": _get_login_state(app),
        "remote_control_enabled": bool(getattr(app, "settings", {}).get("remote_api_enabled", False)),
        "access_mode": str(getattr(app, "settings", {}).get("remote_api_access_mode", "local") or "local"),
        "endpoint": getattr(app, "get_remote_api_endpoint", lambda: "")(),
        "mcp_endpoint": getattr(app, "get_remote_mcp_endpoint", lambda: "")(),
    }


def _rpc_player_get_state(app, _params):
    return _invoke_on_main(app, player_state_snapshot, app)


def _do_player_play(app):
    player = getattr(app, "player", None)
    if player is None:
        raise RemoteDispatchError(-32030, "Playback backend unavailable.")
    queue = list(app._get_active_queue() if hasattr(app, "_get_active_queue") else [])
    current_index = _safe_int(getattr(app, "current_track_index", -1), -1)
    if player.is_playing():
        return _player_state_snapshot(app)
    if getattr(app, "playing_track_id", None):
        player.play()
        if getattr(app, "play_btn", None) is not None:
            app.play_btn.set_icon_name("media-playback-pause-symbolic")
        if hasattr(app, "_mpris_sync_playback"):
            app._mpris_sync_playback()
        if hasattr(app, "_mpris_sync_position"):
            app._mpris_sync_position(force=True)
        if hasattr(app, "_remote_publish_playback_event"):
            app._remote_publish_playback_event("resumed")
        return _player_state_snapshot(app)
    if not queue:
        raise RemoteDispatchError(-32020, "No track available to play.")
    if current_index < 0 or current_index >= len(queue):
        current_index = 0
    app.play_track(current_index)
    return _player_state_snapshot(app)


def _rpc_player_play(app, _params):
    return _invoke_on_main(app, _do_player_play, app)


def _rpc_player_pause(app, _params):
    def _pause():
        player = getattr(app, "player", None)
        if player is not None and player.is_playing():
            app.on_play_pause(None)
        return _player_state_snapshot(app)

    return _invoke_on_main(app, _pause)


def _rpc_player_play_pause(app, _params):
    def _play_pause():
        player = getattr(app, "player", None)
        queue = list(app._get_active_queue() if hasattr(app, "_get_active_queue") else [])
        if player is None:
            raise RemoteDispatchError(-32030, "Playback backend unavailable.")
        if not queue and not getattr(app, "playing_track_id", None):
            raise RemoteDispatchError(-32020, "No track available to toggle.")
        app.on_play_pause(None)
        return _player_state_snapshot(app)

    return _invoke_on_main(app, _play_pause)


def _rpc_player_next(app, _params):
    return _invoke_on_main(app, lambda: (app.on_next_track(None), _player_state_snapshot(app))[1])


def _rpc_player_previous(app, _params):
    return _invoke_on_main(app, lambda: (app.on_prev_track(None), _player_state_snapshot(app))[1])


def _rpc_player_stop(app, _params):
    def _stop():
        player = getattr(app, "player", None)
        if player is not None:
            player.stop()
        if getattr(app, "play_btn", None) is not None:
            app.play_btn.set_icon_name("media-playback-start-symbolic")
        if hasattr(app, "_mpris_sync_playback"):
            app._mpris_sync_playback()
        if hasattr(app, "_mpris_sync_position"):
            app._mpris_sync_position(force=True)
        if hasattr(app, "_remote_publish_playback_event"):
            app._remote_publish_playback_event("stopped")
        return _player_state_snapshot(app)

    return _invoke_on_main(app, _stop)


def _rpc_player_seek(app, params):
    payload = _require_dict_params(params)
    target = _safe_float(payload.get("position_seconds"), math.nan)
    if math.isnan(target) or target < 0:
        raise RemoteDispatchError(-32602, "position_seconds must be a non-negative number.")

    def _seek():
        player = getattr(app, "player", None)
        if player is None:
            raise RemoteDispatchError(-32030, "Playback backend unavailable.")
        player.seek(target)
        if hasattr(app, "_mpris_emit_seeked"):
            app._mpris_emit_seeked(float(target))
        if hasattr(app, "_mpris_sync_position"):
            app._mpris_sync_position(force=True)
        if hasattr(app, "_remote_publish_playback_event"):
            app._remote_publish_playback_event("seek")
        return _player_state_snapshot(app)

    return _invoke_on_main(app, _seek)


def _rpc_queue_get(app, _params):
    return _invoke_on_main(app, queue_public_snapshot, app)


def _rpc_queue_replace(app, params):
    payload = _require_dict_params(params)
    track_ids = payload.get("track_ids")
    if not isinstance(track_ids, list) or not track_ids:
        raise RemoteDispatchError(-32602, "track_ids must be a non-empty array.")
    autoplay = bool(payload.get("autoplay", True))
    start_index = _safe_int(payload.get("start_index"), 0)
    tracks, missing = _resolve_tracks_by_ids(app, track_ids)
    if not tracks:
        raise RemoteDispatchError(-32021, "No tracks could be resolved.", {"missing_ids": missing})
    result = _invoke_on_main(app, app._remote_replace_queue, tracks, autoplay, start_index)
    result["missing_ids"] = missing
    result["tracks"] = [_serialize_track(track) for track in tracks]
    return result


def _rpc_queue_append(app, params):
    payload = _require_dict_params(params)
    track_ids = payload.get("track_ids")
    if not isinstance(track_ids, list) or not track_ids:
        raise RemoteDispatchError(-32602, "track_ids must be a non-empty array.")
    tracks, missing = _resolve_tracks_by_ids(app, track_ids)
    if not tracks:
        raise RemoteDispatchError(-32021, "No tracks could be resolved.", {"missing_ids": missing})
    result = _invoke_on_main(app, app._remote_append_queue, tracks)
    result["missing_ids"] = missing
    result["tracks"] = [_serialize_track(track) for track in tracks]
    return result


def _rpc_queue_clear(app, _params):
    def _clear():
        app.on_queue_clear_clicked(None)
        return {
            "cleared": True,
            "queue_size": 0,
        }

    return _invoke_on_main(app, _clear)


def _rpc_queue_remove_index(app, params):
    payload = _require_dict_params(params)
    index = _safe_int(payload.get("index"), -1)
    if index < 0:
        raise RemoteDispatchError(-32602, "index must be >= 0.")

    def _remove():
        app.on_queue_remove_track_clicked(index)
        queue_state = _queue_snapshot(app)
        return {
            "removed_index": index,
            "queue_size": len(queue_state["queue"]),
            "current_index": queue_state["current_index"],
        }

    return _invoke_on_main(app, _remove)


def _rpc_queue_play_index(app, params):
    payload = _require_dict_params(params)
    index = _safe_int(payload.get("index"), -1)
    if index < 0:
        raise RemoteDispatchError(-32602, "index must be >= 0.")

    def _play_index():
        queue = list(app._get_active_queue() if hasattr(app, "_get_active_queue") else [])
        if index >= len(queue):
            raise RemoteDispatchError(-32602, "index is out of range.")
        app.play_track(index)
        return _player_state_snapshot(app)

    return _invoke_on_main(app, _play_index)


def _rpc_queue_move(app, params):
    payload = _require_dict_params(params)
    from_index = _safe_int(payload.get("from_index"), -1)
    to_index = _safe_int(payload.get("to_index"), -1)
    if from_index < 0 or to_index < 0:
        raise RemoteDispatchError(-32602, "from_index and to_index must be >= 0.")
    try:
        result = _invoke_on_main(app, app._remote_move_queue_item, from_index, to_index)
    except (IndexError, ValueError) as exc:
        raise RemoteDispatchError(-32602, str(exc)) from exc
    result["queue"] = queue_public_snapshot(app)
    return result


def _rpc_queue_insert_at(app, params):
    payload = _require_dict_params(params)
    index = _safe_int(payload.get("index"), -1)
    track_ids = payload.get("track_ids")
    if index < 0:
        raise RemoteDispatchError(-32602, "index must be >= 0.")
    if not isinstance(track_ids, list) or not track_ids:
        raise RemoteDispatchError(-32602, "track_ids must be a non-empty array.")
    tracks, missing = _resolve_tracks_by_ids(app, track_ids)
    if not tracks:
        raise RemoteDispatchError(-32021, "No tracks could be resolved.", {"missing_ids": missing})
    try:
        result = _invoke_on_main(app, app._remote_insert_queue_at, tracks, index)
    except (IndexError, ValueError) as exc:
        raise RemoteDispatchError(-32602, str(exc)) from exc
    result["missing_ids"] = missing
    result["tracks"] = [_serialize_track(track) for track in tracks]
    result["queue"] = queue_public_snapshot(app)
    return result


def _rpc_queue_insert_next(app, params):
    payload = _require_dict_params(params)
    track_ids = payload.get("track_ids")
    if not isinstance(track_ids, list) or not track_ids:
        raise RemoteDispatchError(-32602, "track_ids must be a non-empty array.")
    tracks, missing = _resolve_tracks_by_ids(app, track_ids)
    if not tracks:
        raise RemoteDispatchError(-32021, "No tracks could be resolved.", {"missing_ids": missing})
    try:
        result = _invoke_on_main(app, app._remote_insert_queue_next, tracks)
    except (IndexError, ValueError) as exc:
        raise RemoteDispatchError(-32602, str(exc)) from exc
    result["missing_ids"] = missing
    result["tracks"] = [_serialize_track(track) for track in tracks]
    result["queue"] = queue_public_snapshot(app)
    return result


def _match_score(item, track):
    title_q = _norm_text(item.get("title"))
    artist_q = _norm_text(item.get("artist"))
    album_q = _norm_text(item.get("album"))
    title_c = _norm_text(_track_title(track))
    artist_c = _norm_text(_track_artist_name(track))
    album_c = _norm_text(_track_album_name(track))
    title_score = _score_field(title_q, title_c)
    artist_score = _score_field(artist_q, artist_c)
    album_score = _score_field(album_q, album_c)
    total = (title_score * 1.7) + (artist_score * 1.15) + (album_score * 0.45)
    return {
        "score": round(total, 2),
        "title_score": title_score,
        "artist_score": artist_score,
        "album_score": album_score,
    }


def _rpc_search_match_tracks(app, params):
    payload = _require_dict_params(params)
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise RemoteDispatchError(-32602, "items must be a non-empty array.")

    backend = getattr(app, "backend", None)
    if backend is None:
        raise RemoteDispatchError(-32030, "Playback backend unavailable.")

    logged_in = _get_login_state(app)
    results = []
    for idx, raw_item in enumerate(items):
        item = raw_item if isinstance(raw_item, dict) else {}
        title = str(item.get("title", "") or "").strip()
        artist = str(item.get("artist", "") or "").strip()
        album = str(item.get("album", "") or "").strip()
        if not title:
            results.append(
                {
                    "input_index": idx,
                    "matched": False,
                    "confidence": 0.0,
                    "reason": "missing_title",
                    "track": None,
                }
            )
            continue
        if not logged_in:
            results.append(
                {
                    "input_index": idx,
                    "matched": False,
                    "confidence": 0.0,
                    "reason": "not_logged_in",
                    "track": None,
                }
            )
            continue

        query = " ".join(part for part in (title, artist) if part).strip()
        remote = backend.search_items(query)
        candidates = list(remote.get("tracks", []) or [])
        best_track = None
        best = {"score": 0.0, "title_score": 0, "artist_score": 0, "album_score": 0}
        for track in candidates:
            scored = _match_score(item, track)
            if scored["score"] > best["score"]:
                best = scored
                best_track = track

        matched = False
        if best_track is not None:
            if best["title_score"] >= 72 and (not artist or best["artist_score"] >= 56):
                matched = True
            elif best["score"] >= 155:
                matched = True

        confidence = min(1.0, round(float(best["score"]) / 200.0, 3))
        results.append(
            {
                "input_index": idx,
                "matched": matched,
                "confidence": confidence,
                "query": query,
                "track": _serialize_track(best_track) if matched else None,
                "best_candidate": _serialize_track(best_track),
                "score": best["score"],
            }
        )

    return {
        "logged_in": logged_in,
        "results": results,
        "matched_count": sum(1 for item in results if item.get("matched")),
    }


_METHODS = {
    "app.ping": _rpc_ping,
    "auth.status": _rpc_auth_status,
    "player.get_state": _rpc_player_get_state,
    "player.play": _rpc_player_play,
    "player.pause": _rpc_player_pause,
    "player.play_pause": _rpc_player_play_pause,
    "player.next": _rpc_player_next,
    "player.previous": _rpc_player_previous,
    "player.stop": _rpc_player_stop,
    "player.seek": _rpc_player_seek,
    "queue.get": _rpc_queue_get,
    "queue.replace_with_track_ids": _rpc_queue_replace,
    "queue.append_track_ids": _rpc_queue_append,
    "queue.clear": _rpc_queue_clear,
    "queue.remove_index": _rpc_queue_remove_index,
    "queue.play_index": _rpc_queue_play_index,
    "queue.move": _rpc_queue_move,
    "queue.insert_at": _rpc_queue_insert_at,
    "queue.insert_next": _rpc_queue_insert_next,
    "search.match_tracks": _rpc_search_match_tracks,
}


def list_methods():
    return sorted(_METHODS.keys())


def dispatch_rpc(app, method: str, params=None):
    handler = _METHODS.get(str(method or "").strip())
    if handler is None:
        raise RemoteDispatchError(-32601, f"Unknown method: {method}")
    return handler(app, params)
