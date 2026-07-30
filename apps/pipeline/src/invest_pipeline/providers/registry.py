from __future__ import annotations

from collections.abc import Callable

from invest_pipeline.providers.akshare.adapter import (
    AKSHARE_DECLARATION,
    AkshareEtfMarketDataProvider,
)
from invest_pipeline.providers.capabilities import (
    PROVIDER_KEY_QUICKTINY_MCP,
    PROVIDER_KEY_RSSCAST,
    ProviderCapability,
    ProviderDeclaration,
)
from invest_pipeline.providers.cifang.adapter import (
    CIFANG_DECLARATION,
    CifangEtfMarketDataProvider,
)
from invest_pipeline.providers.errors import (
    InvalidProviderCapabilityError,
    ProviderAdapterNotImplementedError,
    RealProviderRequiresExplicitEnablementError,
    UnknownProviderError,
)
from invest_pipeline.providers.fixture_dev import FixtureDevEtfMarketDataProvider
from invest_pipeline.providers.quicktiny_mcp.declaration import QUICKTINY_MCP_DECLARATION
from invest_pipeline.providers.rsscast.declaration import RSSCAST_DECLARATION

ProviderFactory = Callable[..., object]


class ProviderRegistry:
    """In-memory registry mapping provider keys to declarations and factories.

    Declarations exist for every supported Provider key, including real
    (network-bound) ones that are gated behind explicit enablement. Factories
    only run for the key we look up; real-Provider factories refuse to run
    unless the caller has flipped the enabled flag.

    Construction never imports third-party SDKs: placeholders are
    fully implemented in this package so the registry can be exercised in
    test and CI environments without network access.
    """

    def __init__(self) -> None:
        self._declarations: dict[str, ProviderDeclaration] = {}
        self._factories: dict[str, ProviderFactory] = {}
        self._is_real: dict[str, bool] = {}

    def register(
        self,
        declaration: ProviderDeclaration,
        factory: ProviderFactory,
        *,
        is_real: bool,
    ) -> None:
        if declaration.provider_key in self._declarations:
            raise ValueError(f"Provider key {declaration.provider_key!r} already registered")
        if not declaration.capabilities:
            raise ValueError(
                f"Provider {declaration.provider_key!r} must declare at least one capability"
            )
        self._declarations[declaration.provider_key] = declaration
        self._factories[declaration.provider_key] = factory
        self._is_real[declaration.provider_key] = is_real

    def declaration(self, provider_key: str) -> ProviderDeclaration:
        try:
            return self._declarations[provider_key]
        except KeyError as exc:
            raise UnknownProviderError(provider_key) from exc

    def try_declaration(self, provider_key: str) -> ProviderDeclaration | None:
        return self._declarations.get(provider_key)

    def has(self, provider_key: str) -> bool:
        return provider_key in self._declarations

    def keys(self) -> list[str]:
        return sorted(self._declarations)

    def capabilities_for(self, provider_key: str) -> frozenset[ProviderCapability]:
        return self.declaration(provider_key).capabilities

    def build(self, provider_key: str, *, enabled: bool | None = None, **kwargs: object) -> object:
        if provider_key not in self._factories:
            raise UnknownProviderError(provider_key)
        if self._is_real.get(provider_key, False):
            if not enabled:
                raise RealProviderRequiresExplicitEnablementError(
                    f"Provider {provider_key!r} is a real data source and is disabled by default. "
                    "Set the matching INVEST_PIPELINE_*_ENABLED setting to true before requesting a build."
                )
        factory = self._factories[provider_key]
        return factory(**kwargs)

    def has_capability(self, provider_key: str, capability: ProviderCapability) -> bool:
        try:
            declaration = self.declaration(provider_key)
        except UnknownProviderError:
            return False
        return capability in declaration.capabilities

    def require_capability(
        self, provider_key: str, capability: ProviderCapability
    ) -> ProviderDeclaration:
        declaration = self.declaration(provider_key)
        if capability not in declaration.capabilities:
            raise InvalidProviderCapabilityError(
                f"Provider {provider_key!r} does not declare capability {capability!r}; "
                f"declared={sorted(cap.value for cap in declaration.capabilities)}"
            )
        return declaration


def _raise_not_implemented(provider_key: str, *, capability: ProviderCapability) -> None:
    raise ProviderAdapterNotImplementedError(
        provider_key,
        f"Adapter for {provider_key!r} capability {capability.value!r} is a placeholder; "
        "real network/SDK calls are blocked until O-1 (Provider selection) is confirmed "
        "per ADR-0003.",
    )


def _akshare_factory(**kwargs: object) -> object:
    if set(kwargs) - {"token", "base_url", "timeout_seconds"}:
        raise TypeError(
            "Akshare factory only accepts token/base_url/timeout_seconds kwargs"
        )
    return AkshareEtfMarketDataProvider(
        token=str(kwargs.get("token", "")),
        base_url=str(kwargs.get("base_url", "https://example.invalid/akshare")),
        timeout_seconds=float(kwargs.get("timeout_seconds", 10.0)),
    )


def _cifang_factory(**kwargs: object) -> object:
    if set(kwargs) - {"token", "base_url", "adjustment", "timeout_seconds"}:
        raise TypeError(
            "Cifang factory only accepts token/base_url/adjustment/timeout_seconds kwargs"
        )
    return CifangEtfMarketDataProvider(
        token=str(kwargs.get("token", "")),
        base_url=str(kwargs.get("base_url", "https://www.cifangquant.com/api")),
        adjustment=str(kwargs.get("adjustment", "none")),
        timeout_seconds=float(kwargs.get("timeout_seconds", 10.0)),
    )


def _fixture_dev_factory(**kwargs: object) -> object:
    if kwargs:
        raise TypeError(f"fixture_dev factory ignores kwargs: {sorted(kwargs)}")
    return FixtureDevEtfMarketDataProvider()


def _real_only_block(provider_key: str) -> object:
    raise ProviderAdapterNotImplementedError(
        provider_key,
        f"{provider_key} is a research-only / out-of-scope Provider per "
        "DATA-SOURCE-MIGRATION-MATRIX; v2 does not ship an adapter implementation.",
    )


def build_default_provider_registry() -> ProviderRegistry:
    """Construct the canonical registry used in test/dev and by ADR-0003.

    The registry intentionally contains every supported Provider key, even
    ones that are research-only and have no adapter implementation. This
    keeps the audit surface complete and makes it impossible to silently
    introduce a new Provider key without updating both the registry and
    the migration matrix.
    """

    registry = ProviderRegistry()
    registry.register(
        FixtureDevEtfMarketDataProvider.declaration,
        _fixture_dev_factory,
        is_real=False,
    )
    registry.register(AKSHARE_DECLARATION, _akshare_factory, is_real=True)
    registry.register(CIFANG_DECLARATION, _cifang_factory, is_real=True)
    registry.register(
        RSSCAST_DECLARATION,
        lambda **_kwargs: _real_only_block(PROVIDER_KEY_RSSCAST),
        is_real=True,
    )
    registry.register(
        QUICKTINY_MCP_DECLARATION,
        lambda **_kwargs: _real_only_block(PROVIDER_KEY_QUICKTINY_MCP),
        is_real=True,
    )
    return registry


DEFAULT_PROVIDER_REGISTRY: ProviderRegistry = build_default_provider_registry()
