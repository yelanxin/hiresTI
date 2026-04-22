"""Recursive incremental scanner for local music folders.

Walks a source's root directory, reads tags on files whose (path, mtime,
size) fingerprint differs from the DB, extracts one embedded cover per
album into the cache dir, and upserts rows.

Runs on a worker thread. Progress is reported through a callback that is
invoked on the GTK main loop via `GLib.idle_add`.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Callable, Iterable

from sources.local import library_db
from sources.local.tags import read_tags

logger = logging.getLogger(__name__)


_AUDIO_EXTENSIONS = {
    "flac", "mp3", "m4a", "mp4", "aac", "alac",
    "wav", "wave", "aiff", "aif", "ogg", "oga", "opus",
    "dsf", "dff", "ape", "wv",
}

_SIDECAR_COVER_NAMES = (
    "cover.jpg", "cover.jpeg", "cover.png",
    "folder.jpg", "folder.jpeg", "folder.png",
    "front.jpg", "front.jpeg", "front.png",
    "album.jpg", "album.jpeg", "album.png",
)


def _is_audio(name: str) -> bool:
    ext = os.path.splitext(name)[1].lstrip(".").lower()
    return ext in _AUDIO_EXTENSIONS


def _sidecar_cover(dir_path: str) -> str:
    try:
        entries = {n.lower(): n for n in os.listdir(dir_path)}
    except OSError:
        return ""
    for candidate in _SIDECAR_COVER_NAMES:
        name = entries.get(candidate)
        if name:
            return os.path.join(dir_path, name)
    return ""


def _extract_cover_to_dir(path: str, dest_dir: str, album_hash: str) -> str:
    """Extract embedded art. Returns the written path or ""."""
    try:
        import mutagen
    except Exception:
        return ""
    try:
        mf = mutagen.File(path)
    except Exception:
        return ""
    if mf is None:
        return ""

    data = b""
    ext = "jpg"

    try:
        pics = getattr(mf, "pictures", None) or []
        if pics:
            pic = pics[0]
            data = bytes(getattr(pic, "data", b"") or b"")
            if "png" in str(getattr(pic, "mime", "") or "").lower():
                ext = "png"
    except Exception:
        pass

    if not data:
        try:
            tags = getattr(mf, "tags", None)
            if tags is not None and hasattr(tags, "getall"):
                apics = tags.getall("APIC")
                if apics:
                    data = bytes(getattr(apics[0], "data", b"") or b"")
                    if "png" in str(getattr(apics[0], "mime", "") or "").lower():
                        ext = "png"
        except Exception:
            pass

    if not data:
        try:
            tags = getattr(mf, "tags", None) or {}
            covr = tags.get("covr") if hasattr(tags, "get") else None
            if covr:
                cover = covr[0]
                data = bytes(cover)
                if int(getattr(cover, "imageformat", 13) or 13) == 14:
                    ext = "png"
        except Exception:
            pass

    if not data:
        return ""

    try:
        os.makedirs(dest_dir, exist_ok=True)
        target = os.path.join(dest_dir, f"{album_hash}.{ext}")
        if os.path.exists(target):
            return target
        with open(target, "wb") as fh:
            fh.write(data)
        return target
    except Exception:
        logger.debug("cover write failed for %s", path, exc_info=True)
        return ""


def _parse_tracknumber(raw: str) -> int:
    if not raw:
        return 0
    match = re.match(r"\s*(\d+)", str(raw))
    return int(match.group(1)) if match else 0


def _parse_year(raw: str) -> int:
    if not raw:
        return 0
    match = re.search(r"(\d{4})", str(raw))
    return int(match.group(1)) if match else 0


def _decade_from_year(year: int) -> int:
    if year < 1000:
        return 0
    return (year // 10) * 10


def walk_audio_files(root: str) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith(".") or not _is_audio(name):
                continue
            yield os.path.join(dirpath, name)


def scan_source(
    conn,
    source_id: int,
    root: str,
    cover_cache_dir: str,
    *,
    progress: Callable[[dict], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Scan `root` and upsert rows for `source_id`.

    Returns a summary dict: {added, updated, removed, skipped, errors, total}.
    Progress callback receives the summary dict at each file.
    """
    summary = {
        "added": 0,
        "updated": 0,
        "removed": 0,
        "skipped": 0,
        "errors": 0,
        "total": 0,
        "current": "",
        "done": False,
    }

    if not os.path.isdir(root):
        logger.warning("scan root does not exist: %s", root)
        summary["done"] = True
        if progress:
            progress(dict(summary))
        return summary

    cover_dir = os.path.join(cover_cache_dir, "local-covers")
    seen_keys: list[str] = []
    # Cache cover paths per album so we only extract once per album.
    album_covers: dict[str, str] = {}

    try:
        conn.execute("BEGIN")
    except Exception:
        pass

    try:
        for path in walk_audio_files(root):
            if cancel_event is not None and cancel_event.is_set():
                break

            summary["total"] += 1
            summary["current"] = path

            try:
                st = os.stat(path)
            except OSError as exc:
                logger.debug("stat failed %s: %s", path, exc)
                summary["errors"] += 1
                continue

            dedup_key = library_db.dedup_key_for(path)
            seen_keys.append(dedup_key)
            stored = library_db.get_track_fingerprint(conn, dedup_key)
            if stored is not None:
                prev_mtime, prev_size = stored
                if (
                    abs(prev_mtime - st.st_mtime) < 1.0
                    and prev_size == int(st.st_size)
                ):
                    summary["skipped"] += 1
                    if progress and summary["total"] % 50 == 0:
                        progress(dict(summary))
                    continue

            try:
                tags = read_tags(path)
            except Exception:
                logger.debug("read_tags failed for %s", path, exc_info=True)
                tags = {"path": path}
                summary["errors"] += 1

            albumartist = (
                str(tags.get("albumartist") or "")
                or str(tags.get("artist") or "")
            )
            album = str(tags.get("album") or "")
            album_hash = library_db.album_key_for(albumartist, album)

            cover_path = album_covers.get(album_hash, "")
            if not cover_path:
                cover_path = _extract_cover_to_dir(path, cover_dir, album_hash)
                if not cover_path:
                    sidecar = _sidecar_cover(os.path.dirname(path))
                    if sidecar:
                        cover_path = sidecar
                if cover_path:
                    album_covers[album_hash] = cover_path

            year = _parse_year(str(tags.get("date") or ""))

            try:
                library_db.upsert_track(
                    conn,
                    source_id=source_id,
                    source_type="local",
                    path=path,
                    dedup_key=dedup_key,
                    mtime=float(st.st_mtime),
                    size=int(st.st_size),
                    title=str(tags.get("title") or ""),
                    artist=str(tags.get("artist") or ""),
                    album=album,
                    albumartist=albumartist,
                    tracknumber=_parse_tracknumber(str(tags.get("tracknumber") or "")),
                    discnumber=_parse_tracknumber(str(tags.get("discnumber") or "")),
                    date=str(tags.get("date") or ""),
                    genre=str(tags.get("genre") or ""),
                    decade=_decade_from_year(year),
                    duration=float(tags.get("duration") or 0.0),
                    bit_depth=int(tags.get("bit_depth") or 0),
                    sample_rate=int(tags.get("sample_rate") or 0),
                    codec=str(tags.get("codec") or ""),
                    cover_path=cover_path,
                )
            except Exception:
                logger.exception("upsert failed for %s", path)
                summary["errors"] += 1
                continue

            if stored is None:
                summary["added"] += 1
            else:
                summary["updated"] += 1

            if progress and summary["total"] % 20 == 0:
                progress(dict(summary))

        if cancel_event is None or not cancel_event.is_set():
            summary["removed"] = library_db.delete_tracks_not_in(
                conn, source_id, seen_keys,
            )
            library_db.touch_source_scan(conn, source_id)
        conn.execute("COMMIT")
    except Exception:
        logger.exception("scan failed; rolling back")
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        summary["errors"] += 1

    summary["done"] = True
    summary["current"] = ""
    if progress:
        progress(dict(summary))
    return summary


def scan_source_async(
    db_path: str,
    source_id: int,
    root: str,
    cover_cache_dir: str,
    *,
    on_progress: Callable[[dict], None] | None = None,
    on_done: Callable[[dict], None] | None = None,
) -> tuple[threading.Thread, threading.Event]:
    """Run `scan_source` on a daemon thread.

    Returns (thread, cancel_event). Callbacks are dispatched via GLib.idle_add
    if gtk is importable; otherwise invoked inline on the worker thread.
    """
    cancel_event = threading.Event()

    try:
        from gi.repository import GLib  # type: ignore
    except Exception:
        GLib = None  # type: ignore

    def _on_main(cb, payload):
        if cb is None:
            return
        if GLib is None:
            try:
                cb(payload)
            except Exception:
                logger.debug("callback failed", exc_info=True)
            return
        def _run():
            try:
                cb(payload)
            except Exception:
                logger.debug("idle callback failed", exc_info=True)
            return False
        GLib.idle_add(_run)

    def _worker():
        # Each thread needs its own sqlite connection.
        conn = library_db.open_db(db_path)
        try:
            library_db.init_schema(conn)
            summary = scan_source(
                conn,
                source_id,
                root,
                cover_cache_dir,
                progress=lambda s: _on_main(on_progress, s),
                cancel_event=cancel_event,
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
        _on_main(on_done, summary)

    thread = threading.Thread(target=_worker, name=f"local-scan-{source_id}", daemon=True)
    thread.start()
    return thread, cancel_event


