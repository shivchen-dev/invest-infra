# Phase B Strategy Proposal Contracts

## Purpose

Phase B converts one registered source document and one accepted capability
assessment into a reviewable `StrategyProposal`. It does not create an approved
`StrategyVersion`, an automation definition, or an active strategy.

The delivery seam is intentionally small:

```text
strategy-engineering-task.json + delivery directory
  -> strategy.json
  -> strategy.md
  -> validation.json
```

`strategy.json` is machine-authoritative. Markdown headings and prose layout are
never parsed as contract fields.

## Strict envelope

The following fields may fail preflight because they protect routing,
provenance, idempotency, or integrity:

- schema, proposal, revision, and task identity;
- source-document identity, revision, and content hash;
- capability-assessment identity, task identity, and artifact hash;
- proposal status and generation time;
- hashes binding `strategy.md` and `validation.json`;
- validation identity and binding back to the proposal task.

All hashes are lowercase SHA-256. Unknown additive fields are accepted and
preserved by downstream ingestion.

## Tolerant proposal payload

`definition` contains strategy-specific rules, ordered workflow, inputs,
outputs, calculations, fallback behavior, and report requirements. Its internal
shape may differ between sector and stock strategies and is not exhaustively
validated by the generic preflight.

The proposal must explicitly disclose:

- rules quoted or directly derived from the source document;
- engineering additions not defined by the source;
- degraded or unavailable capabilities and accepted fallback assumptions;
- subjective/model-assisted judgments;
- unresolved decisions requiring CIA review;
- invalidation conditions and known limitations.

Business ambiguity becomes `review`, not a malformed-delivery error.

## Producer status

- `ready_for_review`: complete enough for deterministic system validation and
  human review;
- `needs_review`: material choices remain, but the proposal can be preserved
  and routed;
- `blocked`: no safe executable proposal can currently be formed.

These states are producer claims only. None means approved or active.

## Producer validation

`validation.json` records WorkBuddy's self-checks. Its status is one of:

- `passed`;
- `passed_with_review`;
- `failed`.

This file does not replace 投研系统 deterministic validation, RAA audit, or CIA
decision.

## Validation severity

| Condition | Outcome |
|---|---|
| Invalid JSON, schema, identity, provenance, routing, or hash binding | `error` |
| Optional explanation absent or a non-authoritative check omitted | `warning` |
| Engineering addition, fallback, subjective rule, or unresolved choice | `review` |
| Producer cannot form a safe proposal | proposal status `blocked`; preserve delivery |

## Retention and correction

- Preflight never repairs or overwrites producer artifacts.
- A failed delivery remains available for diagnosis.
- Correction creates a new immutable proposal revision or a new task delivery;
  it does not mutate an already reviewed proposal.
- Later-stage files such as strategy versions, activation records, automation
  definitions, runs, and candidate entries are forbidden in a Phase B package.

## Explicit exclusions

- approval, rejection, CIA decision, RAA audit result, or activation;
- `StrategyVersion` or `StrategyAutomationDefinition` creation;
- scheduling, execution, candidate admission, or database row design;
- parsing Markdown as a machine contract;
- a universal rule schema shared by all strategy types.

## Preflight command, exit codes, and report

ARC runs the Phase B preflight before any ingestion, audit, or CIA review.
The standalone CLI only checks identity, provenance, integrity, routing, and
shape; it never parses Markdown or makes a business decision.

Command:

```text
python3 scripts/validate_strategy_proposal.py --task <task.json> --result-dir <delivery-dir>
```

- Argument count is exactly 2; argparse usage errors exit 2.
- The script never creates a missing `--result-dir`; that is itself an error.
- The script never modifies producer artifacts.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | No envelope/path/binding errors AND proposal `status` is one of `ready_for_review`, `needs_review`, or `blocked` AND producer validation `status` is `passed` or `passed_with_review`. |
| 1 | Any envelope, path, or binding error, any later-stage file, or producer validation `status` is `failed`. |
| 2 | Argparse usage error (missing or extra arguments). |

Producer states are claims only. Exit 0 does not mean the proposal is
approved, accepted, or active.

Report:

- Path: `<delivery-dir>/proposal-preflight-report.json`.
- Schema: `strategy-proposal-preflight/1.0`.
- Contains `task_id`, `proposal_status`, `validation_status`, `ready`,
  `exit_code`, `errors`, `warnings`, `reviews`, `file_hashes`, `bindings`,
  and `unexpected_files`.
- `proposal.definition` is required to be an object but its internals are
  not validated; business ambiguity is the producer's responsibility.
- Producer validation `errors` strings are copied into the report's
  `errors` and block readiness; `warnings` and `reviews` strings are
  copied into the report's `warnings`/`reviews` and are nonblocking.
- The report never contains host-absolute paths.
- The report's `ready` field equals `True` iff the script exits 0.
