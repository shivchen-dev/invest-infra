"""CifangQuant Adapter placeholder (Phase 1 first increment, ADR-0011).

This module intentionally exposes **only** the domain
:class:`invest_domain.market_data.ports.EtfMarketDataProvider` shape and
raises :class:`invest_pipeline.adapters.errors.ProviderAdapterNotImplementedError`
from both ``fetch_*`` methods. The HTTP client, mapper, rate limiter and
real credential handling belong to the Phase 1 second-increment and are
gated on O-1 / O-3 / O-4 (ADR-0011 §4).

The class carries a ``provider_key`` of ``"cifangquant"`` so the
application layer can persist the canonical Provider identifier in
``raw.provider_requests`` without needing a separate configuration
lookup; the value matches the candidate naming frozen in ADR-0011 §1
and the historical ``cifang`` / ``akshare`` keys documented in
``docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from invest_domain.instruments.models import Instrument
from invest_domain.market_data.models import (
    DailyBar,
    ProviderAttempt,
    ProviderBatch,
    ProviderRequest,
)

from invest_pipeline.adapters.cifang.config import CifangSettings
from invest_pipeline.adapters.errors import ProviderAdapterNotImplementedError

_PROVIDER_KEY = "cifangquant"
_NOT_IMPLEMENTED_POINTER = (
    "CifangQuantAdapter is a Phase 1 placeholder (ADR-0011, Status: Proposed). "
    "Real network I/O is gated on O-1 / O-3 / O-4 closure; "
    "see docs/adr/0011-cifangquant-primary-etf-provider.md §4."
)


class CifangQuantInstrumentProvider:
    """Placeholder adapter that satisfies the :class:`EtfMarketDataProvider` port.

    The class declares the same public surface as
    :class:`invest_pipeline.adapters.fixture_dev.adapter.FixtureDevInstrumentProvider`
    so application services and Dagster assets can wire it through the
    Provider Registry without conditional code paths. Both
    :meth:`fetch_instruments` and :meth:`fetch_daily_bars` immediately
    raise
    :class:`invest_pipeline.adapters.errors.ProviderAdapterNotImplementedError`
    with a message that points the operator at ADR-0011 — that error
    category is the documented failure type for adapters whose
    capability is not yet implemented (ADR-0003 §4 / placeholder
    guidance).
    """

    def __init__(self, settings: CifangSettings | None = None) -> None:
        # The settings object is accepted for symmetry with the
        # fixture_dev adapter and to give the second-increment a stable
        # injection point. It is not consulted in this increment; the
        # placeholder raises before any field is read.
        self._settings = settings

    @property
    def provider_key(self) -> str:
        return _PROVIDER_KEY

    def fetch_instruments(
        self, as_of: date
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[Instrument] | None]:
        raise ProviderAdapterNotImplementedError(
            _PROVIDER_KEY,
            f"fetch_instruments(as_of={as_of.isoformat()}) not implemented. "
            f"{_NOT_IMPLEMENTED_POINTER}",
        )

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None]:
        raise ProviderAdapterNotImplementedError(
            _PROVIDER_KEY,
            f"fetch_daily_bars(symbols={list(symbols)!r}, "
            f"start_date={start_date.isoformat()}, "
            f"end_date={end_date.isoformat()}) not implemented. "
            f"{_NOT_IMPLEMENTED_POINTER}",
        )


__all__ = ["CifangQuantInstrumentProvider"]