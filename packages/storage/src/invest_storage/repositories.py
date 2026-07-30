"""Repository implementations for the M1 Storage layer.

Each repository owns its ORM-to-domain mapping: callers always receive
domain objects, never SQLAlchemy ORM rows. The two repositories in this
module cover the tables introduced by M1 increments 2 and 3:

- :class:`SqlAlchemyInstrumentRepository` persists the canonical
  ``core.instruments`` rows. The partial unique index on
  ``(symbol, exchange) WHERE delist_date IS NULL`` is the natural
  business-key upsert target.
- :class:`SqlAlchemyProviderBatchRepository` persists the raw evidence
  rows in ``raw.provider_batches``. The unique constraint on
  ``(provider_key, dataset_key, request_key)`` is enforced by the
  database; a second insert with the same triplet raises ``IntegrityError``.

The :class:`StoredProviderBatch` dataclass is the domain-side handle for
a persisted provider batch. It intentionally mirrors
:class:`invest_storage.models.RawProviderBatchRow` but is free of
SQLAlchemy machinery, so application / domain code can pass it around
without importing the storage layer.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from invest_domain.instruments import (
    Instrument,
    InstrumentId,
    InstrumentStatus,
    InstrumentType,
)
from invest_domain.shared.values import Currency
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from invest_storage.models import InstrumentRow, RawProviderBatchRow


@dataclass(frozen=True, slots=True)
class StoredProviderBatch:
    """Domain-side view of a persisted ``raw.provider_batches`` row.

    Field semantics mirror :class:`RawProviderBatchRow` and the M1
    increment 2 migration comments. The dataclass is frozen so it is safe
    to share across threads and to use as a return value from repository
    methods.
    """

    id: UUID
    provider_key: str
    dataset_key: str
    request_key: str
    request_params: dict[str, Any] = field(default_factory=dict)
    requested_at: datetime | None = None
    received_at: datetime | None = None
    provider_request_id: str | None = None
    status: str = "requested"
    record_count: int | None = None
    raw_payload_json: Any | None = None
    raw_payload_uri: str | None = None
    payload_sha256: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    warnings: list[Any] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewProviderBatch:
    """Input shape for :meth:`SqlAlchemyProviderBatchRepository.add`.

    The application layer constructs this dataclass (id, created_at and
    updated_at are server-generated; the repository fills them in).
    """

    provider_key: str
    dataset_key: str
    request_key: str
    requested_at: datetime
    status: str
    request_params: dict[str, Any] = field(default_factory=dict)
    received_at: datetime | None = None
    provider_request_id: str | None = None
    record_count: int | None = None
    raw_payload_json: Any | None = None
    raw_payload_uri: str | None = None
    payload_sha256: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    warnings: list[Any] = field(default_factory=list)


class SqlAlchemyInstrumentRepository:
    """CRUD + UUID upsert for the canonical ``core.instruments`` table.

    The repository is stateless apart from its session: callers obtain a
    fresh repository per UnitOfWork so the session lifetime is owned by
    the UoW (or by the caller of :func:`invest_storage.database.session_scope`).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, instruments: Sequence[Instrument]) -> int:
        """Insert or update a batch of instruments; returns the count.

        Instruments carrying an explicit ``instrument_id`` are upserted by
        primary key (so an explicit re-import can rewrite the row). The
        remainder are upserted by the partial unique business key
        ``(symbol, exchange) WHERE delist_date IS NULL`` - re-imports of
        an existing active instrument keep the original ``id``.
        """

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

    def get_by_id(self, instrument_id: UUID | InstrumentId) -> Instrument | None:
        raw_id = instrument_id.value if isinstance(instrument_id, InstrumentId) else instrument_id
        row = self._session.get(InstrumentRow, raw_id)
        return _row_to_instrument(row) if row is not None else None

    def get_by_business_key(
        self, *, exchange: str, symbol: str
    ) -> Instrument | None:
        """Return the active instrument carrying the given business key.

        Uses the partial unique index on ``(symbol, exchange) WHERE
        delist_date IS NULL``; delisted rows are ignored. Returns
        ``None`` when no active row matches.
        """

        stmt = (
            select(InstrumentRow)
            .where(
                InstrumentRow.symbol == symbol,
                InstrumentRow.exchange == exchange,
                InstrumentRow.delist_date.is_(None),
            )
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_instrument(row) if row is not None else None

    def list_active(self, *, limit: int = 100, offset: int = 0) -> Sequence[Instrument]:
        rows = self._session.scalars(
            select(InstrumentRow)
            .where(InstrumentRow.is_active.is_(True))
            .order_by(InstrumentRow.exchange, InstrumentRow.symbol)
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_instrument(row) for row in rows]

    def count_active(self) -> int:
        stmt = select(InstrumentRow.id).where(InstrumentRow.is_active.is_(True))
        return len(self._session.scalars(stmt).all())

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


class SqlAlchemyProviderBatchRepository:
    """Read/write access to ``raw.provider_batches``.

    The repository does not enforce the ``status`` value set itself - the
    database CHECK constraint and the domain-side validation in the
    application layer are responsible. A duplicate
    ``(provider_key, dataset_key, request_key)`` insert raises
    :class:`sqlalchemy.exc.IntegrityError` from :meth:`add`; callers
    that want idempotency should call :meth:`get_by_request` first or
    handle the error.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, batch: NewProviderBatch) -> StoredProviderBatch:
        row = RawProviderBatchRow(
            id=uuid.uuid4(),
            provider_key=batch.provider_key,
            dataset_key=batch.dataset_key,
            request_key=batch.request_key,
            request_params=dict(batch.request_params),
            requested_at=batch.requested_at,
            received_at=batch.received_at,
            provider_request_id=batch.provider_request_id,
            status=batch.status,
            record_count=batch.record_count,
            raw_payload_json=batch.raw_payload_json,
            raw_payload_uri=batch.raw_payload_uri,
            payload_sha256=batch.payload_sha256,
            error_code=batch.error_code,
            error_message=batch.error_message,
            warnings=list(batch.warnings),
        )
        self._session.add(row)
        self._session.flush()
        return _row_to_stored_batch(row)

    def get_by_id(self, batch_id: UUID) -> StoredProviderBatch | None:
        row = self._session.get(RawProviderBatchRow, batch_id)
        return _row_to_stored_batch(row) if row is not None else None

    def get_by_request(
        self, *, provider_key: str, dataset_key: str, request_key: str
    ) -> StoredProviderBatch | None:
        stmt = (
            select(RawProviderBatchRow)
            .where(
                RawProviderBatchRow.provider_key == provider_key,
                RawProviderBatchRow.dataset_key == dataset_key,
                RawProviderBatchRow.request_key == request_key,
            )
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_stored_batch(row) if row is not None else None

    def list_by_provider_dataset(
        self, *, provider_key: str, dataset_key: str, limit: int = 100, offset: int = 0
    ) -> Sequence[StoredProviderBatch]:
        rows = self._session.scalars(
            select(RawProviderBatchRow)
            .where(
                RawProviderBatchRow.provider_key == provider_key,
                RawProviderBatchRow.dataset_key == dataset_key,
            )
            .order_by(RawProviderBatchRow.requested_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_stored_batch(row) for row in rows]


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


def _row_to_stored_batch(row: RawProviderBatchRow) -> StoredProviderBatch:
    return StoredProviderBatch(
        id=row.id,
        provider_key=row.provider_key,
        dataset_key=row.dataset_key,
        request_key=row.request_key,
        request_params=dict(row.request_params or {}),
        requested_at=row.requested_at,
        received_at=row.received_at,
        provider_request_id=row.provider_request_id,
        status=row.status,
        record_count=row.record_count,
        raw_payload_json=row.raw_payload_json,
        raw_payload_uri=row.raw_payload_uri,
        payload_sha256=row.payload_sha256,
        error_code=row.error_code,
        error_message=row.error_message,
        warnings=list(row.warnings or []),
        created_at=row.created_at,
        updated_at=row.updated_at,
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