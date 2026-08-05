"""Tushare Pro adapter (Phase 1, bounded increment).

Mirrors the CifangQuant ``invest_pipeline.adapters.cifang`` package
shape: a thin ``TushareSettings`` object, a POST-JSON ``TushareClient``
and an evidence-tuple :class:`TushareInstrumentProvider` that wires the
client to the domain :class:`invest_domain.market_data.ports.
EtfMarketDataProvider` port.

The Tushare Pro HTTP API is a single ``https://api.tushare.pro``
endpoint accepting ``POST`` with a JSON body of
``{api_name, token, params, fields}``. The adapter limits itself to
the two documented ETF surfaces — ``fund_basic`` for the master-data
pull and ``fund_daily`` for the daily-bars pull — and reuses the
existing three-layer evidence tuple
(``ProviderRequest`` / ``ProviderAttempt`` / ``ProviderBatch``) so
the rest of the pipeline needs no awareness of Tushare's wire
format.

Configuration lives in :class:`TushareSettings`; it is disabled by
default, locks ``adjust`` to ``"none"`` and redacts the token from
``repr`` / ``str`` (mirrors the redaction rules in ADR-0010 §5 / §6).
The real token is read from the centralized credential store at request
time only, so ``TushareSettings`` itself never holds a secret.
"""

from __future__ import annotations

from invest_pipeline.adapters.tushare.adapter import TushareInstrumentProvider
from invest_pipeline.adapters.tushare.config import TushareSettings

__all__ = ["TushareInstrumentProvider", "TushareSettings"]
