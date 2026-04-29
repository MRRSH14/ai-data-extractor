import os
from decimal import Decimal

import pytest

# Prevent boto3 credential/provider initialization from requiring local AWS setup.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from worker.errors import NonRetryableProcessingError
from worker.validation import coerce_and_validate_result, validate_extract_payload


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

    normalized = coerce_and_validate_result(raw, schema)

    assert normalized["invoice_id"] == "123"
    assert normalized["amount"] == Decimal("42.5")
    assert normalized["is_paid"] is True


def test_coerce_and_validate_result_rejects_boolean_for_number() -> None:
    schema = {"amount": {"type": "number"}}
    raw = {"amount": True}

    with pytest.raises(NonRetryableProcessingError, match=r"SCHEMA_VALIDATION.*must be a number, got boolean"):
        coerce_and_validate_result(raw, schema)


def test_coerce_and_validate_result_rejects_invalid_boolean_text() -> None:
    schema = {"is_paid": {"type": "boolean"}}
    raw = {"is_paid": "sometimes"}

    with pytest.raises(NonRetryableProcessingError, match=r"SCHEMA_VALIDATION.*must be boolean"):
        coerce_and_validate_result(raw, schema)


def test_coerce_and_validate_result_enforces_required_field() -> None:
    schema = {"invoice_id": {"type": "string", "required": True}}
    raw = {}

    with pytest.raises(NonRetryableProcessingError, match=r'SCHEMA_VALIDATION.*required field "invoice_id" missing'):
        coerce_and_validate_result(raw, schema)


def test_coerce_and_validate_result_enforces_string_enum() -> None:
    schema = {"status": {"type": "string", "enum": ["paid", "unpaid"]}}
    raw = {"status": "paid"}
    normalized = coerce_and_validate_result(raw, schema)
    assert normalized["status"] == "paid"


def test_coerce_and_validate_result_rejects_string_enum_miss() -> None:
    schema = {"status": {"type": "string", "enum": ["paid", "unpaid"]}}
    raw = {"status": "pending"}

    with pytest.raises(NonRetryableProcessingError, match=r'SCHEMA_VALIDATION.*field "status" must be one of'):
        coerce_and_validate_result(raw, schema)


def test_coerce_and_validate_result_enforces_number_enum_after_coercion() -> None:
    schema = {"amount": {"type": "number", "enum": [10, 42.5]}}
    raw = {"amount": "42.5"}
    normalized = coerce_and_validate_result(raw, schema)
    assert normalized["amount"] == Decimal("42.5")


def test_coerce_and_validate_result_enforces_string_length_constraints() -> None:
    schema = {"code": {"type": "string", "min_length": 2, "max_length": 5}}
    raw = {"code": "AB12"}
    normalized = coerce_and_validate_result(raw, schema)
    assert normalized["code"] == "AB12"


def test_coerce_and_validate_result_rejects_string_too_short() -> None:
    schema = {"code": {"type": "string", "min_length": 4}}
    raw = {"code": "AB"}
    with pytest.raises(NonRetryableProcessingError, match=r"SCHEMA_VALIDATION.*length must be >= 4"):
        coerce_and_validate_result(raw, schema)


def test_coerce_and_validate_result_enforces_number_range_constraints() -> None:
    schema = {"score": {"type": "number", "minimum": 0, "maximum": 100}}
    raw = {"score": "42.5"}
    normalized = coerce_and_validate_result(raw, schema)
    assert normalized["score"] == Decimal("42.5")


def test_coerce_and_validate_result_rejects_number_below_minimum() -> None:
    schema = {"score": {"type": "number", "minimum": 10}}
    raw = {"score": 5}
    with pytest.raises(NonRetryableProcessingError, match=r"SCHEMA_VALIDATION.*must be >= 10"):
        coerce_and_validate_result(raw, schema)


def test_validate_extract_payload_accepts_file_mode_s3_reference() -> None:
    payload = {
        "job_type": "extract",
        "input": {
            "mode": "file",
            "file": {
                "source": "s3",
                "bucket": "invoices-bucket",
                "key": "raw/invoice-001.txt",
            },
            "schema": {"invoice_id": {"type": "string"}},
        },
    }

    input_spec, schema = validate_extract_payload(payload)
    assert input_spec["mode"] == "file"
    assert input_spec["file"]["bucket"] == "invoices-bucket"
    assert input_spec["file"]["key"] == "raw/invoice-001.txt"
    assert "invoice_id" in schema
