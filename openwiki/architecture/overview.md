---
type: Concept
title: Architecture overview
description: "Modular-monolith topology, layered rules, five PostgreSQL schemas (`raw` / `core` / `analytics` / `ops` / `integration`) and ADR index for invest-infra (including ADR-0011 CifangQuant Phase 1 first + second increments, the DC-2 ETF profile framework, the Stage 4A evidence / context separation, the architecture-governance convergence that moved ETF / candidate-pool / data-freshness / pipeline-runs / research queries behind application services, ADR-0012 that freezes the evidence-driven Research lifecycle boundary between Domain / Pipeline / Storage, the Stage 4B Market Intelligence foundation that adds the Stock Daily Bars pipeline, the Market Observation / Temperature / Breadth read surface, and the Research Evidence Bundle binding, the Stage 4C Core Data Layer Integration that adds the versioned price-limit policy, the stock price-limit persistence, Market Breadth v2 + Limit Sentiment publish services, and the four new Stage 4C dataset / capability identifiers, the Stage 4D External Integration Workbench (the new `integration` schema, the bridge ingest + shared-directory gateway under `apps/pipeline/integrations/`, the ExternalWorkflow / ExternalArtifact / ExternalObservation / ResearchExternalEvidence repositories, the gated observation-admission command, the read-only External Workflow / Opportunity Radar / Integration Health routers, and the Research-Case ↔ External-Observation evidence link), ADR-0013 that freezes the Provider–Engine–Event Phase 0 boundary — catalog is the Provider-declaration authority, factory/Registry is the only runtime entry point, Engine is a thin stock-daily-bars lifecycle orchestrator, Event Dispatcher is gated on two approved consumers — and the WorkBuddy governance split between the legacy M0/M1/M2 strict-report-audit (`workbuddy_reports`) and the M0 contract-aligned candidate-intake surface (`workbuddy_candidates`)). Explains why the codebase stays inside independent Python packages and how the layers interact."
resource: /openwiki/architecture/overview.md
tags: [architecture, layering, schemas, adr, cifang, tushare, etf-profile, research-context, research-lifecycle, governance, mcp, exposure, stage4b, stage4c, market-breadth, market-temperature, market-observations, evidence-bundle, hithink, provider-engine-event, price-limits, limit-sentiment, workbuddy, workbuddy-reports, workbuddy-candidates, stage4d, external-integration, integration-schema, observation-admission, opportunity-radar, bridge-ingestor]
---

# Architecture overview

`invest-infra` is a **modular monolith** that draws a hard line between
domain logic, persistence, ingest pipelines and read APIs. Each layer
runs in its own Python project (with its own `pyproject.toml` and
`uv.lock`) so a change to one layer cannot silently leak into another.

## 1. Topology

```
React Web ──HTTP/OpenAPI──> FastAPI API ──SQL──> PostgreSQL
                                      ↑
Dagster Pipeline ───────────────SQL───┘
```

The API and the Pipeline share `packages/domain` and `packages/storage`
inside one runtime image only when the developer chooses to; in CI each
project builds and tests independently. Production splits them: see the
[deployment notes](../testing-and-ops/overview.md#6-deployment-and-runtime).

Key invariants:

- **Python continues to own financial-data and computation work**, but
  the API and the pipeline do not share dependencies
  ([README §设计目标](../../README.md)).
- **Modular monolith first.** No microservices, Kafka, Redis or
  Kubernetes are introduced in v2 (ADR-0001).
- **PostgreSQL is the only persistence layer in v2** (ADR-0002).
- **Data sources are isolated through the Provider interface.** Domain
  and storage never import a Provider SDK (ADR-0003).
- **Every calculation records `run_id`, algorithm version and data
  timestamp** so any output is reproducible from raw batches.
- **The front-end only touches data via the OpenAPI surface** — it does
  not call Provider SDKs or write to the database.

## 2. Layers

Per [`/docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md):

### Domain (`packages/domain`)

Only entities, value objects, enums and ports. **MUST NOT** import
FastAPI, SQLAlchemy, Dagster or any Provider SDK. The package stays
deterministic — no clock reads, no `os.environ`, no I/O. See
[Domain overview](../domain/overview.md).

### Application

Use-case orchestration lives in
`apps/pipeline/src/invest_pipeline/*_service.py` and the FastAPI
routers. Application code calls **ports**, never concrete SDKs, and the
SQLAlchemy `UnitOfWork` mediates every transaction.

### Infrastructure

- `packages/storage/src/invest_storage/{models,repositories,unit_of_work,database}.py`
  — SQLAlchemy 2 ORM, repositories and the `UnitOfWork`.
- `apps/pipeline/src/invest_pipeline/adapters/<provider_key>/` — Provider
  adapters. Each adapter is the only place a vendor SDK (or fixture in
  the case of `fixture_dev`) is allowed. See [Adapter boundary](#4-adapter-boundary).
- `apps/pipeline/src/invest_pipeline/{etf_*,input_snapshot}.py` — ETL
  service modules that the Dagster assets wrap. See
  [Pipeline overview](../pipeline/overview.md).

### Entrypoints

- `apps/api/src/invest_api/{main,routers}.py` — FastAPI. Validates inputs,
  calls repositories through the storage `UnitOfWork`, translates results
  to Pydantic shapes. See [API overview](../api/overview.md).
- `apps/pipeline/src/invest_pipeline/{assets,definitions}.py` — Dagster
  `@dg.asset`s and the `dg.Definitions` registration. See
  [Pipeline overview](../pipeline/overview.md).
- `apps/migrations/migrations/versions/*.py` — Alembic migrations. See
  [Migrations overview](../migrations/overview.md).

## 3. The five PostgreSQL schemas

| Schema | Owner | Purpose |
|--------|-------|---------|
| `raw` | Pipeline | Provider evidence — `provider_requests`, `provider_attempts`, `provider_batches`. |
| `core` | Pipeline + API | Normalised business objects — `core.instruments`, `core.daily_bars`, `core.latest_daily_bars` view. |
| `analytics` | Pipeline + API | Reusable inputs and computed results — `analytics.input_snapshots`, `analytics.candidate_pool_runs`, `analytics.candidate_pool_items`. |
| `ops` | Pipeline | Pipeline-level audit — `ops.pipeline_runs` (replaces the retired `app.pipeline_runs`). |
| `integration` | Pipeline + API (Stage 4D) | External workflow data — `integration.external_workflow_runs`, `integration.external_artifacts`, `integration.external_observations`. Read by the new External Workflow / Opportunity Radar / Integration Health routers; written only by `apps/pipeline/integrations/{bridge_ingestor,workbuddy_shared_directory}.py` and the gated observation-admission command. |

The legacy `app` schema is forbidden in production paths; the
checker rejects `schema="app"` literals.

## 4. Adapter boundary

ADR-0003 (accepted via PR-04) fixes the rule for **every** Provider
adapter:

- Adapter code lives in `apps/pipeline/src/invest_pipeline/adapters/<provider_key>/`.
- An adapter does **not** receive a SQLAlchemy `Session`, does **not**
  commit transactions and does **not** insert into `raw.provider_batches`.
- The pipeline-side application service, not the adapter, owns the
  three-layer evidence write inside a single `UnitOfWork`.
- **Four** runtime ETF adapter packages ship today: `fixture_dev`
  (deterministic fixture data — see [Pipeline overview §4](../pipeline/overview.md#4-fixture_dev-adapter)),
  `cifang`, `akshare` and `tushare`. `fixture_dev` is enabled by
  default; the real-data adapters require explicit enablement and
  preserve the upstream provider key in their output. See
  [Pipeline overview §5](../pipeline/overview.md#5-cifang-adapter-adr-0011-phase-1-first--second-increments),
  [§5b](../pipeline/overview.md#5b-akshare-adapter-pr-02) and
  [§5d](../pipeline/overview.md#5d-tushare-pro-adapter-phase-1-bounded-increment).
  The QuickTiny and RssCast packages are separate research-only MCP
  transports and do not implement the ETF daily-bars port. The
  Tushare adapter additionally exposes a `StockTushareProvider`
  branch (`apps/pipeline/src/invest_pipeline/adapters/tushare/stock_adapter.py`)
  for the Stage 4B A-share `stock_daily_bars` /
  `stock_daily_bars_by_date` dataset keys, plus an opt-in
  `tdx_offline` package that reads the local TDX `vipdoc` tree of
  pre-fetched `.day` files for fixture-style A-share offline batches;
  the Stage 4B stock by-date fallback selects it at the application
  layer, not through the generic ETF factory. The `provider_catalog` registry also carries a
  reserved, disabled-by-default `hithink` declaration
  (see [`tasks/hithink-reserved-provider-plan.md`](../../tasks/hithink-reserved-provider-plan.md))
  whose credential is read lazily through the centralized
  `CredentialStore` against the `hithink.api_key` filename but
  which is intentionally not wired into the runtime factory (the
  catalog pins `has_runtime_factory_adapter=False` so the runtime
  factory's `KNOWN_PROVIDER_KEYS` helper excludes it).

The ADR-0013 Provider–Engine–Event Phase 0 seam (see
[Pipeline overview — Provider–Engine–Event seam](../pipeline/provider-engine-event.md))
sits **on top of** the catalog + factory + routing boundary: the
`ProviderRuntimeRegistry.resolve_etf` /
`ProviderRuntimeRegistry.resolve_stock` helpers are stateless
adapters that delegate to `provider_factory.build_provider` /
`build_stock_provider`, so they preserve every fail-closed branch
the factory already implements (`UnknownProviderError` for
catalog-only entries `tdx_offline` / `hithink` / `rsscast` /
`quicktiny_mcp`, `RealProviderRequiresExplicitEnablementError`
when a real provider is disabled, `ProviderAuthenticationError`
when its credential is missing). The Engine wraps a provider
resolved through the registry and calls into the existing
`stock_daily_bars.py` ETL service; the Event Dispatcher is
**not** implemented yet (ADR-0013 §3 only opens it once two
approved, testable consumers exist).

The boundary is enforced two ways: the
[`scripts/check_architecture.py`](../../scripts/check_architecture.py)
import-graph scan and a Testcontainers-backed integration suite.

The WorkBuddy governance split is implemented as two independent
pipeline packages —
[`apps/pipeline/src/invest_pipeline/workbuddy_reports/`](../../apps/pipeline/src/invest_pipeline/workbuddy_reports/)
and
[`apps/pipeline/src/invest_pipeline/workbuddy_candidates/`](../../apps/pipeline/src/invest_pipeline/workbuddy_candidates/).
Both packages stay below the Provider / Domain / Storage boundary:
neither imports `packages/storage`, neither writes to PostgreSQL,
neither participates in the asset graph. The contract re-scoping
([`docs/implementation/WORKBUDDY-CANDIDATE-INTAKE-M0-CONTRACT.md`](../../docs/implementation/WORKBUDDY-CANDIDATE-INTAKE-M0-CONTRACT.md))
explicitly separates the **legacy strict-report-audit**
(`workbuddy_reports` — `validate_triplet` + immutable archive +
`latest-accepted.json` pointer) from the **candidate-intake**
surface (`workbuddy_candidates` — `parse_candidates_payload` /
`extract_legacy_candidates` / `archive_candidates` /
`project_candidates`) so a candidate intake never blocks on a
report-audit verdict. The two packages share the same path-safety
contract — strict `YYYY-MM-DD` `trade_date` plus
`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` `workflow_run_id` — so a
downstream ingest step can compose both archives without
inventing a new identity format. See
[Pipeline overview §5m](../pipeline/overview.md#5m-workbuddy-daily-report-governance-m0--m1--m2-atomic-slices) /
[§5n](../pipeline/overview.md#5n-workbuddy-candidate-intake-m0-contract-aligned-slice)
for the slice-by-slice contract and the focused test layout.

## 5. Architecture decision records

All thirteen ADRs are in [`/docs/adr/`](../../docs/adr/):

- [ADR-0001 — Greenfield modular monolith](../../docs/adr/0001-greenfield-modular-monolith.md)
- [ADR-0002 — Postgres-first](../../docs/adr/0002-postgres-first.md)
- [ADR-0003 — Provider selection and adapter boundary](../../docs/adr/0003-provider-selection-and-adapter-boundary.md) *(accepted in PR-04)*
- [ADR-0004 — ETF market calendar / timezone / range](../../docs/adr/0004-etf-market-calendar-timezone-range.md) (SSE / SZSE, Asia/Shanghai, versioned calendar)
- [ADR-0005 — Daily-bar adjustment contract](../../docs/adr/0005-daily-bar-adjustment-contract.md) (`adjustment='none'` only)
- [ADR-0006 — Daily-bar revision / latest policy](../../docs/adr/0006-daily-bar-revision-latest-policy.md) (revision semantics + the `core.latest_daily_bars` view)
- [ADR-0007 — Input snapshot binding hash](../../docs/adr/0007-input-snapshot-binding-hash.md) (SHA-256 over sorted UUID bytes)
- [ADR-0008 — Candidate pool state machine](../../docs/adr/0008-candidate-pool-state-machine.md) (`calculated → validated → published|rejected`)
- [ADR-0009 — Python core dependency baseline](../../docs/adr/0009-python-core-dependency-baseline.md) (3.12.x, `<3.13`)
- [ADR-0010 — Production deployment / secrets / backup recovery](../../docs/adr/0010-production-deployment-secrets-backup-recovery.md)
- [ADR-0011 — CifangQuant primary ETF provider (Phase 1 first + second increments)](../../docs/adr/0011-cifangquant-primary-etf-provider.md) (Status: Proposed; the adapter is wired but disabled by default and remains gated on O-1 / O-3 / O-4 for production use)
- [ADR-0012 — Research lifecycle and AI execution boundary](../../docs/adr/0012-research-lifecycle-boundary.md) (Accepted 2026-08-07; freezes the `ResearchCase → EvidencePack → ResearchRun → ResearchResult` chain, the immutable evidence-vs-Result separation, and the versioned `ResearchRunner` / playbook boundary implemented by the JiuwenSwarm adapter)
- [ADR-0013 — Provider–Engine–Event architecture enhancement](../../docs/adr/0013-provider-engine-event-architecture.md) (Accepted for Phase 0 / implementation gated by checkpoints; freezes the authority chain — catalog is the Provider declaration authority, `provider_routing` is the dataset × Provider selection authority, factory + `ProviderRuntimeRegistry` is the only runtime entry point, Dagster remains the job-graph / scheduling authority, the Engine is a thin stock-daily-bars lifecycle orchestrator that does not own long-lived sessions or replace Dagster, and the Event Dispatcher is gated on having at least two approved consumers)

The underlying planning documents live under
[`/docs/plan/`](../../docs/plan/) — the current
[`invest-infra-stage4a-final-closure-sprint-plan-v1.1.md`](../../docs/plan/invest-infra-stage4a-final-closure-sprint-plan-v1.1.md)
plus
[`/docs/implementation/`](../../docs/implementation/M0-DECISIONS.md)
(M0 brief, decisions, acceptance). The pre-Stage-1 ETF vertical-slice
and Phase 1 data-ingestion plans are archived under
[`docs/archive/2026-08-02-stage1/`](../../docs/archive/2026-08-02-stage1/);
The architecture-governance and evidence-context-separation plans
were subsequently closed by the convergence commits.

## 6. Architecture governance convergence

[`docs/ARCHITECTURE-GOVERNANCE.md`](../../docs/ARCHITECTURE-GOVERNANCE.md)
is the authoritative Domain / Data / Repository ownership baseline
that complements ADR-0001. As of the convergence PR series
(`0d3ec02`, `1b281e9`, `6982a58`, `52124d9`, `e2676b8`):

- Every read-only API use-case routes through a dedicated
  `apps/api/src/invest_api/application/*.py` service
  (`EtfQueryService`, `CandidatePoolQueryService`,
  `PipelineRunQueryService`, `DataFreshnessQueryService`,
  `ResearchQueryService`, plus the Stage 4D
  `ExternalWorkflowQueryService` /
  `ObservationAdmissionCommandService` /
  `ResearchExternalEvidenceService`). Routers are thin wrappers
  that wire the request through the FastAPI dependency, call the
  service, and translate exceptions — they no longer construct
  repositories or issue SQL.
- The `apps/api/src/invest_api/dependencies.py` builders wire the
  service-layer factories to the storage repositories; tests patch
  `get_*_query_service` per-router and reuse the same
  `app.include_router` entry-point.
- `domain.analytics.factor_calculators` owns
  `FactorCalculationResult` / `calculate_market_state_factors`
  (GOV-03); the redundant `domain.research.factor_calculators`
  module was removed. The composite `ResearchRun` port, the
  research orchestration service and the JiuwenSwarm adapter live
  in the pipeline layer (see [Pipeline overview](../pipeline/overview.md));
  the read-only `ResearchQueryService` lives in the API layer
  (see [API overview](../api/overview.md)).
- New data admissions are gated by
  [`docs/validation/data-admission-checklist.md`](../../docs/validation/data-admission-checklist.md),
  the canonical per-ADR / governance registry record.
