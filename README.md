# ai-data-extractor

A **schema-driven async data extraction service** on AWS, bootstrapped from `platform-v1` of `aws-ai-platform-service`. The repository currently keeps the proven platform baseline (API Gateway HTTP API, Lambda, SQS, DynamoDB, DLQ, auth/tenancy, observability, idempotency) and is now focused on implementing the first extraction product workflow.

## What this project is

- **HTTP API** for health checks and task lifecycle (`POST /tasks`, `GET /tasks/{id}`), currently serving as the product backbone.
- **Asynchronous execution** via a **tasks queue** and a **worker Lambda** that updates task state in **DynamoDB**.
- **Infrastructure as code** with **AWS CDK** (Python) and a manual GitHub Actions deploy workflow.

See **[docs/architecture.md](docs/architecture.md)** for baseline diagrams and request flow. Product-specific extraction behavior is tracked in the implementation plan and will be added incrementally.

## Product direction (next)

The next product milestone is **extractor MVP (text-first) into structured JSON**:

- User submits `job_type="extract"` with inline text (`input.mode="text"`) plus desired result schema.
- Worker performs extraction and validates output shape.
- Task status and result are retrievable through the existing async task pattern.
- Deterministic malformed payload/output paths are treated as terminal `failed`; transient failures continue through retry/DLQ.
- Existing platform qualities (tenant isolation, observability, idempotency, DLQ) remain in place.

## Why this product exists

`ai-data-extractor` is a schema-driven, multi-tenant extraction backend that turns unstructured text/files into predictable JSON with production-grade reliability, security, and observability.

### When to use this vs ChatGPT UI

- Use **ChatGPT UI** for ad-hoc, human-driven, one-off extraction.
- Use **ai-data-extractor** when extraction must be automated, repeatable, auditable, and integrated into backend workflows.
- Choose this service when you need tenant isolation, idempotent task submission, retry/DLQ operations, and consistent result contracts.
- Use this platform when downstream systems require machine-consumable structured output at scale.

## Why this architecture

- **API Lambda** stays focused on validation, persistence, and enqueueing; it returns quickly with a `task_id` (**202 Accepted**).
- **SQS + worker Lambda** decouple submission from execution, give **automatic retries**, and route repeated failures to a **DLQ** for operator handling.
- **DynamoDB** holds **task state** so clients and operators can inspect progress without coupling to queue internals.

Rationale is recorded in [ADR 0001](docs/adrs/0001-async-task-pattern.md). DLQ handling choices are in [ADR 0002](docs/adrs/0002-dlq-manual-operation.md).

## Current endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness-style check (`{"ok": true}`). **Public** |
| `GET` | `/hello` | Sample query param `name` (demo / smoke). **Public** |
| `POST` | `/tasks` | Create an extraction task. MVP contract: `job_type="extract"` and text-mode input (`input.mode="text"`, `input.text`, `input.schema`). Returns **202** with task metadata; repeated logical requests by the same user/tenant return the existing task via server-side idempotency. **JWT required** |
| `GET` | `/tasks/{id}` | Return the task item from DynamoDB or **404**. **JWT required** |

**Security note:** API Gateway now uses a Cognito User Pool JWT authorizer for task routes, and task handlers enforce tenant ownership using JWT claims. `/health` and `/hello` remain public.

## Deploy flow

**Local CDK (typical):**

```bash
cd infra
python -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
npm install -g aws-cdk                              # if needed
cdk bootstrap aws://ACCOUNT/REGION                  # once per account/region
export DLQ_ALERT_EMAIL="ops@example.com"            # optional: SNS email for DLQ alarm
export BEDROCK_MODEL_ID="anthropic.claude-3-haiku-20240307-v1:0"  # optional now, required for live Bedrock extraction
export BEDROCK_REGION="us-east-1"                   # optional; defaults to stack region
cdk deploy
```

Worker IAM scopes `bedrock:InvokeModel` to resource ARNs derived from `BEDROCK_MODEL_ID` (foundation model ID, inference profile ID, or full ARN). The policy includes Bedrock compatibility variants needed for inference-profile-backed invokes.

Stack outputs include **ApiUrl**, **TasksQueueUrl**, **DeadLetterQueueUrl**, **TasksUserPoolId**, **TasksUserPoolClientId**, and related ARNs.

**CI:** [`.github/workflows/cdk-deploy.yml`](.github/workflows/cdk-deploy.yml) runs on **workflow_dispatch**, assumes an AWS role via OIDC, sets `DLQ_ALERT_EMAIL` from **GitHub Actions secrets**, and runs `cdk deploy` from the `infra/` directory.

### Required GitHub config

For Actions-based deploys, configure repository secrets in GitHub:

- `DLQ_ALERT_EMAIL` (optional, enables SNS email subscription for DLQ alarm)
- `BEDROCK_MODEL_ID` (required for live Bedrock extraction path; for some newer models, use an inference profile ID/ARN instead of direct foundation model ID)
- `BEDROCK_REGION` (recommended; defaults to stack region if omitted)

Also ensure the AWS IAM role used by GitHub OIDC trust policy allows this repository (`MRRSH14/ai-data-extractor`) for workflow runs (for example, `repo:MRRSH14/ai-data-extractor:ref:refs/heads/main` and/or `repo:MRRSH14/ai-data-extractor:ref:refs/heads/*` depending on your policy).

## Local development assumptions

- **Python 3.12** matches the Lambda runtime in CDK.
- Meaningful **local runs** of handlers usually assume **AWS credentials** and deployed resources (table name, queue URL) via environment variables, or you mock DynamoDB/SQS. There is no bundled Docker compose for localstack in this repo today.
- **Tests:** CDK unit tests live under `infra/tests/`; run them with whatever test runner you configure for the `infra` package (the repo’s `requirements.txt` is CDK-focused).

## Operational notes

- **Observability (logs, correlation IDs, alarms):** [docs/observability.md](docs/observability.md)
- **DLQ, redrive, alarms:** [docs/runbooks/dlq-and-alerts.md](docs/runbooks/dlq-and-alerts.md)
- **Helper script:** `scripts/dlq_redrive.py` (requires `boto3`)
- **Dev auth/test scripts:** `scripts/dev_setup.sh`, `scripts/dev_test_endpoints.sh`, `scripts/dev_onboard_user.sh`

Task statuses and the split between **DynamoDB status** and **SQS/DLQ** behavior are documented in **architecture** and the runbook; after max retries, a message can sit in the DLQ while DynamoDB may still show `retrying` until you redrive or update the record.

## Dev auth/testing scripts

For local development against a deployed stack, you can automate Cognito user setup/login and API smoke tests:

```bash
./scripts/dev_setup.sh
```

To onboard a single user manually (Option A: admin + script), use:

```bash
./scripts/dev_onboard_user.sh
```

What it does:

- resolves `ApiUrl`, `TasksUserPoolId`, and `TasksUserPoolClientId` from `InfraStack` outputs;
- ensures two users exist with tenant attributes:
  - `test_user@example.com` -> `test_tenant`
  - `demo_user@example.com` -> `demo_tenant`
- logs in both users and obtains JWTs;
- runs `scripts/dev_test_endpoints.sh` endpoint checks (public routes, protected routes, two extraction scenarios, and cross-tenant denial).

Prerequisites:

- AWS credentials/profile must allow Cognito admin APIs (`admin-create-user`, `admin-update-user-attributes`, `admin-set-user-password`) and CloudFormation read access for stack outputs.

You can run endpoint tests directly if you already have tokens:

```bash
API_URL="..." TEST_ID_TOKEN="..." DEMO_ID_TOKEN="..." ./scripts/dev_test_endpoints.sh
```

Smoke checks now validate:

- extractor scenario #1 (`invoice_id`, `amount`, `is_paid`)
- extractor scenario #2 (`po_number`, `vendor_name`, `item_count`, `has_late_fee`)
- `result_metadata` presence on completed tasks (`provider`, `model_id`, `processed_at`)

### Tenant onboarding acceptance check

Use this quick check after onboarding a user to confirm tenant isolation still works:

1. `POST /tasks` with the onboarded user token -> expect `202`.
2. `GET /tasks/{id}` with the same user token -> expect `200`.
3. `GET /tasks/{id}` with a token from a different tenant -> expect `403`.

### Idempotency behavior (server-side)

- `POST /tasks` computes a deterministic hash from caller/task inputs (`tenant_id`, `created_by`, `job_type`, canonicalized `input`) and uses that as an internal idempotency key.
- Idempotency records live in a dedicated DynamoDB table (`TaskIdempotencyTable`) with TTL (`expires_at`) set to **1 week**.
- First request creates/enqueues task as normal; same logical retry returns the existing task (no duplicate enqueue).

### Schema constraints (MVP now enforced)

For each schema field descriptor:

- `type`: one of `string`, `number`, `boolean`
- `required` (optional): boolean; missing required output field causes terminal `failed`
- `enum` (optional): non-empty array of allowed values; API validates enum element types against `type`, and worker enforces the constraint after normalization/coercion

## Roadmap summary

| Phase | Focus |
|-------|--------|
| **Current** | Platform baseline from `platform-v1`: async API + worker, auth/tenancy, observability, idempotency, and operational docs. |
| **Next** | Extractor MVP: schema-driven extraction contract, worker extraction flow, result persistence/retrieval, and validation/error semantics. |
| **Later** | Advanced extraction features (larger files, richer formats, quality controls, cost/performance tuning, optional UI/workflow integrations). |

## Documentation index

- [Architecture](docs/architecture.md)
- [MVP extractor contract](docs/mvp-extractor.md)
- [Observability](docs/observability.md)
- [Implementation plan (living roadmap & checklist)](docs/implementation-plan.md)
- [ADR 0001 — Async task pattern](docs/adrs/0001-async-task-pattern.md)
- [ADR 0002 — DLQ manual operation](docs/adrs/0002-dlq-manual-operation.md)
- [ADR 0003 — Auth and tenancy](docs/adrs/0003-auth-and-tenancy.md)
- [DLQ runbook](docs/runbooks/dlq-and-alerts.md)
