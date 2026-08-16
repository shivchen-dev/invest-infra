# Phase A Strategy Source and Capability Contracts

## Status

Design templates for review. They are not frozen JSON Schemas and do not create formal strategy state.

These contracts implement the first slice of `docs/plan/invest-infra-strategy-source-to-automation-workflow.md`:

```text
StrategySourceDocument
  → capability assessment task
  → WorkBuddy probes
  → StrategyCapabilityAssessment
```

No artifact in this directory can approve, version, activate, or execute a strategy.

## Files

| File | Authority |
|---|---|
| `templates/source-document.json` | Immutable source-material registration example. |
| `templates/capability-assessment-task.json` | Task envelope sent to WorkBuddy. |
| `templates/capability-assessment.json` | Machine-authoritative assessment result shape. |
| `templates/capability-assessment.md` | Recommended human report structure; headings are not machine parsed. |
| `templates/capability-probes.json` | Probe evidence associated with the assessment. |
| `fixtures/*/capability-assessment.json` | Representative result states for contract review. |

## Required fields and reasons

### Strict identity and integrity

These fields may produce an `error` when missing or contradictory because safe routing, interpretation, or audit would be impossible:

- `schema_version`: selects the compatible reader;
- object/task identity fields: provide idempotency and cross-artifact binding;
- source document identity, revision, and content hash: prevent assessment of the wrong source text;
- `data_matrix_version` and `as_of`: freeze the evaluated capability baseline;
- assessment `status`: determines whether strategy engineering may continue;
- artifact names and hashes: bind the assessment to its evidence.

Hashes are lowercase SHA-256 hex strings. Template values are obvious placeholders and must be replaced when producing a real artifact.

### Tolerant business content

Capability details, fallback explanations, limitations, warnings, and suggested next checks are business payload. Unknown fields are allowed and optional enrichment must not fail ingestion.

Individual capability or probe failures are isolated. A failed probe does not invalidate unrelated successful probes. The overall status is:

- `ready`: required capabilities are verified and usable;
- `ready_with_degradation`: execution is possible using an explicit degradation or fallback;
- `needs_review`: evidence is insufficient or a human must choose between material alternatives;
- `blocked`: a required capability is unavailable with no accepted fallback.

## Validation outcomes

| Condition | Outcome |
|---|---|
| Identity, revision, source hash, schema version, or artifact hash mismatch | `error` |
| Optional enrichment missing or a non-required source degraded | `warning` |
| Material fallback, ambiguous interpretation, or unverified required capability | `review` |
| Required capability unavailable without fallback | Assessment status `blocked`; preserve and ingest the assessment |

`blocked` is a valid assessment result, not a malformed delivery.

## Compatibility

- Additive fields are optional within `1.x`.
- Readers preserve original artifacts and ignore unknown compatible fields.
- New required fields or changed semantics require a new contract version and migration fixtures.
- Markdown formatting and heading order are never machine-authoritative.

## Preflight CLI

The Phase A envelope can be locally checked before WorkBuddy artifacts leave the
delivery boundary. The preflight is a single stdlib-only script that is
deployable into the shared delivery directory without installing the pipeline
package:

```bash
python3 scripts/validate_strategy_delivery.py \
    --task /path/task.json --result-dir /path/delivery
```

WorkBuddy uses the shared copy named in
`templates/capability-assessment-task.json`; exit `0` and
`validation-report.json` are required before publishing `.ready`.

It writes `validation-report.json` (schema `strategy-capability-preflight/1.0`)
inside the delivery directory (creating no parent directories) and:

- exits `0` when there are no envelope errors, including valid `ready`,
  `ready_with_degradation`, `needs_review`, or `blocked` assessments;
- exits `1` for any envelope or path error — invalid or unreadable task or
  result-dir paths, malformed JSON, schema or binding mismatches, declared hash
  mismatches, missing canonical outputs, unsafe required output names, or
  unexpected later-stage authority/activation artifacts in the delivery;
- exits `2` for argparse usage errors.

Preflight copies `findings.warnings` and `findings.reviews` from the assessment
verbatim without judging business payload, never rewrites or moves originals,
and records only filenames in the report — no host-absolute paths.

## Explicit exclusions

- Strategy rules, scoring thresholds, approval, activation, and scheduling;
- database row shapes or internal host paths;
- credentials and provider secrets;
- a universal contract shared by strategy, candidate, research, and observation stages.
