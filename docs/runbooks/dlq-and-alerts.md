# DLQ visibility, redrive, and email alerts

## See messages on the DLQ (console)

1. Open **AWS Console** → **SQS**.
2. Find the queue whose name contains **`DeadLetterQueue`** (from stack `InfraStack`).
3. Open the queue → **Monitoring** tab shows approximate message counts.
4. **Send and receive messages** → **Poll for messages** (or use **Start DLQ redrive** — see below).

Stack outputs (after deploy): **DeadLetterQueueUrl**, **TasksQueueUrl** (CloudFormation → stack → **Outputs**).

---

## Why you may not have gotten an email

1. **`DLQ_ALERT_EMAIL` was not set at `cdk deploy` time**  
   The stack only creates an **SNS email subscription** and wires the **CloudWatch alarm → SNS** when this environment variable is set. Manual deploy without it means **no subscriber** and **no alarm action** to SNS.

2. **Alarm sensitivity changed recently**  
   It now fires when the DLQ has **at least 1 visible message** for **1 minute**. This gives faster notification for single-message failures, but can create more alert noise.

---

## Fix alerts: console vs code

### Option A — Redeploy with email (infra as code)

```bash
cd infra
export DLQ_ALERT_EMAIL="you@example.com"   # use a real inbox
source .venv/bin/activate                  # if you use venv
cdk deploy
```

Check your inbox for **AWS Notification – Subscription Confirmation** and **confirm** the subscription.

### Option B — AWS Console only (no redeploy)

1. **SNS** → topic named like **`DeadLetterQueueMessagesAlarmTopic`** → **Create subscription** → Protocol **Email** → your address → confirm email.
2. **CloudWatch** → **Alarms** → alarm **`DeadLetterQueueMessagesAlarm`** → **Edit** → **Actions** → add **SNS** notification → select the same topic.

Until the alarm has an **SNS action** and the topic has a **confirmed** subscription, you will not get mail.

---

## Redrive manually (console)

1. **SQS** → open the **DLQ** → **Start DLQ redrive** (if shown).
2. Choose the **destination** = your **main tasks queue** (name contains **`TasksQueue`**).
3. Start the task and watch status in the console.

This uses the same **asynchronous** move as the API below.

---

## Redrive with the Python script

Install boto3 (once):

```bash
pip install boto3
```

Get URLs from **CloudFormation** → **InfraStack** → **Outputs** (`DeadLetterQueueUrl`, `TasksQueueUrl`).

From the **repository root**:

```bash
export DLQ_URL="..."           # DeadLetterQueueUrl
export MAIN_URL="..."          # TasksQueueUrl

python scripts/dlq_redrive.py stats --dlq-url "$DLQ_URL"
python scripts/dlq_redrive.py peek --dlq-url "$DLQ_URL" --max 5
python scripts/dlq_redrive.py redrive --dlq-url "$DLQ_URL" --destination-url "$MAIN_URL"
```

From the **`infra/`** directory (same commands; wrapper forwards to the repo script):

```bash
python scripts/dlq_redrive.py stats --dlq-url "$DLQ_URL"
```

Or without the wrapper: `python ../scripts/dlq_redrive.py stats --dlq-url "$DLQ_URL"`.

Optional: `--profile your-profile --region us-east-1`.

**When to redrive:** After you have **fixed the worker** (or bad message payload) so reprocessing will succeed. Otherwise messages return to the DLQ.

---

## Operator semantics: `retrying` vs DLQ vs DynamoDB

Use this model to avoid confusion during incidents:

- **`retrying` means:** the last worker attempt failed with a non-terminal error, and SQS may deliver again.
- **DLQ placement means:** SQS exhausted retry attempts (`maxReceiveCount`) and moved the message to DLQ.
- **Important:** DynamoDB status can still show `retrying` even after DLQ placement. Queue state is often the final operator truth for “what happens next.”

### Quick triage table

| Symptom | Likely cause | What to check first | Task status you may see |
|---|---|---|---|
| Email alarm, 1+ message in DLQ | Worker transient/unknown error repeated | CloudWatch alarm history + DLQ visible count | `retrying` (common), sometimes older `running`/`queued` |
| Message stays in DLQ after redrive attempt | Root issue not fixed, message fails again | Worker logs around task/message ID | flips `running` → `retrying`, then returns to DLQ |
| No email but failures suspected | SNS action/subscription missing or unconfirmed | SNS topic subscriptions + alarm actions | Any prior state; status alone is not enough |

### Minimal operator flow

1. Confirm DLQ has messages (`stats` or SQS console).
2. Peek a few messages (`peek`) and capture `task_id` + error context.
3. Check worker CloudWatch logs for the same IDs and identify root cause.
4. Fix code/config/data issue first.
5. Redrive from DLQ to main queue.
6. Confirm lifecycle in DynamoDB and logs (`running` → `completed`, or repeat if still failing).

---

## Operational notes

- **Current behavior:** For transient failures, the worker keeps failing the invocation so SQS can retry and eventually move the message to the DLQ after `maxReceiveCount`.
- **DLQ processing mode:** There is no automatic DLQ consumer Lambda; messages remain in DLQ for manual inspection and redrive.
- **Alert behavior:** Alarm is tuned for fast detection (`>= 1` visible DLQ message, 1-minute period). Keep notifications enabled and verify SNS email subscriptions after deploy.
- **Retention:** DLQ messages are kept **7 days** (see CDK). Redrive or delete before retention expires if you care about them.
