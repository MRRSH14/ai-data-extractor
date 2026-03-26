#!/usr/bin/env bash
set -euo pipefail

# Dev bootstrap:
# - resolves stack outputs (API URL, User Pool ID, User Pool Client ID)
# - creates/updates two users with tenant attributes
# - logs in test_user and demo_user
# - calls dev_test_endpoints.sh

STACK_NAME="${STACK_NAME:-InfraStack}"
REGION="${REGION:-us-east-1}"

TEST_EMAIL="test_user@example.com"
TEST_PASSWORD="TEST@12Three"
TEST_TENANT="test_tenant"

DEMO_EMAIL="demo_user@example.com"
DEMO_PASSWORD="DEMO@34Five"
DEMO_TENANT="demo_tenant"

echo "Resolving CloudFormation outputs from stack: $STACK_NAME ($REGION)"
stack_json="$(
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

if [[ -z "$API_URL" || -z "$USER_POOL_ID" || -z "$CLIENT_ID" ]]; then
  echo "Failed to resolve required stack outputs."
  echo "API_URL='$API_URL' USER_POOL_ID='$USER_POOL_ID' CLIENT_ID='$CLIENT_ID'"
  exit 1
fi

echo "API_URL=$API_URL"
echo "USER_POOL_ID=$USER_POOL_ID"
echo "CLIENT_ID=$CLIENT_ID"

ensure_user() {
  local username="$1"
  local password="$2"
  local tenant="$3"

  if aws cognito-idp admin-get-user --user-pool-id "$USER_POOL_ID" --username "$username" --region "$REGION" >/dev/null 2>&1; then
    echo "User exists: $username"
  else
    echo "Creating user: $username"
    aws cognito-idp admin-create-user \
      --user-pool-id "$USER_POOL_ID" \
      --username "$username" \
      --user-attributes Name=email,Value="$username" \
      --message-action SUPPRESS \
      --region "$REGION" >/dev/null
  fi

  # Ensure permanent password for non-interactive login.
  aws cognito-idp admin-set-user-password \
    --user-pool-id "$USER_POOL_ID" \
    --username "$username" \
    --password "$password" \
    --permanent \
    --region "$REGION" >/dev/null

  # Ensure required attributes.
  aws cognito-idp admin-update-user-attributes \
    --user-pool-id "$USER_POOL_ID" \
    --username "$username" \
    --user-attributes \
      Name=email,Value="$username" \
      Name=email_verified,Value=true \
      Name=custom:tenant_id,Value="$tenant" \
    --region "$REGION" >/dev/null

  echo "Updated user attributes: $username tenant=$tenant"
}

get_id_token() {
  local username="$1"
  local password="$2"
  local auth_json
  auth_json="$(
    aws cognito-idp initiate-auth \
      --region "$REGION" \
      --auth-flow USER_PASSWORD_AUTH \
      --client-id "$CLIENT_ID" \
      --auth-parameters USERNAME="$username",PASSWORD="$password" \
      --output json
  )"
  python3 - <<'PY' "$auth_json"
import json,sys
print(json.loads(sys.argv[1])["AuthenticationResult"]["IdToken"])
PY
}

ensure_user "$TEST_EMAIL" "$TEST_PASSWORD" "$TEST_TENANT"
ensure_user "$DEMO_EMAIL" "$DEMO_PASSWORD" "$DEMO_TENANT"

echo "Logging in users..."
TEST_ID_TOKEN="$(get_id_token "$TEST_EMAIL" "$TEST_PASSWORD")"
DEMO_ID_TOKEN="$(get_id_token "$DEMO_EMAIL" "$DEMO_PASSWORD")"

echo "Running endpoint test script..."
API_URL="$API_URL" TEST_ID_TOKEN="$TEST_ID_TOKEN" DEMO_ID_TOKEN="$DEMO_ID_TOKEN" \
  "$(dirname "$0")/dev_test_endpoints.sh"

echo "Done."
