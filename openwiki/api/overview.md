---
type: Concept
title: API overview
description: FastAPI routers, Pydantic response shapes and the read-only endpoint surface added by PR-09 (GET /api/v1/etf/*, GET /api/v1/candidate-pool/latest) plus the legacy /v1/instruments endpoint.
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
mounts the legacy router and the two PR-09 routers and configures
CORS via `Settings.cors_origins`.

## 1. Modules

```
apps/api/src/invest_api/
├── main.py                # FastAPI app + middleware + router mount
├── routes.py              # legacy /health + /v1/instruments
├── dependencies.py        # get_db_session, get_engine, get_session_factory
├── config.py              # pydantic-settings Settings
├── routers/
│   ├── etf.py             # PR-09 read-only ETF endpoints
│   └── candidate_pool.py  # PR-09 read-only candidate pool endpoint
└── schemas/
    ├── __init__.py        # re-exports ETF + candidate pool shapes
    ├── common.py          # legacy HealthResponse + re-exports
    ├── etf.py             # InstrumentResponse / DailyBarResponse + paginated lists
    └── candidate_pool.py  # CandidatePoolLatestResponse + per-item shapes
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
| `GET /api/v1/candidate-pool/latest` | `routers/candidate_pool.py` | The most recently `published` candidate-pool run plus its `InputSnapshot.content_hash`. |

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
  `exclusion_reasons`).
- `CandidatePoolLatestResponse` (`snapshot_date`, `row_count`,
  `content_hash`, `items`) — the response envelope for the
  `/api/v1/candidate-pool/latest` endpoint; `row_count` is the
  input-snapshot row count mirrored from `input_row_count`.

### `schemas/common.py`

`HealthResponse` is the only shape defined here. The file's other
exports (`InstrumentResponse`, `InstrumentListResponse`) are re-exports
from `schemas/etf.py` so the pre-PR-09 callers can keep
`from invest_api.schemas import HealthResponse, InstrumentResponse`
working.

### `schemas/__init__.py`

Re-exports the ETF and candidate-pool shapes **and** the legacy
`InstrumentResponse` / `InstrumentListResponse` aliases as
`LegacyInstrumentResponse` / `LegacyInstrumentListResponse` so
pre-PR-09 callers can import the legacy names directly
(`from invest_api.schemas import LegacyInstrumentResponse,
DailyBarResponse, CandidatePoolLatestResponse`). The aliases point at
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
- Returns `CandidatePoolLatestResponse(snapshot_date, row_count,
  content_hash, items)`.

## 5. Configuration

`invest_api.config.Settings` (pydantic-settings, `extra="ignore"`):

- `app_name` (default `"invest-infra-v2"`).
- `environment` (default `"development"`).
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
