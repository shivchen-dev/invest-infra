"""PostgreSQL integration tests for :class:`SqlAlchemyStockPriceLimitRepository`.

Stage 4C Phase 1 Task 1.3 wires the
:class:`invest_storage.repositories.SqlAlchemyStockPriceLimitRepository`
into the Unit-of-Work. These tests verify the repository's revision
semantics survive the round-trip through the real database:

- Insert revision 1 with a valid ``core.instruments`` parent and a
  three-layer ``raw.provider_requests`` -> ``raw.provider_attempts`` ->
  ``raw.provider_batches`` FK chain; the row's
  ``(instrument_id, source_batch_id)`` references must resolve.
- A second ``upsert_many`` with the identical ``row_hash`` MUST be a
  no-op (the audit row in ``raw.provider_batches`` is updated by the
  caller, but ``core.stock_price_limits`` is left untouched).
- A third ``upsert_many`` whose ``row_hash`` differs MUST allocate
  ``revision = latest + 1`` so both revisions coexist.
- ``get_latest`` / ``get_exact`` / ``list_by_instrument_and_range``
  read back the persisted business content deterministically.

The Testcontainers PostgreSQL container, schema bootstrap and
savepoint-isolated ``db_session`` fixture are inherited from
``tests/storage/conftest.py`` and ``tests/storage/integration/conftest.py``;
the ``uow_factory`` fixture from the parent conftest provides a
``SqlAlchemyUnitOfWork`` whose ``stock_price_limits`` property resolves
to the same repository class so the round-trip is exercised through
the production code path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from invest_domain.instruments import Instrument, InstrumentType
from invest_storage import (
    NewPriceLimit,
    NewProviderAttempt,
    NewProviderBatch,
    NewProviderRequest,
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
    SqlAlchemyStockPriceLimitRepository,
    SqlAlchemyUnitOfWork,
    StoredPriceLimit,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

_TRADE_DATE = date(2026, 8, 12)
_OBSERVED_AT = datetime(2026, 8, 12, 8, 0, 0, tzinfo=UTC)
_REGIME_ID = "tushare.v1.normal"
_SOURCE_PROVIDER = "fixture_dev"

_ROW_HASH_V1 = "1" * 64
_ROW_HASH_V2 = "2" * 64

_INSTRUMENT_SYMBOL = "600000"
_INSTRUMENT_EXCHANGE = "SSE"


def _insert_instrument(db_session: Session, *, symbol: str) -> uuid.UUID:
    """Insert a minimal ``core.instruments`` row the limit can reference."""

    inserted = db_session.execute(
        text(
            "INSERT INTO core.instruments (id, symbol, exchange, name, "
            "instrument_type, currency, status, is_active, created_at, "
            "updated_at) VALUES (gen_random_uuid(), :symbol, :exchange, "
            ":symbol, 'STOCK', 'CNY', 'active', true, now(), now()) "
            "RETURNING id"
        ),
        {"symbol": symbol, "exchange": _INSTRUMENT_EXCHANGE},
    ).scalar_one()
    db_session.flush()
    return inserted


def _make_request(*, request_key: str) -> NewProviderRequest:
    return NewProviderRequest(
        provider_key=_SOURCE_PROVIDER,
        dataset_key="stock_price_limits",
        request_key=request_key,
        request_params={"trade_date": _TRADE_DATE.isoformat()},
        status="pending",
    )


def _build_audit_chain(
    request_repo: SqlAlchemyProviderRequestRepository,
    attempt_repo: SqlAlchemyProviderAttemptRepository,
    batch_repo: SqlAlchemyProviderBatchRepository,
    *,
    request_key: str,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Persist the PR-02 three-layer evidence triple the limits FK to.

    Returns ``(request_id, attempt_id, batch_id)``.
    """

    stored_request = request_repo.add(_make_request(request_key=request_key))

    started = datetime(2026, 8, 12, 7, 59, 55, tzinfo=UTC)
    finished = datetime(2026, 8, 12, 8, 0, 5, tzinfo=UTC)
    stored_attempt = attempt_repo.add(
        NewProviderAttempt(
            provider_request_id=stored_request.id,
            attempt_no=1,
            started_at=started,
            finished_at=finished,
            status="succeeded",
            response_payload_sha256="a" * 64,
            http_status=200,
        )
    )

    stored_batch = batch_repo.add(
        NewProviderBatch(
            provider_request_id=stored_request.id,
            provider_attempt_id=stored_attempt.id,
            provider_key=_SOURCE_PROVIDER,
            dataset_key="stock_price_limits",
            record_count=1,
            payload_sha256="a" * 64,
            status="succeeded",
            warnings=[],
        )
    )
    request_repo.mark_status(
        stored_request.id, status="succeeded", completed_at=finished
    )
    return stored_request.id, stored_attempt.id, stored_batch.id


@pytest.fixture()
def instrument_id(db_session: Session) -> uuid.UUID:
    return _insert_instrument(db_session, symbol=_INSTRUMENT_SYMBOL)


@pytest.fixture()
def audit_chain(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    return _build_audit_chain(
        request_repository,
        attempt_repository,
        batch_repository,
        request_key="rt-price-limits-v1",
    )


@pytest.fixture()
def price_limit_repository(db_session: Session) -> SqlAlchemyStockPriceLimitRepository:
    return SqlAlchemyStockPriceLimitRepository(db_session)


def _make_limit(
    *,
    instrument_id: uuid.UUID,
    source_batch_id: uuid.UUID,
    trade_date: date = _TRADE_DATE,
    row_hash: str = _ROW_HASH_V1,
    limit_up: Decimal | None = Decimal("11.50"),
    limit_down: Decimal | None = Decimal("9.50"),
    status: str = "known",
    observed_at: datetime = _OBSERVED_AT,
) -> NewPriceLimit:
    return NewPriceLimit(
        instrument_id=instrument_id,
        trade_date=trade_date,
        regime_id=_REGIME_ID,
        limit_up_price=limit_up,
        limit_down_price=limit_down,
        status=status,
        reference_price=Decimal("10.50"),
        source_provider=_SOURCE_PROVIDER,
        source_batch_id=source_batch_id,
        observed_at=observed_at,
        row_hash=row_hash,
    )


# ---------------------------------------------------------------------------
# Repository-direct round-trip (uses db_session / repository fixtures).
# ---------------------------------------------------------------------------


def test_upsert_inserts_revision_one_with_full_fk_chain(
    price_limit_repository: SqlAlchemyStockPriceLimitRepository,
    instrument_id: uuid.UUID,
    audit_chain: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """A first insert against an empty logical key persists revision 1."""

    _request_id, _attempt_id, batch_id = audit_chain

    written = price_limit_repository.upsert_many(
        [_make_limit(instrument_id=instrument_id, source_batch_id=batch_id)]
    )

    assert len(written) == 1
    stored = written[0]
    assert isinstance(stored, StoredPriceLimit)
    assert stored.instrument_id == instrument_id
    assert stored.trade_date == _TRADE_DATE
    assert stored.revision == 1
    assert stored.row_hash == _ROW_HASH_V1
    assert stored.regime_id == _REGIME_ID
    assert stored.limit_up_price == Decimal("11.50")
    assert stored.limit_down_price == Decimal("9.50")
    assert stored.status == "known"
    assert stored.reference_price == Decimal("10.50")
    assert stored.source_provider == _SOURCE_PROVIDER
    assert stored.source_batch_id == batch_id
    assert stored.observed_at == _OBSERVED_AT
    assert stored.created_at is not None


def test_upsert_is_noop_when_row_hash_matches_latest(
    price_limit_repository: SqlAlchemyStockPriceLimitRepository,
    instrument_id: uuid.UUID,
    audit_chain: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    db_session: Session,
) -> None:
    """A re-collect carrying the same business content MUST NOT advance revision."""

    _request_id, _attempt_id, batch_id = audit_chain

    first = price_limit_repository.upsert_many(
        [_make_limit(instrument_id=instrument_id, source_batch_id=batch_id)]
    )
    assert first and first[0].revision == 1

    before = db_session.execute(
        text(
            "SELECT COUNT(*) FROM core.stock_price_limits "
            "WHERE instrument_id = :iid AND trade_date = :td"
        ),
        {"iid": str(instrument_id), "td": _TRADE_DATE.isoformat()},
    ).scalar_one()

    second = price_limit_repository.upsert_many(
        [_make_limit(instrument_id=instrument_id, source_batch_id=batch_id)]
    )
    assert second == [], "identical row_hash MUST be a no-op at the core layer"

    after = db_session.execute(
        text(
            "SELECT COUNT(*) FROM core.stock_price_limits "
            "WHERE instrument_id = :iid AND trade_date = :td"
        ),
        {"iid": str(instrument_id), "td": _TRADE_DATE.isoformat()},
    ).scalar_one()
    assert after == before

    latest = price_limit_repository.get_latest(
        instrument_id=instrument_id, trade_date=_TRADE_DATE
    )
    assert latest is not None
    assert latest.revision == 1
    assert latest.row_hash == _ROW_HASH_V1


def test_upsert_advances_revision_when_row_hash_changes(
    price_limit_repository: SqlAlchemyStockPriceLimitRepository,
    instrument_id: uuid.UUID,
    audit_chain: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    db_session: Session,
) -> None:
    """A re-collect with changed business content MUST allocate revision 2."""

    _request_id, _attempt_id, batch_id = audit_chain

    first = price_limit_repository.upsert_many(
        [_make_limit(instrument_id=instrument_id, source_batch_id=batch_id)]
    )
    assert first and first[0].revision == 1

    second = price_limit_repository.upsert_many(
        [_make_limit(
            instrument_id=instrument_id,
            source_batch_id=batch_id,
            row_hash=_ROW_HASH_V2,
            limit_up=Decimal("11.40"),
            limit_down=Decimal("9.60"),
        )]
    )
    assert len(second) == 1
    assert second[0].revision == 2
    assert second[0].row_hash == _ROW_HASH_V2
    assert second[0].limit_up_price == Decimal("11.40")
    assert second[0].limit_down_price == Decimal("9.60")

    revisions = db_session.execute(
        text(
            "SELECT revision FROM core.stock_price_limits "
            "WHERE instrument_id = :iid AND trade_date = :td "
            "ORDER BY revision ASC"
        ),
        {"iid": str(instrument_id), "td": _TRADE_DATE.isoformat()},
    ).scalars().all()
    assert revisions == [1, 2], "both revisions MUST coexist for the logical key"


# ---------------------------------------------------------------------------
# Read surface (uses db_session / repository fixtures).
# ---------------------------------------------------------------------------


def test_get_latest_returns_highest_revision(
    price_limit_repository: SqlAlchemyStockPriceLimitRepository,
    instrument_id: uuid.UUID,
    audit_chain: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """``get_latest`` MUST return the row with the highest revision."""

    _request_id, _attempt_id, batch_id = audit_chain

    price_limit_repository.upsert_many(
        [_make_limit(instrument_id=instrument_id, source_batch_id=batch_id)]
    )
    price_limit_repository.upsert_many(
        [_make_limit(
            instrument_id=instrument_id,
            source_batch_id=batch_id,
            row_hash=_ROW_HASH_V2,
            limit_up=Decimal("11.40"),
        )]
    )

    latest = price_limit_repository.get_latest(
        instrument_id=instrument_id, trade_date=_TRADE_DATE
    )
    assert latest is not None
    assert latest.revision == 2
    assert latest.row_hash == _ROW_HASH_V2
    assert latest.limit_up_price == Decimal("11.40")


def test_get_exact_pins_revision(
    price_limit_repository: SqlAlchemyStockPriceLimitRepository,
    instrument_id: uuid.UUID,
    audit_chain: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """``get_exact`` MUST return the row at the requested revision."""

    _request_id, _attempt_id, batch_id = audit_chain

    price_limit_repository.upsert_many(
        [_make_limit(instrument_id=instrument_id, source_batch_id=batch_id)]
    )
    price_limit_repository.upsert_many(
        [_make_limit(
            instrument_id=instrument_id,
            source_batch_id=batch_id,
            row_hash=_ROW_HASH_V2,
        )]
    )

    first = price_limit_repository.get_exact(
        instrument_id=instrument_id, trade_date=_TRADE_DATE, revision=1
    )
    second = price_limit_repository.get_exact(
        instrument_id=instrument_id, trade_date=_TRADE_DATE, revision=2
    )
    assert first is not None and first.revision == 1
    assert first.row_hash == _ROW_HASH_V1
    assert second is not None and second.revision == 2
    assert second.row_hash == _ROW_HASH_V2


def test_list_by_instrument_and_range_returns_all_revisions_in_order(
    price_limit_repository: SqlAlchemyStockPriceLimitRepository,
    instrument_id: uuid.UUID,
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
    batch_repository: SqlAlchemyProviderBatchRepository,
    audit_chain: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """``list_by_instrument_and_range`` MUST enumerate every revision per day."""

    _request_id, _attempt_id, first_batch_id = audit_chain

    earlier_trade_date = date(2026, 8, 11)
    earlier_observed = datetime(2026, 8, 11, 8, 0, 0, tzinfo=UTC)
    _, _, earlier_batch_id = _build_audit_chain(
        request_repository,
        attempt_repository,
        batch_repository,
        request_key="rt-price-limits-earlier",
    )

    price_limit_repository.upsert_many(
        [_make_limit(
            instrument_id=instrument_id,
            source_batch_id=earlier_batch_id,
            trade_date=earlier_trade_date,
            observed_at=earlier_observed,
            row_hash="a" * 64,
        )]
    )
    price_limit_repository.upsert_many(
        [_make_limit(
            instrument_id=instrument_id,
            source_batch_id=earlier_batch_id,
            trade_date=earlier_trade_date,
            observed_at=earlier_observed,
            row_hash="b" * 64,
            limit_up=Decimal("11.40"),
        )]
    )
    price_limit_repository.upsert_many(
        [_make_limit(instrument_id=instrument_id, source_batch_id=first_batch_id)]
    )

    listed = price_limit_repository.list_by_instrument_and_range(
        instrument_id=instrument_id,
        start_date=earlier_trade_date,
        end_date=_TRADE_DATE,
    )

    assert [(row.trade_date, row.revision) for row in listed] == [
        (earlier_trade_date, 1),
        (earlier_trade_date, 2),
        (_TRADE_DATE, 1),
    ]
    assert all(isinstance(row, StoredPriceLimit) for row in listed)
    assert [row.row_hash for row in listed] == ["a" * 64, "b" * 64, _ROW_HASH_V1]


# ---------------------------------------------------------------------------
# Unit-of-Work surface (uses uow_factory).
# ---------------------------------------------------------------------------


def test_uow_stock_price_limits_round_trip(
    uow_factory,
) -> None:
    """The UoW exposes the repository and round-trips through commit."""

    with uow_factory() as uow:
        _request_id, _attempt_id, batch_id = _build_audit_chain(
            uow.provider_requests,
            uow.provider_attempts,
            uow.provider_batches,
            request_key="uow-price-limits-v1",
        )
        persisted = uow.instruments.upsert_many(
            [
                Instrument(
                    symbol=_INSTRUMENT_SYMBOL,
                    name="浦发银行",
                    exchange=_INSTRUMENT_EXCHANGE,
                    instrument_type=InstrumentType.STOCK,
                    is_active=True,
                )
            ]
        )
        persisted_instrument = uow.instruments.get_by_business_key(
            exchange=_INSTRUMENT_EXCHANGE, symbol=_INSTRUMENT_SYMBOL
        )
        assert persisted and persisted_instrument is not None
        instrument_id = persisted_instrument.instrument_id.value
        assert isinstance(uow, SqlAlchemyUnitOfWork)
        assert isinstance(
            uow.stock_price_limits, SqlAlchemyStockPriceLimitRepository
        )
        first = uow.stock_price_limits.upsert_many(
            [_make_limit(instrument_id=instrument_id, source_batch_id=batch_id)]
        )
        assert first and first[0].revision == 1

        second = uow.stock_price_limits.upsert_many(
            [_make_limit(
                instrument_id=instrument_id,
                source_batch_id=batch_id,
                row_hash=_ROW_HASH_V2,
                limit_up=Decimal("11.40"),
            )]
        )
        assert second and second[0].revision == 2

        latest = uow.stock_price_limits.get_latest(
            instrument_id=instrument_id, trade_date=_TRADE_DATE
        )
        assert latest is not None and latest.revision == 2

        exact_v1 = uow.stock_price_limits.get_exact(
            instrument_id=instrument_id,
            trade_date=_TRADE_DATE,
            revision=1,
        )
        assert exact_v1 is not None and exact_v1.row_hash == _ROW_HASH_V1

        rows = uow.stock_price_limits.list_by_instrument_and_range(
            instrument_id=instrument_id,
            start_date=_TRADE_DATE,
            end_date=_TRADE_DATE,
        )
        assert [row.revision for row in rows] == [1, 2]

        uow.commit()
