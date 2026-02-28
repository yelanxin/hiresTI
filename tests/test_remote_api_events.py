import io
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.remote_api import _RemoteRequestHandler
from services.remote_events import RemoteEventHub


def test_remote_event_hub_delivers_latest_event_to_subscriber():
    hub = RemoteEventHub()
    subscription_id, event_queue = hub.subscribe()

    hub.publish("queue_changed", {"reason": "unit_test", "queue_size": 3})
    event = event_queue.get(timeout=1.0)
    hub.unsubscribe(subscription_id)

    assert event["type"] == "queue_changed"
    assert event["payload"]["reason"] == "unit_test"
    assert event["payload"]["queue_size"] == 3


def test_write_sse_formats_event_block():
    sink = io.BytesIO()
    dummy = SimpleNamespace(wfile=sink)

    _RemoteRequestHandler._write_sse(dummy, "ready", {"ok": True}, event_id="7")

    payload = sink.getvalue().decode("utf-8")
    assert "id: 7\n" in payload
    assert "event: ready\n" in payload
    assert 'data: {"ok": true}\n' in payload
