"""Core interfaces for pluggable media sources.

A `MediaResolver` turns a queue item (a "track"-shaped object) into a
`StreamInfo` the playback engine can consume. The queue item itself
carries a `_source_type` attribute (string) used by `MediaRegistry` to
pick the right resolver.

Intentionally narrow: this layer only handles the "give me a playable
URI for this item" concern. Browsing / library listing is out of scope
for this interface — those live in per-source library modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SOURCE_TIDAL = "tidal"
SOURCE_LOCAL = "local"


@dataclass
class StreamInfo:
    """Everything the player needs to start decoding a track."""

    url: str
    bit_depth: int = 0
    sample_rate: int = 0
    duration: float = 0.0
    container: str = ""
    codec: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


class MediaResolver:
    """Contract for per-source URL/metadata resolution.

    Implementations run on a daemon thread (not the GTK main loop) so
    blocking network I/O is fine.
    """

    source_type: str = ""

    def resolve(self, track: Any) -> StreamInfo:
        raise NotImplementedError

    def supports(self, track: Any) -> bool:
        return get_source_type(track) == self.source_type


def get_source_type(track: Any) -> str:
    """Read the source tag off a queue item.

    Defaults to `SOURCE_TIDAL` so pre-existing queue items (plain
    tidalapi track objects without the attribute) keep working.
    """
    return str(getattr(track, "_source_type", SOURCE_TIDAL) or SOURCE_TIDAL)


def tag_source(track: Any, source_type: str) -> Any:
    """Stamp a queue item with its source type; returns the same object."""
    try:
        setattr(track, "_source_type", str(source_type))
    except Exception:
        pass
    return track
