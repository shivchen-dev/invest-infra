from __future__ import annotations


class ProviderError(Exception):
    """Base class for all Provider-related failures.

    ADR-0003 §4 keeps errors classified so application services and Dagster
    assets can drive retry, alerting, and rejection policies. Subclasses below
    mirror the categories listed in plan §4.4.
    """

    def __init__(self, provider_key: str, message: str) -> None:
        super().__init__(message)
        self.provider_key = provider_key


class ProviderAuthenticationError(ProviderError):
    """Credentials missing or rejected. Do not auto-retry; alert immediately."""


class ProviderRateLimitError(ProviderError):
    """Provider signaled 429 / quota exhaustion. Honor Retry-After when present."""


class ProviderTimeoutError(ProviderError):
    """Network timeout or reset. Safe to retry with exponential backoff."""


class ProviderUnavailableError(ProviderError):
    """5xx or service-unavailable signal. Safe to retry with a cap."""


class ProviderBadResponseError(ProviderError):
    """Response payload violates the contract so far that it cannot be parsed."""


class ProviderDataContractError(ProviderError):
    """Required fields missing or invalid; the batch must be rejected.

    Carries a machine-readable ``code`` plus a human-readable ``message``
    so the application layer can route alerts without re-parsing free
    text. The signature mirrors the domain
    :exc:`invest_domain.market_data.ports.ProviderDataContractError` so
    adapter and domain layers share the same canonical contract.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        provider_key: str | None = None,
    ) -> None:
        combined = f"[{code}] {message}" if code else message
        super().__init__(provider_key or "cifangquant", combined)
        self.code = code
        self.message = message


class ProviderPermanentError(ProviderError):
    """Explicit permanent failure (e.g. instrument permanently delisted)."""


class ProviderAdapterNotImplementedError(ProviderError):
    """Adapter placeholder explicitly signals a capability is not implemented yet.

    ADR-0003 keeps Provider selection unfrozen until O-1 is confirmed. Placeholder
    adapters raise this category rather than fabricate behavior.
    """


class UnknownProviderError(KeyError):
    """Lookup against the registry failed; surfaces a stable error contract."""


class InvalidProviderCapabilityError(ValueError):
    """Capability mismatch (e.g. declared missing the ETF capability it was asked for)."""


class RealProviderRequiresExplicitEnablementError(RuntimeError):
    """Real (non-fixture) provider was requested while its settings.enabled flag is False.

    Defaults exist so we never silently hit a third-party API in CI / tests / dev.
    """