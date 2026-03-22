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

2. **The alarm is strict**  
   It fires when **visible DLQ messages &gt; 3** for **5 consecutive 1‑minute evaluation periods** (all 5 datapoints must breach). A **single** poison message often **will not** page you.

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

## Operational notes

- **Current behavior:** For transient failures, the worker keeps failing the invocation so SQS can retry and eventually move the message to the DLQ after `maxReceiveCount`.
- **DLQ processing mode:** There is no automatic DLQ consumer Lambda; messages remain in DLQ for manual inspection and redrive.
- **Retention:** DLQ messages are kept **7 days** (see CDK). Redrive or delete before retention expires if you care about them.
