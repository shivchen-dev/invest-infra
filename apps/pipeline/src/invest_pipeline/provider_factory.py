"""Runtime provider factory.

Selects an :class:`invest_domain.market_data.ports.EtfMarketDataProvider`
implementation from the pipeline-level ``INVEST_PIPELINE_PROVIDER_KEY``
setting and constructs it. The factory owns the runtime selection
surface; it has three branches and three explicit failure modes:

* ``fixture_dev`` -> :class:`FixtureDevInstrumentProvider`.
* ``cifangquant`` -> :class:`CifangQuantInstrumentProvider` constructed
  with a :class:`CifangSettings` object; construction is rejected with
  :class:`RealProviderRequiresExplicitEnablementError` when
  ``CifangSettings.enabled`` is ``False`` and with
  :class:`ProviderAuthenticationError` when ``CifangSettings.api_key``
  is empty. **No fallback to another provider is attempted** — the
  caller must resolve the gate before re-asking for the provider.
* ``akshare`` -> :class:`AkshareInstrumentProvider` constructed with a
  :class:`AkshareSettings` object; construction is rejected with
  :class:`RealProviderRequiresExplicitEnablementError` when
  ``AkshareSettings.enabled`` is ``False`` (matrix §6). When the
  ``akshare`` SDK is not installed, the inner :class:`AkshareClient`
  raises :class:`ProviderUnavailableError` from ``fetch_*`` calls;
  factory construction succeeds, but operators see the dependency
  error at fetch time, not at construction time.
* Anything else -> :class:`UnknownProviderError` carrying the offending
  key as the ``KeyError`` argument so callers (and operators reading
  logs) can identify the request without parsing the message string.

Construction never reaches out to the network: the fixture provider
loads its deterministic JSON from disk, the CifangQuant adapter only
constructs its httpx client (which itself is inert until its first
call), and the AkShare adapter only constructs its lazy-importing
``AkshareClient`` (which itself is inert until the first fetch call).
Operators see network errors at fetch time, not at factory time.
"""

from __future__ import annotations

from invest_domain.market_data.ports import EtfMarketDataProvider

from invest_pipeline.adapters.akshare import (
    AkshareInstrumentProvider,
    AkshareSettings,
)
from invest_pipeline.adapters.cifang import (
    CifangQuantInstrumentProvider,
    CifangSettings,
)
from invest_pipeline.adapters.errors import (
    ProviderAuthenticationError,
    RealProviderRequiresExplicitEnablementError,
    UnknownProviderError,
)
from invest_pipeline.adapters.fixture_dev import FixtureDevInstrumentProvider
from invest_pipeline.config import Settings, get_settings

_FIXTURE_DEV_KEY = "fixture_dev"
_CIFANG_KEY = "cifangquant"
_AKSHARE_KEY = "akshare"
_KNOWN_PROVIDER_KEYS: tuple[str, ...] = (
    _FIXTURE_DEV_KEY,
    _CIFANG_KEY,
    _AKSHARE_KEY,
)


def build_provider(
    settings: Settings | None = None,
    *,
    cifang_settings: CifangSettings | None = None,
    akshare_settings: AkshareSettings | None = None,
) -> EtfMarketDataProvider:
    """Return the provider selected by ``INVEST_PIPELINE_PROVIDER_KEY``.

    Parameters
    ----------
    settings:
        Pipeline-level settings object. ``None`` falls back to
        :func:`get_settings` (which is ``lru_cache``-d, so tests that
        need hermetic settings must construct a :class:`Settings`
        instance explicitly).
    cifang_settings:
        Optional pre-built :class:`CifangSettings`. When ``None``, the
        factory reads ``INVEST_PIPELINE_CIFANG_*`` from the
        environment. Tests inject a fully-populated settings object so
        the suite never has to touch real environment variables.
    akshare_settings:
        Optional pre-built :class:`AkshareSettings`. When ``None``, the
        factory reads ``INVEST_PIPELINE_AKSHARE_*`` from the
        environment; the default ``enabled=False`` keeps the adapter
        inert (matrix §6).

    Returns
    -------
    EtfMarketDataProvider
        A :class:`FixtureDevInstrumentProvider`,
        :class:`CifangQuantInstrumentProvider` or
        :class:`AkshareInstrumentProvider`, depending on
        ``settings.provider_key``.

    Raises
    ------
    UnknownProviderError
        When ``settings.provider_key`` is not in
        ``("fixture_dev", "cifangquant", "akshare")``. The exception
        carries the offending key as its ``KeyError`` argument.
    RealProviderRequiresExplicitEnablementError
        When ``provider_key in {"cifangquant", "akshare"}`` but the
        corresponding ``enabled`` flag is ``False``. This is the
        typed gate called out by ADR-0011 §3 / matrix §6 — never
        silently fall through to the fixture provider.
    ProviderAuthenticationError
        When ``provider_key == "cifangquant"`` and the API key is
        empty. The error message never embeds the token.
    """

    pipeline = settings if settings is not None else get_settings()
    key = pipeline.provider_key

    if key == _FIXTURE_DEV_KEY:
        return FixtureDevInstrumentProvider()

    if key == _CIFANG_KEY:
        cfg = cifang_settings if cifang_settings is not None else CifangSettings()
        if not cfg.enabled:
            raise RealProviderRequiresExplicitEnablementError(
                "cifangquant provider requires CifangSettings.enabled=True "
                "(INVEST_PIPELINE_CIFANG_ENABLED); "
                "see ADR-0011 §3 / O-1 / O-3 / O-4 blockers"
            )
        if cfg.api_key.get_secret_value() == "":
            raise ProviderAuthenticationError(
                key,
                "cifangquant provider requires a non-empty "
                "CifangSettings.api_key (INVEST_PIPELINE_CIFANG_API_KEY); "
                "see ADR-0011 §3",
            )
        return CifangQuantInstrumentProvider(cfg)

    if key == _AKSHARE_KEY:
        cfg = (
            akshare_settings
            if akshare_settings is not None
            else AkshareSettings()
        )
        if not cfg.enabled:
            raise RealProviderRequiresExplicitEnablementError(
                "akshare provider requires AkshareSettings.enabled=True "
                "(INVEST_PIPELINE_AKSHARE_ENABLED); "
                "see DATA-SOURCE-MIGRATION-MATRIX.md §6 / O-1 / O-3 "
                "/ O-4 blockers (PR-02)"
            )
        return AkshareInstrumentProvider(cfg)

    raise UnknownProviderError(key)


__all__ = ["KNOWN_PROVIDER_KEYS", "build_provider"]


# Public, frozen alias of the supported provider-key tuple so callers
# (and tests) can introspect the supported set without re-declaring the
# literals. The factory itself never reads this — it pattern-matches
# the string — but the value is exported for documentation / testing
# purposes.
KNOWN_PROVIDER_KEYS: tuple[str, ...] = _KNOWN_PROVIDER_KEYS
