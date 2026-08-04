---
type: Concept
title: Domain overview
description: Bounded contexts inside packages/domain — instruments, market_data, candidate_pool, input_snapshot, pipeline, shared — with the canonical hashing scheme and the invariants that keep the layer infrastructure-free.
resource: /openwiki/domain/overview.md
tags: [domain, bounded-contexts, models, layering]
---

# Domain overview

`packages/domain/src/invest_domain/` hosts the **pure** domain model:
entities, value objects, enums, ports, and a deterministic hashing
helper. The package is guaranteed never to import SQLAlchemy, Alembic,
FastAPI, Dagster, httpx, requests or any Provider SDK; that constraint
is both a coding rule (enforced by [`scripts/check_architecture.py`](../../scripts/check_architecture.py))
and a runtime check exercised by `make arch-check`.

The package is re-exported through `invest_domain.__init__`. Consumers
should `from invest_domain import …` — there are no symbolic imports
outside that surface.

## 1. Bounded contexts

| Context | Module | What it owns |
|---------|--------|--------------|
| `instruments` | `invest_domain.instruments.{models,values}` | `Instrument`, `InstrumentId`, `InstrumentType`, `InstrumentStatus`, `Currency`, `Exchange`. |
| `market_data` | `invest_domain.market_data.{models,values,ports}` | `DailyBar`, `BarSource`, `Adjust`, `TradingStatus`, `ProviderRequest`, `ProviderAttempt`, `ProviderBatch`, the `ProviderFailureStage` vocabulary and the `EtfMarketDataProvider` / `InstrumentProvider` ports. |
| `candidate_pool` | `invest_domain.candidate_pool.{models,calculator,ports,universe,v1_adapter}` | The candidate-pool state machine + calculation contracts, the PR-08 minimum calculator, the pure dynamic ETF universe qualification (`build_etf_universe`), and the V1→V2 pure adapter (`adapt_v1_target_selection`). Detailed in [Candidate pool](candidate-pool.md). |
| `input_snapshot` | `invest_domain.input_snapshot.models` | The hash-pinned `InputSnapshot` membership record. |
| `pipeline` | `invest_domain.pipeline.models` | `PipelineRun`, `PipelineRunStatus` (six-value vocabulary). |
| `research` | `invest_domain.research.{models,factor_set,factor_calculators,quality_gate,canonical}` | Stage 4A evidence-pipeline foundation: `EvidencePack`, `FactorObservation`, `FactorSetMetadata` (v1.0.0 fixed 8-factor set), the `calculate_market_state_factors` pure function, the `evaluate_quality_gate` rule set, and the SHA-256 canonical projection that produces `evi:{pack_hash[:12]}:factor.{key}:{item_hash[:12]}` evidence ids. |
| `shared` | `invest_domain.shared.{canonical,values}` | `canonical_json`, `canonical_sha256`, `content_hash`, `CANONICAL_HASH_SCHEMA_VERSION`. |

Every context exposes its public surface through a single
`__init__.py` that re-exports the public dataclasses, enums and ports.
The bounded contexts reference each other only via the canonical
package — there are no implicit module-level imports from one context
into another.

## 2. Canonical hashing (`shared.canonical`)

`DailyBar.row_hash`, the candidate-pool parameter-hash, and any future
content-derived digest go through [`packages/domain/src/invest_domain/shared/canonical.py`](../../packages/domain/src/invest_domain/shared/canonical.py).
The helper:

- Sorts keys lexicographically before serialisation.
- Serialises Decimal values via a normalised form (no exponent, fixed
  precision matching the storage schema).
- Hex-encodes the SHA-256 digest and tags every output with
  `CANONICAL_HASH_SCHEMA_VERSION`, so a future schema bump changes the
  digest in an auditable way instead of silently re-mapping data.

The `InputSnapshot.content_hash` is built on a more restrictive
algorithm (see [Migrations overview](../migrations/overview.md#the-six-revision-chain))
because it only depends on the byte-sorted `instrument_ids`.

## 3. The infrastructure-free invariant

`packages/domain/src/invest_domain/__init__.py` opens with the
guarantee:

> Importing from this module never triggers any infrastructure
> dependency: the package is guaranteed to be SQLAlchemy-, Alembic-,
> FastAPI-, Dagster- and Provider-SDK-free.

This is enforced mechanically — see
[Architecture overview](../architecture/overview.md#2-layers).
Domain code:

- does not read the wall clock (`datetime.now()` is only used as a
  default inside `InputSnapshot.create` and is overridable for
  deterministic tests);
- does not read environment variables (`os.environ`) or filesystem paths;
- does not perform I/O or instantiate clients.

Application services that need a clock or a session accept them as
parameters. The `MinimumCandidatePoolCalculator.calculate` is the
canonical example — it is a pure function of `(snapshot, bars, policy)`.

## 4. Ports (`market_data.ports`, `candidate_pool.ports`)

Ports are declared as `@runtime_checkable` Protocols so both adapters
and tests can satisfy them structurally. The currently shipped ports:

- `EtfMarketDataProvider` (market_data.ports) — `fetch_instruments` and
  `fetch_daily_bars`; `fixture_dev` is enabled by default, while the
  fully wired `cifang` and `akshare` adapters require explicit
  enablement (see [Pipeline overview §5](../pipeline/overview.md#5-cifang-adapter-adr-0011-phase-1-first--second-increments)
  and [§5b](../pipeline/overview.md#5b-akshare-adapter-pr-02)).
- `InstrumentProvider` — narrower surface used by the
  `seed_instruments` asset.
- `MinimumCandidatePoolCalculator` (candidate_pool.calculator) — the
  PR-08 entry point with the signature `(snapshot, bars, policy) →
  CandidatePoolResult`.

The earlier `CandidatePoolCalculator` (M4 placeholder Protocol) was
removed from `invest_domain.__init__` and from the public re-exports of
`invest_domain.candidate_pool` once the PR-08 minimum calculator was
landed; only the minimum calculator's Protocol ships today. The
`invest_domain.candidate_pool.ports` module now only documents the
removal — the Protocol will be re-introduced once the M4 algorithm
lands (see [Candidate pool](candidate-pool.md#what-is-not-in-the-pr-08-algorithm)).

## 5. Where to look first

- M0 brief on layering and what each PR was allowed to touch —
  [`/docs/implementation/M0-CODING-BRIEF.md`](../../docs/implementation/M0-CODING-BRIEF.md).
- Per-context tests live under `packages/domain/tests/`; the
  CI job `domain-tests` runs the suite via `make test-domain`.
