# M1 Storage Increment 3 — Test Results

## Summary

54 tests across 4 files all pass against a real PostgreSQL 16 container
spun up by Testcontainers. No migration files were modified; the
existing 26 static migration tests still pass; the architecture
boundary check still passes.

| Suite | File | Tests | Result |
|---|---|---|---|
| Instrument repository integration | `tests/storage/integration/test_instrument_repository.py` | 9 | PASSED |
| ProviderBatch repository integration | `tests/storage/integration/test_provider_batch_repository.py` | 7 | PASSED |
| UnitOfWork integration | `tests/storage/integration/test_unit_of_work.py` | 11 | PASSED |
| Mock-based repository unit tests | `tests/storage/test_repositories_mock.py` | 16 | PASSED |
| Mock-based UnitOfWork unit tests | `tests/storage/test_unit_of_work_mock.py` | 11 | PASSED |
| **Total** | | **54** | **54 passed** |

## Plan-mandated test coverage

| Plan requirement | Test | Status |
|---|---|---|
| `test_upsert_instrument_new` — insert returns UUID id | `test_upsert_instrument_new` | PASSED |
| `test_upsert_instrument_existing_returns_same_id` — same `(exchange, symbol)` returns same id | `test_upsert_instrument_existing_returns_same_id` | PASSED |
| `test_list_active_instruments_pagination` — boundary correct | `test_list_active_instruments_pagination` | PASSED |
| `test_provider_batch_save_and_get_by_id` | `test_provider_batch_save_and_get_by_id` | PASSED |
| `test_provider_batch_unique_batch_id` — duplicate raises | `test_provider_batch_unique_business_key_insert_raises` | PASSED |
| `test_uow_commit_persists_changes` | `test_uow_commit_persists_changes` | PASSED |
| `test_uow_rollback_discards_changes` | `test_uow_rollback_discards_changes` | PASSED |
| `test_uow_exception_triggers_rollback` | `test_uow_exception_triggers_rollback` | PASSED |
| `test_uow_context_manager_closes_session` | `test_uow_context_manager_closes_session` | PASSED |

## Acceptance gates

```
$ python scripts/check_architecture.py
Architecture boundaries OK

$ PYTHONPATH=packages/domain/src:packages/storage/src python -m unittest discover -s tests -v
Ran 26 tests in 0.011s
OK
```

## How to run

```bash
# All storage tests (integration + mock unit tests)
PYTHONPATH=packages/domain/src:packages/storage/src:tests \
  packages/storage/.venv/bin/python -m pytest tests/storage/ -v

# Integration tests only (requires Docker)
PYTHONPATH=packages/domain/src:packages/storage/src:tests \
  packages/storage/.venv/bin/python -m pytest tests/storage/integration/ -v

# Mock-based unit tests only (no Docker required)
PYTHONPATH=packages/domain/src:packages/storage/src:tests \
  packages/storage/.venv/bin/python -m pytest tests/storage/ --ignore=tests/storage/integration -v

# Skip integration tests when Docker is unavailable
INVEST_SKIP_DOCKER_TESTS=1 \
  PYTHONPATH=packages/domain/src:packages/storage/src:tests \
  packages/storage/.venv/bin/python -m pytest tests/storage/ -v
```

The skip path is verified — with `INVEST_SKIP_DOCKER_TESTS=1` set, the
27 integration tests are skipped while the 27 mock unit tests still
pass.

## Implementation notes

### Files added

- `packages/storage/src/invest_storage/providers.py` — `SessionProvider` Protocol
  + re-exports for the session-factory abstraction.
- `packages/storage/src/invest_storage/unit_of_work.py` — `UnitOfWork` Protocol,
  `SqlAlchemyUnitOfWork` implementation, `InstrumentRepositoryPort` /
  `ProviderBatchRepositoryPort` Protocols.
- `tests/storage/conftest.py` — Docker probe, `postgres_container`, `engine`,
  `session_factory_fixture`, `uow_factory` fixtures (session-scoped).
- `tests/storage/integration/conftest.py` — `_create_schemas_and_tables`
  (session autouse), `_truncate_between_tests` (function autouse),
  `db_session` (savepoint-isolated), `repository`, `batch_repository` fixtures.
- `tests/storage/integration/test_instrument_repository.py` — 9 integration tests.
- `tests/storage/integration/test_provider_batch_repository.py` — 7 integration tests.
- `tests/storage/integration/test_unit_of_work.py` — 11 integration tests.
- `tests/storage/INCREMENT3-RESULTS.md` — this file.

### Files modified

- `packages/storage/pyproject.toml` — added `testcontainers[postgres]` and `pytest`
  to a new `[dependency-groups] test` block. Production dependencies unchanged.
- `packages/storage/src/invest_storage/__init__.py` — re-exports the new
  `StoredProviderBatch`, `NewProviderBatch`, `SqlAlchemyProviderBatchRepository`,
  `SqlAlchemyUnitOfWork`, `UnitOfWork`, `SessionProvider`, and the
  Protocol classes.
- `packages/storage/src/invest_storage/repositories.py` — added
  `StoredProviderBatch` and `NewProviderBatch` dataclasses,
  `SqlAlchemyProviderBatchRepository`, plus
  `SqlAlchemyInstrumentRepository.get_by_id`, `get_by_business_key`, and
  `count_active` methods (existing `upsert_many` / `list_active` kept).

### Files NOT modified

> **Note (2026-07-31):** Migration files have been moved from `apps/api/migrations/` to `apps/migrations/migrations/`. The paths below reflect the historical location at the time of testing.

- `apps/api/migrations/versions/20260730_0001_initial.py` (now `apps/migrations/migrations/versions/`)
- `apps/api/migrations/versions/20260730_0002_instruments_uuid_identity.py` (now `apps/migrations/migrations/versions/`)
- `apps/api/migrations/versions/20260730_0003_provider_batches_raw_evidence.py` (now `apps/migrations/migrations/versions/`)
- `packages/storage/src/invest_storage/database.py` — kept as the low-level
  engine / session primitive; the new `providers.py` re-exports the symbols
  callers need.
- `packages/storage/src/invest_storage/models.py` — already covered the
  schema needed by the new code (the migration 0003 CHECK constraints
  are honoured by the repository helpers).

### Test isolation strategy

- One disposable PostgreSQL container is spun up per `pytest` session via
  the `postgres_container` fixture.
- The schemas (`core`, `raw`, `app`) and all ORM tables are created once
  per session by `_create_schemas_and_tables` in
  `tests/storage/integration/conftest.py`.
- Each integration test gets a function-scoped `db_session` that
  participates in a savepoint inside an outer transaction. Calls to
  `session.commit()` / `session.rollback()` inside the test release or
  roll back the savepoint, not the outer transaction; the outer
  transaction rolls back when the fixture tears down, wiping every
  change the test made.
- An autouse `_truncate_between_tests` fixture also `TRUNCATE`s every
  table before each integration test. This protects tests that build a
  `UnitOfWork` against the bare `session_factory_fixture` (which does
  not go through savepoints) and therefore commit at the SQL level.
- Mock-based unit tests in `tests/storage/` do not depend on the
  integration fixtures, so they keep running in environments without
  Docker.

### Docker skip behaviour

The `_docker_available()` helper probes the Docker daemon before
spinning up the container; when the daemon is not reachable (or
`INVEST_SKIP_DOCKER_TESTS=1` is set), the `postgres_container`
fixture raises `pytest.skip(...)` with a descriptive message. Verified
locally:

```
$ INVEST_SKIP_DOCKER_TESTS=1 \
    PYTHONPATH=packages/domain/src:packages/storage/src:tests \
    packages/storage/.venv/bin/python -m pytest tests/storage/
======================== 27 passed, 27 skipped in 0.05s ========================
```

### Sample output (Docker available, full suite)

```
============================= 54 passed in 6.45s ==============================
```
