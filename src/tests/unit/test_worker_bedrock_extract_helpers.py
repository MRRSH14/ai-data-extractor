import os

import pytest

# Prevent boto3 credential/provider initialization from requiring local AWS setup.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from worker.bedrock_extract import extract_json_object_text
from worker.errors import NonRetryableProcessingError


def test_extract_json_object_text_accepts_plain_json() -> None:
    text = '{"invoice_id":"INV-1","amount":42.5,"is_paid":true}'
    assert extract_json_object_text(text) == text


def test_extract_json_object_text_accepts_fenced_json() -> None:
    text = """```json
{"invoice_id":"INV-1","amount":42.5,"is_paid":true}
```"""
    assert extract_json_object_text(text) == '{"invoice_id":"INV-1","amount":42.5,"is_paid":true}'


def test_extract_json_object_text_extracts_from_mixed_text() -> None:
    text = (
        "Here is your result:\n"
        '{"invoice_id":"INV-99","amount":"12.75","is_paid":"yes"}\n'
        "Done."
    )
    assert extract_json_object_text(text) == '{"invoice_id":"INV-99","amount":"12.75","is_paid":"yes"}'


def test_extract_json_object_text_rejects_missing_json() -> None:
    with pytest.raises(
        NonRetryableProcessingError, match=r"MODEL_OUTPUT_INVALID.*does not contain a JSON object"
    ):
        extract_json_object_text("No JSON here")
