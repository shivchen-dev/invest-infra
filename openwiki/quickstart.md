---
type: Reference
title: OpenWiki Quickstart
description: Entry point for the invest-infra OpenWiki knowledge base. Describes the modular-monolith layout, links every major concept page, and summarizes how to run, migrate, test, and inspect the codebase.
resource: /openwiki/quickstart.md
tags: [quickstart, navigation, invest-infra]
---

# OpenWiki quickstart — invest-infra v2

`invest-infra` is the greenfield v2 backbone for an investment-research
system. It deliberately starts as a **modular monolith** built around
PostgreSQL and shared pure-Python domain packages, with all access mediated
through the FastAPI API or the Dagster pipeline. This wiki describes the
PR-01 through PR-09 baseline plus the working-copy provider and platform
additions documented below.

## 1. High-level layout

The repository is split into independent Python projects, each with its
own `pyproject.toml`; the application projects maintain their own
`uv.lock` files:

| Path | Role |
|------|------|
| `apps/api` | FastAPI read-only API; depends on `domain` + `storage` only. |
| `apps/pipeline` | Dagster assets that drive Provider adapters and ETL; depends on `domain` + `storage` and may import data-science libs. |
| `apps/migrations` | Standalone Alembic app that owns the PostgreSQL schema (the FastAPI container no longer ships `alembic`). |
| `apps/web` | Thin TypeScript / Vite dashboard that consumes the OpenAPI surface. |
| `packages/domain` | Pure domain models, value objects, ports — SQLAlchemy- and FastAPI-free. |
| `packages/storage` | SQLAlchemy 2 ORM models, repositories, `UnitOfWork`, and the `SessionProvider` protocol. |
| `scripts/check_architecture.py` | Custom AST-based boundary checker. |
| `docs/adr/0001..0010` | Accepted architecture decisions; ADR-0011 is the proposed CifangQuant increment (see [Architecture overview](architecture/overview.md)). |

The runtime topology is defined by [`/compose.yaml`](../compose.yaml):

```
React Web ──HTTP/OpenAPI──> FastAPI API ──SQL──> PostgreSQL
                                      ↑
Dagster Pipeline ───────────────SQL───┘
```

The API and Pipeline can share the `domain` and `storage` packages but
have independent `pyproject.toml` / lockfiles / Docker images / lifecycle.

## 2. Where to start

Read these pages in order:

1. [Architecture overview](architecture/overview.md) — modular monolith
   layers, four PostgreSQL schemas, layered rules and ADR index.
2. [Migrations overview](migrations/overview.md) — how
   `apps/migrations` owns the schema and the 5-revision chain.
3. [Domain overview](domain/overview.md) — bounded contexts and the
   canonical hashing scheme.
4. [Candidate pool](domain/candidate-pool.md) — the pure-function
   calculator and the state machine that governs one calculation.
5. [Storage overview](storage/overview.md) — repositories, the
   `UnitOfWork` and the three-layer Provider evidence model.
6. [API overview](api/overview.md) — FastAPI routers (legacy + PR-09 ETF
   + PR-09 candidate pool), Pydantic response shapes.
7. [Pipeline overview](pipeline/overview.md) — Dagster `Definitions`,
   the `etf_*` assets, adapter boundaries, and the declarative provider
   catalog.
8. [Testing & operations](testing-and-ops/overview.md) — CI jobs, the
   migration-chain AST gate, mock vs integration tests,
   `compose.yaml`, the OpenWiki auto-update workflow.

## 3. Running locally

Pre-requisites: Docker, Docker Compose.

```bash
cp .env.example .env
docker compose up --build
```

Then visit:

- Web — `http://localhost:5173`
- API docs (Swagger UI) — `http://localhost:8000/docs`
- Dagster UI — `http://localhost:3000`

Apply database migrations separately:

```bash
cd apps/migrations && uv run alembic upgrade head
# or, equivalently:
make migrate
```

In Dagster, materialize `seed_instruments` to load the SSE/SZSE ETF
universe via the `fixture_dev` adapter, then refresh the web dashboard.

## 4. Common Make targets

The full list is in [`/Makefile`](../Makefile); the canonical ones are:

- `make up` / `make down` / `make logs` — start / stop / tail the stack.
- `make migrate` — run Alembic against the dev database.
- `make test` — full CI suite: `arch-check` → `test-domain` →
  `test-storage` → `test-storage-integration` → `test-migrations` →
  `test-pipeline` → `test-api` → `test-web`.
- `make test-<area>` — run one slice (`test-domain`, `test-storage`,
  `test-storage-integration`, `test-migrations`, `test-pipeline`,
  `test-api`, `test-web`).
- `make arch-check` — AST-based boundary check
  (`scripts/check_architecture.py`).
- `make lock` — regenerate `uv.lock` for every Python project.

## 5. Layer rules (at a glance)

The boundary scanner [`scripts/check_architecture.py`](../scripts/check_architecture.py)
makes these imports errors:

- `packages/domain/src` must not import `fastapi`, `sqlalchemy`, `dagster`,
  `httpx`, `requests`, `akshare`, `pandas`, `polars`, `vectorbt`,
  `backtrader`.
- `packages/storage/src` must not import `fastapi`, `dagster`,
  `akshare`, `vectorbt`, `backtrader`.
- `apps/api/src` must not import `dagster`, `akshare`, `vectorbt`,
  `backtrader`, `jupyter`.
- `apps/pipeline/src/invest_pipeline/adapters` may not import
  `sqlalchemy`.
- The `apps/pipeline/src/invest_pipeline/assets` layer must not import
  `subprocess`.

The checker also rejects:

- `schema="app"` (the `app` schema was retired — use `raw` / `core` /
  `analytics` / `ops`).
- `qfq` / `hfq` literals in production paths (only `none` is allowed
  per ADR-0005).
- A `providers.py` file coexisting with a `providers/` directory in
  the pipeline package.

## 6. The PR sequence that produced this codebase

The codebase you see today is the result of nine merged PRs:

| PR | Commit | What it added |
|----|--------|---------------|
| M0 / correction plan | `77a156c`, `5866b03` | Greenfield baseline; correction-plan splits the migration app out of `apps/api`. |
| PR-02 | `c5cc938` | Provider three-layer evidence model (`raw.provider_requests` / `provider_attempts` / `provider_batches`). |
| PR-03 | `d2b6b37` | Candidate Pool persistence tables. |
| PR-04 | `2b5779b` | Provider selection ADR-0003 accepted; ready-state for adapter boundary. |
| PR-05 | `905f8d5` | Real ETF instrument data pipeline with the `fixture_dev` adapter. |
| PR-06 | `fac3772` | ETF daily-bars pipeline with the ADR-0006 revision model. |
| PR-07 | `4d55c20` | Input Snapshot pipeline (`analytics.input_snapshots`). |
| PR-08 | `cabc775` | Minimum Candidate Pool calculator as a pure function. |
| PR-09 | `4bdea03` | FastAPI read-only endpoints for ETF and Candidate Pool. |

Working-copy additions after PR-09 refine the response schemas (a single
`InstrumentResponse.from_instrument` factory now builds both the legacy
and ETF list responses) and inline `SessionProvider` into the storage
Unit of Work.

Phase 1 first increment (ADR-0011, Status: Proposed) ships a placeholder
CifangQuant adapter at
[`apps/pipeline/src/invest_pipeline/adapters/cifang/`](apps/pipeline/src/invest_pipeline/adapters/cifang/)
and a declarative `provider_catalog.py` that records provider role /
capability metadata for V2. `QUICKTINY_MCP` is registered as
research-only (`research` + `market_snapshot`), with no ETF-ingestion
runtime; Cifang remains a disabled placeholder adapter.
The M4 `CandidatePoolCalculator` Protocol was removed from
`invest_domain.candidate_pool.ports`; the [provider catalog](pipeline/overview.md#provider-catalog)
and the [cifang placeholder](pipeline/overview.md#cifang-adapter-placeholder-adr-0011-phase-1-first-increment)
sections describe the new surfaces.

## 7. Backlog

- **Web pages for candidate pool and pipeline runs.** The FastAPI surface
  exposes them but `apps/web/` only consumes the legacy `/v1/instruments`
  shape; no `CandidatePoolPage.tsx` exists yet.
- **Real Provider selection (O-1 in M0-DECISIONS §4).** `fixture_dev`
  is the only adapter with real data; the `cifang` placeholder
  ([ADR-0011](../docs/adr/0011-cifangquant-primary-etf-provider.md))
  locks the Port shape but raises `ProviderAdapterNotImplementedError`
  until O-1 / O-3 / O-4 are closed.
- **M4 candidate-pool algorithm.** ADR-0008 calls for scored rules,
  rolling-window liquidity and price-quality rules, and risk scoring;
  only the PR-08 minimum calculator (no-data / suspended / invalid_price
  / low_volume / low_amount) exists today.
- **Operational runbooks (`docs/runbooks/...`).** M0-CODING-BRIEF
  Phase 1-F lists five runbooks (provider-auth-failure,
  daily-bars-missing, reprocess-partition, reject-candidate-pool,
  database-restore); they are not yet checked in.
