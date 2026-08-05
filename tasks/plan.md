# Implementation Plan: Dynamic ETF Candidate Pool — PR-03 institutional channel

## Overview

Implement the first external-opinion channel for the dynamic ETF pool. The
increment accepts validated structured recommendation records, applies source,
time, symbol, and Universe constraints, and emits deterministic auditable
proposals without persistence, network access, or report-text ingestion.

## Architecture decisions

- Keep the domain slice pure: JSON/CSV adapters and CLI file I/O are deferred
  to a later pipeline increment; domain receives structured records.
- Do not reuse the V1 FQIR adapter contract: its channel key is intentionally
  restricted to `fqir`. Define the smallest institutional proposal contract
  needed by the future fusion layer.
- Treat institution recommendations as `external_opinion`; source, publish
  time, expiry, confidence, summary, and citation remain explicit metadata.
- Apply the existing `build_etf_universe` hard gate. An external opinion can
  never promote an ineligible ETF into an included result.
- Use the fixed rating mapping from the plan and stable canonical input/output
  hashes. No historical hit-rate calculation or parameter optimisation.

## Task list

### Phase 1: Domain contract and pure evaluator

- [x] Define validated recommendation/batch/proposal/result value objects.
- [x] Implement rating mapping, source whitelist, expiry, deduplication, and
      unknown-symbol handling.
- [x] Apply Universe eligibility and emit deterministic proposals with audit
      metadata and hashes.
- [x] Add focused tests for valid, expired, duplicate, unknown, conflicting,
      invalid, and ineligible recommendations.

### Checkpoint: PR-03 domain slice

- [x] Focused and full domain tests pass.
- [x] Architecture boundary check passes.
- [x] No database, API, provider, network, or filesystem side effects.

## Deferred phases

- JSON/CSV file adapter and `recommendation-import` CLI.
- PR-04 declarative custom strategy channel.
- PR-05 fusion, persistence, API, Shadow, and E2E acceptance.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| External opinion bypasses quality gates | High | Reuse `build_etf_universe`; ineligible always emits `exclude`. |
| Stale or duplicate recommendation | High | Aware timestamps, explicit expiry, deterministic source/ref dedup. |
| Untrusted report content enters the system | Medium | Store only bounded summary and citation fields; no full report text. |
| Channel contract diverges before fusion | High | Keep field names aligned with plan §7 and version the channel. |
