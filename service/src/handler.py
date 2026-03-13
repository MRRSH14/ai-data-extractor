import json
import logging
from datetime import datetime, timezone
import uuid


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def json_response(status_code: int, payload: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def handle_health() -> dict:
    logger.info("Handling health check")
    return json_response(200, {"ok": True})


def handle_hello(event: dict) -> dict:
    query_params = event.get("queryStringParameters") or {}
    name = query_params.get("name", "world")

    logger.info("Handling hello request. query_params=%s", query_params)

    return json_response(200, {"message": f"Hello {name}!"})

def handle_get_task(event: dict) -> dict:
    path_params = event.get("pathParameters") or {}
    task_id = path_params.get("id")

    logger.info("Handling get task request. task_id=%s", task_id)

    if not task_id:
        return json_response(400, {"error": "task id is required"})

    if task_id != "task-123":
        return json_response(404, {"error": "Task not found"})

    return json_response(
        200,
        {
            "taskId": task_id,
            "status": "completed",
            "jobType": "demo",
            "input": "test",
            "createdAt": "2026-03-13T00:00:00+00:00",
        },
    )


def handle_create_task(event: dict) -> dict:
    raw_body = event.get("body") or "{}"

    logger.info("Handling create task request. raw_body=%s", raw_body)

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON body")
        return json_response(400, {"error": "Invalid JSON body"})

    job_type = body.get("jobType")
    input_value = body.get("input")

    if not job_type:
        logger.warning("Missing required field: jobType")
        return json_response(400, {"error": "jobType is required"})

    if input_value is None:
        logger.warning("Missing required field: input")
        return json_response(400, {"error": "input is required"})

    task_id = f"task-{uuid.uuid4().hex[:8]}"
    created_at = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Task accepted. taskId=%s jobType=%s input=%s",
        task_id,
        job_type,
        input_value,
    )

    return json_response(
        202,
        {
            "taskId": task_id,
            "status": "accepted",
            "jobType": job_type,
            "input": input_value,
            "createdAt": created_at,
        },
    )


def handler(event, context):
    http_info = event.get("requestContext", {}).get("http", {})
    path = http_info.get("path")
    method = http_info.get("method")

    logger.info("Incoming request. method=%s path=%s", method, path)

    if path == "/health" and method == "GET":
        return handle_health()

    if path == "/hello" and method == "GET":
        return handle_hello(event)

    if path == "/tasks" and method == "POST":
        return handle_create_task(event)

    if path.startswith("/tasks/") and method == "GET":
        return handle_get_task(event)

    logger.warning("Route not found. method=%s path=%s", method, path)
    return json_response(404, {"error": "Not found"})
