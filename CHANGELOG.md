# Changelog

All notable changes to this project will be documented in this file.

## [v0.1.0] - 2026-05-08

### Added
- Extractor MVP supports `input.mode="text"` and `input.mode="file"` contract.
- File-mode preprocessing routes text-like files via UTF-8 decode and document/image files via Textract.
- S3 `ContentType` fallback for file-type routing when key extension is missing/unknown.
- Deterministic worker error taxonomy with stable prefixed error messages.
- Task-level `result_metadata.quality` metrics on completed extraction tasks.
- Internal `file_lifecycle_state` markers for file-mode operator visibility.
- Unified smoke tooling (`scripts/dev_smoke_all.sh`) and dedicated file-mode smoke script.
- Architecture decision record for orchestration boundary and Step Functions adoption triggers (`ADR 0004`).
- Open-source contributor package: `LICENSE`, `CONTRIBUTING.md`, issue templates, PR template.
- Quick evaluation assets in `samples/` (request payloads + expected terminal responses).

### Changed
- API and worker modules were refactored into smaller focused components with expanded unit tests.
- README onboarding flow now includes from-scratch quickstart and ordered docs navigation.
- Documentation updated to clarify `status` (client contract) vs `file_lifecycle_state` (internal telemetry).

### Validation
- Unit tests passing (`45 passed`).
- Deploy and smoke checks validated for text and file modes (success + deterministic failure paths).
