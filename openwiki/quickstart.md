---
type: Reference
title: OpenWiki Quickstart
description: Entry point for the invest-infra OpenWiki knowledge base. Describes the modular-monolith layout, links every major concept page, and summarizes local startup, migrations, personal daily scheduling and replay/backfill operations, testing, opt-in CifangQuant / Tushare validation, the DC-2 ETF profile and Stage 4A research context slices, and the centralized provider credential store.
resource: /openwiki/quickstart.md
tags: [quickstart, navigation, invest-infra, etf-profile, research-context]
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
   `apps/migrations` owns the schema and the seven-revision chain.
3. [Domain overview](domain/overview.md) — bounded contexts and the
   canonical hashing scheme (now including the DC-2 `etf_profile`
   context and the Stage 4A `research.context` vocabulary).
4. [Candidate pool](domain/candidate-pool.md) — the pure-function
   calculator and the state machine that governs one calculation.
5. [Storage overview](storage/overview.md) — repositories, the
   `UnitOfWork` and the three-layer Provider evidence model (now
   including the DC-2 `etf_profiles` / `etf_profile_fields`
   repositories and the `research_context_packs` repository).
6. [API overview](api/overview.md) — FastAPI routers (legacy + ETF +
   candidate-pool latest/diff + pipeline-run status/history + data freshness),
   Pydantic response shapes.
7. [Pipeline overview](pipeline/overview.md) — Dagster `Definitions`, the
   `etf_*` assets, adapter boundaries (now including Tushare and the
   centralized credential store), the DC-2 ETF Profile and research
   context builder services, the declarative provider catalog,
   guarded personal scheduling, and replay/backfill operations.
8. [Testing & operations](testing-and-ops/overview.md) — CI jobs, the
   migration-chain AST gate, mock vs integration tests, the PostgreSQL e2e,
   compose runtime, replay/runbook controls, and the OpenWiki auto-update
   workflow.

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

For a host-managed Dagster process, install the user-level unit instead:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/invest-infra-dagster.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now invest-infra-dagster.service
```

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
- `make provider-smoke` — opt-in real-network CifangQuant smoke
  (`SMOKE_SYMBOLS=...`, `SMOKE_TRADE_DATE=...`,
  `SMOKE_CONFIRM_NETWORK=1`).
- `make personal-daily-run` — manual `personal_etf_daily_job` driver
  (`TRADE_DATE=...`); fixture mode needs no opt-in, real-network mode
  needs `INVEST_PIPELINE_PROVIDER_KEY=cifangquant` +
  `INVEST_PIPELINE_CIFANG_ENABLED=true` + `CONFIRM_NETWORK=1` and an
  injected `INVEST_PIPELINE_CIFANG_API_KEY`.
- `make reprocess-date TRADE_DATE=YYYY-MM-DD` — canonical single-date
  replay; it delegates to `personal-daily-run` and requires `TRADE_DATE`.
- `make personal-backfill START_DATE=YYYY-MM-DD END_DATE=YYYY-MM-DD` —
  chronological weekday-only replay for an inclusive range of at most 90
  natural days; weekends are skipped and the first failed weekday aborts.
- `make historical-daily-bars-backfill START_DATE=YYYY-MM-DD END_DATE=YYYY-MM-DD [UNIVERSE=path] [CONFIRM_NETWORK=1]` —
  guarded historical ETF daily-bars backfill (≤90-day chunks, no Dagster
  job, no input-snapshot / candidate-pool / evidence-pack / AI-research
  assets). Provider opt-in is scoped to `fixture_dev` or `cifangquant`
  in this slice; the [Pipeline overview](pipeline/overview.md#11-personal-clis)
  documents the exit-code contract.
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

ADR-0011 (Status: Proposed) CifangQuant adapter is shipped in two
stacked increments. The first increment freezes `CifangSettings`
(redacted `api_key`, locked `adjustment='none'`, `enabled=False`
default) and the `EtfMarketDataProvider` port shape. The second
increment adds the real `httpx` client, the `/api/fund/list` /
`api/fund/hist_em` field mappers, the 50-symbol chunking rule, and
the evidence-tuple adapter; the network is still gated on
`CifangSettings.enabled=True` plus three opt-ins for the smoke CLI.
The runtime selection lives in
`provider_factory.build_provider()` (the `invest_pipeline` assets now
resolve the provider through the factory instead of constructing
`FixtureDevInstrumentProvider` directly).

Stage 1 lands the personal daily pipeline:
[`personal_universe.py`](../apps/pipeline/src/invest_pipeline/personal_universe.py)
loads `config/personal-universe.yaml`, `candidate_pool_service.py`
loads `config/candidate-pool-personal.yaml`, and the new
`personal_etf_daily_job` Dagster job + `personal_candidate_pool`
asset run the whole
`etf_instruments_raw → etf_daily_bars → etf_input_snapshot →
personal_candidate_pool` chain for one trade date. `make
personal-daily-run` is the manual CLI driver; the Section 9
("Personal universe & config"), Section 10 ("Candidate pool
service"), Section 11 ("Personal CLIs") and Section 12 ("Provider
factory") of the [pipeline overview](pipeline/overview.md) describe
the new surfaces. The `provider_catalog.py` declarative registry now registers
**six** frozen `ProviderDeclaration` rows (`akshare` /
`cifangquant` / `fixture_dev` / `quicktiny_mcp` / `rsscast` /
`tushare`); the catalog is the single source of truth for the role /
capability set every provider must respect. Only `fixture_dev` is
enabled by default; every other declaration stays
`enabled_by_default=False` per the matrix §6 default-off rule. The
[Pipeline overview](pipeline/overview.md#7-provider-catalog)
documents the six declarations and the negative-capability
contract, and the [Pipeline overview §7A](pipeline/overview.md)
introduces the deterministic dataset × capability
`provider_routing` layer PR-05 adds on top. Provider credentials
flow through the centralized
[`invest_pipeline.credentials.CredentialStore`](../apps/pipeline/src/invest_pipeline/credentials.py)
helper; the runtime `provider_factory.build_provider()` exposes
`fixture_dev` / `cifangquant` / `akshare` / `tushare` as its four
branches — see [Pipeline overview §12](pipeline/overview.md#12-provider-factory).

Stage 2 aligns all six job assets to the same daily partition, registers a
weekday `16:10 Asia/Shanghai` schedule, and adds preflight checks for future
or weekend dates, provider/universe configuration, and duplicate published
or running work. Automatic scheduling remains default-off unless
`INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED=true`. Operators inspect the new
pipeline-run, candidate-pool diff, and data-freshness endpoints described in
the [API overview](api/overview.md), and use the replay/backfill procedures in
[Testing & operations](testing-and-ops/overview.md#7-operational-runbooks-and-validation).

Stage 4A ships the V2 multi-source catalog and evidence foundation: the
provider catalog now holds **six** frozen `ProviderDeclaration` rows
(`akshare` / `cifangquant` / `fixture_dev` / `quicktiny_mcp` / `rsscast`
/ `tushare`) with frozen `role` / `capability` / `enabled_by_default`
triples. The historical three-provider plan (`eastmoney` / `sina` /
`tonghuashun`) has been **de-scoped** — the three sources are no
longer selectable runtime providers and the catalog carries no
declaration for them; their public historical-quotes endpoints
remain internal upstreams of the AkShare aggregator. The
`provider_routing` layer exposes the deterministic
`select_providers` selection rules plus the read-only
`CoverageReportModel` (sortable, hash-stable) that the
`provider_coverage_cli` driver serialises to JSON. The AkShare,
QuickTiny MCP, RssCast MCP and Tushare adapters land as gated, opt-in
research and market-data transports; the historical ETF backfill
CLI plus the `make historical-daily-bars-backfill` target let
operators replay raw + core.daily_bars over ≤90-day chunks
without invoking the personal daily Dagster job. Provider credentials
flow through the centralized
[`invest_pipeline.credentials.CredentialStore`](../apps/pipeline/src/invest_pipeline/credentials.py)
helper (default root `/home/claw/invest-secrets`, override via
`INVEST_PIPELINE_SECRETS_DIR`); the explicit `INVEST_PIPELINE_*_TOKEN`
env vars remain the highest-priority override.

The `domain.research` bounded context defines the Stage 4A evidence
contract (`EvidencePack` + 8-factor v1.0.0 set + canonical
hashing); the new `domain.research.context` module adds the
`ResearchContextPack` / `ContextItem` / `ContextValueType`
vocabulary that the evidence / context separation plan introduces.
`domain.candidate_pool.{universe,v1_adapter}` provide the pure
dynamic ETF universe qualification and the V1→V2 pure adapter.
`domain.etf_profile` is the DC-2 evidence framework: `EtfProfile`
+ `FieldEvidence` / `FieldKey` / `FieldValueType` /
`FieldEvidenceSource` (PR-ETF-PROFILE-01) and the `ProfileResolver`
+ `ResolutionStatus` / `ResolvedField` (PR-ETF-PROFILE-03). The
pipeline-side `etf_profiles` service runs the PR-02 three-layer
evidence write for the AkShare profile snapshot, persists
`FieldEvidence` rows through `uow.etf_profile_fields`, and
upserts the canonical `core.etf_profiles` row. The
`etf_profile_context` builder projects the resolved evidence into
the `etf_profile` `ResearchContextPack` (plan §"Task C3") and
persists the pack through `uow.research_context_packs`. Migrations
`20260804_0008_etf_profiles` /
`20260805_0009_etf_profile_fields` /
`20260805_0010_research_context_packs` add the matching tables;
the AST migration-chain gate still expects a single head at
`20260805_0010` and round-trips `upgrade head → downgrade base →
upgrade head` end-to-end.

## 7. Web data workbench

`apps/web/` is a read-only React workbench backed by the `/api/v1`
surface. The page files under `apps/web/src/pages/` are intentionally
thin compositions: each route delegates the heavy lifting to a feature
folder (`apps/web/src/features/{dashboard,candidatePool,instruments,operations}/`)
that owns the data widgets, filters, status badges, and chart helpers
— for example, `CandidateFilters`, `CandidateTable`, `CandidateRowDetails`,
`DailyBarsTable`, `ClosePriceChart`, `RunStatusBadge`, and
`LatestRunPanel`. The main routes are:

- `/dashboard` — freshness, candidate summary, diff and latest run;
- `/candidate-pool` — included/excluded/all tabs, filters, exclusion reasons
  and expandable rule details;
- `/etf/:instrumentId` — instrument metadata, 30/60/120-day daily bars and a
  lightweight SVG close-price chart;
- `/operations` — freshness, latest/history Pipeline Runs and a non-executing
  replay command hint.

The browser has no write controls and does not trigger Pipeline runs.
The Web's API client is auto-generated from the FastAPI OpenAPI surface
via `pnpm api:generate` (see
[`apps/web/src/api/generated.ts`](../apps/web/src/api/generated.ts));
manually hand-maintaining response types in `apps/web/src/api/types.ts`
is intentionally discouraged so the contract has a single source of
truth. The local commands are:

```bash
cd apps/web
pnpm typecheck       # TypeScript + Vite build type-check
pnpm test:run        # vitest + jsdom unit suite (router, API client, pages, components, utils)
pnpm build           # production bundle
```

## 8. Backlog
- **Real Provider selection (O-1 in M0-DECISIONS §4).** `cifangquant`
  is wired end-to-end behind the three opt-ins and the smoke CLI;
  [ADR-0011](../docs/adr/0011-cifangquant-primary-etf-provider.md)
  remains Proposed until O-1 / O-3 / O-4 are closed.
- **M4 candidate-pool algorithm.** ADR-0008 calls for scored rules,
  rolling-window liquidity and price-quality rules, and risk scoring;
  only the PR-08 minimum calculator (no-data / suspended / invalid_price
  / low_volume / low_amount) exists today.
- **Remaining operational runbooks.** The checked-in
  [`cifang-auth-failure.md`](../docs/runbooks/cifang-auth-failure.md) and
  [`reprocess-trade-date.md`](../docs/runbooks/reprocess-trade-date.md)
  cover authentication recovery and single-date replay; the M0-CODING-BRIEF
  still calls for `daily-bars-missing`, `reject-candidate-pool`, and
  `database-restore` runbooks, which are not yet checked in.
