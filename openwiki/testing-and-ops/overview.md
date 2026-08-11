---
type: Concept
title: Testing & operations
description: CI jobs (architecture, domain, storage unit/integration, migrations, pipeline, API, personal-daily PostgreSQL e2e, web vitest + Playwright e2e), the AST-based architecture and migration-chain gates, mock vs integration tests, the DC-2 / Stage 4A evidence + context unit suites, the PR-6 JiuwenSwarm adapter and research orchestration unit suites, the PR-7 research API / MCP server unit suites, the PR-W03 research dashboard / PR-W05 case workspace unit suites, the DC-3 exposure collection unit suites, compose runtime, and the Cifang/replay/shadow-run operating procedures.
resource: /openwiki/testing-and-ops/overview.md
tags: [ci, testing, alembic, compose, openwiki, etf-profile, research-context, research-lifecycle, research-cockpit, jiuwenswarm, mcp, exposure]
---

# Testing & operations

This page collects the cross-cutting test and ops machinery:
GitHub Actions jobs, the AST-based architecture and migration-chain
gates, the mock-vs-integration split, the local `docker compose`
stack, current personal-pipeline runbooks and validation templates, and the
scheduled OpenWiki refresh.

## 1. CI jobs (`.github/workflows/ci.yml`)

The CI workflow is fan-out by domain so failures are easy to triage:

| Job | What it runs |
|-----|--------------|
| `architecture` | `python scripts/check_architecture.py` against Python 3.12. Fails on any forbidden cross-layer import or on a co-existing `providers.py` + `providers/` directory. |
| `domain-tests` | `pytest packages/domain/tests -q` with `PYTHONPATH=packages/domain/src`. |
| `storage-unit` | `pip install sqlalchemy psycopg[binary] pytest`, then `pytest tests/storage --ignore=tests/storage/integration -q` against the mock repositories. |
| `storage-integration` | Spins up a `postgres:16` service, `pip install`s `testcontainers`, runs `pytest tests/storage/integration -q` with `DATABASE_URL` pointed at the container. |
| `migrations` | `astral-sh/setup-uv@v6`, `cd apps/migrations && uv sync`, then `upgrade head → downgrade base → upgrade head` round-trip. |
| `pipeline-tests` | `uv sync` + `ruff check` + `pytest -q` for `apps/pipeline` (the `Makefile` target uses `uv run --no-env-file pytest` so a local `apps/pipeline/.env` cannot mask the real `DATABASE_URL` in CI). |
| `pipeline-import-smoke` | Imports `invest_pipeline.definitions.defs` after `uv sync`. |
| `api-tests` | `uv sync` + `ruff check` + `pytest -q` for `apps/api`. |
| `api-openapi-smoke` | Imports `invest_api.main.app` after `uv sync`. |
| `personal-daily-e2e` | Runs `tests/e2e/test_personal_daily_pipeline_postgres.py -q` against a PostgreSQL 16 service after syncing migrations, pipeline and API environments. |
| `openapi-contract` | Re-runs `apps/api/src/invest_api/export_openapi.py` to refresh `apps/api/openapi.json`, then `pnpm api:generate` to refresh `apps/web/src/api/generated.ts`, and finally `git diff --exit-code` on the generated TypeScript file. The job fails when the Web workbench's generated client drifts from the live FastAPI OpenAPI surface. |
| `web-check` | `pnpm install --frozen-lockfile` + `pnpm typecheck` + `pnpm test:run` + `pnpm build` in `apps/web`; the test step drives the vitest + jsdom suite (router, API client, page compositions, components, utils). |
| `web-e2e` (local only) | `pnpm test:e2e` runs the Playwright cockpit end-to-end suite under [`apps/web/e2e/`](../../apps/web/e2e) via [`apps/web/playwright.config.ts`](../../apps/web/playwright.config.ts) (Chromium project, `webServer` boots Vite at `127.0.0.1:5174`). The local script is the canonical way to exercise the Research Cockpit smoke path; the Playwright suite is not yet wired into the GitHub Actions workflow. |

The job name overrides in the `Makefile` (`make test` etc.) cover the
main test slices, but the workflow also has separate import-smoke,
personal-daily-e2e, and openapi-contract jobs. The `web-check` job
type-checks, runs the vitest unit-test suite, and builds; the local
`test-web` target mirrors the same three commands. The Playwright
Research Cockpit e2e (`apps/web/e2e/research-cockpit.e2e.ts`) is
local-only today (`pnpm test:e2e`); it boots Vite at `127.0.0.1:5174`
through the Playwright `webServer` config and is the canonical cockpit
smoke for future operators.

### Migration-chain AST gate

[`/tests/test_migration_chain.py`](../../tests/test_migration_chain.py)
parses every revision file under
`apps/migrations/migrations/versions/`, extracts the `revision` /
`down_revision` module-level literals, and asserts:

- Exactly **one** current head is reachable.
- The initial revision is `20260731_0001` and declares
  `down_revision = None`.
- `upgrade()` calls `op.execute(...)` for each of the four schemas
  (`raw`, `core`, `analytics`, `ops`).
- `upgrade()` creates the canonical `instruments`, `provider_batches`
  and `pipeline_runs` tables.

A helper (`_try_literal_eval`) swallows non-literal expressions so the
AST walk is robust to revision files that import helpers or build
strings dynamically.

## 2. Architecture gate

[`/scripts/check_architecture.py`](../../scripts/check_architecture.py)
is a single-file scanner using the Python `ast` module. It enforces
the rules listed in
[Architecture overview §5](../architecture/overview.md#5-architecture-decision-records):

1. Imports — every layer has a hard-coded `set` of forbidden top-level
   package names; any matching import is reported as a violation.
2. Forbidden patterns — `schema="app"` literal anywhere in the tree
   (the legacy `app` schema is retired) and `qfq`/`hfq` literals
   (only `none` is allowed in production paths per ADR-0005).
3. Co-existence — `apps/pipeline/src/invest_pipeline/providers.py`
   cannot be present at the same time as `providers/` (the new
   adapter layout is `adapters/fixture_dev/...`).

`make arch-check` is the local invocation; CI runs the same script
under the `architecture` job.

## 3. Mock vs integration tests

Tests in `tests/storage` split into two halves:

| Sub-tree | Style |
|----------|-------|
| `tests/storage/test_*_mock.py` | Uses `MagicMock` sessions and the storage-layer DTOs to exercise every repository branch without touching a database. |
| `tests/storage/integration/test_*.py` | Uses `testcontainers.PostgreContainer` to spin up a disposable 16.x container; fixtures create the relevant schema via `Base.metadata.create_all` and roll back the transaction at the end of each test via savepoints. |

The CI matrix keeps the two halves on separate jobs (`storage-unit`,
`storage-integration`) so the fast mock suite does not pay for the
testcontainers docker pull and the integration suite gets a clean
service container.

## 4. API tests

[`apps/api/tests/`](../../apps/api/tests/) is mock-based. The shared
fixtures in [`conftest.py`](../../apps/api/tests/conftest.py) provide:

- `client` — a `TestClient(app)` whose `get_db_session` dependency
  yields a `MagicMock` `Session`.
- `instrument_repo`, `daily_bar_repo`, `candidate_pool_run_repo`,
  `candidate_pool_item_repo`, `input_snapshot_repo`,
  `candidate_pool_instrument_repo`, and `pipeline_run_repo` — each one a
  `MagicMock` patched into the per-router module via `monkeypatch.setattr`.
- Builders: `make_instrument`, `make_daily_bar`, `make_input_snapshot`,
  `make_candidate_pool_run`, `make_pool_item`, and `make_pipeline_run` —
  keep the response-shape and invalid-input tests terse.

`test_etf_endpoints.py`, `test_candidate_pool_endpoints.py`,
`test_pipeline_run_endpoints.py`, and `test_data_freshness_endpoints.py`
cover:

- happy paths and candidate-pool added/retained/removed diffs;
- `test_pipeline_run_endpoints.py` covers the paginated history contract,
  SQL-side personal-job filtering, stable paging parameters, and sanitized
  query failures; candidate-pool tests cover server-side instrument display
  lookup for latest and diff responses.
- filter parameters (`exchange`, `status`, `limit`, `offset`);
- input validation (inverted date range, malformed UUID/date, missing
  instrument or run);
- personal-job scoping for pipeline runs and all five data-freshness
  statuses, including sanitized SQLAlchemy failures;
- schema-level re-export identities
  (`LegacyInstrumentResponse is InstrumentResponse`, …).

## 5. Pipeline tests

[`apps/pipeline/tests/unit/`](../../apps/pipeline/tests/unit/) covers
the asset-level integration paths against fixture data:

- `test_etf_instruments_asset.py` exercises the `etf_instruments`
  asset and the underlying `write_etf_instruments_raw` /
  `upsert_etf_instruments` services. Its provider round-trip regression
  pins `etf_instruments` as the shared formal dataset key, preventing
  real-provider requests from being skipped by a legacy lookup.
- `test_etf_daily_bars_service.py` exercises
  `write_etf_daily_bars_raw` / `upsert_etf_daily_bars`, provider-aware
  `source_provider` sidecars, latest-successful-attempt selection, and
  the rerun-idempotency contract (re-using the logical request via
  `SqlAlchemyProviderRequestRepository.get_or_create`).
- `test_fixture_dev_*` files pin the contract between
  `FixtureDevInstrumentProvider` and the storage layer.
- `test_input_snapshot_asset.py` and `test_input_snapshot.py` exercise
  `create_input_snapshot`, the daily-partitioning semantics and the
  hash determinism.
- `test_fixture_dev_adapter.py` covers the adapter error taxonomy.
- `test_cifangquant_*` files cover the CifangQuant adapter across
  the full evidence-tuple surface: client (`test_cifangquant_client.py`),
  field mapper (`test_cifangquant_mapping.py`), adapter wiring
  (`test_cifangquant_adapter.py`, `test_cifangquant_adapter_e2e.py`)
  and the opt-in smoke CLI (`test_cifangquant_smoke.py`). The suite
  injects `httpx.MockTransport` and a fake clock so CI never reaches
  the network.
- `test_personal_universe.py` and `test_personal_universe_fixture_coverage.py`
  cover `load_personal_universe` / `resolve_personal_universe` and
  pin the YAML ↔ fixture_dev ETF overlap.
- `test_candidate_pool_asset.py` / `test_candidate_pool_service.py`
  exercise `personal_candidate_pool` and the underlying
  `candidate_pool_service.calculate_and_publish_candidate_pool`.
- `test_etf_assets_provider_wiring.py` and
  `test_provider_factory_runtime.py` pin `build_provider()`'s
  four branches (fixture_dev / cifangquant / akshare / tushare /
  unknown) and the `INVEST_PIPELINE_PROVIDER_KEY` env wiring. The
  runtime factory test asserts
  `KNOWN_PROVIDER_KEYS == ("fixture_dev", "cifangquant", "akshare",
  "tushare")` so a future branch cannot land without an explicit
  test update.
- `test_provider_catalog.py` (≈626 LOC) pins the six catalog
  declarations, the alphabetical iteration order, and the
  `KeyError(key)` behaviour of `lookup_provider`. The
  `test_provider_routing_selection.py` /
  `test_provider_routing_coverage.py` /
  `test_provider_routing_probe.py` suite covers the
  `provider_routing` pure layer (dataset / capability matching,
  default-enabled gate, research-only rejection, coverage matrix
  determinism). `test_provider_coverage_cli.py` /
  `test_provider_coverage_plan.py` /
  `test_provider_coverage_merge.py` cover the read-only coverage
  CLI, the active-universe bridge, and the deterministic
  multi-provider merge.
- `test_akshare_adapter.py` / `test_akshare_client_nav_calendar.py`
  / `test_akshare_config.py` / `test_akshare_mapping.py` cover the
  AkShare adapter end-to-end (Sina-preference + Eastmoney-fallback
  loop, NAV / calendar read-only surfaces, lazy SDK import seam,
  adjustment lock, the conservative DC-2 `fetch_etf_profile`
  surface that joins `fund_name_em` and `fund_etf_spot_em` and
  the `map_etf_profile_to_field_evidence` mapper). `test_tushare_integration.py`
  pins the Tushare Pro bounded slice (POST-JSON client, mapper,
  adapter, credentials store), and `test_credentials.py` pins the
  centralized `CredentialStore` lookup contract. `test_quicktiny_mcp_adapter.py`
  and `test_rsscast_adapter.py` cover the MCP research transports
  using `httpx.MockTransport` so CI never opens a socket. The
  historical three-provider plan Phase-1 stubs (`eastmoney` /
  `sina` / `tonghuashun`) were removed alongside the adapter
  packages; the matching test files were deleted as well.
- `test_historical_daily_bars_cli.py` (≈1154 LOC) covers the
  guarded historical ETF backfill CLI: ISO date parsing, range
  validation, ≤90-day chunking, the `KNOWN_PROVIDER_KEYS`-scoped
  provider opt-in, the `TokenNonLeakTest` and the
  `OnlyDailyBarsAssetsInvokedTest` that pins the CLI to
  `etf_daily_bars` only.
- `test_research_fixture_65d.py` pins four invariants of the
  Stage 4A research fixture (`tests/fixtures/research/etf_daily_bars_65d.json`,
  symbol `510300`, ≥65 rows, consecutive weekday chain, no
  future dates, OHLC + amount correctness). The fixture is
  consumed by `packages/domain/tests/test_research_evidence.py`,
  which covers the canonical projection, evidence-id derivation,
  the 8-factor v1.0.0 set, and the golden payload hash. The
  companion `test_v1_adapter.py` and `test_candidate_universe.py`
  cover the V1→V2 pure adapter and the dynamic ETF universe
  qualification.
- `test_personal_daily_cli.py`, `test_personal_etf_daily_job.py` and
  `test_runtime_config_paths.py` cover the manual driver, the
  `personal_etf_daily_job` selection and the
  `INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH` /
  `INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH` env overrides. The CLI
  tests also pin best-effort `ops.pipeline_runs` lifecycle recording,
  token-scrubbed failure summaries, and the rule that audit-write
  failures do not change the job's output or exit code.
- The DC-3 real-exposure slice is covered by
  `test_real_exposure_service.py`,
  `test_real_exposure_cli.py`, `test_real_exposure_asset.py`, and
  `test_real_exposure_job.py`; the fixture exposure CLI pairs with
  the matching DAG-asset tests and integration tests.
- `test_daily_preflight.py` covers the ordered run/skip/fail guard
  decisions and the default-off schedule flag; the schedule remains
  manually exercised rather than reaching a real provider in CI.
- `test_etf_profiles_service.py` / `test_etf_profile_context.py`
  cover the DC-2 `etf_profiles` ETL service and the Stage 4A
  `build_etf_profile_context_pack` builder (resolver → `ContextItem`
  projection, missing / conflict / resolved outcomes, AUM /
  market_value separation). The matching pure-domain tests live
  in `packages/domain/tests/test_etf_profile.py` /
  `test_etf_profile_resolver.py` /
  `test_research_context.py`; the storage mock tests
  `tests/storage/test_etf_profile_repository_mock.py` /
  `test_etf_profile_fields_repository_mock.py` /
  `test_research_context_pack_repository_mock.py` pin the
  `core.etf_profiles` / `analytics.etf_profile_fields` /
  `analytics.research_context_packs` repository contracts.
- [`tests/e2e/test_personal_daily_pipeline_postgres.py`](../../tests/e2e/test_personal_daily_pipeline_postgres.py)
  runs the fixture provider through migrations, raw evidence, core data,
  snapshot and published candidate-pool tables against PostgreSQL 16. It
  reruns the same trade date to verify no duplicate daily-bar revisions or
  natural-key candidate-pool runs, and checks the latest candidate-pool API.
- The PR-7 research API slice adds four unit suites:
  `test_research_endpoints.py` (the six `/api/v1/research-cases` /
  `/api/v1/research-runs` routes plus validation), `test_research_service.py`
  (the `ResearchQueryService` boundary with its four `Reader` Protocols),
  `test_research_detail_serialization.py` (the `EvidencePackResponse` /
  `ResearchCaseResponse` factory path), and `test_mcp_server.py`
  (the PR-MCP-MINIMAL `FastMCP` tool surface). The PR-W03 dashboard
  addition adds `test_research_dashboard_endpoints.py` (the
  `/api/v1/research-dashboard` route plus the
  `data_quality` / `freshness` / `market_status` / `evidence_status`
  boundary) and `test_research_dashboard_service.py` (the
  `get_dashboard` orchestration sequence, the bounded
  `recent_runs` page and the explicit `unavailable` market-status
  shape). The PR-W05 case-workspace addition adds
  `test_research_workspace_endpoints.py` (the
  `/api/v1/research-cases/{case_id}/workspace` route, the 404
  contract, the `case_id` UUID 422 path) and
  `test_research_workspace_service.py` (the `get_workspace`
  composition sequence, the positional run ↔ result pairing, the
  `SQLAlchemyError` boundary). The PR-6 JiuwenSwarm
  slice adds `test_jiuwenswarm_adapter.py` (port binding / version
  matching / transport identity) and `test_jiuwenswarm_slice2.py`
  (the CLI subprocess transport). `test_research_orchestration_service.py`
  pins the `ResearchOrchestrationService` lifecycle and the
  `(SUCCEEDED / RUNNER_FAILED / TIMEOUT_UNCERTAIN /
  RECONCILIATION_REQUIRED)` outcome taxonomy. The Stage 4B
  context-projection slice adds
  [`test_research_context_projection.py`](../../apps/pipeline/tests/unit/test_research_context_projection.py)
  (the application-layer
  `load_context_projection` helper — success path, missing
  bundle / missing snapshot negatives, the full mismatch matrix
  on bundle id / case id / pack id / pack hash / as-of date /
  snapshot id / content hash / `QualityStatus` / `FreshnessStatus`,
  and the legacy `evidence_bundle_id is None` case). The DC-3 exposure
  slice adds `test_akshare_exposure_mapper.py`,
  `test_akshare_holding_mapper.py`, `test_akshare_client_exposure.py`,
  `test_exposure_service.py`, and `test_exposure_cli.py` plus the
  `test_exposure_adapters.py` / `test_exposure_mapping.py` /
  `test_exposure_adapter.py` coverage of the gated
  `apps/pipeline/src/invest_pipeline/adapters/exposure/` surface.

## 6. Deployment and runtime

[`/compose.yaml`](../../compose.yaml) defines the development stack:

- `postgres` — `postgres:16-alpine`, default credentials picked from
  environment variables with `invest_dev_password` as fallback, a
  named volume `postgres-data`, and a `pg_isready` healthcheck.
- `api` — built from `apps/api/Dockerfile`, depends on `postgres`
  being healthy, exposes `8000:8000`.
- `web` — `apps/web/Dockerfile` (Vite dev server) listening on
  `3001:5173`.
- `dagster` — built from `apps/pipeline/Dockerfile`, exposes
  `3000:3000`, persists state in the `dagster-home` named volume, and
  loads `apps/pipeline/.env` via `env_file` so the in-container Dagster
  process sees the same opt-ins the host CLI uses.

`make up` (or `docker compose up --build`) starts the full stack and
prints the OpenAPI / Vite / Dagster URLs from the README.

Outside `docker compose`, two opt-in local CLIs run the personal
pipeline against the host environment without booting the stack:

- `make provider-smoke` invokes
  [`apps/pipeline/src/invest_pipeline/cifang_smoke.py`](../../apps/pipeline/src/invest_pipeline/cifang_smoke.py)
  for an explicit `--trade-date` and symbol list. It needs
  `INVEST_PIPELINE_CIFANG_ENABLED=true` plus a non-empty
  `INVEST_PIPELINE_CIFANG_API_KEY` plus `SMOKE_CONFIRM_NETWORK=1`
  before it touches the network. The Make target sets
  `INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED=false` and forwards
  `apps/pipeline/.env` (when present) so the smoke never runs against
  a mis-configured schedule.
- `make personal-daily-run TRADE_DATE=...` invokes
  [`personal_daily_cli.py`](../../apps/pipeline/src/invest_pipeline/personal_daily_cli.py)
  for the manual `personal_etf_daily_job` driver. Fixture mode
  (`INVEST_PIPELINE_PROVIDER_KEY=fixture_dev`) needs no opt-in; real
  CifangQuant runs require the three env opt-ins plus
  `CONFIRM_NETWORK=1`. The Make target sets
  `INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED=false` and forwards
  `apps/pipeline/.env` for the same reason.
- `make historical-daily-bars-backfill START_DATE=... END_DATE=...`
  invokes
  [`historical_daily_bars_cli.py`](../../apps/pipeline/src/invest_pipeline/historical_daily_bars_cli.py)
  for the guarded historical ETF daily-bars backfill (≤90-day
  chunks, no Dagster job, no input-snapshot / candidate-pool /
  evidence-pack / AI-research assets). The target validates the
  ISO dates, sets
  `INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED=false`, forwards
  `apps/pipeline/.env`, and reuses the existing raw evidence +
  core.daily_bars write path. The provider opt-in is scoped to
  `fixture_dev` or `cifangquant`; an `akshare` historical run
  is not yet wired into this CLI.
- `make openapi-generate` re-derives
  [`apps/api/openapi.json`](../../apps/api/openapi.json) from the
  live FastAPI app via
  [`apps/api/src/invest_api/export_openapi.py`](../../apps/api/src/invest_api/export_openapi.py)
  and then regenerates the Web's
  [`apps/web/src/api/generated.ts`](../../apps/web/src/api/generated.ts)
  through `pnpm api:generate` (`openapi-typescript`).

For host operation, [`deploy/invest-infra-dagster.service`](../../deploy/invest-infra-dagster.service)
ships a **user-level** systemd unit that runs `dagster dev` out of
`/home/claw/invest-infra/apps/pipeline` with
`INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED=true`,
`DAGSTER_HOME=/home/claw/invest-infra/.dagster`, and
`EnvironmentFile=/home/claw/invest-infra/apps/pipeline/.env`. Operators
install it under `~/.config/systemd/user/` and run
`systemctl --user enable --now invest-infra-dagster.service`; the
`Restart=on-failure` directive keeps the dev server alive across transient
crashes. User lingering must be enabled if the service should survive logout.

The CI job `migrations` is the migration counterpart for production:
[ADR-0010](../../docs/adr/0010-production-deployment-secrets-backup-recovery.md)
specifies a separate migration job that runs `alembic upgrade head`
before the API comes up.

## 7. Operational runbooks and validation

The checked-in operational contract is now split between the personal
pipeline implementation and four focused documents:

- [`docs/runbooks/cifang-auth-failure.md`](../../docs/runbooks/cifang-auth-failure.md)
  prescribes redacted diagnostics and recovery for CifangQuant 401/403
  failures; credentials remain environment-injected and must never appear
  in logs, API responses or commits.
- [`docs/runbooks/reprocess-trade-date.md`](../../docs/runbooks/reprocess-trade-date.md)
  makes `make reprocess-date TRADE_DATE=YYYY-MM-DD` the canonical single-date
  replay, with `make personal-backfill START_DATE=... END_DATE=...` for an
  inclusive range of at most 90 natural days. Backfill skips weekends and
  stops at the first failed weekday.
- [`docs/validation/stage1-real-cifang-acceptance.md`](../../docs/validation/stage1-real-cifang-acceptance.md)
  is a redacted real-network acceptance template; it keeps ADR-0011
  `Proposed` and records no key, hash, header or raw response.
- [`docs/validation/stage2-shadow-run-log.md`](../../docs/validation/stage2-shadow-run-log.md)
  is the 10-trading-day manual shadow log. During this closed period,
  `INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED=false`, operators use the manual
  run/replay commands, and graduation requires at least 10 consecutive
  trading days, at least 90% success, replayable failures, no duplicate
  publications or same-content revisions, and no credential leaks.

## 8. The OpenWiki autoupdate

[`.github/workflows/openwiki-update.yml`](../../.github/workflows/openwiki-update.yml)
runs daily at `0 8 * * *` (and on `workflow_dispatch`). It:

1. Checks out the repository.
2. Sets up Node 22 and installs the global `openwiki` CLI.
3. Runs `openwiki code --update --print` against the repository
   (with the OpenRouter + LangSmith secrets supplied via the Actions
   environment).
4. Opens (or updates) a pull request that only adds files under
   `openwiki/`, hand-authored lines stay untouched so the human
   can review each incremental diff.

The deliverable land in this directory; the file you are reading is
`openwiki/testing-and-ops/overview.md`.
