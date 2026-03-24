# ADR 0003: Cognito User Pool JWT auth and tenant-aware task ownership

## Status

Accepted (design phase; implementation follows Week 3 scope)

## Context

The current API is fully open: callers can create tasks and fetch tasks by `task_id` without authentication or tenant isolation. This is acceptable for an early foundation, but not for a credible platform baseline.

For the next phase, we need:

- a standard AWS-native authentication boundary for API routes;
- simple tenant-aware ownership checks on task records;
- minimal complexity (no full RBAC system yet).

We considered Cognito options:

- **Cognito User Pool**: user directory + sign-in + JWT issuance for application/API auth.
- **Cognito Identity Pool**: temporary AWS credentials for clients to access AWS resources directly.

Our immediate need is API authentication and tenant scoping, not client-side direct AWS credentials.

## Decision

Use **Cognito User Pool + API Gateway JWT authorizer** for task endpoints.

### Route policy

- Keep `GET /health` public.
- Protect `POST /tasks` and `GET /tasks/{id}` with JWT authorizer.
- `GET /hello` may remain public temporarily (or be removed later).

### Token and claims usage

- Clients authenticate against Cognito User Pool and send `Authorization: Bearer <JWT>`.
- API Gateway validates token signature, issuer, audience, and expiration.
- API Lambda reads claims from request context.

### Tenant-aware task model

On task creation, store:

- `tenant_id`
- `created_by`
- `created_at` (already present today; keep as canonical creation timestamp)

On task read (`GET /tasks/{id}`):

- fetch task by `task_id`;
- compare caller tenant claim to task `tenant_id`;
- deny cross-tenant access.

## Consequences

### Positive

- API is no longer fully open.
- Tenant boundary is explicit in data and request handling.
- Keeps implementation straightforward while improving production credibility.

### Tradeoffs / limitations

- This is not full authorization modeling (roles/permission matrix not included).
- Claim-to-tenant mapping must be defined consistently (for example, custom claim or group mapping).
- Existing task items without `tenant_id` may need migration strategy or compatibility handling.

## Out of scope (intentionally)

- Full RBAC policy matrix.
- Admin multi-tenant dashboard.
- External policy engines / ABAC frameworks.
- Identity Pool-based direct AWS access flows.

## Implementation notes (Week 3)

1. CDK: create/configure User Pool and app client; add JWT authorizer on protected routes.
2. API handler: extract claims, write tenant-aware fields on `POST /tasks`.
3. API handler: enforce same-tenant reads on `GET /tasks/{id}`.
4. Docs: update architecture + README with auth boundary and route visibility.

