import io
import os

import pytest  # type: ignore[reportMissingImports]
from botocore.exceptions import ClientError  # type: ignore[reportMissingImports]

# Prevent boto3 credential/provider initialization from requiring local AWS setup.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from worker.errors import NonRetryableProcessingError
from worker.file_loader import load_s3_text_object


class _FakeS3Client:
    def __init__(self, payload: bytes | None = None, error_code: str | None = None):
        self.payload = payload
        self.error_code = error_code

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        if self.error_code:
            raise ClientError(
                {
                    "Error": {
                        "Code": self.error_code,
                        "Message": f"simulated {self.error_code}",
                    }
                },
                "GetObject",
            )
        return {"Body": io.BytesIO(self.payload or b"")}


def test_load_s3_text_object_reads_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "worker.file_loader.s3_client",
        lambda: _FakeS3Client(payload=b"Invoice INV-1 amount 10"),
    )
    text = load_s3_text_object("bucket-a", "path/file.txt")
    assert text == "Invoice INV-1 amount 10"


def test_load_s3_text_object_rejects_non_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "worker.file_loader.s3_client",
        lambda: _FakeS3Client(payload=b"\xff\xfe\x00\x00"),
    )
    with pytest.raises(NonRetryableProcessingError, match=r"INPUT_CONTRACT.*must be UTF-8 text"):
        load_s3_text_object("bucket-a", "path/file.bin")


def test_load_s3_text_object_rejects_missing_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "worker.file_loader.s3_client",
        lambda: _FakeS3Client(error_code="NoSuchKey"),
    )
    with pytest.raises(NonRetryableProcessingError, match=r"INPUT_CONTRACT.*s3 object not found"):
        load_s3_text_object("bucket-a", "path/missing.txt")
