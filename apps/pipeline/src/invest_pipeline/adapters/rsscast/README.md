# RssCast MCP Adapter (PR-04, research / index only)

PR-04 implements a **read-only** adapter for the RssCast MCP endpoint
documented in `docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md` §1
/ §3 / §5.4. The adapter is intentionally narrow:

- Research / index only (`ProviderCapability.RESEARCH` /
  `INDEX_DAILY_BARS`). Matrix §3 pins the role to
  `out_of_scope_for_etf`; matrix §5.4 plus the plan PR-01 "do not claim
  ETF daily bars for RssCast" constraint forbid the adapter from
  advertising `ETF_DAILY_BARS` or `ETF_MASTER_DATA`.
- Read-only MCP methods: `initialize`, `tools/list`, `tools/call` for
  research / stock / index / news tools only. ETF DailyBar-shaped tool
  names (e.g. `etf_daily_bars`, `fund_history`, `etf_kline_em`) are
  rejected up-front via
  `invest_pipeline.adapters.rsscast.models.is_forbidden_tool_name` so a
  misconfigured caller cannot trick the adapter into mapping an
  upstream ETF DailyBar-shaped response into a production
  `core.daily_bars` row.
- Disabled by default; real MCP traffic requires an explicit
  `INVEST_PIPELINE_RSSCAST_ENABLED=true` plus a non-empty token and a
  configured base URL (matrix §1 explicitly does not freeze a fixed
  endpoint, so the adapter refuses to ship a hard-coded default).

The adapter deliberately **does not**:

- Map responses to `invest_domain.market_data.models.DailyBar`.
- Advertise `ETF_DAILY_BARS` / `ETF_MASTER_DATA`.
- Extend `invest_pipeline.provider_factory.build_provider` with an ETF
  branch — the catalog declaration
  `invest_pipeline.provider_catalog.RSSCAST` remains the single source
  of truth.
- Introduce database migrations or persist any evidence.

## Layout

| Module    | Role |
|-----------|------|
| `config.py`  | `RssCastMcpSettings`: redacted bearer token, disabled-by-default flag, bounded timeout, **empty** `base_url` default per matrix §1. |
| `client.py`  | JSON-RPC 2.0 transport over `httpx.Client`. Bearer-token header injection, error classification, deterministic SHA-256, ETF DailyBar tool-name rejection. |
| `models.py`  | Frozen / hashable response / result dataclasses + `RssCastMcpResearchResponse` normaliser with provider/tool name, request params hash, response hash, payload, error/limit status. No `httpx` import. |
| `__init__.py` | Public re-exports. |

The models never import `httpx`; the client never imports the domain
layer. Boundary rule: `client` → `models` → application layer.

## Settings contract

```python
from invest_pipeline.adapters.rsscast import RssCastMcpSettings

settings = RssCastMcpSettings()             # enabled=False, base_url="", token empty
assert settings.enabled is False
assert settings.base_url == ""              # matrix §1: no frozen default
assert settings.timeout_seconds == 30.0
assert "***" in repr(settings)              # token never echoed
```

| Env var | Field |
|---------|-------|
| `INVEST_PIPELINE_RSSCAST_ENABLED` | `enabled` (bool, default `False`) |
| `INVEST_PIPELINE_RSSCAST_BASE_URL` | `base_url` (str, default empty per matrix §1) |
| `INVEST_PIPELINE_RSSCAST_TOKEN` | `token` (`SecretStr`, default empty) |
| `INVEST_PIPELINE_RSSCAST_TIMEOUT_SECONDS` | `timeout_seconds` (float, default `30.0`) |

The matrix §1 explicitly notes "归档未冻结固定端点" — the archive did
not freeze a fixed endpoint. Operators must set
`INVEST_PIPELINE_RSSCAST_BASE_URL` to the documented endpoint before
enabling the adapter. The `config.py` module validates the URL when
set (must start with `http://` or `https://`).

## Client contract

```python
import httpx
from invest_pipeline.adapters.rsscast import (
    RssCastMcpClient,
    RssCastMcpSettings,
)

settings = RssCastMcpSettings(
    base_url="https://example.rsscast/api/mcp",  # placeholder URL
    token="...",
)
client = RssCastMcpClient(
    settings,
    transport=httpx.MockTransport(handler),
    id_factory=lambda: "fixed-id",
)
init = client.initialize()
tools = client.list_tools()
call = client.call_tool("stock_quote", {"symbol": "600519"})
```

The transport is injectable so CI never reaches the network; tests use
`httpx.MockTransport` and inject a deterministic `id_factory` for
stable replay assertions.

ETF DailyBar-shaped tool names are rejected up-front:

```python
client.call_tool("etf_daily_bars")          # raises ProviderDataContractError
client.call_tool("fund_history_em")         # raises ProviderDataContractError
client.call_tool("stock_quote", {...})      # OK
```

## What is **still** out of scope

- Dagster assets / schedules / persistence.
- `tools/call` → `DailyBar` mapping (matrix §3 / §5.4 / §9 forbid it).
- Provider Factory branch — the adapter is wired through the catalog
  declaration only; the runtime factory remains on its three-key
  surface (`fixture_dev` / `cifangquant` / `akshare`).
- Real network smoke — out of scope for this slice; the offline test
  suite is the only CI gate.

These remain gated on O-1 / O-3 / O-4 / O-5 / O-6 closure per the V2
data-source plan.