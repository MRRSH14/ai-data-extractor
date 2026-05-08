# Design decisions (showcase summary)

This document is the short, presentation-ready explanation of key engineering choices in `ai-data-extractor`.

## 1) Async API + worker architecture

Decision:
- use `API Gateway -> API Lambda -> SQS -> Worker Lambda -> DynamoDB`.

Why:
- returns fast `202` + `task_id` for clients;
- decouples request acceptance from variable-duration extraction work;
- gets retries and DLQ behavior through SQS primitives.

Tradeoff:
- eventual consistency between queue state and task row status in some failure windows.

References:
- [Architecture](architecture.md)
- [ADR 0001](adrs/0001-async-task-pattern.md)

## 2) Manual-first DLQ operations

Decision:
- keep DLQ processing manual (with runbook + redrive script), no automatic DLQ consumer yet.

Why:
- avoids hidden auto-replay loops before stronger guardrails are needed;
- keeps incidents visible and intentional during MVP.

Tradeoff:
- operational burden on the team to inspect and redrive.

References:
- [DLQ runbook](runbooks/dlq-and-alerts.md)
- [ADR 0002](adrs/0002-dlq-manual-operation.md)

## 3) Tenant-aware auth boundary

Decision:
- use Cognito User Pool JWT authorizer for task endpoints and enforce task ownership checks in API handlers.

Why:
- establishes a real multi-tenant boundary early;
- preserves public `health`/demo routes while protecting task routes.

Tradeoff:
- older task rows without `tenant_id` may require migration/compat handling.

References:
- [ADR 0003](adrs/0003-auth-and-tenancy.md)

## 4) Deterministic error taxonomy

Decision:
- standardize error categories across API and worker paths.

Why:
- faster triage through stable, machine-filterable prefixes/codes;
- clear separation of malformed input/schema issues vs transient runtime failures.

Examples:
- API: `error_code` such as `INPUT_CONTRACT`, `SCHEMA_INVALID`
- Worker: `error_message` prefixes such as `[SCHEMA_VALIDATION] ...`, `[BEDROCK_ACCESS] ...`, `[WORKER_TRANSIENT:TimeoutError] ...`

Tradeoff:
- requires discipline to preserve taxonomy consistency over time.

Reference:
- [MVP extractor contract](mvp-extractor.md)

## 5) File-mode preprocessing strategy

Decision:
- support two file preprocessing paths in worker:
  - text-like files -> UTF-8 decode;
  - doc/image files -> Textract detection;
  - fallback to S3 `ContentType` when extension is missing/unknown.

Why:
- broadens input coverage without changing `/tasks` surface;
- keeps deterministic, user-understandable failure messages.

Tradeoff:
- synchronous worker path is simpler but may not fit future long-running OCR pipelines.

Reference:
- [Architecture](architecture.md)

## 6) Step Functions deferred by explicit triggers

Decision:
- keep worker-first orchestration now; defer Step Functions until complexity thresholds are real.

Trigger conditions:
- async Textract jobs (start + poll/callback),
- multi-stage branching pipelines,
- mandatory per-step retry/timeout policies and stage-by-stage execution visibility,
- human approval/review checkpoints.

Why:
- current flow is still short-running and manageable with SQS + Lambda + DLQ;
- minimizes complexity while preserving external contract stability.

Reference:
- [ADR 0004](adrs/0004-orchestration-boundary.md)

## 7) Product contract stability

Decision:
- keep `POST /tasks` and `GET /tasks/{id}` stable while evolving internals.

Why:
- protects downstream consumers and reduces migration risk;
- enables architecture evolution (for example Step Functions later) without client breakage.

Reference:
- [MVP extractor contract](mvp-extractor.md)
