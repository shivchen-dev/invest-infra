# PR-7: Read-only Research API

## Scope

Expose the six GET endpoints frozen in the Research lifecycle plan. The API
reads existing ResearchCase, EvidencePack, ResearchRun, and ResearchResult
records; it does not create, retry, cancel, or mutate research state.

## Architecture decisions

- Add only the repository pagination/count methods required by the two list
  endpoints; no migration or model change.
- Put query orchestration and SQLAlchemy exception sanitization in one API
  Application Query Service. Routers only validate inputs and map responses.
- Return audit-relevant EvidencePack content, but omit workspace paths,
  E2E/internal request metadata, credentials, and storage implementation data.
- Keep Case and Run list ordering deterministic and SQL-paginated.

## Increments

### Increment 1: storage read surface

Add deterministic `list_recent(limit, offset)` and `count_all()` methods to
ResearchCase and ResearchRun repositories and their UoW protocols.

Acceptance: mock repository tests cover ordering, pagination, and exact count;
existing storage tests and architecture checks pass.

### Increment 2: query service and public contract

Add narrow reader protocols, query methods for six use cases, sanitized query
errors, and Pydantic response schemas. Evidence response must not contain
`workspace_path`, `e2a_request_id`, or `e2a_session_id`.

Acceptance: service tests cover list/detail/evidence/result, missing related
records, and SQLAlchemy error translation.

### Increment 3: HTTP wiring

Add dependency construction, routers, application registration, endpoint
tests, and regenerate `apps/api/openapi.json`.

Acceptance: exactly six new GET routes; pagination is bounded; 404 and 500
responses are sanitized; unsupported write methods are absent.

## Verification

- Focused storage and API tests.
- Full Storage mock tests and full API tests.
- Ruff, architecture boundary check, OpenAPI freshness, and `git diff --check`.
- Confirm the three pre-existing unrelated untracked files remain untouched.

## Excluded

Migrations, domain changes, JiuwenSwarm changes, write/action endpoints, Web UI,
deployment, and semantic investment-decision logic.
