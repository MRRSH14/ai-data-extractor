# Demo script (3-5 minutes)

Use this script for a concise live demo, interview walkthrough, or LinkedIn video.

## 0) Setup (before recording/demo)

- ensure stack is deployed and AWS session is active;
- run:
  - `AWS_PROFILE=mrrsh ./scripts/dev_setup.sh`
  - `AWS_PROFILE=mrrsh ./scripts/dev_smoke_all.sh --skip-login`
- keep these tabs ready:
  - repository `README.md`
  - `docs/architecture.md` (diagram)
  - `docs/design-decisions.md`
  - one terminal with smoke output

## 1) Problem statement (30-40s)

Say:
- "I built a schema-driven async extraction backend on AWS."
- "It converts text or files into deterministic JSON for backend workflows."
- "The focus is reliability and operability, not only LLM prompting."

## 2) Architecture snapshot (45-60s)

Show `docs/architecture.md` diagram and explain:
- API accepts `POST /tasks`, returns `202` + `task_id`;
- worker processes through SQS and persists status in DynamoDB;
- retries go to DLQ with manual redrive/runbook.

## 3) Happy path walkthrough (60-75s)

Show terminal output from smoke:
- text-mode request completes;
- file-mode valid UTF-8 object completes;
- result includes `result` and `result_metadata.quality`.

Point out:
- stable contract via `GET /tasks/{id}`;
- idempotent task submission behavior.

## 4) Failure path and triage (45-60s)

Show deterministic failures:
- missing S3 key -> `[INPUT_CONTRACT] ... not found`;
- non-UTF8/unsupported input -> deterministic `failed`.

Highlight:
- clear error taxonomy;
- no noisy retry loop for non-retryable input failures.

## 5) Decision quality (45-60s)

Show `docs/design-decisions.md` and call out:
- why Step Functions is intentionally deferred now;
- exact triggers for adopting it later;
- roadmap focus: Phase 4 reliability, then multi-tenant product features.

## 6) Close (20-30s)

Say:
- "This is production-style MVP quality: contract-first, tenant-aware, observable, and testable."
- "Next I’m focusing on throughput/retry hardening and operator tooling."

## Optional Q&A prompts

- Why async instead of synchronous extraction?
- Why not Step Functions yet?
- How do you guarantee tenant isolation?
- How do retries/DLQ interact with stored task state?
