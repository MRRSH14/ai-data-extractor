import os
from decimal import Decimal

import pytest

# Prevent boto3 credential/provider initialization from requiring local AWS setup
# when importing worker/shared modules in unit tests.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from worker.worker_handler import (
    NonRetryableProcessingError,
    _coerce_and_validate_result,
    _extract_json_object_text,
)


def test_extract_json_object_text_accepts_plain_json() -> None:
    text = '{"invoice_id":"INV-1","amount":42.5,"is_paid":true}'
    assert _extract_json_object_text(text) == text


def test_extract_json_object_text_accepts_fenced_json() -> None:
    text = """```json
{"invoice_id":"INV-1","amount":42.5,"is_paid":true}
```"""
    assert _extract_json_object_text(text) == '{"invoice_id":"INV-1","amount":42.5,"is_paid":true}'


def test_extract_json_object_text_extracts_from_mixed_text() -> None:
    text = (
        "Here is your result:\n"
        '{"invoice_id":"INV-99","amount":"12.75","is_paid":"yes"}\n'
        "Done."
    )
    assert _extract_json_object_text(text) == '{"invoice_id":"INV-99","amount":"12.75","is_paid":"yes"}'


def test_extract_json_object_text_rejects_missing_json() -> None:
    with pytest.raises(NonRetryableProcessingError, match="does not contain a JSON object"):
        _extract_json_object_text("No JSON here")


def test_coerce_and_validate_result_normalizes_supported_types() -> None:
    schema = {
        "invoice_id": {"type": "string"},
        "amount": {"type": "number"},
        "is_paid": {"type": "boolean"},
    }
    raw = {
        "invoice_id": 123,
        "amount": "42.5",
        "is_paid": "yes",
    }

    normalized = _coerce_and_validate_result(raw, schema)

    assert normalized["invoice_id"] == "123"
    assert normalized["amount"] == Decimal("42.5")
    assert normalized["is_paid"] is True


def test_coerce_and_validate_result_rejects_boolean_for_number() -> None:
    schema = {"amount": {"type": "number"}}
    raw = {"amount": True}

    with pytest.raises(NonRetryableProcessingError, match="must be a number, got boolean"):
        _coerce_and_validate_result(raw, schema)


def test_coerce_and_validate_result_rejects_invalid_boolean_text() -> None:
    schema = {"is_paid": {"type": "boolean"}}
    raw = {"is_paid": "sometimes"}

    with pytest.raises(NonRetryableProcessingError, match="must be boolean"):
        _coerce_and_validate_result(raw, schema)
