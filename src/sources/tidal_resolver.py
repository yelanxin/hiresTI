"""Tidal-backed MediaResolver implementation.

Wraps `TidalBackend.get_stream_url` and surfaces the bit-depth /
sample-rate hints the backend records as side effects on itself
(`_last_stream_bit_depth`, `_last_stream_sample_rate`) into an
immutable `StreamInfo` return value.
"""

from __future__ import annotations

from typing import Any

from sources.base import SOURCE_TIDAL, MediaResolver, StreamInfo


class TidalResolver(MediaResolver):
    source_type = SOURCE_TIDAL

    def __init__(self, backend: Any) -> None:
        self.backend = backend

    def resolve(self, track: Any) -> StreamInfo:
        url = self.backend.get_stream_url(track)
        bit_depth = int(getattr(self.backend, "_last_stream_bit_depth", 0) or 0)
        sample_rate = int(getattr(self.backend, "_last_stream_sample_rate", 0) or 0)
        duration = float(getattr(track, "duration", 0) or 0)
        return StreamInfo(
            url=url or "",
            bit_depth=bit_depth,
            sample_rate=sample_rate,
            duration=duration,
        )
