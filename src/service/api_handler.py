import os
import boto3
from botocore.exceptions import ClientError

from shared import (
    logger,
    json_response,
    get_correlation_id,
    get_idempotency_table,
    get_tasks_table,
)
from service.identity import get_identity_from_claims
from service.task_creation import handle_create_task


def handle_health(*, correlation_id: str) -> dict:
    logger.info(
        "Handling health check",
        extra={"component": "api", "correlation_id": correlation_id, "event": "health"},
    )
    return json_response(200, {"ok": True})


def handle_hello(event: dict, *, correlation_id: str) -> dict:
    query_params = event.get("queryStringParameters") or {}
    name = query_params.get("name", "world")

    logger.info(
        "Handling hello request",
        extra={
            "component": "api",
            "correlation_id": correlation_id,
            "event": "hello",
            "query_params": query_params,
        },
    )

    return json_response(200, {"message": f"Hello {name}!"})


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


def handler(event, context):
    http_info = event.get("requestContext", {}).get("http", {})
    path = http_info.get("path")
    method = http_info.get("method")
    correlation_id = get_correlation_id(event)
    tasks_queue_url = os.getenv("TASKS_QUEUE_URL")
    if not tasks_queue_url:
        logger.error(
            "TASKS_QUEUE_URL environment variable is not set",
            extra={"component": "api", "correlation_id": correlation_id},
        )
        return json_response(500, {"error": "Internal server error"})

    tasks_table = get_tasks_table()
    idempotency_table = get_idempotency_table()

    sqs_resource = boto3.resource("sqs")
    tasks_queue = sqs_resource.Queue(tasks_queue_url)  # type: ignore[attr-defined]

    logger.info(
        "Incoming request",
        extra={
            "component": "api",
            "correlation_id": correlation_id,
            "event": "request",
            "method": method,
            "path": path,
        },
    )

    if path == "/health" and method == "GET":
        return handle_health(correlation_id=correlation_id)

    if path == "/hello" and method == "GET":
        return handle_hello(event, correlation_id=correlation_id)

    if path == "/tasks" and method == "POST":
        return handle_create_task(event, tasks_table, idempotency_table, tasks_queue)

    if path.startswith("/tasks/") and method == "GET":
        return handle_get_task(event, tasks_table, correlation_id=correlation_id)

    logger.warning(
        "Route not found",
        extra={
            "component": "api",
            "correlation_id": correlation_id,
            "event": "not_found",
            "method": method,
            "path": path,
        },
    )
    return json_response(404, {"error": "Not found"})
