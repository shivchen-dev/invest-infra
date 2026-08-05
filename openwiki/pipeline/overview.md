---
type: Concept
title: Pipeline overview
description: Dagster assets, the guarded personal daily schedule and preflight, ETL service modules, the fixture_dev, cifang, akshare and tushare adapter boundaries, the MCP research transports, the DC-2 ETF profile collection and the Stage 4A evidence/context builders, the declarative provider_catalog and deterministic provider-routing layer, the read-only provider coverage CLI, and replay/backfill operations wired into the raw / core / analytics / ops PostgreSQL schemas.
resource: /openwiki/pipeline/overview.md
tags: [pipeline, dagster, adapters, etl, fixture_dev, cifang, akshare, tushare, provider-catalog, provider-routing, coverage, historical-backfill, etf-profile, research-context]
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
├── clock.py               # market_today() — pinned Asia/Shanghai business clock
├── credentials.py         # centralised, lazy provider-credential lookup
├── request_keys.py        # deterministic bounded logical request keys
├── provider_catalog.py    # declarative provider role / capability registry
├── provider_factory.py    # build_provider() — runtime fixture_dev / cifangquant / akshare / tushare
├── provider_quality.py    # DC-1 provider registry contract
├── provider_consistency.py # provider daily-bar consistency comparison
├── provider_routing/      # deterministic dataset × capability routing layer (PR-05)
│   ├── datasets.py        # Dataset StrEnum + DATASET_CAPABILITIES mapping
│   ├── selection.py       # select_providers() pure function
│   ├── coverage.py        # calculate_coverage() pure grid
│   └── probe.py           # build_coverage_samples() input builder
├── candidate_routing/     # dynamic candidate shadow MVP
│   └── shadow.py          # shadow run probe
├── provider_coverage_report.py   # CoverageReportModel + deterministic content hash
├── provider_coverage_plan.py     # select_active_etf_symbols + build_backfill_plan
├── provider_coverage_merge.py    # deterministic multi-provider report merge
├── provider_coverage_cli.py      # read-only coverage CLI (PR-05)
├── historical_daily_bars_cli.py  # guarded historical ETF backfill CLI
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
│   ├── cifang/            # CifangQuant adapter (ADR-0011 Phase 1 + Phase 2)
│   │   ├── adapter.py     # CifangQuantInstrumentProvider (evidence-tuple adapter)
│   │   ├── client.py      # httpx transport + chunking + error classification
│   │   ├── mapper.py      # /api/fund/list + /api/fund/hist_em field mappers
│   │   ├── config.py      # CifangSettings (redacted, disabled by default)
│   │   └── README.md
│   ├── akshare/           # AkShare ETF data adapter (PR-02 + DC-2 ETF Profile)
│   │   ├── adapter.py     # AkshareInstrumentProvider (Sina-pref + Eastmoney fallback; +fetch_etf_profile)
│   │   ├── client.py      # lazy akshare SDK resolver + per-symbol ETF calls
│   │   ├── mapper.py      # fund_etf_fund_info_em + fund_etf_hist_em + NAV/calendar + ETF profile mappers
│   │   ├── config.py      # AkshareSettings (redacted, disabled by default, adjust="")
│   │   └── README.md
│   ├── tushare/           # Tushare Pro adapter (Phase 1 bounded increment)
│   │   ├── __init__.py
│   │   ├── adapter.py     # TushareInstrumentProvider (evidence-tuple adapter)
│   │   ├── client.py      # POST-JSON TushareClient (fund_basic / fund_daily)
│   │   ├── mapper.py      # /api/fund_basic + /api/fund_daily field mappers
│   │   └── config.py      # TushareSettings (redacted, adjust="none", disabled by default)
│   ├── quicktiny_mcp/     # QuickTiny MCP read-only transport (PR-03, research_only)
│   │   ├── client.py      # JSON-RPC 2.0 over httpx (initialize / tools/list / tools/call)
│   │   ├── config.py      # QuickTinyMcpSettings (redacted, default base_url frozen)
│   │   ├── models.py      # frozen response / result dataclasses
│   │   └── README.md
│   └── rsscast/           # RssCast MCP read-only transport (PR-04, research / index)
│       ├── client.py      # JSON-RPC 2.0 + ETF-DailyBar-shaped tool name rejection
│       ├── config.py      # RssCastMcpSettings (redacted, base_url NOT frozen)
│       ├── models.py      # is_forbidden_tool_name guard
│       └── README.md
├── etf_instruments.py     # write_etf_instruments_raw / upsert_etf_instruments
│                         # (owns RawEtlResult + UnitOfWorkFactory helpers)
├── etf_daily_bars.py      # write_etf_daily_bars_raw / upsert_etf_daily_bars
│                         # (re-exports RawEtlResult from etf_instruments)
├── etf_profiles.py        # write_etf_profiles_raw / upsert_etf_profiles (DC-2)
├── etf_profile_context.py # build_etf_profile_context_pack (Stage 4A context slice)
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
and [`akshare` adapter](#5b-akshare-adapter-pr-02)
are wired end-to-end but disabled until the relevant `*Settings.enabled=True`.
`fixture_dev` returns:

- **ETF instruments** from `fixture_dev/etf_instruments.json` — 16
  active SSE / SZSE ETF symbols covering the broad-market, sector
  and bond categories used throughout the slice.
- **ETF daily bars** from `fixture_dev/etf_daily_bars.json` — six
  trading days (2026-07-23..2026-07-30) of OHLCV rows including a
  deliberately mixed `trading_status` (mix of `normal` and
  `suspended`) so the calculator's `suspended` exclusion path is
  exercised by the test suite.

The adapter's role is **purely deterministic**: serialise-deserialise
helpers keep the standardisation tests honest about sidecar shapes
and the `response_payload_json` round-trip. The fixture is the
default for `INVEST_PIPELINE_PROVIDER_KEY`; production deployment
of `cifangquant` and `akshare` is still blocked on ADR-0011 O-1 /
O-3 / O-4, and the fixture is what the storage + pipeline + API
layers exercise when those open questions are unresolved.

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

The `cifang` adapter is the only ETF daily-bars **provider that has
been exercised end-to-end against a real network in this slice**.
Real calls require three opt-ins: `CifangSettings.enabled=True` (via
`INVEST_PIPELINE_CIFANG_ENABLED=true`), a non-empty
`INVEST_PIPELINE_CIFANG_API_KEY`, and `--confirm-network` on the
smoke CLI — see [Personal CLIs](#11-personal-clis). The provider
remains gated on ADR-0011 O-1 / O-3 / O-4 closure for production use.
[`akshare`](#5b-akshare-adapter-pr-02) and
[`tushare`](#5d-tushare-pro-adapter-phase-1-bounded-increment) are
also fully wired in the factory. The historical three-provider plan
(`eastmoney` / `sina` / `tonghuashun` Phase-1 stubs) was de-scoped
in this slice; see [Provider catalog](#7-provider-catalog) for the
six remaining catalog declarations.

## 5b. `akshare` adapter (PR-02)

[`apps/pipeline/src/invest_pipeline/adapters/akshare/`](../../apps/pipeline/src/invest_pipeline/adapters/akshare/)
is the read-only AkShare provider documented in
[`DATA-SOURCE-MIGRATION-MATRIX.md` §2 / §5.4 / §10](../../docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md).
The package mirrors the Cifang layer separation (`client.py` is the
only module that may import the `akshare` SDK; the import is
performed lazily in `_resolve_module()` and surfaces
`ProviderUnavailableError` on `ImportError` so CI never fails
purely because the optional SDK is absent).

- [`config.py`](../../apps/pipeline/src/invest_pipeline/adapters/akshare/config.py) ships `AkshareSettings` with
  `enabled=False` default, `adjust` **locked to `""`** (the
  AkShare "no adjustment" literal; ADR-0005 §4 forbids `hfq` /
  `qfq`), `timeout_seconds > 0`, optional `SecretStr` token, and a
  `redacted_dict()` that masks the token.
- [`adapter.py`](../../apps/pipeline/src/invest_pipeline/adapters/akshare/adapter.py) exposes
  `AkshareInstrumentProvider` with the same
  `EtfMarketDataProvider` surface as Cifang, plus three read-only
  extensions: `fetch_nav(symbol)` (which rides on
  `AkshareNavRecord` — `unit_nav` / `accumulated_nav` /
  `daily_growth_rate`; **NAV is never coerced to OHLCV** per the
  V2 plan §5 Task 2 invariant), `fetch_trading_calendar()` (date-only
  records), and `fetch_etf_profile()` (the DC-2 ETF Profile surface —
  fans out to `ak.fund_name_em()` and `ak.fund_etf_spot_em()`,
  joins the payloads by `基金代码` in `merge_etf_profile`, and stamps
  the result on a dedicated `ProviderBatch` with
  `dataset_key="etf_profile"`).
- [`client.py`](../../apps/pipeline/src/invest_pipeline/adapters/akshare/client.py) lazily resolves the
  optional `akshare` SDK; every call uses `hasattr(module, operation)`
  and raises `ProviderUnavailableError` on missing operations. The
  DC-2 Profile slice added `fetch_fund_name_em` and
  `fetch_fund_etf_spot_em`; the upstream `总市值` column is read
  but explicitly **not** mapped to `aum` (AUM is a Provider-disclosed
  figure, not a market-cap calculation).
- [`mapper.py`](../../apps/pipeline/src/invest_pipeline/adapters/akshare/mapper.py) translates
  `fund_etf_fund_info_em` and `fund_etf_hist_em` responses (plus
  the NAV / calendar / ETF profile surfaces) into domain
  `Instrument` / `DailyBar` / `AkshareProfileRecord` rows. As of `07cfd65` the
  `fetch_daily_bars` loop prefers Sina (`fund_etf_hist_sina`) and
  falls back to Eastmoney (`fund_etf_hist_em`); the resulting
  `DailyBar.source.provider_key` records which upstream actually
  served the row, so a Sina-success path is distinguishable from an
  Eastmoney-fallback path in the raw evidence tables. The DC-2
  slice adds `merge_etf_profile` (joins the `fund_name_em` /
  `fund_etf_spot_em` payloads by symbol) and
  `map_etf_profile_to_field_evidence` (the PR-ETF-PROFILE-02
  Provider Mapping slice that converts the merged
  `AkshareProfileRecord` rows into domain `FieldEvidence` rows for
  `FUND_TYPE` / `CATEGORY` / `SHARES` only — `AUM` and
  `MARKET_VALUE` are deliberately never emitted here).
- The `provider_factory` exposes `akshare` as the third runtime
  branch — see [Provider factory](#12-provider-factory) — and
  raises `RealProviderRequiresExplicitEnablementError` when
  `AkshareSettings.enabled=False`. When the optional `akshare`
  SDK is missing, factory construction still succeeds; the
  `ProviderUnavailableError` is raised at fetch time so a
  misconfigured deployment never silently succeeds.

`make` does not yet expose a `provider-smoke` target for AkShare; the
single-ETF / 16-symbol batch probes recorded in
[`docs/implementation/PROVIDER-COVERAGE-2026-08-04.md`](../../docs/implementation/PROVIDER-COVERAGE-2026-08-04.md)
were driven directly through `python -m
invest_pipeline.provider_coverage_cli`. As of 2026-08-04 the SDK
is installed and importable but the 16-symbol batch hit
`ProxyError / RemoteDisconnected` against EastMoney via the local
proxy; a real full-coverage verdict is pending network recovery.

## 5c. MCP research transports (PR-03 QuickTiny, PR-04 RssCast)

Two read-only MCP adapters share the same JSON-RPC 2.0 envelope but
intentionally do **not** map responses to `DailyBar`:

- [`adapters/quicktiny_mcp/`](../../apps/pipeline/src/invest_pipeline/adapters/quicktiny_mcp/)
  talks to `https://stock.quicktiny.cn/api/mcp` (the
  matrix §9.1 official endpoint) with `initialize` / `tools/list` /
  `tools/call` methods. `QuickTinyMcpSettings` defaults to
  `enabled=False`, `base_url` frozen to the official endpoint,
  bounded timeout, and redacted `SecretStr` token. PR-03 deliberately
  ships transport only — no `etf_market` → `DailyBar` mapping per
  matrix §3 / §5.4 / §9.2 — so the catalog advertises only
  `RESEARCH` and `MARKET_SNAPSHOT`.
- [`adapters/rsscast/`](../../apps/pipeline/src/invest_pipeline/adapters/rsscast/) shares the
  JSON-RPC envelope but **rejects ETF-DailyBar-shaped tool names**
  (`etf_daily_bars`, `fund_history`, `etf_kline_em`, …) at
  `call_tool` time via `is_forbidden_tool_name`, raising
  `ProviderDataContractError("RSSCAST_ETF_DAILY_BARS_FORBIDDEN")` so
  a misconfigured caller cannot accidentally promote an upstream
  ETF-DailyBar-shaped response into a `core.daily_bars` row.
  `RssCastMcpSettings` defaults to `enabled=False` and `base_url=""`
  — matrix §1 explicitly notes that the archive did not freeze a
  fixed endpoint, so operators must set
  `INVEST_PIPELINE_RSSCAST_BASE_URL` before enabling the adapter.

Neither adapter extends `provider_factory.build_provider`; both are
exercised only through the catalog declaration. The MCP transports
are research-only — they do not write to PostgreSQL, do not
participate in the `personal_etf_daily_job` and do not reach the
Dagster asset graph. CI uses `httpx.MockTransport` so the suite
never opens a TCP connection.

## 5d. Tushare Pro adapter (Phase 1 bounded increment)

[`apps/pipeline/src/invest_pipeline/adapters/tushare/`](../../apps/pipeline/src/invest_pipeline/adapters/tushare/)
is the read-only Tushare Pro adapter that PR-02 / DC-1 added as a
secondary ETF source. The package mirrors the Cifang layer
separation (`client.py` is the only module that may issue
HTTP/POST-JSON; the mapper is pure):

- [`config.py`](../../apps/pipeline/src/invest_pipeline/adapters/tushare/config.py) ships `TushareSettings`
  with `enabled=False` default, `adjust` **locked to `"none"`**
  (ADR-0005 §4), and a `SecretStr` token whose `__repr__` / `__str__`
  / `redacted_dict()` masks the value. The token is read from the
  centralized credential store at request time only
  (`TushareSettings.resolved_token()`) so the settings object is
  safe to construct in CI without credentials being present.
- [`client.py`](../../apps/pipeline/src/invest_pipeline/adapters/tushare/client.py) wraps
  `httpx.Client` against the single `https://api.tushare.pro`
  endpoint with a `POST` JSON body of
  `{api_name, token, params, fields}`. The client is inert until
  the first `fetch_*` call; constructor injection lets tests
  substitute a `FakeTushareClient` and the suite never opens a
  real TCP connection.
- [`mapper.py`](../../apps/pipeline/src/invest_pipeline/adapters/tushare/mapper.py) translates
  `fund_basic` and `fund_daily` payloads into domain
  `Instrument` / `DailyBar` instances. The slice is intentionally
  bounded to the two documented ETF surfaces; the SSE / SZSE
  allow-list and the `SH → SSE` / `SZ → SZSE` exchange aliasing
  mirror the Cifang mappers.
- [`adapter.py`](../../apps/pipeline/src/invest_pipeline/adapters/tushare/adapter.py) exposes
  `TushareInstrumentProvider` with the same
  `EtfMarketDataProvider` surface as the Cifang / AkShare adapters
  (`fetch_instruments` / `fetch_daily_bars`). The provider reads
  `TushareSettings.enabled` and refuses to reach the network when
  `False` — both `fetch_*` methods raise
  `RealProviderRequiresExplicitEnablementError` with a pointer to
  the centralized credential store. When `enabled=True`, the
  adapter drives the client and mapper, packages a successful (or
  failed) evidence bundle, and emits a `ProviderBatch` whose
  `raw_payload_hash` is the SHA-256 of the parsed payload.
- The `provider_factory` exposes `tushare` as the fourth runtime
  branch — see [Provider factory](#12-provider-factory) — and
  raises `RealProviderRequiresExplicitEnablementError` when
  `TushareSettings.enabled=False` and `ProviderAuthenticationError`
  when the token is empty. Construction always succeeds; the
  token is read lazily on the first request so a CI build can
  construct the provider without the secret file being present.

### Centralized credential store

[`apps/pipeline/src/invest_pipeline/credentials.py`](../../apps/pipeline/src/invest_pipeline/credentials.py)
is the single source of truth for provider credentials:

- `DEFAULT_SECRETS_DIR` is `/home/claw/invest-secrets`; the env
  variable `INVEST_PIPELINE_SECRETS_DIR` overrides the root.
- The `_CREDENTIAL_FILES` table maps every supported provider_key
  to its filename inside the secrets directory
  (`cifangquant.api_key` / `akshare.token` / `rsscast.token` /
  `tushare.token`).
- `CredentialStore.resolve(provider_key, explicit_value="")` returns
  the explicit value when supplied and otherwise reads and trims
  the matching file. Unknown provider_keys raise `ValueError`;
  `OSError` from a malformed file becomes a `RuntimeError` that
  never embeds the credential value.
- Per-adapter settings classes (`CifangSettings.api_key` /
  `AkshareSettings.token` / `RssCastMcpSettings.token` /
  `TushareSettings.token`) call
  `CredentialStore().resolve(provider_key, explicit_value)` so the
  explicit `INVEST_PIPELINE_*` env-var override remains the
  highest-priority path; the centralized file is the fallback.

The historical V2 three-provider plan
([`tasks/plan-data-source-three-provider.md`](../../tasks/plan-data-source-three-provider.md))
once proposed standalone `eastmoney` / `sina` / `tonghuashun`
adapters. That plan has been **de-scoped** in this slice: the
three sources are not selectable runtime providers in V2 and the
catalog carries no declaration for them. Their public
historical-quotes endpoints remain internal upstreams of the
AkShare aggregator (`fund_etf_hist_sina` / `fund_etf_hist_em`)
and surface only as `source_key` values on `BarSource` rows
produced by the AkShare adapter.

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
- [`etf_profiles.py`](../../apps/pipeline/src/invest_pipeline/etf_profiles.py)
  is the DC-2 ETF Profile ETL service. `write_etf_profiles_raw(provider,
  session_factory, *, unit_of_work_factory=SqlAlchemyUnitOfWork)`
  drives the `provider.fetch_etf_profile()` call and persists the
  PR-02 three-layer evidence bundle to `raw.provider_*` with
  `dataset_key="etf_profile"`, `request_key="etf-profile"` and a
  single JSONB sidecar that carries every `AkshareProfileRecord`
  (symbol / exchange / `fund_type` / `category` / `shares`).
  `upsert_etf_profiles(session_factory, *, ...)` re-opens a fresh
  UoW, locates the latest successful attempt for the
  `(provider_key, dataset_key="etf_profile", request_key="etf-profile")`
  triplet, deserialises the sidecar, resolves the real
  `core.instruments.id` per `(symbol, exchange)` and upserts the
  standardised profile records into `core.etf_profiles`. The
  function also persists the per-field `FieldEvidence` rows through
  `uow.etf_profile_fields` so the resolver's read path stays
  pre-populated. The slice stays conservative: `aum` / `manager` /
  `benchmark_index` / `inception_date` / `management_fee` /
  `custody_fee` stay `None` until a dedicated profile endpoint is
  verified, the `total_market_value` column from `fund_etf_spot_em`
  is never aliased to `aum`, and NAV remains on the dedicated
  `fund_etf_fund_daily_em` path.
- [`etf_profile_context.py`](../../apps/pipeline/src/invest_pipeline/etf_profile_context.py)
  is the pure pipeline builder for the `etf_profile`
  `ResearchContextPack` (Stage 4A evidence / context separation).
  `build_etf_profile_context_pack(evidence_rows, *, instrument_id,
  observed_at, created_at=None, context_version=1)` runs the
  domain `resolve_etf_profile_evidence` resolver, projects every
  canonical `FieldKey` (`MANAGER` / `BENCHMARK_INDEX` / `CATEGORY` /
  `INCEPTION_DATE` / `FUND_TYPE` / `MANAGEMENT_FEE` / `CUSTODY_FEE` /
  `AUM` / `SHARES`) into a `ContextItem` whose `quality_status`
  is `COMPLETE` / `CONFLICT` / `MISSING` according to the
  resolver's `ResolutionStatus`, and returns a hash-stable
  `ResearchContextPack` ready for `uow.research_context_packs`.
  The builder never fabricates a Provider identifier for a
  `MISSING` field; the audit chain is anchored on the resolver-side
  `"resolver"` / `"etf_profile_resolution"` provenance so the
  `ContextItem` still has a stable source reference without an
  invented value.

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

The catalog registers **six** frozen declarations
(`apps/pipeline/src/invest_pipeline/provider_catalog.py`):

| Key | Role | Capabilities | `enabled_by_default` |
|---|---|---|---|
| `akshare` | `research_only` | `ETF_DAILY_BARS` / `ETF_MASTER_DATA` / `INDEX_DAILY_BARS` | `False` |
| `cifangquant` | `secondary` | `ETF_DAILY_BARS` / `ETF_MASTER_DATA` / `INDEX_DAILY_BARS` | `False` |
| `fixture_dev` | `fixture_dev` | `ETF_DAILY_BARS` / `ETF_MASTER_DATA` | `True` |
| `quicktiny_mcp` | `research_only` | `RESEARCH` / `MARKET_SNAPSHOT` | `False` |
| `rsscast` | `out_of_scope_for_etf` | `INDEX_DAILY_BARS` / `RESEARCH` | `False` |
| `tushare` | `secondary` | `ETF_DAILY_BARS` / `ETF_MASTER_DATA` | `False` |

The negative-capability contract is part of the public catalog
contract: `quicktiny_mcp` and `rsscast` must never advertise
`ETF_DAILY_BARS` or `ETF_MASTER_DATA` (matrix §3 / §5.4 / §9.2
forbid it), and a future regression that silently re-adds an
ETF daily-bars capability to a research-only source would
violate the catalog's frozen string values. `iter_provider_declarations()`
returns the declarations in ascending `provider_key` order so
tests and the routing layer can iterate the catalog without
depending on `dict` insertion order. `lookup_provider(key)` raises
`KeyError(key)` so callers can assert on the offending key.

The deterministic routing / coverage layer that consumes this
catalog lives in `provider_routing/` (`select_providers`,
`calculate_coverage`, `build_coverage_samples`) together with the
operator-facing `provider_coverage_*` helpers and the
`provider_coverage_cli` runner; the canonical home for that
material is §12 ([Provider factory](overview.md#12-provider-factory)).

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

The fourth CLI, [`historical_daily_bars_cli.py`](../../apps/pipeline/src/invest_pipeline/historical_daily_bars_cli.py),
is the guarded historical ETF daily-bars backfill driver. It is
paired with the [`make historical-daily-bars-backfill`](../../Makefile)
target and:

- Replays `write_etf_daily_bars_raw` + `upsert_etf_daily_bars` over
  an inclusive `[start_date, end_date]` range, chunked into at most
  90 natural-day blocks processed in order. Both arguments are
  required, must parse as `YYYY-MM-DD`, and `end_date` must not be
  in the future; the CLI raises `HistoricalDailyBarsCLIConfigError`
  (exit `2`) for any of these without importing Dagster or
  touching any DB state.
- Accepts an optional `--universe` override that maps to
  `INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH` **before**
  `invest_pipeline.config.get_settings()` is first hit (settings are
  `lru_cache`-d).
- Validates `--provider-key` against the
  `KNOWN_PROVIDER_KEYS` tuple — only `fixture_dev` and
  `cifangquant` are admitted (the Cifang branch additionally
  requires the documented triple opt-in). AkShare and Tushare are
  **not** accepted by the historical backfill CLI in this slice even
  though the factory wires them; align this gap before any
  historical run depends on the third or fourth runtime provider.
- Persists through `SqlAlchemyUnitOfWork` and reuses the
  `RawEtlResult` shape from `etf_daily_bars` /
  `etf_instruments` so the rerun idempotency contract
  (`get_or_create` on `(provider_key, dataset_key, request_key)`)
  remains single-source.
- Stops at the first chunk whose attempt is not `succeeded` and
  exits `3`; never prints the API key, raw payload, headers or
  exception reprs. Exits `2` for configuration errors, `0` for
  success.

## 12. Provider factory

[`provider_factory.py`](../../apps/pipeline/src/invest_pipeline/provider_factory.py)
is the runtime selection surface for the personal pipeline. The
factory has four branches and four explicit failure modes:

- `fixture_dev` → `FixtureDevInstrumentProvider()`.
- `cifangquant` → `CifangQuantInstrumentProvider(CifangSettings())`;
  raises `RealProviderRequiresExplicitEnablementError` when
  `CifangSettings.enabled=False` and
  `ProviderAuthenticationError` when the resolved API key (env
  override or centralized file) is empty.
- `akshare` → `AkshareInstrumentProvider(AkshareSettings())`;
  raises `RealProviderRequiresExplicitEnablementError` when
  `AkshareSettings.enabled=False`. Construction succeeds even when
  the optional `akshare` SDK is absent; the inner
  `AkshareClient` surfaces `ProviderUnavailableError` at fetch
  time (not at construction time) so a missing optional
  dependency never silently swaps in another provider.
- `tushare` → `TushareInstrumentProvider(TushareSettings())`;
  raises `RealProviderRequiresExplicitEnablementError` when
  `TushareSettings.enabled=False` and `ProviderAuthenticationError`
  when the resolved token is empty. The token is read from
  `TushareSettings.resolved_token()` (env override → centralized
  `tushare.token` file) lazily on the first request, so the
  factory can construct the provider without the secret file
  being present.
- Anything else → `UnknownProviderError` carrying the offending key.

The factory never silently falls back to the fixture provider, so a
misconfigured `INVEST_PIPELINE_PROVIDER_KEY` is surfaced at job-start
time, not at fetch time. `KNOWN_PROVIDER_KEYS = ("fixture_dev",
"cifangquant", "akshare", "tushare")` is exported as a frozen tuple
for documentation and testing, and `test_provider_factory_runtime.py`
pins that exact tuple so a fifth runtime branch cannot land
without an explicit test update. The `cifangquant` /
`akshare` / `tushare` settings objects accept an injected
pre-built instance so hermetic tests never have to touch real
environment variables; the `provider_key` itself is read from
`Settings.provider_key` (`INVEST_PIPELINE_PROVIDER_KEY`).

### Provider routing layer (`provider_routing/`)

[`apps/pipeline/src/invest_pipeline/provider_routing/`](../../apps/pipeline/src/invest_pipeline/provider_routing/)
is the deterministic dataset × declaration selection layer PR-05
adds on top of the catalog. It is pure (never imports the factory,
network or DB) and exports four small modules:

- `datasets.py` freezes five dataset identifiers
  (`ETF_DAILY_BARS` / `ETF_INSTRUMENTS` / `INDEX_DAILY_BARS` /
  `RESEARCH` / `MARKET_SNAPSHOT`) plus the canonical
  `DATASET_CAPABILITIES` mapping each dataset uses. The string
  values are persisted in `raw.provider_requests.dataset_key` so
  a change here requires a migration. Note that
  `Dataset.ETF_INSTRUMENTS` resolves to the `ETF_MASTER_DATA`
  capability to keep backwards compatibility with already-persisted
  `etf_instruments` rows.
- `selection.py` exports the pure `select_providers(declarations,
  dataset, *, enabled_only=True, exclude_research_only_for_etf_daily_bars=True)`
  function. Three documented rules apply in order: capability
  match (declaration must advertise the required capability);
  default-enable gate (when `enabled_only=True`, declarations with
  `enabled_by_default=False` are dropped — keeps the function safe
  in dev without silently enabling a third-party API); and the
  research-only-rejection rule, which is **scoped to
  `ETF_DAILY_BARS` / `ETF_INSTRUMENTS`** (matrix §5.4 "no
  research-only source as production SLA"). `INDEX_DAILY_BARS` /
  `RESEARCH` / `MARKET_SNAPSHOT` keep research-only providers as
  eligible, because those surfaces are explicitly reserved for the
  MCP research feeds. The function returns a sorted tuple
  (`provider_key` ascending) and raises `NoEligibleProviderError`
  carrying the dataset string as its first argument when no
  declaration matches.
- `coverage.py` exposes `calculate_coverage`, a pure deterministic
  grid builder that takes per-`(provider, symbol)` probe samples
  and returns a `CoverageReport` with sorted `providers` and
  sorted per-symbol date ranges. It never touches the network, DB
  or filesystem.
- `probe.py` is the pure input builder for `calculate_coverage`
  (`build_coverage_samples`); the frozen `NAV_FIELDS` /
  `DAILY_BARS_FIELDS` / `INSTRUMENT_FIELDS` / `CALENDAR_FIELDS`
  constants anchor the field set the operator-facing tooling
  consumes.

### Provider coverage report / plan / merge

The routing layer's read-only coverage surface is the JSON-ready
[CoverageReportModel](../../apps/pipeline/src/invest_pipeline/provider_coverage_report.py).
The model is rich and deterministic: it pins
`schema_version=1`, exposes a stable `content_hash` (SHA-256 of
the canonical business content, **excluding** `generated_at`),
sorts symbols ascending and providers by `provider_key`, and is
serialised by `serialize_coverage_report()` with `sort_keys=True`.
`provider_coverage_plan.select_active_etf_symbols` filters an
`Instrument` iterable to the active SSE/SZSE ETF universe
(`is_active=True`, `status=ACTIVE`, `InstrumentType.ETF`),
raising `ActiveUniverseAmbiguityError` when a single symbol maps
to multiple exchanges; `build_backfill_plan` then sorts
`(provider_priority, 0/1 for failed-vs-missing, symbol)` so the
operator-facing CLI prints a stable work list.
`provider_coverage_merge.merge_coverage_reports` is the
deterministic multi-provider merge: it rejects mismatched
`schema_version`, rejects duplicate provider keys, and produces
an aggregate `content_hash = SHA-256(sorted(report.content_hashes))`.
None of these modules import the factory, network or DB.

### Provider coverage CLI

[`provider_coverage_cli.py`](../../apps/pipeline/src/invest_pipeline/provider_coverage_cli.py)
is the operator-facing CLI that drives the coverage matrix against
the V2 ETF adapters in two explicit opt-in modes:

- **Offline mode (default).** The CLI uses
  `FixtureDevInstrumentProvider` and never reaches the network.
- **Real-network opt-in.** `--provider cifangquant` requires the
  triple opt-in (`INVEST_PIPELINE_CIFANG_ENABLED=true`,
  `INVEST_PIPELINE_CIFANG_API_KEY`, `--confirm-network`);
  `--provider fixture_dev` never needs `--confirm-network`. The
  CLI rejects every other `--provider` value upfront (it only
  accepts the two keys above) because AkShare / QuickTiny /
  RssCast are explicitly excluded from the ETF daily-bars
  surface (matrix §5.4).

`--symbols` is required (1..20, no duplicates); the default date
window is the fixture's six-day `2026-07-23..2026-07-30` range
so a default run produces a stable, inspectable report. `--dataset`
is hard-coded to `etf_daily_bars` (the field-completeness contract
is the OHLCV surface the daily-bars mappers stamp on
`DailyBar`). The CLI never writes to PostgreSQL, never invokes
Dagster assets, never performs backfill, and never prints the
API key, raw payload, request headers, exception reprs or
absolute filesystem paths. It exits `0` on success with a single
deterministic redacted JSON line; exit code `2` on configuration
errors. There is no `make provider-coverage` target; invoke
`python -m invest_pipeline.provider_coverage_cli --symbols …`
directly (or wire up a Make target of your own).

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

Provider-specific settings (`CifangSettings`,
`AkshareSettings`, `TushareSettings`, `QuickTinyMcpSettings`,
`RssCastMcpSettings`) live next to their adapter and follow the
redaction rules in ADR-0010 §5 / §6 and ADR-0011 §3. Real
credentials are looked up through the centralized
[`credentials.py`](#5d-tushare-pro-adapter-phase-1-bounded-increment)
store; the explicit `INVEST_PIPELINE_CIFANG_API_KEY` /
`INVEST_PIPELINE_AKSHARE_TOKEN` / `INVEST_PIPELINE_TUSHARE_TOKEN`
/ `INVEST_PIPELINE_RSSCAST_TOKEN` env-var overrides remain the
highest-priority path. The MCP adapters (`quicktiny_mcp` /
`rsscast`) and the catalog-only declarations are configuration-only
in this slice and do not extend `provider_factory`; only
`cifangquant`, `akshare` and `tushare` are runtime-selectable
through `build_provider()` alongside `fixture_dev`.

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
