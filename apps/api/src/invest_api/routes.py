from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from invest_api.config import get_settings
from invest_api.dependencies import get_db_session
from invest_api.schemas import HealthResponse, InstrumentListResponse, InstrumentResponse
from invest_storage.repositories import SqlAlchemyInstrumentRepository

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=get_settings().app_name)


@router.get("/v1/instruments", response_model=InstrumentListResponse, tags=["instruments"])
def list_instruments(
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InstrumentListResponse:
    repository = SqlAlchemyInstrumentRepository(session)
    instruments = repository.list_active(limit=limit, offset=offset)
    return InstrumentListResponse(
        items=[
            InstrumentResponse(
                symbol=item.symbol,
                name=item.name,
                exchange=item.exchange,
                instrument_type=item.instrument_type.value,
                is_active=item.is_active,
            )
            for item in instruments
        ],
        limit=limit,
        offset=offset,
    )
