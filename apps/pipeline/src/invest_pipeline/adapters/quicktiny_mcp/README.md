# QuickTiny MCP Adapter (PR-03, research_only)

PR-03 implements a **read-only** adapter for the QuickTiny MCP endpoint
documented in `docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md` §9.1
/ §9.2. The adapter is intentionally narrow:

- Research / market-snapshot only (`ProviderCapability.RESEARCH` /
  `MARKET_SNAPSHOT`).
- Read-only MCP methods: `initialize`, `tools/list`, `tools/call`
  for `etf_market` and `index_market` only.
- Disabled by default; real MCP traffic requires an explicit
  `INVEST_PIPELINE_QUICKTINY_MCP_ENABLED=true` plus a non-empty token.

The adapter deliberately **does not**:

- Map responses to `invest_domain.market_data.models.DailyBar`.
- Advertise `ETF_DAILY_BARS` / `ETF_MASTER_DATA` / `INDEX_DAILY_BARS`.
- Extend `invest_pipeline.provider_factory.build_provider` with an ETF
  branch — the catalog declaration
  `invest_pipeline.provider_catalog.QUICKTINY_MCP` remains the single
  source of truth.
- Introduce database migrations or persist any evidence.

## Layout

| Module    | Role |
|-----------|------|
| `config.py`  | `QuickTinyMcpSettings`: redacted bearer token, disabled-by-default flag, bounded timeout, official `base_url` default. |
| `client.py`  | JSON-RPC 2.0 transport over `httpx.Client`. Bearer-token header injection, error classification, deterministic SHA-256. |
| `models.py`  | Frozen / hashable response / result dataclasses + `etf_market` / `index_market` normaliser. No `httpx` import. |
| `__init__.py` | Public re-exports. |

The models never import `httpx`; the client never imports the domain
layer. Boundary rule: `client` → `models` → application layer.

## Settings contract

```python
from invest_pipeline.adapters.quicktiny_mcp import QuickTinyMcpSettings

settings = QuickTinyMcpSettings()        # enabled=False, token empty
assert settings.enabled is False
assert settings.base_url == "https://stock.quicktiny.cn/api/mcp"
assert settings.timeout_seconds == 30.0
assert "***" in repr(settings)           # token never echoed
```

| Env var | Field |
|---------|-------|
| `INVEST_PIPELINE_QUICKTINY_MCP_ENABLED` | `enabled` (bool, default `False`) |
| `INVEST_PIPELINE_QUICKTINY_MCP_BASE_URL` | `base_url` (str, default `https://stock.quicktiny.cn/api/mcp`) |
| `INVEST_PIPELINE_QUICKTINY_MCP_TOKEN` | `token` (`SecretStr`, default empty) |
| `INVEST_PIPELINE_QUICKTINY_MCP_TIMEOUT_SECONDS` | `timeout_seconds` (float, default `30.0`) |

## Client contract

```python
import httpx
from invest_pipeline.adapters.quicktiny_mcp import (
    QuickTinyMcpClient,
    QuickTinyMcpSettings,
)

settings = QuickTinyMcpSettings()
client = QuickTinyMcpClient(
    settings,
    transport=httpx.MockTransport(handler),
    id_factory=lambda: "fixed-id",
)
init = client.initialize()
tools = client.list_tools()
call = client.call_tool("etf_market", {"symbol": "510300"})
```

The transport is injectable so CI never reaches the network; tests use
`httpx.MockTransport` and inject a deterministic `id_factory` for
stable replay assertions.

## What is **still** out of scope

- Dagster assets / schedules / persistence.
- `etf_market` → `DailyBar` mapping (matrix §3 / §5.4 / §9.2 forbid it).
- Provider Factory branch — the adapter is wired through the catalog
  declaration only; the runtime factory remains on its three-key
  surface (`fixture_dev` / `cifangquant` / `akshare`).
- Real network smoke — out of scope for this slice; the offline test
  suite is the only CI gate.

These remain gated on O-1 / O-3 / O-4 / O-5 / O-6 closure per the V2
data-source plan.