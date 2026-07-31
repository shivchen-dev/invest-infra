"""Integration tests for :class:`SqlAlchemyUnitOfWork`.

The fixture (``uow_factory``) hands out a fresh ``SqlAlchemyUnitOfWork``
backed by the disposable Testcontainers PostgreSQL. Each test owns its
own UoW; the savepoint isolation pattern in the ``db_session`` fixture
is reused here so ``commit()`` / ``rollback()`` exercise the UoW's own
transaction boundaries rather than leaking across tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from invest_storage import (
    NewProviderAttempt,
    NewProviderBatch,
    NewProviderRequest,
    SqlAlchemyUnitOfWork,
)
from invest_storage.models import InstrumentRow
from invest_storage.repositories import SqlAlchemyInstrumentRepository
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def test_uow_commit_persists_changes(
    uow_factory, session_factory_fixture, engine
) -> None:
    from invest_domain.instruments import Instrument, InstrumentType

    instrument = Instrument(
        symbol="510050",
        name="SSE 50 ETF",
        exchange="SSE",
        instrument_type=InstrumentType.ETF,
        is_active=True,
    )

    with uow_factory() as uow:
        uow.instruments.upsert_many([instrument])
        uow.commit()

    with session_factory_fixture() as verify_session:
        count = verify_session.execute(
            text("SELECT COUNT(*) FROM core.instruments WHERE symbol = :symbol"),
            {"symbol": "510050"},
        ).scalar_one()
        assert count == 1

    with engine.connect() as connection:
        persisted = connection.execute(
            text(
                "SELECT symbol, exchange FROM core.instruments WHERE symbol = :symbol"
            ),
            {"symbol": "510050"},
        ).mappings().one()
    assert persisted["symbol"] == "510050"
    assert persisted["exchange"] == "SSE"


def test_uow_rollback_discards_changes(uow_factory, session_factory_fixture) -> None:
    from invest_domain.instruments import Instrument, InstrumentType

    with uow_factory() as uow:
        uow.instruments.upsert_many(
            [
                Instrument(
                    symbol="510050",
                    name="Should not persist",
                    exchange="SSE",
                    instrument_type=InstrumentType.ETF,
                    is_active=True,
                )
            ]
        )
        assert uow.instruments.count_active() == 1
        uow.rollback()

    with session_factory_fixture() as verify_session:
        count = verify_session.execute(text("SELECT COUNT(*) FROM core.instruments")).scalar_one()
        assert count == 0


def test_uow_exception_triggers_rollback(
    uow_factory, session_factory_fixture
) -> None:
    from invest_domain.instruments import Instrument, InstrumentType

    class _BoomError(RuntimeError):
        pass

    with pytest.raises(_BoomError), uow_factory() as uow:
        uow.instruments.upsert_many(
            [
                Instrument(
                    symbol="510050",
                    name="Should not persist",
                    exchange="SSE",
                    instrument_type=InstrumentType.ETF,
                    is_active=True,
                )
            ]
        )
        assert uow.instruments.count_active() == 1
        raise _BoomError("simulated failure inside UoW")

    with session_factory_fixture() as verify_session:
        count = verify_session.execute(
            text("SELECT COUNT(*) FROM core.instruments")
        ).scalar_one()
        assert count == 0


def test_uow_context_manager_closes_session(uow_factory) -> None:
    with uow_factory() as uow:
        assert isinstance(uow, SqlAlchemyUnitOfWork)
        assert uow.closed is False
        assert isinstance(uow.instruments, SqlAlchemyInstrumentRepository)
        session_ref = uow.session
        assert isinstance(session_ref, Session)

    assert uow.closed is True
    with pytest.raises(RuntimeError, match="outside of 'with' block"):
        _ = uow.session


def test_uow_provides_both_repositories(uow_factory) -> None:
    from invest_storage.repositories import SqlAlchemyProviderBatchRepository

    with uow_factory() as uow:
        assert isinstance(uow.instruments, SqlAlchemyInstrumentRepository)
        assert isinstance(uow.provider_batches, SqlAlchemyProviderBatchRepository)
        assert uow.instruments is uow.instruments
        assert uow.provider_batches is uow.provider_batches


def test_uow_commit_failure_rolls_back(uow_factory, session_factory_fixture) -> None:
    """A ``commit()`` that raises must still release the session.

    The plan asserts that ``commit`` / ``rollback`` mirror the
    underlying ``Session`` behaviour. We force a failure by inserting
    two provider requests with the same logical key in the same UoW;
    PostgreSQL rejects the second insert with ``UniqueViolationError``
    on ``uq_provider_requests_logical_key``, which propagates from
    ``commit()`` -> ``__exit__`` -> rollback.
    """

    base = NewProviderRequest(
        provider_key="akshare",
        dataset_key="etf_daily",
        request_key="dup-key",
        status="pending",
        request_params={"foo": "bar"},
    )

    duplicate = NewProviderRequest(
        provider_key="akshare",
        dataset_key="etf_daily",
        request_key="dup-key",
        status="pending",
    )

    with pytest.raises(IntegrityError), uow_factory() as uow:
        uow.provider_requests.add(base)
        uow.provider_requests.add(duplicate)
        uow.commit()

    with session_factory_fixture() as verify_session:
        count = verify_session.execute(
            text("SELECT COUNT(*) FROM raw.provider_requests")
        ).scalar_one()
        assert count == 0


def test_uow_three_layer_persistence_round_trip(
    uow_factory, session_factory_fixture
) -> None:
    """Persisting request → attempt → batch leaves all three rows.

    PR-02 introduced the three-layer evidence model; the UoW must
    expose each repository as a property and the FK chain must round
    trip end-to-end.
    """

    started = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    finished = datetime(2026, 7, 30, 12, 0, 5, tzinfo=UTC)

    with uow_factory() as uow:
        stored_request = uow.provider_requests.add(
            NewProviderRequest(
                provider_key="akshare",
                dataset_key="etf_daily",
                request_key="rt-1",
                status="succeeded",
                request_params={"foo": "bar"},
            )
        )
        stored_attempt = uow.provider_attempts.add(
            NewProviderAttempt(
                provider_request_id=stored_request.id,
                attempt_no=1,
                started_at=started,
                finished_at=finished,
                status="succeeded",
                response_payload_sha256="a" * 64,
            )
        )
        stored_batch = uow.provider_batches.add(
            NewProviderBatch(
                provider_request_id=stored_request.id,
                provider_attempt_id=stored_attempt.id,
                provider_key="akshare",
                dataset_key="etf_daily",
                record_count=2,
                payload_sha256="a" * 64,
                status="succeeded",
            )
        )
        uow.commit()

    with session_factory_fixture() as verify_session:
        row_count = verify_session.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM raw.provider_requests) AS requests, "
                "(SELECT COUNT(*) FROM raw.provider_attempts) AS attempts, "
                "(SELECT COUNT(*) FROM raw.provider_batches) AS batches"
            )
        ).mappings().one()
        assert row_count["requests"] == 1
        assert row_count["attempts"] == 1
        assert row_count["batches"] == 1

    assert stored_batch.provider_request_id == stored_request.id
    assert stored_batch.provider_attempt_id == stored_attempt.id


def test_uow_repositories_share_session(uow_factory) -> None:
    with uow_factory() as uow:
        instrument_session = uow.instruments._session
        batch_session = uow.provider_batches._session
        uow_session = uow.session
        assert instrument_session is uow_session
        assert batch_session is uow_session


def test_uow_raises_when_accessing_session_outside_context(uow_factory) -> None:
    uow = uow_factory()
    with pytest.raises(RuntimeError, match="outside of 'with' block"):
        _ = uow.session


def test_uow_repository_property_returns_same_instance(uow_factory) -> None:
    with uow_factory() as uow:
        first = uow.instruments
        second = uow.instruments
        first_batch = uow.provider_batches
        second_batch = uow.provider_batches
        assert first is second
        assert first_batch is second_batch
        assert first is not first_batch


def test_uow_exit_without_exception_still_closes(
    uow_factory, session_factory_fixture
) -> None:
    """Leaving the ``with`` block cleanly must close the session.

    The session's identity map therefore cannot outlive the block; the
    test below writes through the UoW, exits cleanly, then opens a new
    session and asserts the row is visible (it was committed by
    ``__exit__`` -> ``commit()``).
    """

    from invest_domain.instruments import Instrument, InstrumentType

    with uow_factory() as uow:
        uow.instruments.upsert_many(
            [
                Instrument(
                    symbol="510050",
                    name="Persisted by clean exit",
                    exchange="SSE",
                    instrument_type=InstrumentType.ETF,
                    is_active=True,
                )
            ]
        )

    with session_factory_fixture() as verify_session:
        count = verify_session.execute(
            text("SELECT COUNT(*) FROM core.instruments WHERE symbol = :s"),
            {"s": "510050"},
        ).scalar_one()
        assert count == 1


def test_uow_orm_layer_still_present(uow_factory, db_session: Session) -> None:
    """Sanity check: the ORM model is reachable from the UoW context.

    The plan emphasises Repository -> ORM conversion; this test makes
    sure the ORM layer is in fact wired up end-to-end so the Repository
    has something to talk to.
    """

    from invest_domain.instruments import Instrument, InstrumentType

    with uow_factory() as uow:
        uow.instruments.upsert_many(
            [
                Instrument(
                    symbol="510050",
                    name="Orm check",
                    exchange="SSE",
                    instrument_type=InstrumentType.ETF,
                    is_active=True,
                )
            ]
        )
        uow.commit()

    row = db_session.query(InstrumentRow).filter_by(symbol="510050").one()
    assert row.exchange == "SSE"