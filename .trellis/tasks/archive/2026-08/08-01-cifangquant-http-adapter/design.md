# Design: CifangQuant HTTP adapter

## Boundaries

- `client.py` owns HTTP, headers, timeout, retry, batching, and transport
  exceptions. It returns decoded provider payloads and never touches storage.
- `mapper.py` owns provider-field aliases, exchange/type/date/Decimal mapping,
  ETF filtering, and domain validation. It never imports `httpx`.
- `adapter.py` composes client and mapper, stamps UTC evidence objects, hashes
  the canonical response representation, and converts failures into the
  existing `ProviderAttempt` taxonomy.
- `config.py` remains disabled by default and keeps `adjustment="none"` locked.

## Request and retry model

`CifangClient` receives an optional `httpx.Client`/transport, `sleep` callable,
and clock. It sends `x-api-key` only as a header. `401/403` fail immediately;
`429`, `5xx`, timeout, and transport failures retry with bounded exponential
backoff. JSON decoding and response-contract errors do not retry. The client
uses a 50-symbol chunker for historical bars; the adapter aggregates chunks
while preserving a deterministic request key and warning about chunk count.

## Evidence model

Each public adapter call returns the existing
`(ProviderRequest, ProviderAttempt, ProviderBatch | None)` tuple. A successful
aggregated response creates one batch and one attempt. A failed call creates a
failed attempt with a `ProviderFailureStage` and no batch. Secret-bearing
headers are never copied into `ProviderRequest.params` or error messages.

## Contract risk

ADR-0011 permits missing `prev_close` and `amount`. Before implementation,
verify the current `DailyBar` normal-row invariants. The mapper must preserve
missing values; it must not invent a previous close. If the existing domain
rejects a valid nullable provider response, record the smallest domain contract
adjustment separately from the adapter and cover it with a domain test.

## Verification

Use MockTransport/fakes only. Run focused pipeline tests, Ruff, and
`python3 scripts/check_architecture.py`; do not run a real Cifang request.
