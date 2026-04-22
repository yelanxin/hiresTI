"""High-level browsing facade over the local library DB.

The UI calls these methods; all DB I/O lives in `library_db`. Each call
opens a short-lived sqlite3 connection — cheap, and keeps us thread-safe
without sharing a connection object across threads.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable

from sources.local import library_db
from sources.local.models import LocalAlbum, LocalArtist
from sources.local.track import make_local_track

logger = logging.getLogger(__name__)


class LocalLibrarySource:
    """Single-entry-point for local-music browsing."""

    def __init__(self, db_path: str, cover_cache_dir: str) -> None:
        self.db_path = db_path
        self.cover_cache_dir = cover_cache_dir
        self._write_lock = threading.Lock()
        conn = library_db.open_db(db_path)
        try:
            library_db.init_schema(conn)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # connection helpers
    # ------------------------------------------------------------------

    def _conn(self):
        return library_db.open_db(self.db_path)

    # ------------------------------------------------------------------
    # sources (folders)
    # ------------------------------------------------------------------

    def list_folders(self) -> list[dict]:
        conn = self._conn()
        try:
            rows = library_db.list_sources(conn)
        finally:
            conn.close()
        # UI only cares about folder-type sources in Phase 1.
        return [r for r in rows if r.get("type") == "folder"]

    def add_folder(self, location: str, name: str = "") -> int:
        location = os.path.abspath(location)
        with self._write_lock:
            conn = self._conn()
            try:
                sid = library_db.add_source(
                    conn, type="folder", location=location, name=name,
                )
            finally:
                conn.close()
        return sid

    def remove_folder(self, source_id: int) -> None:
        with self._write_lock:
            conn = self._conn()
            try:
                library_db.remove_source(conn, source_id)
            finally:
                conn.close()

    def folder_track_count(self, source_id: int) -> int:
        conn = self._conn()
        try:
            return library_db.count_tracks_for_source(conn, source_id)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # browsing
    # ------------------------------------------------------------------

    def total_tracks(self) -> int:
        conn = self._conn()
        try:
            return library_db.count_tracks(conn)
        finally:
            conn.close()

    def get_albums(self) -> list[LocalAlbum]:
        conn = self._conn()
        try:
            rows = library_db.query_albums(conn)
        finally:
            conn.close()
        return [self._album_from_row(r) for r in rows]

    def get_artists(self) -> list[LocalArtist]:
        conn = self._conn()
        try:
            rows = library_db.query_artists(conn)
        finally:
            conn.close()
        return [
            LocalArtist(
                name=r.get("artist") or "",
                album_count=r.get("album_count") or 0,
                track_count=r.get("track_count") or 0,
            )
            for r in rows
        ]

    def get_tracks(self, limit: int | None = None, offset: int = 0):
        conn = self._conn()
        try:
            rows = library_db.query_tracks(conn, limit=limit, offset=offset)
        finally:
            conn.close()
        return [self._track_from_row(r) for r in rows]

    def get_album_tracks(self, albumartist: str, album: str):
        conn = self._conn()
        try:
            rows = library_db.query_album_tracks(conn, albumartist, album)
        finally:
            conn.close()
        return [self._track_from_row(r) for r in rows]

    def get_artist_albums(self, artist: str) -> list[LocalAlbum]:
        conn = self._conn()
        try:
            rows = library_db.query_artist_albums(conn, artist)
        finally:
            conn.close()
        return [self._album_from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # id resolution (for deep-linking into album/artist detail pages)
    # ------------------------------------------------------------------

    def find_album_by_id(self, album_id: str) -> LocalAlbum | None:
        for album in self.get_albums():
            if album.id == album_id:
                return album
        return None

    def find_artist_by_id(self, artist_id: str) -> LocalArtist | None:
        for artist in self.get_artists():
            if artist.id == artist_id:
                return artist
        return None

    # ------------------------------------------------------------------
    # scan orchestration
    # ------------------------------------------------------------------

    def rescan_folder(
        self,
        source_id: int,
        *,
        on_progress: Callable[[dict], None] | None = None,
        on_done: Callable[[dict], None] | None = None,
    ):
        from sources.local.scanner import scan_source_async
        conn = self._conn()
        try:
            src = library_db.get_source(conn, source_id)
        finally:
            conn.close()
        if not src:
            logger.warning("rescan requested for unknown source id=%s", source_id)
            return None
        return scan_source_async(
            self.db_path,
            source_id,
            src["location"],
            self.cover_cache_dir,
            on_progress=on_progress,
            on_done=on_done,
        )

    def rescan_all(
        self,
        *,
        on_progress: Callable[[dict], None] | None = None,
        on_done: Callable[[dict], None] | None = None,
    ) -> list:
        handles = []
        for src in self.list_folders():
            h = self.rescan_folder(
                int(src["id"]),
                on_progress=on_progress,
                on_done=on_done,
            )
            if h is not None:
                handles.append(h)
        return handles

    # ------------------------------------------------------------------
    # row -> shim
    # ------------------------------------------------------------------

    def _track_from_row(self, row: dict):
        tags = {
            "title": row.get("title") or "",
            "artist": row.get("artist") or "",
            "album": row.get("album") or "",
            "albumartist": row.get("albumartist") or "",
            "date": row.get("date") or "",
            "duration": row.get("duration") or 0.0,
            "bit_depth": row.get("bit_depth") or 0,
            "sample_rate": row.get("sample_rate") or 0,
            "codec": row.get("codec") or "",
            "cover_path": row.get("cover_path") or "",
        }
        track = make_local_track(row["path"], tags)
        # Override id to match the DB dedup_key (stable across metadata edits).
        track.id = f"local:{row['dedup_key']}"
        # Populate album / artist ids so navigation actions can deep-link.
        try:
            from sources.local.models import _album_id, _artist_id
            track.album.id = _album_id(row.get("albumartist") or row.get("artist") or "",
                                       row.get("album") or "")
            track.artist.id = _artist_id(row.get("artist") or "")
        except Exception:
            pass
        return track

    def _album_from_row(self, row: dict) -> LocalAlbum:
        return LocalAlbum(
            albumartist=row.get("albumartist") or "",
            album=row.get("album") or "",
            cover=row.get("cover_path") or "",
            num_tracks=row.get("track_count") or 0,
            duration=row.get("total_duration") or 0.0,
            date=row.get("date") or "",
            max_bit_depth=row.get("max_bit_depth") or 0,
            max_sample_rate=row.get("max_sample_rate") or 0,
        )
