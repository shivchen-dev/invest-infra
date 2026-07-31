"""Pydantic response schemas for the ``/api/v1/etf`` read-only endpoints.

The shapes mirror the storage/domain objects returned by the
``SqlAlchemyInstrumentRepository`` and ``SqlAlchemyDailyBarRepository``.
The M1 API is intentionally read-only; therefore no request bodies are
defined here - every input is a query parameter on the endpoint itself.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class InstrumentResponse(BaseModel):
    """Public representation of one ``core.instruments`` row."""

    id: UUID
    symbol: str
    name: str
    exchange: str
    instrument_type: str
    currency: str
    status: str
    is_active: bool
    list_date: date | None = None
    delist_date: date | None = None
    underlying_index: str | None = None
    category: str | None = None


class InstrumentListResponse(BaseModel):
    """Paginated envelope for the ``GET /api/v1/etf/instruments`` endpoint."""

    items: list[InstrumentResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=1000)
    offset: int = Field(ge=0)


class DailyBarResponse(BaseModel):
    """One row of standardized daily OHLCV data (ADR-0005 / ADR-0006)."""

    instrument_id: UUID
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    prev_close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    adjustment: str
    trading_status: str
    source_provider: str
    source_batch_id: UUID | None
    observed_at: datetime
    revision: int


class DailyBarListResponse(BaseModel):
    """Paginated envelope for the ``GET /api/v1/etf/daily-bars`` endpoint."""

    items: list[DailyBarResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=1000)
    offset: int = Field(ge=0)


__all__ = [
    "DailyBarListResponse",
    "DailyBarResponse",
    "InstrumentListResponse",
    "InstrumentResponse",
]
