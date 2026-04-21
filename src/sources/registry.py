"""Registry mapping source_type -> MediaResolver."""

from __future__ import annotations

import logging
from typing import Any

from sources.base import MediaResolver, StreamInfo, get_source_type

logger = logging.getLogger(__name__)


class MediaRegistry:
    def __init__(self) -> None:
        self._resolvers: dict[str, MediaResolver] = {}

    def register(self, source_type: str, resolver: MediaResolver) -> None:
        key = str(source_type).strip()
        if not key:
            raise ValueError("source_type must be non-empty")
        self._resolvers[key] = resolver
        logger.debug("Registered media resolver: %s -> %s", key, type(resolver).__name__)

    def get(self, source_type: str) -> MediaResolver | None:
        return self._resolvers.get(str(source_type))

    def resolver_for(self, track: Any) -> MediaResolver | None:
        return self.get(get_source_type(track))

    def resolve(self, track: Any) -> StreamInfo:
        resolver = self.resolver_for(track)
        if resolver is None:
            raise LookupError(f"No resolver registered for source_type={get_source_type(track)!r}")
        return resolver.resolve(track)
