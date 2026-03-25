# Implementation plan (living document)

**Purpose:** Track the **prioritized roadmap**, the **original 4-week sprint**, and **extra topics** raised in discussion that were not in that plan. Update this file as you complete steps or reprioritize—useful for practice, learning, and alignment with tools (Cursor, ChatGPT, teammates).

**How to update:** After each meaningful change, adjust checkboxes, dates, or priority labels (`P0`–`P3`). It is fine to defer or drop items; the list still preserves concepts for later review.

---

## Original 4-week sprint (baseline)

This is the plan you started from; it prioritizes **documentation, state semantics, auth/tenancy, observability** before the AI layer.

| Week | Theme | Main deliverables |
|------|--------|-------------------|
| **1** | Architecture / story | `docs/architecture.md`, README improvements, ADRs 0001–0002 (async pattern, manual DLQ) |
| **2** | Retry / DLQ semantics | Clear `retrying` meaning, operator docs, runbook expansion, optional metadata (`last_attempt_at`, etc.) |
| **3** | Auth + tenant shape | ADR 0003, Cognito JWT authorizer, `tenant_id` / `created_by` / `created_at`, tenant-scoped GET |
| **4** | Observability | Structured logs, correlation ID API → SQS → worker, metrics/alarms review, `docs/observability.md`, runbook for debugging |

**Explicitly out of scope for those four weeks:** RAG, heavy RBAC, auto-DLQ consumers, admin UI, full AI integration—see README roadmap.

---

## Topics from discussion (not in the original 4-week plan)

These came from **this thread** and related chats; they **extend** the baseline, not replace it. You may never implement all of them; keeping them here preserves the **concepts** for refresher and discussion.

| # | Topic | Notes | Suggested priority |
|---|--------|--------|-------------------|
| A | **Idempotent task submission** | Often what people mean by “omnipotent”: safe retries / dedupe so the same logical request does not create duplicate work (client key, hash of payload, etc.). | **P1** after core API semantics are stable |
| B | **Caching** | What to cache (e.g. `GET /tasks/{id}`, model outputs), where (edge, Lambda, dedicated cache), invalidation when status changes. | **P2** when read patterns or cost justify |
| C | **DynamoDB lifecycle** | TTL on task items (or a `ttl` attribute), PITR/backups for audit/DR, capacity mode vs cost. | **P2** with compliance/retention needs |
| D | **S3 + lifecycle for results** | Large/binary outputs in S3, pointer/metadata in DynamoDB; lifecycle rules (expire, tier); IAM scoped per tenant prefix. | **P2** with AI/heavy results |
| E | **Docker Compose + LocalStack (bundled)** | One-command local emulation of AWS services for dev without hitting the cloud; optional quality-of-life for the repo. | **P3** (learning / DX); not required for cloud-first workflow |
| F | **Redundancy / HA posture** | Single region is normal for this stage; document “managed services + DLQ + backups TBD”; multi-region only if requirements demand. | **P2** documentation / DR planning |
| G | **Concurrency & limits** | Account/region Lambda concurrency, optional reserved concurrency on worker, SQS-driven parallelism, DynamoDB hot partitions / throttling—**document first knobs** before tuning. | **P1** with observability week (Week 4) or right after |
| H | **Lambda provisioned concurrency** | Reduce cold starts; **costs money**—defer until metrics/SLOs justify (often API more than worker). | **P3** unless latency is contractual |
| I | **GSIs / list-by-tenant-or-user** | Today: only efficient **get by `task_id`**. Listing “my tasks” or “tenant’s tasks” needs **indexes or new keys**—pairs with **Week 3 tenancy**. | **P1** when you add list APIs |
| J | **DLQ alarm behavior vs email** | Current policy is now fast alerting (`>= 1` visible message for 1 minute). Keep verifying notification paths (subscription confirmation vs alarm, message count, console edits) and tune noise if needed. | **P1** ops clarity; see checklist below |

| K | **Tenant provisioning (A: manual, B: automated)** | Decide how new Cognito users get `custom:tenant_id`: start with manual admin/script (A) and enforce strict mode now (missing => `403`, no dev-only default fallback). Later, switch to automated tenant recognition (B) via Cognito triggers or signup flow. | **P1** for practical testing + future automation |

**Meta (not a backlog ticket):** **ADR** = why we decided; **runbook** = how to operate. **Two components (API + worker)** = tradeoff (more to monitor vs sync Lambda), not a bug.

---

## Priority legend

| Label | Meaning |
|-------|--------|
| **P0** | Current sprint / blocking credibility |
| **P1** | Soon after foundation; high learning or ops value |
| **P2** | Platform maturity, retention, cost, multi-tenant scale |
| **P3** | Optional, experimental, or “when metrics say so” |

---

## Checklist — baseline sprint (update as you go)

### Week 1 — architecture & ADRs

- [x] `docs/architecture.md` (flows, states, DLQ, limitations)
- [x] README improvements + ADR 0001 / 0002
- [x] Optional: pass end-of-week self-review (“new engineer could onboard from docs alone”)

### Week 2 — state & DLQ semantics

- [x] Document `retrying` vs DLQ vs DynamoDB; operator truth
- [x] Expand `docs/runbooks/dlq-and-alerts.md` (symptoms, peek, redrive, DDB expectations)
- [x] Optional: `last_error_message` / `last_attempt_at` style fields if still useful (deferred intentionally; keep existing `error_message` + `updated_at` for now)

### Week 3 — auth & tenancy

- [x] `docs/adrs/0003-auth-and-tenancy.md`
- [x] Cognito JWT authorizer in CDK; protect task routes; `/health` public
- [x] Tenant fields + ownership checks on `POST` / `GET`

### Week 4 — observability

- [ ] Structured logging + correlation ID through API → SQS → worker
- [ ] Metrics/alarms review + `docs/observability.md`
- [ ] Runbook: trace a failed task end-to-end

---

## Checklist — extended topics (optional / later)

- [ ] **(A)** Idempotency design + ADR or API contract (`Idempotency-Key` or server-side dedupe)
- [ ] **(B)** Caching strategy doc (only if you have a concrete read pattern)
- [ ] **(C)** DynamoDB TTL / backup posture documented
- [ ] **(D)** S3 results bucket + lifecycle + worker write path (when AI/results land)
- [ ] **(E)** `docker-compose` + LocalStack recipe in repo (optional)
- [ ] **(F)** Short “HA / single-region” paragraph in architecture (if not merged)
- [ ] **(G)** Document concurrency knobs (worker timeout, visibility timeout, reserved concurrency) in observability or runbook
- [ ] **(H)** Evaluate provisioned concurrency with real p95/p99
- [ ] **(I)** GSI (or pattern) for list-by-tenant after Week 3
- [ ] **(J)** DLQ alarm verification + runbook tweak (see [Deferred follow-ups](#deferred-follow-ups))

---

## Deferred follow-ups

### J — DLQ alarm vs single-message email

**Context:** Alarm policy is now fast detection (`threshold=1`, one 1-minute period). We still want to verify when emails are subscription-confirmation messages vs real alarm transitions.

**When you pick this up:**

1. Confirm **SNS subscription confirmation** vs **CloudWatch ALARM** notification.
2. **CloudWatch → Alarms → History** for `DeadLetterQueueMessagesAlarm` and metric values at the time.
3. Count **messages** in DLQ (not just “one task”); check for **console edits** to the alarm.
4. Decide: separate alarm for “≥1 message” vs noise; update runbook.

---

## Related docs

- [Architecture](architecture.md) — [README](../README.md) — [DLQ runbook](runbooks/dlq-and-alerts.md) — [ADR 0001](adrs/0001-async-task-pattern.md) — [ADR 0002](adrs/0002-dlq-manual-operation.md)

---

## Prompts for ChatGPT (copy/paste)

### Master prompt — maintain plan, learn concepts, prioritize

Use when you want help updating priorities, teaching tradeoffs, or reviewing the roadmap without assuming ChatGPT has repo access:

```
I am building aws-ai-platform-service: API Gateway HTTP API, Lambda API, SQS + worker Lambda, DynamoDB task state, DLQ with manual redrive, CDK Python, optional SNS email on a DLQ backlog alarm. The original 4-week plan was: (1) architecture + ADRs, (2) retry/DLQ semantics + runbook, (3) Cognito JWT + tenant fields + scoped access, (4) structured logs + correlation IDs + observability doc. AI/RAG is explicitly later.

Separately we tracked extra topics: idempotent POST semantics, caching strategy, DynamoDB TTL/backups, S3+ lifecycle for large results, Docker Compose+LocalStack for local dev, HA/DR posture documentation, Lambda concurrency limits and reserved concurrency, provisioned concurrency only if SLOs justify, GSIs for list-by-tenant, and verifying DLQ alarm emails (subscription vs alarm, threshold semantics).

Please:
1. Summarize tradeoffs for any items I ask about (no code required unless I request it).
2. Suggest how to order optional items against P0–P3 with honest “defer until…” conditions.
3. Call out AWS gotchas (SQS visibility timeout vs Lambda timeout, DynamoDB access patterns, alarm false negatives/positives).
4. If I paste an updated checklist from docs/implementation-plan.md, suggest concise edits or next steps.

Stay accurate; say when something is account-specific or needs console verification.
```

### Focused prompt — DLQ alarm vs email

```
I have an AWS CDK stack (Python) that creates an SQS dead-letter queue and a CloudWatch alarm on metric ApproximateNumberOfMessagesVisible for that queue. The alarm is configured with threshold=3, evaluation_periods=5, datapoints_to_alarm=5 (1-minute periods). The alarm description says the DLQ has more than 3 visible messages for 5 minutes.

I expected a single visible message in the DLQ NOT to trigger this alarm, but during testing I still received an email tied to SNS (the alarm can notify SNS when DLQ_ALERT_EMAIL is set at deploy).

Please help me:
1. List plausible explanations (e.g. SNS subscription confirmation vs alarm state change, multiple visible messages, alarm comparison operator / threshold semantics in CDK default, console edits, other alarms).
2. Give concrete steps in AWS Console to verify: SNS subscription vs alarm notification, CloudWatch alarm history and breached metric values, and DLQ visible message count at the time.
3. If I want “notify on any DLQ message” vs “notify only on backlog,” suggest alarm design tradeoffs and example settings (without assuming a specific framework).

Assume standard SQS + CloudWatch + SNS; code is CDK aws-cdk-lib cloudwatch.Alarm on dead_letter_queue.metric_approximate_number_of_messages_visible.
```
