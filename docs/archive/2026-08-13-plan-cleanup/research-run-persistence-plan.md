# Implementation Plan: Research lifecycle — PR-5.5 persistence closure

## Overview

Persist `ResearchRun` attempts and immutable `ResearchResult` values before the
JiuwenSwarm adapter is introduced. The slice extends the existing analytics
schema, storage repositories, and Unit of Work without importing JiuwenSwarm or
adding API endpoints.

## Architecture decisions

- Store runs and results as separate lifecycle records under `analytics`.
- Preserve exact domain UUIDs; persistence must round-trip domain objects.
- A result is immutable and unique per run. A succeeded run cannot publish two
  results.
- Run state changes use compare-and-set semantics so stale workers cannot
  overwrite a newer state.
- Reserve nullable external request/session identity on the run persistence
  boundary and enforce session uniqueness for the later adapter; domain remains
  independent of JiuwenSwarm.
- Keep this slice additive and independently rollbackable.

## Task list

### Slice 1: Migration and row contracts

- Add `analytics.research_runs` and `analytics.research_results` migration.
- Add SQLAlchemy row models with foreign keys, checks, indexes, result/run
  uniqueness, and external-session uniqueness.
- Verify upgrade/downgrade shape and single migration head.

### Slice 2: Repository round trips

- Add run/result repository ports and SQLAlchemy implementations.
- Cover add/get/list, immutable result publication, external identity lookup,
  and stale compare-and-set rejection.
- Verify with public-interface unit and PostgreSQL integration tests.

### Slice 3: Unit of Work and documentation status

- Expose both repositories through the existing Unit of Work.
- Update the Research lifecycle plan's actual completion status and insert
  PR-5.5 before PR-6.
- Run focused tests, full relevant regression, Ruff, architecture checks, and
  `git diff --check`.

## Acceptance checkpoint

- A run survives a database round trip in every domain state.
- A result survives a database round trip without changing evidence references.
- Concurrent stale state changes fail closed.
- One run/external session cannot publish duplicate successful results.
- Migration chain has exactly one head and downgrades cleanly.
- No JiuwenSwarm dependency or Research API is introduced.

## Status (PR-5.5)

| Slice | State | Evidence |
|---|---|---|
| Slice 1: migration + row contracts | Done | `apps/migrations/migrations/versions/20260807_0014_research_runs.py`; `tests/test_migration_chain.py` 11 passed. |
| Slice 2: repository round trips | Done | `tests/storage/test_research_run_repository_mock.py` (14), `tests/storage/test_research_result_repository_mock.py` (13), and the focused PostgreSQL integration `tests/storage/integration/test_research_run_result_repositories.py` (9 passed). |
| Slice 3: UoW + documentation status | Done | `tests/storage/test_unit_of_work_mock.py` PR-5.5 blocks green; storage mocks (mock tests under `tests/storage/`, excluding integration) 205 passed; pipeline suite 1461 passed. |

Lifecycle beyond PR-5.5 remains pending: the JiuwenSwarm Adapter (PR-6) and the read-only Research API (PR-7) are **not** delivered by this slice and must not be claimed as such.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Domain/storage drift | Round-trip tests use domain public constructors and equality. |
| Duplicate callback publication | Database uniqueness plus idempotent repository behavior. |
| Lost update during recovery | Compare-and-set status updates. |
| Scope creep into adapter/API | Explicitly exclude SDK, network calls, routers, and query services. |
