import os

import boto3  # type: ignore[reportMissingImports]
from botocore.exceptions import ClientError  # type: ignore[reportMissingImports]

from shared import ErrorCode
from worker.errors import non_retryable


def s3_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if region:
        return boto3.client("s3", region_name=region)
    return boto3.client("s3")


def load_s3_text_object(bucket: str, key: str) -> str:
    try:
        response = s3_client().get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        error = exc.response.get("Error", {})
        code = error.get("Code", "")
        if code in {"NoSuchBucket", "NoSuchKey", "404"}:
            raise non_retryable(
                ErrorCode.INPUT_CONTRACT,
                f's3 object not found: "{bucket}/{key}"',
            ) from None
        if code == "AccessDenied":
            raise non_retryable(
                ErrorCode.INPUT_CONTRACT,
                f's3 access denied for "{bucket}/{key}"',
            ) from None
        raise

    body = response.get("Body")
    if body is None:
        raise non_retryable(
            ErrorCode.INPUT_CONTRACT,
            f's3 object body missing for "{bucket}/{key}"',
        )

    raw_bytes = body.read()
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise non_retryable(
            ErrorCode.INPUT_CONTRACT,
            f's3 object content invalid for "{bucket}/{key}"',
        )

    try:
        text = bytes(raw_bytes).decode("utf-8")
    except UnicodeDecodeError:
        raise non_retryable(
            ErrorCode.INPUT_CONTRACT,
            f's3 object "{bucket}/{key}" must be UTF-8 text',
        ) from None

    if not text.strip():
        raise non_retryable(
            ErrorCode.INPUT_CONTRACT,
            f's3 object "{bucket}/{key}" must be non-empty UTF-8 text',
        )
    return text
