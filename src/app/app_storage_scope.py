"""Storage cache maintenance and account scope helpers."""

import logging
import os

import utils.helpers as utils
from core.constants import CacheSettings
from core.executor import submit_daemon

logger = logging.getLogger(__name__)


def _schedule_cache_maintenance(self):
    def _parse_int_env(name, default):
        raw = os.getenv(name)
        if not raw:
            return default
        try:
            value = int(raw)
            return value if value > 0 else default
        except ValueError:
            return default

    max_mb = _parse_int_env("HIRESTI_COVER_CACHE_MAX_MB", CacheSettings.DEFAULT_MAX_MB)
    max_days = _parse_int_env("HIRESTI_COVER_CACHE_MAX_DAYS", CacheSettings.DEFAULT_MAX_DAYS)
    max_bytes = max_mb * 1024 * 1024

    def task():
        logger.info(
            "Running cover/audio cache maintenance (cover=%sMB ttl=%sd, audio tracks=%s)",
            max_mb,
            max_days,
            getattr(self, "audio_cache_tracks", 0),
        )
        utils.prune_image_cache(self.cache_dir, max_bytes=max_bytes, max_age_days=max_days)
        utils.prune_audio_cache(
            getattr(self, "audio_cache_dir", ""),
            max_tracks=max(0, int(getattr(self, "audio_cache_tracks", 0) or 0)),
        )

    submit_daemon(task)


def _account_scope_from_backend_user(self):
    user = getattr(self.backend, "user", None)
    uid = getattr(user, "id", None)
    if uid is None:
        return "guest"
    raw = str(uid).strip()
    if not raw:
        return "guest"
    safe = "".join(ch if (ch.isalnum() or ch in ("-", "_")) else "_" for ch in raw)
    return f"u_{safe}" if safe else "guest"


def _apply_account_scope(self, force=False):
    scope = self._account_scope_from_backend_user()
    if (not force) and scope == getattr(self, "_account_scope", None):
        return
    self._account_scope = scope
    if hasattr(self, "history_mgr") and self.history_mgr is not None:
        self.history_mgr.set_scope(scope)
    if hasattr(self, "playlist_mgr") and self.playlist_mgr is not None:
        self.playlist_mgr.set_scope(scope)
    # Reset playlist-specific transient state to avoid stale references across accounts.
    self.current_playlist_id = None
    self.playlist_edit_mode = False
    self.playlist_rename_mode = False
    logger.info("Local data scope switched to account: %s", scope)
