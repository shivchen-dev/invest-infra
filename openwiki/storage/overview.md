---
type: Concept
title: Storage overview
description: SQLAlchemy 2 ORM models, repositories, the SqlAlchemyUnitOfWork + SessionProvider, the three-layer Provider evidence model, the candidate-pool snapshot and job-history read contracts, the DC-2 ETF profile and per-field evidence repositories, and the Stage 4A research context pack persistence under packages/storage/src/invest_storage.
resource: /openwiki/storage/overview.md
tags: [storage, sqlalchemy, repository, unit-of-work, provider-evidence, etf-profile, research-context]
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
  `CandidatePoolItemRow`, `ResearchEvidencePackRow`,
  `EtfProfileRow`, `EtfProfileFieldRow`, `ResearchContextPackRow`,
  `ResearchContextItemRow`.
- **Repositories and DTOs.** `SqlAlchemy*Repository` classes plus the
  `New*` and `Stored*` dataclasses that shape their inputs and outputs.
- **Unit of Work.** `UnitOfWork` (Protocol), `SqlAlchemyUnitOfWork`
  (impl), `SessionProvider` (Protocol), and the per-collection port
  Protocols (`InstrumentRepositoryPort`, `DailyBarRepositoryPort`,
  `EtfProfileRepositoryPort`, `EtfProfileFieldRepositoryPort`,
  `ResearchContextPackRepositoryPort`, …).

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
  `get_by_id`, `get_many_by_ids`, `get_by_business_key`, `list_active`,
  `count_active`.
- `SqlAlchemyProviderRequestRepository`: `add`, `get_or_create`,
  `get_by_logical_key`, `mark_status`.
- `SqlAlchemyProviderAttemptRepository`: `add`, `start`, `mark_succeeded`,
  `mark_failed`, `get_by_id`, `list_by_request`.
- `SqlAlchemyProviderBatchRepository`: `add`, `list_by_attempt`,
  `list_by_provider_dataset`.
- `SqlAlchemyPipelineRunRepository`: `start`, `mark_succeeded`,
  `mark_failed`, `get_by_id`, `list_recent`, `list_by_job_key`,
  `count_by_job_key`, `count_by_status`.
- `SqlAlchemyCandidatePoolRunRepository`: `add`, `get_by_id`,
  `get_by_natural_key`, `transition_status`, `list_by_status`,
  `list_by_trade_date`.
- `SqlAlchemyCandidatePoolItemRepository`: `bulk_add`, `list_by_run_id`.
- `SqlAlchemyDailyBarRepository`: `upsert_many`, `get_latest`,
  `get_exact`, `list_by_instrument_and_range`.
- `SqlAlchemyEtfProfileRepository`: `upsert`, `get_by_id`,
  `list_by_manager`, `list_by_category`, `list_by_fund_type`,
  `list_all`, `count_all` (Stage DC-2; mirrors the
  `invest_domain.etf_profile.models.EtfProfile` contract 1-1).
- `SqlAlchemyEtfProfileFieldRepository`: `add`, `upsert`,
  `get_by_instrument`, `get_by_instrument_field` (PR-ETF-PROFILE-04;
  one row per `FieldEvidence` observation keyed on `content_hash`).
- `SqlAlchemyResearchContextPackRepository`: `add`, `upsert`,
  `get_by_id`, `get_by_instrument_and_version`, `list_by_instrument`
  (Stage 4A evidence / context separation; persists
  `ResearchContextPack` together with its child
  `ResearchContextItem` rows inside a single `UnitOfWork`).
- `InputSnapshotRepository`: `add`, `get_by_date_and_hash`,
  `list_by_date`.

Domain code (and the FastAPI routers) interact with repositories via
this module's surface. Application code that needs to coordinate
multiple repositories uses the `UnitOfWork` instead of taking
individual session handles.

`CandidatePoolRunRow.input_snapshot_id` is a non-null foreign key to
`analytics.input_snapshots.id`, named `fk_cpool_runs_snapshot_id`. The
Alembic [migration](../migrations/overview.md#the-six-revision-chain)
adds the same constraint, so a persisted candidate-pool run cannot point
at a missing input snapshot. This storage invariant backs the
[Candidate pool input-snapshot binding](../domain/candidate-pool.md#input-snapshot-binding)
and the API's published-pool audit response.

### Pipeline-run audit guards

`SqlAlchemyPipelineRunRepository` carries two safety nets the personal
CLI and the API rely on:

- `get_blocking_by_job_and_partition` first takes a
  `pg_advisory_xact_lock` keyed on a blake2b hash of
  `(len(job_key), job_key, partition_key)`, then returns the latest
  `ops.pipeline_runs` row whose `status` is in
  `('queued', 'running', 'succeeded')` for that `(job_key,
  partition_key)`. The recorder uses this as a single-run guard so a
  second concurrent manual invocation for the same partition cannot
  open a duplicate `running` row. `('failed', 'partial',
  'cancelled')` are explicitly **not** blocking — those are retryable
  outcomes and a fresh run may open a new row for the same partition.
- `mark_succeeded` is idempotent: when the row is already in the
  `succeeded` state the call returns the existing record without
  re-writing `finished_at`, so a duplicate
  `mark_succeeded` from a CLI retry after the original succeeded row
  has been persisted does not corrupt the audit history.
  `mark_failed` is the symmetric guard — it refuses to downgrade an
  already-`succeeded` row and raises `ValueError`; a retry that fails
  after a prior success must therefore open a brand-new
  `ops.pipeline_runs` row rather than overwriting the succeeded one.

## 4. Transactions and Unit of Work

`SqlAlchemyUnitOfWork`:

- Owns a single SQLAlchemy `Session` plus twelve lazily-built repository
  properties: `instruments`, `input_snapshot_repository`,
  `provider_requests`, `provider_attempts`, `provider_batches`,
  `pipeline_runs`, `candidate_pool_runs`, `candidate_pool_items`,
  `daily_bars`, `etf_profiles`, `etf_profile_fields`,
  `research_context_packs`.
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
| `analytics.candidate_pool_runs` / `_items` | `personal_candidate_pool` via `candidate_pool_service.calculate_and_publish_candidate_pool`, inside one `UnitOfWork`. | `/api/v1/candidate-pool/latest` and the candidate-pool diff endpoints. |
| `analytics.research_evidence_packs` | Stage 4A research evidence persistence (migration `20260803_0007`). The ORM class `ResearchEvidencePackRow` is defined in `models.py` but is **not** yet re-exported from `invest_storage.__init__`; no `SqlAlchemy*Repository`, no Unit-of-Work property, and no FastAPI router write or read it in this slice. | No API surface; the table is in place for a future persistence slice. |
| `core.etf_profiles` | DC-2 `etf_profiles` service (migration `20260804_0008_etf_profiles`). One row per `core.instruments` (instrument_id is both PK and FK), carrying the canonical ETF static metadata (`manager` / `benchmark_index` / `category` / `inception_date` / `fund_type` / `management_fee` / `custody_fee` / `aum` / `shares`). | No API surface yet; the table is the persistence target of `SqlAlchemyEtfProfileRepository.upsert`. |
| `analytics.etf_profile_fields` | PR-ETF-PROFILE-04 `etf_profile_fields` persistence (migration `20260805_0009_etf_profile_fields`). One row per `FieldEvidence` observation, idempotent on `content_hash`, with discriminated `field_value_text` / `field_value_numeric` / `field_value_date` columns plus source provenance and `(instrument_id, field_key)` index. | No API surface yet; the resolver reads through `SqlAlchemyEtfProfileFieldRepository.get_by_instrument_field`. |
| `analytics.research_context_packs` + `analytics.research_context_items` | Stage 4A evidence / context separation (migration `20260805_0010_research_context_packs`). One pack per `(instrument_id, context_version)`; child items carry the per-field `ContextItem` rows built by the pure `build_etf_profile_context_pack` builder. | No API surface yet; the tables are the persistence target of `SqlAlchemyResearchContextPackRepository` plus the child `ResearchContextItemRow` cascade. |
| `ops.pipeline_runs` | Pipeline job wrappers via `SqlAlchemyPipelineRunRepository`. | `/api/v1/pipeline-runs` latest, detail, and paginated history endpoints. |

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
