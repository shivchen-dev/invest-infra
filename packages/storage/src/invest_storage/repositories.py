from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from invest_domain.instruments import Instrument, InstrumentType
from invest_storage.models import InstrumentRow


class SqlAlchemyInstrumentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, instruments: Sequence[Instrument]) -> int:
        if not instruments:
            return 0
        values = [
            {
                "symbol": item.symbol,
                "name": item.name,
                "exchange": item.exchange,
                "instrument_type": item.instrument_type.value,
                "is_active": item.is_active,
            }
            for item in instruments
        ]
        statement = insert(InstrumentRow).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[InstrumentRow.symbol],
            set_={
                "name": statement.excluded.name,
                "exchange": statement.excluded.exchange,
                "instrument_type": statement.excluded.instrument_type,
                "is_active": statement.excluded.is_active,
            },
        )
        self._session.execute(statement)
        return len(values)

    def list_active(self, *, limit: int = 100, offset: int = 0) -> Sequence[Instrument]:
        rows = self._session.scalars(
            select(InstrumentRow)
            .where(InstrumentRow.is_active.is_(True))
            .order_by(InstrumentRow.symbol)
            .limit(limit)
            .offset(offset)
        ).all()
        return [
            Instrument(
                symbol=row.symbol,
                name=row.name,
                exchange=row.exchange,
                instrument_type=InstrumentType(row.instrument_type),
                is_active=row.is_active,
            )
            for row in rows
        ]
