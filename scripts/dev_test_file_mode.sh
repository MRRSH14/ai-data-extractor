#!/usr/bin/env bash
set -euo pipefail

# Required env vars:
#   API_URL
#   TEST_ID_TOKEN
#   INPUT_BUCKET
#
# Example setup:
#   export API_URL="https://....execute-api.us-east-1.amazonaws.com"
#   export TEST_ID_TOKEN="eyJ..."
#   export INPUT_BUCKET="infrastack-inputdocumentsbucket..."

if [[ -z "${API_URL:-}" ]]; then
  echo "Missing API_URL"
  exit 1
fi

if [[ -z "${TEST_ID_TOKEN:-}" ]]; then
  echo "Missing TEST_ID_TOKEN"
  exit 1
fi

if [[ -z "${INPUT_BUCKET:-}" ]]; then
  echo "Missing INPUT_BUCKET"
  exit 1
fi

if ! command -v aws >/dev/null 2>&1; then
  echo "Missing aws CLI"
  exit 1
fi

create_task() {
  local key="$1"
  local payload
  payload="$(
    python3 - <<'PY' "$key" "$INPUT_BUCKET"
import json,sys
key = sys.argv[1]
bucket = sys.argv[2]
payload = {
    "job_type": "extract",
    "input": {
        "mode": "file",
        "file": {"source": "s3", "bucket": bucket, "key": key},
        "schema": {
            "invoice_id": {"type": "string"},
            "amount": {"type": "number"},
            "is_paid": {"type": "boolean"},
        },
    },
}
print(json.dumps(payload, separators=(",", ":")))
PY
  )"

  curl -sS -X POST "$API_URL/tasks" \
    -H "Authorization: Bearer $TEST_ID_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$payload"
}

poll_terminal() {
  local task_id="$1"
  local max_attempts=20
  local attempt=1
  while [[ "$attempt" -le "$max_attempts" ]]; do
    local resp
    resp="$(curl -sS -X GET "$API_URL/tasks/$task_id" -H "Authorization: Bearer $TEST_ID_TOKEN")"
    local status
    status="$(
      python3 - <<'PY' "$resp"
import json,sys
print(json.loads(sys.argv[1]).get("status",""))
PY
    )"
    if [[ "$status" == "completed" || "$status" == "failed" ]]; then
      echo "$resp"
      return 0
    fi
    sleep 1
    attempt=$((attempt + 1))
  done
  echo '{"status":"timeout"}'
}

summarize_case() {
  local case_name="$1"
  local resp="$2"
  python3 - <<'PY' "$case_name" "$resp"
import json,sys
name = sys.argv[1]
obj = json.loads(sys.argv[2])
status = obj.get("status")
print(f"[{name}] status={status}")
if status == "completed":
    keys = sorted((obj.get("result") or {}).keys())
    print(f"[{name}] result_keys={keys}")
if status == "failed":
    print(f"[{name}] error={obj.get('error_message','')}")
PY
}

unix_ts="$(date +%s)"
valid_key="smoke/valid-${unix_ts}.txt"
non_utf8_key="smoke/nonutf-${unix_ts}.bin"
missing_key="smoke/does-not-exist-${unix_ts}.txt"

printf 'Invoice INV-100 amount 42.5 paid yes' > /tmp/file-mode-valid.txt
python3 - <<'PY'
from pathlib import Path
Path("/tmp/file-mode-nonutf.bin").write_bytes(b"\xff\xfe\x00\x00")
PY

aws s3 cp /tmp/file-mode-valid.txt "s3://$INPUT_BUCKET/$valid_key" >/dev/null
aws s3 cp /tmp/file-mode-nonutf.bin "s3://$INPUT_BUCKET/$non_utf8_key" >/dev/null

echo "Running file-mode smoke tests against: $API_URL"
echo "Using input bucket: $INPUT_BUCKET"

valid_create_resp="$(create_task "$valid_key")"
valid_task_id="$(
  python3 - <<'PY' "$valid_create_resp"
import json,sys
print(json.loads(sys.argv[1]).get("task_id",""))
PY
)"
valid_terminal_resp="$(poll_terminal "$valid_task_id")"
summarize_case "valid_utf8" "$valid_terminal_resp"

missing_create_resp="$(create_task "$missing_key")"
missing_task_id="$(
  python3 - <<'PY' "$missing_create_resp"
import json,sys
print(json.loads(sys.argv[1]).get("task_id",""))
PY
)"
missing_terminal_resp="$(poll_terminal "$missing_task_id")"
summarize_case "missing_key" "$missing_terminal_resp"

nonutf_create_resp="$(create_task "$non_utf8_key")"
nonutf_task_id="$(
  python3 - <<'PY' "$nonutf_create_resp"
import json,sys
print(json.loads(sys.argv[1]).get("task_id",""))
PY
)"
nonutf_terminal_resp="$(poll_terminal "$nonutf_task_id")"
summarize_case "non_utf8" "$nonutf_terminal_resp"

echo "File-mode smoke checks complete."
