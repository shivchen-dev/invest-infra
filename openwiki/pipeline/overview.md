---
type: Concept
title: Pipeline overview
description: Dagster assets, the guarded personal daily schedule and preflight, ETL service modules, the fixture_dev and cifang adapter boundaries, the declarative provider_catalog, and replay/backfill operations wired into the raw / core / analytics / ops PostgreSQL schemas.
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
├── assets.py              # @dg.asset definitions (seed_instruments + etf_* + personal_*)
├── definitions.py         # dg.Definitions + personal_etf_daily_job
├── schedules.py           # guarded Asia/Shanghai personal daily schedule
├── daily_preflight.py     # pure run/skip/fail decision gate
├── config.py              # pydantic-settings Settings (universe + policy paths)
├── provider_catalog.py    # declarative provider role / capability registry
├── provider_factory.py    # build_provider() — runtime fixture_dev / cifangquant selection
├── cifang_smoke.py        # opt-in real-network CifangQuant smoke CLI (ADR-0011 §3)
├── personal_universe.py   # PersonalUniverse YAML loader + resolver
├── personal_daily_cli.py  # manual personal_etf_daily_job driver CLI
├── candidate_pool_service.py  # calculate_and_publish_candidate_pool service
├── adapters/
│   ├── __init__.py        # re-exports FixtureDevInstrumentProvider + error taxonomy
│   ├── errors.py          # ProviderError hierarchy
│   ├── fixture_dev/
│   │   ├── __init__.py
│   │   ├── adapter.py     # FixtureDevInstrumentProvider
│   │   ├── etf_instruments.json
│   │   └── etf_daily_bars.json
│   └── cifang/            # CifangQuant adapter (ADR-0011 Phase 1 + Phase 2)
│       ├── __init__.py
│       ├── adapter.py     # CifangQuantInstrumentProvider (evidence-tuple adapter)
│       ├── client.py      # httpx transport + chunking + error classification
│       ├── mapper.py      # /api/fund/list + /api/fund/hist_em field mappers
│       ├── config.py      # CifangSettings (redacted, disabled by default)
│       └── README.md      # increment-level design notes
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
registers the assets in dependency order and binds the personal daily
job:

```python
personal_etf_daily_job = dg.define_asset_job(
    name="personal_etf_daily_job",
    selection=[
        etf_instruments_raw,
        etf_instruments,
        etf_daily_bars_raw,
        etf_daily_bars,
        etf_input_snapshot,
        personal_candidate_pool,
    ],
)

dg.Definitions(
    assets=[
        seed_instruments,
        etf_instruments_raw,
        etf_instruments,
        etf_input_snapshot,    # daily-partitioned snapshot
        etf_daily_bars_raw,
        etf_daily_bars,
        personal_candidate_pool,   # partition-aligned candidate pool asset
    ],
    jobs=[personal_etf_daily_job],
    schedules=[personal_etf_daily_schedule],
)
```

The registered [`personal_etf_daily_schedule`](../../apps/pipeline/src/invest_pipeline/schedules.py)
triggers the same partitioned job only after its preflight gate passes.
`make pipeline-dev` runs `dagster dev -m invest_pipeline.definitions`,
and `make test-pipeline` runs `ruff check` + `pytest` + an import
check. `make personal-daily-run` is the manual one-command driver for
`personal_etf_daily_job` (see [Personal CLIs](#11-personal-clis)).

### Guarded schedule and preflight

[`daily_preflight.py`](../../apps/pipeline/src/invest_pipeline/daily_preflight.py)
is an infrastructure-free decision gate. In order, it fails future dates,
unknown providers and unavailable personal-universe data; skips weekends,
already-published dates, already-running dates, and (when a caller supplies
one) data that is not ready; and otherwise returns `run / ready`. Loader and
data-check exceptions become the stable failure reasons
`personal_universe_unavailable` and `data_check_failed`.

[`schedules.py`](../../apps/pipeline/src/invest_pipeline/schedules.py)
registers `personal_etf_daily_schedule` for
`personal_etf_daily_job` at `10 16 * * 1-5` in `Asia/Shanghai`. It is
`STOPPED` unless `INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED=true` exactly
(case-insensitive after trimming). A ready tick emits the stable
`run_key=personal-etf-daily:{YYYY-MM-DD}`, the matching partition key, and
`trade_date` / `trigger_type=schedule` tags. A skip returns a Dagster
`SkipReason`; a failed preflight raises a runtime error. The schedule checks
both an existing published candidate-pool run and a running
`ops.pipeline_runs` row, providing two layers of single-run protection.

## 3. Asset graph

```
seed_instruments ───────────────┐
                                ↓
                etf_instruments_raw ──→ etf_instruments ──→ etf_input_snapshot ──→ personal_candidate_pool
                                          │
                                          └──→ etf_daily_bars_raw ──→ etf_daily_bars ──┘
                                                                                       ↑
                                              (partition-aligned on trade_date)
```

`personal_etf_daily_job` selects the six downstream assets
(`etf_instruments_raw` → `etf_daily_bars` → `etf_input_snapshot` →
`personal_candidate_pool`) so the whole personal daily pipeline is
materializable as a single job.

- `seed_instruments` exists for the greenfield slice and seeds the
  canonical rows directly. Production cuts over to the `etf_*`
  assets; the asset is still registered so the slice validation works.
- `etf_instruments_raw` writes the three-layer evidence bundle and
  persists the standardized records inside the SAME raw transaction
  (request → attempt → batch → instruments upsert). The asset now
  resolves the provider through `provider_factory.build_provider()`
  rather than constructing `FixtureDevInstrumentProvider` directly, so
  the `INVEST_PIPELINE_PROVIDER_KEY` setting gates which adapter is
  exercised at runtime.
- `etf_instruments` re-opens a `SqlAlchemyUnitOfWork`, reads the
  attempt's `response_payload_json`, deserialises the records and
  upserts them into `core.instruments`. Both providers and the asset
  use the formal `dataset_key="etf_instruments"`; keeping this raw
  logical key aligned prevents a CifangQuant request from being missed
  by a stale `"instruments"` lookup. If the upstream attempt
  failed the asset returns a `MaterializeResult` with `skipped=True`
  rather than raising, so a contract failure doesn't cascade into a
  Dagster retry storm.
- `etf_daily_bars_raw` / `etf_daily_bars` mirror that pattern for
  `core.daily_bars`; `etf_daily_bars.upsert_many` is the call site
  where the ADR-0006 revision rules apply (no-op on identical
  `row_hash`, `latest+1` on a content change). The raw sidecar stamps
  `source_provider` from the request's actual provider key, preserving
  `cifangquant` provenance instead of defaulting every row to
  `fixture_dev`. The raw writer uses
  `SqlAlchemyProviderRequestRepository.get_or_create` so a re-run of
  the same `(provider_key, dataset_key, request_key)` triple reuses
  the existing `raw.provider_requests` row and allocates a fresh
  `attempt_no` (rather than tripping the
  `uq_provider_requests_logical_key` constraint), keeping reruns
  idempotent. During core upsert, the service scans up to 1,000
  persisted attempts and selects the latest successful one by
  `finished_at` with `attempt_no` as the deterministic tiebreaker;
  storage returns attempts oldest-first, so taking the first success
  could otherwise replay a stale sidecar.
- `etf_input_snapshot` is a `DailyPartitionsDefinition` asset keyed
  by `trade_date` (the partition starts on `2026-07-23`). It loads
  `config/personal-universe.yaml` via `personal_universe.load_personal_universe`,
  resolves every configured symbol to exactly one ETF `Instrument`
  through `personal_universe.resolve_personal_universe`, and stores
  the resulting `InputSnapshot` (see [Personal universe](#9-personal-universe--config)).
  Resolution fails loudly when a symbol is missing, the matched
  instrument is not an ETF on SSE / SZSE, or the symbol is ambiguous
  across rows.
- `personal_candidate_pool` is a `DailyPartitionsDefinition` asset
  that runs the candidate pool service for the partition's trade
  date. It depends on `etf_input_snapshot` (so the snapshot row
  exists) and on `etf_daily_bars` (so the daily bars the calculator
  needs are already persisted). It loads
  `config/candidate-pool-personal.yaml` via
  `load_candidate_pool_policy` and delegates to
  `candidate_pool_service.calculate_and_publish_candidate_pool`
  (see [Candidate pool service](#10-candidate-pool-service)).

All six production assets in this job share the same `DailyPartitionsDefinition`
starting at `2026-07-23`. The master-data assets derive `as_of` only from
`context.partition_key` rather than `date.today()`, and the daily-bars assets
reject explicit date arguments that do not match the partition. This keeps
historical backfills on the requested trade date; `seed_instruments` remains
the intentionally unpartitioned fixture-only path.

## 4. `fixture_dev` adapter

[`FixtureDevInstrumentProvider`](../../apps/pipeline/src/invest_pipeline/adapters/fixture_dev/adapter.py)
is the **only** adapter that ships fully enabled by default; the
[`cifang` adapter](#5-cifang-adapter-adr-0011-phase-1-first--second-increments)
is wired end-to-end but disabled until `CifangSettings.enabled=True`.
`fixture_dev` returns:

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
and the `response_payload_json` round-trip. The fixture is the
default for `INVEST_PIPELINE_PROVIDER_KEY`; production deployment
of `cifangquant` is still blocked on ADR-0011 O-1 / O-3 / O-4, and
the fixture is what the storage + pipeline + API layers exercise
when those open questions are unresolved.

## 5. `cifang` adapter (ADR-0011, Phase 1 first + second increments)

[`apps/pipeline/src/invest_pipeline/adapters/cifang/`](../../apps/pipeline/src/invest_pipeline/adapters/cifang/)
is the CifangQuant Provider adapter documented in
[ADR-0011](../../docs/adr/0011-cifangquant-primary-etf-provider.md)
(Status: Proposed). The package spans two stacked increments; both
keep `CifangSettings.enabled=False` as the authoritative opt-in gate
so CI never reaches the network.

**First increment (configuration + port lock).** Establishes the
public surface:

- [`CifangSettings`](../../apps/pipeline/src/invest_pipeline/adapters/cifang/config.py)
  is a `pydantic-settings` model with `enabled=False` by default,
  `adjustment` locked to the literal `"none"` (rejected otherwise,
  ADR-0005 §4) and `api_key` carried as a `pydantic.SecretStr` whose
  `__repr__` / `__str__` / `redacted_dict()` render `"***"`. The
  env-prefix is `INVEST_PIPELINE_CIFANG_*`.
- [`CifangQuantInstrumentProvider`](../../apps/pipeline/src/invest_pipeline/adapters/cifang/adapter.py)
  exposes the same `fetch_instruments` / `fetch_daily_bars` shape as
  `FixtureDevInstrumentProvider`, so the Domain
  `EtfMarketDataProvider` port is satisfied.

**Second increment (httpx client + field mapper + evidence-tuple
adapter).** Adds the real I/O pieces wired together behind the same
port:

- [`client.py`](../../apps/pipeline/src/invest_pipeline/adapters/cifang/client.py)
  wraps `httpx.Client` with endpoint construction
  (`/api/fund/list`, `/api/fund/hist_em`), `x-api-key` header
  injection, a 10s connect / 30s read timeout, bounded exponential
  backoff (3 attempts, `429 / 500 / 502 / 503 / 504` retryable;
  `401 / 403` mapped to `ProviderAuthenticationError`), and the
  50-symbol chunking rule for `/api/fund/hist_em`. Every transport
  side effect (transport, sleep, clock) is injectable so tests
  replay CI deterministically.
- [`mapper.py`](../../apps/pipeline/src/invest_pipeline/adapters/cifang/mapper.py)
  translates `CifangResponse` payloads into domain
  `Instrument` / `DailyBar` instances. It applies the
  SSE / SZSE allow-list, the ETF filter (non-ETF rows skipped with a
  warning), the `SH → SSE` / `SZ → SZSE` exchange aliasing, the
  nullable `amount` / `prev_close` fields, and the normalisation
  hooks for the real upstream payload shape.
- The `adapter` now reads `CifangSettings.enabled` and refuses to
  reach the network when `False` — both `fetch_*` methods raise
  `RealProviderRequiresExplicitEnablementError` with a pointer to
  ADR-0011 §3 / O-1 / O-3 / O-4. When `enabled=True`, the adapter
  drives the client and mapper, packages a successful (or failed)
  evidence bundle, and emits a `ProviderBatch` whose
  `raw_payload_hash` is the SHA-256 of the parsed payload (the wire
  bytes are SHA-256'd by the client too).
- The top-level
  [`adapters/__init__.py`](../../apps/pipeline/src/invest_pipeline/adapters/__init__.py)
  still does **not** re-export `CifangQuantInstrumentProvider`
  (ADR-0011 §5 defers the public symbol-table change); callers go
  through `from invest_pipeline.adapters.cifang import …` or via
  `provider_factory.build_provider()` (see
  [Provider factory](#12-provider-factory)).

The `cifang` adapter is the only real-network provider wired today.
Real calls require three opt-ins: `CifangSettings.enabled=True` (via
`INVEST_PIPELINE_CIFANG_ENABLED=true`), a non-empty
`INVEST_PIPELINE_CIFANG_API_KEY`, and `--confirm-network` on the
smoke CLI — see [Personal CLIs](#11-personal-clis). The provider
remains gated on ADR-0011 O-1 / O-3 / O-4 closure for production use.

## 6. ETL service modules

The assets wrap testable, asset-agnostic service functions so the
contract tests can drive them without spinning up Dagster:

- [`etf_instruments.py`](../../apps/pipeline/src/invest_pipeline/etf_instruments.py)
  defines `write_etf_instruments_raw(provider, session_factory, as_of=...)`
  and `upsert_etf_instruments(session_factory, as_of=...)`. Both sides
  use the formal `etf_instruments` dataset key across fixture and real
  providers. It is the **single source of truth** for the shared
  `RawEtlResult` dataclass and the `UnitOfWorkFactory` /
  `_coerce_session_factory` helpers both ingestion paths need.
- [`etf_daily_bars.py`](../../apps/pipeline/src/invest_pipeline/etf_daily_bars.py)
  defines `write_etf_daily_bars_raw(provider, session_factory, *,
  symbols, start_date, end_date)` and `upsert_etf_daily_bars(...)`.
  The raw writer distinguishes three failure cases: a failed
  attempt persists only the request + attempt (no batch), a
  successful attempt without batch persists request + attempt +
  marked-partial request status, and a successful attempt with a
  non-empty batch persists all three rows. The request row is
  resolved through `SqlAlchemyProviderRequestRepository.get_or_create`
  and a fresh `attempt_no` is allocated on each call, so a rerun of
  the same `(provider_key, dataset_key, request_key)` does not trip
  the `uq_provider_requests_logical_key` constraint and is therefore
  idempotent. The upsert wrapper reads
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
candidate-pool calculator's validation step. The `cifang` adapter
raises `RealProviderRequiresExplicitEnablementError` whenever
`CifangSettings.enabled=False` and otherwise classifies HTTP / SDK
failures into the same exception types.

## 9. Personal universe & config

The daily pipeline is driven by a personal ETF universe
[`config/personal-universe.yaml`](../../config/personal-universe.yaml)
and a personal candidate-pool policy
[`config/candidate-pool-personal.yaml`](../../config/candidate-pool-personal.yaml).
Both files are versioned, kept outside the application packages and
loaded through small helper modules so the rest of the pipeline
remains unaware of the format:

- [`personal_universe.py`](../../apps/pipeline/src/invest_pipeline/personal_universe.py)
  ships two narrow slices. PR-2A exposes `load_personal_universe(path)`
  which parses the YAML, validates that every symbol is exactly six
  ASCII digits, deduplicates per-symbol entries across groups and
  emits a `PersonalUniverse` frozen value object with a stable
  `content_hash` over the canonical content. PR-2B adds
  `resolve_personal_universe(universe, lookup)` which aligns every
  symbol to **exactly one** ETF `Instrument` on SSE / SZSE via an
  injected `InstrumentLookup` callable. The resolver raises
  `PersonalUniverseMissingSymbolError`,
  `PersonalUniverseInvalidInstrumentError`, or
  `PersonalUniverseAmbiguousSymbolError` for every resolution failure
  mode so a stale YAML or a mis-classified `core.instruments` row is
  surfaced loudly rather than silently producing a partial snapshot.
  The resolver is database-free; the Dagster asset wires it to the
  storage layer.
- [`Settings`](../../apps/pipeline/src/invest_pipeline/config.py)
  resolves `personal_universe_path` and
  `candidate_pool_policy_path` from
  `INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH` /
  `INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH`, falling back to
  `config/personal-universe.yaml` and
  `config/candidate-pool-personal.yaml`.

The `personal-universe.yaml` file declares groups (e.g.
`broad_market`, `technology`, `overseas`) and an `enabled_groups`
list; only the symbols in enabled groups contribute to the universe.
The `candidate-pool-personal.yaml` file supplies
`algorithm.{key,version,parameter_set_key}`,
`eligibility.{min_volume,min_amount}` and `selection.max_candidates`
— the calculator's other structural fields are filled with explicit
legal defaults so the minimum calculator receives a well-formed
`CandidatePoolPolicy` (see [Candidate pool service](#10-candidate-pool-service)).

## 10. Candidate pool service

[`candidate_pool_service.py`](../../apps/pipeline/src/invest_pipeline/candidate_pool_service.py)
hosts the Dagster-free application service that the
`personal_candidate_pool` asset wraps:

- `load_candidate_pool_policy(path)` parses
  `config/candidate-pool-personal.yaml` into a fully-formed
  `CandidatePoolPolicy` (the smaller YAML surface is enough to drive
  the PR-08 minimum calculator without inventing scoring behaviour).
- `calculate_and_publish_candidate_pool(uow_factory, *,
  trade_date, snapshot_id, policy)` resolves the persisted
  `InputSnapshot` by id (raising
  `CandidatePoolSnapshotNotFoundError` if missing), reads the
  partition's latest daily bars through `Adjust.NONE`, runs
  `DefaultMinimumCandidatePoolCalculator.calculate(...)`, persists
  one `CandidatePoolRun` plus every `CandidatePoolItem` inside a
  single `UnitOfWork`, and transitions the run through the existing
  repository state machine (`CALCULATED → VALIDATED → PUBLISHED`).
- The slice is intentionally minimal: no asset wiring, no
  superseded state, no publication pipeline. The state-machine
  transitions are delegated to
  `SqlAlchemyCandidatePoolRunRepository.transition_status`, which
  enforces the legal-transition set from
  [Candidate pool](../domain/candidate-pool.md#1-state-machine).

The PR-08 minimum algorithm covers `no_data` / `suspended` /
`invalid_price` / `low_volume` / `low_amount` exclusions and ranks
included items by `close * volume` with `uuid.bytes` as the
deterministic tiebreaker (see
[Candidate pool §4](../domain/candidate-pool.md#4-the-minimum-calculators-exclusion-tree)).

## 11. Personal CLIs

Two CLIs land alongside the personal pipeline:

- [`cifang_smoke.py`](../../apps/pipeline/src/invest_pipeline/cifang_smoke.py)
  is an opt-in smoke against the real CifangQuant HTTP API
  (`make provider-smoke`). It requires **three** opt-ins — the
  `CifangSettings.enabled=True` setting, a non-empty
  `INVEST_PIPELINE_CIFANG_API_KEY`, and the explicit
  `--confirm-network` CLI flag — and refuses to construct the
  adapter when any of them is missing. On success it emits a single
  redacted JSON line (provider key, trade date, instrument count,
  daily-bar count, batch status); it never prints the API key,
  raw payload, headers or exception reprs.
- [`personal_daily_cli.py`](../../apps/pipeline/src/invest_pipeline/personal_daily_cli.py)
  is the manual `personal_etf_daily_job` driver
  (`make personal-daily-run`). It validates `--trade-date`, accepts
  optional `--universe` / `--policy` overrides that are mapped to
  the corresponding env vars before `definitions.defs` is imported,
  enforces the same `confirm-network` gate for `cifangquant`, and
  emits a single safe-counts JSON line on success. Fixture / dev
  runs never need `--confirm-network`. The default CLI also starts an
  `ops.pipeline_runs` audit row with `job_key=personal_etf_daily_job`,
  `trigger_type=manual`, and the trade-date partition, then marks it
  succeeded or failed. The single-run guard calls
  `SqlAlchemyPipelineRunRepository.get_blocking_by_job_and_partition`
  so an already `queued` / `running` / `succeeded` row for the same
  partition causes the recorder to skip the new `running` insert; only
  `failed` / `partial` / `cancelled` prior rows are treated as
  retryable and a fresh audit row is opened (see
  [Storage overview](../storage/overview.md#pipeline-run-audit-guards)).
  Audit insertion and terminal-state updates are
  best-effort: database errors produce a warning but never replace the
  job's summary or exit code, and recorded failure summaries scrub the
  configured provider token. The CLI also pins the market clock
  through `invest_pipeline.clock.market_today()` so the trade-date
  validation and the preflight gate agree on the same `Asia/Shanghai`
  business date.

For operations, [`make reprocess-date`](../../Makefile) is the canonical
single-date replay alias; it requires `TRADE_DATE` and delegates to the same
manual CLI, so it preserves the pipeline's idempotency behavior. The
`personal-backfill` target loops through an inclusive date range in
chronological order, validates a maximum of 90 natural days, skips weekends,
and aborts on the first failed weekday. Its shell-side date validation uses
GNU `date -d`, so macOS operators need an equivalent GNU date implementation.
The authentication and replay procedures are maintained in
[`docs/runbooks/cifang-auth-failure.md`](../../docs/runbooks/cifang-auth-failure.md)
and [`docs/runbooks/reprocess-trade-date.md`](../../docs/runbooks/reprocess-trade-date.md).

## 12. Provider factory

[`provider_factory.py`](../../apps/pipeline/src/invest_pipeline/provider_factory.py)
is the runtime selection surface for the personal pipeline. The
factory has three branches and three explicit failure modes:

- `fixture_dev` → `FixtureDevInstrumentProvider()`.
- `cifangquant` → `CifangQuantInstrumentProvider(CifangSettings())`;
  raises `RealProviderRequiresExplicitEnablementError` when
  `CifangSettings.enabled=False` and
  `ProviderAuthenticationError` when `api_key` is empty.
- Anything else → `UnknownProviderError` carrying the offending key.

The factory never silently falls back to the fixture provider, so a
misconfigured `INVEST_PIPELINE_PROVIDER_KEY` is surfaced at job-start
time, not at fetch time. `KNOWN_PROVIDER_KEYS` is exported as a
frozen tuple for documentation and testing.

## 13. Configuration

`invest_pipeline.config.Settings` mirrors the API's pydantic-settings
contract:

- `database_url` (default points at the local `postgres:5432/invest`
  service).
- `provider_key` (default `fixture_dev`, env
  `INVEST_PIPELINE_PROVIDER_KEY`) — selected by
  `provider_factory.build_provider()`.
- `personal_universe_path` (default
  `config/personal-universe.yaml`, env
  `INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH`).
- `candidate_pool_policy_path` (default
  `config/candidate-pool-personal.yaml`, env
  `INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH`).

Provider-specific settings (`CifangSettings`, future
`AkShareSettings`, …) live next to their adapter and follow the
redaction rules in ADR-0010 §5 / §6 and ADR-0011 §3.

## 14. Pipeline run audit

`SqlAlchemyPipelineRunRepository` writes `ops.pipeline_runs` (six-value
status vocabulary: `queued`, `running`, `succeeded`, `failed`,
`partial`, `cancelled`). The manual `personal_daily_cli` now uses this
repository through `SqlAlchemyPipelineRunRecorder`, recording a
`running → succeeded|failed` lifecycle in transactions separate from
the Dagster job; audit failures are non-fatal so they cannot mask the
primary run result. Every asset's transaction can therefore be
linked back to a Domain `PipelineRun` value object (with `job_key`,
`trigger_type` and `error_summary` columns — see
[Storage overview](../storage/overview.md#where-each-table-is-written));
the `count_by_status` helper is the basis for the future
`/v1/pipeline-runs` page noted in PR-09 backward planning. The
`PipelineRun` domain object carries `job_key` (non-empty string),
`trigger_type` (non-empty string) and `error_summary` (only set on
`failed` / `partial`); the schema-level CHECK constraint enforces the
six-value status vocabulary.
