# MVP Extractor — Contract & Semantics

This document defines the **input contract, schema format, output contract, and failure semantics** for the first extraction mode: text input with a caller-supplied JSON schema.

---

## Overview

A caller submits a task with `job_type=extract` and provides:
1. The **full source text to extract from** as an inline string in the request body (≤ 32 KB for MVP).
2. A **schema** describing the fields they want back.

For MVP, file paths, S3 pointers, and uploaded files are out of scope for execution input. Those are planned as a later mode.

For the current MVP implementation, the worker invokes Claude through Amazon Bedrock, validates payload/schema shape, and persists the result. The caller polls `GET /tasks/{id}` until status is `completed` or `failed`.

**LLM backend (current):** Claude via Amazon Bedrock (`bedrock-runtime`). Auth is IAM (no API keys). Worker IAM grants `bedrock:InvokeModel` on scoped resources derived from `BEDROCK_MODEL_ID` (including compatibility ARN variants used by inference-profile-backed invokes). No third-party SDK bundling is required; `boto3` covers the Bedrock client.

---

## Input contract

### `POST /tasks`

**Headers:** `Authorization: Bearer <JWT>`

**Body:**

```json
{
  "job_type": "extract",
  "input": {
    "mode": "text",
    "text": "<string, required, 1–32768 chars>",
    "schema": {
      "<field_name>": {
        "type": "<string | number | boolean>",
        "description": "<string, optional hint for the LLM>",
        "required": true
      }
    }
  }
}
```

**Field rules:**

| Field | Type | Required | Constraints |
|---|---|---|---|
| `job_type` | string | yes | Must be `"extract"` |
| `input.mode` | string | yes | Must be `"text"` (only supported mode in MVP) |
| `input.text` | string | yes | 1 – 32 768 characters |
| `input.schema` | object | yes | 1 – 20 top-level keys; each key is a field descriptor |
| `input.schema[field].type` | string | yes | One of `"string"`, `"number"`, `"boolean"` |
| `input.schema[field].description` | string | no | Plain-language hint sent to the LLM |
| `input.schema[field].required` | boolean | no | Default `false`; if `true` and model omits it -> task fails |
| `input.schema[field].enum` | array | no | Non-empty list of allowed values; element type must match `type` |

**Example:**

```json
{
  "job_type": "extract",
  "input": {
    "mode": "text",
    "text": "Invoice #INV-2024-001 dated 2024-03-15. Total due: $1,250.00. Vendor: Acme Corp.",
    "schema": {
      "invoice_number": { "type": "string", "required": true },
      "date":           { "type": "string", "description": "ISO 8601 date" },
      "total_amount":   { "type": "number", "required": true },
      "vendor_name":    { "type": "string" }
    }
  }
}
```

**Response (202 Accepted):**

```json
{
  "task_id": "task-a1b2c3d4",
  "status": "queued",
  "job_type": "extract",
  "tenant_id": "acme",
  "created_by": "<sub>",
  "created_at": "2024-03-15T10:00:00Z",
  "updated_at": "2024-03-15T10:00:00Z",
  "correlation_id": "<uuid>"
}
```

### Idempotency

`POST /tasks` is idempotent per the platform baseline. The idempotency key is derived from `(tenant_id, created_by, job_type, canonicalized input)`. Repeating the same logical request within 1 week returns the existing task (status 200).

---

## Output / result contract

### `GET /tasks/{id}` — terminal states

**Completed:**

```json
{
  "task_id": "task-a1b2c3d4",
  "status": "completed",
  "job_type": "extract",
  "result": {
    "invoice_number": "INV-2024-001",
    "date": "2024-03-15",
    "total_amount": 1250.00,
    "vendor_name": "Acme Corp"
  },
  "result_metadata": {
    "provider": "bedrock",
    "model_id": "arn:aws:bedrock:us-east-1:123456789012:inference-profile/global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "processed_at": "2024-03-15T10:00:05Z"
  },
  "tenant_id": "acme",
  "created_by": "<sub>",
  "created_at": "2024-03-15T10:00:00Z",
  "updated_at": "2024-03-15T10:00:05Z"
}
```

**Failed:**

```json
{
  "task_id": "task-a1b2c3d4",
  "status": "failed",
  "job_type": "extract",
  "error_message": "Required field 'invoice_number' missing from LLM response",
  "tenant_id": "acme",
  "created_by": "<sub>",
  "created_at": "2024-03-15T10:00:00Z",
  "updated_at": "2024-03-15T10:00:06Z"
}
```

### Task status lifecycle

```
queued → running → completed
                 → failed        (non-retryable: schema validation, bad LLM output)
         running → retrying      (transient error: LLM timeout, network, rate-limit)
         retrying → running      (SQS retry attempt)
         retrying → [DLQ]        (after maxReceiveCount exhausted)
```

`result` is only present when `status == "completed"`.
`result_metadata` is only present when `status == "completed"`.
`error_message` is present when `status == "failed"` or `"retrying"`.

---

## Failure semantics

| Scenario | Status set | Retried? | Notes |
|---|---|---|---|
| `text` empty or > 32 KB | API returns **400** | No | Rejected at API layer before task is created |
| `schema` missing or empty | API returns **400** | No | Rejected at API layer |
| Unknown `mode` value | API returns **400** | No | Only `"text"` supported in MVP |
| Required schema field absent in extraction output | `failed` | No | Non-retryable contract/validation issue |
| Extracted value violates enum constraint | `failed` | No | Non-retryable contract/validation issue |
| Worker payload/schema validation fails | `failed` | No | Non-retryable malformed input path |
| Bedrock timeout / network error | `retrying` | Yes | SQS retries up to `maxReceiveCount`; then DLQ |
| Bedrock throttling (`ThrottlingException`) | `retrying` | Yes | Same retry path |
| Worker crash / unhandled exception | `retrying` | Yes | Same retry path |
| Exhausted retries → DLQ | DynamoDB stays `retrying` | No (operator) | Operator must redrive or manually mark `failed` |

### Non-retryable vs retryable distinction

The worker distinguishes failures before raising:
- **Non-retryable** (schema validation, parse error): set status `failed`, do **not** re-raise → message is deleted from SQS, no DLQ routing.
- **Retryable** (LLM call errors, unknown exceptions): set status `retrying`, re-raise → SQS retries and eventually DLQ.

---

## API validation added in MVP

`POST /tasks` gains the following checks when `job_type == "extract"`:

1. `input.mode` must be `"text"`.
2. `input.text` must be a non-empty string ≤ 32 768 characters.
3. `input.schema` must be a non-empty object with ≤ 20 keys.
4. Each schema field descriptor must have a valid `type` (`"string"`, `"number"`, `"boolean"`).
5. If `enum` is provided, it must be a non-empty array with element types matching descriptor `type`.

These return **400** with a descriptive `error` string.

---

## Out of scope for MVP

- File pointer input (S3 key / presigned URL) — tracked as next mode.
- Nested object/array schema types in extraction result contract.
- Per-field confidence scores.
- Streaming results.
- Client-provided idempotency keys.

---

## Related docs

- [Architecture](architecture.md)
- [Implementation plan](implementation-plan.md)
- [DLQ runbook](runbooks/dlq-and-alerts.md)
- [Observability](observability.md)

---

## Implementation sequence (small, reviewable steps)

Use this as the execution order while implementing MVP text extraction:

1. Align product docs scope to extractor-first in `README.md` and `docs/implementation-plan.md`.
2. Enforce API contract in `src/service/api_handler.py`:
   - accept only `job_type="extract"`,
   - validate `input.mode == "text"`,
   - validate `input.text` and `input.schema` constraints.
3. Implement worker text extraction path in `src/worker/worker_handler.py`:
   - parse extract payload,
   - persist deterministic `result` on success,
   - set terminal `failed` for deterministic malformed/unsupported payloads,
   - keep retry path for transient failures.
4. Update smoke flow in `scripts/dev_test_endpoints.sh` to submit extractor payload and verify idempotency + retrieval behavior.
5. Update runbook/docs for extractor operational semantics.

Pause for confirmation after each major step.

### Proposed commit slices

- Commit 1: docs scope alignment + this contract doc.
- Commit 2: API extractor validation (text-first).
- Commit 3: worker extractor path + result/failure semantics.
- Commit 4: smoke test updates + runbook/doc updates.

### Validation checklist

- `POST /tasks` rejects non-extractor or malformed extractor payloads with clear 4xx.
- Duplicate logical extractor requests dedupe via server-side idempotency.
- Worker writes `result` for `completed` tasks.
- Deterministic payload/validation failures become `failed` (no pointless retries).
- Transient worker errors continue through `retrying` and SQS/DLQ path.
- Tenant isolation and correlation-id observability remain unchanged.
