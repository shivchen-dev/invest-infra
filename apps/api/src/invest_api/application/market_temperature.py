from __future__ import annotations

from typing import Protocol

from invest_domain.analytics.market_observations import MarketObservationSnapshot
from sqlalchemy.exc import SQLAlchemyError


class MarketTemperatureReader(Protocol):
    def get_latest(self) -> MarketObservationSnapshot | None: ...


class MarketTemperatureQueryError(RuntimeError):
    pass


class MarketTemperatureQueryService:
    def __init__(self, reader: MarketTemperatureReader) -> None:
        self._reader = reader

    def get_latest(self) -> MarketObservationSnapshot | None:
        try:
            return self._reader.get_latest()
        except SQLAlchemyError as exc:
            raise MarketTemperatureQueryError("market temperature query failed") from exc
