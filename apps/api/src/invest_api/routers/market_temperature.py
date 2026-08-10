from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from invest_api.application.market_temperature import (
    MarketTemperatureQueryError,
    MarketTemperatureQueryService,
)
from invest_api.dependencies import get_market_temperature_query_service
from invest_api.schemas.market_temperature import MarketTemperatureResponse

router = APIRouter(prefix="/api/v1/market-temperature", tags=["market-temperature"])


@router.get("/latest", response_model=MarketTemperatureResponse)
def get_latest_market_temperature(
    service: Annotated[
        MarketTemperatureQueryService, Depends(get_market_temperature_query_service)
    ],
) -> MarketTemperatureResponse:
    try:
        snapshot = service.get_latest()
    except MarketTemperatureQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Market temperature query failed",
        ) from exc
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Market temperature snapshot not found",
        )
    return MarketTemperatureResponse.from_domain(snapshot)
