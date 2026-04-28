import json

from shared import logger


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
