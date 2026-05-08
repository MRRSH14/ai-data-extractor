# ADR 0004: Worker-first orchestration boundary and Step Functions adoption triggers

## Status

Accepted

## Context

The service now supports both text and file-mode extraction while keeping a stable async shape (`API -> SQS -> worker -> DynamoDB`). File mode currently includes inline preprocessing paths (UTF-8 text decode and synchronous Textract detection for supported document/image types).

We need a clear decision on orchestration scope so contributors and operators understand:

- why we are still using worker-only orchestration now;
- when Step Functions should be introduced;
- what must remain stable for API consumers during a future migration.

## Decision

Keep orchestration worker-first for the current phase:

- continue using `SQS -> worker` as the execution backbone;
- keep file preprocessing inside worker execution for current supported flows;
- defer Step Functions until concrete complexity thresholds are reached.

Step Functions adoption triggers:

1. Async document jobs are required (for example, start Textract job and wait/poll/callback).
2. The pipeline becomes multi-step and branching (for example ingest -> preprocess -> extract -> validate -> post-process).
3. Operators require explicit per-step retries/timeouts and execution-history visibility as a standard operational control.
4. Human review or approval checkpoints must be inserted into the flow.

## Consequences

### Positive

- Preserves a simple, low-overhead architecture while Phase 3 input expansion stabilizes.
- Avoids premature workflow orchestration complexity for short-running, mostly linear processing.
- Keeps external API/task contract stable while internals evolve.

### Tradeoffs

- Worker code carries more orchestration responsibility in the near term.
- Per-step workflow visibility remains limited compared with Step Functions execution history.
- Future migration work is deferred, not removed.

## Migration boundary (explicit)

If/when Step Functions is introduced, treat it as an internal orchestration change:

- keep `POST /tasks` and `GET /tasks/{id}` contract stable;
- preserve top-level task status semantics for clients;
- continue using `file_lifecycle_state` as operator-facing telemetry (internal detail).

## Follow-up

- Reevaluate this ADR when any trigger condition is met in production planning.
- If adopted, create a follow-up ADR describing chosen state machine boundaries, retry policy, and failure mapping.
