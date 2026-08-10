"""Application service for the read-only ``/api/v1/market-breadth`` slice.

The service is the smallest possible vertical cut of the Stage 4B
Market Breadth read surface: it pins a single ``scope_type`` /
``scope_key`` pair (``"ashare_universe"`` /
``"ashare_active_universe_v1"``) because the API is the only consumer
of the breadth family in this slice, calls the storage repository's
:meth:`get_latest_for_scope` method with an optional ``as_of_date``
override, and translates any :class:`sqlalchemy.exc.SQLAlchemyError`
into :class:`MarketBreadthQueryError` so the HTTP layer can render a
sanitized 500.

The repository is taken as a narrow :class:`MarketBreadthReader`
:class:`typing.Protocol` so the service depends only on the read-side
method it actually uses; the dependency factory in
:mod:`invest_api.dependencies` instantiates the concrete
:class:`invest_storage.SqlAlchemyMarketObservationSnapshotRepository`
against the FastAPI-provided session and passes it in.

There is intentionally no generic service framework here: the
application layer is a thin domain-use-case wrapper, not an
abstraction over FastAPI or SQLAlchemy.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from invest_domain.analytics.market_observations import MarketObservationSnapshot
from sqlalchemy.exc import SQLAlchemyError

SCOPE_TYPE: str = "ashare_universe"
"""Fixed ``scope_type`` the read-only API narrows the breadth family to.

The Market Breadth family carries one ``scope_key`` in this slice; the
API service pins it so callers cannot accidentally read a Market
Temperature snapshot through the breadth route.
"""

SCOPE_KEY: str = "ashare_active_universe_v1"
"""Fixed ``scope_key`` the read-only API narrows the breadth family to."""

_QUERY_ERROR_DETAIL: str = "Market breadth query failed"
"""Exact 500 detail the router surfaces for :class:`MarketBreadthQueryError`."""


class MarketBreadthReader(Protocol):
    """Read-side surface the breadth service depends on.

    Declared as a structural :class:`typing.Protocol` so the storage
    repository satisfies it without the storage layer having to import
    a type from the application layer. The protocol intentionally
    exposes only the scope-filtered lookup the service uses; the
    service never asks the reader for an unscoped "latest" because that
    would risk leaking a sibling ``scope_type`` (e.g. ``market_temperature``)
    through the breadth route.
    """

    def get_latest_for_scope(
        self,
        scope_type: str,
        scope_key: str,
        as_of_date: date | None = None,
    ) -> MarketObservationSnapshot | None: ...


class MarketBreadthQueryError(RuntimeError):
    """Raised when the breadth reader raises :class:`SQLAlchemyError`.

    The HTTP layer converts this into a sanitized 500 response; the
    original driver-level exception is intentionally swallowed so the
    router never leaks a connection string or driver detail to the
    client.
    """


class MarketBreadthQueryService:
    """Application service for the read-only ``/api/v1/market-breadth`` use case.

    The service owns the scope filter (pinned to ``ashare_universe`` /
    ``ashare_active_universe_v1``), the optional ``as_of_date`` default
    (``None`` -> "newest snapshot regardless of date") and the
    :class:`SQLAlchemyError` -> :class:`MarketBreadthQueryError`
    translation. Domain-to-response mapping stays in the router so the
    application layer remains free of FastAPI / Pydantic imports.
    """

    def __init__(self, reader: MarketBreadthReader) -> None:
        self._reader = reader

    def get_latest(
        self, as_of_date: date | None = None
    ) -> MarketObservationSnapshot | None:
        """Return the latest Market Breadth snapshot for ``as_of_date``.

        ``as_of_date`` defaults to ``None`` so the reader returns the
        newest snapshot regardless of date; the router forwards
        ``as_of_date`` verbatim from the optional ``as_of_date`` query
        parameter without any extra defaulting. ``SQLAlchemyError`` from
        the reader is translated to :class:`MarketBreadthQueryError`
        so the router can render a sanitized 500.
        """

        try:
            return self._reader.get_latest_for_scope(
                SCOPE_TYPE, SCOPE_KEY, as_of_date
            )
        except SQLAlchemyError as exc:
            raise MarketBreadthQueryError(_QUERY_ERROR_DETAIL) from exc


__all__ = [
    "MarketBreadthQueryError",
    "MarketBreadthQueryService",
    "MarketBreadthReader",
    "SCOPE_KEY",
    "SCOPE_TYPE",
]