"""Legacy cross-cutting response schemas shared across routers.

The PR-09 read-only endpoints live in the dedicated
:mod:`invest_api.schemas.etf` and :mod:`invest_api.schemas.candidate_pool`
modules; this file keeps the simple shapes used by the original
``/v1/instruments`` and ``/health`` endpoints.
"""

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


__all__ = ["HealthResponse", "InstrumentListResponse", "InstrumentResponse"]
