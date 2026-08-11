---
type: Concept
title: Domain overview
description: Bounded contexts inside packages/domain — instruments, market_data, candidate_pool, input_snapshot, pipeline, etf_profile, research, exposure, analytics, shared — with the canonical hashing scheme, the DC-2 ETF profile evidence framework (FieldEvidence / ProfileResolver), the Stage 4A evidence / context separation (ResearchContextPack / ContextItem), the evidence-driven Research lifecycle (ResearchCase / ResearchRun / ResearchResult / ResearchRunner), the DC-3 exposure bounded context, and the invariants that keep the layer infrastructure-free.
resource: /openwiki/domain/overview.md
tags: [domain, bounded-contexts, models, layering, etf-profile, research-context, research-lifecycle, exposure, analytics]
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
| `candidate_pool` | `invest_domain.candidate_pool.{models,calculator,ports,universe,v1_adapter,baseline_channel,institutional_channel,custom_strategy}` | The candidate-pool state machine + calculation contracts, the PR-08 minimum calculator, the pure dynamic ETF universe qualification (`build_etf_universe`), the V1→V2 pure adapter (`adapt_v1_target_selection`), and the three declarative channel strategies (`BaselineFactorChannel` / `InstitutionalRecommendationChannel` / `CustomStrategyChannel`) the routing layer dispatches against. Detailed in [Candidate pool](candidate-pool.md). |
| `input_snapshot` | `invest_domain.input_snapshot.models` | The hash-pinned `InputSnapshot` membership record. |
| `pipeline` | `invest_domain.pipeline.models` | `PipelineRun`, `PipelineRunStatus` (six-value vocabulary). |
| `etf_profile` | `invest_domain.etf_profile.{models,resolver}` | DC-2 ETF profile evidence framework (`PR-ETF-PROFILE-01..03`): the canonical `EtfProfile` record, the `FieldEvidence` / `FieldEvidenceSource` / `FieldKey` / `FieldValueType` value objects, the `compute_field_evidence_hash` helper, the `ProfileResolver` (`ResolvedField` / `ProfileResolution` / `ResolutionStatus` / `ProviderPriorityPolicy`) and the `resolve_etf_profile_evidence` pure function. `AUM`, `MARKET_VALUE` and `TURNOVER_VALUE` stay distinct (plan §6). |
| `research` | `invest_domain.research.{models,factor_set,quality_gate,canonical,context,research_case,research_run,runner}` | Stage 4A evidence-pipeline foundation plus the **evidence / context separation** (Stage 4A adjusted plan §"evidence / context separation") plus the **evidence-driven research lifecycle** ([ADR-0012](../../docs/adr/0012-research-lifecycle-boundary.md)). `EvidencePack`, `FactorObservation`, `FactorSetMetadata` (v1.0.0 fixed 8-factor set), the `evaluate_quality_gate` rule set, the SHA-256 canonical projection that produces `evi:{pack_hash[:12]}:factor.{key}:{item_hash[:12]}` evidence ids, the `ResearchContextPack` / `ContextItem` / `ContextValueType` vocabulary, the `ResearchCase` (six-value `ResearchCaseStatus`, terminal-status `closed_at` invariant) and `ResearchCaseStatus` lifecycle, the `ResearchRun` / `ResearchRunStatus` aggregate with external identity (`attempt`/`runner_key`/`playbook_key`), the `ResearchResult` bound to a succeeded run, the `ResearchRunner` port plus the `ResearchPlaybook` / `ResearchRunnerDraft` helpers, and the lifecycle orchestrators `start_research_attempt` / `complete_research_attempt` / `fail_research_attempt` / `execute_research_attempt`. The slice is intentionally **probabilistic-result-free** in pure-domain: AI results live on `ResearchResult`, never inside an `EvidencePack`. |
| `exposure` | `invest_domain.exposure.models` | DC-3 / Stage 4A exposure bounded context: `ExposureProvenance`, `IndexProfile` / `IndexConstituent` / `IndexConstituentSnapshot`, `EtfHolding` / `EtfIndexMapping` / `EtfHoldingSnapshot`. Domain-side only — provider selection and storage persistence live in the pipeline layer. |
| `analytics` | `invest_domain.analytics.factor_calculators` | The pure factor-calculator module consolidated out of the legacy `research.factor_calculators` ([GOV-03](../../docs/ARCHITECTURE-GOVERNANCE.md)): `FactorCalculationResult`, the `calculate_market_state_factors` pure function, and the `_BarValue` / `_aggregate_by_date` internals. `invest_domain.research.__init__` re-exports these via a `__getattr__` lazy bridge so existing callers keep working without creating an import cycle. |
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
algorithm (see [Migrations overview](../migrations/overview.md#2-the-seventeen-revision-chain))
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

The `Exchange` enum in [`shared/values.py`](../../packages/domain/src/invest_domain/shared/values.py) now includes `BJSE` for Stage 4B A-share stock data. This widens the canonical domain vocabulary, not the ETF contract: ETF mappers retain their SSE/SZSE allow-list and must reject Beijing exchange rows in ETF-only flows. Tushare and TDX stock mappers are responsible for converting `.BJ` / `bj` source codes to `BJSE`; focused coverage is in `apps/pipeline/tests/unit/test_tushare_stock.py` and the TDX adapter tests. This distinction keeps the stock fallback described in the [pipeline overview](../pipeline/overview.md#7b-stock-daily-bars-fallback-and-tdx-offline-provider) from changing ETF semantics.


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
lands (see [Candidate pool](candidate-pool.md#5-what-is-not-in-the-pr-08-algorithm)).

## 4A. ETF Profile evidence framework (`etf_profile`)

`packages/domain/src/invest_domain/etf_profile/` is the DC-2 evidence
context that sits between the Provider adapters and the canonical
`EtfProfile` view of an instrument. It is **infrastructure-free** and
reuses the canonical hashing helper, so the same digests that
`row_hash` and `InputSnapshot.content_hash` carry apply here.

Pipeline chain honoured by the slice:

```
Provider Raw Evidence  ->  FieldEvidence  ->  ProfileResolver  ->  EtfProfile
```

- `EtfProfile` (`models.EtfProfile`) is the canonical 1-1 record per
  `core.instruments` row. All non-key fields are optional; the
  domain validator rejects empty strings for textual fields, accepts
  fees only in the inclusive `[0, 1)` range, and refuses non-positive
  AUM / shares values. The slice mirrors the field set in
  `core.etf_profiles` 1-1.
- `FieldEvidence` / `FieldEvidenceSource` / `FieldKey` /
  `FieldValueType` (`models`) are the per-field value object used by
  the resolver. `content_hash` is the 64-character lowercase hex
  digest of the business content (instrument_id, field_key, value,
  value_type, source provenance, quality_status, confidence_score)
  computed through `compute_field_evidence_hash`; `created_at` is
  intentionally excluded so the digest stays stable across reruns.
  The same hash is the natural idempotency key on the
  `analytics.etf_profile_fields` table.
- `FieldKey` is a closed-set vocabulary covering the Level 0 / Level 1
  fields of the evidence framework (`manager` / `benchmark_index` /
  `category` / `inception_date` / `fund_type` / `management_fee` /
  `custody_fee` / `aum` / `shares` plus the evidence-only
  `market_value` and `turnover_value` keys). The vocabulary keeps
  `AUM`, `MARKET_VALUE` and `TURNOVER_VALUE` distinct (plan §6) so
  the trading-day market value of an ETF cannot be silently
  rewritten as its assets under management.
- `ProfileResolver` (`resolver.py`, the PR-ETF-PROFILE-03 increment)
  is a pure function `resolve_etf_profile_evidence(rows,
  instrument_id, *, policy=DEFAULT_PROVIDER_PRIORITY_POLICY) -> ProfileResolution`
  that groups the `FieldEvidence` rows by `FieldKey` and emits one
  `ResolvedField` per field. The three closed-set outcomes are
  `ResolutionStatus.RESOLVED` / `MISSING` / `CONFLICT`; the resolver
  never silently overwrites conflicting observations (plan §5
  "禁止覆盖") and never aliases AUM with `MARKET_VALUE` /
  `TURNOVER_VALUE`. The default `ProviderPriorityPolicy` carves out
  `manager` / `benchmark_index` / `aum`; other fields fall back to a
  stable alphabetical `provider_key` order so the result is fully
  deterministic even without a configured mapping.
- `ResolutionPolicyError` is the only exception the resolver raises
  (mixed-instrument input); the slice refuses to reconcile rows that
  point at different `InstrumentId` values, so the application layer
  must partition the input before calling `resolve(...)`.

The slice ships no Provider adapter, no Storage write and no Dagster
asset; it is the contract that `etf_profiles` / `etf_profile_context`
consume at the next layer down (see
[Pipeline overview §6](../pipeline/overview.md#6-etl-service-modules)).

## 4B. Research context separation (`research.context`)

Stage 4A ships an explicit **evidence / context separation** (Stage 4A
adjusted plan §"evidence / context separation"): the deterministic
`EvidencePack` + 8-factor v1.0.0 set stays the evidence layer; the
new `invest_domain.research.context` vocabulary is the context layer
that downstream consumers actually project.

`packages/domain/src/invest_domain/research/context.py` adds:

- `ResearchContextPack` (`schema_version="0.1.0"`, hash-stable
  `content_hash` computed through the same canonical SHA-256 helper
  as `EvidencePack.content_hash`) carries a deterministic
  `(context_type, key, item_hash)` ordering so the digest is stable
  across reruns. `created_at` is excluded from the digest.
- `ContextItem` is the per-field value object: `context_type` /
  `key` / `value` / `value_type` (`text` / `decimal` / `date` /
  `json`) / `source_provider` / `source_dataset` /
  `source_batch_id` / `source_revision` / `observed_at` /
  `quality_status` / `confidence_score` (Decimal in `[0, 1]`) /
  `evidence_refs` (de-duplicated sorted tuple of 64-character
  `content_hash` references). `item_hash` is the per-item canonical
  hash.
- `ContextValueType` is a closed-set vocabulary; the runtime value
  type is enforced in `__post_init__` so a mis-typed value cannot
  slip past the domain boundary.
- The context pack deliberately carries **no `FactorSetMetadata` /
  no factor calculation result** — those remain the evidence layer's
  responsibility. Context packs are the immutable snapshot downstream
  consumers (e.g. the ETF profile dashboard) read.

The `invest_domain.research.__init__` module re-exports the new
`ResearchContextPack` / `ContextItem` / `ContextValueType` / hash
helpers alongside the existing factor-set vocabulary so
`from invest_domain.research import ResearchContextPack, …` is the
single import path. The pipeline-side `etf_profile_context.build_etf_profile_context_pack`
is the only consumer in this slice; the AkShare `map_etf_profile_to_field_evidence`
slice produces the `FieldEvidence` rows it consumes, so the
"Provider → FieldEvidence → Resolver → ContextItem → ContextPack"
chain stays inside the pure-domain layer.

## 4C. Evidence-driven research lifecycle (ADR-0012)

[ADR-0012](../../docs/adr/0012-research-lifecycle-boundary.md)
separates deterministic data processing (owned by `PipelineRun`)
from probabilistic research execution (owned by `ResearchRun`). The
`packages/domain/src/invest_domain/research/` package ships the
pure-domain half:

- `ResearchCase` (`research_case.py`) is the lifecycle of one
  research question for one instrument and as-of date. Fields:
  `case_id` (UUID), `instrument_id` (`InstrumentId`),
  `as_of_date`, `question`, `horizon`, `status`
  (`ResearchCaseStatus`: `DRAFT` / `READY` / `RUNNING` /
  `COMPLETED` / `FAILED` / `CANCELLED`), the
  `created_at` audit timestamp, an optional `closed_at` (required on
  terminal status, forbidden on active status), and an optional
  `candidate_pool_run_id` FK to surface the originating candidate-pool
  publication. The slice enforces the `closed_at` invariant in
  `__post_init__` so a terminal case can never be silently
  re-published.
- `ResearchCaseStatus` carries the legal-transition table; the
  `transition_to(target)` method raises a `ValueError` (with the
  offending transition surfaced in the message) on any disallowed
  edge. The slice is intentionally six-status so a misbehaving
  caller can request every documented outcome (`draft`, `ready`,
  `running`, `completed`, `failed`, `cancelled`) without reaching
  for a custom string.
- `ResearchRun` (`research_run.py`) is the executor-aggregate
  counterpart: `run_id`, `case_id`, `evidence_pack_id` (FK to an
  immutable `EvidencePack`), `runner_key`, `playbook_key`,
  `status` (`ResearchRunStatus`: `QUEUED` / `RUNNING` /
  `SUCCEEDED` / `FAILED` / `CANCELLED`), `attempt` (int ≥ 1), optional
  `started_at` / `finished_at` / `error_summary`. The
  `error_summary` is only set on `FAILED`.
- `ResearchResult` (`research_run.py`) is the conclusion sidecar
  bound to a succeeded run. Fields: `result_id`, `run_id`,
  `evidence_pack_id` (must match the run), `conclusion`, `risks`
  (tuple of non-blank strings), `evidence_ids` (tuple of stable
  SHA-256 evidence ids), `report_markdown`, plus the versioned
  provenance (`model_key`, `model_version`, `playbook_version`,
  `adapter_version`, `created_at`). The slice's invariants prevent
  a `ResearchResult` from referencing evidence IDs the parent pack
  does not actually carry (checked by `complete_research_attempt`).
- `ResearchRunner` (`runner.py`, `Protocol`):
  structural port every concrete runner satisfies; shipped
  implementations live in
  [`invest_pipeline.adapters.jiuwenswarm.runner`](../../apps/pipeline/src/invest_pipeline/adapters/jiuwenswarm/runner.py)
  and test-local in-memory runner doubles. The port
  exposes `run(case, run, playbook, evidence_pack) -> ResearchRunnerDraft | ResearchRunnerFailure`
  plus `run_with_identity(...)` (Slice 3) so the orchestrator can
  reconcile external session ids.
- `ResearchPlaybook` is the versioned configuration record the
  runner binds to a run (`playbook_key` / `playbook_version` /
  `description` / sorted `cited_factor_keys`). A run with a
  mismatched `playbook_key` is rejected by the orchestrator before
  the runner fires.
- `ResearchRunnerDraft` is the structured runner output: the
  conclusion + risks + evidence_ids + report + versioned model /
  playbook / adapter provenance + `created_at`. Frozen
  dataclass; the orchestrator validates the draft against the
  source `EvidencePack` before transitioning the run to
  `SUCCEEDED`.
- Lifecycle helpers — `start_research_attempt`, `execute_research_attempt`
  (`PLAYBOOK_KEY` / `RUNNER_KEY` / `EVIDENCE_IDS` invariants),
  `complete_research_attempt` (validates draft ↔ pack binding),
  `fail_research_attempt` — drive the run from `QUEUED` to `RUNNING`
  and then to `SUCCEEDED` or `FAILED`; case completion is a separate
  aggregate transition. They surface a `ResearchRunnerFailure` when
  the draft is unusable. They never
  read the wall clock or accept an injected datetime directly;
  call sites pass a fully-formed `ResearchRun` /
  `ResearchRunnerDraft`.

The bounded context is infrastructure-free (`research_case.py`,
`research_run.py`, `runner.py`, `context.py`, `models.py`,
`factor_set.py`, `quality_gate.py`, `canonical.py`); persistence
lives in [`packages/storage`](../storage/overview.md) and the
[orchestrator](../../apps/pipeline/src/invest_pipeline/research_orchestration_service.py)
on the pipeline side.

## 4D. DC-3 exposure bounded context

`packages/domain/src/invest_domain/exposure/` is the
deterministic vocabulary for index-level and ETF-level exposure
observations, kept separate from Research. Every value object
carries a SHA-256-stable `content_hash` (or an explicit
`ExposureProvenance`), so the storage layer can dedupe
observations idempotently.

- `ExposureProvenance` — `provider_key` / `dataset_key` /
  `observed_at` (timezone-aware), optional `source_batch_id`
  (UUID), `revision` (default `1`), `confidence` (`Decimal`,
  default `1`).
- `IndexProfile` / `IndexConstituent` / `IndexConstituentSnapshot` —
  the snapshot of an index's constituents on one date. The
  snapshot carries a sorted, content-hash-stable `constituents`
  tuple.
- `EtfHolding` / `EtfIndexMapping` / `EtfHoldingSnapshot` — the
  ETF side of the exposure link: a `weight`-bearing
  constituent inside an ETF, plus the date-bounded mapping from
  ETF ↔ index, plus the per-ETF reporting-period snapshot.

The pure-domain slice is intentionally narrow; provider selection
(AkShare `fund_portfolio_hold_em`, CSIndex
`report_asset_detail`) and persistence
(`apps/pipeline/src/invest_pipeline/exposure_service.py` /
`real_exposure_service.py`) live in the pipeline layer.

## 5. Where to look first

- M0 brief on layering and what each PR was allowed to touch —
  [`/docs/implementation/M0-CODING-BRIEF.md`](../../docs/implementation/M0-CODING-BRIEF.md).
- Per-context tests live under `packages/domain/tests/`; the
  CI job `domain-tests` runs the suite via `make test-domain`.
