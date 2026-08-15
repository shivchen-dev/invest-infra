# Strategy Artifact Template Governance

## 1. Purpose

This document governs the design and evolution of strategy-library and stage-delivery artifact templates. Its purpose is to keep contracts traceable and machine-consumable without making agent-produced deliverables too rigid to enter the workflow.

It applies to strategy, candidate, research, and observation artifacts, including JSON contracts, Markdown templates, validators, ingestion rules, and admission gates.

## 2. Governing principle

Use the smallest stable machine contract that preserves identity, integrity, provenance, and safe routing. Allow business content to become richer over time without turning formatting differences or non-critical omissions into workflow failures.

Templates guide delivery. They are not database models, exhaustive ontologies, or permission to predict every future requirement.

## 3. Three-layer contract

### 3.1 Strict envelope

The envelope contains only fields required for safe routing, idempotency, version interpretation, and audit. Examples include task identity, stage, schema version, strategy identity and version when applicable, delivery status, generation time, artifact inventory, and content hashes.

Missing, contradictory, or invalid envelope data may fail closed when the system cannot safely identify, deduplicate, interpret, or audit the delivery.

### 3.2 Tolerant business payload

Strategy rules, candidate reasons, scores, risks, evidence summaries, and analytical conclusions must support reasonable agent variation.

- Separate required facts from optional enrichment.
- Accept unknown extension fields unless they create ambiguity or risk.
- Do not require fields merely because they may be useful later.
- Isolate invalid items in a batch; valid items continue whenever identity and integrity remain sound.
- Route ambiguous but recoverable content to review instead of rejecting the entire delivery.
- Preserve the original artifact alongside normalized or extracted data.

### 3.3 Human-readable report

Markdown reports use recommended section templates for readability and review. Exact headings, ordering, prose style, and formatting are not machine-authoritative unless a specific requirement is justified and documented.

Structured JSON is the machine-processing authority. A report formatting defect alone must not invalidate an otherwise safe structured delivery.

## 4. Validation severity

Every validation rule must declare one of three outcomes:

- `error`: identity, integrity, version interpretation, security, or authoritative admission is unsafe; stop the affected scope.
- `warning`: content is usable but incomplete or lower confidence; continue and record the limitation.
- `review`: deterministic handling is unsafe, but the artifact can be preserved and routed for human decision.

Do not use `error` for presentation quality, preferred wording, optional enrichment, or speculative future needs.

Validation operates at the narrowest safe scope. An invalid candidate item must not fail a valid batch unless the batch envelope itself is invalid.

## 5. Template design rules

For every template or schema change:

1. State the business decision or workflow operation enabled by each required field.
2. Keep identity and provenance separate from analytical content.
3. Mark fields explicitly as required, optional, or extension.
4. Provide one minimal valid example and representative degraded examples.
5. Define `error`, `warning`, and `review` behavior before implementation.
6. Define item-level isolation, retry, and original-artifact retention behavior.
7. Reuse existing domain concepts; do not mirror the complete domain model into an artifact.
8. Prefer a small stable core plus versioned extensions over a large initial schema.

## 6. Compatibility and evolution

- Every machine contract has an explicit `schema_version`.
- Compatible additions are optional by default.
- Existing readers ignore unknown compatible fields while preserving original artifacts.
- A new required field needs a demonstrated workflow or safety requirement, migration handling, fixtures, and compatibility tests.
- Incompatible semantic changes require a new contract version; never reinterpret archived artifacts silently.
- Strategy evolution uses proposals, validation, review, and immutable new strategy versions. It does not mutate historical artifacts or active versions in place.

## 7. Candidate-flow tolerance

Candidate discovery is a broad-input stage and must not demand perfect analytical standardization from an agent.

The expected flow is:

```text
validate delivery envelope
  -> parse candidates independently
  -> admit valid items
  -> route incomplete but recoverable items to review
  -> isolate invalid items
  -> retain the original delivery and diagnostics
```

CandidateAdmission may remain strict about symbol identity, date, provenance, duplication, freshness, and authoritative data checks. Discovery-report style, optional explanation depth, and non-critical enrichment must not become admission hard gates.

## 8. Anti-overengineering constraints

Do not:

- build one universal schema for every strategy and stage;
- make all fields required to simplify validator implementation;
- duplicate storage aggregates in delivery JSON;
- parse Markdown as the primary business contract;
- reject an entire batch because one item is malformed;
- create fields, states, abstractions, or extension systems without a current accepted use case;
- treat a tool, process, HTTP response, or file appearance as proof of business completion;
- raise gates solely to make agent output look uniform.

## 9. Review checklist

Before approving a template or gate, confirm:

- the minimum valid artifact is genuinely minimal;
- every hard failure protects a specific safety or authority boundary;
- agent variation has a warning or review path;
- malformed batch items are isolated;
- reports remain readable without becoming machine-authoritative;
- compatibility, replay, provenance, and original-artifact retention are defined;
- the design serves the current vertical slice rather than a hypothetical platform.
