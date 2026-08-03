# AkShare Adapter (PR-02)

Phase 1 of the AkShare adapter lands the runtime adapter shape
mirroring the CifangQuant Phase 1 layout, with two **necessary**
differences:

1. The ``akshare`` dependency is **optional**. The package is
   importable from CI / local dev without the SDK; the
   :class:`AkshareClient` resolves the SDK lazily on first fetch
   call and raises
   :class:`invest_pipeline.adapters.errors.ProviderUnavailableError`
   with a pointer to ``pip install akshare`` when the module cannot
   be imported. This is mandated by matrix §10 — the slice ships
   without the third-party dependency and operators opt in by
   installing it.
2. The public configuration is **disabled by default**. Even when
   the SDK is installed, ``AkshareSettings.enabled=False`` keeps the
   adapter inert; ``fetch_instruments`` / ``fetch_daily_bars`` raise
   :class:`~invest_pipeline.adapters.errors.RealProviderRequiresExplicitEnablementError`
   so callers never silently hit the network in tests.

## Layout

| Module | Role |
|--------|------|
| `client.py` | Lazy `import akshare` wrapper. Exposes `fetch_fund_etf_fund_info_em()` for the ETF master-data path and `fetch_fund_etf_hist_em(symbol=..., start_date=..., end_date=...)` for the per-symbol daily-bars path. Normalises the pandas `DataFrame` returns to list-of-dicts so the rest of the stack stays `pandas`-free. |
| `mapper.py` | Pure field mappers (master data + daily bars). SSE / SZSE allow-list, ETF filter, OHLC invariant, nullable `prev_close` / `amount`. No `akshare` / `pandas` imports. |
| `adapter.py` | Evidence-tuple adapter (`ProviderRequest` / `ProviderAttempt` / `ProviderBatch`). Owns the disabled-by-default gate, the request-key deterministic stamping and the typed-error classification. |
| `config.py` | `AkshareSettings`: disabled by default, `adjust=""` locked at construction time, optional redacted SDK token, bounded `timeout_seconds`. |

Boundary rule: client → mapper → adapter → domain. `client.py` is the
only module that may import `akshare` (lazily).

## Usage

```python
from datetime import date
from invest_pipeline.adapters.akshare import (
    AkshareInstrumentProvider,
    AkshareSettings,
)

settings = AkshareSettings()       # enabled=False, adjust=""
provider = AkshareInstrumentProvider(settings)
assert provider.provider_key == "akshare"

provider.fetch_instruments(date(2026, 7, 30))
# RealProviderRequiresExplicitEnablementError: ... (PR-02 / matrix §6)
```

To exercise the wired adapter under tests, inject a stub `module`:

```python
from types import SimpleNamespace
from invest_pipeline.adapters.akshare import (
    AkshareClient,
    AkshareInstrumentProvider,
    AkshareSettings,
)


def _fake_fund_etf_fund_info_em():
    return [{"基金代码": "510300", "基金简称": "沪深300ETF"}]


settings = AkshareSettings()
object.__setattr__(settings, "enabled", True)
stub_module = SimpleNamespace(
    fund_etf_fund_info_em=_fake_fund_etf_fund_info_em,
)
client = AkshareClient(settings, module=stub_module)
provider = AkshareInstrumentProvider(
    settings=settings,
    client=client,
    clock=lambda: datetime(2026, 7, 30, tzinfo=timezone.utc),
)
request, attempt, batch = provider.fetch_instruments(date(2026, 7, 30))
```

The real adapter path stays inert until both `enabled=True` and the
`akshare` SDK are installed. The failure path surfaces a typed
`ProviderUnavailableError` (carrying `provider_key="akshare"` and an
install hint) so CI never silently hits the upstream service.

## Risks carried forward (matrix §3 / §5.4)

- **Aggregator library**: AkShare is a community aggregator over many
  upstream sources; ARC-confirmed rate-limit / blocking events in the
  archive. Matrix §5.4 forbids treating AkShare as a production SLA
  source; the default role is `research_only` until O-1 is closed.
- **No upstream SLA contract**: the SDK does not ship a documented
  rate limit, quota or endpoint stability guarantee. Operators that
  enable AkShare must accept that a future API rename can break the
  adapter mid-flight. The client raises a typed
  `ProviderUnavailableError` when the expected function name is not
  present on the installed module so the failure surfaces cleanly.
- **Adjustment must be `""`**: AkShare uses an empty string for the
  "no adjustment" literal. The legacy `hfq` / `qfq` values
  documented in matrix §5.3 must never reach the production path —
  `AkshareSettings.adjust` is locked to `""` at construction time.
- **Optional install**: when `akshare` is not installed the adapter
  continues to import cleanly but every fetch raises a typed
  `ProviderUnavailableError`. The install hint is included in the
  message so operators do not have to guess.

## What is **still** out of scope

- AkShare `fund_etf_fund_info_em` / `fund_etf_hist_em` are the only
  two operations the Phase 1 adapter ships. NAV, fund-list
  extensions and trading-calendar ingestion are deliberately deferred
  to a follow-up PR per matrix §10.
- No smoke CLI lands in this increment; the existing
  `cifang_smoke.py` pattern remains the only network-touching entry
  point and the AkShare adapter is exercised via the unit-test
  suite (with an injected stub module).
- No Dagster asset, schedule, database migration or production
  secret rotation is added.
- No new dependency is added to `pyproject.toml`; the SDK stays an
  **opt-in** install per matrix §10.
- `provider_factory.build_provider` is extended with an explicit
  `akshare_settings` seam and an `akshare` branch behind the
  `enabled=true` gate; the existing two-key surface remains
  observable through `KNOWN_PROVIDER_KEYS`.
