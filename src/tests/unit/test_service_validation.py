import json
import os

# Prevent boto3 credential/provider initialization from requiring local AWS setup.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from service.validation import validate_extract_input, validation_error


def test_validation_error_includes_error_code() -> None:
    resp = validation_error("corr-1", "bad input", error_code="INPUT_CONTRACT")
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 400
    assert body["error"] == "bad input"
    assert body["error_code"] == "INPUT_CONTRACT"


def test_validate_extract_input_accepts_minimal_valid_payload() -> None:
    payload = {
        "mode": "text",
        "text": "Invoice INV-1 amount 10",
        "schema": {
            "invoice_id": {"type": "string", "required": True},
            "amount": {"type": "number", "minimum": 0},
        },
    }
    assert validate_extract_input(payload, correlation_id="corr-1") is None


def test_validate_extract_input_rejects_invalid_string_length_bounds() -> None:
    payload = {
        "mode": "text",
        "text": "x",
        "schema": {
            "invoice_id": {"type": "string", "min_length": 5, "max_length": 2},
        },
    }
    resp = validate_extract_input(payload, correlation_id="corr-1")
    assert resp is not None
    body = json.loads(resp["body"])
    assert body["error_code"] == "SCHEMA_INVALID"
    assert "min_length cannot exceed max_length" in body["error"]


def test_validate_extract_input_rejects_invalid_number_bounds() -> None:
    payload = {
        "mode": "text",
        "text": "amount 10",
        "schema": {
            "amount": {"type": "number", "minimum": 10, "maximum": 5},
        },
    }
    resp = validate_extract_input(payload, correlation_id="corr-1")
    assert resp is not None
    body = json.loads(resp["body"])
    assert body["error_code"] == "SCHEMA_INVALID"
    assert "minimum cannot exceed maximum" in body["error"]


def test_validate_extract_input_accepts_file_mode_s3_reference() -> None:
    payload = {
        "mode": "file",
        "file": {
            "source": "s3",
            "bucket": "invoices-bucket",
            "key": "raw/invoice-001.txt",
        },
        "schema": {
            "invoice_id": {"type": "string", "required": True},
        },
    }
    assert validate_extract_input(payload, correlation_id="corr-1") is None


def test_validate_extract_input_rejects_file_mode_missing_bucket() -> None:
    payload = {
        "mode": "file",
        "file": {
            "source": "s3",
            "key": "raw/invoice-001.txt",
        },
        "schema": {
            "invoice_id": {"type": "string"},
        },
    }
    resp = validate_extract_input(payload, correlation_id="corr-1")
    assert resp is not None
    body = json.loads(resp["body"])
    assert body["error_code"] == "INPUT_CONTRACT"
    assert "input.file.bucket must be a non-empty string" == body["error"]
