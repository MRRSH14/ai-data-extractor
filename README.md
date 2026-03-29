# aws-ai-platform-service

A **production-style async task API** on AWS: API Gateway HTTP API, Lambda, SQS, DynamoDB, and a dead-letter queue with optional email alerts. The codebase is intentionally a **foundation**—clear boundaries for later **auth, tenancy, observability, and AI workloads**—not a complete AI product.

## What this project is

- **HTTP API** for health checks, a sample `hello` route, and **task lifecycle**: create a task (`POST /tasks`), poll status (`GET /tasks/{id}`).
- **Asynchronous execution** via a **tasks queue** and a **worker Lambda** that updates task state in **DynamoDB**.
- **Infrastructure as code** with **AWS CDK** (Python) and a **manual** GitHub Actions deploy workflow.

See **[docs/architecture.md](docs/architecture.md)** for diagrams, request flow, task states, and current limitations.

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
| `POST` | `/tasks` | Create a task. JSON body: `job_type` (string), `input` (any). Returns **202** with task including `task_id` and `status`. **JWT required** |
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
cdk deploy
```

Stack outputs include **ApiUrl**, **TasksQueueUrl**, **DeadLetterQueueUrl**, **TasksUserPoolId**, **TasksUserPoolClientId**, and related ARNs.

**CI:** [`.github/workflows/cdk-deploy.yml`](.github/workflows/cdk-deploy.yml) runs on **workflow_dispatch**, assumes an AWS role via OIDC, sets `DLQ_ALERT_EMAIL` from **GitHub Actions secrets**, and runs `cdk deploy` from the `infra/` directory.

## Local development assumptions

- **Python 3.12** matches the Lambda runtime in CDK.
- Meaningful **local runs** of handlers usually assume **AWS credentials** and deployed resources (table name, queue URL) via environment variables, or you mock DynamoDB/SQS. There is no bundled Docker compose for localstack in this repo today.
- **Tests:** CDK unit tests live under `infra/tests/`; run them with whatever test runner you configure for the `infra` package (the repo’s `requirements.txt` is CDK-focused).

## Operational notes

- **Observability (logs, correlation IDs, alarms):** [docs/observability.md](docs/observability.md)
- **DLQ, redrive, alarms:** [docs/runbooks/dlq-and-alerts.md](docs/runbooks/dlq-and-alerts.md)
- **Helper script:** `scripts/dlq_redrive.py` (requires `boto3`)
- **Dev auth/test scripts:** `scripts/dev_setup.sh`, `scripts/dev_test_endpoints.sh`

Task statuses and the split between **DynamoDB status** and **SQS/DLQ** behavior are documented in **architecture** and the runbook; after max retries, a message can sit in the DLQ while DynamoDB may still show `retrying` until you redrive or update the record.

## Dev auth/testing scripts

For local development against a deployed stack, you can automate Cognito user setup/login and API smoke tests:

```bash
./scripts/dev_setup.sh
```

What it does:

- resolves `ApiUrl`, `TasksUserPoolId`, and `TasksUserPoolClientId` from `InfraStack` outputs;
- ensures two users exist with tenant attributes:
  - `test_user@example.com` -> `test_tenant`
  - `demo_user@example.com` -> `demo_tenant`
- logs in both users and obtains JWTs;
- runs `scripts/dev_test_endpoints.sh` endpoint checks (public routes, protected routes, and cross-tenant denial).

Prerequisites:

- AWS credentials/profile must allow Cognito admin APIs (`admin-create-user`, `admin-update-user-attributes`, `admin-set-user-password`) and CloudFormation read access for stack outputs.

You can run endpoint tests directly if you already have tokens:

```bash
API_URL="..." TEST_ID_TOKEN="..." DEMO_ID_TOKEN="..." ./scripts/dev_test_endpoints.sh
```

## Roadmap summary

| Phase | Focus |
|-------|--------|
| **Current** | Async skeleton + auth boundary: API + SQS + worker + DynamoDB + DLQ + Cognito JWT protection on task routes; docs and ADRs. |
| **Next** | Strengthen tenant onboarding/migration details; extend **metrics/dashboards** as usage grows (structured logs and correlation IDs are in place—see [observability](docs/observability.md)). |
| **Later** | **AI layer**: provider abstraction, task payload for model work, worker execution, persistence, cost/guardrails—**after** the platform boundary is credible. |

## Documentation index

- [Architecture](docs/architecture.md)
- [Observability](docs/observability.md)
- [Implementation plan (living roadmap & checklist)](docs/implementation-plan.md)
- [ADR 0001 — Async task pattern](docs/adrs/0001-async-task-pattern.md)
- [ADR 0002 — DLQ manual operation](docs/adrs/0002-dlq-manual-operation.md)
- [ADR 0003 — Auth and tenancy](docs/adrs/0003-auth-and-tenancy.md)
- [DLQ runbook](docs/runbooks/dlq-and-alerts.md)
