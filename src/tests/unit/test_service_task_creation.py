import json
import os

# Prevent boto3 credential/provider initialization from requiring local AWS setup.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from service.task_creation import handle_create_task


def test_handle_create_task_rejects_invalid_json() -> None:
    event = {
        "body": "{bad-json",
        "requestContext": {"requestId": "corr-1"},
    }
    resp = handle_create_task(event, tasks_table=None, idempotency_table=None, tasks_queue=None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 400
    assert body["error"] == "Invalid JSON body"


def test_handle_create_task_rejects_missing_job_type() -> None:
    event = {
        "body": json.dumps({"input": {"mode": "text", "text": "x", "schema": {"f": {"type": "string"}}}}),
        "requestContext": {"requestId": "corr-1"},
    }
    resp = handle_create_task(event, tasks_table=None, idempotency_table=None, tasks_queue=None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 400
    assert body["error_code"] == "INPUT_CONTRACT"
    assert body["error"] == "job_type is required"


def test_handle_create_task_rejects_missing_input() -> None:
    event = {
        "body": json.dumps({"job_type": "extract"}),
        "requestContext": {"requestId": "corr-1"},
    }
    resp = handle_create_task(event, tasks_table=None, idempotency_table=None, tasks_queue=None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 400
    assert body["error_code"] == "INPUT_CONTRACT"
    assert body["error"] == "input is required"
