def get_jwt_claims(event: dict) -> dict:
    request_context = event.get("requestContext", {})
    authorizer = request_context.get("authorizer", {})
    jwt = authorizer.get("jwt", {})
    claims = jwt.get("claims")
    if isinstance(claims, dict):
        return claims
    return {}


def get_identity_from_claims(event: dict) -> tuple[str | None, str | None]:
    claims = get_jwt_claims(event)
    tenant_id = claims.get("custom:tenant_id")
    created_by = claims.get("sub") or claims.get("email")
    if not isinstance(tenant_id, str):
        tenant_id = None
    if not isinstance(created_by, str):
        created_by = None
    return tenant_id, created_by
