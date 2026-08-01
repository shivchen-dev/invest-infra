# Implement CifangQuant HTTP adapter

## Goal

Implement the second, fixture-first increment of the CifangQuant ETF adapter:
an auditable HTTP client, response mapper, retry/error classification, and
three-layer evidence adapter. Real credentials and runtime provider selection
remain disabled until ADR-0011 O-1/O-3/O-4 are resolved.

## Requirements

- Use `httpx` only inside `apps/pipeline`; support injectable transport, sleep,
  and clock dependencies so CI never calls the network or waits in real time.
- Call the ADR-0011 endpoints `/api/fund/list` and `/api/fund/hist_em` with
  `x-api-key`, `adjust=none`, bounded timeouts, and at most three attempts for
  retryable network/429/5xx failures.
- Never place the API key in request parameters, evidence payloads, exception
  text, logs, or fixtures. Keep `enabled=False` by default.
- Map only SSE/SZSE ETF data: `SH`/`SZ` become `SSE`/`SZSE`; dates and numeric
  values become domain types; `amount` and `prev_close` remain nullable and
  are never synthesized.
- Reject malformed, non-ETF, unsupported-exchange, invalid-OHLC, or non-`none`
  adjustment responses with classified provider/domain errors.
- Split daily-bar requests into chunks of at most 50 symbols and aggregate the
  standardized records into the existing single evidence tuple shape.

## Acceptance Criteria

- [ ] Client and mapper are covered by MockTransport/fake-clock tests for
  success, mapping, malformed responses, auth, rate limit, 5xx, timeout,
  retry count, and 50-symbol batching.
- [ ] Adapter returns valid `ProviderRequest`, `ProviderAttempt`, and
  `ProviderBatch` objects on success and classified failed attempts without a
  batch; request params contain no secret.
- [ ] Existing placeholder contract tests remain green; Cifang stays disabled
  by default and no Dagster/provider-selection/database code is changed.
- [ ] `uv run pytest` focused tests, `uv run ruff check`, and the architecture
  checker pass.

## Out of scope

- Provider runtime selection, Dagster jobs/assets, migrations, database writes,
  production secret setup, and real smoke execution.
- Changing the Domain contract solely to accommodate an unverified provider
  field; if `prev_close=None` conflicts with current normal-bar invariants,
  document the blocker and add only the smallest contract-compatible test or
  change required by ADR-0005.
