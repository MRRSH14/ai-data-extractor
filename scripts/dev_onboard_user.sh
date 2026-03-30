#!/usr/bin/env bash
set -euo pipefail

# Manual tenant onboarding (Option A):
# - resolves User Pool ID from InfraStack outputs
# - creates user if missing
# - sets permanent password
# - updates custom:tenant_id
#
# Usage:
#   ./scripts/dev_onboard_user.sh
# Optional env:
#   STACK_NAME (default InfraStack)
#   REGION (default us-east-1)

STACK_NAME="${STACK_NAME:-InfraStack}"
REGION="${REGION:-us-east-1}"

echo "Resolving User Pool output from stack: $STACK_NAME ($REGION)"
stack_json="$(
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --output json
)"

USER_POOL_ID="$(
  python3 - <<'PY' "$stack_json"
import json,sys
s=json.loads(sys.argv[1])["Stacks"][0]["Outputs"]
print(next((o["OutputValue"] for o in s if o["OutputKey"]=="TasksUserPoolId"),""))
PY
)"

if [[ -z "$USER_POOL_ID" ]]; then
  echo "Failed to resolve TasksUserPoolId from stack outputs."
  exit 1
fi

echo "USER_POOL_ID=$USER_POOL_ID"
echo

read -r -p "Email: " email
if [[ -z "${email:-}" ]]; then
  echo "Email is required."
  exit 1
fi

read -r -p "Username (blank = email): " username
username="${username:-$email}"

read -r -s -p "Password (will not echo): " password
echo
if [[ -z "${password:-}" ]]; then
  echo "Password is required."
  exit 1
fi

read -r -p "Tenant ID (custom:tenant_id): " tenant_id
if [[ -z "${tenant_id:-}" ]]; then
  echo "Tenant ID is required."
  exit 1
fi

echo
echo "About to onboard user:"
echo "  username=$username"
echo "  email=$email"
echo "  tenant_id=$tenant_id"
read -r -p "Continue? [y/N]: " confirm
if [[ "${confirm:-}" != "y" && "${confirm:-}" != "Y" ]]; then
  echo "Cancelled."
  exit 0
fi

if aws cognito-idp admin-get-user \
  --user-pool-id "$USER_POOL_ID" \
  --username "$username" \
  --region "$REGION" >/dev/null 2>&1; then
  echo "User exists: $username"
else
  echo "Creating user: $username"
  aws cognito-idp admin-create-user \
    --user-pool-id "$USER_POOL_ID" \
    --username "$username" \
    --user-attributes Name=email,Value="$email" \
    --message-action SUPPRESS \
    --region "$REGION" >/dev/null
fi

aws cognito-idp admin-set-user-password \
  --user-pool-id "$USER_POOL_ID" \
  --username "$username" \
  --password "$password" \
  --permanent \
  --region "$REGION" >/dev/null

aws cognito-idp admin-update-user-attributes \
  --user-pool-id "$USER_POOL_ID" \
  --username "$username" \
  --user-attributes \
    Name=email,Value="$email" \
    Name=email_verified,Value=true \
    Name=custom:tenant_id,Value="$tenant_id" \
  --region "$REGION" >/dev/null

echo "Onboarding complete: username=$username tenant_id=$tenant_id"
