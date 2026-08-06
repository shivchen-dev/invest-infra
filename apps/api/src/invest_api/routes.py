from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from invest_api.application.etf import EtfQueryError, EtfQueryService
from invest_api.config import get_settings
from invest_api.dependencies import get_etf_query_service
from invest_api.schemas import HealthResponse
from invest_api.schemas.common import InstrumentListResponse, InstrumentResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=get_settings().app_name)


@router.get(
    "/v1/instruments",
    response_model=InstrumentListResponse,
    response_model_exclude={
        "total": True,
        "items": {
            "__all__": {
                "id",
                "currency",
                "status",
                "list_date",
                "delist_date",
                "underlying_index",
                "category",
            }
        },
    },
    tags=["instruments"],
)
def list_instruments(
    service: Annotated[EtfQueryService, Depends(get_etf_query_service)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InstrumentListResponse:
    try:
        view = service.list_active_instruments(limit=limit, offset=offset)
    except EtfQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ETF query failed",
        ) from exc
    return InstrumentListResponse(
        items=[InstrumentResponse.from_instrument(item) for item in view.items],
        total=view.total,
        limit=view.limit,
        offset=view.offset,
    )
