import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import boto3  # type: ignore[reportMissingImports]
from botocore.exceptions import ClientError  # type: ignore[reportMissingImports]

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


def _coerce_and_validate_result(raw_result: object, schema: dict) -> dict:
    if not isinstance(raw_result, dict):
        raise NonRetryableProcessingError("model output must be a JSON object")

    normalized: dict = {}
    for field_name, descriptor in schema.items():
        if not isinstance(field_name, str) or not field_name.strip():
            raise NonRetryableProcessingError("schema field names must be non-empty strings")
        if not isinstance(descriptor, dict):
            raise NonRetryableProcessingError(
                f'schema descriptor for "{field_name}" must be an object'
            )

        field_type = descriptor.get("type")
        required = bool(descriptor.get("required", False))
        enum_values = descriptor.get("enum")
        value = raw_result.get(field_name)
        if value is None:
            if required:
                raise NonRetryableProcessingError(
                    f'required field "{field_name}" missing from model output'
                )
            continue

        if field_type == "string":
            if not isinstance(value, str):
                value = str(value)
        elif field_type == "number":
            if isinstance(value, bool):
                raise NonRetryableProcessingError(
                    f'field "{field_name}" must be a number, got boolean'
                )
            if isinstance(value, float):
                value = Decimal(str(value))
            elif not isinstance(value, (int, Decimal)):
                try:
                    value = Decimal(str(value))
                except (TypeError, ValueError, InvalidOperation):
                    raise NonRetryableProcessingError(
                        f'field "{field_name}" must be numeric'
                    ) from None
        elif field_type == "boolean":
            if isinstance(value, bool):
                pass
            elif isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "yes", "1"}:
                    value = True
                elif lowered in {"false", "no", "0"}:
                    value = False
                else:
                    raise NonRetryableProcessingError(
                        f'field "{field_name}" must be boolean'
                    )
            else:
                raise NonRetryableProcessingError(f'field "{field_name}" must be boolean')
        else:
            raise NonRetryableProcessingError(
                f'schema type for "{field_name}" must be string, number, or boolean'
            )

        if enum_values is not None:
            if not isinstance(enum_values, list) or not enum_values:
                raise NonRetryableProcessingError(
                    f'schema enum for "{field_name}" must be a non-empty array'
                )
            if field_type == "number":
                try:
                    normalized_value = (
                        value if isinstance(value, Decimal) else Decimal(str(value))
                    )
                    normalized_enum = [Decimal(str(v)) for v in enum_values]
                except (TypeError, ValueError, InvalidOperation):
                    raise NonRetryableProcessingError(
                        f'schema enum for "{field_name}" must contain numeric values'
                    ) from None
                if normalized_value not in normalized_enum:
                    raise NonRetryableProcessingError(
                        f'field "{field_name}" must be one of {enum_values}'
                    )
            elif field_type == "string":
                if not all(isinstance(v, str) for v in enum_values):
                    raise NonRetryableProcessingError(
                        f'schema enum for "{field_name}" must contain string values'
                    )
                if value not in enum_values:
                    raise NonRetryableProcessingError(
                        f'field "{field_name}" must be one of {enum_values}'
                    )
            else:  # boolean
                if not all(isinstance(v, bool) for v in enum_values):
                    raise NonRetryableProcessingError(
                        f'schema enum for "{field_name}" must contain boolean values'
                    )
                if value not in enum_values:
                    raise NonRetryableProcessingError(
                        f'field "{field_name}" must be one of {enum_values}'
                    )

        normalized[field_name] = value

    return normalized


def _bedrock_client():
    region = os.getenv("BEDROCK_REGION")
    if region:
        return boto3.client("bedrock-runtime", region_name=region)
    return boto3.client("bedrock-runtime")


def _build_model_prompt(text: str, schema: dict) -> str:
    schema_json = json.dumps(schema, ensure_ascii=True, sort_keys=True)
    return (
        "Extract fields from the provided text using the schema.\n"
        "Return only a JSON object with top-level keys from schema.\n"
        "Do not include markdown, explanations, or extra keys.\n\n"
        f"Schema:\n{schema_json}\n\n"
        f"Text:\n{text}"
    )


def _extract_json_object_text(text: str) -> str:
    candidate = text.strip()
    if not candidate:
        raise NonRetryableProcessingError("model output is empty")

    # Common LLM pattern: ```json ... ```
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    # Fast path when output is already a JSON object.
    if candidate.startswith("{") and candidate.endswith("}"):
        return candidate

    # Fallback: find the first balanced JSON object inside mixed text.
    start = candidate.find("{")
    if start == -1:
        raise NonRetryableProcessingError("model output does not contain a JSON object")

    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(candidate)):
        ch = candidate[idx]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return candidate[start : idx + 1]

    raise NonRetryableProcessingError("model output contains incomplete JSON object")


def _invoke_bedrock_extract(text: str, schema: dict) -> dict:
    model_id = os.getenv("BEDROCK_MODEL_ID")
    if not model_id:
        raise NonRetryableProcessingError("BEDROCK_MODEL_ID is not configured")

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "temperature": 0,
        "messages": [{"role": "user", "content": _build_model_prompt(text, schema)}],
    }

    try:
        client = _bedrock_client()
        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
    except ClientError as exc:
        error = exc.response.get("Error", {})
        code = error.get("Code", "")
        message = error.get("Message", "")
        # Config/contract issue for some newer models (e.g., Claude Haiku 4.5):
        # Bedrock may require invoking via inference profile instead of direct model ID.
        if code == "ValidationException" and "inference profile" in message.lower():
            raise NonRetryableProcessingError(
                "BEDROCK_MODEL_ID must be an inference profile ID or ARN for this model"
            ) from None
        if code == "AccessDeniedException" and (
            "aws-marketplace:subscribe" in message.lower()
            or "aws-marketplace:viewsubscriptions" in message.lower()
            or "marketplace subscription" in message.lower()
        ):
            raise NonRetryableProcessingError(
                "Bedrock model access is not enabled for this account. "
                "Grant AWS Marketplace permissions and subscribe/enable the model first."
            ) from None
        logger.exception("Bedrock invoke failed", extra={"component": "worker", "event": "bedrock_error"})
        raise

    raw_body = response.get("body")
    if raw_body is None:
        raise NonRetryableProcessingError("Bedrock response body is missing")

    response_json = json.loads(raw_body.read())
    content = response_json.get("content")
    if not isinstance(content, list) or not content:
        raise NonRetryableProcessingError("Bedrock response content is missing")

    first_block = content[0]
    if not isinstance(first_block, dict):
        raise NonRetryableProcessingError("Bedrock response content block is invalid")
    text_output = first_block.get("text")
    if not isinstance(text_output, str) or not text_output.strip():
        raise NonRetryableProcessingError("Bedrock text output is missing")

    try:
        parsed = json.loads(_extract_json_object_text(text_output))
    except json.JSONDecodeError as exc:
        raise NonRetryableProcessingError(
            f"model output is not valid JSON: {exc.msg}"
        ) from None

    return _coerce_and_validate_result(parsed, schema)


def _store_completed_result(tasks_table, task_id: str, result: dict) -> None:
    updated_at = datetime.now(timezone.utc).isoformat()
    model_id = os.getenv("BEDROCK_MODEL_ID", "")
    metadata = {
        "provider": "bedrock",
        "model_id": model_id,
        "processed_at": updated_at,
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
