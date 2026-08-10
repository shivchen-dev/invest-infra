"""Domain Ports (Protocols) and pure-domain errors for ``market_data``.

The Port definitions live in the domain layer per ADR-0003. Adapters that
implement them must live in ``apps/pipeline`` and must not import this
module — this keeps the dependency direction one-way (pipeline -> domain).

PR-02 widens the contract from a single :class:`ProviderBatch` to the
three-layer evidence model (:class:`ProviderRequest` / :class:`ProviderAttempt`
/ :class:`ProviderBatch`). Adapters MUST return all three layers so the
application service can persist ``raw.provider_requests``,
``raw.provider_attempts`` and (on success / partial) ``raw.provider_batches``
with consistent FK wiring. The :class:`ProviderBatch` is ``None`` when
the attempt failed: failed attempts leave no batch row behind, the
failure evidence lives on the attempt row only.

:exc:`ProviderDataContractError` is a pure-domain exception that adapters
must raise when a Provider response violates the ADR-0005 contract
(unsupported adjustment, malformed field, non-ETF instrument in a daily-bar
batch, etc.). The Adapter is responsible for converting internal SDK /
HTTP exceptions into this single canonical type before the batch leaves
the Adapter boundary; the domain does not depend on any specific Provider
SDK, HTTP library, or logging framework.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from invest_domain.instruments.models import Instrument
from invest_domain.market_data.models import (
    DailyBar,
    ProviderAttempt,
    ProviderBatch,
    ProviderRequest,
)


class ProviderDataContractError(ValueError):
    """Raised when a Provider response violates the ADR-0005 contract.

    Pure-domain exception; carries the Provider identifier and a
    stable, machine-readable reason ``code`` so the application layer can
    fan out to alerts / dead-letter queues without re-parsing free text.
    The ``message`` is a human-readable explanation.
    """

    def __init__(self, code: str, message: str, *, provider_key: str | None = None) -> None:
        if not code or not code.strip():
            raise ValueError("ProviderDataContractError.code must not be empty")
        if not message or not message.strip():
            raise ValueError("ProviderDataContractError.message must not be empty")
        super().__init__(f"[{code}] {message}")
        self.code = code.strip()
        self.message = message.strip()
        self.provider_key = provider_key.strip() if provider_key else None


@runtime_checkable
class InstrumentProvider(Protocol):
    """Port for listing ETF instruments from a Provider.

    This is the canonical definition. ``invest_domain.ports`` re-exports
    the same class so callers that import the legacy path see the exact
    same object and ``isinstance`` checks are stable.
    """

    def list_instruments(self) -> Sequence[Instrument]: ...


@runtime_checkable
class EtfMarketDataProvider(Protocol):
    """Port for fetching standardized ETF master data and daily bars.

    Mirrors plan §4.2 / ADR-0003 (PR-02 three-layer model). Adapters
    must:

    - Identify themselves via a non-empty ``provider_key`` (e.g.
      ``fixture_dev``, ``cifang`` once O-1 is closed).
    - Return a ``(ProviderRequest, ProviderAttempt, ProviderBatch[T] | None)``
      triple for every call so the application service can persist
      ``raw.provider_requests``, ``raw.provider_attempts`` and (on
      success / partial) ``raw.provider_batches``. A ``None`` batch
      signals a failed attempt; the failure evidence still lives on
      the returned :class:`ProviderAttempt`.
    - Convert any internal SDK / HTTP exceptions into
      :exc:`ProviderDataContractError` before the batch leaves the Adapter
      layer; the domain never sees the underlying SDK / transport types.
    """

    @property
    def provider_key(self) -> str: ...

    def fetch_instruments(
        self, as_of: date
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[Instrument] | None]: ...

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None]: ...


@runtime_checkable
class StockMarketDataProvider(EtfMarketDataProvider, Protocol):
    """Port with the same evidence contract for listed A-share stocks."""
