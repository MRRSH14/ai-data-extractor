import json
from datetime import datetime, timezone
import uuid
import os
import time
import boto3
from botocore.exceptions import ClientError

from shared import (
    logger,
    IDEMPOTENCY_TTL_SECONDS,
    build_idempotency_key,
    json_response,
    get_correlation_id,
    get_idempotency_table,
    get_tasks_table,
    update_task_status,
)


MAX_TEXT_LENGTH = 32768
MAX_SCHEMA_FIELDS = 20
ALLOWED_SCHEMA_TYPES = {"string", "number", "boolean"}


def _validation_error(correlation_id: str, message: str) -> dict:
    logger.warning(
        message,
        extra={
            "component": "api",
            "correlation_id": correlation_id,
            "event": "validation_error",
        },
    )
    return json_response(400, {"error": message})


def _validate_extract_input(input_value: object, *, correlation_id: str) -> dict | None:
    if not isinstance(input_value, dict):
        return _validation_error(correlation_id, "input must be an object")

    mode = input_value.get("mode")
    if mode != "text":
        return _validation_error(correlation_id, 'input.mode must be "text"')

    text = input_value.get("text")
    if not isinstance(text, str):
        return _validation_error(correlation_id, "input.text must be a string")
    if not text.strip():
        return _validation_error(correlation_id, "input.text must be non-empty")
    if len(text) > MAX_TEXT_LENGTH:
        return _validation_error(
            correlation_id, f"input.text exceeds max length of {MAX_TEXT_LENGTH}"
        )

    schema = input_value.get("schema")
    if not isinstance(schema, dict) or not schema:
        return _validation_error(correlation_id, "input.schema must be a non-empty object")
    if len(schema) > MAX_SCHEMA_FIELDS:
        return _validation_error(
            correlation_id, f"input.schema exceeds max fields of {MAX_SCHEMA_FIELDS}"
        )

    for field_name, descriptor in schema.items():
        if not isinstance(field_name, str) or not field_name.strip():
            return _validation_error(correlation_id, "input.schema field names must be non-empty strings")
        if not isinstance(descriptor, dict):
            return _validation_error(
                correlation_id, f'input.schema["{field_name}"] must be an object'
            )

        field_type = descriptor.get("type")
        if field_type not in ALLOWED_SCHEMA_TYPES:
            return _validation_error(
                correlation_id,
                f'input.schema["{field_name}"].type must be one of {sorted(ALLOWED_SCHEMA_TYPES)}',
            )

        description = descriptor.get("description")
        if description is not None and not isinstance(description, str):
            return _validation_error(
                correlation_id,
                f'input.schema["{field_name}"].description must be a string when provided',
            )

        required = descriptor.get("required")
        if required is not None and not isinstance(required, bool):
            return _validation_error(
                correlation_id,
                f'input.schema["{field_name}"].required must be a boolean when provided',
            )

    return None


def get_jwt_claims(event: dict) -> dict:
    request_context = event.get("requestContext", {})
    authorizer = request_context.get("authorizer", {})
    jwt = authorizer.get("jwt", {})
    claims = jwt.get("claims")
    if isinstance(claims, dict):
        return claims
    return {}


def get_identity_from_claims(event: dict) -> tuple[str | None, str | None]:
    claims = get_jwt_claims(event)
    tenant_id = claims.get("custom:tenant_id")
    created_by = claims.get("sub") or claims.get("email")
    if not isinstance(tenant_id, str):
        tenant_id = None
    if not isinstance(created_by, str):
        created_by = None
    return tenant_id, created_by


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


def handle_create_task(event: dict, tasks_table, idempotency_table, tasks_queue) -> dict:
    raw_body = event.get("body") or "{}"
    correlation_id = get_correlation_id(event)

    logger.info(
        "Handling create task request",
        extra={
            "component": "api",
            "correlation_id": correlation_id,
            "event": "create_task",
        },
    )

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning(
            "Invalid JSON body",
            extra={
                "component": "api",
                "correlation_id": correlation_id,
                "event": "bad_json",
            },
        )
        return json_response(400, {"error": "Invalid JSON body"})

    job_type = body.get("job_type")
    input_value = body.get("input")

    if not job_type:
        return _validation_error(correlation_id, "job_type is required")
    if job_type != "extract":
        return _validation_error(correlation_id, 'job_type must be "extract"')

    if input_value is None:
        return _validation_error(correlation_id, "input is required")

    validation_result = _validate_extract_input(input_value, correlation_id=correlation_id)
    if validation_result:
        return validation_result

    tenant_id, created_by = get_identity_from_claims(event)
    if not tenant_id:
        logger.warning(
            "Missing tenant claim on create task request",
            extra={
                "component": "api",
                "correlation_id": correlation_id,
                "event": "auth_missing_tenant",
            },
        )
        return json_response(403, {"error": "Missing tenant claim"})
    if not created_by:
        logger.warning(
            "Missing user identity claim on create task request",
            extra={
                "component": "api",
                "correlation_id": correlation_id,
                "event": "auth_missing_user",
            },
        )
        return json_response(403, {"error": "Missing user identity claim"})

    idempotency_key = build_idempotency_key(
        tenant_id=tenant_id,
        created_by=created_by,
        job_type=job_type,
        input_value=input_value,
    )
    now_epoch = int(time.time())
    expires_at = now_epoch + IDEMPOTENCY_TTL_SECONDS

    idempotency_item = {
        "idempotency_key": idempotency_key,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,
        "tenant_id": tenant_id,
        "created_by": created_by,
    }

    task_id = f"task-{uuid.uuid4().hex[:8]}"
    created_at = datetime.now(timezone.utc).isoformat()

    item = {
        "task_id": task_id,
        "status": "pending_enqueue",
        "job_type": job_type,
        "input": input_value,
        "tenant_id": tenant_id,
        "created_by": created_by,
        "created_at": created_at,
        "updated_at": created_at,
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
    }

    try:
        idempotency_table.put_item(
            Item={**idempotency_item, "task_id": task_id},
            ConditionExpression="attribute_not_exists(idempotency_key)",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            logger.info(
                "Duplicate create request detected via idempotency",
                extra={
                    "component": "api",
                    "correlation_id": correlation_id,
                    "event": "idempotency_duplicate",
                    "idempotency_key": idempotency_key,
                    "tenant_id": tenant_id,
                },
            )
            try:
                idem_resp = idempotency_table.get_item(
                    Key={"idempotency_key": idempotency_key}
                )
                idem_item = idem_resp.get("Item") or {}
                existing_task_id = idem_item.get("task_id")
                if isinstance(existing_task_id, str) and existing_task_id:
                    existing_resp = tasks_table.get_item(Key={"task_id": existing_task_id})
                    existing_item = existing_resp.get("Item")
                    if existing_item:
                        return json_response(200, existing_item)
            except ClientError:
                logger.exception(
                    "Failed to resolve existing idempotent task",
                    extra={
                        "component": "api",
                        "correlation_id": correlation_id,
                        "event": "idempotency_lookup_error",
                        "idempotency_key": idempotency_key,
                    },
                )
            return json_response(409, {"error": "Could not resolve idempotent task"})
        logger.exception(
            "Failed to write idempotency record to DynamoDB",
            extra={
                "component": "api",
                "correlation_id": correlation_id,
                "event": "idempotency_write_error",
                "idempotency_key": idempotency_key,
            },
        )
        return json_response(500, {"error": "Failed to create task"})

    try:
        tasks_table.put_item(Item=item)
    except ClientError:
        logger.exception(
            "Failed to write task to DynamoDB",
            extra={
                "component": "api",
                "correlation_id": correlation_id,
                "event": "ddb_error",
                "task_id": task_id,
            },
        )
        try:
            idempotency_table.delete_item(Key={"idempotency_key": idempotency_key})
        except ClientError:
            logger.exception(
                "Failed to rollback idempotency record after task write failure",
                extra={
                    "component": "api",
                    "correlation_id": correlation_id,
                    "event": "idempotency_rollback_error",
                    "idempotency_key": idempotency_key,
                },
            )
        return json_response(500, {"error": "Failed to create task"})

    logger.info(
        "Task stored",
        extra={
            "component": "api",
            "correlation_id": correlation_id,
            "event": "task_stored",
            "task_id": task_id,
            "tenant_id": tenant_id,
        },
    )

    try:
        tasks_queue.send_message(MessageBody=json.dumps(item))
    except ClientError:
        logger.exception(
            "Failed to send task to SQS",
            extra={
                "component": "api",
                "correlation_id": correlation_id,
                "event": "sqs_error",
                "task_id": task_id,
            },
        )
        return json_response(500, {"error": "Failed to create task"})

    try:
        update_task_status(tasks_table, task_id, "queued")
    except ClientError:
        return json_response(500, {"error": "Failed to create task"})

    logger.info(
        "Task enqueued",
        extra={
            "component": "api",
            "correlation_id": correlation_id,
            "event": "task_enqueued",
            "task_id": task_id,
            "tenant_id": tenant_id,
        },
    )
    item["status"] = "queued"
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    return json_response(202, item)


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
