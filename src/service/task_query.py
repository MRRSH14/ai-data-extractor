from botocore.exceptions import ClientError

from service.identity import get_identity_from_claims
from shared import json_response, logger


def handle_get_task(event: dict, tasks_table, *, correlation_id: str) -> dict:
    path_params = event.get("pathParameters") or {}
    task_id = path_params.get("id")

    logger.info(
        "Handling get task request",
        extra={
            "component": "api",
            "correlation_id": correlation_id,
            "event": "get_task",
            "task_id": task_id,
        },
    )

    if not task_id:
        return json_response(400, {"error": "task id is required"})

    try:
        response = tasks_table.get_item(Key={"task_id": task_id})
    except ClientError:
        logger.exception(
            "Failed to read task from DynamoDB",
            extra={
                "component": "api",
                "correlation_id": correlation_id,
                "event": "ddb_error",
                "task_id": task_id,
            },
        )
        return json_response(500, {"error": "Failed to read task"})

    item = response.get("Item")
    if not item:
        return json_response(404, {"error": "Task not found"})

    caller_tenant_id, _ = get_identity_from_claims(event)
    if not caller_tenant_id:
        logger.warning(
            "Missing tenant claim on get task request",
            extra={
                "component": "api",
                "correlation_id": correlation_id,
                "event": "auth_missing_tenant",
                "task_id": task_id,
            },
        )
        return json_response(403, {"error": "Missing tenant claim"})

    task_tenant_id = item.get("tenant_id")
    if not isinstance(task_tenant_id, str):
        logger.warning(
            "Task is missing tenant context",
            extra={
                "component": "api",
                "correlation_id": correlation_id,
                "event": "task_no_tenant",
                "task_id": task_id,
                "caller_tenant_id": caller_tenant_id,
            },
        )
        return json_response(403, {"error": "Task has no tenant context"})

    if task_tenant_id != caller_tenant_id:
        logger.warning(
            "Cross-tenant access denied",
            extra={
                "component": "api",
                "correlation_id": correlation_id,
                "event": "cross_tenant_denied",
                "task_id": task_id,
                "caller_tenant_id": caller_tenant_id,
                "task_tenant_id": task_tenant_id,
            },
        )
        return json_response(403, {"error": "Forbidden"})

    return json_response(200, item)
