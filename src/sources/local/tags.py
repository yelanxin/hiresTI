"""Tag / audio-property reader for local files.

Uses `mutagen` when available. Falls back to filename-only metadata
otherwise — playback still works, just with no title/artist/album.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

try:
    import mutagen
    from mutagen.flac import FLAC
except Exception:
    mutagen = None
    FLAC = None


_TEXT_KEYS = {
    "title": ("TIT2", "title", "\xa9nam"),
    "artist": ("TPE1", "artist", "\xa9ART"),
    "album": ("TALB", "album", "\xa9alb"),
    "albumartist": ("TPE2", "albumartist", "aART"),
    "date": ("TDRC", "date", "\xa9day"),
    "tracknumber": ("TRCK", "tracknumber", "trkn"),
    "genre": ("TCON", "genre", "\xa9gen"),
}


def _first(tags, keys):
    for k in keys:
        if k in tags:
            val = tags[k]
            if isinstance(val, list) and val:
                val = val[0]
            try:
                text = str(val).strip()
            except Exception:
                continue
            if text:
                return text
    return ""


def read_tags(path: str) -> dict:
    """Return a normalized dict of tags + audio properties for a file.

    Keys populated when available: `title`, `artist`, `album`,
    `albumartist`, `date`, `tracknumber`, `genre`, `duration`,
    `bit_depth`, `sample_rate`, `codec`.
    """
    info: dict = {"path": path}
    if mutagen is None:
        logger.debug("mutagen not available; using filename-only metadata for %s", path)
        return info

    try:
        mf = mutagen.File(path)
    except Exception as exc:
        logger.info("mutagen failed to read %s: %s", path, exc)
        return info
    if mf is None:
        return info

    tags = getattr(mf, "tags", None) or {}
    try:
        for key, candidates in _TEXT_KEYS.items():
            val = _first(tags, candidates)
            if val:
                info[key] = val
    except Exception as exc:
        logger.debug("tag normalization failed for %s: %s", path, exc)

    audio = getattr(mf, "info", None)
    if audio is not None:
        for attr, out in (
            ("length", "duration"),
            ("sample_rate", "sample_rate"),
            ("bits_per_sample", "bit_depth"),
            ("channels", "channels"),
            ("bitrate", "bitrate"),
        ):
            try:
                value = getattr(audio, attr, None)
                if value is None:
                    continue
                info[out] = value
            except Exception:
                continue

    ext = os.path.splitext(path)[1].lstrip(".").lower()
    if ext:
        info.setdefault("codec", ext)
    return info
