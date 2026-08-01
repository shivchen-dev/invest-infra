"""Read-only ETF endpoints under ``/api/v1/etf``.

Both endpoints stay inside the storage repositories' surface area -
the handler fetches domain objects and translates them into the
Pydantic response shapes. No write path is exposed here.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from invest_domain.market_data.values import Adjust
from invest_storage.repositories import (
    SqlAlchemyDailyBarRepository,
    SqlAlchemyInstrumentRepository,
)
from sqlalchemy.orm import Session

from invest_api.dependencies import get_db_session
from invest_api.schemas.etf import (
    DailyBarListResponse,
    DailyBarResponse,
    InstrumentListResponse,
    InstrumentResponse,
)

router = APIRouter(prefix="/api/v1/etf", tags=["etf"])


@router.get("/instruments", response_model=InstrumentListResponse)
def list_etf_instruments(
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    exchange: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    status_: Annotated[str | None, Query(alias="status", min_length=1, max_length=24)] = None,
) -> InstrumentListResponse:
    """Return the active ETF master data, optionally filtered by exchange/status."""

    repository = SqlAlchemyInstrumentRepository(session)
    # Fetch the full active set so the API can compute ``total`` after
    # filtering. The endpoint is read-only and the active instrument
    # universe is bounded by ADR-0004 to the SSE / SZSE exchanges.
    all_active = repository.list_active(limit=1000, offset=0)
    filtered = [
        item
        for item in all_active
        if (exchange is None or item.exchange == exchange)
        and (status_ is None or item.status.value == status_)
    ]
    total = len(filtered)
    page = filtered[offset : offset + limit]
    items = [InstrumentResponse.from_instrument(item) for item in page]
    return InstrumentListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/daily-bars", response_model=DailyBarListResponse)
def list_etf_daily_bars(
    session: Annotated[Session, Depends(get_db_session)],
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

    instrument_repository = SqlAlchemyInstrumentRepository(session)
    instrument = instrument_repository.get_by_id(instrument_id)
    if instrument is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"instrument {instrument_id} not found",
        )

    daily_bar_repository = SqlAlchemyDailyBarRepository(session)
    all_revisions = daily_bar_repository.list_by_instrument_and_range(
        instrument_id=instrument_id,
        start_date=start_date,
        end_date=end_date,
        adjustment=Adjust.NONE,
    )
    # Per ADR-0006 §6, callers run their own "latest per day" reduction;
    # the repository returns every revision sorted by trade_date then
    # revision ascending, so we keep only the highest revision per day.
    latest_by_date: dict[date, object] = {}
    for bar in all_revisions:
        existing = latest_by_date.get(bar.trade_date)
        if existing is None or bar.revision > existing.revision:
            latest_by_date[bar.trade_date] = bar
    ordered = sorted(latest_by_date.values(), key=lambda item: item.trade_date)
    total = len(ordered)
    page = ordered[offset : offset + limit]
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
        for bar in page
    ]
    return DailyBarListResponse(items=items, total=total, limit=limit, offset=offset)


__all__ = ["router"]
