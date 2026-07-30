from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str


class InstrumentResponse(BaseModel):
    symbol: str
    name: str
    exchange: str
    instrument_type: str
    is_active: bool


class InstrumentListResponse(BaseModel):
    items: list[InstrumentResponse]
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
