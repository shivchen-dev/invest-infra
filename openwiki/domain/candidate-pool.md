---
type: Concept
title: Candidate pool (domain)
description: Candidate-pool state machine, calculation context, minimum pure-function calculator and input-snapshot contract. Explains why the M4 Calculator Protocol is no longer exported and how the PR-08 algorithm covers no_data / suspended / invalid_price / low_volume / low_amount.
resource: /openwiki/domain/candidate-pool.md
tags: [candidate-pool, calculator, state-machine, input-snapshot]
---

# Candidate pool

The candidate-pool bounded context owns the lifecycle of one
calculation per `trade_date`. It is split across three pure modules
inside `packages/domain/`:

| Module | Responsibility |
|--------|----------------|
| [`invest_domain.candidate_pool.models`](../../packages/domain/src/invest_domain/candidate_pool/models.py) | State machine (`CandidatePoolStatus`), eligibility / scoring criteria, `CandidatePoolItem`, `CandidatePoolResult`, `RuleOutcome`, `ExclusionReason`, `CandidatePoolPolicy`. |
| [`invest_domain.candidate_pool.calculator`](../../packages/domain/src/invest_domain/candidate_pool/calculator.py) | The PR-08 minimum calculator (`DefaultMinimumCandidatePoolCalculator`) + the `MinimumCandidatePoolCalculator` protocol. |
| [`invest_domain.candidate_pool.ports`](../../packages/domain/src/invest_domain/candidate_pool/ports.py) | The M4 `CandidatePoolCalculator` Protocol that previously lived here has been removed; the module documents the removal and the future re-introduction. The PR-08 minimum calculator's `MinimumCandidatePoolCalculator` Protocol (in `calculator.py`) already locks the call signature used today. |

The PR-08 minimum algorithm intentionally uses a smaller signature than
the planned M4 contract because it does not yet consume rolling
histories. See the calculator's module docstring for the trade-off.

## 1. State machine

Per [ADR-0008](../../docs/adr/0008-candidate-pool-state-machine.md), the
state lives on `CandidatePoolStatus`:

```
calculated --> validated --> published   (terminal)
                       \-> rejected      (terminal)
```

- **Legal transitions** are enforced by
  `CandidatePoolStatus.can_transition_to(target)`.
- Terminal states are irreversible; the only way to "supersede" a
  published pool is to publish another one and stamp the previous run
  with `superseded_at` in the publication pointer table
  (`analytics.candidate_pool_publications`).
- `(trade_date, algorithm_key, algorithm_version, parameter_hash,
  input_snapshot_id)` is the business uniqueness key — re-using the
  same snapshot and parameters must not create a second row.

The PR-08 calculator returns a `CandidatePoolResult` once a run is
`calculated`; the validator pipeline is what later promotes the run to
`validated` and then `published` or `rejected`.

## 2. Inputs and outputs

The calculator consumes the smallest possible input set:

- `InputSnapshot` — the immutable membership list with its
  `content_hash` ([Candidate pool §3](#input-snapshot-binding)).
- `list[DailyBar]` — the standardised bars for one `trade_date`.
- `CandidatePoolPolicy` — the eligibility / liquidity / scoring
  parameters (all explicit, none implicit).

It returns a `CandidatePoolResult` containing exactly one
`CandidatePoolItem` per input `instrument_id`:

- `included=True` items carry a `rank`, `total_score`, `metrics`, and
  zero-or-more `RuleOutcome` entries.
- `included=False` items carry `exclusion_reasons` (typically one code
  per item — the calculator only emits the first failing check).

`CalculationContext` is *derived* from the `InputSnapshot` inside the
calculator (the call site does not pass it). `CandidatePoolSummary`
records `input_count`, `included_count`, `excluded_count` and the
rule-outcome counts that the validator later consumes.

## 3. Input-snapshot binding

`InputSnapshot.create` is the only sanctioned constructor for fresh
snapshots. It:

1. Sorts `instrument_ids` by their raw 16-byte UUID representation.
2. Computes `content_hash = SHA-256(b"".join(uuid.bytes for uuid in
   sorted_uuids)).hexdigest()`.
3. Allocates `id` and `created_at` (timezone-aware UTC) via injectable
   factories so tests can pin them.

`__post_init__` rejects empty / duplicate membership lists, mismatched
`row_count`, non-UUID entries, non-hex `content_hash` of the wrong
length and naive datetimes — see the invariants in
[`invest_domain.input_snapshot.models`](../../packages/domain/src/invest_domain/input_snapshot/models.py).

## 4. The minimum calculator's exclusion tree

`DefaultMinimumCandidatePoolCalculator.calculate(snapshot, bars, policy)`
is pure:

```
for instrument_uuid in snapshot.instrument_ids:
    bar = latest_bar_per_instrument[bars][instrument_uuid]
    reason = _check_eligibility(bar, min_volume=…, min_amount=…)
    if reason:
        excluded_items[instrument_uuid] = CandidatePoolItem(...)
    else:
        turnover = bar.close * bar.volume
        included_candidates.append((turnover, instrument_uuid, bar))

included_candidates.sort(key=(-turnover, instrument_uuid.bytes))
for rank, (turnover, uuid, bar) in enumerate(..., start=1):
    included_items[uuid] = CandidatePoolItem(rank=rank, total_score=turnover, …)
```

The exclusion codes emitted by `_check_eligibility` are stable strings:

| Code | Meaning |
|------|---------|
| `no_data` | No `DailyBar` available for this instrument on the snapshot date. |
| `suspended` | Latest bar's `trading_status == TradingStatus.SUSPENDED`. |
| `invalid_price` | `close` is missing or non-positive (defensive — domain validation already rejects it). |
| `low_volume` | `volume` is missing or `< policy.eligibility.min_volume`. |
| `low_amount` | `amount` is missing or `< policy.eligibility.min_amount`. |

Two properties of the sort key matter for the API surface:

- **Deterministic tiebreak.** Items with equal `close * volume` rank in
  ascending `uuid.bytes` order, so identical inputs always produce
  identical ranks.
- **Stable output order.** The result items are emitted in the same
  order as `snapshot.instrument_ids`, so the API can stream them
  through directly.

## 5. What is NOT in the PR-08 algorithm

The minimum calculator does not yet consume rolling histories and does
not produce `RuleOutcome` entries for included items. The M4 algorithm
will add:

- `LiquidityCriteria`-based rolling-window liquidity scoring.
- `PriceQualityCriteria` for missing-day / zero-volume ratios.
- `RiskCriteria` for volatility and drawdown windows.
- Score-based ranking (`ScoreWeights`) replacing the placeholder
  `close * volume` turnover ranking.

The M4 `CandidatePoolCalculator` Protocol that was once exported from
`invest_domain.candidate_pool.ports` has been removed; it will be
re-introduced alongside the M4 algorithm when the rolling-history work
lands.

## 6. Storage integration

The persistence tables for runs and items live in
`analytics.candidate_pool_runs` and `analytics.candidate_pool_items`.
Repositories are `SqlAlchemyCandidatePoolRunRepository` and
`SqlAlchemyCandidatePoolItemRepository`. Transitions go through
`CandidatePoolRunRepository.transition_status`, which issues an
optimistic `UPDATE … WHERE id=? AND status=?` and raises
`ConcurrentTransitionError` on a zero-row match — see
[Storage overview](../storage/overview.md#transactions-and-unit-of-work).

## 7. How the API reads it

PR-09 exposes the most recently published pool through
`GET /api/v1/candidate-pool/latest`. The handler:

1. Fetches the most recent `CandidatePoolStatus.PUBLISHED` run.
2. Loads the matching `InputSnapshot` from `analytics.input_snapshots`
   so the caller can audit the exact input set.
3. Translates each `CandidatePoolItem` (rules and exclusions included)
   into the `CandidatePoolLatestResponse` Pydantic shape via
   [`apps/api/src/invest_api/routers/candidate_pool.py`](../../apps/api/src/invest_api/routers/candidate_pool.py).

See [API overview](../api/overview.md#get-apiv1candidate-poollatest).
