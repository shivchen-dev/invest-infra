# Error Handling

> How errors are handled in this project.

---

## Overview

<!--
Document your project's error handling conventions here.

Questions to answer:
- What error types do you define?
- How are errors propagated?
- How are errors logged?
- How are errors returned to clients?
-->

Errors are validated at the boundary that owns the invariant. Domain models
raise `TypeError`/`ValueError` or `ProviderDataContractError`; adapters use the
typed errors in `apps/pipeline/src/invest_pipeline/adapters/errors.py`; API
routers translate expected lookup/validation failures to FastAPI HTTP errors.

---

## Error Types

<!-- Custom error classes/types -->

Provider errors must retain the provider key and classify authentication,
rate-limit, transport, payload, and not-implemented conditions. Failed
Provider attempts must retain error stage/code/message and must not create a
successful batch. Unexpected errors propagate to the application boundary.

---

## Error Handling Patterns

<!-- Try-catch patterns, error propagation -->

API routers return the existing response schemas and use explicit HTTP status
codes. Do not expose database exceptions, credentials, raw provider payloads,
or internal stack traces to clients.

---

## API Error Responses

<!-- Standard error response format -->

Do not catch `Exception` just to return success, silently fall back to another
date, or synthesize missing market data. Preserve audit evidence for failed
provider attempts.

---

## Common Mistakes

<!-- Error handling mistakes your team has made -->

(To be filled by the team)
