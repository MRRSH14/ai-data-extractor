import json
import logging
import os
import uuid
import hashlib
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError


# Attributes LogRecord always has; extras from logger.info(..., extra={...}) merge into the record.
_LOGRECORD_STANDARD_KEYS = frozenset(
    vars(
        logging.LogRecord(
            name="",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="",
            args=(),
            exc_info=None,
        )
    ).keys()
) | frozenset({"message", "exc_info", "exc_text", "stack_info"})


class JsonFormatter(logging.Formatter):
    """One JSON object per line for CloudWatch Logs Insights."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key in _LOGRECORD_STANDARD_KEYS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info).strip()
        return json.dumps(payload, default=str)


def _configure_structured_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = JsonFormatter()
    if root.handlers:
        for h in root.handlers:
            h.setFormatter(fmt)
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(fmt)
        root.addHandler(handler)


_configure_structured_logging()

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
IDEMPOTENCY_TTL_SECONDS = 7 * 24 * 60 * 60


def json_response(status_code: int, payload: dict) -> dict:
    def _json_default(value):
        if isinstance(value, Decimal):
            # Keep integers as ints; otherwise emit float for API clients/tests.
            if value == value.to_integral_value():
                return int(value)
            return float(value)
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, default=_json_default),
    }


def get_correlation_id(event: dict) -> str:
    """Prefer API Gateway request id; otherwise a new UUID (still logged consistently)."""
    rc = event.get("requestContext") or {}
    req_id = rc.get("requestId")
    if isinstance(req_id, str) and req_id.strip():
        return req_id.strip()
    return str(uuid.uuid4())


def get_tasks_table():
    tasks_table_name = os.getenv("TASKS_TABLE_NAME")
    if not tasks_table_name:
        logger.error("TASKS_TABLE_NAME environment variable is not set")
        raise RuntimeError("Missing TASKS_TABLE_NAME environment variable")
    return dynamodb.Table(tasks_table_name)


def get_idempotency_table():
    table_name = os.getenv("IDEMPOTENCY_TABLE_NAME")
    if not table_name:
        logger.error("IDEMPOTENCY_TABLE_NAME environment variable is not set")
        raise RuntimeError("Missing IDEMPOTENCY_TABLE_NAME environment variable")
    return dynamodb.Table(table_name)


def build_idempotency_key(
    *,
    tenant_id: str,
    created_by: str,
    job_type: str,
    input_value,
    version: str = "idem:v1",
) -> str:
    canonical_payload = {
        "v": version,
        "tenant_id": tenant_id,
        "created_by": created_by,
        "job_type": job_type,
        "input": input_value,
    }
    canonical_json = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def update_task_status(
    tasks_table,
    task_id: str,
    status: str,
    *,
    error_message: str | None = None,
) -> None:
    updated_at = datetime.now(timezone.utc).isoformat()
    expr_names = {"#status": "status"}
    expr_values = {
        ":status": status,
        ":updated_at": updated_at,
    }
    update_parts = ["#status = :status", "updated_at = :updated_at"]
    if error_message is not None:
        expr_names["#err"] = "error_message"
        expr_values[":err"] = error_message[:2000]
        update_parts.append("#err = :err")
    try:
        tasks_table.update_item(
            Key={"task_id": task_id},
            UpdateExpression="SET " + ", ".join(update_parts),
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
    except ClientError:
        logger.exception(
            "Failed to update task status in DynamoDB. task_id=%s, status=%s",
            task_id,
            status,
        )
        raise

    logger.info(
        "Task updated",
        extra={
            "component": "shared",
            "event": "task_status_update",
            "task_id": task_id,
            "status": status,
        },
    )
