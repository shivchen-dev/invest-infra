# PR-7 Read-only Research API Checklist

- [x] Add deterministic paginated Case/Run repository reads and counts.
- [x] Add repository mock tests for pagination, ordering, and count.
- [x] Add the Research Application Query Service and sanitized error boundary.
- [x] Add public Case, Evidence, Run, and Result response schemas.
- [x] Add exactly six read-only Research endpoints and dependency wiring.
- [x] Add service and endpoint tests, including 404/422/500 behavior.
- [x] Add HTTP-seam behavior tests with real `ResearchCase` / `EvidencePack` / `ResearchRun` / `ResearchResult` domain objects, asserting exact JSON serialization, explicit factor unit, and absence of `workspace_path` / `e2a_request_id` / `e2a_session_id` in the actual response payload.
- [x] Verify sensitive/internal Evidence metadata is absent from responses.
- [x] Regenerate and verify `apps/api/openapi.json`.
- [x] Run full API, relevant Storage, Ruff, architecture, and diff checks.

## Fresh results (2026-08-08)

- Focused service + endpoint + HTTP-seam tests: 16 passed (4 detail-serialization + 6 endpoint + 6 service).
- Full API suite: 199 passed.
- Storage mock tests (excluding integration): 217 passed.
- Ruff (`apps/api`): clean.
- Architecture boundary check: clean.
- OpenAPI regen: no drift (`md5 f1427b434b03bbc27a463f5473bd08dc`).
- `git diff --check`: clean.
- Protected untracked files (`docs/archive/2026-08-06-plan-cleanup/README.md`, `packages/domain/uv.lock`, `packages/storage/uv.lock`): untouched.
