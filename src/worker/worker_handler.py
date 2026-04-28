import os
from datetime import datetime, timezone

from shared import logger, get_tasks_table, update_task_status
from worker.bedrock_extract import (
    _extract_json_object_text,
    _invoke_bedrock_extract,
)
from worker.errors import (
    NonRetryableProcessingError,
    retryable_error_message as _retryable_error_message,
)
from worker.parsing import parse_task_id_from_record, parse_task_payload
from worker.quality import _build_quality_metadata
from worker.validation import (
    _coerce_and_validate_result,
    _validate_extract_payload,
)


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


def _store_completed_result(tasks_table, task_id: str, result: dict, schema: dict) -> None:
    updated_at = datetime.now(timezone.utc).isoformat()
    model_id = os.getenv("BEDROCK_MODEL_ID", "")
    metadata = {
        "provider": "bedrock",
        "model_id": model_id,
        "processed_at": updated_at,
        "quality": _build_quality_metadata(schema, result),
    }
    tasks_table.update_item(
        Key={"task_id": task_id},
        UpdateExpression=(
            "SET #status = :status, updated_at = :updated_at, "
            "#result = :result, #meta = :meta REMOVE #err"
        ),
        ExpressionAttributeNames={
            "#status": "status",
            "#result": "result",
            "#meta": "result_metadata",
            "#err": "error_message",
        },
        ExpressionAttributeValues={
            ":status": "completed",
            ":updated_at": updated_at,
            ":result": result,
            ":meta": metadata,
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
    result = _invoke_bedrock_extract(text, schema)
    _store_completed_result(tasks_table, task_id, result, schema)

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
                err_text = _retryable_error_message(exc)
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
