import logging
import os
import time
from contextlib import contextmanager


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def viz_perf_enabled() -> bool:
    return _parse_bool_env("HIRESTI_VIZ_PERF", False)


class VizPerfWindow:
    def __init__(
        self,
        scope: str,
        logger_obj: logging.Logger | None = None,
        *,
        enabled: bool | None = None,
        log_interval_s: float = 2.0,
        now_fn=None,
        timer_fn=None,
    ):
        self.scope = str(scope or "viz")
        self.logger = logger_obj or logging.getLogger(__name__)
        self._enabled_override = enabled
        self._log_interval_s = max(0.1, float(log_interval_s or 2.0))
        self._now_fn = now_fn or time.monotonic
        self._timer_fn = timer_fn or time.perf_counter
        self._stats = {}
        self._last_flush_ts = float(self._now_fn())

    def is_enabled(self) -> bool:
        if self._enabled_override is not None:
            return bool(self._enabled_override)
        return viz_perf_enabled()

    def snapshot(self) -> dict:
        out = {}
        for name, stats in self._stats.items():
            calls = int(stats["calls"])
            total_ms = float(stats["total_ms"])
            out[name] = {
                "calls": calls,
                "total_ms": total_ms,
                "avg_ms": (total_ms / float(calls)) if calls > 0 else 0.0,
                "max_ms": float(stats["max_ms"]),
            }
        return out

    def reset(self) -> None:
        self._stats.clear()
        self._last_flush_ts = float(self._now_fn())

    def record_ms(self, name: str, dt_ms: float, now: float | None = None) -> None:
        if not self.is_enabled():
            return
        metric = str(name or "unknown")
        entry = self._stats.get(metric)
        if entry is None:
            entry = {"calls": 0, "total_ms": 0.0, "max_ms": 0.0}
            self._stats[metric] = entry
        entry["calls"] += 1
        entry["total_ms"] += float(dt_ms)
        entry["max_ms"] = max(float(entry["max_ms"]), float(dt_ms))
        self.flush_if_due(now=now)

    def flush_if_due(self, now: float | None = None) -> None:
        if not self.is_enabled():
            return
        if not self._stats:
            return
        ts = float(self._now_fn() if now is None else now)
        if (ts - self._last_flush_ts) < self._log_interval_s:
            return
        parts = []
        for name, stats in sorted(
            self._stats.items(),
            key=lambda item: (-float(item[1]["total_ms"]), item[0]),
        ):
            calls = int(stats["calls"])
            total_ms = float(stats["total_ms"])
            avg_ms = total_ms / float(calls) if calls > 0 else 0.0
            parts.append(
                f"{name} calls={calls} total={total_ms:.2f}ms avg={avg_ms:.2f}ms max={float(stats['max_ms']):.2f}ms"
            )
        self.logger.info("VIZ PERF %s: %s", self.scope, " | ".join(parts))
        self._stats.clear()
        self._last_flush_ts = ts

    @contextmanager
    def track(self, name: str):
        if not self.is_enabled():
            yield
            return
        start = float(self._timer_fn())
        try:
            yield
        finally:
            end = float(self._timer_fn())
            self.record_ms(name, (end - start) * 1000.0)
