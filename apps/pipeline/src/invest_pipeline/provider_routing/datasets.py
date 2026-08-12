"""Dataset registry for the V2 provider routing layer (PR-05).

The :class:`Dataset` enum freezes the dataset keys the V2 routing
layer distinguishes. The string values mirror the ``dataset_key`` the
rest of the pipeline writes to ``raw.provider_requests`` and
``raw.provider_batches`` (see :mod:`invest_pipeline.adapters.cifang`
and :mod:`invest_pipeline.adapters.fixture_dev.adapter`) so the
routing decision can be joined with the raw evidence tables without
translation:

```text
"etf_daily_bars"             -> ETF_DAILY_BARS
"etf_instruments"            -> ETF_MASTER_DATA
"index_daily_bars"           -> INDEX_DAILY_BARS
"research"                   -> RESEARCH
"market_snapshot"            -> MARKET_SNAPSHOT
"stock_minute_bars"          -> STOCK_MINUTE_BARS
"stock_block_memberships"    -> STOCK_BLOCK_MEMBERSHIPS
"stock_price_limits"         -> STOCK_PRICE_LIMITS
"tdx_gui_analysis_results"   -> TDX_GUI_ANALYSIS
```

The :data:`DATASET_CAPABILITIES` mapping is the canonical capability
contract: each dataset names the
:class:`invest_pipeline.provider_catalog.ProviderCapability` a
provider must advertise to be eligible for it. The mapping is the
single source of truth for the routing layer; both
:func:`select_providers` and the tests consult it directly so a future
addition (for example an ``intraday_bars`` dataset) cannot drift
between the catalog and the routing layer.

The dataset keys are deliberately stable strings — they are persisted
in ``raw.provider_requests`` and must not change without a migration.

Stage 4C Phase 0 Task 0.1
(``tasks/stage4c-core-data-layer-integration-plan.md``) freezes the
four additional dataset keys the new core data layer introduces
(``stock_minute_bars`` / ``stock_block_memberships`` /
``stock_price_limits`` / ``tdx_gui_analysis_results``) but does
**not** wire any runtime provider for them: matching provider
declarations land in later Stage 4C phases, so a routing call
against these new datasets currently raises
:class:`NoEligibleProviderError`. The dataset enum and capability
mapping are nevertheless frozen now to keep the persisted
``dataset_key`` strings stable.
"""

from __future__ import annotations

from enum import StrEnum

from invest_pipeline.provider_catalog import ProviderCapability


class Dataset(StrEnum):
    """Frozen dataset identifiers used by the V2 provider routing layer.

    The string values are persisted in ``raw.provider_requests.dataset_key``
    and ``raw.provider_batches.dataset_key`` and must not change without
    a migration. The values match the catalogue of surfaces the
    V2 plan §3 / PR-05 cares about:

    * ``ETF_DAILY_BARS`` — ETF standardised OHLCV feed (matrix §2
      direct capability).
    * ``ETF_INSTRUMENTS`` — ETF master data feed (``etf_instruments``
      dataset the rest of the pipeline writes). Despite the dataset
      string the required capability is ``ETF_MASTER_DATA``; the
      mismatch mirrors the historical ``etf_instruments`` key and
      keeps PR-05 backwards compatible with the rows the previous
      PRs have already persisted.
    * ``INDEX_DAILY_BARS`` — index daily-bars surface (matrix §2
      indirect capability for the ETF-side sources).
    * ``RESEARCH`` — non-deterministic research responses (RssCast,
      Quicktiny, etc.) that must never be persisted as
      ``core.daily_bars`` per plan §3 and matrix §5.4.
    * ``MARKET_SNAPSHOT`` — market snapshot / ranking surface
      (Quicktiny's MCP ``etf_market`` / ``index_market``). Also
      non-deterministic; the routing layer surfaces it for
      completeness but the coverage calculator never persists it as
      a daily-bars row.
    * ``STOCK_MINUTE_BARS`` — A-share 1/5-minute OHLCV feed (Stage
      4C Phase 3). Required capability is
      ``STOCK_MINUTE_BARS``; no provider declares it yet.
    * ``STOCK_BLOCK_MEMBERSHIPS`` — block / sector / industry /
      concept membership snapshot (Stage 4C Phase 2). Required
      capability is ``STOCK_BLOCK_MEMBERSHIPS``; no provider
      declares it yet.
    * ``STOCK_PRICE_LIMITS`` — daily price-limit rules per
      regulation regime (Stage 4C Phase 1.2). Required capability
      is ``STOCK_PRICE_LIMITS``; no provider declares it yet.
    * ``TDX_GUI_ANALYSIS_RESULTS`` — TDX GUI export results
      (Stage 4C Phase 4, ``tdx_gui_analysis`` independent provider
      slice). Required capability is ``TDX_GUI_ANALYSIS``; no
      provider declares it yet.
    """

    ETF_DAILY_BARS = "etf_daily_bars"
    ETF_INSTRUMENTS = "etf_instruments"
    INDEX_DAILY_BARS = "index_daily_bars"
    RESEARCH = "research"
    MARKET_SNAPSHOT = "market_snapshot"
    STOCK_MINUTE_BARS = "stock_minute_bars"
    STOCK_BLOCK_MEMBERSHIPS = "stock_block_memberships"
    STOCK_PRICE_LIMITS = "stock_price_limits"
    TDX_GUI_ANALYSIS_RESULTS = "tdx_gui_analysis_results"


DATASET_CAPABILITIES: dict[Dataset, ProviderCapability] = {
    Dataset.ETF_DAILY_BARS: ProviderCapability.ETF_DAILY_BARS,
    Dataset.ETF_INSTRUMENTS: ProviderCapability.ETF_MASTER_DATA,
    Dataset.INDEX_DAILY_BARS: ProviderCapability.INDEX_DAILY_BARS,
    Dataset.RESEARCH: ProviderCapability.RESEARCH,
    Dataset.MARKET_SNAPSHOT: ProviderCapability.MARKET_SNAPSHOT,
    Dataset.STOCK_MINUTE_BARS: ProviderCapability.STOCK_MINUTE_BARS,
    Dataset.STOCK_BLOCK_MEMBERSHIPS: ProviderCapability.STOCK_BLOCK_MEMBERSHIPS,
    Dataset.STOCK_PRICE_LIMITS: ProviderCapability.STOCK_PRICE_LIMITS,
    Dataset.TDX_GUI_ANALYSIS_RESULTS: ProviderCapability.TDX_GUI_ANALYSIS,
}
"""Capability required to serve each dataset.

The mapping is the single source of truth for the routing layer. It
is exported (rather than inlined into :func:`select_providers`) so
the tests and the coverage calculator can introspect the contract
without re-declaring the literals. The four Stage 4C Phase 0
entries (the stock minute / block / price-limit / GUI rows) each
map 1:1 onto a same-named :class:`ProviderCapability` member so
the contract is symmetric: the persisted ``dataset_key`` and the
required capability carry the same snake_case stem.
"""


_REQUIRED_CAPABILITIES_FROZEN: tuple[tuple[Dataset, ProviderCapability], ...] = tuple(
    sorted(DATASET_CAPABILITIES.items(), key=lambda item: item[0].value)
)


def required_capability_for(dataset: Dataset) -> ProviderCapability:
    """Return the :class:`ProviderCapability` required to serve ``dataset``.

    The helper is a thin wrapper around
    :data:`DATASET_CAPABILITIES` that makes the routing layer's intent
    explicit at call sites and gives a single, type-checked entry
    point the tests can mock if a future PR introduces an alternate
    routing policy.
    """

    if not isinstance(dataset, Dataset):
        raise ValueError(
            f"required_capability_for requires a Dataset instance, "
            f"got {type(dataset).__name__}"
        )
    return DATASET_CAPABILITIES[dataset]


def dataset_requires_capability(
    dataset: Dataset, capability: ProviderCapability
) -> bool:
    """Return ``True`` iff serving ``dataset`` requires ``capability``.

    Convenience wrapper used by the tests; the routing layer itself
    consults :data:`DATASET_CAPABILITIES` directly.
    """

    return required_capability_for(dataset) is capability


__all__ = [
    "DATASET_CAPABILITIES",
    "Dataset",
    "dataset_requires_capability",
    "required_capability_for",
]
