"""ProviderRuntimeRegistry — Provider–Engine–Event Phase 1 T1.2 seam.

The registry is a thin, stateless adapter over the existing
:mod:`invest_pipeline.provider_catalog` and
:mod:`invest_pipeline.provider_factory` modules. It exists so the
upcoming Engine and Event layers have a single, typed entry point that
resolves a runtime provider behind a :class:`invest_pipeline.config.
Settings` instance without re-implementing the catalog/factory wiring.

The registry owns **no** state, schedule, event, session, or database
seam — it is purely a resolver that:

* Looks the request's ``provider_key`` up in the catalog (so a
  completely unknown key surfaces as :class:`KeyError` before any
  factory branch runs).
* Delegates the construction to the existing
  :func:`invest_pipeline.provider_factory.build_provider` (ETF) /
  :func:`invest_pipeline.provider_factory.build_stock_provider`
  (stock) factory functions, preserving the canonical fail-closed
  errors:

  - :class:`invest_pipeline.adapters.errors.UnknownProviderError` for
    catalog-only entries (``tdx_offline`` / ``hithink`` / ``rsscast``
    / ``quicktiny_mcp``) and for any other key outside the
    runtime-supported set;
  - :class:`invest_pipeline.adapters.errors.RealProviderRequiresExplicitEnablementError`
    for real (non-fixture) providers whose ``enabled`` flag is
    ``False``;
  - :class:`invest_pipeline.adapters.errors.ProviderAuthenticationError`
    for providers whose credential (``api_key`` / ``token``) is
    missing or empty.

* Wraps the resulting provider into a frozen
  :class:`ResolvedProvider` record so the Engine / Event layers
  cannot accidentally mutate the resolution. The record exposes the
  underlying provider object, the catalog declaration and the
  canonical ``provider_key`` so callers can introspect the resolved
  surface (role / capabilities / ``enabled_by_default``) without
  re-issuing :func:`invest_pipeline.provider_catalog.lookup_provider`.

* Exposes :meth:`ProviderRuntimeRegistry.describe` as a thin wrapper
  over :func:`invest_pipeline.provider_catalog.lookup_provider` so the
  Engine layer can read the catalog (for routing / coverage / status
  displays) through the same entry point.

The registry deliberately does **not**:

* Add a fallback chain, retry policy, or scheduling hook. The Engine /
  Event layers are expected to layer those concerns on top of the
  registry's :class:`ResolvedProvider` result; the registry must stay
  a pure resolver so the Engine's orchestration logic remains the
  single place that decides "what to do when a provider fails".
* Touch the database, the session factory, the Dagster ``Definitions``
  object, the credentials store beyond what the factory already
  consults, or any HTTP / MCP / SDK transport. Construction is
  therefore guaranteed to stay network-free; the underlying
  :func:`invest_pipeline.provider_factory.build_provider` /
  :func:`invest_pipeline.provider_factory.build_stock_provider`
  factories already enforce that contract (PR-01 / PR-02 / ADR-0011).
* Re-declare the runtime-supported keys tuple. The factory's
  :data:`invest_pipeline.provider_factory.KNOWN_PROVIDER_KEYS` alias
  (derived from the catalog's
  :func:`invest_pipeline.provider_catalog.runtime_supported_provider_keys`
  helper) remains the single source of truth for the runtime surface
  (GOV-04); the registry is an adapter/reader of that authority, not a
  parallel source of truth.

Phase 1 scope (this slice):

* ``resolve_etf`` covers the full ETF runtime surface — fixture_dev,
  cifangquant, akshare, tushare — preserving every fail-closed branch
  the factory already implements.
* ``resolve_stock`` only permits ``tushare``. ``tdx_offline`` and the
  other catalog-only entries are deliberately rejected by the factory
  with :class:`invest_pipeline.adapters.errors.UnknownProviderError`
  even though their catalog declaration is resolvable (the lookup
  succeeds, the factory rejects); this keeps the stock runtime
  surface narrow until a follow-up ADR wires the TDX offline reader.
* ``describe`` is a thin catalog lookup so callers have one entry
  point that never re-implements the catalog identity map.
"""

from __future__ import annotations

from dataclasses import dataclass

from invest_domain.market_data.ports import EtfMarketDataProvider

from invest_pipeline.adapters.akshare import AkshareSettings
from invest_pipeline.adapters.cifang import CifangSettings
from invest_pipeline.adapters.tushare import TushareSettings
from invest_pipeline.config import Settings
from invest_pipeline.provider_catalog import (
    ProviderDeclaration,
    lookup_provider,
)
from invest_pipeline.provider_factory import build_provider, build_stock_provider


@dataclass(frozen=True, slots=True)
class ResolvedProvider:
    """Frozen result of resolving a runtime provider.

    Attributes
    ----------
    provider_key:
        Stable, lower_snake_case provider identifier. Mirrors
        :attr:`invest_pipeline.provider_catalog.ProviderDeclaration.provider_key`
        and the runtime instance's ``provider_key`` property so the
        three values agree.
    declaration:
        The catalog declaration the resolution looked up. Held so the
        Engine / Event layers can introspect the resolved provider's
        role / capabilities / ``enabled_by_default`` flag without
        re-issuing :func:`invest_pipeline.provider_catalog.lookup_provider`.
    provider:
        The constructed runtime provider instance, typed as the
        canonical ETF port (:class:`invest_domain.market_data.ports.
        EtfMarketDataProvider`). The Tushare-backed A-share stock
        provider implements the same port so the same typing covers
        both :meth:`ProviderRuntimeRegistry.resolve_etf` and
        :meth:`ProviderRuntimeRegistry.resolve_stock` results.
    """

    provider_key: str
    declaration: ProviderDeclaration
    provider: EtfMarketDataProvider


class ProviderRuntimeRegistry:
    """Resolve the runtime provider behind a :class:`Settings` instance.

    The registry is intentionally stateless: every method returns a new
    :class:`ResolvedProvider` (or raises) without mutating any
    internal cache, so it is safe to construct once per request and
    share across Dagster assets / CLI commands / tests.

    Construction never reaches out to the network, the database, the
    session factory, the Dagster object graph, or the credentials
    store beyond what the underlying factory already consults. The
    registry is purely a composition root for the runtime provider
    surface that the existing catalog and factory already manage.
    """

    def resolve_etf(
        self,
        settings: Settings,
        *,
        cifang_settings: CifangSettings | None = None,
        akshare_settings: AkshareSettings | None = None,
        tushare_settings: TushareSettings | None = None,
    ) -> ResolvedProvider:
        """Resolve the ETF runtime provider behind ``settings``.

        Parameters
        ----------
        settings:
            Pipeline-level settings object. ``settings.provider_key``
            drives the catalog lookup and the factory selection.
        cifang_settings:
            Optional pre-built :class:`CifangSettings` forwarded to
            :func:`invest_pipeline.provider_factory.build_provider`.
            When ``None`` the factory reads
            ``INVEST_PIPELINE_CIFANG_*`` from the environment.
        akshare_settings:
            Optional pre-built :class:`AkshareSettings` forwarded to
            the factory. When ``None`` the factory reads
            ``INVEST_PIPELINE_AKSHARE_*`` from the environment.
        tushare_settings:
            Optional pre-built :class:`TushareSettings` forwarded to
            the factory. When ``None`` the factory reads
            ``INVEST_PIPELINE_TUSHARE_*`` from the environment.

        Returns
        -------
        ResolvedProvider
            Frozen record carrying the constructed provider, the
            catalog declaration and the canonical ``provider_key``.

        Raises
        ------
        KeyError
            When ``settings.provider_key`` is not registered in the
            catalog at all (e.g. ``"eastmoney"``, a typo, an empty
            string or a mistyped case). The raised :class:`KeyError`
            carries the requested key as its argument, mirroring
            :func:`invest_pipeline.provider_catalog.lookup_provider`.
        invest_pipeline.adapters.errors.UnknownProviderError
            When ``settings.provider_key`` is in the catalog but is
            not backed by a runtime factory adapter (catalog-only
            entries: ``tdx_offline`` / ``hithink`` / ``rsscast`` /
            ``quicktiny_mcp``). The factory raises this with the
            offending key as its first argument; the registry does
            not wrap or rewrite the error.
        invest_pipeline.adapters.errors.RealProviderRequiresExplicitEnablementError
            When a real (non-fixture) provider is selected but its
            settings' ``enabled`` flag is ``False``. The factory
            raises this for ``cifangquant`` / ``akshare`` /
            ``tushare``; the registry does not wrap or rewrite the
            error.
        invest_pipeline.adapters.errors.ProviderAuthenticationError
            When a real provider is selected and enabled yet its
            credential (``api_key`` / ``token``) is missing. The
            factory raises this for ``cifangquant`` and ``tushare``;
            the registry does not wrap or rewrite the error.
        """

        declaration = lookup_provider(settings.provider_key)
        provider = build_provider(
            settings,
            cifang_settings=cifang_settings,
            akshare_settings=akshare_settings,
            tushare_settings=tushare_settings,
        )
        return ResolvedProvider(
            provider_key=declaration.provider_key,
            declaration=declaration,
            provider=provider,
        )

    def resolve_stock(
        self,
        settings: Settings,
        *,
        tushare_settings: TushareSettings | None = None,
    ) -> ResolvedProvider:
        """Resolve the A-share stock runtime provider behind ``settings``.

        The stock surface is intentionally narrower than the ETF
        surface: only ``tushare`` has a stock provider today. The
        ``tdx_offline`` catalog declaration is registered (Stage 4B
        Phase 5 slice 1) but its adapter is not wired into
        :func:`invest_pipeline.provider_factory.build_stock_provider`
        yet — ``tdx_offline`` therefore stays catalog-only and the
        factory raises :class:`invest_pipeline.adapters.errors.UnknownProviderError`
        with ``"tdx_offline"`` as the offending key. The registry
        preserves that contract verbatim so callers see a stable
        error category.

        Parameters
        ----------
        settings:
            Pipeline-level settings object. ``settings.provider_key``
            drives the catalog lookup and the factory selection.
        tushare_settings:
            Optional pre-built :class:`TushareSettings` forwarded to
            :func:`invest_pipeline.provider_factory.build_stock_provider`.
            When ``None`` the factory reads ``INVEST_PIPELINE_TUSHARE_*``
            from the environment.

        Returns
        -------
        ResolvedProvider
            Frozen record carrying the constructed
            :class:`invest_pipeline.adapters.tushare.StockTushareProvider`
            (typed as the canonical ETF port because the stock
            adapter implements the same evidence-contract protocol),
            the catalog declaration and the canonical ``provider_key``.

        Raises
        ------
        KeyError
            When ``settings.provider_key`` is not registered in the
            catalog at all. Raised by the catalog lookup before the
            factory runs.
        invest_pipeline.adapters.errors.UnknownProviderError
            When ``settings.provider_key`` is in the catalog but the
            factory refuses it. This covers the historical ETF
            providers (``fixture_dev`` / ``cifangquant`` / ``akshare``)
            and the catalog-only entries (``tdx_offline`` /
            ``hithink`` / ``rsscast`` / ``quicktiny_mcp``). The
            factory raises this with the offending key as its first
            argument; the registry does not wrap or rewrite the
            error.
        invest_pipeline.adapters.errors.RealProviderRequiresExplicitEnablementError
            When ``settings.provider_key == "tushare"`` but
            ``tushare_settings.enabled is False``. The registry
            forwards the factory's error verbatim.
        invest_pipeline.adapters.errors.ProviderAuthenticationError
            When ``settings.provider_key == "tushare"`` and the
            resolved token is empty. The registry forwards the
            factory's error verbatim.
        """

        declaration = lookup_provider(settings.provider_key)
        provider = build_stock_provider(settings, tushare_settings=tushare_settings)
        return ResolvedProvider(
            provider_key=declaration.provider_key,
            declaration=declaration,
            provider=provider,
        )

    def describe(self, provider_key: str) -> ProviderDeclaration:
        """Return the catalog declaration registered under ``provider_key``.

        Thin wrapper over
        :func:`invest_pipeline.provider_catalog.lookup_provider` so
        the Engine / Event layers have a single entry point that
        reads the catalog. The wrapper intentionally does not catch
        or rewrite the :class:`KeyError` the catalog raises for
        unknown keys — the canonical catalog error category carries
        the offending key as its argument and callers can introspect
        it without parsing message text.

        Parameters
        ----------
        provider_key:
            The provider identifier to describe.

        Returns
        -------
        invest_pipeline.provider_catalog.ProviderDeclaration
            The catalog declaration registered under ``provider_key``.

        Raises
        ------
        KeyError
            When no provider is registered under ``provider_key``.
            The raised :class:`KeyError` carries the requested key as
            its argument, mirroring
            :func:`invest_pipeline.provider_catalog.lookup_provider`.
        """

        return lookup_provider(provider_key)


__all__ = ["ProviderRuntimeRegistry", "ResolvedProvider"]