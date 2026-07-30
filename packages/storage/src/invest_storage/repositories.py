from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from invest_domain.instruments import (
    Instrument,
    InstrumentId,
    InstrumentStatus,
    InstrumentType,
)
from invest_domain.shared.values import Currency
from invest_storage.models import InstrumentRow


class SqlAlchemyInstrumentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, instruments: Sequence[Instrument]) -> int:
        if not instruments:
            return 0

        with_id: list[Instrument] = []
        without_id: list[Instrument] = []
        for item in instruments:
            if item.instrument_id is None:
                without_id.append(item)
            else:
                with_id.append(item)

        total = 0
        if with_id:
            total += self._upsert_by_id(with_id)
        if without_id:
            total += self._upsert_by_business_key(without_id)
        return total

    def list_active(self, *, limit: int = 100, offset: int = 0) -> Sequence[Instrument]:
        rows = self._session.scalars(
            select(InstrumentRow)
            .where(InstrumentRow.is_active.is_(True))
            .order_by(InstrumentRow.exchange, InstrumentRow.symbol)
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_instrument(row) for row in rows]

    def _upsert_by_id(self, instruments: Sequence[Instrument]) -> int:
        values = [
            {
                "id": item.instrument_id.value,  # type: ignore[union-attr]
                "symbol": item.symbol,
                "exchange": item.exchange,
                "name": item.name,
                "instrument_type": item.instrument_type.value,
                "currency": _currency_value(item.currency),
                "list_date": item.list_date,
                "delist_date": item.delist_date,
                "status": _status_value(item.status),
                "underlying_index": item.underlying_index,
                "category": item.category,
                "provider_symbol_map": _provider_symbol_map(item.provider_symbol_map),
                "valid_from": item.valid_from,
                "valid_to": item.valid_to,
                "is_active": item.is_active,
            }
            for item in instruments
        ]
        statement = insert(InstrumentRow).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[InstrumentRow.id],
            set_=_excluded_set(),
        )
        self._session.execute(statement)
        return len(values)

    def _upsert_by_business_key(self, instruments: Sequence[Instrument]) -> int:
        values = [
            {
                "id": uuid.uuid4(),
                "symbol": item.symbol,
                "exchange": item.exchange,
                "name": item.name,
                "instrument_type": item.instrument_type.value,
                "currency": _currency_value(item.currency),
                "list_date": item.list_date,
                "delist_date": item.delist_date,
                "status": _status_value(item.status),
                "underlying_index": item.underlying_index,
                "category": item.category,
                "provider_symbol_map": _provider_symbol_map(item.provider_symbol_map),
                "valid_from": item.valid_from,
                "valid_to": item.valid_to,
                "is_active": item.is_active,
            }
            for item in instruments
        ]
        statement = insert(InstrumentRow).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[InstrumentRow.symbol, InstrumentRow.exchange],
            index_where=InstrumentRow.delist_date.is_(None),
            set_=_excluded_set(),
        )
        self._session.execute(statement)
        return len(values)


def _excluded_set() -> dict[str, Any]:
    excluded = insert(InstrumentRow).excluded
    return {
        "symbol": excluded.symbol,
        "exchange": excluded.exchange,
        "name": excluded.name,
        "instrument_type": excluded.instrument_type,
        "currency": excluded.currency,
        "list_date": excluded.list_date,
        "delist_date": excluded.delist_date,
        "status": excluded.status,
        "underlying_index": excluded.underlying_index,
        "category": excluded.category,
        "provider_symbol_map": excluded.provider_symbol_map,
        "valid_from": excluded.valid_from,
        "valid_to": excluded.valid_to,
        "is_active": excluded.is_active,
    }


def _row_to_instrument(row: InstrumentRow) -> Instrument:
    return Instrument(
        symbol=row.symbol,
        name=row.name,
        exchange=row.exchange,
        instrument_type=InstrumentType(row.instrument_type),
        is_active=row.is_active,
        instrument_id=InstrumentId(row.id) if row.id is not None else None,
        currency=Currency(row.currency) if row.currency else Currency.CNY,
        list_date=_as_date(row.list_date),
        delist_date=_as_date(row.delist_date),
        status=InstrumentStatus(row.status) if row.status else InstrumentStatus.UNKNOWN,
        underlying_index=row.underlying_index,
        category=row.category,
        provider_symbol_map=dict(row.provider_symbol_map or {}),
        valid_from=_as_date(row.valid_from),
        valid_to=_as_date(row.valid_to),
    )


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    raise TypeError(f"expected date or None, got {type(value).__name__}")


def _currency_value(value: Currency) -> str:
    return value.value if isinstance(value, Currency) else str(value)


def _status_value(value: InstrumentStatus) -> str:
    return value.value if isinstance(value, InstrumentStatus) else str(value)


def _provider_symbol_map(value: dict[str, str] | None) -> dict[str, str]:
    return dict(value) if value else {}
