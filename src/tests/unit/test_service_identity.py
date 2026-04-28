import os

# Prevent boto3 credential/provider initialization from requiring local AWS setup.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from service.identity import get_identity_from_claims, get_jwt_claims


def test_get_jwt_claims_returns_empty_when_missing() -> None:
    assert get_jwt_claims({}) == {}


def test_get_identity_from_claims_reads_tenant_and_sub() -> None:
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "custom:tenant_id": "tenant-a",
                        "sub": "user-123",
                    }
                }
            }
        }
    }
    tenant_id, created_by = get_identity_from_claims(event)
    assert tenant_id == "tenant-a"
    assert created_by == "user-123"


def test_get_identity_from_claims_falls_back_to_email() -> None:
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "custom:tenant_id": "tenant-a",
                        "email": "user@example.com",
                    }
                }
            }
        }
    }
    tenant_id, created_by = get_identity_from_claims(event)
    assert tenant_id == "tenant-a"
    assert created_by == "user@example.com"
