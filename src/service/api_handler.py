import os
import boto3

from shared import (
    logger,
    json_response,
    get_correlation_id,
    get_idempotency_table,
    get_tasks_table,
)
from service.task_creation import handle_create_task
from service.task_query import handle_get_task


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


def handler(event, context):
    http_info = event.get("requestContext", {}).get("http", {})
    path = http_info.get("path")
    method = http_info.get("method")
    correlation_id = get_correlation_id(event)

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
        tasks_table = get_tasks_table()
        tasks_queue_url = os.getenv("TASKS_QUEUE_URL")
        if not tasks_queue_url:
            logger.error(
                "TASKS_QUEUE_URL environment variable is not set",
                extra={"component": "api", "correlation_id": correlation_id},
            )
            return json_response(500, {"error": "Internal server error"})
        idempotency_table = get_idempotency_table()
        sqs_resource = boto3.resource("sqs")
        tasks_queue = sqs_resource.Queue(tasks_queue_url)  # type: ignore[attr-defined]
        return handle_create_task(event, tasks_table, idempotency_table, tasks_queue)

    if path.startswith("/tasks/") and method == "GET":
        tasks_table = get_tasks_table()
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
