"""Read-only ETF endpoints under ``/api/v1/etf``.

Both endpoints stay inside the application service's surface area -
the handlers translate the small domain views returned by
:class:`invest_api.application.etf.EtfQueryService` into the public
Pydantic response shapes and convert application exceptions into
HTTP errors. No storage repositories are referenced here; the
dependency factory in :mod:`invest_api.dependencies` owns the
session and the two repositories.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from invest_api.application.etf import (
    MISSING_INSTRUMENT_DETAIL_TEMPLATE,
    EtfQueryError,
    EtfQueryService,
)
from invest_api.dependencies import get_etf_query_service
from invest_api.schemas.etf import (
    DailyBarListResponse,
    DailyBarResponse,
    InstrumentListResponse,
    InstrumentResponse,
)

router = APIRouter(prefix="/api/v1/etf", tags=["etf"])


@router.get("/instruments", response_model=InstrumentListResponse)
def list_etf_instruments(
    service: Annotated[EtfQueryService, Depends(get_etf_query_service)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    exchange: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    status_: Annotated[str | None, Query(alias="status", min_length=1, max_length=24)] = None,
) -> InstrumentListResponse:
    """Return the active ETF master data, optionally filtered by exchange/status."""

    try:
        view = service.list_active_instruments(
            exchange=exchange, status_=status_, limit=limit, offset=offset
        )
    except EtfQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ETF query failed",
        ) from exc

    items = [InstrumentResponse.from_instrument(item) for item in view.items]
    return InstrumentListResponse(
        items=items, total=view.total, limit=view.limit, offset=view.offset
    )


@router.get("/daily-bars", response_model=DailyBarListResponse)
def list_etf_daily_bars(
    service: Annotated[EtfQueryService, Depends(get_etf_query_service)],
    instrument_id: Annotated[UUID, Query()],
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DailyBarListResponse:
    """Return the latest revision per trade_date for one instrument."""

    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"end_date {end_date.isoformat()} must be on or after "
                f"start_date {start_date.isoformat()}"
            ),
        )

    try:
        view = service.list_latest_daily_bars(
            instrument_id=instrument_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
    except EtfQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ETF query failed",
        ) from exc

    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MISSING_INSTRUMENT_DETAIL_TEMPLATE.format(
                instrument_id=instrument_id
            ),
        )

    items = [
        DailyBarResponse(
            instrument_id=bar.instrument_id,
            trade_date=bar.trade_date,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            prev_close=bar.prev_close,
            volume=bar.volume,
            amount=bar.amount,
            adjustment=bar.adjustment,
            trading_status=bar.trading_status,
            source_provider=bar.source_provider,
            source_batch_id=bar.source_batch_id,
            observed_at=bar.observed_at,
            revision=bar.revision,
        )
        for bar in view.items
    ]
    return DailyBarListResponse(
        items=items, total=view.total, limit=view.limit, offset=view.offset
    )


__all__ = ["router"]
