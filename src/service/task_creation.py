import json
import time
import uuid
from datetime import datetime, timezone

from botocore.exceptions import ClientError

from service.identity import get_identity_from_claims
from service.validation import validate_extract_input, validation_error
from shared import (
    IDEMPOTENCY_TTL_SECONDS,
    ErrorCode,
    build_idempotency_key,
    get_correlation_id,
    json_response,
    logger,
    update_task_status,
)


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
        return validation_error(correlation_id, "job_type is required", error_code=ErrorCode.INPUT_CONTRACT)
    if job_type != "extract":
        return validation_error(
            correlation_id, 'job_type must be "extract"', error_code=ErrorCode.INPUT_CONTRACT
        )

    if input_value is None:
        return validation_error(correlation_id, "input is required", error_code=ErrorCode.INPUT_CONTRACT)

    validation_result = validate_extract_input(input_value, correlation_id=correlation_id)
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
