# Phase 1 ETF Data Ingestion Implementation Plan

## Overview

Complete the ETF ingestion vertical slice against the current repository state,
using CifangQuant as the intended primary Provider and preserving the existing
three-layer raw evidence model. The implementation must remain fixture-first in
CI and must not require real credentials for ordinary tests.

## Architecture decisions

- Use `cifangquant` as the Provider key, pending credential/access smoke validation.
- Use `GET /api/fund/list` for ETF master data and `GET /api/fund/hist_em` with
  `adjust=none` for daily bars.
- Map `SH`/`SZ` to `SSE`/`SZSE`; reject non-ETF or unsupported markets.
- Preserve the existing `raw.provider_requests`, `raw.provider_attempts`, and
  `raw.provider_batches` model; do not regress to the older single-table design.
- Treat missing `prev_close` and `amount` as nullable because the documented
  historical response does not provide them.

## Task list

### Phase 0: Reconcile current state

- [ ] Inspect and preserve the existing dirty worktree.
- [ ] Verify current migration, repository, fixture, and Dagster test baselines.
- [ ] Freeze the CifangQuant contract in `docs/adr/0011-primary-etf-provider.md`.

### Phase 1: Real Provider adapter

- [ ] Add CifangQuant settings and redacted configuration.
- [ ] Add HTTP client with timeout, bounded retry, and error classification.
- [ ] Add mapper for fund list and historical bars.
- [ ] Add adapter contract fixtures and unit tests.
- [ ] Add an opt-in smoke command without placing credentials in the repository.

### Checkpoint: Provider contract

- [ ] Fixture tests pass.
- [ ] `adjust=none` is asserted in the request contract.
- [ ] Authentication and rate-limit failures are classified.
- [ ] No token appears in logs or error text.

### Phase 2: Service and runtime integration

- [ ] Replace hard-coded fixture selection with configuration-driven provider selection.
- [ ] Extract instrument and daily-bar ingestion services around the existing UoW.
- [ ] Add basic quality checks and pipeline-run failure handling.
- [ ] Add Dagster single-day and date-range execution paths.

### Phase 3: End-to-end verification

- [ ] Add PostgreSQL integration coverage for real-adapter-shaped payloads.
- [ ] Verify idempotency and revision behavior.
- [ ] Verify failure/retry audit records.
- [ ] Run opt-in CifangQuant smoke test when credentials are available.
- [ ] Review the complete diff and current dirty-worktree boundary.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Provider quota or rate limit is undocumented | Medium | Keep batch size <= 50, bounded retry, and require smoke validation |
| Fund list is broader than ETF universe | High | Filter `fund_type`, validate market, and add fixture cases |
| Historical API lacks amount/prev_close | Medium | Keep fields nullable; never synthesize values |
| Existing worktree contains unrelated edits | High | Small bounded increments and ARC diff review after every increment |
| Real credentials are unavailable | Medium | Complete all fixture/integration work; defer only real smoke validation |

## Acceptance gate

The phase is complete only when fixture E2E, PostgreSQL integration, Dagster
single-day execution, idempotent rerun, revision handling, and an authorized
real-provider smoke test all pass.
