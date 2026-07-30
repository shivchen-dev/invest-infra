from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class InstrumentType(StrEnum):
    ETF = "ETF"
    STOCK = "STOCK"
    INDEX = "INDEX"


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    name: str
    exchange: str
    instrument_type: InstrumentType
    is_active: bool = True

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.exchange.strip():
            raise ValueError("exchange must not be empty")
