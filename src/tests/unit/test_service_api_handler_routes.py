import json
import os

# Prevent boto3 credential/provider initialization from requiring local AWS setup.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import service.api_handler as api_handler


def test_health_route_does_not_require_task_dependencies(monkeypatch) -> None:
    def _should_not_be_called():
        raise AssertionError("get_tasks_table should not be called for /health")

    monkeypatch.setattr(api_handler, "get_tasks_table", _should_not_be_called)

    event = {
        "requestContext": {
            "http": {"path": "/health", "method": "GET"},
            "requestId": "corr-1",
        }
    }
    resp = api_handler.handler(event, None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["ok"] is True


def test_tasks_post_requires_queue_url(monkeypatch) -> None:
    monkeypatch.delenv("TASKS_QUEUE_URL", raising=False)

    class _FakeTable:
        pass

    monkeypatch.setattr(api_handler, "get_tasks_table", lambda: _FakeTable())
    event = {
        "requestContext": {
            "http": {"path": "/tasks", "method": "POST"},
            "requestId": "corr-2",
        },
        "body": "{}",
    }
    resp = api_handler.handler(event, None)
    assert resp["statusCode"] == 500
