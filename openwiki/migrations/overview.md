---
type: Concept
title: Migrations overview
description: How apps/migrations owns the PostgreSQL schema as an independent Alembic app, the fourteen-revision chain under apps/migrations/migrations/versions (baseline + provider evidence + candidate pool + daily bars + input snapshots + DC-2 etf_profiles + PR-ETF-PROFILE-04 etf_profile_fields + Stage 4A research_context_packs + DC-3 exposure + research_cases + evidence-pack case FK + research_runs/results), and the schema-ownership rules across raw/core/analytics/ops.
resource: /openwiki/migrations/overview.md
tags: [migrations, alembic, postgres, schemas, etf-profile, research-context, exposure, research-lifecycle]
---

# Migrations overview

`apps/migrations/` is a **standalone Alembic application** that owns the
`raw` / `core` / `analytics` / `ops` PostgreSQL schemas. It was split
out of `apps/api` in PR-01 (`5866b03`) precisely so that the API
runtime image no longer needs alembic, the migrations directories, or
the migration job entry-point.

## 1. Layout

```
apps/migrations/
├── pyproject.toml          # uv-managed "invest-migrations" project
├── uv.lock
├── alembic.ini             # points at migrations/env.py
└── migrations/
    ├── env.py              # offline/online migration runner
    ├── script.py.mako
    └── versions/
        ├── 20260731_0001_v2_baseline.py
        ├── 20260731_0002_provider_three_layer.py
        ├── 20260731_0003_candidate_pool_tables.py
        ├── 20260731_0004_daily_bars_and_revision.py
        ├── 20260731_0005_input_snapshots.py
        ├── 20260731_0006_candidate_pool_snapshot_fk.py
        ├── 20260803_0007_research_evidence_packs.py
        ├── 20260804_0008_etf_profiles.py
        ├── 20260805_0009_etf_profile_fields.py
        ├── 20260805_0010_research_context_packs.py
        ├── 20260806_0011_dc3_exposure.py
        ├── 20260807_0012_research_cases.py
        ├── 20260807_0013_research_evidence_packs_case_fk.py
        └── 20260807_0014_research_runs.py
```

The shell entry-point is `cd apps/migrations && uv run alembic ...`,
which `make migrate` aliases.

## 2. The fourteen-revision chain

Every revision declares its own `revision`, `down_revision` and a
single `upgrade()` / `downgrade()` pair. The chain currently ends at
`20260807_0014_research_runs.py` and is verified by an AST-based
gate — see [Testing & operations](../testing-and-ops/overview.md#migration-chain-ast-gate).

| Revision | Purpose | Key additions |
|----------|---------|---------------|
| `20260731_0001_v2_baseline` | Reset / initialise the four schemas. Creates `raw.provider_*`, `core.instruments`, `ops.pipeline_runs`. | Every CREATE SCHEMA call for `raw`, `core`, `analytics`, `ops`; the canonical `instruments`, `provider_batches` and `pipeline_runs` tables. The `app` schema is no longer referenced. |
| `20260731_0002_provider_three_layer` | The PR-02 evidence bundle. | Adds `provider_requests`, `provider_attempts`, `provider_batches` in `raw` with their CHECK constraints, FK chain and natural unique key. |
| `20260731_0003_candidate_pool_tables` | The PR-03 candidate pool persistence. | Creates `analytics.candidate_pool_runs`, `analytics.candidate_pool_items`, plus the `(trade_date, algorithm_key, algorithm_version, parameter_hash, input_snapshot_id)` business uniqueness and the `CandidatePoolStatus` CHECK. |
| `20260731_0004_daily_bars_and_revision` | The PR-06 daily-bars table and revision view. | `core.daily_bars` with the `(instrument_id, trade_date, adjustment, revision)` composite PK and per-row invariants; `core.latest_daily_bars` view as the read-only latest-per-day surface. |
| `20260731_0005_input_snapshots` | The PR-07 input snapshot header. | `analytics.input_snapshots` (uuid PK, `(snapshot_date, content_hash)` unique key, jsonb membership list, length-64 content-hash CHECK). |
| `20260731_0006_candidate_pool_snapshot_fk` | Bind candidate-pool runs to their input snapshots. | Adds `fk_cpool_runs_snapshot_id` from `analytics.candidate_pool_runs.input_snapshot_id` to `analytics.input_snapshots.id`; downgrade drops the constraint. |
| `20260803_0007_research_evidence_packs` | Stage 4A research evidence persistence. | Creates `analytics.research_evidence_packs` (uuid PK, `instrument_id` FK, `input_snapshot_id` and `candidate_pool_run_id` nullable FKs, `schema_version` / `factor_set_key` / `factor_set_version` / `freshness_status` / `quality_status` / length-64 `content_hash` / JSONB `payload`, plus a five-column `uq_research_evidence_packs_natural_key` unique constraint and two indexes on `(instrument_id, as_of_date)` and `content_hash`). |
| `20260804_0008_etf_profiles` | DC-2 ETF Profile collection slice. | Creates `core.etf_profiles` (uuid PK `instrument_id` equal to the `core.instruments.id` FK, plus the nine nullable static fields `manager` / `benchmark_index` / `category` / `inception_date` / `fund_type` / `management_fee` / `custody_fee` / `aum` / `shares` and the `created_at` / `updated_at` audit timestamps). The CHECK constraints mirror the domain contract — non-empty textual fields, `management_fee` / `custody_fee` in `[0, 1)`, strictly positive AUM / shares — and three indexes cover the dashboard read paths on `manager` / `category` / `fund_type`. |
| `20260805_0009_etf_profile_fields` | PR-ETF-PROFILE-04 storage slice. | Creates `analytics.etf_profile_fields` (uuid PK, `instrument_id` FK, `field_key` / `value_type` / source provenance columns, three discriminated value columns `field_value_text` / `field_value_numeric` / `field_value_date`, `confidence_score` in `[0, 1]`, `observed_at` timezone-aware timestamp, the unique `content_hash` index plus the three lookup indexes on `(instrument_id, field_key)` / `(instrument_id)` / `(source_provider)`). The natural idempotency key is `content_hash`; a different provider / revision produces a different `content_hash` and is stored as a coexisting row so the resolver can read every observation of one field. |
| `20260805_0010_research_context_packs` | Stage 4A evidence / context separation (context layer). | Creates `analytics.research_context_packs` (uuid PK, `instrument_id` FK, `schema_version` / `context_version` / length-64 `content_hash` / optional `missing_reason` / `created_at`, with the unique `content_hash` index plus two indexes on `(instrument_id, context_version)` and `(instrument_id, created_at)`) **and** the child `analytics.research_context_items` (uuid PK, `pack_id` cascade-FK, `context_type` / `key` / `value_type` / JSONB `value` / source provenance columns, `observed_at`, `quality_status`, `confidence_score` in `[0, 1]`, JSONB `evidence_refs`, length-64 `item_hash`; the `value_type IN ('text','decimal','date','json')` CHECK and the `(pack_id, item_hash)` unique constraint anchor the per-item hash stability). |
| `20260806_0011_dc3_exposure` | DC-3 index-exposure persistence. | Creates the `core.indexes`, `core.index_profiles`, `core.index_constituent_snapshots`, `core.index_constituents`, `core.etf_index_mappings`, `core.etf_holding_snapshots`, and `core.etf_holdings` tables. Their named foreign keys, natural-key/content-hash uniqueness rules, provenance fields, and child-row cascade constraints preserve index and ETF exposure history. |
| `20260807_0012_research_cases` | Research lifecycle persistence (case header). | Creates `analytics.research_cases` with non-null `instrument_id`, optional `candidate_pool_run_id`, `as_of_date`, `question`, `horizon`, six-value lowercase status, and `created_at` / `closed_at`. CHECK constraints enforce non-blank text and terminal-status/`closed_at` consistency; indexes cover `(instrument_id, as_of_date)` and `status`. |
| `20260807_0013_research_evidence_packs_case_fk` | Bind research evidence packs to their case. | Adds nullable `research_case_id`, its FK to `analytics.research_cases.case_id`, and an index on the new column. It also adds a global unique constraint on `content_hash`. |
| `20260807_0014_research_runs` | Research-run and result persistence. | Creates `analytics.research_runs` with five lowercase statuses (`queued`, `running`, `succeeded`, `failed`, `cancelled`), external request/session identity fields, and a partial unique index on non-null `external_session_id`. Creates `analytics.research_results` with one-result-per-run uniqueness, evidence-pack FK, JSONB risks/evidence IDs, version provenance, and payload CHECK constraints. |

Older `20260730_0001..0004` revisions are no longer in the chain —
they were retired when the migrations moved to `apps/migrations/`.

## 3. Schema ownership

| Schema | Tables owned by | Pipeline writes via | API reads via |
|--------|----------------|---------------------|---------------|
| `raw` | Pipeline adapters + application service | `apps/pipeline/src/invest_pipeline/{etf_instruments,etf_daily_bars}.py` through `SqlAlchemyUnitOfWork` | — (read-only by API not currently surfaced). |
| `core` | Pipeline; normalised row shapes exposed to API | `etf_instruments` / `etf_daily_bars` assets; `etf_profiles` service for the DC-2 static ETF metadata (1-1 with `core.instruments`) | `SqlAlchemyInstrumentRepository`, `SqlAlchemyDailyBarRepository`, `SqlAlchemyEtfProfileRepository`. |
| `analytics` | Pipeline (input snapshots) + Application (candidate pool) + Research context | `etf_input_snapshot` asset; candidate-pool assets; `etf_profile_context` / `etf_profiles` service; `research_orchestration_service.execute` for case / run / result lifecycle | `InputSnapshotRepository`, `SqlAlchemyCandidatePoolRunRepository`, `SqlAlchemyCandidatePoolItemRepository`, `SqlAlchemyEtfProfileFieldRepository`, `SqlAlchemyResearchContextPackRepository`, `SqlAlchemyResearchCaseRepository`, `SqlAlchemyResearchRunRepository`, `SqlAlchemyResearchResultRepository`, `SqlAlchemyEvidencePackRepository`. |
| `ops` | Pipeline | `ops.pipeline_runs` writes via `SqlAlchemyPipelineRunRepository` | Personal-job history and latest status via the read-only `/api/v1/pipeline-runs` endpoints. |

## 4. Composability rules

- Every revision's `upgrade()` must be reversible via a matching
  `downgrade()`. The `test-migrations` Make target (and CI job
  `migrations`) round-trips `alembic upgrade head` → `alembic
  downgrade base` → `alembic upgrade head` against a disposable
  PostgreSQL container.
- New tables added by future revisions must live under one of the four
  schemas. The `app` schema is forbidden by `scripts/check_architecture.py`
  (AST scan for `schema="app"`).
- Revision IDs follow `YYYYMMDD_NNNN`; the initial revision `20260731_0001`
  is required (the AST gate fails when the initial revision is missing).
- A single migration never spans multiple schemas unless the cross-schema
  relationship is unavoidable (rare).
- The JSONB membership list on `analytics.input_snapshots` is kept in
  the same lexicographic byte order used to compute `content_hash`
  (see [Candidate pool](../domain/candidate-pool.md#input-snapshot-binding)).

## 5. PR-09 / current diff touches

- `tests/test_migration_chain.py` targets
  `apps/migrations/migrations/versions` and uses a `_try_literal_eval` helper
  to dodge `ast.literal_eval` exceptions for non-literal nodes.
- `tests/test_increment2_migrations_ast.py` was deleted because the
  superseding chain gate above is the canonical check going forward.
- `tests/test_migration_chain.py` also asserts that revision `20260731_0006`
  references `candidate_pool_runs`, `input_snapshots`, and
  `fk_cpool_runs_snapshot_id`, and that revision `20260803_0007`
  creates the `research_evidence_packs` table with its three
  foreign keys (`fk_research_packs_instrument` /
  `fk_research_packs_snapshot` /
  `fk_research_packs_candidate_run`), the two CHECK constraints
  (`ck_research_evidence_packs_content_hash_len64` /
  `ck_research_evidence_packs_payload_object`), and the
  five-column `uq_research_evidence_packs_natural_key` unique
  constraint. The DC-2 / PR-ETF-PROFILE-04 / research-context /
  DC-3 / research-lifecycle slices add seven further revisions
  (`20260804_0008` / `20260805_0009` / `20260805_0010` /
  `20260806_0011` / `20260807_0012` / `20260807_0013` /
  `20260807_0014`); the chain gate now expects a single head at
  `20260807_0014` and the test suite still round-trips
  `upgrade head → downgrade base → upgrade head` end-to-end so the
  full fourteen-revision chain is exercised. Revision
  `20260807_0013` adds the indexed `research_case_id` FK and global
  `content_hash` uniqueness used by the read-only research API;
  revision `20260807_0014` adds the run/result tables and the
  external-session and one-result-per-run uniqueness guards.
