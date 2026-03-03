"""
Global HTTP session management with configurable connection pool.
"""
import logging
import os
import requests
import requests.adapters

logger = logging.getLogger(__name__)

_global_session = None


def reset_global_session() -> None:
    """
    Close and discard the global HTTP session, forcing a fresh one on next use.
    Call this after system sleep/resume or when connections are known to be stale.
    """
    global _global_session
    old = _global_session
    _global_session = None
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
    logger.info("Global HTTP session reset (stale connections discarded)")


def get_global_session() -> requests.Session:
    """
    Get or create a global requests Session with larger connection pool.
    Pool size can be configured via HIRESTI_HTTP_POOL_SIZE environment variable.
    Default: 64, Max: 256.
    """
    global _global_session
    if _global_session is None:
        pool_size = int(os.getenv("HIRESTI_HTTP_POOL_SIZE", "64") or 64)
        pool_size = max(10, min(256, pool_size))
        _global_session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=pool_size,
            pool_maxsize=pool_size,
        )
        _global_session.mount("https://", adapter)
        _global_session.mount("http://", adapter)
        logger.info("Global HTTP session configured: pool_size=%s", pool_size)
    return _global_session
