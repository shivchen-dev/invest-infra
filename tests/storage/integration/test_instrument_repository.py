"""Integration tests for :class:`SqlAlchemyInstrumentRepository`.

Each test runs inside the savepoint-isolated session fixture defined in
``tests/storage/conftest.py``. The fixtures handle starting a disposable
PostgreSQL container via Testcontainers and rolling back every change
after the test, so the tests can share a single container without
leaking data between cases.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from invest_domain.instruments import (
    Instrument,
    InstrumentId,
    InstrumentType,
)
from invest_domain.shared.values import Currency
from invest_storage import SqlAlchemyInstrumentRepository
from sqlalchemy import text
from sqlalchemy.orm import Session


def _make_instrument(
    *,
    symbol: str = "510050",
    exchange: str = "SSE",
    name: str = "SSE 50 ETF",
    instrument_type: InstrumentType = InstrumentType.ETF,
    instrument_id: InstrumentId | None = None,
    is_active: bool = True,
) -> Instrument:
    return Instrument(
        symbol=symbol,
        name=name,
        exchange=exchange,
        instrument_type=instrument_type,
        is_active=is_active,
        instrument_id=instrument_id,
        currency=Currency.CNY,
    )


def test_upsert_instrument_new(repository: SqlAlchemyInstrumentRepository) -> None:
    instrument = _make_instrument(symbol="510050", name="SSE 50 ETF")
    assert instrument.instrument_id is None

    inserted = repository.upsert_many([instrument])
    assert inserted == 1

    found = repository.get_by_business_key(exchange="SSE", symbol="510050")
    assert found is not None
    assert found.symbol == "510050"
    assert found.exchange == "SSE"
    assert found.instrument_type is InstrumentType.ETF
    assert found.instrument_id is not None
    assert isinstance(found.instrument_id.value, uuid.UUID)
    assert found.instrument_id.value != uuid.UUID(int=0)
    assert found.name == "SSE 50 ETF"
    assert found.currency is Currency.CNY
    assert found.is_active is True


def test_upsert_instrument_existing_returns_same_id(
    repository: SqlAlchemyInstrumentRepository,
) -> None:
    first = _make_instrument(symbol="510050", exchange="SSE", name="SSE 50 ETF v1")
    repository.upsert_many([first])

    first_read = repository.get_by_business_key(exchange="SSE", symbol="510050")
    assert first_read is not None
    original_id = first_read.instrument_id
    assert original_id is not None
    assert first_read.name == "SSE 50 ETF v1"

    second = _make_instrument(symbol="510050", exchange="SSE", name="SSE 50 ETF v2")
    assert second.instrument_id is None
    repository.upsert_many([second])

    second_read = repository.get_by_business_key(exchange="SSE", symbol="510050")
    assert second_read is not None
    assert second_read.instrument_id is not None
    assert second_read.instrument_id.value == original_id.value
    assert second_read.name == "SSE 50 ETF v2"


def test_upsert_many_with_explicit_id_round_trips(
    repository: SqlAlchemyInstrumentRepository,
) -> None:
    explicit_id = InstrumentId.generate()
    instrument = _make_instrument(
        symbol="510300", name="CSI 300 ETF", instrument_id=explicit_id
    )

    repository.upsert_many([instrument])

    found = repository.get_by_id(explicit_id)
    assert found is not None
    assert found.instrument_id == explicit_id

    updated = _make_instrument(
        symbol="510300", name="CSI 300 ETF (renamed)", instrument_id=explicit_id
    )
    repository.upsert_many([updated])

    reread = repository.get_by_id(explicit_id)
    assert reread is not None
    assert reread.name == "CSI 300 ETF (renamed)"
    assert reread.instrument_id == explicit_id


def test_get_by_business_key_returns_none_when_missing(
    repository: SqlAlchemyInstrumentRepository,
) -> None:
    assert repository.get_by_business_key(exchange="SSE", symbol="DOES_NOT_EXIST") is None


def test_get_by_id_returns_none_when_missing(
    repository: SqlAlchemyInstrumentRepository,
) -> None:
    missing = InstrumentId.generate()
    assert repository.get_by_id(missing) is None


def test_list_active_instruments_pagination(
    repository: SqlAlchemyInstrumentRepository,
) -> None:
    instruments: list[Instrument] = [
        _make_instrument(symbol=f"51{i:04d}", name=f"Instrument {i}") for i in range(12)
    ]
    repository.upsert_many(instruments)
    assert repository.count_active() == 12

    first_page: Sequence[Instrument] = repository.list_active(limit=5, offset=0)
    second_page: Sequence[Instrument] = repository.list_active(limit=5, offset=5)
    third_page: Sequence[Instrument] = repository.list_active(limit=5, offset=10)

    assert [item.symbol for item in first_page] == [
        "510000",
        "510001",
        "510002",
        "510003",
        "510004",
    ]
    assert [item.symbol for item in second_page] == [
        "510005",
        "510006",
        "510007",
        "510008",
        "510009",
    ]
    assert [item.symbol for item in third_page] == ["510010", "510011"]

    all_pages = list(first_page) + list(second_page) + list(third_page)
    assert len(all_pages) == 12
    symbols = [item.symbol for item in all_pages]
    assert len(symbols) == len(set(symbols)), "pagination must not repeat rows"

    empty_page = repository.list_active(limit=5, offset=1000)
    assert list(empty_page) == []


def test_list_active_filters_inactive_instruments(
    repository: SqlAlchemyInstrumentRepository,
) -> None:
    active = _make_instrument(symbol="510050", name="Active ETF", is_active=True)
    inactive = _make_instrument(symbol="510051", name="Inactive ETF", is_active=False)
    repository.upsert_many([active, inactive])

    rows = repository.list_active()
    symbols = [row.symbol for row in rows]
    assert "510050" in symbols
    assert "510051" not in symbols


def test_upsert_many_empty_returns_zero(repository: SqlAlchemyInstrumentRepository) -> None:
    assert repository.upsert_many([]) == 0


def test_upsert_mixed_with_and_without_id(
    repository: SqlAlchemyInstrumentRepository,
    db_session: Session,
) -> None:
    explicit = InstrumentId.generate()
    repository.upsert_many(
        [
            _make_instrument(symbol="510050", name="Auto-id", instrument_id=None),
            _make_instrument(symbol="510300", name="Explicit-id", instrument_id=explicit),
        ]
    )

    auto = repository.get_by_business_key(exchange="SSE", symbol="510050")
    explicit_row = repository.get_by_business_key(exchange="SSE", symbol="510300")

    assert auto is not None and auto.instrument_id is not None
    assert explicit_row is not None and explicit_row.instrument_id == explicit

    total = db_session.execute(
        text("SELECT COUNT(*) FROM core.instruments")
    ).scalar_one()
    assert total == 2