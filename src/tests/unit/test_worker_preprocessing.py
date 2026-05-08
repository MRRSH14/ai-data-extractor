import os

import pytest  # type: ignore[reportMissingImports]
from botocore.exceptions import ClientError  # type: ignore[reportMissingImports]

# Prevent boto3 credential/provider initialization from requiring local AWS setup.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from worker.errors import NonRetryableProcessingError
from worker.preprocessing import preprocess_file_to_text


def test_preprocess_file_to_text_routes_text_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "worker.preprocessing.load_s3_text_object",
        lambda bucket, key: f"text:{bucket}/{key}",
    )
    result = preprocess_file_to_text("bucket-a", "docs/input.txt")
    assert result == "text:bucket-a/docs/input.txt"


def test_preprocess_file_to_text_rejects_unsupported_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Avoid network calls by forcing content-type fallback to remain unknown.
    monkeypatch.setattr(
        "worker.preprocessing.get_s3_object_content_type",
        lambda bucket, key: None,
    )
    with pytest.raises(NonRetryableProcessingError, match=r"INPUT_CONTRACT.*unsupported file type"):
        preprocess_file_to_text("bucket-a", "docs/input.docx")


def test_preprocess_file_to_text_uses_textract_for_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeTextractClient:
        def detect_document_text(self, *, Document: dict) -> dict:
            assert Document["S3Object"]["Bucket"] == "bucket-a"
            assert Document["S3Object"]["Name"] == "docs/input.pdf"
            return {
                "Blocks": [
                    {"BlockType": "LINE", "Text": "Invoice INV-100"},
                    {"BlockType": "LINE", "Text": "Total 42.5"},
                ]
            }

    monkeypatch.setattr("worker.preprocessing.textract_client", lambda: _FakeTextractClient())
    text = preprocess_file_to_text("bucket-a", "docs/input.pdf")
    assert text == "Invoice INV-100\nTotal 42.5"


def test_preprocess_file_to_text_uses_content_type_fallback_for_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeTextractClient:
        def detect_document_text(self, *, Document: dict) -> dict:
            return {"Blocks": [{"BlockType": "LINE", "Text": "Invoice INV-200"}]}

    monkeypatch.setattr(
        "worker.preprocessing.get_s3_object_content_type",
        lambda bucket, key: "application/pdf",
    )
    monkeypatch.setattr("worker.preprocessing.textract_client", lambda: _FakeTextractClient())
    text = preprocess_file_to_text("bucket-a", "uploads/no-extension")
    assert text == "Invoice INV-200"


def test_preprocess_file_to_text_maps_textract_unsupported_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeTextractClient:
        def detect_document_text(self, *, Document: dict) -> dict:
            raise ClientError(
                {"Error": {"Code": "UnsupportedDocumentException", "Message": "unsupported"}},
                "DetectDocumentText",
            )

    monkeypatch.setattr("worker.preprocessing.textract_client", lambda: _FakeTextractClient())
    with pytest.raises(NonRetryableProcessingError, match=r"INPUT_CONTRACT.*unsupported document"):
        preprocess_file_to_text("bucket-a", "docs/input.pdf")
