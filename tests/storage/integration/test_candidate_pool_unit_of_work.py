"""Integration tests for the candidate-pool UnitOfWork wiring.

Verifies that ``uow.candidate_pool_runs`` and ``uow.candidate_pool_items``
expose the same SQLAlchemy session as the rest of the UoW's repositories
so a single transactional boundary wraps every write.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from invest_domain.candidate_pool.models import (
    CandidatePoolItem,
    CandidatePoolRun,
    CandidatePoolStatus,
)
from invest_domain.instruments import Instrument, InstrumentId, InstrumentType
from invest_storage import (
    SqlAlchemyCandidatePoolItemRepository,
    SqlAlchemyCandidatePoolRunRepository,
)
from sqlalchemy import text
from sqlalchemy.orm import Session


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def _new_calculated_run() -> CandidatePoolRun:
    return CandidatePoolRun(
        id=uuid4(),
        trade_date=date(2026, 7, 31),
        algorithm_key="candidate_pool.v1",
        algorithm_version="v1.0",
        parameter_set_key="default",
        parameter_hash="a" * 64,
        input_snapshot_id=uuid4(),
        input_row_count=2,
        included_count=1,
        status=CandidatePoolStatus.CALCULATED,
        created_at=_utc(2026, 7, 31, 9),
    )


def test_uow_exposes_candidate_pool_repositories(uow_factory) -> None:
    """The UoW exposes both candidate-pool repositories as cached properties."""

    with uow_factory() as uow:
        assert isinstance(
            uow.candidate_pool_runs, SqlAlchemyCandidatePoolRunRepository
        )
        assert isinstance(
            uow.candidate_pool_items, SqlAlchemyCandidatePoolItemRepository
        )
        # Cached for the lifetime of the UoW
        assert uow.candidate_pool_runs is uow.candidate_pool_runs
        assert uow.candidate_pool_items is uow.candidate_pool_items


def test_uow_candidate_pool_repositories_share_session(uow_factory) -> None:
    """All repositories wired to the UoW operate on the same session."""

    with uow_factory() as uow:
        assert uow.candidate_pool_runs._session is uow.session  # noqa: SLF001
        assert uow.candidate_pool_items._session is uow.session  # noqa: SLF001
        assert uow.instruments._session is uow.session  # noqa: SLF001


def test_uow_candidate_pool_round_trip_persists(
    uow_factory, session_factory_fixture
) -> None:
    """Writing through the UoW persists the run + items end-to-end."""

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

    with session_factory_fixture() as lookup_session:
        instrument_uuid = lookup_session.execute(
            text("SELECT id FROM core.instruments WHERE symbol = '510050'")
        ).scalar_one()

    run = _new_calculated_run()
    items = (
        CandidatePoolItem(
            instrument_id=InstrumentId(instrument_uuid),
            included=True,
            rank=1,
            total_score=Decimal("0.5"),
            metrics={"liquidity": Decimal("1.5")},
        ),
    )

    with uow_factory() as uow:
        persisted_run = uow.candidate_pool_runs.add(run)
        inserted = uow.candidate_pool_items.bulk_add(persisted_run.id, items)
        uow.commit()

    assert inserted == 1

    with session_factory_fixture() as verify_session:
        run_count = verify_session.execute(
            text("SELECT COUNT(*) FROM analytics.candidate_pool_runs")
        ).scalar_one()
        item_count = verify_session.execute(
            text("SELECT COUNT(*) FROM analytics.candidate_pool_items")
        ).scalar_one()
    assert run_count == 1
    assert item_count == 1


def test_uow_candidate_pool_rollback_discards(
    uow_factory, session_factory_fixture
) -> None:
    """Rolling back the UoW drops every candidate-pool write."""

    run = _new_calculated_run()

    class _BoomError(RuntimeError):
        pass

    with pytest.raises(_BoomError), uow_factory() as uow:
        uow.candidate_pool_runs.add(run)
        assert uow.candidate_pool_runs.get_by_id(run.id) is not None
        raise _BoomError("simulated failure inside UoW")

    with session_factory_fixture() as verify_session:
        count = verify_session.execute(
            text("SELECT COUNT(*) FROM analytics.candidate_pool_runs")
        ).scalar_one()
    assert count == 0


def test_uow_candidate_pool_status_transitions(
    uow_factory, session_factory_fixture
) -> None:
    """State-machine transitions committed via the UoW are visible across sessions."""

    run = _new_calculated_run()

    with uow_factory() as uow:
        uow.candidate_pool_runs.add(run)
        uow.commit()

    with uow_factory() as uow:
        validated = uow.candidate_pool_runs.transition_status(
            run.id,
            CandidatePoolStatus.VALIDATED,
            at=_utc(2026, 7, 31, 10),
        )
        assert validated.status == CandidatePoolStatus.VALIDATED
        uow.commit()

    with session_factory_fixture() as verify_session:
        status = verify_session.execute(
            text(
                "SELECT status FROM analytics.candidate_pool_runs WHERE id = :id"
            ),
            {"id": str(run.id)},
        ).scalar_one()
    assert status == "validated"


if __name__ == "__main__":
    import unittest

    unittest.main()