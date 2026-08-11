"""Provider catalog declarations for the V2 pipeline (stdlib only).

This module is a **declaration catalog**, not an adapter implementation.
It records the ``provider_key``, ``role``, ``capabilities`` and
``enabled_by_default`` flag of every provider the V2 codebase references
by name. PR-01 (see
``docs/plan/invest-infra-v2-all-data-sources-integration-plan.md``)
freezes the original catalog; this slice adds the opt-in Tushare ETF
source. The historical V2
three-provider plan (see ``tasks/plan-data-source-three-provider.md``)
proposed three additional aggregator sources (``eastmoney``,
``sina``, ``tonghuashun``) but has been **de-scoped** in this slice:
the three sources are not selectable runtime providers in V2 and the
catalog carries no declaration for them. Their public historical-quotes
endpoints remain internal upstreams of the AkShare aggregator
(``fund_etf_hist_sina`` / ``fund_etf_hist_em``); the catalog surface
is therefore:

```text
fixture_dev   cifangquant   akshare   tushare   rsscast   quicktiny_mcp   hithink   tdx_offline
```

The module is intentionally small:

* No HTTP, MCP or SDK transport is imported.
* No API key, token or credential handling is wired in.
* No runtime provider selection, factory or registry is implemented in
  this module. The runtime factory
  (:mod:`invest_pipeline.provider_factory`) owns construction and
  consumes the catalog's declaration of the *runtime* provider surface.
  The catalog records that surface via the :attr:`ProviderDeclaration.has_runtime_factory_adapter`
  flag, and the factory derives
  :data:`invest_pipeline.provider_factory.KNOWN_PROVIDER_KEYS` from
  :func:`runtime_supported_provider_keys` so the two modules cannot
  drift (GOV-04).
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
  default stays off. ``tushare`` is an opt-in secondary ETF source;
  its token is read lazily from the operator-managed token file and
  its ``adjust`` mode is fixed to ``none``.
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
* The historical V2 three-provider plan
  (``tasks/plan-data-source-three-provider.md``) once proposed
  ``eastmoney`` / ``sina`` / ``tonghuashun`` as cross-validation /
  historical-quotes sources. That plan has been de-scoped in this
  slice: the three sources are **not** selectable runtime providers
  in V2 and the catalog carries no declaration for them. Their
  public historical-quotes endpoints remain internal upstreams of
  the AkShare aggregator (``ak.fund_etf_hist_sina`` /
  ``ak.fund_etf_hist_em``) and surface only as ``source_key``
  values on :class:`BarSource` rows produced by the AkShare
  adapter. A future ADR may revisit the plan, but the current
  catalog intentionally stops at the six runtime providers.

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
    STOCK_DAILY_BARS = "stock_daily_bars"
    STOCK_MASTER_DATA = "stock_master_data"
    STOCK_FINANCIALS = "stock_financials"
    STOCK_VALUATIONS = "stock_valuations"


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
    has_runtime_factory_adapter:
        Whether the catalog declares a runtime factory adapter for
        this provider. Defaults to ``False`` so historical and
        third-party :class:`ProviderDeclaration` constructions that
        omit the field keep working unchanged. Only the four
        declarations backed by a real runtime factory
        (``fixture_dev`` / ``cifangquant`` / ``akshare`` / ``tushare``)
        set this to ``True``; MCP research sources and the
        historical three-provider plan entries stay ``False``.
        Exposed via :func:`runtime_supported_provider_declarations`
        and :func:`runtime_supported_provider_keys`, which the
        runtime factory (:mod:`invest_pipeline.provider_factory`)
        consults as the single source of truth for its supported
        key tuple.
    """

    provider_key: str
    role: ProviderRole
    capabilities: tuple[ProviderCapability, ...]
    enabled_by_default: bool
    has_runtime_factory_adapter: bool = False


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
    has_runtime_factory_adapter=True,
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
    has_runtime_factory_adapter=True,
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
    has_runtime_factory_adapter=True,
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

TUSHARE = ProviderDeclaration(
    provider_key="tushare",
    role=ProviderRole.SECONDARY,
    capabilities=(
        ProviderCapability.ETF_DAILY_BARS,
        ProviderCapability.ETF_MASTER_DATA,
        ProviderCapability.STOCK_DAILY_BARS,
        ProviderCapability.STOCK_MASTER_DATA,
    ),
    enabled_by_default=False,
    has_runtime_factory_adapter=True,
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


HITHINK = ProviderDeclaration(
    provider_key="hithink",
    role=ProviderRole.RESEARCH_ONLY,
    capabilities=(
        ProviderCapability.RESEARCH,
        ProviderCapability.MARKET_SNAPSHOT,
        ProviderCapability.STOCK_DAILY_BARS,
        ProviderCapability.STOCK_MASTER_DATA,
        ProviderCapability.STOCK_FINANCIALS,
        ProviderCapability.STOCK_VALUATIONS,
    ),
    enabled_by_default=False,
)
"""HiThink reserved provider declaration.

The HiThink source is registered as a catalog-only, disabled-by-default
entry per the ``tasks/hithink-reserved-provider-plan.md`` reserved
slice. The declaration advertises the six surfaces the upstream
HiThink contract exposes (``research`` / ``market_snapshot`` /
``stock_daily_bars`` / ``stock_master_data`` / ``stock_financials`` /
``stock_valuations``) but explicitly omits every ETF / index capability
and leaves ``has_runtime_factory_adapter=False`` so the runtime
factory's :data:`invest_pipeline.provider_factory.KNOWN_PROVIDER_KEYS`
helper excludes it. ``enabled_by_default=False`` is consistent with
matrix §6 and the "no production SLA path yet" reserved posture. The
credential is read lazily through the centralized
:func:`invest_pipeline.credentials.CredentialStore` against the
``hithink.api_key`` filename; no runtime factory branch or network
client is added in this slice.
"""


TDX_OFFLINE = ProviderDeclaration(
    provider_key="tdx_offline",
    role=ProviderRole.RESEARCH_ONLY,
    capabilities=(
        ProviderCapability.STOCK_DAILY_BARS,
    ),
    enabled_by_default=False,
)
"""TDX offline provider declaration (Stage 4B Phase 5, slice 1).

The TDX ``.day`` offline adapter is the catalog declaration for the
Tushare → TDX offline fallback path. The role is ``research_only``
because the offline reader is a deterministic, file-based backstop
that exists to keep the daily-bars evidence tuple auditable when the
Tushare primary source is unavailable — it is **not** a production
SLA source. The capability set is intentionally narrow: only
``STOCK_DAILY_BARS`` (the surface the upstream ``vipdoc/<market>/lday``
files cover). ETF / index / research / market-snapshot / financials /
valuations capabilities are explicitly omitted so the catalog cannot
silently widen the offline adapter's role.

``has_runtime_factory_adapter=False`` keeps the declaration
catalog-only for this slice: the slice ships the adapter, the
settings, and the catalog entry, but does **not** add a
:func:`invest_pipeline.provider_factory.build_stock_provider` branch
or wire the offline read into the ``stock_daily_bars_raw`` Dagster
asset. The runtime fallback orchestration is documented as a
follow-up that requires a symbol-enumeration contract the slice did
not invent.
"""


_PROVIDER_CATALOG: dict[str, ProviderDeclaration] = {
    AKSHARE.provider_key: AKSHARE,
    CIFANGQUANT.provider_key: CIFANGQUANT,
    FIXTURE_DEV.provider_key: FIXTURE_DEV,
    HITHINK.provider_key: HITHINK,
    QUICKTINY_MCP.provider_key: QUICKTINY_MCP,
    RSSCAST.provider_key: RSSCAST,
    TDX_OFFLINE.provider_key: TDX_OFFLINE,
    TUSHARE.provider_key: TUSHARE,
}

_ALL_DECLARATIONS: tuple[ProviderDeclaration, ...] = (
    AKSHARE,
    CIFANGQUANT,
    FIXTURE_DEV,
    HITHINK,
    QUICKTINY_MCP,
    RSSCAST,
    TDX_OFFLINE,
    TUSHARE,
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

_RUNTIME_SUPPORTED_DECLARATIONS: tuple[ProviderDeclaration, ...] = tuple(
    sorted(
        (
            declaration
            for declaration in _ALL_DECLARATIONS
            if declaration.has_runtime_factory_adapter
        ),
        key=lambda declaration: declaration.provider_key,
    )
)

_RUNTIME_SUPPORTED_KEYS: tuple[str, ...] = tuple(
    declaration.provider_key for declaration in _RUNTIME_SUPPORTED_DECLARATIONS
)


def runtime_supported_provider_declarations() -> tuple[ProviderDeclaration, ...]:
    """Return catalog declarations backed by a runtime factory adapter.

    The returned tuple is filtered by ``has_runtime_factory_adapter=True`` and
    sorted alphabetically by ``provider_key`` so the runtime factory
    (:mod:`invest_pipeline.provider_factory`) can derive its public
    ``KNOWN_PROVIDER_KEYS`` tuple from a single, stable source of
    truth. Catalog-only entries (``rsscast`` / ``quicktiny_mcp`` and
    any future non-runtime declarations) are excluded by design so a
    caller cannot accidentally treat a research-only MCP source as a
    selectable runtime provider.
    """

    return _RUNTIME_SUPPORTED_DECLARATIONS


def runtime_supported_provider_keys() -> tuple[str, ...]:
    """Return provider keys backed by a runtime factory adapter.

    The returned tuple mirrors
    :func:`runtime_supported_provider_declarations` and preserves the
    same alphabetical ordering so the two helpers can be cross-checked
    by tests. The runtime factory uses this helper to derive its
    ``KNOWN_PROVIDER_KEYS`` tuple; downstream callers (coverage
    reports, routing, etc.) can introspect the runtime-supported set
    without re-declaring the literals.
    """

    return _RUNTIME_SUPPORTED_KEYS


__all__ = [
    "AKSHARE",
    "CIFANGQUANT",
    "FIXTURE_DEV",
    "HITHINK",
    "ProviderCapability",
    "ProviderDeclaration",
    "ProviderRole",
    "QUICKTINY_MCP",
    "RSSCAST",
    "TDX_OFFLINE",
    "TUSHARE",
    "iter_provider_declarations",
    "lookup_provider",
    "runtime_supported_provider_declarations",
    "runtime_supported_provider_keys",
]
