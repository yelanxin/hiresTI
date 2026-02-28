#!/usr/bin/env bash

set -euo pipefail

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-18473}"
API_URL="${API_URL:-http://${API_HOST}:${API_PORT}/rpc}"
HEALTH_URL="${HEALTH_URL:-http://${API_HOST}:${API_PORT}/health}"
API_KEY="${API_KEY:-eB8f2-7rpaWaE9nYpGeKHfyKjSpFMT4C3Cyimm8GH8I}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required but was not found." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found." >&2
  exit 1
fi

rpc_call() {
  local payload="$1"
  curl -sS "${API_URL}" \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer ${API_KEY}" \
    -d "${payload}"
}

wait_for_ready_player_state() {
  local attempts="${1:-10}"
  local delay_s="${2:-0.5}"
  local response=""
  local i

  for ((i = 1; i <= attempts; i++)); do
    response="$(rpc_call '{"jsonrpc":"2.0","id":5,"method":"player.get_state","params":{}}')"
    if STATE_JSON="${response}" python3 - <<'PY' >/dev/null 2>&1
import json
import os
import sys

payload = json.loads(os.environ["STATE_JSON"])
result = payload.get("result", {})
is_playing = bool(result.get("is_playing"))
position = float(result.get("position_seconds") or 0.0)
sys.exit(0 if (is_playing or position > 0.0) else 1)
PY
    then
      printf '%s\n' "${response}"
      return 0
    fi
    sleep "${delay_s}"
  done

  printf '%s\n' "${response}"
  return 0
}

print_json() {
  python3 -m json.tool
}

require_json() {
  local raw="$1"
  if [[ -z "${raw}" ]]; then
    echo "Empty response from remote API." >&2
    exit 1
  fi
  printf '%s\n' "${raw}" | print_json
}

echo "== Health =="
HEALTH_RESPONSE="$(curl -sS "${HEALTH_URL}" || true)"
if [[ -z "${HEALTH_RESPONSE}" ]]; then
  echo "Failed to reach remote API health endpoint: ${HEALTH_URL}" >&2
  echo "Make sure Remote Control is enabled in Settings and the host/port are correct." >&2
  exit 1
fi
require_json "${HEALTH_RESPONSE}"
echo

echo "== Player State (before) =="
STATE_BEFORE="$(rpc_call '{"jsonrpc":"2.0","id":1,"method":"player.get_state","params":{}}')"
printf '%s\n' "${STATE_BEFORE}" > /tmp/hiresti_remote_state_before.json
require_json "${STATE_BEFORE}"
echo

echo "== Match Tracks =="
MATCH_RESPONSE="$(rpc_call '{
  "jsonrpc":"2.0",
  "id":2,
  "method":"search.match_tracks",
  "params":{
    "items":[
      {"title":"Blinding Lights","artist":"The Weeknd"},
      {"title":"Hello","artist":"Adele"},
      {"title":"Someone Like You","artist":"Adele"}
    ]
  }
}')"
printf '%s\n' "${MATCH_RESPONSE}" > /tmp/hiresti_remote_match_tracks.json
require_json "${MATCH_RESPONSE}"
echo

TRACK_IDS="$(MATCH_RESPONSE_JSON="${MATCH_RESPONSE}" python3 - <<'PY'
import json
import os
import sys

payload = json.loads(os.environ["MATCH_RESPONSE_JSON"])
items = payload.get("result", {}).get("results", [])
track_ids = []
for item in items:
    track = item.get("track") or {}
    track_id = str(track.get("id") or "").strip()
    if track_id:
        track_ids.append(track_id)
if len(track_ids) < 3:
    raise SystemExit(f"Expected 3 matched track ids, got {len(track_ids)}")
print(json.dumps(track_ids))
PY
)"

echo "Matched track ids: ${TRACK_IDS}"
echo

echo "== Replace Queue With 3 Tracks =="
QUEUE_REPLACE_PAYLOAD="$(TRACK_IDS_JSON="${TRACK_IDS}" python3 - <<'PY'
import json
import os

track_ids = json.loads(os.environ["TRACK_IDS_JSON"])
payload = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "queue.replace_with_track_ids",
    "params": {
        "track_ids": track_ids,
        "autoplay": True,
        "start_index": 0,
    },
}
print(json.dumps(payload))
PY
)"
QUEUE_REPLACE_RESPONSE="$(rpc_call "${QUEUE_REPLACE_PAYLOAD}")"
printf '%s\n' "${QUEUE_REPLACE_RESPONSE}" > /tmp/hiresti_remote_queue_replace.json
require_json "${QUEUE_REPLACE_RESPONSE}"
echo

echo "== Queue Get =="
QUEUE_GET_RESPONSE="$(rpc_call '{"jsonrpc":"2.0","id":4,"method":"queue.get","params":{}}')"
printf '%s\n' "${QUEUE_GET_RESPONSE}" > /tmp/hiresti_remote_queue_get.json
require_json "${QUEUE_GET_RESPONSE}"
echo

echo "== Player State (after) =="
STATE_AFTER="$(wait_for_ready_player_state 12 0.5)"
printf '%s\n' "${STATE_AFTER}" > /tmp/hiresti_remote_state_after.json
require_json "${STATE_AFTER}"
echo

echo "Smoke test complete."
echo "Saved raw responses to:"
echo "  /tmp/hiresti_remote_state_before.json"
echo "  /tmp/hiresti_remote_match_tracks.json"
echo "  /tmp/hiresti_remote_queue_replace.json"
echo "  /tmp/hiresti_remote_queue_get.json"
echo "  /tmp/hiresti_remote_state_after.json"
