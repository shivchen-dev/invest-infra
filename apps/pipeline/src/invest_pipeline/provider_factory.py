"""Runtime provider factory.

Selects an :class:`invest_domain.market_data.ports.EtfMarketDataProvider`
implementation from the pipeline-level ``INVEST_PIPELINE_PROVIDER_KEY``
setting and constructs it. The factory owns the runtime selection
surface; it has four provider branches and explicit failure modes:

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
* ``tushare`` -> :class:`TushareInstrumentProvider` constructed with a
  :class:`TushareSettings` object; construction is rejected until the
  provider is explicitly enabled. The client reads the operator-managed
  token file lazily when the first request is made.
* Anything else -> :class:`UnknownProviderError` carrying the offending
  key as the ``KeyError`` argument so callers (and operators reading
  logs) can identify the request without parsing the message string.

The factory consults :func:`invest_pipeline.provider_catalog.
runtime_supported_provider_keys` as the single source of truth for
which provider keys have a runtime factory adapter. ``KNOWN_PROVIDER_KEYS``
is derived from that helper rather than re-declaring the literals
inline, so the catalog (``provider_catalog``) remains the declaration
authority and the factory is an adapter/reader of that authority per
GOV-04. Catalog-only entries that do not advertise
``has_runtime_factory_adapter=True`` (currently ``rsscast`` and
``quicktiny_mcp``) therefore fail the upfront runtime gate with the
same :class:`UnknownProviderError` the factory raises for completely
unknown keys — preventing a regression where a research-only MCP
source silently re-enters the runtime selection surface.

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
from invest_pipeline.adapters.tushare import (
    StockTushareProvider,
    TushareInstrumentProvider,
    TushareSettings,
)
from invest_pipeline.config import Settings, get_settings
from invest_pipeline.provider_catalog import runtime_supported_provider_keys

_FIXTURE_DEV_KEY = "fixture_dev"
_CIFANG_KEY = "cifangquant"
_AKSHARE_KEY = "akshare"


def build_provider(
    settings: Settings | None = None,
    *,
    cifang_settings: CifangSettings | None = None,
    akshare_settings: AkshareSettings | None = None,
    tushare_settings: TushareSettings | None = None,
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
        :class:`CifangQuantInstrumentProvider`,
        :class:`AkshareInstrumentProvider` or
        :class:`TushareInstrumentProvider`, depending on
        ``settings.provider_key``.

    Raises
    ------
    UnknownProviderError
        When ``settings.provider_key`` is not in
        ``("fixture_dev", "cifangquant", "akshare", "tushare")``. The exception
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

    if key not in KNOWN_PROVIDER_KEYS:
        # The catalog is the declaration authority for which providers
        # have a runtime factory adapter. Validating against
        # ``KNOWN_PROVIDER_KEYS`` (derived from the catalog) before any
        # adapter branch runs turns catalog-only entries such as
        # ``rsscast`` / ``quicktiny_mcp`` (and any future
        # non-runtime declaration) into the same
        # :class:`UnknownProviderError` the factory already raises for
        # completely unknown keys — keeping the runtime surface
        # auditable without re-declaring the literals in two places.
        raise UnknownProviderError(key)

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
        if not cfg.resolved_api_key():
            raise ProviderAuthenticationError(
                key,
                "cifangquant provider requires a non-empty "
                "CifangSettings.api_key (INVEST_PIPELINE_CIFANG_API_KEY); "
                "see ADR-0011 §3",
            )
        return CifangQuantInstrumentProvider(cfg)

    if key == _AKSHARE_KEY:
        cfg = akshare_settings if akshare_settings is not None else AkshareSettings()
        if not cfg.enabled:
            raise RealProviderRequiresExplicitEnablementError(
                "akshare provider requires AkshareSettings.enabled=True "
                "(INVEST_PIPELINE_AKSHARE_ENABLED); "
                "see DATA-SOURCE-MIGRATION-MATRIX.md §6 / O-1 / O-3 "
                "/ O-4 blockers (PR-02)"
            )
        return AkshareInstrumentProvider(cfg)

    if key == "tushare":
        cfg = tushare_settings if tushare_settings is not None else TushareSettings()
        if not cfg.enabled:
            raise RealProviderRequiresExplicitEnablementError(
                "tushare provider requires TushareSettings.enabled=True "
                "(INVEST_PIPELINE_TUSHARE_ENABLED)"
            )
        if not cfg.resolved_token():
            raise ProviderAuthenticationError(key, "tushare provider credential is missing")
        return TushareInstrumentProvider(cfg)

    raise UnknownProviderError(key)


def build_stock_provider(
    settings: Settings | None = None,
    *,
    tushare_settings: TushareSettings | None = None,
):
    """Build the Tushare-backed A-share provider for stock consumers."""

    pipeline = settings if settings is not None else get_settings()
    if pipeline.provider_key != "tushare":
        raise UnknownProviderError(pipeline.provider_key)
    cfg = tushare_settings if tushare_settings is not None else TushareSettings()
    if not cfg.enabled:
        raise RealProviderRequiresExplicitEnablementError(
            "tushare provider requires TushareSettings.enabled=True "
            "(INVEST_PIPELINE_TUSHARE_ENABLED)"
        )
    if not cfg.resolved_token():
        raise ProviderAuthenticationError("tushare", "tushare provider credential is missing")
    return StockTushareProvider(cfg)


__all__ = ["KNOWN_PROVIDER_KEYS", "build_provider", "build_stock_provider"]


# Public, frozen alias of the supported provider-key tuple so callers
# (and tests) can introspect the supported set without re-declaring
# the literals. Derived from the catalog's
# ``runtime_supported_provider_keys`` helper so the catalog remains the
# single declaration authority (GOV-04); the factory is an
# adapter/reader of that authority, not a parallel source of truth.
KNOWN_PROVIDER_KEYS: tuple[str, ...] = runtime_supported_provider_keys()
