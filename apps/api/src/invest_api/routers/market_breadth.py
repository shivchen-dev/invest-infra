"""Read-only market-breadth endpoint ``GET /api/v1/market-breadth/latest``.

The endpoint exposes the Stage 4B Market Breadth observation family as
a single read-only lookup: it scopes the underlying
``analytics.market_observation_snapshots`` family to a fixed
``scope_type`` / ``scope_key`` pair (see
:mod:`invest_api.application.market_breadth`), accepts an optional
``as_of_date`` query parameter so the front-end can refetch a
historical trade date, and serialises the matching
:class:`MarketObservationSnapshot` through the public Pydantic shape.

The router only handles query-parameter validation, dependency
injection and the FastAPI / Pydantic response mapping; the scope
filter and the :class:`SQLAlchemyError` boundary both live in
:class:`invest_api.application.market_breadth.MarketBreadthQueryService`
so this module stays free of raw SQL and direct storage dependencies.

A missing snapshot returns 404; an invalid ``as_of_date`` value is
rejected by FastAPI with 422 before the handler is invoked; a
:class:`MarketBreadthQueryError` from the service is converted into a
sanitized HTTP 500 with the same ``Market breadth query failed``
detail the service emits so the client never sees a driver-level
exception repr.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from invest_api.application.market_breadth import (
    MarketBreadthQueryError,
    MarketBreadthQueryService,
)
from invest_api.dependencies import get_market_breadth_query_service
from invest_api.schemas.market_breadth import MarketBreadthResponse

router = APIRouter(prefix="/api/v1/market-breadth", tags=["market-breadth"])

_ERROR_DETAIL: str = "Market breadth query failed"
_NOT_FOUND_DETAIL: str = "Market breadth snapshot not found"


@router.get("/latest", response_model=MarketBreadthResponse)
def get_latest_market_breadth(
    service: Annotated[
        MarketBreadthQueryService, Depends(get_market_breadth_query_service)
    ],
    as_of_date: Annotated[date | None, Query()] = None,
) -> MarketBreadthResponse:
    """Return the latest Market Breadth snapshot for ``as_of_date``.

    ``as_of_date`` is optional: omitting it asks the service for the
    newest snapshot regardless of trade date; supplying a value
    narrows the lookup to that exact date. The application service
    pins ``scope_type`` / ``scope_key`` so the route never reads a
    sibling ``scope_type`` family (e.g. ``market_temperature``)
    through the breadth surface.
    """

    try:
        snapshot = service.get_latest(as_of_date)
    except MarketBreadthQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_ERROR_DETAIL,
        ) from exc
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NOT_FOUND_DETAIL,
        )
    return MarketBreadthResponse.from_domain(snapshot)


__all__ = ["router"]