import json
from datetime import datetime, timezone
import uuid
import os
import boto3
from botocore.exceptions import ClientError

from shared import (
    logger,
    json_response,
    get_tasks_table,
    update_task_status,
)


def handle_health() -> dict:
    logger.info("Handling health check")
    return json_response(200, {"ok": True})


def handle_hello(event: dict) -> dict:
    query_params = event.get("queryStringParameters") or {}
    name = query_params.get("name", "world")

    logger.info("Handling hello request. query_params=%s", query_params)

    return json_response(200, {"message": f"Hello {name}!"})


def handle_get_task(event: dict, tasks_table) -> dict:
    path_params = event.get("pathParameters") or {}
    task_id = path_params.get("id")

    logger.info("Handling get task request. task_id=%s", task_id)

    if not task_id:
        return json_response(400, {"error": "task id is required"})

    try:
        response = tasks_table.get_item(Key={"task_id": task_id})
    except ClientError:
        logger.exception("Failed to read task from DynamoDB")
        return json_response(500, {"error": "Failed to read task"})

    item = response.get("Item")
    if not item:
        return json_response(404, {"error": "Task not found"})

    return json_response(200, item)


def handle_create_task(event: dict, tasks_table, tasks_queue) -> dict:
    raw_body = event.get("body") or "{}"

    logger.info("Handling create task request. raw_body=%s", raw_body)

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON body")
        return json_response(400, {"error": "Invalid JSON body"})

    job_type = body.get("job_type")
    input_value = body.get("input")

    if not job_type:
        logger.warning("Missing required field: job_type")
        return json_response(400, {"error": "job_type is required"})

    if input_value is None:
        logger.warning("Missing required field: input")
        return json_response(400, {"error": "input is required"})

    task_id = f"task-{uuid.uuid4().hex[:8]}"
    created_at = datetime.now(timezone.utc).isoformat()

    item = {
        "task_id": task_id,
        "status": "pending_enqueue",
        "job_type": job_type,
        "input": input_value,
        "created_at": created_at,
        "updated_at": created_at,
    }

    try:
        tasks_table.put_item(Item=item)
    except ClientError:
        logger.exception("Failed to write task to DynamoDB")
        return json_response(500, {"error": "Failed to create task"})

    logger.info("Task stored. task_id=%s", task_id)

    try:
        tasks_queue.send_message(MessageBody=json.dumps(item))
    except ClientError:
        logger.exception("Failed to send task to SQS")
        return json_response(500, {"error": "Failed to create task"})

    try:
        update_task_status(tasks_table, task_id, "queued")
    except ClientError:
        return json_response(500, {"error": "Failed to create task"})

    logger.info("Task enqueued. task_id=%s", task_id)
    item["status"] = "queued"
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    return json_response(202, item)


def handler(event, context):
    http_info = event.get("requestContext", {}).get("http", {})
    path = http_info.get("path")
    method = http_info.get("method")
    tasks_queue_url = os.getenv("TASKS_QUEUE_URL")
    if not tasks_queue_url:
        logger.error("TASKS_QUEUE_URL environment variable is not set")
        return json_response(500, {"error": "Internal server error"})

    tasks_table = get_tasks_table()

    sqs_resource = boto3.resource("sqs")
    tasks_queue = sqs_resource.Queue(tasks_queue_url)

    logger.info("Incoming request. method=%s path=%s", method, path)

    if path == "/health" and method == "GET":
        return handle_health()

    if path == "/hello" and method == "GET":
        return handle_hello(event)

    if path == "/tasks" and method == "POST":
        return handle_create_task(event, tasks_table, tasks_queue)

    if path.startswith("/tasks/") and method == "GET":
        return handle_get_task(event, tasks_table)

    logger.warning("Route not found. method=%s path=%s", method, path)
    return json_response(404, {"error": "Not found"})
