# ADR 0002: Manual DLQ operation (no automatic consumer)

## Status

Accepted

## Context

When the worker fails repeatedly for a message, SQS moves the message to a **dead-letter queue** after `maxReceiveCount`. Automatic responses to DLQ traffic include: Lambda triggers on the DLQ, auto-redrive rules, or custom reapers. Each option adds behavior that can hide incidents, duplicate work, or require careful idempotency before we have full operator playbooks and monitoring.

## Decision

Keep **DLQ handling manual** for this phase:

- No Lambda subscribed to the DLQ for automatic reprocessing.
- Operators **inspect** the DLQ (console, CLI, or `scripts/dlq_redrive.py`), **fix** the underlying issue (worker bug, bad payload, downstream outage), then **redrive** to the main queue or delete messages as appropriate.

Email notification is optional via CloudWatch → SNS when `DLQ_ALERT_EMAIL` is set at deploy time; that is **alerting**, not automated processing.

## Consequences

**Positive**

- Incidents remain visible; teams consciously decide when to redrive.
- Avoids premature automation that could amplify bad messages or mask repeated failures.

**Negative**

- **Operational burden:** Someone must act on DLQ backlog; messages are retained for a limited time (e.g. 7 days in current CDK).
- **Status vs queue:** DynamoDB may still show `retrying` (or other states) while the message sits in or has been moved to the DLQ; operators must treat queue state and stored status as related but not always identical without a reconciling job.

**Follow-up**

- Revisit automatic or semi-automatic DLQ handling once idempotency, auth, and observability are stronger.
