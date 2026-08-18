---
type: Reference
title: OpenWiki Quickstart
description: "Entry point for the invest-infra OpenWiki knowledge base. Describes the modular-monolith layout, links every major concept page, and summarizes local startup, migrations, personal daily scheduling and replay/backfill operations, testing, opt-in CifangQuant / Tushare / JiuwenSwarm validation, the DC-2 ETF profile and Stage 4A evidence / context slices, the ADR-0012 evidence-driven Research lifecycle (PR-7 API + JiuwenSwarm adapter + orchestration service + context-projection loader + PR-W03 dashboard / PR-W05 case workspace read models), the PR-MCP-MINIMAL read-only MCP server, the DC-3 exposure collection slice, the Research Cockpit web workbench (widget runtime + dashboard widgets + safe markdown renderer), the centralized provider credential store, the Stage 4B Market Intelligence foundation (Market Observation / Temperature / Breadth read slices + Tushare-stock by-date pipeline + TDX offline fallback + Research Evidence Bundle chain), the Stage 4C Core Data Layer Integration (versioned price-limit domain policy + Stock Price-Limit raw/core persistence + Market Breadth v2 + Limit Sentiment + 18-revision chain), the ADR-0013 Provider–Engine–Event Phase 0 seam (ProviderRuntimeRegistry + StockDailyBars Engine/Application + provider publishability gate), the HiThink reserved provider catalog entry, the WorkBuddy daily-report governance (M0/M1/M2: validator + immutable archive + accepted-only latest-pointer) plus WorkBuddy candidate intake (M0 contract: parser + immutable archive + symbol/projection dedupe + shared-directory gateway), and the Stage 4D External Integration Workbench (Bridge ingest + `integration` schema + External Workflow Run / Artifact / Observation read API + Opportunity Radar + Integration Health + Research-Case evidence link + gated admission-decision command). Two independently-evolving pipelines that share the strict `YYYY-MM-DD` / safe-path-segment identity contract."
resource: /openwiki/quickstart.md
tags: [quickstart, navigation, invest-infra, etf-profile, research-context, research-lifecycle, research-cockpit, jiuwenswarm, mcp, exposure, governance, stage4b, stage4c, market-breadth, market-temperature, market-observations, stock-universe, tdx-offline, evidence-bundle, hithink, provider-engine-event, price-limits, limit-sentiment, workbuddy, workbuddy-reports, workbuddy-candidates, stage4d, external-workflows, opportunity-radar, integration-health, admission-decisions, bridge-ingest]
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
   `apps/migrations` owns the schema and the twenty-revision chain
    (the eighteen Stage 4C chain plus
    `0019` external integration and
    `0020` research-external-evidence — see
    [Migrations overview §2](migrations/overview.md#2-the-twenty-revision-chain)),
   (now including `0011` DC-3 exposure, `0012` research cases,
   `0013` evidence-pack case FK, `0014` research runs,
   `0015` market-observation snapshots, `0016` research evidence
   bundles, `0017` research-result ↔ evidence-bundle FK and
   `0018` Stage 4C stock price-limits).
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
   lifecycle queries + the PR-MCP-MINIMAL read-only MCP server +
   the Stage 4D external-workflows / integration-health /
   opportunity-radar read endpoints + the gated
   admission-decisions write command + the research-case external
   evidence link),
   Pydantic response shapes, the architecture-governance
   application-service split.
7. [Pipeline overview](pipeline/overview.md) — Dagster `Definitions`, the
   `etf_*` assets, adapter boundaries (now including Tushare, the
   JiuwenSwarm research-runner adapter and the gated
   `exposure` adapters), the DC-2 ETF Profile and research context
   builder services, the PR-7 `research_orchestration_service`,
   the DC-3 real-exposure collection, the declarative provider catalog
   (now carrying `STOCK_MINUTE_BARS` / `STOCK_BLOCK_MEMBERSHIPS` /
   `STOCK_PRICE_LIMITS` / `TDX_GUI_ANALYSIS` capabilities and a
   `STOCK_PRICE_LIMITS` `dataset_key` for Stage 4C), the
   Stage 4B stock daily-bars fallback (Tushare + TDX offline slice 2
   with bounded pair request keys and `prev_close` derivation),
   the Stage 4C stock price-limits ETL service + Limit Sentiment
   publish service + Market Breadth v2 publish service,
   the [Provider–Engine–Event seam](pipeline/provider-engine-event.md)
   (`ProviderRuntimeRegistry` + `StockDailyBarsEngine` /
   `StockDailyBarsApplication` + `ProviderPublishDecision` gate),
the [WorkBuddy daily-report governance](pipeline/overview.md#5m-workbuddy-daily-report-governance-m0--m1--m2-atomic-slices)
   (M0 first-slice validator + M1/M2 immutable archive +
   `latest-accepted.json` pointer), the
   [WorkBuddy candidate intake](pipeline/overview.md#5n-workbuddy-candidate-intake-m0-contract-aligned-slice)
   (M0 contract-aligned parser + immutable archive +
   symbol/projection dedupe) and the
   [Stage 4D Bridge ingest](pipeline/overview.md#5k-stage-4d-external-integration-workbench-bridge-ingest--shared-directory-gateway)
   (`import_archived_candidate_run` + `SharedDirectoryWorkBuddyGateway`
   that turn an archived `candidates.json` into External Workflow Run /
   Artifact / Observation rows through the storage UoW),
   guarded personal scheduling, and replay/backfill operations.
8. [Testing & operations](testing-and-ops/overview.md) — CI jobs, the
   migration-chain AST gate, mock vs integration tests, the PostgreSQL e2e,
   compose runtime, replay/runbook controls, and the OpenWiki auto-update
   workflow.

## 2a. Task routing

| Change area or user intent | Relevant wiki page | Exact source entry points | Important symbols or types | Focused tests | Minimal validation command |
|---|---|---|---|---|---|
| Change stock daily-bars discovery or TDX fallback | [Pipeline overview](pipeline/overview.md#7b-stock-daily-bars-fallback-and-tdx-offline-provider) | `apps/pipeline/src/invest_pipeline/stock_daily_bars.py`; `apps/pipeline/src/invest_pipeline/assets.py`; `apps/pipeline/src/invest_pipeline/adapters/tdx_offline/stock_adapter.py` | `stock_daily_bars_by_date`; `TdxOfflineStockProvider`; `MARKET_TO_EXCHANGE`; `map_tdx_daily_bars` | `tests/unit/test_stock_daily_bars_tdx_fallback.py`; `test_tdx_offline_stock_provider.py`; `test_stock_assets_wiring.py` | `cd apps/pipeline && uv run pytest -q tests/unit/test_stock_daily_bars_tdx_fallback.py tests/unit/test_tdx_offline_stock_provider.py tests/unit/test_stock_assets_wiring.py` |
| Add or change provider declarations and runtime eligibility | [Pipeline overview](pipeline/overview.md#7-provider-catalog) | `apps/pipeline/src/invest_pipeline/provider_catalog.py`; `provider_factory.py`; `credentials.py` | `ProviderDeclaration`; `lookup_provider`; `KNOWN_PROVIDER_KEYS`; `CredentialStore`; `runtime_supported_provider_keys` | `tests/unit/test_provider_catalog.py`; `test_provider_factory_runtime.py`; `test_credentials.py` | `cd apps/pipeline && uv run pytest -q tests/unit/test_provider_catalog.py tests/unit/test_provider_factory_runtime.py tests/unit/test_credentials.py` |
| Change canonical exchange or stock/ETF mapping rules | [Architecture overview](architecture/overview.md#4-adapter-boundary) | `packages/domain/src/invest_domain/shared/values.py`; `apps/pipeline/src/invest_pipeline/adapters/tushare/mapper.py` | `Exchange`; `_exchange` | `packages/domain/tests/test_instrument.py`; `apps/pipeline/tests/unit/test_tushare_stock.py` | `make test-domain && cd apps/pipeline && uv run pytest -q tests/unit/test_tushare_stock.py` |
| Rebuild a research `ContextProjection` from bundle + snapshots | [Pipeline overview](pipeline/overview.md#5h-research-context-projection-loader-adr-0012--stage-4b-phase-3) | `apps/pipeline/src/invest_pipeline/research_context_projection.py`; `packages/domain/src/invest_domain/research/evidence_bundle.py` | `load_context_projection`; `ContextProjectionLoadError`; `build_projection`; `ResearchEvidenceBundle` | `apps/pipeline/tests/unit/test_research_context_projection.py`; `packages/domain/tests/test_research_evidence_bundle.py` | `cd apps/pipeline && uv run pytest -q tests/unit/test_research_context_projection.py` |
| Change the versioned A-share price-limit policy or evaluate a limit | [Domain overview](domain/overview.md); [Pipeline overview](pipeline/overview.md#5i-stage-4c-stock-price-limits-etl-service) | `packages/domain/src/invest_domain/market_data/price_limits.py`; `apps/pipeline/src/invest_pipeline/stock_price_limits.py`; `apps/pipeline/src/invest_pipeline/adapters/fixture_dev/price_limits.py` | `PriceLimitPolicy`; `PriceLimitRegime`; `Board`; `ListingStatus`; `PriceLimitInput`; `PriceLimitResult`; `KnownPriceLimit`; `UnlimitedPriceLimit`; `UnknownPriceLimit`; `DEFAULT_PRICE_LIMIT_REGIMES` | `packages/domain/tests/test_price_limits.py`; `apps/pipeline/tests/unit/test_stock_price_limits_service.py`; `tests/unit/test_fixture_dev_price_limits.py`; `tests/storage/test_stock_price_limits_model.py`; `tests/storage/integration/test_stock_price_limit_repository.py` | `make test-domain && cd apps/pipeline && uv run pytest -q tests/unit/test_stock_price_limits_service.py tests/unit/test_fixture_dev_price_limits.py` |
| Publish a Market Breadth v2 / Limit Sentiment snapshot | [Pipeline overview](pipeline/overview.md#5j-stage-4c-market-breadth-v2--limit-sentiment-publish-services) | `apps/pipeline/src/invest_pipeline/market_breadth_service.py`; `apps/pipeline/src/invest_pipeline/limit_sentiment_service.py`; `packages/domain/src/invest_domain/analytics/{market_breadth,limit_sentiment}.py` | `calculate_and_publish_market_breadth_v2`; `calculate_and_publish_limit_sentiment`; `MarketBreadthInput`; `LimitSentimentInput`; `build_market_breadth_v2`; `build_limit_sentiment`; `StockUniverseEmptyError`; `MarketBreadthInsufficientDataError` | `apps/pipeline/tests/unit/test_market_breadth_service.py`; `test_market_breadth_assets.py`; `test_limit_sentiment_service.py`; `test_stage4c_seeded_replay.py`; `test_tushare_tdx_consistency_golden.py`; `packages/domain/tests/test_market_breadth.py`; `tests/storage/integration/test_limit_sentiment_service.py` | `make test-domain && cd apps/pipeline && uv run pytest -q tests/unit/test_market_breadth_service.py tests/unit/test_limit_sentiment_service.py tests/unit/test_stage4c_seeded_replay.py` |
| Add or change the Provider–Engine–Event seam (registry, engine, publishability gate) | [Provider–Engine–Event seam](pipeline/provider-engine-event.md); [Architecture overview](architecture/overview.md#5-architecture-decision-records) | `apps/pipeline/src/invest_pipeline/provider_runtime_registry.py`; `stock_daily_bars_engine.py`; `stock_daily_bars_application.py`; `provider_health.py`; `provider_quality.py` | `ProviderRuntimeRegistry`; `ResolvedProvider`; `StockDailyBarsCommand`; `StockDailyBarsOutcome`; `ProviderHealthSnapshot`; `ProviderHealthStatus`; `decide_provider_publishability`; `decision_from_score` | `apps/pipeline/tests/unit/test_provider_runtime_registry.py`; `test_provider_runtime_registry_characterization.py`; `test_stock_daily_bars_engine.py`; `test_stock_daily_bars_application.py`; `test_provider_health.py`; `test_provider_quality.py` | `cd apps/pipeline && uv run pytest -q tests/unit/test_provider_runtime_registry.py tests/unit/test_stock_daily_bars_engine.py tests/unit/test_stock_daily_bars_application.py tests/unit/test_provider_health.py tests/unit/test_provider_quality.py` |
| Change stock price-limits storage / migrations | [Storage overview](storage/overview.md); [Migrations overview](migrations/overview.md) | `packages/storage/src/invest_storage/repositories.py`; `models.py`; `unit_of_work.py`; `apps/migrations/migrations/versions/20260812_0018_stock_price_limits.py` | `SqlAlchemyStockPriceLimitRepository`; `StockPriceLimitRow`; `NewPriceLimit`; `StoredPriceLimit`; `uow.stock_price_limits` | `tests/storage/test_stock_price_limits_model.py`; `tests/storage/integration/test_stock_price_limit_repository.py`; `tests/migrations/test_stock_price_limits_migration_roundtrip.py`; `apps/pipeline/tests/unit/test_stock_price_limits_service.py` | `cd apps/pipeline && uv run pytest -q tests/unit/test_stock_price_limits_service.py && make test-storage && make test-migrations` |
| Validate a WorkBuddy daily-report triplet or import it into the immutable governance archive | [Pipeline overview §5m](pipeline/overview.md#5m-workbuddy-daily-report-governance-m0--m1--m2-atomic-slices) | `apps/pipeline/src/invest_pipeline/workbuddy_reports/validator.py`; `apps/pipeline/src/invest_pipeline/workbuddy_reports/archive.py`; `apps/pipeline/src/invest_pipeline/workbuddy_reports/__main__.py` | `validate_triplet`; `discover_triplet`; `SUPPORTED_RULES_VERSION`; `TOLERANCE`; `archive_run`; `ImportOutcome.exit_code`; `_LATEST_POINTER_LOCK_FILENAME` | `apps/pipeline/tests/unit/test_workbuddy_reports_validator.py`; `test_workbuddy_reports_archive.py` | `cd apps/pipeline && uv run pytest -q tests/unit/test_workbuddy_reports_validator.py tests/unit/test_workbuddy_reports_archive.py` |
| Parse or archive a WorkBuddy candidate intake payload (production rules 2.0.0 / legacy 1.1.1 / 1.1.2 extraction) | [Pipeline overview §5n](pipeline/overview.md#5n-workbuddy-candidate-intake-m0-contract-aligned-slice) | `apps/pipeline/src/invest_pipeline/workbuddy_candidates/__init__.py`; `apps/pipeline/src/invest_pipeline/workbuddy_candidates/archive.py`; `apps/pipeline/src/invest_pipeline/workbuddy_candidates/projection.py` | `parse_candidates_payload`; `extract_legacy_candidates`; `CandidateIntakeResult`; `archive_candidates`; `ArchiveOutcome`; `project_candidates`; `ProjectionResult` | `apps/pipeline/tests/unit/test_workbuddy_candidates.py`; `test_workbuddy_candidates_archive.py`; `test_workbuddy_candidates_projection.py` | `cd apps/pipeline && uv run pytest -q tests/unit/test_workbuddy_candidates.py tests/unit/test_workbuddy_candidates_archive.py tests/unit/test_workbuddy_candidates_projection.py` |
| Bridge a WorkBuddy `candidates.json` archive into External Workflow Run / Artifact / Observation rows | [Pipeline overview §5k](pipeline/overview.md#5k-stage-4d-external-integration-workbench-bridge-ingest--shared-directory-gateway) | `apps/pipeline/src/invest_pipeline/integrations/bridge_ingestor.py`; `apps/pipeline/src/invest_pipeline/integrations/workbuddy_shared_directory.py`; `apps/pipeline/src/invest_pipeline/integrations/admission.py` | `import_archived_candidate_run`; `BridgeImportResult`; `SharedDirectoryWorkBuddyGateway`; `SharedDirectoryImport`; `ObservationAdmissionService` | `tests/pipeline/test_bridge_ingestor.py`; `tests/pipeline/test_workbuddy_shared_directory.py`; `apps/pipeline/tests/unit/test_observation_admission.py` | `cd apps/pipeline && uv run pytest -q tests/unit/test_observation_admission.py ../../tests/pipeline/test_bridge_ingestor.py ../../tests/pipeline/test_workbuddy_shared_directory.py` |
| Read external-workflow integration data through the read-only Stage 4D endpoints | [API overview §1](api/overview.md#1-modules), [§2](api/overview.md#2-routing-surface) | `apps/api/src/invest_api/routers/external_workflows.py`; `routers/integration_health.py`; `routers/opportunity_radar.py` | `list_external_workflows`; `get_external_workflow`; `list_external_artifacts`; `list_external_observations`; `get_integration_health`; `preview_artifact`; `list_opportunity_radar` | `apps/api/tests/test_external_workflow_service.py`; `test_admission_endpoints.py` | `cd apps/api && uv run pytest -q tests/test_external_workflow_service.py tests/test_admission_endpoints.py` |
| Issue or audit a gated `AdmissionDecision` for an external observation | [API overview §4 admission](api/overview.md#stage-4d-external-workflow-opportunity-radar-admission-evidence-link-endpoints) | `apps/api/src/invest_api/routers/admission.py`; `apps/api/src/invest_api/application/admission.py`; `apps/api/src/invest_api/config.py` | `ObservationAdmissionCommandService`; `decide`; `evaluate_admission`; `stage4d_admission_commands_enabled` | `apps/api/tests/test_admission_endpoints.py` | `cd apps/api && uv run pytest -q tests/test_admission_endpoints.py` |
| Link an admitted external observation to a Research Case as immutable evidence | [API overview §4 research-evidence](api/overview.md#stage-4d-external-workflow-opportunity-radar-admission-evidence-link-endpoints) | `apps/api/src/invest_api/routers/research_external_evidence.py`; `apps/api/src/invest_api/application/research_external_evidence.py` | `ResearchExternalEvidenceService`; `link`; `observation_to_evidence_item` | `apps/api/tests/test_research_external_evidence.py` | `cd apps/api && uv run pytest -q tests/test_research_external_evidence.py` |
| Create a Research Case from an admitted observation and bind its Evidence | [API overview §4 research-evidence](api/overview.md#stage-4d-external-workflow-opportunity-radar-admission-evidence-link-endpoints) | `apps/api/src/invest_api/routers/research_external_evidence.py`; `apps/api/src/invest_api/application/research_external_evidence.py` | `ResearchExternalEvidenceService`; `create_case_and_link` | `apps/api/tests/test_research_external_evidence.py` | `cd apps/api && uv run pytest -q tests/test_research_external_evidence.py` |

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

Stage 4C (Core Data Layer Integration) closes out the
`docs/plan/invest-infra-stage4c-core-data-layer-integration-plan.md` MVP:
the pure-domain side carves
[`packages/domain/src/invest_domain/market_data/price_limits.py`](../packages/domain/src/invest_domain/market_data/price_limits.py)
(`Board` / `ListingStatus` / `PriceLimitRegime` /
`PriceLimitPolicy.evaluate` returning one of
`KnownPriceLimit` / `UnlimitedPriceLimit` / `UnknownPriceLimit` over
the explicit A-share price-limit rules — main ±10% with ±5% for
`risk_warning`, GEM/STAR ±20%, BSE ±30%, plus the documented IPO
unlimited-session windows) and the two
`analytics.market_observations` builders
([`market_breadth.py`](../packages/domain/src/invest_domain/analytics/market_breadth.py)
v1 + v2 with `above_ma60_ratio` / `new_high_ratio` / `new_low_ratio`
additive fields and
[`limit_sentiment.py`](../packages/domain/src/invest_domain/analytics/limit_sentiment.py)
v1 `limit_up_ratio` / `limit_down_ratio` /
`limit_touch_unknown_ratio`). The pipeline side ships
[`stock_price_limits.py`](../apps/pipeline/src/invest_pipeline/stock_price_limits.py)
(`write_stock_price_limits_raw` + `upsert_stock_price_limits` over the
fixture-dev provider),
[`limit_sentiment_service.py`](../apps/pipeline/src/invest_pipeline/limit_sentiment_service.py)
and the v2-capable
[`market_breadth_service.calculate_and_publish_market_breadth_v2`](../apps/pipeline/src/invest_pipeline/market_breadth_service.py);
the fixture provider
[`adapters/fixture_dev/price_limits.py`](../apps/pipeline/src/invest_pipeline/adapters/fixture_dev/price_limits.py)
is **not** catalog-routed — `select_providers` for
`Dataset.STOCK_PRICE_LIMITS` still raises `NoEligibleProviderError`
because the slice intentionally freezes `STOCK_PRICE_LIMITS` /
`STOCK_MINUTE_BARS` / `STOCK_BLOCK_MEMBERSHIPS` / `TDX_GUI_ANALYSIS`
capabilities and `dataset_key`s without registering a runtime
provider. Storage gains
[`SqlAlchemyStockPriceLimitRepository`](../packages/storage/src/invest_storage/repositories.py)
(`upsert_many` under the ADR-0006 §3 revision algorithm with a
`UNIQUE (instrument_id, trade_date, revision, row_hash)` final guard)
and the `uow.stock_price_limits` UoW property; migration
`20260812_0018_stock_price_limits` adds `core.stock_price_limits`
(migration chain head is `20260812_0018`). The Stage 4C MVP Checkpoint
B acceptance ([`docs/validation/stage4c-mvp-checkpoint-b-acceptance.md`](../docs/validation/stage4c-mvp-checkpoint-b-acceptance.md))
records `1887 passed` pipeline tests, the full
`upgrade → downgrade → upgrade` migration round-trip, the seeded
replay determinism and the Tushare/TDX cross-source consistency
golden test. The TDX offline slice 2 binds the pair-request keys
to the qualified `(market, symbol)` universe
([`apps/pipeline/src/invest_pipeline/adapters/tdx_offline/stock_adapter.py`](../apps/pipeline/src/invest_pipeline/adapters/tdx_offline/stock_adapter.py))
and derives `prev_close` from the previous valid trading-day close
inside the per-security sequence, so a re-run can never smuggle a
`None` pair key into `raw.provider_requests` and never shares
`prev_close` across two symbols read in the same run.

ADR-0013 (Provider–Engine–Event Phase 0) introduces the seam that
the future Engine / Event layers will own without breaking the
catalog / factory / Dagster responsibilities. The implementation
lands three thin modules:

- [`provider_runtime_registry.py`](../apps/pipeline/src/invest_pipeline/provider_runtime_registry.py)
  is the typed resolver over `provider_catalog` +
  `provider_factory`. `ProviderRuntimeRegistry.resolve_etf(settings)`
  and `resolve_stock(settings)` look the request's `provider_key`
  up in the catalog and delegate construction to
  `build_provider` / `build_stock_provider`, returning a frozen
  `ResolvedProvider` (provider + declaration + canonical
  `provider_key`); `describe(provider_key)` is the catalog lookup.
  The registry never adds a fallback chain, never owns a session,
  never reaches the network, and never re-declares the
  `KNOWN_PROVIDER_KEYS` tuple (GOV-04 — the factory's helper is
  the single source of truth).
- [`stock_daily_bars_engine.py`](../apps/pipeline/src/invest_pipeline/stock_daily_bars_engine.py)
  freezes the `StockDailyBarsCommand` / `StockDailyBarsOutcome`
  dataclasses; the run status string vocabulary is the canonical
  `invest_domain.pipeline.PipelineRunStatus`. `error_summary`
  string values are scrubbed against an internal
  `_ERROR_SECRET_MARKERS` tuple so an api_key / token / password
  fragment can never leak through the engine outcome.
- [`stock_daily_bars_application.py`](../apps/pipeline/src/invest_pipeline/stock_daily_bars_application.py)
  is the application-layer Engine that wires the
  `ProviderResolver` / `RawIngestor` / `CorePublisher` / optional
  `HealthPreflight` protocols around the engine. The health
  preflight returns a `ProviderHealthSnapshot` (see
  [`provider_health.py`](../apps/pipeline/src/invest_pipeline/provider_health.py));
  a `DISABLED` / `UNKNOWN` / `STALE` snapshot downgrades the
  outcome to `_UNHEALTHY_PREFLIGHT_SUMMARY` rather than letting
  the resolver spin up a disabled provider. The fail-closed
  `ProviderPublishDecision` gate
  ([`provider_quality.decide_provider_publishability`](../apps/pipeline/src/invest_pipeline/provider_quality.py))
  is the audit-grade publishability contract the future
  asset-level consumer will read; today no asset wires it in,
  but the canonical entry point is locked. See the dedicated
  [Provider–Engine–Event page](pipeline/provider-engine-event.md)
  for the relationship between catalog / factory / registry /
  engine / quality gate.

WorkBuddy daily-report governance ships in two independently-evolving
pipeline modules under
[`apps/pipeline/src/invest_pipeline/workbuddy_reports/`](../apps/pipeline/src/invest_pipeline/workbuddy_reports/).
The pair is intentionally split between **legacy report audit** and
**candidate intake** per the M0 contract re-scoping
([`docs/implementation/WORKBUDDY-CANDIDATE-INTAKE-M0-CONTRACT.md`](../docs/implementation/WORKBUDDY-CANDIDATE-INTAKE-M0-CONTRACT.md)):

- The [`workbuddy_reports`](../apps/pipeline/src/invest_pipeline/workbuddy_reports/) package
  freezes the **legacy M0 governance surface** for the historical
  WorkBuddy triplet
  (`sector_result*.json` / `板块强度排行榜*.md` /
  `sector_quality*.json`, with the legacy
  `result*.json` / `report*.md` / `quality_report*.json` aliases
  still accepted for backward compatibility with the 2026-08-13 sample).
  [`validator.validate_triplet`](../apps/pipeline/src/invest_pipeline/workbuddy_reports/validator.py)
  is the public entry point: it normalises the
  `result.status` → `producer_status` alias with a warning, applies
  the explicit `report_rules_version` compat set
  `{1.1.1, 1.1.2}` (the M0 contract freezes
  `SUPPORTED_RULES_VERSION="1.1.2"` and any 1.1.x / 1.0.x / 2.0.x
  outside the compat set raises `unsupported_version` → exit 4),
  enforces strict `YYYY-MM-DD` `trade_date` and safe single-path-segment
  `workflow_run_id` (so the archive layout
  `<root>/runs/<trade_date>/<workflow_run_id>/` cannot be smuggled
  through), enforces cross-file identity on the canonical identity
  fields, runs the hard-validation matrix
  (stages / applied_rules / scores / ranking / candidates / markdown
  consistency), and finally classifies the verdict into
  `accepted` / `partial` / `rejected` (`rejected > partial > accepted`).
  [`archive.archive_run`](../apps/pipeline/src/invest_pipeline/workbuddy_reports/archive.py)
  builds the immutable governance archive under
  `<root>/runs/<trade_date>/<workflow_run_id>/` (three-layer evidence
  bundle: original basenames + `governed-quality-report.json` +
  `manifest.json` re-hashed on disk), then atomically updates
  `<root>/latest-accepted.json` only when the verdict is `accepted`;
  the pointer writer is serialized with `fcntl.flock` on
  `<root>/.latest-accepted.lock` and refuses to overwrite an older
  `(trade_date, finished_at, workflow_run_id)` triple. Both surfaces
  are exposed through
  [`python -m invest_pipeline.workbuddy_reports {validate,import}`](../apps/pipeline/src/invest_pipeline/workbuddy_reports/__main__.py),
  which emits a single JSON object on stdout and exits `0` (`accepted`)
  / `2` (`partial`) / `3` (validation-level rejection) /
  `4` (input / argument / unsupported-version error) /
  `5` (archive conflict or I/O failure). The pipeline ships no
  Make target for either subcommand today; see [§8 Backlog](#8-backlog).
- The [`workbuddy_candidates`](../apps/pipeline/src/invest_pipeline/workbuddy_candidates/) package
  implements the **candidate intake** surface that supersedes
  report-audit as the WorkBuddy entry contract (production rules
  `2.0.0`). [`parse_candidates_payload`](../apps/pipeline/src/invest_pipeline/workbuddy_candidates/__init__.py)
  is a pure, database-free parser: it requires
  `workflow_run_id` / `trade_date` / `strategy_id` / `status` /
  `candidates` at the batch level, refuses an unsafe
  `workflow_run_id` or a non-calendar `trade_date`, and **isolates
  bad items at item level** (a missing `symbol` or `reason` adds a
  finding and rejects only that item, never the whole batch).
  [`extract_legacy_candidates`](../apps/pipeline/src/invest_pipeline/workbuddy_candidates/__init__.py)
  is the adapter for the historical 1.1.1 / 1.1.2 triplet — it pulls
  `candidates` out of the legacy `result.json` without requiring the
  scoring / ranking / source-refs surface to be present, so the
  legacy `2026-08-13` real sample can populate the candidate pool
  without first passing the strict report audit.
  [`archive.archive_candidates`](../apps/pipeline/src/invest_pipeline/workbuddy_candidates/archive.py)
  writes the immutable `runs/<trade_date>/<workflow_run_id>/{candidates.json,manifest.json}`
  archive (idempotent on byte-identical re-import, conflict when the
  same identity carries different bytes — the existing archive is
  never overwritten), and
  [`projection.project_candidates`](../apps/pipeline/src/invest_pipeline/workbuddy_candidates/projection.py)
  resolves symbols through an injected `Resolver` callable,
  de-duplicates on `(trade_date, strategy_id, normalized_symbol)`,
  and tags `unresolved` items with `status="needs_symbol_resolution"`
  so the downstream research pipeline can re-attempt resolution
  without re-reading WorkBuddy artefacts. Both surfaces are pure
  helpers — no Dagster sensor, no API/Web surface, no DB write — so
  future ingestion wires can compose them without rebuilding the
  contract.

Both modules are independent of the Provider–Engine–Event seam and
the asset graph: they neither write to PostgreSQL nor participate in
`personal_etf_daily_job`. They are exposed as Python libraries plus
the `workbuddy_reports` CLI; the candidate-intake CLI is **not**
wired today and is the next integration step listed in [§8 Backlog](#8-backlog).

The Stage 4D commit `5603b87` lands the **External Integration
Workbench** that bridges WorkBuddy into the Research lifecycle:

- [`apps/pipeline/src/invest_pipeline/integrations/bridge_ingestor.py`](../apps/pipeline/src/invest_pipeline/integrations/bridge_ingestor.py)
  defines `import_archived_candidate_run(archive_root, *, trade_date,
  workflow_run_id, uow, resolver=None)`. It reads only the
  `candidates.json` + `manifest.json` pair from an already-archived
  WorkBuddy run (never executes producer code, never accepts a path
  from the payload) and turns the archive into one immutable
  `ExternalWorkflowRun`, one `ExternalArtifact`, and a tuple of
  `ExternalObservation` rows — one per WorkBuddy candidate, tagged
  `pending_validation` for resolved symbols or `needs_symbol_resolution`
  for unresolved symbols. Re-importing an unchanged archive returns the
  existing domain objects (`BridgeImportResult.idempotent=True`);
  symbol-resolution exceptions are isolated to a single item.
- [`apps/pipeline/src/invest_pipeline/integrations/workbuddy_shared_directory.py`](../apps/pipeline/src/invest_pipeline/integrations/workbuddy_shared_directory.py)
  defines `SharedDirectoryWorkBuddyGateway(bridge_root)` — the
  filesystem side of the bridge. It discovers `<bridge_root>/workbuddy/results/*.ready/`
  directories in deterministic order, atomically claims them via
  `os.replace` into `workbuddy/processing/`, archives the payload
  through `workbuddy_candidates.archive.archive_candidates`, then calls
  `import_archived_candidate_run` against the new archive and moves
  the package into `workbuddy/archive/` or `workbuddy/failed/`
  depending on outcome. Failed packages are never silently dropped —
  they land in `workbuddy/failed/<workflow_run_id>/` with the error
  string on the `SharedDirectoryImport.error` slot.
- [`apps/pipeline/src/invest_pipeline/integrations/admission.py`](../apps/pipeline/src/invest_pipeline/integrations/admission.py)
  ships the pipeline-side
  `ObservationAdmissionService.decide(observation_id, verification)`
  helper. The HTTP route in
  [`apps/api/src/invest_api/routers/admission.py`](../apps/api/src/invest_api/routers/admission.py)
  wraps the same `evaluate_admission` rule with a request-scoped
  idempotency key and a
  `stage4d_admission_commands_enabled=False` gate. The read-only
  flow (radar + workflow + artifact previews) is the Stage 4D baseline
  surface and is always available; the write command is opt-in via the
  Settings flag.
- The Bridge writes through the storage UoW —
  [`uow.external_workflow_runs`](../packages/storage/src/invest_storage/unit_of_work.py),
  [`uow.external_artifacts`](../packages/storage/src/invest_storage/unit_of_work.py),
  and [`uow.external_observations`](../packages/storage/src/invest_storage/unit_of_work.py)
  — and the migration chain
  ([`20260814_0019_external_integration`](../apps/migrations/migrations/versions/20260814_0019_external_integration.py)
  + [`20260814_0020_research_external_evidence`](../apps/migrations/migrations/versions/20260814_0020_research_external_evidence.py))
  adds the matching `integration` PostgreSQL schema. The cross-system
  link from admitted observation to Research Case lives in
  [`apps/api/src/invest_api/routers/research_external_evidence.py`](../apps/api/src/invest_api/routers/research_external_evidence.py)
  and is the bridge between the WorkBuddy intake and the
  ADR-0012 evidence-driven Research lifecycle.

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
  [`GET /api/v1/research-cases/{case_id}/workspace`](api/overview.md);
- `/opportunity-radar` — Stage 4D
  [`OpportunityRadarPage`](../apps/web/src/pages/OpportunityRadarPage.tsx)
  reads the most recent external observations through
  [`GET /api/v1/opportunity-radar`](api/overview.md#2-routing-surface)
  and surfaces them by `admission_status` filter (`待验证` /
  `已交叉验证` / `已准入` / `已拒绝` / `冲突`). Every row is still
  an external observation, not an evidence item — admission is the
  responsibility of the gated command endpoint.
- `/automation` — Stage 4D
  [`AutomationCenterPage`](../apps/web/src/pages/AutomationCenterPage.tsx)
  reads `GET /api/v1/external-workflows` (paginated) plus per-run
  artifact counts through
  `GET /api/v1/external-workflows/{run_id}/artifacts`. The page is a
  read-only dashboard over WorkBuddy runs; no buttons trigger a
  task.
- The `/dashboard` page now hosts an
  [`IntegrationHealthPanel`](../apps/web/src/features/dashboard/IntegrationHealthPanel.tsx)
  widget that polls
  [`GET /api/v1/integration/health`](api/overview.md#2-routing-surface)
  so operators see external-workflow producer / intake status next to
  the freshness and candidate-pool panels.

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

The Playwright suite includes
[`apps/web/e2e/stage4d-workbench.e2e.ts`](../apps/web/e2e/stage4d-workbench.e2e.ts)
— it boots the Stage 4D `/opportunity-radar` and `/automation`
pages against a fixture-backed API and asserts the radar status
filter and the workflow card shape render end-to-end.

The default `API_BASE` falls back to `http://${window.location.hostname}:8000`
when `VITE_API_BASE_URL` is unset, so the workbench auto-resolves the LAN
address of the API container without a rebuild — see
[`apps/web/src/api/client.ts`](../apps/web/src/api/client.ts).

### 7b. Stage 4D External Integration Workbench

Stage 4D adds three read-only web surfaces and two gated backend
commands: admission decision and Research-Case evidence linking. The web pages are intentionally
read-only — the bridge that turns WorkBuddy archives into
`ExternalObservation` rows lives in the pipeline layer and writes
through the storage UoW; the browser never imports a candidate
archive or runs a workbuddy pipeline job.

| Page | Source entry point | API contract | Behaviour |
|------|-------------------|-------------|-----------|
| `/opportunity-radar` | [`apps/web/src/pages/OpportunityRadarPage.tsx`](../apps/web/src/pages/OpportunityRadarPage.tsx) | `GET /api/v1/opportunity-radar?admission_status=…&limit=…&offset=…` | 60-second polling. Status filter (`待验证` / `已交叉验证` / `已准入` / `已拒绝` / `冲突`) re-fetches with `opportunityRadarQueryKey`; radar rows show symbol / status / `as_of` / producer / `observed_at`. |
| `/automation` | [`apps/web/src/pages/AutomationCenterPage.tsx`](../apps/web/src/pages/AutomationCenterPage.tsx) | `GET /api/v1/external-workflows?limit=…&offset=…` + `GET /api/v1/external-workflows/{run_id}/artifacts` | Lists recent external workflow runs; per-run card shows producer / schema / status pills / started_at / artifact count. |
| `/dashboard` (panel only) | [`apps/web/src/features/dashboard/IntegrationHealthPanel.tsx`](../apps/web/src/features/dashboard/IntegrationHealthPanel.tsx) | `GET /api/v1/integration/health` | Lightweight health banner showing `status` (`healthy` / `degraded`), `sample_size`, `producer_statuses`, `intake_statuses`. |

The admission-decision command lives at
`POST /api/v1/external-observations/{observation_id}/admission-decisions`
and is gated on `stage4d_admission_commands_enabled` — the
default-off flag is documented in
[API overview §5](api/overview.md#5-configuration). The web
workbench does not call this command yet; the operator-side flow
is wired through the API directly until the e2e contract is signed
off.

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
- **Stage 4C Dagster asset wiring.** The
  `stock_price_limits_raw` / `stock_price_limits` / `limit_sentiment_snapshot`
  / `market_breadth_v2_snapshot` Dagster assets are **not** registered
  in [`invest_pipeline.definitions.defs`](../apps/pipeline/src/invest_pipeline/definitions.py)
  yet — only the pure-domain contracts (`PriceLimitPolicy.evaluate`),
  the ETL / publish services
  ([`stock_price_limits.py`](../apps/pipeline/src/invest_pipeline/stock_price_limits.py) /
  [`limit_sentiment_service.py`](../apps/pipeline/src/invest_pipeline/limit_sentiment_service.py) /
  [`market_breadth_service.calculate_and_publish_market_breadth_v2`](../apps/pipeline/src/invest_pipeline/market_breadth_service.py))
  and the fixture provider land in this slice. The Stage 4C MVP
  Checkpoint B acceptance signs off on the deterministic contract
  suite (`test_stage4c_seeded_replay.py` +
  `test_tushare_tdx_consistency_golden.py`), not on the
  `personal_etf_daily_job`-aligned asset graph.
- **Stage 4C Stock Price-Limit catalog entry.**
  `Dataset.STOCK_PRICE_LIMITS` is frozen without a matching provider
  declaration; the only callable provider today is the
  fixture-only `FixtureDevStockPriceLimitsProvider`. A real-network
  provider declaration is intentionally deferred to a later Stage 4C
  phase so `select_providers(Dataset.STOCK_PRICE_LIMITS)` keeps
  raising `NoEligibleProviderError` rather than silently selecting a
  half-wired upstream.
- **Provider–Engine–Event Engine consumers.** The Phase 0 seam
  ([`ProviderRuntimeRegistry`](../apps/pipeline/src/invest_pipeline/provider_runtime_registry.py) +
  [`StockDailyBarsEngine`](../apps/pipeline/src/invest_pipeline/stock_daily_bars_engine.py) +
  [`StockDailyBarsApplication`](../apps/pipeline/src/invest_pipeline/stock_daily_bars_application.py))
  ships the typed entry points but does not yet wire an
  Engine-driven consumer into the asset graph. ADR-0013 §3 explicitly
  defers the Event Dispatcher until a second approved consumer is
  ready, so this slice intentionally has no dispatcher.
- **WorkBuddy CLI exposure / Make targets.** The
  [`workbuddy_reports`](../apps/pipeline/src/invest_pipeline/workbuddy_reports/__main__.py)
  CLI subcommands (`validate` / `import`) are library-only today:
  there is no `make workbuddy-validate` / `make workbuddy-import`
  target, no Dagster sensor, no API or Web surface. Promote to
  [`Makefile`](../Makefile) only after the operator-side acceptance
  checklist ([`docs/plan/invest-infra-workbuddy-daily-report-governance-mvp-plan-v1.0.md`](../docs/plan/invest-infra-workbuddy-daily-report-governance-mvp-plan-v1.0.md) §5 M3) signs off.
- **WorkBuddy candidate intake end-to-end.** The
  [`workbuddy_candidates`](../apps/pipeline/src/invest_pipeline/workbuddy_candidates/) surface ships
  parser / archive / projection helpers and the focused unit suite,
  but the production CLI (`python -m
  invest_pipeline.workbuddy_candidates …`) is not yet wired and no
  asset / schedule consumes
  `project_candidates`'s output. The candidate-pool writer and the
  Dagster sensor are explicitly deferred per
  [`docs/plan/invest-infra-workbuddy-daily-report-governance-mvp-plan-v1.0.md`](../docs/plan/invest-infra-workbuddy-daily-report-governance-mvp-plan-v1.0.md) §7.
- **Stage 4D unified investment workbench integration.** The MVP
  slice has landed in commit `5603b87` (the Bridge ingest, the
  External Workflow / Artifact / Observation read API, the
  Opportunity Radar, the Integration Health panel, the gated
  admission-decision command, and the Research-Case evidence link
  are wired end-to-end). The next backlog step is the operator-side
  acceptance checklist plus the production CLI
  `python -m invest_pipeline.integrations …` for the shared-directory
  gateway, both tracked in
  [`docs/plan/invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md`](../docs/plan/invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md)
  + the authoritative Stage 4D plan
  [`docs/plan/invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md`](../docs/plan/invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md).
