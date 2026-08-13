# Implementation Plan: Dynamic ETF Candidate Pool — PR-04 custom strategy channel

## Overview

Implement the first declarative custom-strategy channel for the dynamic ETF
pool. YAML is parsed at the pipeline boundary with `yaml.safe_load`; the
domain receives a validated mapping/definition and evaluates only the
allow-listed shared factors. The slice remains deterministic and has no
Python, SQL, network, persistence, or arbitrary expression execution.

## Architecture decisions

- Keep YAML/file I/O in `apps/pipeline`; keep strategy validation and
  evaluation in `packages/domain`.
- Reuse the existing eight-factor `calculate_market_state_factors` output;
  do not duplicate factor formulas.
- Allow only the plan's factor keys and operators: `gt`, `gte`, `lt`, `lte`,
  `eq`, `in`, `all`, and `any`.
- Require filter rules to pass before scoring. Missing factors fail closed and
  produce an auditable warning/reason.
- Score only finite Decimal factor values, normalize each factor by its
  direction against the observed eligible set, then apply stable Top-N and
  Watch-N selection. Partial Universe entries can reach Watch only; ineligible
  entries always remain Excluded.
- Include normalized configuration/content hashes in the result for audit.

## Task list

### Phase 1: Domain contract and evaluator

- [x] Define validated strategy, filter, score, and result value objects.
- [x] Implement factor/operator allow-list and deterministic filter evaluation.
- [x] Implement direction-aware weighted scoring, hard Universe gate, stable
      Top-N/Watch-N output, and hashes.
- [x] Add focused tests for valid config, invalid config, filters, missing
      factors, direction, ranking ties, partial/ineligible Universe, and hash
      stability.

### Phase 2: YAML boundary

- [x] Add `yaml.safe_load` loader with path/type/error validation.
- [x] Add a representative `custom-trend.yaml` fixture/config.
- [x] Add loader tests proving unsafe YAML tags and unsupported fields/rules
      are rejected.

### Checkpoint: PR-04 domain/pipeline slice

- [x] Focused and full relevant tests pass.
- [x] Architecture boundary check passes.
- [x] Ruff and `git diff --check` pass.
- [x] No Python/SQL/network execution or persistence side effects.

## Deferred phases

- PR-05 `weighted_union_v1` fusion and publication.
- Strategy validation CLI and API/E2E integration.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Config executes arbitrary code | Critical | `safe_load`, strict schema, factor/operator allow-list, no eval/exec. |
| Strategy bypasses data quality | High | Reuse Universe eligibility; missing factor fails closed. |
| Ranking is not reproducible | High | Decimal arithmetic, canonical hashes, explicit tie-break by instrument ID. |
| YAML schema drifts from domain | Medium | Loader delegates to the domain mapping parser and tests both boundaries. |
