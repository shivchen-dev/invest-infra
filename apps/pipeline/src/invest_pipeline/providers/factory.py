from __future__ import annotations

from invest_pipeline.providers.akshare.adapter import AkshareEtfMarketDataProvider
from invest_pipeline.providers.capabilities import (
    PROVIDER_KEY_AKSHARE,
    PROVIDER_KEY_CIFANG,
    PROVIDER_KEY_FIXTURE_DEV,
    PROVIDER_KEY_QUICKTINY_MCP,
    PROVIDER_KEY_RSSCAST,
)
from invest_pipeline.providers.cifang.adapter import CifangEtfMarketDataProvider
from invest_pipeline.providers.errors import UnknownProviderError
from invest_pipeline.providers.fixture_dev import FixtureDevEtfMarketDataProvider
from invest_pipeline.providers.settings import ProviderSettings, default_provider_settings


def build_provider_from_settings(
    settings: ProviderSettings,
    *,
    provider_key: str | None = None,
    registry: object | None = None,
):
    """Resolve an adapter from settings.

    Defaults to ``settings.provider_key``. Real network sources are
    refused unless their ``enabled`` flag is set; see
    ``ProviderRegistry.build``.

    The optional ``registry`` argument exists primarily for testing; the
    default registry imports no third-party SDKs.
    """

    resolved_key = provider_key or settings.provider_key
    if resolved_key == PROVIDER_KEY_FIXTURE_DEV:
        return FixtureDevEtfMarketDataProvider()
    if resolved_key == PROVIDER_KEY_AKSHARE:
        if not settings.akshare.enabled:
            from invest_pipeline.providers.errors import (
                RealProviderRequiresExplicitEnablementError,
            )

            raise RealProviderRequiresExplicitEnablementError(
                "akshare is disabled by default; flip INVEST_PIPELINE_AKSHARE_ENABLED=true "
                "after O-1 (Provider selection) is confirmed."
            )
        return AkshareEtfMarketDataProvider(
            token=settings.akshare.token,
            base_url=settings.akshare.base_url,
            timeout_seconds=settings.akshare.timeout_seconds,
        )
    if resolved_key == PROVIDER_KEY_CIFANG:
        if not settings.cifang.enabled:
            from invest_pipeline.providers.errors import (
                RealProviderRequiresExplicitEnablementError,
            )

            raise RealProviderRequiresExplicitEnablementError(
                "cifang is disabled by default; flip INVEST_PIPELINE_CIFANG_ENABLED=true "
                "after O-1 (Provider selection) is confirmed."
            )
        return CifangEtfMarketDataProvider(
            token=settings.cifang.token,
            base_url=settings.cifang.base_url,
            adjustment=settings.cifang.adjustment,
            timeout_seconds=settings.cifang.timeout_seconds,
        )
    if resolved_key == PROVIDER_KEY_RSSCAST:
        from invest_pipeline.providers.errors import (
            ProviderAdapterNotImplementedError,
        )

        raise ProviderAdapterNotImplementedError(
            PROVIDER_KEY_RSSCAST,
            "RssCast is research-only and not implemented as a v2 ETF Provider; "
            "no stock/index production asset will be wired in M0.",
        )
    if resolved_key == PROVIDER_KEY_QUICKTINY_MCP:
        from invest_pipeline.providers.errors import (
            ProviderAdapterNotImplementedError,
        )

        raise ProviderAdapterNotImplementedError(
            PROVIDER_KEY_QUICKTINY_MCP,
            "quicktiny_mcp is research-only and not implemented as a v2 ETF Provider.",
        )
    raise UnknownProviderError(resolved_key)
