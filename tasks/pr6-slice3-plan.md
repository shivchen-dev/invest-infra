# PR-6 Slice 3: Research Orchestration and Failure Recovery

## Scope

Add one Pipeline application service that coordinates the existing
`ResearchCase`, `ResearchRun`, `EvidencePack`, `ResearchRunner`, and PR-5.5
repositories. No schema, domain, API, Dagster, or provider changes.

## Tasks

1. Load and validate the case, run, and immutable evidence pack through one
   read transaction; reject missing or misaligned lifecycle inputs.
2. Persist the queued-to-running transition before invoking the external
   runner, then bind its external request/session identity when available.
3. Persist an immutable result and the running-to-succeeded transition in one
   transaction. Replays return the existing equivalent result and never create
   a second successful result for the same run/session.
4. Classify request-before-acceptance failures, uncertain timeouts, remote
   rejection, malformed reports, and persistence conflicts without fabricating
   a success result.

## Acceptance

- Normal completion persists exactly one result and closes the run/case.
- Duplicate callback/replay is idempotent; a divergent result conflicts.
- External session uniqueness and uncertain timeout behavior are covered.
- Pipeline tests, Ruff, architecture checks, and diff checks pass.

## Boundary

This slice does not add the read-only Research API and does not claim semantic
truthfulness of model prose; semantic acceptance remains an explicit gate.
