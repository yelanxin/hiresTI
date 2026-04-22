"""Album / Artist shims for the local library.

Duck-typed to match the subset of `tidalapi.Album` / `tidalapi.Artist`
that the existing UI reads. Only fields the UI actually touches are
populated.
"""

from __future__ import annotations

import hashlib
from typing import Any


def _album_id(albumartist: str, album: str) -> str:
    raw = f"{(albumartist or '').strip().lower()}||{(album or '').strip().lower()}"
    return "local-album-" + hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16]


def _artist_id(artist: str) -> str:
    raw = (artist or "").strip().lower()
    return "local-artist-" + hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16]


class _NamedRef:
    __slots__ = ("name", "id")

    def __init__(self, name: str = "", id: str = "") -> None:
        self.name = name or ""
        self.id = id or ""


class LocalAlbum:
    """Album shape for a grouping of local tracks (albumartist, album)."""

    __slots__ = (
        "id", "name", "cover", "artist", "artists",
        "num_tracks", "duration", "release_date", "year",
        "max_bit_depth", "max_sample_rate", "_albumartist", "_source_type",
    )

    def __init__(
        self,
        *,
        albumartist: str,
        album: str,
        cover: str = "",
        num_tracks: int = 0,
        duration: float = 0.0,
        date: str = "",
        max_bit_depth: int = 0,
        max_sample_rate: int = 0,
    ) -> None:
        self.id = _album_id(albumartist, album)
        self.name = album or "Unknown Album"
        self.cover = cover or ""
        self.artist = _NamedRef(name=albumartist or "Unknown Artist",
                                id=_artist_id(albumartist))
        self.artists = [self.artist]
        self.num_tracks = int(num_tracks or 0)
        self.duration = float(duration or 0.0)
        self.release_date = date or ""
        self.year = date[:4] if date else ""
        self.max_bit_depth = int(max_bit_depth or 0)
        self.max_sample_rate = int(max_sample_rate or 0)
        self._albumartist = albumartist or ""
        self._source_type = "local"


class LocalArtist:
    """Artist shape for a grouping of local tracks."""

    __slots__ = ("id", "name", "picture", "album_count", "track_count", "_source_type")

    def __init__(
        self,
        *,
        name: str,
        album_count: int = 0,
        track_count: int = 0,
        picture: str = "",
    ) -> None:
        self.id = _artist_id(name)
        self.name = name or "Unknown Artist"
        self.picture = picture or ""
        self.album_count = int(album_count or 0)
        self.track_count = int(track_count or 0)
        self._source_type = "local"
