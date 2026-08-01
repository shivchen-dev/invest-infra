---
type: Concept
title: Testing & operations
description: CI jobs (architecture, domain, storage unit/integration, migrations, pipeline, api, web), the AST-based architecture and migration-chain gates, mock vs integration split, compose stack, and the scheduled OpenWiki refresh.
resource: /openwiki/testing-and-ops/overview.md
tags: [ci, testing, alembic, compose, openwiki]
---

# Testing & operations

This page collects the cross-cutting test and ops machinery:
GitHub Actions jobs, the AST-based architecture and migration-chain
gates, the mock-vs-integration split, the local `docker compose`
stack, and the scheduled OpenWiki refresh.

## 1. CI jobs (`.github/workflows/ci.yml`)

The CI workflow is fan-out by domain so failures are easy to triage:

| Job | What it runs |
|-----|--------------|
| `architecture` | `python scripts/check_architecture.py` against Python 3.12. Fails on any forbidden cross-layer import or on a co-existing `providers.py` + `providers/` directory. |
| `domain-tests` | `pytest packages/domain/tests -q` with `PYTHONPATH=packages/domain/src`. |
| `storage-unit` | `pip install sqlalchemy psycopg[binary] pytest`, then `pytest tests/storage --ignore=tests/storage/integration -q` against the mock repositories. |
| `storage-integration` | Spins up a `postgres:16` service, `pip install`s `testcontainers`, runs `pytest tests/storage/integration -q` with `DATABASE_URL` pointed at the container. |
| `migrations` | `astral-sh/setup-uv@v6`, `cd apps/migrations && uv sync`, then `upgrade head → downgrade base → upgrade head` round-trip. |
| `pipeline-tests` | `uv sync` + `ruff check` + `pytest -q` + import check against `invest_pipeline.definitions.defs`. |
| `api-tests` | `uv sync` + `ruff check` + `pytest -q` + import check against `invest_api.main.app`. |
| `web` (see file directly) | `pnpm install --frozen-lockfile` + `typecheck` + `test --run` + `build`; the current Web package still needs its lockfile and test script checked in before this job can pass. |

The job name overrides in the `Makefile` (`make test` etc.) mirror
those jobs so local runs reproduce CI exactly.

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
[Architecture overview §5](../../architecture/overview.md#5-architecture-decision-records):

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
  `candidate_pool_item_repo`, `input_snapshot_repo` — each one is a
  `MagicMock` patched into the per-router module via `monkeypatch.setattr`.
- Builders: `make_instrument`, `make_daily_bar`, `make_input_snapshot`,
  `make_candidate_pool_run`, `make_pool_item` — keep the response-shape
  and invalid-input tests terse.

`test_etf_endpoints.py` and `test_candidate_pool_endpoints.py` cover:

- happy paths,
- filter parameters (`exchange`, `status`, `limit`, `offset`),
- input validation (inverted date range, missing instrument, 422 on
  invalid `limit` / `offset`),
- schema-level re-export identities
  (`LegacyInstrumentResponse is InstrumentResponse`, …).

## 5. Pipeline tests

[`apps/pipeline/tests/unit/`](../../apps/pipeline/tests/unit/) covers
the asset-level integration paths against fixture data:

- `test_etf_instruments_asset.py` exercises the `etf_instruments`
  asset and the underlying `write_etf_instruments_raw` /
  `upsert_etf_instruments` services.
- `test_etf_instruments_asset.py` / `test_fixture_dev_daily_bars.py`
  cover the daily-bars split.
- `test_fixture_dev_*` files pin the contract between
  `FixtureDevInstrumentProvider` and the storage layer.
- `test_input_snapshot_asset.py` and `test_input_snapshot.py` exercise
  `create_input_snapshot`, the daily-partitioning semantics and the
  hash determinism.
- `test_fixture_dev_adapter.py` covers the adapter error taxonomy.

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

The CI job `migrations` is the migration counterpart for production:
[ADR-0010](../../docs/adr/0010-production-deployment-secrets-backup-recovery.md)
specifies a separate migration job that runs `alembic upgrade head`
before the API comes up.

## 7. The OpenWiki autoupdate

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
