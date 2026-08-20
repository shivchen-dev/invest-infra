---
type: Concept
title: Storage overview
description: SQLAlchemy 2 ORM models, repositories, the SqlAlchemyUnitOfWork + SessionProvider, Provider evidence, candidate-pool and job-history contracts, ETF profile/context persistence, research lifecycle persistence (case + run + result + evidence bundle + research-external-evidence link + reverse observation lookup), the Stage 4B market observation snapshot persistence, the Stage 4C stock price-limit revision-aware persistence, the Stage 4D External Integration Workbench persistence (integration.external_workflow_runs / external_artifacts / external_observations + analytics.research_external_evidence), and DC-3 index/ETF exposure repositories under packages/storage/src/invest_storage.
resource: /openwiki/storage/overview.md
tags: [storage, sqlalchemy, repository, unit-of-work, provider-evidence, etf-profile, research-context, research-lifecycle, exposure, market-observations, evidence-bundle, stage4b, stage4c, stock-price-limits, stage4d, external-integration, research-external-evidence, research-run-command, observation-lookup]
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
├── evidence_pack_codec.py  # ORM ↔ EvidencePack projection (read-only research API)
└── unit_of_work.py         # UoW Protocol + SqlAlchemyUnitOfWork + SessionProvider
```

The public surface (`invest_storage.__all__`) groups everything into
three buckets:

- **Models.** `Base`, `InstrumentRow`, `ProviderRequestRow`,
  `ProviderAttemptRow`, `RawProviderBatchRow`, `PipelineRunRow`,
  `DailyBarRow`, `InputSnapshotRow`, `CandidatePoolRunRow`,
  `CandidatePoolItemRow`, `ResearchEvidencePackRow`,
  `EtfProfileRow`, `EtfProfileFieldRow`, `ResearchContextPackRow`,
  `ResearchContextItemRow`, `ResearchCaseRow`, `ResearchRunRow`,
  `ResearchResultRow`, `ResearchEvidenceBundleRow`,
  `MarketObservationSnapshotRow`, `ExposureObservationRow`,
  `ExposureBundleRow`, `IndexIdentityRow`, `EtfIndexMappingRow`,
  `IndexProfileRow`, `IndexConstituentSnapshotRow`,
  `EtfHoldingSnapshotRow`, **`StockPriceLimitRow`** (Stage 4C —
  per-instrument per-trade-date upper / lower price-limit row
  keyed on `(instrument_id, trade_date, revision, row_hash)`, with
  `regime_id` / `status` / `reference_price` / `source_provider` /
  `source_batch_id` / `observed_at` audit columns),
  **`ExternalWorkflowRunRow`** / **`ExternalArtifactRow`** /
  **`ExternalObservationRow`** (Stage 4D —
  `integration.external_workflow_runs` / `external_artifacts` /
  `external_observations` rows that anchor the External Integration
  Workbench),
  **`ResearchExternalEvidenceRow`** (Stage 4D —
  `analytics.research_external_evidence` row that binds an admitted
  external observation to a Research Case, idempotent on
  `(research_case_id, observation_id)`).
- **Repositories and DTOs.** `SqlAlchemy*Repository` classes plus the
  `New*` and `Stored*` dataclasses that shape their inputs and outputs.
  The PR-7 + DC-3 + ADR-0012 persistence slices add
  `SqlAlchemyResearchCaseRepository`,
  `SqlAlchemyResearchRunRepository`,
  `SqlAlchemyResearchResultRepository`,
  `SqlAlchemyExposureObservationRepository`,
  `SqlAlchemyExposureBundleRepository`,
  `SqlAlchemyIndexIdentityRepository`,
  `SqlAlchemyIndexProfileRepository`,
  `SqlAlchemyIndexConstituentSnapshotRepository`,
  `SqlAlchemyEtfIndexMappingRepository`,
  `SqlAlchemyEtfHoldingSnapshotRepository`.
  The Stage 4D External Integration Workbench adds
  `SqlAlchemyExternalWorkflowRunRepository` (`add` /
  `get_by_id` / `list_recent`),
  `SqlAlchemyExternalArtifactRepository` (`add` / `get_by_id` /
  `list_by_run`), `SqlAlchemyExternalObservationRepository` (`add`
  / `get_by_id` / `list_by_run` / `list_by_admission_status` /
  `list_recent` / `save_admission`), and
  `SqlAlchemyResearchExternalEvidenceRepository` (idempotent
  `add(research_case_id, item)` plus `list_by_case`).
- **Unit of Work.** `UnitOfWork` (Protocol), `SqlAlchemyUnitOfWork`
  (impl), `SessionProvider` (Protocol), and the per-collection port
  Protocols (`InstrumentRepositoryPort`, `DailyBarRepositoryPort`,
  `EtfProfileRepositoryPort`, `EtfProfileFieldRepositoryPort`,
  `ResearchContextPackRepositoryPort`,
  `ResearchCaseRepositoryPort`,
  `ResearchRunRepositoryPort`,
  `ResearchResultRepositoryPort`,
  `IndexIdentityRepositoryPort`, …,
  `ExternalWorkflowRunRepositoryPort`,
  `ExternalArtifactRepositoryPort`,
  `ExternalObservationRepositoryPort`,
  `ResearchExternalEvidenceRepositoryPort` — Stage 4D).

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
- `SqlAlchemyResearchCaseRepository`: `add`, `get`,
  `list_by_instrument`, `list_recent`, `count_all`,
  `save_transition` (PR-7 / ADR-0012; persists the `ResearchCase`
  lifecycle and exposes the read-side `list_recent` /
  `count_all` page used by
  [`/api/v1/research-cases`](../api/overview.md#2-routing-surface)).
- `SqlAlchemyResearchRunRepository`: `add`, `get`, `list_by_case`,
  `save_transition`, `bind_external_identity`,
  `lookup_by_external_session_id`, `list_recent`, and `count_all`.
  Status transitions use a compare-and-swap update; external session
  identity is protected by a partial unique index.
- `SqlAlchemyResearchResultRepository`: `add`, `get_by_id`, and
  `get_by_run_id`; the database permits one immutable result per run.
  Migration `20260812_0017_research_result_evidence_bundle_fk` adds
  the nullable `evidence_bundle_id` FK so a successful run can carry
  its Stage 4B bundle identity end-to-end through `research_run →
  research_evidence_bundle → research_result`.
- `SqlAlchemyResearchEvidenceBundleRepository`: `add`, `get_by_id`,
  `get_by_case` (Stage 4B / migration `20260811_0016`; persists the
  `ResearchEvidenceBundle` aggregate and exposes the case-anchored
  read used by the
  `market_breadth_bundle_service.bind_evidence_bundle` application
  service). The bundle is uniquely keyed on
  `(research_case_id, content_hash)` so re-publishing the same
  canonical bundle is idempotent.
- `SqlAlchemyMarketObservationSnapshotRepository`: `add`,
  `get_by_id`, `get_latest_for_scope(scope_type, scope_key, as_of_date=None)`,
  and `get_by_content_hash` (Stage 4B / migration `20260810_0015`;
  persists the Market Observation snapshot family used by both the
  Market Temperature and the Market Breadth read slices).
  `get_latest_for_scope` narrows the lookup to a single
  `(scope_type, scope_key)` pair so the API service can never
  accidentally read a Market Temperature snapshot through the
  breadth route. `get_by_content_hash` is the deterministic lookup
  the Stage 4B Phase 3
  [`research_context_projection.load_context_projection`](../pipeline/overview.md#5h-research-context-projection-loader-adr-0012--stage-4b-phase-3)
  helper uses to resolve each `MarketSnapshotRef.content_hash` in
  a `ResearchEvidenceBundle` to a concrete snapshot row.
- `SqlAlchemyEvidencePackRepository`: bind-side reader used by
  the research router's `/api/v1/research-cases/{case_id}/evidence`
  endpoint (`list_by_case(case_id)`). The persistence path that
  creates `analytics.research_evidence_packs` rows lives on the
  pipeline side and the case-id FK added by migration
  `20260807_0013` makes the case-anchored filter a single indexed
  read.
- `SqlAlchemyStockPriceLimitRepository` (Stage 4C; migration
  `20260812_0018_stock_price_limits`): revision-aware read/write
  access to `core.stock_price_limits`. The repository owns the
  ADR-0006 §3 revision-allocation algorithm: a write only advances
  `revision` when the incoming business content (`row_hash`) differs
  from the latest persisted row for `(instrument_id, trade_date)`;
  re-collects of identical content are no-ops at the core layer.
  Surface: `upsert_many`, `get_latest`, `get_exact`, and
  `list_by_instrument_and_range`. The database-level
  `UNIQUE (instrument_id, trade_date, revision, row_hash)`
  constraint is the final concurrency guard; the repository reads
  the latest revision inside the same UoW so the deterministic
  content comparison runs before the INSERT.
- `SqlAlchemyExposureObservationRepository`,
  `SqlAlchemyExposureBundleRepository`,
  `SqlAlchemyIndexIdentityRepository` (DC-3 / migration
  `20260806_0011_dc3_exposure`): persist CSIndex index constituents
  and AkShare `fund_portfolio_hold_em` ETF holdings. Bundles are
  deduped on `content_hash`; observations on
  `(instrument_id, index_code, as_of_date, provenance.revision)`.
- `SqlAlchemyIndexProfileRepository`,
  `SqlAlchemyIndexConstituentSnapshotRepository`,
  `SqlAlchemyEtfIndexMappingRepository`,
  `SqlAlchemyEtfHoldingSnapshotRepository` (the index-level
  half of the exposure bounded context): the bounded `IndexProfile`
  metadata, the bounded `IndexConstituentSnapshot` per date, the
  date-bounded `EtfIndexMapping`, and the per-ETF
  `EtfHoldingSnapshot` for the reporting period.
- `SqlAlchemyExternalWorkflowRunRepository` (Stage 4D / migration
  `20260814_0019_external_integration`): `add`, `get_by_id`, and
  `list_recent(limit, offset)` (ordered by `started_at` desc with
  `run_id` as the deterministic tiebreaker). The repository is the
  read/write seam for `integration.external_workflow_runs` — every
  row is immutable producer-side metadata (started / finished /
  schema version / status / metadata) and never carries a payload.
- `SqlAlchemyExternalArtifactRepository` (Stage 4D): `add`,
  `get_by_id`, `list_by_run(run_id, limit, offset)` (ordered by
  `created_at` and `artifact_id`). Each row is the size / hash
  / logical URI / media-type ledger for one external artifact;
  the table carries no payload bytes — only a 64-char `content_hash`.
- `SqlAlchemyExternalObservationRepository` (Stage 4D):
  `add`, `get_by_id`, `list_by_run(run_id, limit, offset)`,
  `list_by_admission_status(status, limit, offset)`,
  `list_recent(status=None, limit, offset)` (radar ordering
  by `observed_at` desc, then `observation_id`), and
  `save_admission(observation)` — the only state-machine
  transition the table allows (admission metadata update on
  an existing row). Admission terminal states (`ADMITTED` /
  `REJECTED`) are immutable in the domain layer; the
  repository reads the row before flushing so the
  admission-state audit history is preserved.
- `SqlAlchemyResearchExternalEvidenceRepository` (Stage 4D /
  migration `20260814_0020_research_external_evidence`): the
  write side is idempotent on `(research_case_id, observation_id)`
  through a `UNIQUE` constraint plus the structural `add(case_id,
  item)` lookup. A re-link of an existing pair with the same
  `content_hash` returns the existing row; a divergent
  `content_hash` raises `ValueError` so an existing evidence
  row is never overwritten with a different admission audit
  trail. `list_by_case(case_id)` is the ordered-by-`created_at`
  reader used by future case-workspace surfaces, and the
  `get_by_observation(observation_id)` lookup is the canonical
  reverse lookup the controlled Research Run queue
  (`ResearchRunCommandService.queue` /
  `ExternalResearchHandoffService.queue`) uses to confirm an
  admitted observation is already linked before opening a new
  `ResearchRun` row.
- `InputSnapshotRepository`: `add`, `get_by_date_and_hash`,
  `list_by_date`.

Domain code (and the FastAPI routers) interact with repositories via
this module's surface. Application code that needs to coordinate
multiple repositories uses the `UnitOfWork` instead of taking
individual session handles.

`CandidatePoolRunRow.input_snapshot_id` is a non-null foreign key to
`analytics.input_snapshots.id`, named `fk_cpool_runs_snapshot_id`. The
Alembic [migration](../migrations/overview.md#2-the-twenty-revision-chain)
adds the same constraint, so a persisted candidate-pool run cannot point
at a missing input snapshot. This storage invariant backs the
[Candidate pool input-snapshot binding](../domain/candidate-pool.md#3-input-snapshot-binding)
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

- Owns a single SQLAlchemy `Session` plus twenty-three lazily-built repository
  properties: `instruments`, `input_snapshot_repository`,
  `provider_requests`, `provider_attempts`, `provider_batches`,
  `pipeline_runs`, `candidate_pool_runs`, `candidate_pool_items`,
  `daily_bars`, `etf_profiles`, `etf_profile_fields`,
  `research_context_packs`, `research_cases`, `research_evidence_packs`,
  `research_runs`, `research_results`,
  `research_evidence_bundles` (Stage 4B Phase 3 case-anchored
  bundle reader used by `market_breadth_bundle_service`),
  `market_observation_snapshots` (Stage 4B Phase 2 / 4C observer
  family — used by `market_breadth_service` /
  `limit_sentiment_service`),
  `stock_price_limits` (Stage 4C Phase 1 revision-aware
  repository), `index_identities`,
  `index_profiles`, `index_constituent_snapshots`, `etf_index_mappings`,
  `etf_holding_snapshots`. These are the complete public repository
  properties; the UoW does not expose separate `exposure_*` aliases.
  The Stage 4D slice adds four more lazily-built properties —
  `external_workflow_runs`, `external_artifacts`,
  `external_observations`, and `research_external_evidence` —
  alongside the reset hooks on `rollback()` / exit so the
  external-integration repositories can be reused by the API
  routers through the same context-managed session.
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
| `analytics.research_evidence_packs` | Stage 4A research evidence persistence (migration `20260803_0007`), with the indexed nullable `research_case_id` FK added by migration `20260807_0013`. `SqlAlchemyEvidencePackRepository` is exposed as `uow.research_evidence_packs`. | `/api/v1/research-cases/{case_id}/evidence`. |
| `analytics.research_cases` | Migration `20260807_0012_research_cases`. Stores the case ID, instrument, as-of date, question, horizon, lifecycle status, timestamps, and optional candidate-pool run binding. | `/api/v1/research-cases`, `/api/v1/research-cases/{case_id}`. |
| `analytics.research_runs` / `analytics.research_results` | Migration `20260807_0014_research_runs`. Runs carry case/evidence bindings, runner/playbook keys, attempt, state, timestamps and optional external identities; results are unique by `run_id`. | `/api/v1/research-runs`, `/api/v1/research-runs/{run_id}`, `/api/v1/research-runs/{run_id}/result`. |
| `core.indexes`, `core.index_profiles`, `core.index_constituent_snapshots`, `core.index_constituents`, `core.etf_index_mappings`, `core.etf_holding_snapshots`, `core.etf_holdings` | DC-3 migration `20260806_0011_dc3_exposure`; pipeline exposure services persist index metadata, constituent snapshots, ETF/index mappings and ETF holdings through the matching UoW repositories. | No API surface yet. |
| `core.etf_profiles` | DC-2 `etf_profiles` service (migration `20260804_0008_etf_profiles`). One row per `core.instruments` (instrument_id is both PK and FK), carrying the canonical ETF static metadata (`manager` / `benchmark_index` / `category` / `inception_date` / `fund_type` / `management_fee` / `custody_fee` / `aum` / `shares`). | No API surface yet; the table is the persistence target of `SqlAlchemyEtfProfileRepository.upsert`. |
| `analytics.etf_profile_fields` | PR-ETF-PROFILE-04 `etf_profile_fields` persistence (migration `20260805_0009_etf_profile_fields`). One row per `FieldEvidence` observation, idempotent on `content_hash`, with discriminated `field_value_text` / `field_value_numeric` / `field_value_date` columns plus source provenance and `(instrument_id, field_key)` index. | No API surface yet; the resolver reads through `SqlAlchemyEtfProfileFieldRepository.get_by_instrument_field`. |
| `analytics.research_context_packs` + `analytics.research_context_items` | Stage 4A evidence / context separation (migration `20260805_0010_research_context_packs`). One pack per `(instrument_id, context_version)`; child items carry the per-field `ContextItem` rows built by the pure `build_etf_profile_context_pack` builder. | No API surface yet; the tables are the persistence target of `SqlAlchemyResearchContextPackRepository` plus the child `ResearchContextItemRow` cascade. |
| `core.stock_price_limits` | Stage 4C Phase 1 (migration `20260812_0018_stock_price_limits`). One row per `(instrument_id, trade_date, revision)`; carries the `regime_id` / `limit_up_price` / `limit_down_price` / `status` / `reference_price` plus `source_provider` / `source_batch_id` / `observed_at` audit columns; revision advances only on content-hash change (ADR-0006 §3). FKs to `core.instruments.id` and `raw.provider_batches.id`. | No API surface yet; the table is the persistence target of `SqlAlchemyStockPriceLimitRepository.upsert_many`. |
| `integration.external_workflow_runs` | Stage 4D (migration `20260814_0019_external_integration`). One row per external producer run; immutable producer metadata (`started_at` / `finished_at` / `schema_version` / `producer_status` / `intake_status` / JSONB metadata). No payload bytes. | `apps/pipeline/src/invest_pipeline/integrations/bridge_ingestor.py` (`import_archived_candidate_run`) | `/api/v1/external-workflows`, `/api/v1/integration/health`. |
| `integration.external_artifacts` | Stage 4D. One row per external artifact (`logical_uri` / `content_hash` / `media_type` / `size_bytes` / JSONB metadata). FK to `external_workflow_runs.run_id` plus a `(run_id, logical_uri)` UNIQUE constraint. | Same bridge ingest; no payload bytes stored in the table. | `/api/v1/external-workflows/{run_id}/artifacts`, `/api/v1/integration/artifacts/{artifact_id}` (safe preview only). |
| `integration.external_observations` | Stage 4D. One row per external fact candidate (`payload` JSONB / `symbol` / optional `instrument_id` FK / `admission_status` / `metadata`); FKs to `external_workflow_runs` and `external_artifacts`. No payload bytes outside `payload` JSONB. | Same bridge ingest; admission transitions via the gated `/api/v1/external-observations/{observation_id}/admission-decisions` command. | `/api/v1/external-workflows/{run_id}/observations`, `/api/v1/opportunity-radar`. |
| `analytics.research_external_evidence` | Stage 4D (migration `20260814_0020_research_external_evidence`). One row per admitted external observation bound to a research case; idempotent on `(research_case_id, observation_id)` and globally on `evidence_id`. Carries the canonical `content_hash` / `artifact_content_hash` / `observed_at` / `as_of` / `source_uri` / `producer` / `payload` / `admission` audit metadata. FKs to `analytics.research_cases`, `integration.external_observations`, `integration.external_artifacts`. | `POST /api/v1/research-cases/{case_id}/external-observations/{observation_id}/evidence` (the only writer today). | No API list endpoint yet; future case-workspace surfaces will read through `SqlAlchemyResearchExternalEvidenceRepository.list_by_case`. |
| `ops.pipeline_runs` | Pipeline job wrappers via `SqlAlchemyPipelineRunRepository`. | `/api/v1/pipeline-runs` latest, detail, and paginated history endpoints. |

## 6. Boundary rules enforced from the storage side

- `packages/storage/src` MUST NOT import `fastapi`, `dagster`,
  `akshare`, `vectorbt`, `backtrader` (see
  [Architecture overview §5](../architecture/overview.md#5-architecture-decision-records)).
- The transition guard on `CandidatePoolRun.transition_to` mirrors the
  protocol's legal-transition set; an attempt that violates the guard
  raises `ConcurrentTransitionError` rather than committing.

## 7. Tests

 - **Unit (mock):** [`tests/storage/test_external_integration_repository_mock.py`](../../tests/storage/test_external_integration_repository_mock.py)
  exercise every repository against a `MagicMock` session.
- **Integration (Testcontainers):**
  [`tests/storage/`](../../tests/storage/INCREMENT3-RESULTS.md)
  spins up a disposable PostgreSQL container, runs migrations, and
  exercises the same repositories end-to-end. CI runs them under the
  `storage-integration` job. The session-level conftest
  ([`tests/storage/integration/conftest.py`](../../tests/storage/integration/conftest.py))
  declares the full six-schema set (`raw` / `core` / `ops` / `app` /
  `analytics` / `integration`) in its `_create_schemas_and_tables`
  autouse fixture and the matching `app` / `analytics` /
  `integration` truncations in `_truncate_between_tests`, so the
  Stage 4D `integration.*` repositories resolve their ORM tables
  through `Base.metadata.create_all` without manual migration
  preflight.
