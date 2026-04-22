"""Resolver for local filesystem audio files."""

from __future__ import annotations

import logging
import os
from urllib.parse import quote
from urllib.request import pathname2url

from sources.base import SOURCE_LOCAL, MediaResolver, StreamInfo
from sources.local.tags import read_tags

logger = logging.getLogger(__name__)


def path_to_file_uri(path: str) -> str:
    """Convert an absolute filesystem path to a `file://` URI."""
    abs_path = os.path.abspath(path)
    return "file://" + pathname2url(abs_path)


class LocalFileResolver(MediaResolver):
    source_type = SOURCE_LOCAL

    def resolve(self, track) -> StreamInfo:
        path = getattr(track, "path", "") or ""
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"Local track path missing: {path!r}")

        bit_depth = int(getattr(track, "bit_depth", 0) or 0)
        sample_rate = int(getattr(track, "sample_rate", 0) or 0)
        duration = float(getattr(track, "duration", 0.0) or 0.0)
        codec = str(getattr(track, "codec", "") or "")

        if not (bit_depth and sample_rate and duration):
            tags = read_tags(path)
            bit_depth = bit_depth or int(tags.get("bit_depth") or 0)
            sample_rate = sample_rate or int(tags.get("sample_rate") or 0)
            duration = duration or float(tags.get("duration") or 0.0)
            codec = codec or str(tags.get("codec") or "")

        return StreamInfo(
            url=path_to_file_uri(path),
            bit_depth=bit_depth,
            sample_rate=sample_rate,
            duration=duration,
            codec=codec,
        )
