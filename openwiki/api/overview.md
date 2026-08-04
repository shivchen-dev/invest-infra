---
type: Concept
title: API overview
description: FastAPI routers, Pydantic response shapes and the read-only endpoint surface for ETF data, candidate-pool results and diffs, personal pipeline-run status and paginated history, and data freshness, including the legacy /v1/instruments endpoint.
resource: /openwiki/api/overview.md
tags: [api, fastapi, routers, pydantic, etf, candidate-pool]
---

# API overview

`apps/api/src/invest_api/` ships a read-only HTTP surface for the
canonical business objects. The container is FastAPI, depends only on
`packages/domain` and `packages/storage`, and runs with CORS open to
the local Vite dev server. **It carries no Provider SDKs, no
backtesting libraries and no Notebook dependency** — see
[Architecture overview §5](../architecture/overview.md#5-architecture-decision-records).

The application entry-point is
[`invest_api.main.app`](../../apps/api/src/invest_api/main.py); it
mounts the legacy, ETF, candidate-pool, pipeline-run and data-freshness
routers and configures CORS via `Settings.cors_origins`.

## 1. Modules

```
apps/api/src/invest_api/
├── main.py                # FastAPI app + middleware + router mount
├── routes.py              # legacy /health + /v1/instruments
├── dependencies.py        # get_db_session, get_engine, get_session_factory
├── config.py              # pydantic-settings Settings
├── routers/
│   ├── etf.py             # PR-09 read-only ETF endpoints
│   ├── candidate_pool.py  # candidate-pool latest + diff endpoints
│   ├── pipeline_runs.py   # personal daily pipeline-run status + history
│   └── data_freshness.py  # personal daily data-freshness summary
└── schemas/
    ├── __init__.py        # re-exports all public response shapes
    ├── common.py          # legacy HealthResponse + re-exports
    ├── etf.py             # InstrumentResponse / DailyBarResponse + paginated lists
    ├── candidate_pool.py  # latest, item and diff shapes
    ├── pipeline_runs.py   # PipelineRunResponse + PipelineRunListResponse
    └── data_freshness.py  # DataFreshnessResponse + status vocabulary
```

`apps/api/tests/` holds mock-based contract tests for every router
(see [Testing & operations §API tests](../testing-and-ops/overview.md#api-tests)).

## 2. Routing surface

| Verb + path | Source | Purpose |
|-------------|--------|---------|
| `GET /health` | [`routes.py`](../../apps/api/src/invest_api/routes.py) | Liveness probe; returns `{status, service}`. |
| `GET /v1/instruments` | `routes.py` | Legacy sparse instrument list (`limit/offset` only, response uses `response_model_exclude` to keep the historically contracted fields). |
| `GET /api/v1/etf/instruments` | `routers/etf.py` | Active ETF instruments with optional `exchange` and `status` filters, paginated with `limit/offset`. |
| `GET /api/v1/etf/daily-bars` | `routers/etf.py` | Daily-bars range query — collapses to the latest revision per `trade_date` (ADR-0006 §6). |
| `GET /api/v1/candidate-pool/latest` | `routers/candidate_pool.py` | The most recently `published` candidate-pool run with run metadata, snapshot audit data, item display fields, and its `InputSnapshot.content_hash`. |
| `GET /api/v1/candidate-pool/latest/diff` | `routers/candidate_pool.py` | Added, retained and removed included-candidate entries for the latest published run versus the most recent earlier published run. |
| `GET /api/v1/candidate-pool/{run_id}/diff` | `routers/candidate_pool.py` | The same included-candidate diff for a specified published run; missing or non-published runs return 404. |
| `GET /api/v1/pipeline-runs` | `routers/pipeline_runs.py` | Paginated history scoped to the `personal_etf_daily_job` job key (default `limit=20`, maximum 100). |
| `GET /api/v1/pipeline-runs/latest` | `routers/pipeline_runs.py` | Most recent run scoped to the `personal_etf_daily_job` job key. |
| `GET /api/v1/pipeline-runs/{run_id}` | `routers/pipeline_runs.py` | One personal daily pipeline run; missing or other-job IDs return 404. |
| `GET /api/v1/data-freshness` | `routers/data_freshness.py` | Counts and status summary for the expected trade date, defaulting to the latest weekday. |

All endpoints accept the `get_db_session` FastAPI dependency; tests
override it with a `MagicMock` `Session` and patch the relevant
`SqlAlchemy*Repository` constructors per-router.

## 3. Pydantic schemas

### `schemas/etf.py`

- `InstrumentResponse` (full shape) — built via
  `InstrumentResponse.from_instrument(Instrument)`; carries `id`,
  `symbol`, `name`, `exchange`, `instrument_type`, `currency`,
  `status`, `is_active`, `list_date`, `delist_date`,
  `underlying_index`, `category`.
- `InstrumentListResponse` — paginated envelope used by
  `/api/v1/etf/instruments`.
- `DailyBarResponse` — one standardised OHLCV row: `instrument_id`,
  `trade_date`, `open`/`high`/`low`/`close`/`prev_close`,
  `volume`/`amount`, `adjustment`, `trading_status`,
  `source_provider`, `source_batch_id`, `observed_at`, `revision`.
- `DailyBarListResponse` — paginated envelope used by
  `/api/v1/etf/daily-bars`.

### `schemas/candidate_pool.py`

- `RuleOutcomeResponse` (`rule_key`, `passed`, `severity`,
  optional `value`, `threshold`, `message`) mirrors
  `invest_domain.candidate_pool.models.RuleOutcome`.
- `ExclusionReasonResponse` (`code`, `message`) mirrors
  `ExclusionReason`.
- `CandidatePoolItemResponse` (`instrument_id`, `included`, optional
  `rank` / `total_score`, `metrics`, `rule_results`,
  `exclusion_reasons`, plus optional `symbol`, `name`, `exchange`). Missing
  instrument rows degrade those display fields to `None`.
- `CandidatePoolLatestResponse` (`run_id`, `trade_date`, `algorithm_key`,
  `algorithm_version`, `parameter_set_key`, `snapshot_id`, `content_hash`,
  `row_count`, `included_count`, `excluded_count`, optional `published_at`,
  and `items`) is the response envelope for
  `/api/v1/candidate-pool/latest`; `row_count` mirrors the input snapshot's
  `input_row_count`.
- `CandidatePoolDiffEntry` carries an `instrument_id` plus optional display
  fields. `CandidatePoolDiffResponse` (`trade_date`, optional
  `previous_trade_date`, `added`, `retained`, `removed`) contains lists of
  these entries for included-candidate membership changes, not UUID-only
  lists or excluded input items.

### `schemas/pipeline_runs.py`

`PipelineRunResponse` exposes the public subset of an `ops.pipeline_runs`
row: `id`, `job_key`, `partition_key`, `trigger_type`, `status`, optional
`started_at` / `finished_at`, and `error_summary`. `error_code` is part of
the contract but remains `None` until the storage layer persists a separate
structured code. The router only returns the hard-coded
`personal_etf_daily_job` scope.

`PipelineRunListResponse` wraps a page of those rows with `items`,
`total`, `limit`, and `offset`; history is ordered by `started_at` descending
with `id` as a deterministic tiebreaker. The storage layer provides the
job-key-filtered page and exact count documented in the
[Storage overview](../storage/overview.md#repositories-repositoriespy).

### `schemas/data_freshness.py`

`DataFreshnessResponse` reports `as_of`, the latest published trade date,
`universe_count`, `daily_bar_count`, non-negative `missing_count`,
`candidate_count`, optional snapshot/run IDs and pipeline status, plus the
`DataFreshnessStatus` literal: `fresh`, `partial`, `stale`, `missing`, or
`failed`.

### `schemas/common.py`

`HealthResponse` is the only shape defined here. The file's other
exports (`InstrumentResponse`, `InstrumentListResponse`) are re-exports
from `schemas/etf.py` so the pre-PR-09 callers can keep
`from invest_api.schemas import HealthResponse, InstrumentResponse`
working.

### `schemas/__init__.py`

Re-exports the ETF, candidate-pool, pipeline-run and data-freshness shapes **and** the legacy
`InstrumentResponse` / `InstrumentListResponse` aliases as
`LegacyInstrumentResponse` / `LegacyInstrumentListResponse` so
pre-PR-09 callers can import the legacy names directly
(`from invest_api.schemas import LegacyInstrumentResponse,
DailyBarResponse, CandidatePoolLatestResponse, CandidatePoolDiffEntry,
PipelineRunListResponse, PipelineRunResponse`). The aliases point at
the same Pydantic classes that [`schemas/common.py`](#schemascommonpy)
re-exports from `schemas/etf.py`, so the public surface is one
definition with two names. Test code uses this surface
(see [Testing & operations](../testing-and-ops/overview.md#api-tests)).

## 4. Endpoint contracts

### `GET /api/v1/etf/instruments`

- Query: `limit` (1..1000, default 100), `offset` (≥0, default 0),
  `exchange` (optional, 1..32 chars), `status` (optional, 1..24 chars,
  query alias for the `status_` parameter so the keyword doesn't shadow
  Python's built-in).
- Calls `SqlAlchemyInstrumentRepository.list_active(limit=1000)`, applies
  optional `exchange` / `status_` filters in Python, then paginates.
- Returns `InstrumentListResponse(items, total, limit, offset)`.

### `GET /api/v1/etf/daily-bars`

- Query: `instrument_id` (UUID, required), `start_date` /
  `end_date` (ISO dates, required), `limit` (1..1000, default 100),
  `offset` (≥0, default 0).
- Validates `end_date >= start_date` (400 otherwise) and
  `SqlAlchemyInstrumentRepository.get_by_id` (404 otherwise).
- Calls `SqlAlchemyDailyBarRepository.list_by_instrument_and_range`
  with `adjustment=Adjust.NONE`, then collapses the revision list to the
  highest revision per `trade_date` (ADR-0006 §6).
- Returns `DailyBarListResponse(items, total, limit, offset)`.

### `GET /api/v1/candidate-pool/latest`

- No query string.
- `SqlAlchemyCandidatePoolRunRepository.list_by_status(PUBLISHED, 1)` →
  404 if no published run.
- Resolves the matching `InputSnapshot` through
  `InputSnapshotRepository.list_by_date(trade_date)`; a missing
  snapshot for the run's `input_snapshot_id` raises 500 (data integrity
  violation).
- Resolves display fields for each item through
  `SqlAlchemyInstrumentRepository.get_many_by_ids`; missing instrument rows
  leave `symbol`, `name`, and `exchange` as `None` rather than failing the
  endpoint.
- Returns `CandidatePoolLatestResponse(run_id, trade_date, algorithm_key,
  algorithm_version, parameter_set_key, snapshot_id, content_hash,
  row_count, included_count, excluded_count, published_at, items)`.

### `GET /api/v1/candidate-pool/latest/diff`

- No query string. Resolves the latest `PUBLISHED` run and compares the set
  of `included=True` instrument IDs with the most recent earlier published
  run; excluded input items never participate.
- Returns `CandidatePoolDiffEntry` rows sorted by `symbol` and then
  `instrument_id` in the `added`, `retained`, and `removed` buckets, plus
  `trade_date` and optional `previous_trade_date`. Each entry includes
  optional `symbol`, `name`, and `exchange` display fields.
- Returns 404 when no published run exists. If there is no predecessor, the
  response is 200 with every included current instrument in `added` and the
  other two lists empty. The predecessor search is bounded to the latest 100
  published runs.

### `GET /api/v1/candidate-pool/{run_id}/diff`

- `run_id` is a UUID path parameter. A missing or non-`PUBLISHED` run returns
  404, while malformed UUID input is rejected by FastAPI with 422.
- Otherwise it uses the same included-only `CandidatePoolDiffEntry` contract
  and predecessor bound as `/latest/diff`; the endpoint is read-only.

### `GET /api/v1/pipeline-runs`

- Query: `limit` (1..100, default 20) and `offset` (≥0, default 0).
- The repository applies the `job_key="personal_etf_daily_job"` filter in
  SQL through `list_by_job_key`; `count_by_job_key` supplies the exact
  unbounded `total`. Items are ordered by `started_at` descending and then
  `id` ascending for stable pagination.
- Returns `PipelineRunListResponse(items, total, limit, offset)`. SQLAlchemy
  failures become a sanitized 500 with detail `Pipeline runs query failed`.

### `GET /api/v1/pipeline-runs/latest` and `/{run_id}`

- Both routes are hard-coded to `job_key="personal_etf_daily_job"`.
- `/latest` scans the 100 most recent stored runs and returns the first
  matching job; `/` returns the matching UUID only. Missing runs and UUIDs
  belonging to another job are intentionally indistinguishable 404s; malformed
  UUIDs are 422.
- `PipelineRunResponse.error_code` is currently always `null`; the storage
  layer persists the human-readable `error_summary` but not a separate code.

### `GET /api/v1/data-freshness`

- Optional `expected_trade_date` is an ISO date; when omitted, the handler
  reads the market clock via `invest_api.clock.market_today()`
  (`Asia/Shanghai`, single source of truth — see
  [`invest_api/clock.py`](../../apps/api/src/invest_api/clock.py)) and
  snaps the result back to Friday on weekends. The response
  combines personal-universe snapshot (or published-run fallback), daily-bar,
  published-candidate, input-snapshot and personal-job audit counts/IDs.
- The daily-bar and missing counts are scoped to the expected-date snapshot's
  `instrument_ids`; without that snapshot, the handler uses the latest
  published run's candidate-pool membership. `universe_count` comes from the
  snapshot `row_count`, or the published run's `input_row_count` fallback.
- `status` precedence is `failed` (failed pipeline and no publication for the
  expected date), `missing` (no publication ever), `stale` (latest publication
  before expected), `partial` (expected publication but fewer bars than the
  personal universe), then `fresh` (expected publication and complete scoped
  bar coverage).
  A failed pipeline is therefore not surfaced as `failed` when an expected-date
  publication already exists.
- SQLAlchemy errors become a sanitized 500 response with detail
  `Data freshness query failed`; database/driver details are not exposed.

## 5. Configuration

`invest_api.config.Settings` (pydantic-settings, `extra="ignore"`):

- `app_name` (default `"invest-infra-v2"`).
- `database_url` (default points at `postgres:5432/invest`).
- `api_cors_origins` (default `"http://localhost:5173"`), parsed into
  `Settings.cors_origins: list[str]`.

The CORS middleware allows every standard verb plus OPTIONS, with
credentials enabled and `*` headers.

## 6. Legacy `/v1/instruments` shape

The legacy `InstrumentResponse` defined in `schemas/common.py` (a
short 5-field shape) was retired: `common.py` now re-exports the
richer ETF `InstrumentResponse`. The `/v1/instruments` endpoint keeps
returning the historically-contracted fields via FastAPI's
`response_model_exclude` (drops `total`, `id`, `currency`, `status`,
`list_date`, `delist_date`, `underlying_index`, `category`).

The router resolves instruments through the same
`SqlAlchemyInstrumentRepository` as `/api/v1/etf/instruments`, then
runs them through the unified `InstrumentResponse.from_instrument`
factory — there is a single construction path for `Instrument`
domain objects across both endpoints.
