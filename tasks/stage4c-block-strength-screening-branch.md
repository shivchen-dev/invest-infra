# Stage 4C Branch — Block Strength Screening

## Status

- Type: non-blocking research branch
- Parent: Stage 4C Core Data Layer Integration
- Start gate: Phase 2 provides governed block membership snapshots and daily aggregates
- Production status: candidate screening only; not an investment score or trading signal

## Objective

Use Stage 4C canonical facts to reproduce and evaluate a simple block-strength ranking that filters short-lived themes while preserving full provenance and replayability.

## Baseline Model

```text
block_strength = return_1d * 0.30 + return_5d * 0.50 + return_20d * 0.20
```

The weights are an external heuristic, not an accepted production rule. They must remain versioned parameters until historical evaluation supports a formal Analytics model decision.

## Candidate Filters and Diagnostics

- exclude blocks with fewer than 8 governed constituents;
- evaluate, rather than assume, the proposed five-day average turnover threshold;
- measure large-cap or leading-constituent participation;
- measure advance and limit-up breadth across constituents;
- track ranking persistence and one-day spike/reversal patterns;
- report source coverage, snapshot date, freshness, quality state, and model version.

## Outputs

- daily candidate block ranking;
- rank changes over 1, 3, and 7 trading days;
- persistence and one-day-spike diagnostics;
- historical evaluation report for weights and thresholds.

## Boundaries

- Does not change Stage 4C dataset or canonical-fact contracts.
- Does not block any Stage 4C phase or checkpoint.
- Does not publish an investment recommendation, position instruction, or trading action.
- Does not enter formal Analytics or Research evidence until separately reviewed and versioned.
- Does not use current block membership to backfill unknown historical membership.

## Acceptance Gate for Formal Adoption

Formal adoption requires reproducible historical evaluation, explicit universe and survivorship controls, parameter/version registration, failure behavior, and a separate architecture/model decision.
