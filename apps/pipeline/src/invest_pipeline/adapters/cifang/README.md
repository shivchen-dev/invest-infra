# CifangQuant Adapter (Phase 1, ADR-0011)

Phase 1 of the CifangQuant adapter spans two increments:

1. **First increment (placeholder):** settings object with the
   ``adjustment="none"`` lock and ``enabled=False`` default;
   ``ProviderAdapterNotImplementedError`` for both ``fetch_*`` methods
   with a pointer to [ADR-0011](../../../../docs/adr/0011-cifangquant-primary-etf-provider.md).
2. **Second increment (this increment — fixture-first):** the real
   httpx-backed client, field mapper and three-layer evidence-tuple
   adapter. The Provider stays disabled by default
   (``RealProviderRequiresExplicitEnablementError`` until
   ``enabled=True``) and every transport side effect (httpx transport,
   sleep, clock) is injected so CI never reaches the network.

Both increments share the same package
(`apps/pipeline/src/invest_pipeline/adapters/cifang/`) so the public
surface stays stable:

```python
from invest_pipeline.adapters.cifang import (
    CifangQuantInstrumentProvider,
    CifangSettings,
)
```

## Layout

| Module | Role |
|--------|------|
| `client.py` | ``httpx`` wrapper: endpoints, headers, timeout, retry, error classification, 50-symbol chunking. |
| `mapper.py` | Domain mappers for ``/api/fund/list`` and ``/api/fund/hist_em``. Pure functions over a ``CifangResponse``; no httpx. |
| `adapter.py` | Evidence-tuple adapter (``ProviderRequest`` / ``ProviderAttempt`` / ``ProviderBatch``). Owns the disabled-by-default gate and the UTC clock. |
| `config.py` | ``CifangSettings``: redacted ``api_key``, locked ``adjustment="none"``, disabled by default. |

The mapper never imports ``httpx``; the client never imports the domain
layer. Boundary rule: client → mapper → adapter → domain.

## What is **still** out of scope

- Dagster provider-selection / assets / schedules.
- Database migrations / persistence.
- Production secret rotation / real smoke.
- Any change to the `fixture_dev` default Provider.

These remain gated on ADR-0011 O-1 / O-3 / O-4 closure.

## Usage

```python
from datetime import date
from invest_pipeline.adapters.cifang import (
    CifangQuantInstrumentProvider,
    CifangSettings,
)

settings = CifangSettings()          # enabled=False, adjustment="none"
provider = CifangQuantInstrumentProvider(settings)
assert provider.provider_key == "cifangquant"

provider.fetch_instruments(date(2026, 7, 30))
# RealProviderRequiresExplicitEnablementError: ... (ADR-0011 §4)
```

To exercise the wired adapter under tests, inject an
``httpx.MockTransport`` and a fake clock:

```python
import httpx
from invest_pipeline.adapters.cifang import (
    CifangClient,
    CifangQuantInstrumentProvider,
    CifangSettings,
)

settings = CifangSettings()
object.__setattr__(settings, "enabled", True)
client = CifangClient(
    settings,
    transport=httpx.MockTransport(my_handler),
    sleep=lambda _: None,
)
provider = CifangQuantInstrumentProvider(
    settings=settings,
    client=client,
    clock=lambda: datetime(2026, 7, 30, tzinfo=timezone.utc),
)
request, attempt, batch = provider.fetch_instruments(date(2026, 7, 30))
```

## Risks carried forward

The adapter deliberately keeps ``enabled=False`` and
``adjustment="none"`` locked. The archived CifangQuant default of
``qfq`` adjustment (see
`docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md` §5.3) is **not**
exposed anywhere in this package; any future change that loosens
``adjustment`` must come with a new ADR.

## Smoke command (opt-in)

The repo ships a CLI wrapper for an explicit, network-hitting smoke
against the official CifangQuant API. It is **safe by default**: the
real HTTP client is only constructed when **both** the settings
opt-in (``INVEST_PIPELINE_CIFANG_ENABLED=true``) and the
``--confirm-network`` CLI flag are present. The API key is read only
from the ``INVEST_PIPELINE_CIFANG_API_KEY`` environment variable and is
never accepted as a CLI argument and never printed.

```bash
export INVEST_PIPELINE_CIFANG_ENABLED=true
export INVEST_PIPELINE_CIFANG_API_KEY=...      # never echoed by `make`
make provider-smoke \
    SMOKE_SYMBOLS=510300,510500 \
    SMOKE_TRADE_DATE=2026-07-30 \
    SMOKE_CONFIRM_NETWORK=1
```

The command runs only the two adapter calls needed for a minimal
smoke (`fetch_instruments(as_of=trade_date)` and
`fetch_daily_bars(symbols, start_date=trade_date, end_date=trade_date)`),
prints a single redacted JSON summary to stdout, and exits non-zero on
any failure. Data is never persisted. The same command is also
available directly:

```bash
cd apps/pipeline && uv run python -m invest_pipeline.cifang_smoke \
    --symbols 510300,510500 \
    --trade-date 2026-07-30 \
    --confirm-network
```

Both invocations require the same three opt-in levers; if any of them
is missing the command exits non-zero with a concise message and never
reaches the network.