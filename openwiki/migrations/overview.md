---
type: Concept
title: Migrations overview
description: How apps/migrations owns the PostgreSQL schema as an independent Alembic app, the six-revision chain under apps/migrations/migrations/versions, and the schema-ownership rules across raw/core/analytics/ops.
resource: /openwiki/migrations/overview.md
tags: [migrations, alembic, postgres, schemas]
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
        └── 20260803_0007_research_evidence_packs.py
```

The shell entry-point is `cd apps/migrations && uv run alembic ...`,
which `make migrate` aliases.

## 2. The seven-revision chain

Every revision declares its own `revision`, `down_revision` and a
single `upgrade()` / `downgrade()` pair. The chain currently ends at
`20260803_0007_research_evidence_packs.py` and is verified by an AST-based
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

Older `20260730_0001..0004` revisions are no longer in the chain —
they were retired when the migrations moved to `apps/migrations/`.

## 3. Schema ownership

| Schema | Tables owned by | Pipeline writes via | API reads via |
|--------|----------------|---------------------|---------------|
| `raw` | Pipeline adapters + application service | `apps/pipeline/src/invest_pipeline/{etf_instruments,etf_daily_bars}.py` through `SqlAlchemyUnitOfWork` | — (read-only by API not currently surfaced). |
| `core` | Pipeline; normalised row shapes exposed to API | `etf_instruments` / `etf_daily_bars` assets | `SqlAlchemyInstrumentRepository`, `SqlAlchemyDailyBarRepository`. |
| `analytics` | Pipeline (input snapshots) + Application (candidate pool) | `etf_input_snapshot` asset; future candidate-pool assets | `InputSnapshotRepository`, `SqlAlchemyCandidatePoolRunRepository`, `SqlAlchemyCandidatePoolItemRepository`. |
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
  constraint.
