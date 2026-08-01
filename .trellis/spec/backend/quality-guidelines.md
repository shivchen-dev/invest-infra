# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

Every change must preserve architecture boundaries and leave a focused,
repeatable verification path. The repository uses Ruff, pytest/unittest,
`scripts/check_architecture.py`, and migration checks.

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

Do not import framework/database/provider SDKs into domain. Do not add
`qfq`/`hfq` to the Phase 1 production path, write the deprecated `app` schema,
commit from adapters, or enable real providers by default.

---

## Required Patterns

<!-- Patterns that must always be used -->

Keep Provider adapters behind domain ports, keep fixture data deterministic,
keep real credentials out of Git, and preserve raw evidence plus revision
semantics when changing ingestion.

---

## Testing Requirements

<!-- What level of testing is expected -->

Run the narrowest relevant tests during iteration, then run architecture and
project-level checks before acceptance. New Provider contracts require offline
fixtures/tests; external smoke tests are opt-in and separately authorized.

---

## Code Review Checklist

<!-- What reviewers should check -->

Review correctness, domain/storage/application boundaries, error and secret
handling, migration safety, idempotency, and whether the change touches only
the authorized files. Do not accept an agent's self-reported test result
without independently checking the diff and commands.

Example boundary check:

```python
from datetime import date

from invest_domain.market_data.ports import EtfMarketDataProvider

def load(provider: EtfMarketDataProvider) -> None:
    request, attempt, batch = provider.fetch_instruments(as_of=date.today())
```
