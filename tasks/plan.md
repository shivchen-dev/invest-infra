# Implementation Plan: Dynamic ETF Candidate Pool — PR-02 baseline channel

## Overview

Add the first formal Stage 4A-0 routing slice: a deterministic baseline-factor
channel that consumes the existing ETF universe classifier and shared market
factor calculator, then emits auditable candidate proposals. This increment
does not publish to PostgreSQL, add APIs, or implement institution/custom
channels.

## Architecture decisions

- Reuse `build_etf_universe` and `calculate_market_state_factors`; do not create
  a second factor implementation.
- Keep the channel pure and side-effect free. Persistence remains owned by the
  existing Candidate Pool service until the fusion contract is ready.
- Use a small, typed proposal interface with deterministic ordering, explicit
  `include/watch/exclude` decisions, quality-gate reasons, and a versioned
  policy hash.
- Default thresholds are conservative and configurable; no parameter
  optimisation or backtest logic is introduced.

## Task list

### Phase 1: Baseline channel

- [x] Define the baseline-channel policy and proposal output contract.
- [x] Score eligible candidates from the existing eight-factor result.
- [x] Emit deterministic proposals for full, partial, and ineligible inputs.
- [x] Add focused tests for scoring, gates, missing factors, stable ordering,
      hash stability, and fail-closed behaviour.

### Checkpoint: PR-02 baseline channel

- [x] Focused domain/pipeline tests pass.
- [x] Existing candidate-pool and factor tests pass.
- [x] No database, API, provider-network, or filesystem side effects.

## Deferred phases

- PR-03: institution recommendation adapter.
- PR-04: safe YAML custom-strategy adapter.
- PR-05: fusion, Shadow persistence, API, and E2E acceptance.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Duplicate factor formulas | High | Call the existing shared factor calculator only. |
| Missing or conflicted data becomes a recommendation | High | Hard-gate incomplete/invalid/conflicted factor results. |
| Non-reproducible ranking | High | Decimal arithmetic, pinned policy version, stable tie-breakers. |
| Premature production impact | High | Pure output only; no publish path in this increment. |
