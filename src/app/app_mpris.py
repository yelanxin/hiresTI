"""MPRIS lifecycle and sync wrappers for TidalApp."""

import logging

from services.mpris import MPRISService

logger = logging.getLogger(__name__)


def _start_mpris_service(self):
    try:
        svc = getattr(self, "_mpris", None)
        if svc is None:
            svc = MPRISService(self)
            self._mpris = svc
        svc.start()
        if svc.started:
            svc.sync_all(force=True)
    except Exception as e:
        logger.debug("Failed to start MPRIS service: %s", e)


def _stop_mpris_service(self):
    svc = getattr(self, "_mpris", None)
    if svc is None:
        return
    try:
        svc.stop()
    except Exception:
        logger.debug("Failed to stop MPRIS service", exc_info=True)


def _mpris_sync_all(self, force=False):
    svc = getattr(self, "_mpris", None)
    if svc is None:
        return
    try:
        svc.sync_all(force=bool(force))
    except Exception:
        logger.debug("MPRIS sync_all failed", exc_info=True)


def _mpris_sync_metadata(self):
    svc = getattr(self, "_mpris", None)
    if svc is None:
        return
    try:
        svc.sync_metadata()
    except Exception:
        logger.debug("MPRIS sync_metadata failed", exc_info=True)


def _mpris_sync_playback(self):
    svc = getattr(self, "_mpris", None)
    if svc is None:
        return
    try:
        svc.sync_playback()
    except Exception:
        logger.debug("MPRIS sync_playback failed", exc_info=True)


def _mpris_sync_position(self, force=False):
    svc = getattr(self, "_mpris", None)
    if svc is None:
        return
    try:
        svc.sync_position(force=bool(force))
    except Exception:
        logger.debug("MPRIS sync_position failed", exc_info=True)


def _mpris_sync_volume(self):
    svc = getattr(self, "_mpris", None)
    if svc is None:
        return
    try:
        svc.sync_volume()
    except Exception:
        logger.debug("MPRIS sync_volume failed", exc_info=True)


def _mpris_emit_seeked(self, position_seconds=None):
    svc = getattr(self, "_mpris", None)
    if svc is None:
        return
    try:
        svc.emit_seeked(position_seconds=position_seconds)
    except Exception:
        logger.debug("MPRIS emit_seeked failed", exc_info=True)

