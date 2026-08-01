"""CifangQuant Adapter (Phase 1, ADR-0011 placeholder).

The first bounded increment freezes the official CifangQuant API facts
documented in :doc:`docs/adr/0011-cifangquant-primary-etf-provider.md`
and exposes only the domain :class:`invest_domain.market_data.ports.
EtfMarketDataProvider` shape. Real network I/O, the HTTP client and the
field mapper are intentionally not implemented in this increment; both
``fetch_*`` methods raise
:class:`invest_pipeline.adapters.errors.ProviderAdapterNotImplementedError`
with a pointer to ADR-0011 so the call site surfaces a stable failure
category (ADR-0003 §4) until O-1 / O-3 / O-4 are closed.

Configuration lives in :class:`invest_pipeline.adapters.cifang.config.
CifangSettings`; it is disabled by default, locks ``adjustment`` to
``"none"`` (ADR-0005) and redacts the API key from ``repr`` / ``str``.
"""

from __future__ import annotations

from invest_pipeline.adapters.cifang.adapter import CifangQuantInstrumentProvider
from invest_pipeline.adapters.cifang.config import CifangSettings

__all__ = ["CifangQuantInstrumentProvider", "CifangSettings"]