"""Application service for the read-only ETF and instrument endpoints.

The service owns three read-side use cases the FastAPI routers expose:

* the legacy ``/v1/instruments`` sparse list
  (:meth:`EtfQueryService.list_active_instruments`),
* the ``/api/v1/etf/instruments`` active list filtered by ``exchange``
  / ``status`` (:meth:`EtfQueryService.list_active_instruments`),
* the ``/api/v1/etf/daily-bars`` range query that collapses every
  revision down to the latest per ``trade_date``
  (:meth:`EtfQueryService.list_latest_daily_bars`).

The router delegates session handling, repository construction, the
active-instrument fetch, the in-Python ``exchange`` / ``status`` filter
on the full active set, the per-day latest-revision reduction, the
``Adjust.NONE`` adjustment selection, the
:class:`invest_domain.instruments.Instrument` existence check and the
:class:`sqlalchemy.exc.SQLAlchemyError` boundary to this service so the
HTTP layer only translates the small domain views back into Pydantic
response shapes and converts the application exception into HTTP
errors.

Each repository is taken as a narrow :class:`typing.Protocol` so the
service depends only on the read-side surface it actually uses. The
concrete repositories are wired in by the dependency factory in
:mod:`invest_api.dependencies`; this module intentionally does not
import any storage-layer dataclasses so the application boundary
stays decoupled from the persistence representation. A local
:class:`DailyBarRecord` Protocol captures only the fields the
service and the router mapping actually read, and any object that
exposes them - including the storage dataclass returned by the
concrete repository - structurally conforms to it. There is
intentionally no generic service framework here: the application
layer is a thin domain-use-case wrapper, not an abstraction over
FastAPI or SQLAlchemy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from invest_domain.instruments import Instrument
from sqlalchemy.exc import SQLAlchemyError

INSTRUMENT_UNIVERSE_FETCH_LIMIT: int = 1000
"""Bounded page size the service asks the active-instrument repository for.

The ETF instrument universe is bounded by ADR-0004 to the SSE / SZSE
exchanges, so loading the full active set fits inside one page; this
matches the legacy router behaviour that fetched ``limit=1000,
offset=0`` so the API could compute the post-filter ``total`` and
paginate in Python.
"""

MISSING_INSTRUMENT_DETAIL_TEMPLATE: str = "instrument {instrument_id} not found"
"""Format string the router substitutes ``instrument_id`` into for a 404 detail.

Kept as a module constant so the router and any future caller can
format the wire-format detail without re-deriving the string.
"""

_QUERY_ERROR_DETAIL: str = "ETF query failed"
"""Exact 500 detail the router surfaces for :class:`EtfQueryError`."""


class InstrumentReader(Protocol):
    """Narrow read-side surface of the instrument repository."""

    def list_active(
        self, *, limit: int = 1000, offset: int = 0
    ) -> list[Instrument]:
        """Return the active instruments ordered by ``exchange``, ``symbol``."""

    def get_by_id(self, instrument_id: UUID) -> Instrument | None:
        """Return the instrument for ``instrument_id`` or ``None`` if absent."""


class DailyBarRecord(Protocol):
    """Minimal read-side surface of a persisted daily bar.

    Declares only the fields the service (``trade_date`` /
    ``revision`` for the latest-per-day reduction) and the router
    mapping (the ``DailyBarResponse`` Pydantic model) actually read.
    The concrete storage dataclass structurally conforms to this
    Protocol without the application layer needing to know its
    concrete type.
    """

    id: UUID
    instrument_id: UUID
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    prev_close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    adjustment: str
    trading_status: str
    source_provider: str
    source_batch_id: UUID | None
    observed_at: datetime
    revision: int
    row_hash: str
    created_at: datetime | None


class DailyBarReader(Protocol):
    """Narrow read-side surface of the daily-bar repository."""

    def list_by_instrument_and_range(
        self,
        *,
        instrument_id: UUID,
        start_date: date,
        end_date: date,
        adjustment: object,
    ) -> Sequence[DailyBarRecord]:
        """Return every revision of the bars in ``[start_date, end_date]``.

        The result is ordered by ``trade_date`` ascending then
        ``revision`` ascending so the service can run the
        latest-per-day reduction in a single pass.
        """


class EtfQueryError(RuntimeError):
    """Raised when either of the repositories raise :class:`SQLAlchemyError`.

    The HTTP layer converts this into a sanitized 500 response; the
    original driver-level exception is intentionally swallowed so the
    router never leaks a connection string or driver detail to the
    client.
    """


@dataclass(frozen=True, slots=True)
class InstrumentPageView:
    """Paginated view of the active instruments backing
    :class:`invest_api.schemas.InstrumentListResponse`.

    ``items`` carries the page slice the service computed; ``total`` is
    the size of the filtered universe (not just the current page) so
    the router can surface a real total without doing another query.
    ``limit`` and ``offset`` mirror the inputs so the router does not
    need to re-thread them through.
    """

    items: tuple[Instrument, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class DailyBarPageView:
    """Paginated view of the latest-revision-per-day bars backing
    :class:`invest_api.schemas.DailyBarListResponse`.

    ``items`` is sorted by ``trade_date`` ascending so the router can
    emit the same ordering with no extra work. ``total`` is the size of
    the latest-per-day set (not the underlying revision count), and
    ``limit`` / ``offset`` mirror the inputs.
    """

    items: tuple[DailyBarRecord, ...]
    total: int
    limit: int
    offset: int


class EtfQueryService:
    """Application service for the read-only ETF / instrument use cases.

    The service is intentionally small: it owns the
    ``INSTRUMENT_UNIVERSE_FETCH_LIMIT`` page size, the in-Python
    ``exchange`` / ``status`` filter, the per-day latest-revision
    reduction (ADR-0006 §6), the ``Adjust.NONE`` adjustment selection,
    the instrument existence check for the daily-bars endpoint, and the
    :class:`SQLAlchemyError` -> :class:`EtfQueryError` translation.
    Domain-to-response mapping stays in the router so the application
    layer remains free of FastAPI / Pydantic imports.
    """

    def __init__(
        self,
        *,
        instrument_repository: InstrumentReader,
        daily_bar_repository: DailyBarReader,
    ) -> None:
        self._instruments = instrument_repository
        self._daily_bars = daily_bar_repository

    def list_active_instruments(
        self,
        *,
        exchange: str | None = None,
        status_: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> InstrumentPageView:
        """Return the filtered active-set page for both ETF endpoints.

        The service fetches the full active set through
        ``INSTRUMENT_UNIVERSE_FETCH_LIMIT`` (matching the legacy ETF
        handler), applies the optional ``exchange`` and ``status_``
        filters in Python, computes the filtered ``total``, then slices
        the page. :class:`SQLAlchemyError` is caught and re-raised as
        :class:`EtfQueryError` so the HTTP layer renders a sanitized 500.
        """

        try:
            all_active = self._instruments.list_active(
                limit=INSTRUMENT_UNIVERSE_FETCH_LIMIT, offset=0
            )
        except SQLAlchemyError as exc:
            raise EtfQueryError(_QUERY_ERROR_DETAIL) from exc

        filtered = [
            item
            for item in all_active
            if (exchange is None or item.exchange == exchange)
            and (status_ is None or item.status.value == status_)
        ]
        total = len(filtered)
        page = filtered[offset : offset + limit]
        return InstrumentPageView(
            items=tuple(page), total=total, limit=limit, offset=offset
        )

    def list_latest_daily_bars(
        self,
        *,
        instrument_id: UUID,
        start_date: date,
        end_date: date,
        limit: int = 100,
        offset: int = 0,
    ) -> DailyBarPageView | None:
        """Return the latest-revision-per-day bars for ``instrument_id``.

        Resolves the instrument through
        :meth:`InstrumentReader.get_by_id` first; when the instrument
        is unknown the service returns ``None`` so the router can
        surface a single indistinguishable 404 with the
        ``MISSING_INSTRUMENT_DETAIL_TEMPLATE`` detail. Per ADR-0006 §6
        the repository returns every revision sorted by ``trade_date``
        then ``revision`` ascending, so the service keeps only the
        highest revision per day in a single pass.
        :class:`SQLAlchemyError` is caught and re-raised as
        :class:`EtfQueryError`.

        Note: the caller (``FastAPI``) is responsible for the
        ``end_date >= start_date`` HTTP-level validation; the repository
        also rejects an inverted range with ``ValueError``, and the
        service lets that propagate unchanged so the existing 400
        contract survives if a caller forgets the FastAPI check.
        """

        try:
            instrument = self._instruments.get_by_id(instrument_id)
        except SQLAlchemyError as exc:
            raise EtfQueryError(_QUERY_ERROR_DETAIL) from exc
        if instrument is None:
            return None

        from invest_domain.market_data.values import Adjust

        try:
            all_revisions = self._daily_bars.list_by_instrument_and_range(
                instrument_id=instrument_id,
                start_date=start_date,
                end_date=end_date,
                adjustment=Adjust.NONE,
            )
        except SQLAlchemyError as exc:
            raise EtfQueryError(_QUERY_ERROR_DETAIL) from exc

        latest_by_date: dict[date, DailyBarRecord] = {}
        for bar in all_revisions:
            existing = latest_by_date.get(bar.trade_date)
            if existing is None or bar.revision > existing.revision:
                latest_by_date[bar.trade_date] = bar
        ordered = sorted(latest_by_date.values(), key=lambda item: item.trade_date)
        total = len(ordered)
        page = ordered[offset : offset + limit]
        return DailyBarPageView(
            items=tuple(page), total=total, limit=limit, offset=offset
        )


__all__ = [
    "DailyBarPageView",
    "DailyBarReader",
    "DailyBarRecord",
    "EtfQueryError",
    "EtfQueryService",
    "INSTRUMENT_UNIVERSE_FETCH_LIMIT",
    "InstrumentPageView",
    "InstrumentReader",
    "MISSING_INSTRUMENT_DETAIL_TEMPLATE",
]
