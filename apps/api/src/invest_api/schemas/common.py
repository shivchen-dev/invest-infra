"""Legacy compatibility exports shared across routers."""

from __future__ import annotations

from pydantic import BaseModel

from invest_api.schemas.etf import InstrumentListResponse, InstrumentResponse


class HealthResponse(BaseModel):
    status: str
    service: str


__all__ = ["HealthResponse", "InstrumentListResponse", "InstrumentResponse"]
