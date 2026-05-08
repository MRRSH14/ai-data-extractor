# Contributing

Thanks for contributing to `ai-data-extractor`.

## Development setup

1. Clone the repository.
2. Create a Python virtual environment for infra tooling:
   - `cd infra`
   - `python -m venv .venv && source .venv/bin/activate`
   - `pip install -r requirements.txt`
3. Return to repo root for app tests/scripts.

## Local validation before PR

- Unit tests:
  - `PYTHONPATH=src infra/.venv/bin/python -m pytest src/tests/unit -q`
- Keep docs aligned for any behavior/contract changes:
  - `README.md`
  - `docs/mvp-extractor.md`
  - `docs/architecture.md`
  - relevant ADR/runbook sections

## Pull request expectations

- Prefer small, focused PRs.
- Include:
  - what changed and why;
  - validation performed (tests/smoke/manual checks);
  - any follow-up work intentionally deferred.
- Preserve API contract stability unless the PR explicitly proposes a breaking change.

## Commit guidance

- Use clear, imperative commit messages.
- Keep refactors behavior-preserving unless otherwise stated.

## Reporting issues

When opening a bug, include:

- expected vs actual behavior;
- reproduction steps;
- relevant task ID / correlation ID / logs;
- environment context (AWS profile/region, stack state).
