"""Shared helpers for app wiring."""

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)


def bind_map(cls, mapping, seen=None):
    items = mapping.items() if isinstance(mapping, Mapping) else mapping
    local_seen = set()
    for name, func in items:
        if name in local_seen:
            logger.warning("Duplicate wiring target detected in block: %s", name)
        local_seen.add(name)
        if seen is not None:
            if name in seen:
                logger.warning("Duplicate wiring target detected: %s", name)
            seen.add(name)
        setattr(cls, name, func)
