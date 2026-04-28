import os

# Prevent boto3 credential/provider initialization from requiring local AWS setup.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from service.task_query import handle_get_task


class _FakeTasksTable:
    def __init__(self, item):
        self._item = item

    def get_item(self, Key):  # noqa: N803 - boto3 style
        return {"Item": self._item} if self._item is not None else {}


def _event_with_claims(task_id: str, tenant_id: str) -> dict:
    return {
        "pathParameters": {"id": task_id},
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "custom:tenant_id": tenant_id,
                        "sub": "user-1",
                    }
                }
            }
        },
    }


def test_handle_get_task_returns_404_when_missing() -> None:
    event = _event_with_claims("task-1", "tenant-a")
    resp = handle_get_task(event, _FakeTasksTable(None), correlation_id="corr-1")
    assert resp["statusCode"] == 404


def test_handle_get_task_blocks_cross_tenant_access() -> None:
    event = _event_with_claims("task-1", "tenant-a")
    item = {"task_id": "task-1", "tenant_id": "tenant-b"}
    resp = handle_get_task(event, _FakeTasksTable(item), correlation_id="corr-1")
    assert resp["statusCode"] == 403


def test_handle_get_task_returns_200_for_same_tenant() -> None:
    event = _event_with_claims("task-1", "tenant-a")
    item = {"task_id": "task-1", "tenant_id": "tenant-a", "status": "queued"}
    resp = handle_get_task(event, _FakeTasksTable(item), correlation_id="corr-1")
    assert resp["statusCode"] == 200
