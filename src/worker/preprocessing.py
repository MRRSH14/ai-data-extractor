import os

import boto3  # type: ignore[reportMissingImports]
from botocore.exceptions import ClientError  # type: ignore[reportMissingImports]

from shared import ErrorCode
from worker.errors import non_retryable
from worker.file_loader import load_s3_text_object

TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json"}
TEXTRACT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"}


def textract_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if region:
        return boto3.client("textract", region_name=region)
    return boto3.client("textract")


def _detect_input_type(key: str) -> str:
    extension = ""
    if "." in key:
        extension = "." + key.rsplit(".", 1)[1].lower()

    if extension in TEXT_EXTENSIONS:
        return "text"
    if extension in TEXTRACT_EXTENSIONS:
        return "textract"
    raise non_retryable(
        ErrorCode.INPUT_CONTRACT,
        f'unsupported file extension for input.file.key: "{key}"',
    )


def _extract_text_via_textract(bucket: str, key: str) -> str:
    try:
        response = textract_client().detect_document_text(
            Document={"S3Object": {"Bucket": bucket, "Name": key}}
        )
    except ClientError as exc:
        code = (exc.response.get("Error") or {}).get("Code", "")
        if code in {"UnsupportedDocumentException", "InvalidS3ObjectException", "AccessDeniedException"}:
            raise non_retryable(
                ErrorCode.INPUT_CONTRACT,
                f'textract could not process "{bucket}/{key}": {code}',
            ) from None
        raise

    lines = []
    for block in response.get("Blocks", []):
        if isinstance(block, dict) and block.get("BlockType") == "LINE":
            text = block.get("Text")
            if isinstance(text, str) and text.strip():
                lines.append(text.strip())

    joined = "\n".join(lines).strip()
    if not joined:
        raise non_retryable(
            ErrorCode.MODEL_OUTPUT_INVALID,
            f'no extractable text found in "{bucket}/{key}"',
        )
    return joined


def preprocess_file_to_text(bucket: str, key: str) -> str:
    input_type = _detect_input_type(key)
    if input_type == "text":
        return load_s3_text_object(bucket, key)
    return _extract_text_via_textract(bucket, key)
