# CifangQuant Adapter (Phase 1 first increment)

Phase 1 of the CifangQuant adapter is a **placeholder** that only
exposes the domain
[`EtfMarketDataProvider`](../../../../packages/domain/src/invest_domain/market_data/ports.py)
shape. Both `fetch_instruments` and `fetch_daily_bars` raise
`ProviderAdapterNotImplementedError` with a pointer to
[ADR-0011](../../../../docs/adr/0011-cifangquant-primary-etf-provider.md).

The placeholder exists so that:

- the `cifangquant` provider key and its redacted settings can be
  referenced from configuration and from the eventual Provider Registry
  without leaking any implementation detail;
- the application service / Dagster asset surface can route through
  a stable failure category
  (`ProviderAdapterNotImplementedError`) instead of `NotImplementedError`
  (ADR-0003 §4);
- unit tests can assert the redaction, `adjustment=none` lock and
  default-disabled behaviour without a network or PostgreSQL dependency.

## What is **not** in this increment

- No `httpx` / HTTP client.
- No field mapper for `/api/fund/list` or `/api/fund/hist_em`.
- No rate limiting, retry, or error classification.
- No real credential handling beyond `pydantic.SecretStr` redaction.

These land in the second Phase 1 increment, gated on O-1 / O-3 / O-4
(see ADR-0011 §4).

## Usage

```python
from invest_pipeline.adapters.cifang import (
    CifangQuantInstrumentProvider,
    CifangSettings,
)

settings = CifangSettings()          # enabled=False, adjustment="none"
provider = CifangQuantInstrumentProvider(settings)
assert provider.provider_key == "cifangquant"
```

Attempting any `fetch_*` call raises:

```
ProviderAdapterNotImplementedError: [cifangquant] fetch_instruments(... ) not
implemented. CifangQuantAdapter is a Phase 1 placeholder (ADR-0011,
Status: Proposed). ...
```

## Risks carried forward

The placeholder deliberately keeps `enabled=False` and `adjustment="none"`
locked. The archived CifangQuant default of `qfq` adjustment (see
`docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md` §5.3) is **not**
exposed anywhere in this package; any future change that loosens
`adjustment` must come with a new ADR.