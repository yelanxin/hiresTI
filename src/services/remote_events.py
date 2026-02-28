"""Thread-safe event fanout for remote control subscribers."""

from __future__ import annotations

import queue
import threading
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RemoteEventHub:
    def __init__(self, max_queue_size: int = 64):
        self.max_queue_size = max(8, int(max_queue_size or 64))
        self._lock = threading.Lock()
        self._next_subscription_id = 1
        self._next_event_id = 1
        self._subscribers = {}

    def subscribe(self):
        q = queue.Queue(maxsize=self.max_queue_size)
        with self._lock:
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            self._subscribers[subscription_id] = q
        return subscription_id, q

    def unsubscribe(self, subscription_id):
        with self._lock:
            self._subscribers.pop(int(subscription_id), None)

    def publish(self, event_type: str, payload=None):
        with self._lock:
            event_id = self._next_event_id
            self._next_event_id += 1
            subscribers = list(self._subscribers.values())

        event = {
            "id": str(event_id),
            "type": str(event_type or "message"),
            "timestamp": _utc_now_iso(),
            "payload": payload if isinstance(payload, dict) else {},
        }
        for q in subscribers:
            try:
                q.put_nowait(event)
                continue
            except queue.Full:
                pass
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(event)
            except queue.Full:
                pass
        return event

    def close_all(self):
        with self._lock:
            subscribers = list(self._subscribers.values())
            self._subscribers.clear()
        for q in subscribers:
            try:
                q.put_nowait(None)
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass
