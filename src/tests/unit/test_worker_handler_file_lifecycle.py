import os

# Prevent boto3 credential/provider initialization from requiring local AWS setup.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import worker.worker_handler as worker_handler


class _FakeTable:
    def __init__(self):
        self.calls = []

    def update_item(self, **kwargs):
        self.calls.append(kwargs)


def test_process_record_file_mode_sets_lifecycle_states(monkeypatch) -> None:
    table = _FakeTable()
    payload = {"task_id": "task-1", "correlation_id": "corr-1"}

    monkeypatch.setattr(worker_handler, "update_task_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        worker_handler,
        "validate_extract_payload",
        lambda payload: (
            {"mode": "file", "file": {"bucket": "bucket-a", "key": "docs/invoice.pdf"}},
            {"invoice_id": {"type": "string"}},
        ),
    )
    monkeypatch.setattr(worker_handler, "preprocess_file_to_text", lambda *args, **kwargs: "Invoice INV-1")
    monkeypatch.setattr(worker_handler, "invoke_bedrock_extract", lambda *args, **kwargs: {"invoice_id": "INV-1"})

    worker_handler.process_record(table, payload)

    file_states = [
        c.get("ExpressionAttributeValues", {}).get(":state")
        for c in table.calls
        if ":state" in c.get("ExpressionAttributeValues", {})
    ]
    assert file_states == ["ingested", "processing"]

    completed_calls = [
        c
        for c in table.calls
        if c.get("ExpressionAttributeValues", {}).get(":status") == "completed"
    ]
    assert len(completed_calls) == 1
    assert completed_calls[0]["ExpressionAttributeValues"].get(":file_state") == "extracted"
