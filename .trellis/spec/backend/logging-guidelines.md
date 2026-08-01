# Logging Guidelines

> How logging is done in this project.

---

## Overview

<!--
Document your project's logging conventions here.

Questions to answer:
- What logging library do you use?
- What are the log levels and when to use each?
- What should be logged?
- What should NOT be logged (PII, secrets)?
-->

The current codebase uses standard application/runtime output and structured
metadata attached to Dagster materializations; no new logging dependency is
part of the baseline. Add logging only at an application boundary where it
helps diagnose a run or provider attempt.

---

## Log Levels

<!-- When to use each level: debug, info, warn, error -->

Use debug for local diagnostics, info for lifecycle milestones, warning for
recoverable quality issues, and error for failed runs or provider attempts.
Include provider key, dataset, request key, run ID, and error code when known.

---

## Structured Logging

<!-- Log format, required fields -->

Prefer stable named fields over interpolated payload dumps. Keep logs
correlatable with `ops.pipeline_runs` and the raw provider evidence tables.

---

## What to Log

<!-- Important events to log -->

Log start/end/failure of meaningful ingestion operations and quality summaries,
not every row. Preserve warnings in ProviderBatch metadata when they belong to
the data contract.

---

## What NOT to Log

<!-- Sensitive data, PII, secrets -->

Never log API keys, cookies, authorization headers, database passwords, full
raw provider responses, or personal data. Cifang settings use `SecretStr` and
redacted representations.
