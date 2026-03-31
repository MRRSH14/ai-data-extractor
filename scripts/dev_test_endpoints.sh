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
read -r code resp < <(http_status POST "$API_URL/tasks" "" '{"job_type":"demo","input":{"hello":"world"}}')
if [[ "$code" != "401" && "$code" != "403" ]]; then
  echo "[FAIL] POST /tasks without token expected 401/403 got $code"
  exit 1
fi
echo "[PASS] POST /tasks requires token ($code)"

# 4) Protected create with test token should pass
read -r code resp < <(http_status POST "$API_URL/tasks" "$TEST_ID_TOKEN" '{"job_type":"demo","input":{"hello":"world"}}')
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
read -r code resp < <(http_status POST "$API_URL/tasks" "$TEST_ID_TOKEN" '{"job_type":"demo","input":{"hello":"world"}}')
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

# 5) Protected get with same token should pass
read -r code resp < <(http_status GET "$API_URL/tasks/$task_id" "$TEST_ID_TOKEN")
assert_status "GET /tasks/{id} same tenant" "$code" "200"

# 6) Optional cross-tenant check
if [[ -n "${DEMO_ID_TOKEN:-}" ]]; then
  read -r code resp < <(http_status GET "$API_URL/tasks/$task_id" "$DEMO_ID_TOKEN")
  assert_status "GET /tasks/{id} cross-tenant denied" "$code" "403"
fi

echo "All endpoint checks passed."
