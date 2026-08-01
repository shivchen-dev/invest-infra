---
type: Concept
title: Pipeline overview
description: Dagster assets, ETL service modules, the fixture_dev and cifang adapter boundaries, the declarative provider_catalog, and how the etf_* / etf_input_snapshot assets wire the three-layer Provider evidence model into the raw / core / analytics PostgreSQL schemas.
resource: /openwiki/pipeline/overview.md
tags: [pipeline, dagster, adapters, etl, fixture_dev, cifang, provider-catalog]
---

# Pipeline overview

`apps/pipeline/src/invest_pipeline/` runs the daily ETL on top of
Dagster. Assets coordinate two well-known patterns:

- **Three-layer Provider evidence write.** Every Provider call
  produces a `(ProviderRequest, ProviderAttempt, ProviderBatch)`
  triple into `raw.*`. Adapters never write to these tables
  directly — the application service inside a `SqlAlchemyUnitOfWork`
  does.
- **Standardisation into `core.*` / `analytics.*`.** The downstream
  asset reads the persisted request's `response_payload_json`
  sidecar, deserialises the records, resolves canonical IDs, and
  upserts into the business tables using the repository surface.

## 1. Module layout

```
apps/pipeline/src/invest_pipeline/
├── __init__.py
├── assets.py              # @dg.asset definitions (seed_instruments + etf_*)
├── definitions.py         # dg.Definitions registry
├── config.py              # pydantic-settings Settings
├── provider_catalog.py    # declarative provider role / capability registry
├── adapters/
│   ├── __init__.py        # re-exports FixtureDevInstrumentProvider + error taxonomy
│   ├── errors.py          # ProviderError hierarchy
│   ├── fixture_dev/
│   │   ├── __init__.py
│   │   ├── adapter.py     # FixtureDevInstrumentProvider
│   │   ├── etf_instruments.json
│   │   └── etf_daily_bars.json
│   └── cifang/            # CifangQuant adapter (ADR-0011 Phase 1 placeholder)
│       ├── __init__.py
│       ├── adapter.py     # CifangQuantInstrumentProvider (raises NotImplemented)
│       └── config.py      # CifangSettings (redacted, disabled by default)
├── etf_instruments.py     # write_etf_instruments_raw / upsert_etf_instruments
│                         # (owns RawEtlResult + UnitOfWorkFactory helpers)
├── etf_daily_bars.py      # write_etf_daily_bars_raw / upsert_etf_daily_bars
│                         # (re-exports RawEtlResult from etf_instruments)
└── input_snapshot.py      # create_input_snapshot (PR-07)
```

Tests live in
[`apps/pipeline/tests/`](../../apps/pipeline/tests/);
unit tests for each service module cover contract and idempotency
guarantees.

## 2. Definitions

[`invest_pipeline.definitions.defs`](../../apps/pipeline/src/invest_pipeline/definitions.py)
registers the assets in dependency order:

```python
dg.Definitions(
    assets=[
        seed_instruments,
        etf_instruments_raw,
        etf_instruments,
        etf_input_snapshot,    # daily-partitioned snapshot
        etf_daily_bars_raw,
        etf_daily_bars,
    ]
)
```

`make pipeline-dev` runs `dagster dev -m invest_pipeline.definitions`,
and `make test-pipeline` runs `ruff check` + `pytest` + an import
check.

## 3. Asset graph

```
seed_instruments ───────────────┐
                                ↓
                etf_instruments_raw ──→ etf_instruments ──→ etf_input_snapshot ──→ (future pool)
                                          │
                                          └──→ etf_daily_bars_raw ──→ etf_daily_bars
```

- `seed_instruments` exists for the greenfield slice and seeds the
  canonical rows directly. Production cuts over to the `etf_*`
  assets; the asset is still registered so the slice validation works.
- `etf_instruments_raw` writes the three-layer evidence bundle and
  persists the standardized records inside the SAME raw transaction
  (request → attempt → batch → instruments upsert).
- `etf_instruments` re-opens a `SqlAlchemyUnitOfWork`, reads the
  attempt's `response_payload_json`, deserialises the records and
  upserts them into `core.instruments`. If the upstream attempt
  failed the asset returns a `MaterializeResult` with `skipped=True`
  rather than raising, so a contract failure doesn't cascade into a
  Dagster retry storm.
- `etf_daily_bars_raw` / `etf_daily_bars` mirror that pattern for
  `core.daily_bars`; `etf_daily_bars.upsert_many` is the call site
  where the ADR-0006 revision rules apply (no-op on identical
  `row_hash`, `latest+1` on a content change).
- `etf_input_snapshot` is a `DailyPartitionsDefinition` asset keyed
  by `trade_date` (the partition starts on `2026-07-23`). It selects
  every `core.instruments.id` whose `instrument_type` is `ETF`, then
  hands the sorted IDs to `create_input_snapshot` which calculates
  the canonical `content_hash` and stores it.

## 4. `fixture_dev` adapter

[`FixtureDevInstrumentProvider`](../../apps/pipeline/src/invest_pipeline/adapters/fixture_dev/adapter.py)
is the **only** adapter with real (deterministic) data today; the
[newer `cifang` placeholder](#5-cifang-adapter-placeholder-adr-0011-phase-1-first-increment)
exists only to lock the port shape. `fixture_dev` returns:

- **ETF instruments** from `fixture_dev/etf_instruments.json` — a small
  but representative SSE / SZSE ETF universe (12 symbols covering the
  broad-market, sector and bond categories used throughout the slice).
- **ETF daily bars** from `fixture_dev/etf_daily_bars.json` — eight
  trading days (2026-07-23..2026-07-30) of OHLCV rows including a
  deliberately mixed `trading_status` (mix of `normal` and
  `suspended`) so the calculator's `suspended` exclusion path is
  exercised by the test suite.

The adapter's role is **purely deterministic**: serialise-deserialise
helpers keep the standardisation tests honest about sidecar shapes
and the `response_payload_json` round-trip. Per ADR-0003 the real
Provider selection is blocked until O-1 is confirmed; the fixture's
purpose is to let the storage + pipeline + API layers ship while
real Provider integration stays a future, gated change.

## 5. `cifang` adapter placeholder (ADR-0011, Phase 1 first increment)

[`apps/pipeline/src/invest_pipeline/adapters/cifang/`](../../apps/pipeline/src/invest_pipeline/adapters/cifang/)
is the **Phase 1 first increment** ship-target for the CifangQuant
Provider documented in [ADR-0011](../../docs/adr/0011-cifangquant-primary-etf-provider.md)
(Status: Proposed). It is intentionally a placeholder:

- [`CifangQuantInstrumentProvider`](../../apps/pipeline/src/invest_pipeline/adapters/cifang/adapter.py)
  carries `provider_key="cifangquant"` and exposes the same
  `fetch_instruments` / `fetch_daily_bars` shape as `FixtureDevInstrumentProvider`,
  but both methods immediately raise
  `invest_pipeline.adapters.errors.ProviderAdapterNotImplementedError`,
  pointing the operator at ADR-0011 §4. No HTTP client, mapper or
  rate limiter ships in this increment.
- [`CifangSettings`](../../apps/pipeline/src/invest_pipeline/adapters/cifang/config.py)
  is a `pydantic-settings` model with `enabled=False` by default,
  `adjustment` locked to the literal `"none"` (rejected otherwise,
  ADR-0005 §4) and `api_key` carried as a `pydantic.SecretStr` whose
  `__repr__` / `__str__` / `redacted_dict()` render `"***"`. The
  env-prefix is `INVEST_PIPELINE_CIFANG_*`.
- The top-level [`apps/pipeline/src/invest_pipeline/adapters/__init__.py`](../../apps/pipeline/src/invest_pipeline/adapters/__init__.py)
  is **not** updated to re-export `CifangQuantInstrumentProvider` (ADR-0011 §5
  defers the public symbol-table change to the second increment); the
  adapter is referenced via its own package.

The placeholder satisfies the Domain `EtfMarketDataProvider` port so
later increments can swap it in via the Provider Registry without
touching the application services. The Phase 1 second increment
(HTTP client, mapper, rate limiter, real I/O) is gated on O-1 / O-3
/ O-4 closure.

## 6. ETL service modules

The assets wrap testable, asset-agnostic service functions so the
contract tests can drive them without spinning up Dagster:

- [`etf_instruments.py`](../../apps/pipeline/src/invest_pipeline/etf_instruments.py)
  defines `write_etf_instruments_raw(provider, session_factory, as_of=...)`
  and `upsert_etf_instruments(session_factory, as_of=...)`. It is the
  **single source of truth** for the shared `RawEtlResult` dataclass
  and the `UnitOfWorkFactory` / `_coerce_session_factory` helpers both
  ingestion paths need.
- [`etf_daily_bars.py`](../../apps/pipeline/src/invest_pipeline/etf_daily_bars.py)
  defines `write_etf_daily_bars_raw(provider, session_factory, *,
  symbols, start_date, end_date)` and `upsert_etf_daily_bars(...)`.
  The raw writer distinguishes three failure cases: a failed
  attempt persists only the request + attempt (no batch), a
  successful attempt without batch persists request + attempt +
  marked-partial request status, and a successful attempt with a
  non-empty batch persists all three rows. The upsert wrapper reads
  the persisted attempt's `response_payload_json` sidecar, resolves
  `core.instruments.id` per symbol and calls
  `SqlAlchemyDailyBarRepository.upsert_many`. `RawEtlResult` is
  re-exported from `etf_instruments` so both slices share one
  terminal-status shape; the slice-specific `_ProviderPort` Protocol
  is retained because `fetch_daily_bars` (symbols + range) is
  semantically different from `fetch_instruments` (as_of date).
- [`input_snapshot.py`](../../apps/pipeline/src/invest_pipeline/input_snapshot.py)
  exposes a single `create_input_snapshot(uow_factory,
  snapshot_date, instrument_ids)` that builds an `InputSnapshot`,
  deduplicates IDs, opens a UoW, calls
  `uow.input_snapshot_repository.add(snapshot)` and commits.

The services rely on `SqlAlchemyUnitOfWork` as the only transactional
adapter — the asset-level integration is verified through the test
suite without booting a real database in unit tests.

## 7. Provider catalog

[`provider_catalog.py`](../../apps/pipeline/src/invest_pipeline/provider_catalog.py)
is a **declarative** registry — not a runtime factory — that records
the `provider_key`, `role`, `capabilities` and `enabled_by_default`
flag of every Provider V2 knows about by name. The catalog is
stdlib-only (no SDK, HTTP or MCP transport is imported) and is the
code-level mirror of the roles / capabilities listed in
[`DATA-SOURCE-MIGRATION-MATRIX.md` §3 / §6](../../docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md).

Object surface:

- `ProviderRole(StrEnum)` — `RESEARCH_ONLY`, `SECONDARY`, `PRIMARY`,
  `OUT_OF_SCOPE_FOR_ETF`, `FIXTURE_DEV`. String values are frozen by
  the migration matrix and must not change without an ADR.
- `ProviderCapability(StrEnum)` — `RESEARCH`, `MARKET_SNAPSHOT`,
  `ETF_DAILY_BARS`, `ETF_MASTER_DATA`, `INDEX_DAILY_BARS`. The latter
  three exist so the catalog can explicitly **omit** capabilities a
  provider must not advertise.
- `ProviderDeclaration` — a frozen dataclass carrying the four
  declaration fields. The `capabilities` tuple is immutable and
  ordered for deterministic output.
- `lookup_provider(provider_key)` — pure lookup; raises `KeyError`
  with the requested key when the provider is not registered.

The only declaration that ships today is `QUICKTINY_MCP`
(`research_only`, capabilities `RESEARCH` + `MARKET_SNAPSHOT`,
`enabled_by_default=False`). The other Provider entries in the
migration matrix are intentionally deferred until adapter code lands
so the catalog never claims a capability the code does not back
(see the matrix §5.1 rule on "no capability without an adapter").

## 8. Provider error model

[`adapters/errors.py`](../../apps/pipeline/src/invest_pipeline/adapters/errors.py)
defines the exception hierarchy every adapter must raise:

- `ProviderError` (top of tree)
- `ProviderAuthenticationError`, `ProviderRateLimitError`,
  `ProviderTimeoutError`, `ProviderUnavailableError`,
  `ProviderPermanentError`, `ProviderBadResponseError`,
  `ProviderDataContractError`, `ProviderAdapterNotImplementedError`,
  `InvalidProviderCapabilityError`,
  `RealProviderRequiresExplicitEnablementError`, `UnknownProviderError`.

Mapping to `ProviderFailureStage` (domain enum) lives in the same
module; the README documents the rule that the contract failure
detected here translates into an `ERROR`-level RuleOutcome at the
candidate-pool calculator's validation step. The `cifang` placeholder
relies on `ProviderAdapterNotImplementedError` until ADR-0011 §4
unblocks Phase 1 second increment.

## 9. Configuration

`invest_pipeline.config.Settings` mirrors the API's pydantic-settings
contract: `database_url`, `environment`, plus `provider_key` (used by
`Definitions` to gate which adapter is registered — the slice
defaults to `fixture_dev`). Provider-specific settings (`CifangSettings`,
future `AkShareSettings`, …) live next to their adapter and follow
the redaction rules in ADR-0010 §5 / §6 and ADR-0011 §3.

## 10. Pipeline run audit

`SqlAlchemyPipelineRunRepository` writes `ops.pipeline_runs` (six-value
status vocabulary: `queued`, `running`, `succeeded`, `failed`,
`partial`, `cancelled`). Every asset's transaction can therefore be
linked back to a Domain `PipelineRun` value object (with `job_key`,
`trigger_type` and `error_summary` columns — see
[Storage overview](../storage/overview.md#where-each-table-is-written));
the `count_by_status` helper is the basis for the future
`/v1/pipeline-runs` page noted in PR-09 backward planning. The
`PipelineRun` domain object carries `job_key` (non-empty string),
`trigger_type` (non-empty string) and `error_summary` (only set on
`failed` / `partial`); the schema-level CHECK constraint enforces the
six-value status vocabulary.
