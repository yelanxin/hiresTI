"""SQLite-backed store for the local music library.

Schema (Phase 1):

    sources(id, type, name, location, last_scanned_at, enabled)
    tracks(id, source_id, source_type, path, dedup_key,
           mtime, size,
           title, artist, album, albumartist,
           tracknumber, discnumber, date, genre, decade,
           duration, bit_depth, sample_rate, codec,
           cover_path)

`dedup_key` is a stable sha1 over the absolute path; used for upserts and
as the LocalTrack public id.

All callers hand in a short-lived `sqlite3.Connection`. Opening is cheap;
this keeps threading simple (scanner runs off the GTK loop, UI reads on
the loop).
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import time
from typing import Any, Iterable

logger = logging.getLogger(__name__)


SCHEMA_VERSION = 1


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    name TEXT,
    location TEXT NOT NULL,
    last_scanned_at REAL,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(type, location)
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    path TEXT NOT NULL,
    dedup_key TEXT NOT NULL UNIQUE,
    mtime REAL,
    size INTEGER,
    title TEXT,
    artist TEXT,
    album TEXT,
    albumartist TEXT,
    tracknumber INTEGER,
    discnumber INTEGER,
    date TEXT,
    genre TEXT,
    decade INTEGER,
    duration REAL,
    bit_depth INTEGER,
    sample_rate INTEGER,
    codec TEXT,
    cover_path TEXT,
    added_at REAL
);

CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(albumartist, album);
CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist);
CREATE INDEX IF NOT EXISTS idx_tracks_genre ON tracks(genre);
CREATE INDEX IF NOT EXISTS idx_tracks_decade ON tracks(decade);
CREATE INDEX IF NOT EXISTS idx_tracks_source ON tracks(source_id);
"""


def dedup_key_for(path: str) -> str:
    abs_path = os.path.realpath(path)
    return hashlib.sha1(abs_path.encode("utf-8", "replace")).hexdigest()


def album_key_for(albumartist: str, album: str) -> str:
    raw = f"{(albumartist or '').strip().lower()}||{(album or '').strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16]


def artist_key_for(artist: str) -> str:
    raw = (artist or "").strip().lower()
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16]


def open_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'version'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('version', ?)",
            (str(SCHEMA_VERSION),),
        )


# ------------------------------------------------------------------
# Sources
# ------------------------------------------------------------------

def add_source(
    conn: sqlite3.Connection,
    *,
    type: str,
    location: str,
    name: str = "",
) -> int:
    """Insert or return id of an existing source with the same (type, location)."""
    cur = conn.execute(
        "SELECT id FROM sources WHERE type = ? AND location = ?",
        (type, location),
    )
    row = cur.fetchone()
    if row is not None:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO sources(type, name, location, last_scanned_at, enabled) "
        "VALUES(?, ?, ?, NULL, 1)",
        (type, name or os.path.basename(location.rstrip("/")) or location, location),
    )
    return int(cur.lastrowid)


def list_sources(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, type, name, location, last_scanned_at, enabled "
        "FROM sources ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


def get_source(conn: sqlite3.Connection, source_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, type, name, location, last_scanned_at, enabled "
        "FROM sources WHERE id = ?",
        (int(source_id),),
    ).fetchone()
    return dict(row) if row is not None else None


def remove_source(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute("DELETE FROM sources WHERE id = ?", (int(source_id),))


def touch_source_scan(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute(
        "UPDATE sources SET last_scanned_at = ? WHERE id = ?",
        (time.time(), int(source_id)),
    )


# ------------------------------------------------------------------
# Tracks
# ------------------------------------------------------------------

def get_track_fingerprint(
    conn: sqlite3.Connection,
    dedup_key: str,
) -> tuple[float, int] | None:
    """Return (mtime, size) of the stored row or None if absent."""
    row = conn.execute(
        "SELECT mtime, size FROM tracks WHERE dedup_key = ?",
        (dedup_key,),
    ).fetchone()
    if row is None:
        return None
    return (float(row["mtime"] or 0.0), int(row["size"] or 0))


def upsert_track(
    conn: sqlite3.Connection,
    *,
    source_id: int,
    source_type: str = "local",
    path: str,
    dedup_key: str,
    mtime: float = 0.0,
    size: int = 0,
    title: str = "",
    artist: str = "",
    album: str = "",
    albumartist: str = "",
    tracknumber: int = 0,
    discnumber: int = 0,
    date: str = "",
    genre: str = "",
    decade: int = 0,
    duration: float = 0.0,
    bit_depth: int = 0,
    sample_rate: int = 0,
    codec: str = "",
    cover_path: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO tracks(
            source_id, source_type, path, dedup_key, mtime, size,
            title, artist, album, albumartist,
            tracknumber, discnumber, date, genre, decade,
            duration, bit_depth, sample_rate, codec, cover_path, added_at
        ) VALUES (?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?,
                  ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dedup_key) DO UPDATE SET
            source_id    = excluded.source_id,
            source_type  = excluded.source_type,
            path         = excluded.path,
            mtime        = excluded.mtime,
            size         = excluded.size,
            title        = excluded.title,
            artist       = excluded.artist,
            album        = excluded.album,
            albumartist  = excluded.albumartist,
            tracknumber  = excluded.tracknumber,
            discnumber   = excluded.discnumber,
            date         = excluded.date,
            genre        = excluded.genre,
            decade       = excluded.decade,
            duration     = excluded.duration,
            bit_depth    = excluded.bit_depth,
            sample_rate  = excluded.sample_rate,
            codec        = excluded.codec,
            cover_path   = excluded.cover_path
        """,
        (
            int(source_id), source_type, path, dedup_key, float(mtime or 0.0), int(size or 0),
            title or "", artist or "", album or "", albumartist or "",
            int(tracknumber or 0), int(discnumber or 0), date or "", genre or "", int(decade or 0),
            float(duration or 0.0), int(bit_depth or 0), int(sample_rate or 0), codec or "",
            cover_path or "", time.time(),
        ),
    )


def delete_tracks_not_in(
    conn: sqlite3.Connection,
    source_id: int,
    seen_keys: Iterable[str],
) -> int:
    """Remove rows from `source_id` whose dedup_key isn't in `seen_keys`.

    Uses a temp table to avoid the 999-var SQLite limit.
    """
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _seen_keys(k TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM _seen_keys")
    conn.executemany(
        "INSERT OR IGNORE INTO _seen_keys(k) VALUES(?)",
        ((k,) for k in seen_keys),
    )
    cur = conn.execute(
        "DELETE FROM tracks "
        "WHERE source_id = ? AND dedup_key NOT IN (SELECT k FROM _seen_keys)",
        (int(source_id),),
    )
    removed = int(cur.rowcount or 0)
    conn.execute("DROP TABLE _seen_keys")
    return removed


# ------------------------------------------------------------------
# Queries used by the UI
# ------------------------------------------------------------------

def count_tracks(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM tracks").fetchone()
    return int(row["c"]) if row else 0


def query_tracks(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    sql = (
        "SELECT * FROM tracks "
        "ORDER BY albumartist COLLATE NOCASE, album COLLATE NOCASE, "
        "         discnumber, tracknumber, title COLLATE NOCASE"
    )
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = (int(limit), int(offset))
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_albums(conn: sqlite3.Connection) -> list[dict]:
    """Return one row per distinct (albumartist, album) with aggregate info."""
    rows = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(albumartist, ''), artist) AS albumartist,
            album AS album,
            MIN(date)       AS date,
            MAX(cover_path) AS cover_path,
            COUNT(*)        AS track_count,
            SUM(duration)   AS total_duration,
            MAX(bit_depth)  AS max_bit_depth,
            MAX(sample_rate) AS max_sample_rate
        FROM tracks
        WHERE COALESCE(album, '') <> ''
        GROUP BY COALESCE(NULLIF(albumartist, ''), artist), album
        ORDER BY albumartist COLLATE NOCASE, date DESC, album COLLATE NOCASE
        """
    ).fetchall()
    return [dict(r) for r in rows]


def query_artists(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(albumartist, ''), artist) AS artist,
            COUNT(DISTINCT album) AS album_count,
            COUNT(*)              AS track_count
        FROM tracks
        WHERE COALESCE(NULLIF(albumartist, ''), artist) <> ''
        GROUP BY COALESCE(NULLIF(albumartist, ''), artist)
        ORDER BY artist COLLATE NOCASE
        """
    ).fetchall()
    return [dict(r) for r in rows]


def query_album_tracks(
    conn: sqlite3.Connection,
    albumartist: str,
    album: str,
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM tracks
        WHERE COALESCE(NULLIF(albumartist, ''), artist) = ?
          AND album = ?
        ORDER BY discnumber, tracknumber, title COLLATE NOCASE
        """,
        (albumartist, album),
    ).fetchall()
    return [dict(r) for r in rows]


def query_artist_albums(conn: sqlite3.Connection, artist: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(albumartist, ''), artist) AS albumartist,
            album AS album,
            MIN(date)       AS date,
            MAX(cover_path) AS cover_path,
            COUNT(*)        AS track_count,
            SUM(duration)   AS total_duration,
            MAX(bit_depth)  AS max_bit_depth,
            MAX(sample_rate) AS max_sample_rate
        FROM tracks
        WHERE COALESCE(NULLIF(albumartist, ''), artist) = ?
          AND COALESCE(album, '') <> ''
        GROUP BY album
        ORDER BY date DESC, album COLLATE NOCASE
        """,
        (artist,),
    ).fetchall()
    return [dict(r) for r in rows]


def count_tracks_for_source(conn: sqlite3.Connection, source_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM tracks WHERE source_id = ?",
        (int(source_id),),
    ).fetchone()
    return int(row["c"]) if row else 0
