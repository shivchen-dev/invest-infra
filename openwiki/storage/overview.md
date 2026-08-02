---
type: Concept
title: Storage overview
description: SQLAlchemy 2 ORM models, repositories, the SqlAlchemyUnitOfWork + SessionProvider, and the three-layer Provider evidence model under packages/storage/src/invest_storage.
resource: /openwiki/storage/overview.md
tags: [storage, sqlalchemy, repository, unit-of-work, provider-evidence]
---

# Storage overview

`packages/storage/src/invest_storage/` owns the SQLAlchemy 2 ORM
mappings, repository factories, and the `UnitOfWork` (UoW) that
coordinates every transaction. The package depends on
`packages/domain` but never on `apps/api` or `apps/pipeline`; it
therefore is reusable from either side without a cyclic import.

## 1. Module layout

```
packages/storage/src/invest_storage/
├── __init__.py             # public re-exports
├── database.py             # build_engine, session_factory, session_scope
├── models.py               # ORM tables (raw.* / core.* / analytics.* / ops.*)
├── repositories.py         # SQLAlchemy-backed repository factories
└── unit_of_work.py         # UoW Protocol + SqlAlchemyUnitOfWork + SessionProvider
```

The public surface (`invest_storage.__all__`) groups everything into
three buckets:

- **Models.** `Base`, `InstrumentRow`, `ProviderRequestRow`,
  `ProviderAttemptRow`, `RawProviderBatchRow`, `PipelineRunRow`,
  `DailyBarRow`, `InputSnapshotRow`, `CandidatePoolRunRow`,
  `CandidatePoolItemRow`.
- **Repositories and DTOs.** `SqlAlchemy*Repository` classes plus the
  `New*` and `Stored*` dataclasses that shape their inputs and outputs.
- **Unit of Work.** `UnitOfWork` (Protocol), `SqlAlchemyUnitOfWork`
  (impl), `SessionProvider` (Protocol), and the per-collection port
  Protocols (`InstrumentRepositoryPort`, `DailyBarRepositoryPort`, …).

## 2. Three-layer Provider evidence model

The PR-02 evidence bundle lives in `raw`:

```
raw.provider_requests ──< raw.provider_attempts ──< raw.provider_batches
```

| Row | Purpose |
|-----|---------|
| `provider_requests` | One row per logical request. Unique on `(provider_key, dataset_key, request_key)`. Carries `request_params` jsonb and the lifecycle status. |
| `provider_attempts` | One row per network/SDK attempt (retries / fail-over). FK to `provider_requests.id`, `attempt_no >= 1`, error metadata on failure, sidecar JSON on success. |
| `provider_batches` | One row per successful or partial batch. FKs to the request and the attempt; payload hash and warnings. No row exists if the attempt failed. |

CHECK constraints encode the lifecycle:

- `provider_attempts`: `status IN ('running','succeeded','failed')`,
  succeeded rows must carry `response_payload_sha256`, failed rows
  must carry `error_stage` + `error_code`, `finished_at >= started_at`.
- `provider_batches` are created only for `('succeeded','partial')`.

The application service in `apps/pipeline/src/invest_pipeline/etf_*.py`
is responsible for persisting all three rows inside a single
`UnitOfWork` so the assignment of UUIDs to `provider_attempts` and
`provider_batches` is atomic. Adapters never see a `Session`.

## 3. Repositories (`repositories.py`)

For every business object there is a `SqlAlchemy*Repository` plus a
`New*` (write-input) and `Stored*` (read-output) dataclass. Repositories
always hand callers **domain objects**, never SQLAlchemy ORM rows.
Examples:

- `SqlAlchemyInstrumentRepository`: `upsert_many`,
  `get_by_id`, `get_by_business_key`, `list_active`, `count_active`.
- `SqlAlchemyProviderRequestRepository`: `add`, `get_or_create`,
  `get_by_logical_key`, `mark_status`.
- `SqlAlchemyProviderAttemptRepository`: `add`, `start`, `mark_succeeded`,
  `mark_failed`, `get_by_id`, `list_by_request`.
- `SqlAlchemyProviderBatchRepository`: `add`, `list_by_attempt`,
  `list_by_provider_dataset`.
- `SqlAlchemyPipelineRunRepository`: `start`, `mark_succeeded`,
  `mark_failed`, `get_by_id`, `list_recent`, `count_by_status`.
- `SqlAlchemyCandidatePoolRunRepository`: `add`, `get_by_id`,
  `get_by_natural_key`, `transition_status`, `list_by_status`,
  `list_by_trade_date`.
- `SqlAlchemyCandidatePoolItemRepository`: `bulk_add`, `list_by_run_id`.
- `SqlAlchemyDailyBarRepository`: `upsert_many`, `get_latest`,
  `get_exact`, `list_by_instrument_and_range`.
- `InputSnapshotRepository`: `add`, `get_by_date_and_hash`,
  `list_by_date`.

Domain code (and the FastAPI routers) interact with repositories via
this module's surface. Application code that needs to coordinate
multiple repositories uses the `UnitOfWork` instead of taking
individual session handles.

## 4. Transactions and Unit of Work

`SqlAlchemyUnitOfWork`:

- Owns a single SQLAlchemy `Session` plus nine lazily-built repository
  properties: `instruments`, `input_snapshot_repository`,
  `provider_requests`, `provider_attempts`, `provider_batches`,
  `pipeline_runs`, `candidate_pool_runs`, `candidate_pool_items`,
  `daily_bars`.
- Is a context manager: `with uow:` enters, commits on clean exit,
  rolls back on exception, and always closes the session.
- Exposes a `commit()` / `rollback()` pair (mirroring `Session`) but
  the recommended style is the `with` block.

The `SessionProvider` Protocol (moved out of the now-deleted
`invest_storage.providers` module into `unit_of_work.py`) lets the
UoW be constructed against a fake provider in unit tests without
spinning up a real database. The default implementation is the
`sessionmaker` returned by `invest_storage.database.session_factory`.

The protocol-level repositories (`InstrumentRepositoryPort`,
`DailyBarRepositoryPort`, `ProviderAttemptRepositoryPort`, …) keep
application code decoupled from the SQLAlchemy implementation — the
UoW exposes them as `Protocol`s, while the actual work is done by the
SQLAlchemy classes above.

## 5. Where each table is written

| Table | Written by | Read by |
|-------|------------|---------|
| `raw.provider_*` | `apps/pipeline/.../etf_instruments.py` / `etf_daily_bars.py` through `SqlAlchemyUnitOfWork`. | Storage repository factories; not surfaced to the API yet. |
| `core.instruments` | `etf_instruments` asset; idempotent upsert keyed on `(symbol, exchange) WHERE delist_date IS NULL`. | FastAPI `/api/v1/etf/instruments`, `/v1/instruments`. |
| `core.daily_bars` | `etf_daily_bars` asset via `SqlAlchemyDailyBarRepository.upsert_many` (ADR-0006 revision rules). | `/api/v1/etf/daily-bars`. |
| `core.latest_daily_bars` | View maintained by the database (revision desc row_number). | New snapshot builders (NOT for replay). |
| `analytics.input_snapshots` | `etf_input_snapshot` asset + `InputSnapshotRepository.add`. | `/api/v1/candidate-pool/latest` (for `content_hash`). |
| `analytics.candidate_pool_runs` / `_items` | Future candidate-pool assets; today's only producer is the FastAPI router's read path. | `/api/v1/candidate-pool/latest`. |
| `ops.pipeline_runs` | Dagster job wrappers via `SqlAlchemyPipelineRunRepository`. | Future pipeline-runs pages; not surfaced to the API yet. |

## 6. Boundary rules enforced from the storage side

- `packages/storage/src` MUST NOT import `fastapi`, `dagster`,
  `akshare`, `vectorbt`, `backtrader` (see
  [Architecture overview §5](../architecture/overview.md#5-architecture-decision-records)).
- The transition guard on `CandidatePoolRun.transition_to` mirrors the
  protocol's legal-transition set; an attempt that violates the guard
  raises `ConcurrentTransitionError` rather than committing.

## 7. Tests

- **Unit (mock):** [`/tests/storage/test_*_mock.py`](../../tests/storage)
  exercise every repository against a `MagicMock` session.
- **Integration (Testcontainers):**
  [`/tests/storage/integration/`](../../tests/storage/integration)
  spins up a disposable PostgreSQL container, runs migrations, and
  exercises the same repositories end-to-end. CI runs them under the
  `storage-integration` job.
