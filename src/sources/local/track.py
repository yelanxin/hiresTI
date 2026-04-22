"""Local-file queue item shim.

Duck-types the subset of `tidalapi.Track` that the existing player and
UI read directly: `.id`, `.name`, `.artist.name`, `.album.name`,
`.album.cover`, `.duration`, `.cover`.
"""

from __future__ import annotations

import hashlib
import os

from sources.base import SOURCE_LOCAL, tag_source


class _NamedRef:
    __slots__ = ("name", "cover", "id", "_source_type")

    def __init__(self, name: str = "", cover: str = "", id: str = "") -> None:
        self.name = name or ""
        self.cover = cover or ""
        self.id = id or ""
        self._source_type = SOURCE_LOCAL


class LocalTrack:
    """Minimal track-shaped object for files on disk."""

    __slots__ = (
        "id", "name", "duration", "path",
        "artist", "album", "cover",
        "bit_depth", "sample_rate", "codec",
        "_source_type",
    )

    def __init__(
        self,
        *,
        id: str,
        name: str,
        path: str,
        duration: float = 0.0,
        artist_name: str = "",
        album_name: str = "",
        album_cover: str = "",
        bit_depth: int = 0,
        sample_rate: int = 0,
        codec: str = "",
    ) -> None:
        self.id = str(id)
        self.name = name or os.path.basename(path)
        self.duration = float(duration or 0.0)
        self.path = path
        self.artist = _NamedRef(name=artist_name or "Unknown Artist")
        self.album = _NamedRef(name=album_name or "Unknown Album", cover=album_cover or "")
        self.cover = album_cover or ""
        self.bit_depth = int(bit_depth or 0)
        self.sample_rate = int(sample_rate or 0)
        self.codec = codec or ""
        self._source_type = SOURCE_LOCAL


def _stable_id(path: str) -> str:
    abs_path = os.path.realpath(path)
    return "local:" + hashlib.sha1(abs_path.encode("utf-8", "replace")).hexdigest()[:16]


def make_local_track(path: str, tags: dict | None = None) -> LocalTrack:
    """Build a LocalTrack from a filesystem path and an optional tag dict."""
    tags = tags or {}
    basename = os.path.splitext(os.path.basename(path))[0]
    track = LocalTrack(
        id=_stable_id(path),
        name=str(tags.get("title") or basename),
        path=path,
        duration=float(tags.get("duration") or 0.0),
        artist_name=str(tags.get("artist") or ""),
        album_name=str(tags.get("album") or ""),
        album_cover=str(tags.get("cover_path") or ""),
        bit_depth=int(tags.get("bit_depth") or 0),
        sample_rate=int(tags.get("sample_rate") or 0),
        codec=str(tags.get("codec") or ""),
    )
    tag_source(track, SOURCE_LOCAL)
    return track
