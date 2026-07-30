from __future__ import annotations

from invest_pipeline.providers.akshare.adapter import (
    AKSHARE_DECLARATION,
    AkshareEtfMarketDataProvider,
)
from invest_pipeline.providers.capabilities import (
    ADJUSTMENT_NONE,
    PROVIDER_KEY_AKSHARE,
    PROVIDER_KEY_CIFANG,
    PROVIDER_KEY_FIXTURE_DEV,
    PROVIDER_KEY_QUICKTINY_MCP,
    PROVIDER_KEY_RSSCAST,
    ProviderCapability,
    ProviderDeclaration,
    ProviderRole,
    is_adjustment_allowed,
)
from invest_pipeline.providers.cifang.adapter import (
    CIFANG_DECLARATION,
    CifangEtfMarketDataProvider,
)
from invest_pipeline.providers.errors import (
    InvalidProviderCapabilityError,
    ProviderAdapterNotImplementedError,
    ProviderAuthenticationError,
    ProviderBadResponseError,
    ProviderDataContractError,
    ProviderError,
    ProviderPermanentError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RealProviderRequiresExplicitEnablementError,
    UnknownProviderError,
)
from invest_pipeline.providers.factory import (
    ProviderSettings,
    build_provider_from_settings,
    default_provider_settings,
)
from invest_pipeline.providers.fixture_dev import (
    FIXTURE_DEV_PROVIDER_KEY,
    FixtureDevEtfMarketDataProvider,
    FixtureDevInstrumentProvider,
)
from invest_pipeline.providers.quicktiny_mcp.declaration import QUICKTINY_MCP_DECLARATION
from invest_pipeline.providers.registry import (
    DEFAULT_PROVIDER_REGISTRY,
    ProviderRegistry,
)
from invest_pipeline.providers.rsscast.declaration import RSSCAST_DECLARATION

__all__ = [
    "ADJUSTMENT_NONE",
    "AKSHARE_DECLARATION",
    "CIFANG_DECLARATION",
    "DEFAULT_PROVIDER_REGISTRY",
    "FIXTURE_DEV_PROVIDER_KEY",
    "FixtureDevEtfMarketDataProvider",
    "FixtureDevInstrumentProvider",
    "InvalidProviderCapabilityError",
    "PROVIDER_KEY_AKSHARE",
    "PROVIDER_KEY_CIFANG",
    "PROVIDER_KEY_FIXTURE_DEV",
    "PROVIDER_KEY_QUICKTINY_MCP",
    "PROVIDER_KEY_RSSCAST",
    "QUICKTINY_MCP_DECLARATION",
    "RSSCAST_DECLARATION",
    "AkshareEtfMarketDataProvider",
    "CifangEtfMarketDataProvider",
    "ProviderAdapterNotImplementedError",
    "ProviderAuthenticationError",
    "ProviderBadResponseError",
    "ProviderCapability",
    "ProviderDataContractError",
    "ProviderDeclaration",
    "ProviderError",
    "ProviderPermanentError",
    "ProviderRateLimitError",
    "ProviderRole",
    "ProviderSettings",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "ProviderRegistry",
    "RealProviderRequiresExplicitEnablementError",
    "UnknownProviderError",
    "build_provider_from_settings",
    "default_provider_settings",
    "is_adjustment_allowed",
]
