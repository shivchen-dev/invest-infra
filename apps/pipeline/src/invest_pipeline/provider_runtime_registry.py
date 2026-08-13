"""Minimal runtime boundary for catalog-declared providers.

The registry resolves an explicitly requested provider only.  It does not
perform fallback, routing, persistence, event handling, or session lifetime
management; those concerns remain with their existing owners.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from invest_domain.market_data.ports import EtfMarketDataProvider

from invest_pipeline.adapters.akshare import AkshareSettings
from invest_pipeline.adapters.cifang import CifangSettings
from invest_pipeline.adapters.tushare import StockTushareProvider, TushareSettings
from invest_pipeline.config import Settings
from invest_pipeline.provider_catalog import (
    ProviderDeclaration,
    lookup_provider,
)
from invest_pipeline.provider_factory import build_provider, build_stock_provider


@dataclass(frozen=True, slots=True)
class ResolvedProvider:
    """The declaration and runtime adapter for one explicit provider choice."""

    provider_key: str
    declaration: ProviderDeclaration
    provider: EtfMarketDataProvider | StockTushareProvider


class ProviderRuntimeRegistry:
    """Resolve explicitly requested ETF and Tushare stock providers."""

    def resolve_etf(
        self,
        settings: Settings,
        *,
        cifang_settings: CifangSettings | None = None,
        akshare_settings: AkshareSettings | None = None,
        tushare_settings: TushareSettings | None = None,
    ) -> ResolvedProvider:
        """Resolve one ETF provider, preserving the factory's failure modes."""

        declaration = lookup_provider(settings.provider_key)
        provider = build_provider(
            settings,
            cifang_settings=cifang_settings,
            akshare_settings=akshare_settings,
            tushare_settings=tushare_settings,
        )
        return ResolvedProvider(settings.provider_key, declaration, provider)

    def resolve_stock(
        self,
        settings: Settings,
        *,
        tushare_settings: TushareSettings | None = None,
    ) -> ResolvedProvider:
        """Resolve the Tushare stock provider; TDX remains catalog-only."""

        declaration = lookup_provider(settings.provider_key)
        provider = cast(
            StockTushareProvider,
            build_stock_provider(settings, tushare_settings=tushare_settings),
        )
        return ResolvedProvider(settings.provider_key, declaration, provider)

    def describe(self, provider_key: str) -> ProviderDeclaration:
        """Return the catalog declaration for ``provider_key``."""

        return lookup_provider(provider_key)


__all__ = ["ProviderRuntimeRegistry", "ResolvedProvider"]
