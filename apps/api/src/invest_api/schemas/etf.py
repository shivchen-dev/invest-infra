"""Pydantic response schemas for the ``/api/v1/etf`` read-only endpoints.

The shapes mirror the storage/domain objects returned by the
``SqlAlchemyInstrumentRepository`` and ``SqlAlchemyDailyBarRepository``.
The M1 API is intentionally read-only; therefore no request bodies are
defined here - every input is a query parameter on the endpoint itself.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Self
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from invest_domain.instruments import Instrument


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

    @classmethod
    def from_instrument(cls, instrument: Instrument) -> Self:
        return cls(
            id=(
                instrument.instrument_id.value
                if instrument.instrument_id is not None
                else UUID(int=0)
            ),
            symbol=instrument.symbol,
            name=instrument.name,
            exchange=instrument.exchange,
            instrument_type=instrument.instrument_type.value,
            currency=instrument.currency.value,
            status=instrument.status.value,
            is_active=instrument.is_active,
            list_date=instrument.list_date,
            delist_date=instrument.delist_date,
            underlying_index=instrument.underlying_index,
            category=instrument.category,
        )


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
