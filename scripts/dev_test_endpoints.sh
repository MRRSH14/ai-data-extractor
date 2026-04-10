#!/usr/bin/env bash
set -euo pipefail

# Required env vars:
#   API_URL
#   TEST_ID_TOKEN
# Optional:
#   DEMO_ID_TOKEN

if [[ -z "${API_URL:-}" ]]; then
  echo "Missing API_URL"
  exit 1
fi

if [[ -z "${TEST_ID_TOKEN:-}" ]]; then
  echo "Missing TEST_ID_TOKEN"
  exit 1
fi

http_status() {
  local method="$1"
  local url="$2"
  local auth="${3:-}"
  local body="${4:-}"
  local tmp_body
  tmp_body="$(mktemp)"

  local code
  if [[ -n "$auth" && -n "$body" ]]; then
    code="$(curl -sS -o "$tmp_body" -w "%{http_code}" -X "$method" "$url" \
      -H "Authorization: Bearer $auth" \
      -H "Content-Type: application/json" \
      -d "$body")"
  elif [[ -n "$auth" ]]; then
    code="$(curl -sS -o "$tmp_body" -w "%{http_code}" -X "$method" "$url" \
      -H "Authorization: Bearer $auth")"
  elif [[ -n "$body" ]]; then
    code="$(curl -sS -o "$tmp_body" -w "%{http_code}" -X "$method" "$url" \
      -H "Content-Type: application/json" \
      -d "$body")"
  else
    code="$(curl -sS -o "$tmp_body" -w "%{http_code}" -X "$method" "$url")"
  fi

  local resp
  resp="$(cat "$tmp_body")"
  rm -f "$tmp_body"
  echo "$code" "$resp"
}

assert_status() {
  local name="$1"
  local got="$2"
  local want="$3"
  if [[ "$got" != "$want" ]]; then
    echo "[FAIL] $name expected $want got $got"
    exit 1
  fi
  echo "[PASS] $name ($got)"
}

echo "Running endpoint checks against: $API_URL"

# 1) Public health
read -r code resp < <(http_status GET "$API_URL/health")
assert_status "GET /health public" "$code" "200"

# 2) Public hello
read -r code resp < <(http_status GET "$API_URL/hello?name=dev")
assert_status "GET /hello public" "$code" "200"

# 3) Protected create without token should fail
read -r code resp < <(http_status POST "$API_URL/tasks" "" '{"job_type":"extract","input":{"mode":"text","text":"Invoice 100 total 42.5 paid","schema":{"invoice_id":{"type":"string"},"amount":{"type":"number"},"is_paid":{"type":"boolean"}}}}')
if [[ "$code" != "401" && "$code" != "403" ]]; then
  echo "[FAIL] POST /tasks without token expected 401/403 got $code"
  exit 1
fi
echo "[PASS] POST /tasks requires token ($code)"

# 4) Protected create with test token should pass
extract_payload='{"job_type":"extract","input":{"mode":"text","text":"Invoice 100 total 42.5 paid","schema":{"invoice_id":{"type":"string"},"amount":{"type":"number"},"is_paid":{"type":"boolean"}}}}'
read -r code resp < <(http_status POST "$API_URL/tasks" "$TEST_ID_TOKEN" "$extract_payload")
assert_status "POST /tasks with test token" "$code" "202"

task_id="$(
  python3 - <<'PY' "$resp"
import json,sys
payload = json.loads(sys.argv[1])
print(payload.get("task_id",""))
PY
)"

if [[ -z "$task_id" ]]; then
  echo "[FAIL] Could not parse task_id from create response"
  exit 1
fi
echo "[INFO] Created task_id=$task_id"

# 4b) Repeat same create request should be idempotent (same task_id)
read -r code resp < <(http_status POST "$API_URL/tasks" "$TEST_ID_TOKEN" "$extract_payload")
if [[ "$code" != "200" && "$code" != "202" ]]; then
  echo "[FAIL] POST /tasks idempotent retry expected 200/202 got $code"
  exit 1
fi
retry_task_id="$(
  python3 - <<'PY' "$resp"
import json,sys
payload = json.loads(sys.argv[1])
print(payload.get("task_id",""))
PY
)"
if [[ -z "$retry_task_id" ]]; then
  echo "[FAIL] Could not parse task_id from idempotent retry response"
  exit 1
fi
if [[ "$retry_task_id" != "$task_id" ]]; then
  echo "[FAIL] Idempotent retry returned different task_id: $retry_task_id (expected $task_id)"
  exit 1
fi
echo "[PASS] POST /tasks idempotent retry returns same task_id ($retry_task_id)"

# 5) Poll task until terminal state and validate extractor result
poll_attempt=1
max_attempts=10
last_resp=""
while [[ "$poll_attempt" -le "$max_attempts" ]]; do
  read -r code resp < <(http_status GET "$API_URL/tasks/$task_id" "$TEST_ID_TOKEN")
  assert_status "GET /tasks/{id} same tenant (attempt $poll_attempt)" "$code" "200"
  status="$(
    python3 - <<'PY' "$resp"
import json,sys
payload = json.loads(sys.argv[1])
print(payload.get("status",""))
PY
  )"
  last_resp="$resp"
  if [[ "$status" == "completed" || "$status" == "failed" ]]; then
    break
  fi
  sleep 1
  poll_attempt=$((poll_attempt + 1))
done

if [[ -z "$last_resp" ]]; then
  echo "[FAIL] Empty task response while polling"
  exit 1
fi

python3 - <<'PY' "$last_resp"
import json,sys
payload = json.loads(sys.argv[1])
status = payload.get("status")
if status != "completed":
    print(f"[FAIL] Expected completed status, got {status!r}")
    sys.exit(1)
result = payload.get("result")
if not isinstance(result, dict):
    print("[FAIL] Expected result object on completed task")
    sys.exit(1)
for key in ("invoice_id", "amount", "is_paid"):
    if key not in result:
        print(f"[FAIL] Missing expected result key: {key}")
        sys.exit(1)
if not isinstance(result.get("amount"), (int, float)):
    print("[FAIL] result.amount must be numeric")
    sys.exit(1)
if not isinstance(result.get("is_paid"), bool):
    print("[FAIL] result.is_paid must be boolean")
    sys.exit(1)
print("[PASS] Extractor task completed with expected result shape")
PY

# 6) Optional cross-tenant check
if [[ -n "${DEMO_ID_TOKEN:-}" ]]; then
  read -r code resp < <(http_status GET "$API_URL/tasks/$task_id" "$DEMO_ID_TOKEN")
  assert_status "GET /tasks/{id} cross-tenant denied" "$code" "403"
fi

echo "All endpoint checks passed."
