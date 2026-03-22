# ADR 0001: Async API + worker pattern with DynamoDB task state

## Status

Accepted

## Context

We need a backend that can accept work from clients, return quickly with a stable identifier, and execute work asynchronously without blocking HTTP connections. The system should run on AWS with infrastructure as code and be easy to extend toward authenticated, multi-tenant, and AI-driven workloads later.

Constraints:

- API Lambda should stay short-lived and cheap for simple operations.
- Long or variable-duration work should not rely on API Gateway timeouts alone.
- Operators need a durable record of what was requested and what happened (`status`, errors).

## Decision

Use **API Gateway HTTP API → API Lambda** for HTTP routing and task creation, **SQS** as the buffer between API and workers, a **worker Lambda** driven by SQS events for processing, and **DynamoDB** as the **source of truth for task status and payload**.

Flow:

1. Create task: write DynamoDB → send SQS message → update status to `queued`.
2. Worker: consume SQS → set `running` → work → set `completed` or `failed`, or set `retrying` and fail the invocation for retry/DLQ behavior.

## Consequences

**Positive**

- Clear separation between “accept request” and “do work,” matching common AWS patterns.
- Natural retry and DLQ behavior via SQS without custom schedulers.
- Task status is queryable with `GET /tasks/{id}` for clients and operators.

**Negative / tradeoffs**

- **Eventual consistency** between “message in queue” and “what DynamoDB says” in edge cases (e.g. partial failures during create, or status vs DLQ after max retries). These must be documented and operated explicitly.
- Two moving parts (API + worker) to deploy and monitor versus a single synchronous Lambda.

**Follow-up**

- Correlation IDs and structured logging across API → SQS → worker (see observability roadmap).
- Auth and `tenant_id` on task rows (see future ADRs).
