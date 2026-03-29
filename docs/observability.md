# Observability

This stack uses **CloudWatch Logs** as the primary signal: the API and worker Lambdas emit **one JSON object per line** so you can filter and join in **Logs Insights**. **Correlation IDs** tie a single user request to downstream processing.

## Structured logs

- **Format:** JSON with at least `timestamp`, `level`, `message`, `logger`, plus contextual fields.
- **Components:** `component` is `api`, `worker`, or `shared` so you can split traffic by Lambda responsibility.
- **Events:** Many lines include `event` (for example `request`, `task_enqueued`, `task_running`) for quick filtering.

Configure the log group in the Lambda console (or from `/aws/lambda/<function-name>`). Both functions load `shared` logging, which applies a JSON formatter to the root logger (including the handler the Lambda runtime attaches).

## Correlation ID

- **API:** For HTTP API requests, `correlation_id` is the API Gateway **`requestContext.requestId`** when present; otherwise a new UUID is generated so logs still align.
- **Persistence:** `POST /tasks` stores `correlation_id` on the DynamoDB item and includes it in the SQS message body (same payload the worker consumes).
- **Worker:** Logs include `correlation_id` when the message carried it (tasks created after this feature shipped). Older messages may omit it.

### Example Logs Insights queries

Replace log group names with yours (both API and worker groups if you search across the flow):

```sql
fields @timestamp, message, correlation_id, task_id, event, component
| filter correlation_id = "PASTE_REQUEST_ID_HERE"
| sort @timestamp asc
```

```sql
fields @timestamp, message, correlation_id, task_id, component
| filter task_id = "task-xxxxxxxx"
| sort @timestamp asc
```

## Metrics and alarms

- **DLQ backlog:** A CloudWatch alarm on the dead-letter queue’s **ApproximateNumberOfMessagesVisible** notifies via SNS when email is configured at deploy (`DLQ_ALERT_EMAIL`). Details and tuning notes: [DLQ runbook](runbooks/dlq-and-alerts.md).
- **Lambda / SQS:** Use standard Lambda and SQS metrics in CloudWatch for latency, errors, and queue depth. Reserved concurrency, batch size, and visibility timeout interact with retries—see [implementation plan](implementation-plan.md) topic **(G)** for documentation follow-ups.

**X-Ray** tracing is not enabled in this foundation stack; add later if you need service maps and distributed traces.

## Trace a failed task end-to-end

1. **Identify the task:** From the client or DynamoDB, note `task_id` (and `correlation_id` on the item if present).
2. **API logs:** Filter by `correlation_id` or `task_id` and `component = "api"` to confirm enqueue and status transitions to `queued`.
3. **Worker logs:** Filter by the same IDs and `component = "worker"` for `task_running`, `task_completed`, or errors (`record_error_retryable`, `exception` field on stack traces).
4. **DynamoDB:** Confirm `status`, `error_message`, and `updated_at` vs what you see in logs.
5. **If the message reached the DLQ:** Follow [DLQ runbook — operator flow](runbooks/dlq-and-alerts.md#minimal-operator-flow), using `task_id` and timestamps from the steps above.

## Related docs

- [Architecture](architecture.md) — request and state flow
- [DLQ runbook](runbooks/dlq-and-alerts.md) — alarms, peek, redrive
- [Implementation plan](implementation-plan.md) — Week 4 checklist
