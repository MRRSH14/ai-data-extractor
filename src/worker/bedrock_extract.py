import json
import os

import boto3  # type: ignore[reportMissingImports]
from botocore.exceptions import ClientError  # type: ignore[reportMissingImports]

from shared import ErrorCode, logger
from worker.errors import non_retryable
from worker.validation import coerce_and_validate_result


def bedrock_client():
    region = os.getenv("BEDROCK_REGION")
    if region:
        return boto3.client("bedrock-runtime", region_name=region)
    return boto3.client("bedrock-runtime")


def build_model_prompt(text: str, schema: dict) -> str:
    schema_json = json.dumps(schema, ensure_ascii=True, sort_keys=True)
    return (
        "Extract fields from the provided text using the schema.\n"
        "Return only a JSON object with top-level keys from schema.\n"
        "Do not include markdown, explanations, or extra keys.\n\n"
        f"Schema:\n{schema_json}\n\n"
        f"Text:\n{text}"
    )


def extract_json_object_text(text: str) -> str:
    candidate = text.strip()
    if not candidate:
        raise non_retryable(ErrorCode.MODEL_OUTPUT_INVALID, "model output is empty")

    # Common LLM pattern: ```json ... ```
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    if candidate.startswith("{") and candidate.endswith("}"):
        return candidate

    start = candidate.find("{")
    if start == -1:
        raise non_retryable(ErrorCode.MODEL_OUTPUT_INVALID, "model output does not contain a JSON object")

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

    raise non_retryable(ErrorCode.MODEL_OUTPUT_INVALID, "model output contains incomplete JSON object")


def invoke_bedrock_extract(text: str, schema: dict) -> dict:
    model_id = os.getenv("BEDROCK_MODEL_ID")
    if not model_id:
        raise non_retryable(ErrorCode.CONFIG_ERROR, "BEDROCK_MODEL_ID is not configured")

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "temperature": 0,
        "messages": [{"role": "user", "content": build_model_prompt(text, schema)}],
    }

    try:
        client = bedrock_client()
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
        if code == "ValidationException" and "inference profile" in message.lower():
            raise non_retryable(
                ErrorCode.BEDROCK_CONFIG,
                "BEDROCK_MODEL_ID must be an inference profile ID or ARN for this model",
            ) from None
        if code == "AccessDeniedException" and (
            "aws-marketplace:subscribe" in message.lower()
            or "aws-marketplace:viewsubscriptions" in message.lower()
            or "marketplace subscription" in message.lower()
        ):
            raise non_retryable(
                ErrorCode.BEDROCK_ACCESS,
                "Bedrock model access is not enabled for this account. "
                "Grant AWS Marketplace permissions and subscribe/enable the model first.",
            ) from None
        logger.exception("Bedrock invoke failed", extra={"component": "worker", "event": "bedrock_error"})
        raise

    raw_body = response.get("body")
    if raw_body is None:
        raise non_retryable(ErrorCode.BEDROCK_RESPONSE_INVALID, "Bedrock response body is missing")

    response_json = json.loads(raw_body.read())
    content = response_json.get("content")
    if not isinstance(content, list) or not content:
        raise non_retryable(ErrorCode.BEDROCK_RESPONSE_INVALID, "Bedrock response content is missing")

    first_block = content[0]
    if not isinstance(first_block, dict):
        raise non_retryable(
            ErrorCode.BEDROCK_RESPONSE_INVALID, "Bedrock response content block is invalid"
        )
    text_output = first_block.get("text")
    if not isinstance(text_output, str) or not text_output.strip():
        raise non_retryable(ErrorCode.BEDROCK_RESPONSE_INVALID, "Bedrock text output is missing")

    try:
        parsed = json.loads(extract_json_object_text(text_output))
    except json.JSONDecodeError as exc:
        raise non_retryable(
            ErrorCode.MODEL_OUTPUT_INVALID,
            f"model output is not valid JSON: {exc.msg}",
        ) from None

    return coerce_and_validate_result(parsed, schema)

