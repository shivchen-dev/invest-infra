---
type: Reference
title: OpenWiki Quickstart
description: Entry point for the invest-infra OpenWiki knowledge base. Describes the modular-monolith layout, links every major concept page, and summarizes local startup, migrations, personal daily scheduling and replay/backfill operations, testing, opt-in CifangQuant / Tushare / JiuwenSwarm validation, the DC-2 ETF profile and Stage 4A evidence / context slices, the ADR-0012 evidence-driven Research lifecycle (PR-7 API + JiuwenSwarm adapter + orchestration service + PR-W03 dashboard / PR-W05 case workspace read models), the PR-MCP-MINIMAL read-only MCP server, the DC-3 exposure collection slice, the Research Cockpit web workbench (widget runtime + dashboard widgets + safe markdown renderer), the centralized provider credential store, the Stage 4B Market Intelligence foundation (Market Observation / Temperature / Breadth read slices + Tushare-stock by-date pipeline + Research Evidence Bundle chain), and the HiThink reserved provider catalog entry.
resource: /openwiki/quickstart.md
tags: [quickstart, navigation, invest-infra, etf-profile, research-context, research-lifecycle, research-cockpit, jiuwenswarm, mcp, exposure, governance, stage4b, market-breadth, market-temperature, market-observations, stock-universe, tdx-offline, evidence-bundle, hithink]
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
| `docs/adr/0001..0012` | Architecture decisions; ADR-0011 remains Proposed, while ADR-0012 freezes the evidence-driven Research lifecycle boundary (see [Architecture overview](architecture/overview.md)). |

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
   layers, four PostgreSQL schemas, layered rules, ADR index (now
   including ADR-0012 for the Research lifecycle boundary) and the
   architecture-governance baseline.
2. [Migrations overview](migrations/overview.md) — how
   `apps/migrations` owns the schema and the seventeen-revision chain
   (now including `0011` DC-3 exposure, `0012` research cases,
   `0013` evidence-pack case FK, `0014` research runs,
   `0015` market-observation snapshots, `0016` research evidence
   bundles and `0017` research-result ↔ evidence-bundle FK).
3. [Domain overview](domain/overview.md) — bounded contexts and the
   canonical hashing scheme (now including the DC-2 `etf_profile`
   context, the Stage 4A `research.context` vocabulary, the
   evidence-driven `research.{case,run,runner}` lifecycle, the
   `exposure` bounded context, and the consolidated
   `analytics.factor_calculators`).
4. [Candidate pool](domain/candidate-pool.md) — the pure-function
   calculator and the state machine that governs one calculation.
5. [Storage overview](storage/overview.md) — repositories, the
   `UnitOfWork` and the three-layer Provider evidence model (now
   including the DC-2 `etf_profiles` / `etf_profile_fields`
   repositories, the `research_context_packs` / `research_cases` /
   `research_runs` / `research_results` repositories, the
   `evidence_pack_codec`, the exposure repositories, and the
   `research_evidence_packs.research_case_id` FK from `20260807_0013`).
6. [API overview](api/overview.md) — FastAPI routers (legacy + ETF +
   candidate-pool latest/diff + pipeline-run status/history + data
   freshness + the PR-7 research-case / evidence / run / result
   lifecycle queries + the PR-MCP-MINIMAL read-only MCP server),
   Pydantic response shapes, the architecture-governance
   application-service split.
7. [Pipeline overview](pipeline/overview.md) — Dagster `Definitions`, the
   `etf_*` assets, adapter boundaries (now including Tushare, the
   JiuwenSwarm research-runner adapter and the gated
   `exposure` adapters), the DC-2 ETF Profile and research context
   builder services, the PR-7 `research_orchestration_service`,
   the DC-3 real-exposure collection, the declarative provider catalog,
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

- Web — `http://localhost:3001`
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

ADR-0012 freezes the evidence-driven Research lifecycle:
`ResearchCase` (binds an instrument and optional Candidate Pool run)
→ immutable `EvidencePack` → `ResearchRun` (versioned runner /
playbook, attempts, external session identity) → `ResearchResult`
(only when a run has succeeded, references only valid evidence IDs).
The pipeline ships the `JiuwenSwarmResearchRunner` adapter behind
the domain `ResearchRunner` port ([Pipeline overview §5e](pipeline/overview.md#5e-jiuwenswarm-research-runner-adapter-pr-6-slice-1-3))
plus the `research_orchestration_service` ([Pipeline overview §5g](pipeline/overview.md#5g-research-orchestration-service-pr-7--adr-0012))
that drives one attempt through the storage `UnitOfWork` and
persists `analytics.research_cases` / `research_evidence_packs` /
`research_runs` / `research_results`. The read-only `ResearchQueryService`
exposes the lifecycle through the API ([API overview §1](api/overview.md#1-modules))
at `/api/v1/research-cases`, `/api/v1/research-runs`, and the matching
evidence / result detail endpoints (see [API overview §2](api/overview.md#2-routing-surface)
for the six original PR-7 endpoints). PR-W03 adds the read-only
`/api/v1/research-dashboard` aggregate, and PR-W05 adds the read-only case
workspace route. The PR-MCP-MINIMAL read-only MCP
server ([API overview §7](api/overview.md#7-read-only-mcp-server-pr-mcp-minimal))
exposes `get_data_freshness` / `get_latest_candidate_pool` /
`get_candidate_pool_diff` / `get_etf_daily_bars` through the FastMCP
transport so research agents query the API surface instead of
reaching into PostgreSQL directly.

The architecture-governance convergence ([Architecture overview §6](architecture/overview.md#6-architecture-governance-convergence))
moved every read-only API use-case behind a dedicated
`invest_api.application.*` service (`EtfQueryService`,
`CandidatePoolQueryService`, `PipelineRunQueryService`,
`DataFreshnessQueryService`, `ResearchQueryService`) so the
routers are thin wrappers and SQLAlchemy access lives in one place.
New data additions are gated by the
[data admission checklist](../docs/validation/data-admission-checklist.md)
and the consolidated `domain.analytics.factor_calculators` owns
the deterministic factor calculation (GOV-03). DC-3 exposure
collection (CSIndex `report_asset_detail` / AkShare
`fund_portfolio_hold_em` mapped onto `IndexProfile` /
`IndexConstituentSnapshot` / `EtfIndexMapping` /
`EtfHoldingSnapshot`) lands in
[`apps/pipeline/src/invest_pipeline/exposure_service.py`](../apps/pipeline/src/invest_pipeline/exposure_service.py)
with the fixture / real-exposure driver pairing mirroring the
ETF collection slice. Migration `20260806_0011_dc3_exposure`
adds the matching tables; `20260807_0012_research_cases`,
`20260807_0013_research_evidence_packs_case_fk` and
`20260807_0014_research_runs` anchor the research lifecycle.
The AST migration-chain gate now expects a single head at
`20260812_0017` and round-trips `upgrade head → downgrade base →
upgrade head` end-to-end.

Stage 4B lands the **Market Intelligence Foundation** vertical slice on top
of the Stage 4A evidence / context separation. The pure-domain side carves
three new analytical modules ([`market_observations`](../packages/domain/src/invest_domain/analytics/market_observations.py) /
[`market_temperature`](../packages/domain/src/invest_domain/analytics/market_temperature.py) /
[`market_breadth`](../packages/domain/src/invest_domain/analytics/market_breadth.py)) that share a single `MarketObservationSnapshot`
vocabulary, plus the [`research.evidence_bundle`](../packages/domain/src/invest_domain/research/evidence_bundle.py)
domain object that pins a case to one ResearchEvidenceBundle. The pipeline
gains a Tushare-driven stock-daily-bars + dynamic-universe slice
([`stock_universe.py`](../apps/pipeline/src/invest_pipeline/stock_universe.py) +
[`stock_daily_bars.py`](../apps/pipeline/src/invest_pipeline/stock_daily_bars.py)) that materialises
`stock_input_snapshot` against the active `STOCK` universe, a `tdx_offline`
adapter ([`adapters/tdx_offline/`](../apps/pipeline/src/invest_pipeline/adapters/tdx_offline/)) that
reads pre-fetched TDX snapshot archives without ever touching the network,
the [`market_breadth_service.py`](../apps/pipeline/src/invest_pipeline/market_breadth_service.py) +
[`market_breadth_bundle_service.py`](../apps/pipeline/src/invest_pipeline/market_breadth_bundle_service.py) application services that bridge the
snapshot family to the new `ResearchEvidenceBundle`, and Dagster assets
(`stock_daily_bars_raw` / `stock_daily_bars` / `stock_input_snapshot` /
`market_breadth_snapshot`). The API exposes two new read-only routes —
`GET /api/v1/market-temperature/latest` and
`GET /api/v1/market-breadth/latest` — both thin wrappers over dedicated
[`MarketTemperatureQueryService`](../apps/api/src/invest_api/application/market_temperature.py) and
[`MarketBreadthQueryService`](../apps/api/src/invest_api/application/market_breadth.py) services that pin a fixed
`scope_type` / `scope_key` pair so a snapshot family is never read through
the wrong route. Migrations
[`20260810_0015_market_observation_snapshots`](../apps/migrations/migrations/versions/20260810_0015_market_observation_snapshots.py),
[`20260811_0016_research_evidence_bundles`](../apps/migrations/migrations/versions/20260811_0016_research_evidence_bundles.py) and
[`20260812_0017_research_result_evidence_bundle_fk`](../apps/migrations/migrations/versions/20260812_0017_research_result_evidence_bundle_fk.py)
extend the chain (`20260807_0014` → `20260812_0017` head).

The HiThink reserved provider slice ([`tasks/hithink-reserved-provider-plan.md`](../tasks/hithink-reserved-provider-plan.md))
registers `hithink` as a reserved `ProviderDeclaration` in
[`provider_catalog.py`](../apps/pipeline/src/invest_pipeline/provider_catalog.py):
role `research_only`, capabilities `research` / `market_snapshot` /
`stock_daily_bars` / `stock_master_data` / `stock_financials` /
`stock_valuations`, `enabled_by_default=False`,
**`has_runtime_factory_adapter=False`** so `provider_factory.build_provider()`
keeps failing the future `INVEST_PIPELINE_PROVIDER_KEY=hithink` lookup with
`UnknownProviderError`. The API key is read lazily via the centralized
[`invest_pipeline.credentials.CredentialStore`](../apps/pipeline/src/invest_pipeline/credentials.py)
against `hithink.api_key` (documented in `.env.example`); no network client
or runtime factory branch lands in this slice, and no test / log embeds the
credential material.

## 7. Web data workbench

`apps/web/` is a read-only React workbench backed by the `/api/v1`
surface. The page files under `apps/web/src/pages/` are intentionally
thin compositions: each route delegates the heavy lifting to a feature
folder (`apps/web/src/features/{dashboard,candidatePool,instruments,operations,research}/`)
that owns the data widgets, filters, status badges, and chart helpers
— for example, `CandidateFilters`, `CandidateTable`, `CandidateRowDetails`,
`DailyBarsTable`, `ClosePriceChart`, `RunStatusBadge`, and
`LatestRunPanel`. The main routes are:

- `/dashboard` — freshness, candidate summary, diff and latest run, plus
  the **Research Cockpit** widget grid (`MarketStatusWidget` /
  `ResearchSummaryWidget` / `EvidencePackWidget` /
  `FactorSnapshotWidget` / `RiskMonitorWidget` /
  `ResearchRunTimelineWidget`) composed by
  [`features/research/dashboard/ResearchCockpitSection.tsx`](../apps/web/src/features/research/dashboard/ResearchCockpitSection.tsx)
  and driven by [`GET /api/v1/research-dashboard`](api/overview.md);
- `/candidate-pool` — included/excluded/all tabs, filters, exclusion reasons
  and expandable rule details;
- `/etf/:instrumentId` — instrument metadata, 30/60/120-day daily bars and a
  lightweight SVG close-price chart;
- `/operations` — freshness, latest/history Pipeline Runs and a non-executing
  replay command hint;
- `/research/history` — paginated research-case list with filters, table,
  status-tone badges and a detail link into the cockpit;
- `/research/:caseId` — read-only Research Cockpit case workspace with the
  bound `EvidencePack`, run timeline (Chinese-localised status labels plus a
  dedicated diagnostic panel for `failed` / `error` runs), the latest
  `ResearchResult` rendered through the safe markdown renderer
  (`MarkdownView`, which only promotes `http(s)://` URLs to links and keeps
  everything else as plain text), and result metadata — all driven by
  [`GET /api/v1/research-cases/{case_id}/workspace`](api/overview.md).

### 7a. Research Cockpit widget runtime

The `/dashboard` and `/research/:caseId` pages render widgets through a
small deterministic runtime under
[`apps/web/src/research-workspace/runtime/`](../apps/web/src/research-workspace/runtime/index.ts):

- `WidgetFrame` is the shared shell: title, description, provenance, state
  badge (`pending` / `ready` / `error` / `empty`), `generatedAt`, and the
  `asOf` date. Frame content is loaded through `WorkspaceLoadingGate` so
  a widget and its loading state stay in lock-step.
- `StatusBadge` is the deterministic tone helper used by the cockpit
  (`success` / `warning` / `danger` / `info` / `neutral`) and maps the
  raw research-run status to a Chinese label (`已创建` / `证据就绪` /
  `运行中` / `已完成` / `失败` / `已跳过` / `已取消` / `等待中`) so a
  failure surfaces the localised label **plus** a dedicated
  `cockpitRunDiagnostic` panel that quotes `error_summary` verbatim.
- `registry.ts` is the typed registry that maps widget `id`s to their
  metadata; `layout.ts` derives the responsive 12-column grid placement
  from a single source of truth so `/dashboard` and the case workspace
  share the same shape. The registry deliberately omits market data
  discovery / write controls — every widget is a read-only projection
  of the PR-W03 dashboard endpoint.

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
pnpm test:e2e        # Playwright cockpit e2e (apps/web/e2e/*.e2e.ts) on http://127.0.0.1:5174
pnpm build           # production bundle
```

The default `API_BASE` falls back to `http://${window.location.hostname}:8000`
when `VITE_API_BASE_URL` is unset, so the workbench auto-resolves the LAN
address of the API container without a rebuild — see
[`apps/web/src/api/client.ts`](../apps/web/src/api/client.ts).

## 8. Backlog
- **Real Provider selection (O-1 in M0-DECISIONS §4).** `cifangquant`
  is wired end-to-end behind the three opt-ins and the smoke CLI;
  [ADR-0011](../docs/adr/0011-cifangquant-primary-etf-provider.md)
  remains Proposed until O-1 / O-3 / O-4 are closed.
- **M4 candidate-pool algorithm.** ADR-0008 calls for scored rules,
  rolling-window liquidity and price-quality rules, and risk scoring;
  only the PR-08 minimum calculator (no-data / suspended / invalid_price
  / low_volume / low_amount) exists today, plus the PR-5 declarative
  `candidate_pool.{baseline,institutional,custom_strategy}` channels
  the architecture-governance slice added.
- **JiuwenSwarm go-live.** The
  [JiuwenSwarm adapter](pipeline/overview.md#5e-jiuwenswarm-research-runner-adapter-pr-6-slice-1-3)
  is wired and tested against an in-memory fake runner; the
  Slice 1 / 2 / 3 boundaries hold, but production traffic still
  depends on a real helper CLI binary and ADR-0012 ongoing
  graduation criteria.
- **Remaining operational runbooks.** The checked-in
  [`cifang-auth-failure.md`](../docs/runbooks/cifang-auth-failure.md) and
  [`reprocess-trade-date.md`](../docs/runbooks/reprocess-trade-date.md)
  cover authentication recovery and single-date replay; the M0-CODING-BRIEF
  still calls for `daily-bars-missing`, `reject-candidate-pool`, and
  `database-restore` runbooks, which are not yet checked in.
- **Research API write surface.** The PR-7 API exposes read-only
  lifecycle queries (cases, runs, evidence, results); the PR-W03
  cockpit dashboard and PR-W05 case workspace read models are
  read-only compositions of those existing resources. A controller
  surface that opens new `ResearchCase` rows through HTTP, plus the
  replay / reconciliation endpoint for
  `ResearchOrchestrationReconciliationRequiredError`, is not part
  of this slice.
- **Research Cockpit market / factor slots.** The PR-W03 dashboard
  exposes an explicit `{"state": "unavailable", "reason": ...}` shape
  for the `market_status` slot and renders only structural placeholders
  for `FactorSnapshot` / `RiskMonitor`; a real market / factor source
  must be wired in before those widgets can move out of the empty
  state.
- **Web e2e in CI.** The Playwright cockpit e2e
  (`apps/web/e2e/research-cockpit.e2e.ts`) ships as a local
  `pnpm test:e2e` script; the GitHub Actions workflow still runs the
  vitest + jsdom suite under `web-check` only, so the cockpit smoke
  is not gated by CI today.
