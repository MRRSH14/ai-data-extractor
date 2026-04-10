import json
import re
import time
from datetime import datetime, timezone

from shared import logger, get_tasks_table, update_task_status


class NonRetryableProcessingError(Exception):
    """Raised for deterministic payload/contract issues that should not retry."""


def _worker_extra(
    task_id: str,
    *,
    correlation_id: str | None = None,
    message_id: str | None = None,
    receive_count: int | None = None,
    event: str | None = None,
) -> dict:
    extra: dict = {"component": "worker", "task_id": task_id}
    if correlation_id:
        extra["correlation_id"] = correlation_id
    if message_id is not None:
        extra["message_id"] = message_id
    if receive_count is not None:
        extra["receive_count"] = receive_count
    if event is not None:
        extra["event"] = event
    return extra


def parse_task_payload(record: dict) -> dict:
    body = record.get("body")
    if not body:
        logger.error(
            "SQS record body is missing",
            extra={"component": "worker", "event": "parse_error"},
        )
        raise ValueError("SQS record body is missing")

    try:
        message = json.loads(body)
    except json.JSONDecodeError:
        logger.error(
            "Invalid JSON in SQS message body",
            extra={"component": "worker", "event": "parse_error", "body_preview": body[:500]},
        )
        raise ValueError("Invalid JSON in SQS message body")

    task_id = message.get("task_id")
    if not task_id:
        logger.error(
            "task_id is missing in SQS message",
            extra={"component": "worker", "event": "parse_error"},
        )
        raise ValueError("task_id is missing in SQS message")

    correlation_id = message.get("correlation_id")
    if correlation_id is not None and not isinstance(correlation_id, str):
        correlation_id = str(correlation_id)

    return {
        "task_id": task_id,
        "correlation_id": correlation_id,
        "job_type": message.get("job_type"),
        "input": message.get("input"),
    }


def parse_task_id_from_record(record: dict) -> str:
    """Backward-compatible: task id only (used in error paths)."""
    return parse_task_payload(record)["task_id"]


def _validate_extract_payload(payload: dict) -> tuple[str, dict]:
    job_type = payload.get("job_type")
    if job_type != "extract":
        raise NonRetryableProcessingError('job_type must be "extract"')

    input_value = payload.get("input")
    if not isinstance(input_value, dict):
        raise NonRetryableProcessingError("input must be an object")

    mode = input_value.get("mode")
    if mode != "text":
        raise NonRetryableProcessingError('input.mode must be "text"')

    text = input_value.get("text")
    if not isinstance(text, str) or not text.strip():
        raise NonRetryableProcessingError("input.text must be a non-empty string")

    schema = input_value.get("schema")
    if not isinstance(schema, dict) or not schema:
        raise NonRetryableProcessingError("input.schema must be a non-empty object")

    return text, schema


def _extract_number(text: str) -> float:
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return 0.0
    return float(match.group(0))


def _extract_boolean(text: str) -> bool:
    lowered = text.lower()
    truthy = ("yes", "true", "approved", "confirmed", "paid")
    return any(token in lowered for token in truthy)


def _build_result(text: str, schema: dict) -> dict:
    result: dict = {}
    compact_text = " ".join(text.strip().split())
    for field_name, descriptor in schema.items():
        if not isinstance(field_name, str) or not field_name.strip():
            raise NonRetryableProcessingError("schema field names must be non-empty strings")
        if not isinstance(descriptor, dict):
            raise NonRetryableProcessingError(
                f'schema descriptor for "{field_name}" must be an object'
            )
        field_type = descriptor.get("type")
        if field_type == "string":
            result[field_name] = compact_text[:500]
        elif field_type == "number":
            result[field_name] = _extract_number(text)
        elif field_type == "boolean":
            result[field_name] = _extract_boolean(text)
        else:
            raise NonRetryableProcessingError(
                f'schema type for "{field_name}" must be string, number, or boolean'
            )
    return result


def _store_completed_result(tasks_table, task_id: str, result: dict) -> None:
    updated_at = datetime.now(timezone.utc).isoformat()
    tasks_table.update_item(
        Key={"task_id": task_id},
        UpdateExpression=(
            "SET #status = :status, updated_at = :updated_at, "
            "#result = :result REMOVE #err"
        ),
        ExpressionAttributeNames={
            "#status": "status",
            "#result": "result",
            "#err": "error_message",
        },
        ExpressionAttributeValues={
            ":status": "completed",
            ":updated_at": updated_at,
            ":result": result,
        },
    )


def process_record(tasks_table, payload: dict) -> None:
    task_id = payload["task_id"]
    correlation_id = payload.get("correlation_id")

    logger.info(
        "Task processing started",
        extra=_worker_extra(
            task_id,
            correlation_id=correlation_id,
            event="task_running",
        ),
    )

    update_task_status(tasks_table, task_id, "running")

    text, schema = _validate_extract_payload(payload)

    # Keep a small simulated delay to preserve async behavior in smoke checks.
    time.sleep(5)

    result = _build_result(text, schema)
    _store_completed_result(tasks_table, task_id, result)

    logger.info(
        "Task processing completed",
        extra=_worker_extra(
            task_id,
            correlation_id=correlation_id,
            event="task_completed",
        ),
    )


def handler(event, context):
    records = event.get("Records", [])
    if not records:
        logger.warning(
            "No SQS records received",
            extra={"component": "worker", "event": "empty_batch"},
        )
        return {"processed": 0}

    tasks_table = get_tasks_table()

    logger.info(
        "Received SQS batch",
        extra={
            "component": "worker",
            "event": "batch_start",
            "record_count": len(records),
        },
    )

    processed = 0
    failed = 0

    for record in records:
        message_id = record.get("messageId")
        receive_count_raw = (record.get("attributes") or {}).get(
            "ApproximateReceiveCount", "1"
        )
        try:
            receive_count = int(receive_count_raw)
        except (TypeError, ValueError):
            receive_count = 1

        try:
            payload = parse_task_payload(record)
        except ValueError:
            failed += 1
            continue

        task_id = payload["task_id"]
        correlation_id = payload.get("correlation_id")

        try:
            process_record(tasks_table, payload)
            processed += 1
            logger.info(
                "Record processed successfully",
                extra=_worker_extra(
                    task_id,
                    correlation_id=correlation_id,
                    message_id=message_id,
                    receive_count=receive_count,
                    event="record_ok",
                ),
            )
        except NonRetryableProcessingError as exc:
            err_text = str(exc)
            failed += 1
            logger.warning(
                "Processing error (non-retryable)",
                extra=_worker_extra(
                    task_id,
                    correlation_id=correlation_id,
                    message_id=message_id,
                    receive_count=receive_count,
                    event="record_error_non_retryable",
                ),
            )
            update_task_status(
                tasks_table,
                task_id,
                "failed",
                error_message=err_text,
            )
            logger.info(
                "Marked task as failed",
                extra=_worker_extra(
                    task_id,
                    correlation_id=correlation_id,
                    message_id=message_id,
                    receive_count=receive_count,
                    event="task_marked_failed",
                ),
            )
        except Exception as exc:
            # Transient / unknown failures (timeouts, network, bugs):
            # keep failing the invocation so SQS can retry and eventually
            # move the message to DLQ after maxReceiveCount.
            logger.exception(
                "Processing error (may retry)",
                extra=_worker_extra(
                    task_id,
                    correlation_id=correlation_id,
                    message_id=message_id,
                    receive_count=receive_count,
                    event="record_error_retryable",
                ),
            )
            try:
                err_text = str(exc)
                update_task_status(
                    tasks_table,
                    task_id,
                    "retrying",
                    error_message=err_text,
                )
                logger.info(
                    "Marked task as retrying",
                    extra=_worker_extra(
                        task_id,
                        correlation_id=correlation_id,
                        message_id=message_id,
                        receive_count=receive_count,
                        event="task_marked_retrying",
                    ),
                )
                raise
            except Exception:
                logger.exception(
                    "Failed to update task after transient error",
                    extra=_worker_extra(
                        task_id,
                        correlation_id=correlation_id,
                        message_id=message_id,
                        receive_count=receive_count,
                        event="status_update_error",
                    ),
                )
                raise

    return {"processed": processed, "failed": failed}
