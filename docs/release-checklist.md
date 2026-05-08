# Release checklist (5-day ship plan)

Use this checklist to move from current MVP to a public, showcase-ready open-source release.

## Goals

- ship a stable `v0.1.0` extractor MVP;
- make onboarding easy for reviewers;
- prepare clean artifacts for LinkedIn and interview/demo storytelling.

## Day 1 - Stability gate

- [ ] Run full unit tests (`PYTHONPATH=src infra/.venv/bin/python -m pytest src/tests/unit -q`).
- [ ] Run lint/diagnostics pass and fix regressions.
- [ ] Validate no unintended local changes (`git status` clean after fixes/commits).
- [ ] Record final "known limitations" list for release notes.

## Day 2 - Deploy and smoke validation

- [ ] Deploy stack from clean env (`cdk deploy`) with required Bedrock/Textract env vars.
- [ ] Run unified smoke script (`scripts/dev_smoke_all.sh`) for text and file modes.
- [ ] Manually verify three file scenarios:
  - valid S3 UTF-8 object -> `completed`;
  - missing key -> `failed` with deterministic input-contract style message;
  - non-UTF8 object -> deterministic non-retryable failure (no retry loop).
- [ ] Capture 2-3 evidence artifacts (task payloads, status snapshots, logs) for docs/post.

## Day 3 - Open-source polish

- [ ] Confirm `README.md` quickstart is complete and works end-to-end.
- [ ] Ensure core docs are coherent and linked:
  - `docs/architecture.md`
  - `docs/mvp-extractor.md`
  - `docs/implementation-plan.md`
  - `docs/runbooks/dlq-and-alerts.md`
  - `docs/adrs/*`
- [ ] Add/verify repository essentials:
  - `LICENSE`
  - contribution guide (`CONTRIBUTING.md`)
  - issue template(s) and PR template (optional but recommended)
- [ ] Add a short "Project status / roadmap" block in README (what is done now vs next).

## Day 4 - Showcase package

- [ ] Finalize one architecture diagram for the repository and LinkedIn visuals.
- [ ] Create `docs/design-decisions.md` (or equivalent) with key tradeoffs:
  - async API + worker pattern;
  - deterministic error taxonomy;
  - file-mode preprocessing + Textract path;
  - Step Functions deferred decision and migration triggers.
- [ ] Prepare one demo script narrative (3-5 minutes) with expected outputs.
- [ ] Draft release notes (`CHANGELOG.md` entry or GitHub release notes draft).

## Day 5 - Publish

- [ ] Final pass: tests + lint + smoke (quick confidence rerun).
- [ ] Tag release (`v0.1.0`) and publish GitHub release notes.
- [ ] Confirm repository visibility/settings and pinned README sections.
- [ ] Publish LinkedIn post with:
  - problem statement;
  - architecture snapshot;
  - notable engineering decisions;
  - outcomes + what you learned;
  - roadmap (Phase 4/5).

## Exit criteria (ready to post)

- [ ] New contributor can run the project from README without private context.
- [ ] All core tests pass and smoke flow is repeatable.
- [ ] Documentation reflects actual behavior (no stale contracts).
- [ ] Demo evidence exists for both success and deterministic failure paths.
- [ ] Public narrative is honest about scope, tradeoffs, and next steps.
