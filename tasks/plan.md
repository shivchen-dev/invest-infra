# Implementation Plan: Stage 3 Completion

## Scope

Close the locally executable remainder of the stability and personal-use stage, while recording external blockers without fabricating acceptance results.

## Phase 1: Baseline and test gaps

- [x] Run the full repository test/architecture baseline with the current working tree.
- [x] Add the smallest useful Web unit-test setup and tests for the implemented read-only pages/API states.
- [x] Verify Web typecheck and production build after the test setup.

## Phase 2: Database and operational verification

- [x] Run migration-chain and PostgreSQL Fixture E2E checks when Docker/PostgreSQL is available.
- [x] Verify schedule/preflight behavior and document exact remaining runtime prerequisites.
- [ ] Refresh current-stage documentation and remove stale acceptance claims.

## Phase 3: External acceptance blockers

- [ ] Perform authorized CifangQuant acceptance only after credentials, contract evidence, and rate-limit/cutoff decisions are supplied.
- [ ] Run and record the 10-trading-day shadow window.

## Acceptance

- Local tests and builds pass.
- No external acceptance is marked complete without evidence.
- Documentation distinguishes implemented code, verified behavior, and blocked external work.
