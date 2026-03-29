import json
import time

from shared import logger, get_tasks_table, update_task_status


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
    }


def parse_task_id_from_record(record: dict) -> str:
    """Backward-compatible: task id only (used in error paths)."""
    return parse_task_payload(record)["task_id"]


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

    # Simulate background work for now.
    time.sleep(5)

    update_task_status(tasks_table, task_id, "completed")

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
