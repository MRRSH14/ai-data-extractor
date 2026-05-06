#!/usr/bin/env bash
set -euo pipefail

# One-command smoke runner for local/dev environments.
# It prepares auth + env and runs text/file smoke scripts.
#
# Usage:
#   scripts/dev_smoke_all.sh
#   scripts/dev_smoke_all.sh --text-only
#   scripts/dev_smoke_all.sh --file-only
#   scripts/dev_smoke_all.sh --skip-login
#
# Optional env overrides:
#   STACK_NAME (default: InfraStack)
#   REGION     (default: us-east-1)
#   PROFILE    (default: mrrsh)

STACK_NAME="${STACK_NAME:-InfraStack}"
REGION="${REGION:-us-east-1}"
PROFILE="${PROFILE:-mrrsh}"

RUN_TEXT=true
RUN_FILE=true
SKIP_LOGIN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --text-only)
      RUN_TEXT=true
      RUN_FILE=false
      shift
      ;;
    --file-only)
      RUN_TEXT=false
      RUN_FILE=true
      shift
      ;;
    --skip-login)
      SKIP_LOGIN=true
      shift
      ;;
    -h|--help)
      sed -n '1,30p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if ! command -v aws >/dev/null 2>&1; then
  echo "Missing aws CLI"
  exit 1
fi

if [[ "$SKIP_LOGIN" == "false" ]]; then
  echo "Ensuring AWS SSO session for profile: $PROFILE"
  aws sso login --profile "$PROFILE" >/dev/null
fi

echo "Resolving stack outputs: $STACK_NAME ($REGION)"
stack_json="$(
  AWS_PROFILE="$PROFILE" AWS_REGION="$REGION" \
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --output json
)"

API_URL="$(
  python3 - <<'PY' "$stack_json"
import json,sys
s=json.loads(sys.argv[1])["Stacks"][0]["Outputs"]
print(next((o["OutputValue"] for o in s if o["OutputKey"]=="ApiUrl"),""))
PY
)"

USER_POOL_ID="$(
  python3 - <<'PY' "$stack_json"
import json,sys
s=json.loads(sys.argv[1])["Stacks"][0]["Outputs"]
print(next((o["OutputValue"] for o in s if o["OutputKey"]=="TasksUserPoolId"),""))
PY
)"

CLIENT_ID="$(
  python3 - <<'PY' "$stack_json"
import json,sys
s=json.loads(sys.argv[1])["Stacks"][0]["Outputs"]
print(next((o["OutputValue"] for o in s if o["OutputKey"]=="TasksUserPoolClientId"),""))
PY
)"

INPUT_BUCKET="$(
  python3 - <<'PY' "$stack_json"
import json,sys
s=json.loads(sys.argv[1])["Stacks"][0]["Outputs"]
print(next((o["OutputValue"] for o in s if o["OutputKey"]=="InputDocumentsBucketName"),""))
PY
)"

if [[ -z "$API_URL" || -z "$CLIENT_ID" ]]; then
  echo "Failed to resolve required outputs (ApiUrl/TasksUserPoolClientId)."
  exit 1
fi

if [[ "$RUN_FILE" == "true" && -z "$INPUT_BUCKET" ]]; then
  echo "Missing InputDocumentsBucketName stack output; file-mode smoke cannot run."
  exit 1
fi

echo "Getting test/demo ID tokens via Cognito..."
TEST_ID_TOKEN="$(
  AWS_PROFILE="$PROFILE" AWS_REGION="$REGION" \
  aws cognito-idp initiate-auth \
    --region "$REGION" \
    --auth-flow USER_PASSWORD_AUTH \
    --client-id "$CLIENT_ID" \
    --auth-parameters USERNAME="test_user@example.com",PASSWORD="TEST@12Three" \
    --query "AuthenticationResult.IdToken" \
    --output text
)"

DEMO_ID_TOKEN="$(
  AWS_PROFILE="$PROFILE" AWS_REGION="$REGION" \
  aws cognito-idp initiate-auth \
    --region "$REGION" \
    --auth-flow USER_PASSWORD_AUTH \
    --client-id "$CLIENT_ID" \
    --auth-parameters USERNAME="demo_user@example.com",PASSWORD="DEMO@34Five" \
    --query "AuthenticationResult.IdToken" \
    --output text
)"

if [[ -z "$TEST_ID_TOKEN" ]]; then
  echo "Failed to get TEST_ID_TOKEN"
  exit 1
fi

export AWS_PROFILE="$PROFILE"
export AWS_REGION="$REGION"
export API_URL
export USER_POOL_ID
export CLIENT_ID
export TEST_ID_TOKEN
export DEMO_ID_TOKEN
export INPUT_BUCKET

echo "API_URL=$API_URL"
echo "INPUT_BUCKET=${INPUT_BUCKET:-<not-needed>}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$RUN_TEXT" == "true" ]]; then
  echo "Running text-mode smoke checks..."
  "$script_dir/dev_test_endpoints.sh"
fi

if [[ "$RUN_FILE" == "true" ]]; then
  echo "Running file-mode smoke checks..."
  "$script_dir/dev_test_file_mode.sh"
fi

echo "All requested smoke checks finished."
