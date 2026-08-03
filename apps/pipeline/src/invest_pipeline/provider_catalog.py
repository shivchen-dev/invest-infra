"""Provider catalog declarations for the V2 pipeline (stdlib only).

This module is a **declaration catalog**, not an adapter implementation.
It records the ``provider_key``, ``role``, ``capabilities`` and
``enabled_by_default`` flag of every provider the V2 codebase references
by name. PR-01 (see
``docs/plan/invest-infra-v2-all-data-sources-integration-plan.md``)
freezes the full five-entry catalog:

```text
fixture_dev   cifangquant   akshare   rsscast   quicktiny_mcp
```

The module is intentionally small:

* No HTTP, MCP or SDK transport is imported.
* No API key, token or credential handling is wired in.
* No runtime provider selection, factory or registry is implemented in
  this module. The runtime factory
  (:mod:`invest_pipeline.provider_factory`) owns construction and keeps
  its own two-key surface (``fixture_dev`` / ``cifangquant``); the
  factory is intentionally **not** extended in this increment.
* No Dagster asset, schedule or database migration is added.
* No external network call is issued.

The entries mirror ``docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md``
§2 / §3 / §5.4 / §6:

* ``fixture_dev`` is the deterministic in-repo provider used by dev and
  tests; matrix §3 pins its role as ``fixture_dev`` and matrix §6 keeps
  it on by default. It advertises the ETF master-data and ETF daily-bars
  capabilities that the on-disk ``etf_instruments.json`` and
  ``etf_daily_bars.json`` fixtures cover.
* ``cifangquant`` is the real ETF primary / secondary source already
  wired in the runtime factory; matrix §3 pins its role as
  ``secondary`` (only after O-1) and §6 keeps it disabled by default.
  The catalog records the three capabilities the matrix §2 already
  observed (``ETF_DAILY_BARS`` / ``ETF_MASTER_DATA`` / indirect
  ``INDEX_DAILY_BARS``).
* ``akshare`` is the aggregator library that matrix §3 keeps in the
  safer ``research_only`` role until O-1 is closed. The catalog
  advertises the three capabilities matrix §2 observed (ETF master
  data, ETF daily bars, indirect index daily bars) but matrix §5.4
  forbids it from being treated as a production SLA source, so the
  default stays off.
* ``rsscast`` is the MCP research / index source; matrix §3 pins its
  role as ``out_of_scope_for_etf`` and matrix §5.4 explicitly forbids
  it from claiming ``ETF_DAILY_BARS`` (the plan PR-01 "do not claim ETF
  daily bars for RssCast" constraint). The catalog advertises only
  ``INDEX_DAILY_BARS`` and ``RESEARCH`` (the "research / index only"
  set called out by the plan).
* ``quicktiny_mcp`` is the MCP research / market-snapshot source;
  matrix §5.4 and the plan PR-01 "research / market_snapshot only"
  constraint forbid it from claiming ``ETF_DAILY_BARS`` (or any ETF
  / index daily-bars capability). The catalog advertises only
  ``RESEARCH`` and ``MARKET_SNAPSHOT``.

Every real provider stays ``enabled_by_default=False`` per matrix §6.
The negative-capability assertions for RssCast and Quicktiny are part
of the catalog's public contract so a future regression cannot
silently slip an ETF daily-bars capability into a research-only
source.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProviderRole(StrEnum):
    """Stable role identifiers for a provider in the V2 pipeline.

    The string values are frozen by ``DATA-SOURCE-MIGRATION-MATRIX.md``
    §3 and must not change without an ADR. ``RESEARCH_ONLY`` declares
    that the provider is not a production SLA source and must not be
    used as a primary or secondary ingest path. ``OUT_OF_SCOPE_FOR_ETF``
    is the role the matrix assigns to sources that may legitimately
    serve research / index data but must never feed the ETF daily
    pipeline.
    """

    RESEARCH_ONLY = "research_only"
    SECONDARY = "secondary"
    PRIMARY = "primary"
    OUT_OF_SCOPE_FOR_ETF = "out_of_scope_for_etf"
    FIXTURE_DEV = "fixture_dev"


class ProviderCapability(StrEnum):
    """Stable capability identifiers a provider may advertise.

    The string values are the canonical names referenced from
    ``DATA-SOURCE-MIGRATION-MATRIX.md`` §2 and the V2 all-data-sources
    plan §3. The five values let the catalog distinguish the data
    surfaces the V2 pipeline cares about:

    * ``ETF_DAILY_BARS`` / ``ETF_MASTER_DATA`` cover the production ETF
      data path (raw provider evidence -> ``core.daily_bars`` and
      ``core.instruments``). Only providers the matrix and ADR-0011
      admit into the production data path may claim them.
    * ``INDEX_DAILY_BARS`` covers the index surfaces that share
      storage with the ETF path but historically came from a
      different source family (matrix §2 observed CifangQuant, AkShare
      and RssCast as indirect / direct index sources).
    * ``RESEARCH`` / ``MARKET_SNAPSHOT`` cover the non-deterministic
      surfaces (Quicktiny, RssCast research feeds, etc.) that must
      never be persisted as ``core.daily_bars`` per the plan §3 and
      matrix §5.4.

    The catalog **must not** omit these enum members while
    RssCast / Quicktiny stay research-only: a missing enum value
    would make the negative-capability assertions impossible to
    express.
    """

    RESEARCH = "research"
    MARKET_SNAPSHOT = "market_snapshot"
    ETF_DAILY_BARS = "etf_daily_bars"
    ETF_MASTER_DATA = "etf_master_data"
    INDEX_DAILY_BARS = "index_daily_bars"


@dataclass(frozen=True, slots=True)
class ProviderDeclaration:
    """A single provider declaration row.

    Attributes
    ----------
    provider_key:
        Stable, lower_snake_case provider identifier (for example
        ``"quicktiny_mcp"``). Persisted in ``raw.provider_batches``.
    role:
        Role the provider plays in the V2 pipeline. Drives runtime
        selection (out of scope for this increment).
    capabilities:
        Immutable tuple of capabilities the provider advertises. The
        tuple is empty-safe and ordered for deterministic output.
    enabled_by_default:
        Whether the provider is enabled by default. Real providers in
        V2 default to ``False`` per the migration matrix §6; only
        ``fixture_dev`` defaults to ``True``.
    """

    provider_key: str
    role: ProviderRole
    capabilities: tuple[ProviderCapability, ...]
    enabled_by_default: bool


QUICKTINY_MCP = ProviderDeclaration(
    provider_key="quicktiny_mcp",
    role=ProviderRole.RESEARCH_ONLY,
    capabilities=(
        ProviderCapability.RESEARCH,
        ProviderCapability.MARKET_SNAPSHOT,
    ),
    enabled_by_default=False,
)
"""Quicktiny MCP provider declaration (research_only).

The role and capability set mirror ``DATA-SOURCE-MIGRATION-MATRIX.md``
§3 and the plan PR-01 "research / market_snapshot only" constraint.
Quicktiny is research_only and is explicitly **not** an ETF
master-data, ETF daily-bars or index daily-bars provider. The
provider is disabled by default per matrix §6.
"""


FIXTURE_DEV = ProviderDeclaration(
    provider_key="fixture_dev",
    role=ProviderRole.FIXTURE_DEV,
    capabilities=(
        ProviderCapability.ETF_DAILY_BARS,
        ProviderCapability.ETF_MASTER_DATA,
    ),
    enabled_by_default=True,
)
"""``fixture_dev`` provider declaration.

The deterministic in-repo ETF provider that backs ``apps/pipeline/src/
invest_pipeline/adapters/fixture_dev``. Matrix §3 pins the role to
``fixture_dev`` and matrix §6 keeps the default on because no real
network call is ever issued. The capability set covers exactly the
two surfaces the on-disk fixtures (``etf_instruments.json`` /
``etf_daily_bars.json``) feed.
"""


CIFANGQUANT = ProviderDeclaration(
    provider_key="cifangquant",
    role=ProviderRole.SECONDARY,
    capabilities=(
        ProviderCapability.ETF_DAILY_BARS,
        ProviderCapability.ETF_MASTER_DATA,
        ProviderCapability.INDEX_DAILY_BARS,
    ),
    enabled_by_default=False,
)
"""CifangQuant provider declaration.

Matrix §3 pins the role to ``secondary`` (only after O-1) and matrix §6
keeps it disabled by default. The capability set reflects matrix §2:
``ETF_MASTER_DATA`` and ``ETF_DAILY_BARS`` are direct
``/api/fund/list`` / ``/api/fund/hist_em`` capabilities;
``INDEX_DAILY_BARS`` is the indirect capability matrix §2 observed
(``"间接（与 ETF 数据共用接口，已观察到）"``) so the routing layer
sees the full surface. The runtime factory already constructs this
provider behind the ``CifangSettings.enabled`` gate; the catalog
merely declares it for matrix-aligned discovery.
"""


AKSHARE = ProviderDeclaration(
    provider_key="akshare",
    role=ProviderRole.RESEARCH_ONLY,
    capabilities=(
        ProviderCapability.ETF_DAILY_BARS,
        ProviderCapability.ETF_MASTER_DATA,
        ProviderCapability.INDEX_DAILY_BARS,
    ),
    enabled_by_default=False,
)
"""AkShare provider declaration.

Matrix §3 pins the role to ``research_only`` (the safer default until
O-1 upgrades the recommendation to ``secondary``). Matrix §5.4
forbids it from being treated as a production SLA source, so the
``enabled_by_default`` flag stays off regardless of the capability
set. The three capabilities mirror matrix §2: ETF master data
(``fund_etf_fund_info_em`` family), ETF daily bars
(``fund_etf_hist_em``) and the indirect index daily bars
(``stock_zh_index_daily`` / aggregator library).
"""


RSSCAST = ProviderDeclaration(
    provider_key="rsscast",
    role=ProviderRole.OUT_OF_SCOPE_FOR_ETF,
    capabilities=(
        ProviderCapability.INDEX_DAILY_BARS,
        ProviderCapability.RESEARCH,
    ),
    enabled_by_default=False,
)
"""RssCast provider declaration.

Matrix §3 pins the role to ``out_of_scope_for_etf`` and matrix §5.4
plus the plan PR-01 "do not claim ETF daily bars for RssCast"
constraint forbid the provider from advertising ``ETF_DAILY_BARS`` (or
any ETF master-data capability). The capability set is the
"research / index only" pair the plan calls out: ``INDEX_DAILY_BARS``
(matrix §2 direct capability) plus ``RESEARCH`` (matrix §2 "仅行情片段"
research surface). The provider stays disabled by default per matrix
§6.
"""


_PROVIDER_CATALOG: dict[str, ProviderDeclaration] = {
    AKSHARE.provider_key: AKSHARE,
    CIFANGQUANT.provider_key: CIFANGQUANT,
    FIXTURE_DEV.provider_key: FIXTURE_DEV,
    QUICKTINY_MCP.provider_key: QUICKTINY_MCP,
    RSSCAST.provider_key: RSSCAST,
}

_ALL_DECLARATIONS: tuple[ProviderDeclaration, ...] = (
    AKSHARE,
    CIFANGQUANT,
    FIXTURE_DEV,
    QUICKTINY_MCP,
    RSSCAST,
)

_ALL_PROVIDER_KEYS: tuple[str, ...] = tuple(
    declaration.provider_key for declaration in _ALL_DECLARATIONS
)


def lookup_provider(provider_key: str) -> ProviderDeclaration:
    """Return the declaration registered under ``provider_key``.

    Parameters
    ----------
    provider_key:
        The provider identifier to look up.

    Raises
    ------
    KeyError
        If no provider is registered under ``provider_key``. The raised
        ``KeyError`` carries the requested key as its argument so
        callers (and tests) can assert on it directly.
    """
    try:
        return _PROVIDER_CATALOG[provider_key]
    except KeyError as exc:
        raise KeyError(provider_key) from exc


def iter_provider_declarations() -> tuple[ProviderDeclaration, ...]:
    """Return every registered provider declaration in a stable order.

    The tuple is in alphabetical ``provider_key`` order so tests and
    documentation tables can iterate the catalog without depending on
    ``dict`` insertion order. Returns a fresh tuple each call so
    callers cannot accidentally mutate the catalog's internal state.
    """

    return _PROVIDER_CATALOG_SORTED


_PROVIDER_CATALOG_SORTED: tuple[ProviderDeclaration, ...] = tuple(
    sorted(_ALL_DECLARATIONS, key=lambda declaration: declaration.provider_key)
)


__all__ = [
    "AKSHARE",
    "CIFANGQUANT",
    "FIXTURE_DEV",
    "ProviderCapability",
    "ProviderDeclaration",
    "ProviderRole",
    "QUICKTINY_MCP",
    "RSSCAST",
    "iter_provider_declarations",
    "lookup_provider",
]
