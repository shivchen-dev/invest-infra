# ADR-0012: Research lifecycle and AI execution boundary

## Status

Accepted — 2026-08-07

## Context

The repository already has deterministic analytics, Candidate Pool,
`EvidencePack`, `ResearchContextPack`, and their upstream ETF/Profile/Exposure
data. It does not yet have an explicit lifecycle for a research question or an
AI execution. Reusing `PipelineRun` for that purpose would mix deterministic
data processing with probabilistic research execution and failure recovery.

## Decision

1. `ResearchCase` owns the lifecycle of one research question for one
   instrument and as-of date. A Candidate Pool reference is optional.
2. `EvidencePack` is an immutable, case-scoped collection of deterministic
   evidence. `ResearchContextPack` remains a rebuildable read-only projection;
   neither stores AI conclusions.
3. `PipelineRun` continues to own provider collection and deterministic
   computation. `ResearchRun` is a separate aggregate and persistence model for
   runner execution, attempts, external session identity, failure recovery, and
   completion.
4. `ResearchResult` belongs to a successful `ResearchRun`, references the exact
   Evidence Pack and valid Evidence IDs, and never mutates evidence.
5. Run idempotency is based on the case, immutable Evidence Pack identity,
   versioned runner/playbook, and attempt policy. One external session cannot
   publish more than one successful result.
6. JiuwenSwarm is an infrastructure adapter behind a `ResearchRunner` port.
   Domain packages must not import its SDK. Agent roles and playbooks are
   versioned configuration, not domain constants.
7. The first executable checkpoint uses a Fake Runner. JiuwenSwarm, read-only
   Research API, and additional DC-4+ datasets are not prerequisites for that
   checkpoint.

## State ownership

```text
Instrument / optional Candidate Pool
                ↓
          ResearchCase
                ↓
     immutable EvidencePack
                ↓
          ResearchRun
                ↓
         ResearchResult
```

Recommended initial states:

- ResearchCase: `draft → ready → running → completed|failed`, with
  `draft|ready → cancelled`.
- ResearchRun: `queued → running → succeeded|failed|cancelled`; retry creates a
  new attempt and does not rewrite a completed attempt.

Exact transition guards and compare-and-set persistence semantics are frozen by
the ResearchCase/ResearchRun domain slices and their tests before migrations are
added.

## Consequences

- Research and pipeline failures can be retried independently.
- AI output remains auditable against immutable evidence.
- Existing Evidence/Context implementations are reused instead of duplicated.
- DC-4 valuation data can be added later when a research case demonstrates the
  need; data breadth does not block the minimum research lifecycle.
- New tables and repositories are admitted only for aggregates with an
  independent lifecycle and stable query requirements.
