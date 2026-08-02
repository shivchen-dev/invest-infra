---
type: Concept
title: Testing & operations
description: CI jobs (architecture, domain, storage unit/integration, migrations, pipeline, API, personal-daily PostgreSQL e2e, and web), the AST-based architecture and migration-chain gates, mock vs integration tests, compose runtime, and the Cifang/replay/shadow-run operating procedures.
resource: /openwiki/testing-and-ops/overview.md
tags: [ci, testing, alembic, compose, openwiki]
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
| `pipeline-tests` | `uv sync` + `ruff check` + `pytest -q` for `apps/pipeline`. |
| `pipeline-import-smoke` | Imports `invest_pipeline.definitions.defs` after `uv sync`. |
| `api-tests` | `uv sync` + `ruff check` + `pytest -q` for `apps/api`. |
| `api-openapi-smoke` | Imports `invest_api.main.app` after `uv sync`. |
| `personal-daily-e2e` | Runs `tests/e2e/test_personal_daily_pipeline_postgres.py -q` against a PostgreSQL 16 service after syncing migrations, pipeline and API environments. |
| `web-check` | `pnpm install` + `pnpm typecheck` + `pnpm build` in `apps/web`; this workflow job does not run the local `pnpm test --run` command. |

The job name overrides in the `Makefile` (`make test` etc.) cover the
main test slices, but the workflow also has separate import-smoke and
personal-daily-e2e jobs. The workflow's `web-check` job is intentionally
lighter than the local `test-web` target: CI currently type-checks and
builds, while the Make target also runs the web test command.

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
  `candidate_pool_item_repo`, `input_snapshot_repo`, and
  `pipeline_run_repo` — each one a `MagicMock` patched into the
  per-router module via `monkeypatch.setattr`.
- Builders: `make_instrument`, `make_daily_bar`, `make_input_snapshot`,
  `make_candidate_pool_run`, `make_pool_item`, and `make_pipeline_run` —
  keep the response-shape and invalid-input tests terse.

`test_etf_endpoints.py`, `test_candidate_pool_endpoints.py`,
`test_pipeline_run_endpoints.py`, and `test_data_freshness_endpoints.py`
cover:

- happy paths and candidate-pool added/retained/removed diffs;
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
  `test_provider_factory_runtime.py` pin `build_provider()`'s three
  branches (fixture_dev / cifangquant / unknown) and the
  `INVEST_PIPELINE_PROVIDER_KEY` env wiring.
- `test_personal_daily_cli.py`, `test_personal_etf_daily_job.py` and
  `test_runtime_config_paths.py` cover the manual driver, the
  `personal_etf_daily_job` selection and the
  `INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH` /
  `INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH` env overrides. The CLI
  tests also pin best-effort `ops.pipeline_runs` lifecycle recording,
  token-scrubbed failure summaries, and the rule that audit-write
  failures do not change the job's output or exit code.
- `test_daily_preflight.py` covers the ordered run/skip/fail guard
  decisions and the default-off schedule flag; the schedule remains
  manually exercised rather than reaching a real provider in CI.
- [`tests/e2e/test_personal_daily_pipeline_postgres.py`](../../tests/e2e/test_personal_daily_pipeline_postgres.py)
  runs the fixture provider through migrations, raw evidence, core data,
  snapshot and published candidate-pool tables against PostgreSQL 16. It
  reruns the same trade date to verify no duplicate daily-bar revisions or
  natural-key candidate-pool runs, and checks the latest candidate-pool API.

## 6. Deployment and runtime

[`/compose.yaml`](../../compose.yaml) defines the development stack:

- `postgres` — `postgres:16-alpine`, default credentials picked from
  environment variables with `invest_dev_password` as fallback, a
  named volume `postgres-data`, and a `pg_isready` healthcheck.
- `api` — built from `apps/api/Dockerfile`, depends on `postgres`
  being healthy, exposes `8000:8000`.
- `web` — `apps/web/Dockerfile` (Vite dev server) listening on
  `5173:5173`.
- `dagster` — built from `apps/pipeline/Dockerfile`, exposes
  `3000:3000`, persists state in the `dagster-home` named volume.

`make up` (or `docker compose up --build`) starts the full stack and
prints the OpenAPI / Vite / Dagster URLs from the README.

Outside `docker compose`, two opt-in local CLIs run the personal
pipeline against the host environment without booting the stack:

- `make provider-smoke` invokes
  [`apps/pipeline/src/invest_pipeline/cifang_smoke.py`](../../apps/pipeline/src/invest_pipeline/cifang_smoke.py)
  for an explicit `--trade-date` and symbol list. It needs
  `INVEST_PIPELINE_CIFANG_ENABLED=true` plus a non-empty
  `INVEST_PIPELINE_CIFANG_API_KEY` plus `SMOKE_CONFIRM_NETWORK=1`
  before it touches the network.
- `make personal-daily-run TRADE_DATE=...` invokes
  [`personal_daily_cli.py`](../../apps/pipeline/src/invest_pipeline/personal_daily_cli.py)
  for the manual `personal_etf_daily_job` driver. Fixture mode
  (`INVEST_PIPELINE_PROVIDER_KEY=fixture_dev`) needs no opt-in; real
  CifangQuant runs require the three env opt-ins plus
  `CONFIRM_NETWORK=1`.

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
