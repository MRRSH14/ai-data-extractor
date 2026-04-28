import os
from decimal import Decimal

# Prevent boto3 credential/provider initialization from requiring local AWS setup.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from worker.quality import build_quality_metadata


def test_build_quality_metadata_reports_coverage_and_field_presence() -> None:
    schema = {
        "invoice_id": {"type": "string", "required": True},
        "amount": {"type": "number", "required": True},
        "vendor_name": {"type": "string"},
    }
    result = {
        "invoice_id": "INV-42",
        "amount": Decimal("10.5"),
    }

    quality = build_quality_metadata(schema, result)

    assert quality["coverage"] == {
        "schema_fields_total": 3,
        "schema_fields_extracted": 2,
        "ratio": Decimal("0.6667"),
    }
    assert quality["required_coverage"] == {
        "required_fields_total": 2,
        "required_fields_extracted": 2,
        "ratio": Decimal("1.0000"),
    }
    assert quality["field_presence"] == {
        "invoice_id": True,
        "amount": True,
        "vendor_name": False,
    }
