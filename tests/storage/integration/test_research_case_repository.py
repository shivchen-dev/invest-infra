"""Focused integration tests for :class:`SqlAlchemyResearchCaseRepository`."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from invest_domain.candidate_pool.models import (
    CandidatePoolRun,
    CandidatePoolStatus,
)
from invest_domain.instruments import Instrument, InstrumentId, InstrumentType
from invest_domain.research import ResearchCase, ResearchCaseStatus
from invest_storage import (
    ResearchCaseTransitionError,
    SqlAlchemyCandidatePoolRunRepository,
    SqlAlchemyResearchCaseRepository,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

CREATED_AT = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
READY_AT = datetime(2026, 8, 7, 10, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 8, 7, 11, 0, tzinfo=UTC)
TEST_INPUT_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000001")


def _insert_instrument(db_session: Session, symbol: str) -> UUID:
    return db_session.execute(
        text(
            "INSERT INTO core.instruments (id, symbol, exchange, name, "
            "instrument_type, currency, status, is_active, created_at, "
            "updated_at) VALUES (gen_random_uuid(), :symbol, 'SSE', :symbol, "
            "'ETF', 'CNY', 'active', true, now(), now()) RETURNING id"
        ),
        {"symbol": symbol},
    ).scalar_one()


@pytest.fixture()
def instrument_a(db_session: Session) -> UUID:
    return _insert_instrument(db_session, "510050")


@pytest.fixture()
def candidate_pool_run(db_session: Session) -> UUID:
    """Real ``CandidatePoolRun`` via the existing repository; the conftest
    seeds ``TEST_INPUT_SNAPSHOT_ID`` so the FK chain is satisfied."""

    return SqlAlchemyCandidatePoolRunRepository(db_session).add(
        CandidatePoolRun(
            id=uuid4(), trade_date=date(2026, 8, 7),
            algorithm_key="candidate_pool.v1", algorithm_version="v1.0",
            parameter_set_key="default", parameter_hash="a" * 64,
            input_snapshot_id=TEST_INPUT_SNAPSHOT_ID,
            input_row_count=1, included_count=0,
            status=CandidatePoolStatus.CALCULATED, created_at=CREATED_AT,
        ),
        quality_summary={"coverage": 0.97},
    ).id


def _draft(
    *,
    instrument_id: UUID,
    case_id: UUID | None = None,
    candidate_pool_run_id: UUID | None = None,
) -> ResearchCase:
    return ResearchCase(
        case_id=case_id or uuid4(),
        instrument_id=InstrumentId(instrument_id),
        as_of_date=date(2026, 8, 7),
        question="Will momentum persist?",
        horizon="20-60d",
        status=ResearchCaseStatus.DRAFT,
        created_at=CREATED_AT,
        closed_at=None,
        candidate_pool_run_id=candidate_pool_run_id,
    )


@pytest.fixture()
def repo(db_session: Session) -> SqlAlchemyResearchCaseRepository:
    return SqlAlchemyResearchCaseRepository(db_session)


def test_add_round_trip_full_payload_and_get(
    repo, instrument_a, candidate_pool_run
):
    case = _draft(instrument_id=instrument_a, candidate_pool_run_id=candidate_pool_run)
    persisted = repo.add(case)

    assert persisted == case
    assert repo.get(case.case_id) == case
    assert persisted.candidate_pool_run_id == candidate_pool_run


def test_add_optional_candidate_pool_run_id_round_trips(repo, instrument_a):
    persisted = repo.add(_draft(instrument_id=instrument_a))

    assert persisted.candidate_pool_run_id is None
    assert persisted.closed_at is None
    assert persisted.status is ResearchCaseStatus.DRAFT


def test_add_duplicate_case_id_raises(repo, instrument_a):
    case = _draft(instrument_id=instrument_a)
    repo.add(case)

    with pytest.raises(IntegrityError):
        repo.add(_draft(instrument_id=instrument_a, case_id=case.case_id))


@pytest.mark.parametrize(
    "instrument_id, candidate_pool_run_id",
    [(uuid4(), None), (None, uuid4())],
    ids=["unknown_instrument_id", "unknown_candidate_pool_run_id"],
)
def test_add_unknown_fk_raises(
    repo, instrument_a, candidate_pool_run, instrument_id, candidate_pool_run_id
):
    with pytest.raises(IntegrityError):
        repo.add(
            _draft(
                instrument_id=instrument_id or instrument_a,
                candidate_pool_run_id=candidate_pool_run_id or candidate_pool_run,
            )
        )


def test_list_by_instrument_orders_by_created_at_then_case_id(repo, instrument_a):
    earlier = _draft(instrument_id=instrument_a)
    later_base = {
        "instrument_id": InstrumentId(instrument_a),
        "as_of_date": date(2026, 8, 7),
        "status": ResearchCaseStatus.DRAFT,
        "created_at": CREATED_AT.replace(hour=10),
        "closed_at": None,
        "candidate_pool_run_id": None,
    }
    earlier_id = uuid4()
    later_id = UUID(int=earlier_id.int - 1)
    tiebreak_id = UUID(int=earlier_id.int + 1)
    later = ResearchCase(case_id=later_id, question="later", horizon="20-60d", **later_base)
    tiebreak = ResearchCase(case_id=tiebreak_id, question="tie", horizon="20-60d", **later_base)
    repo.add(later)
    repo.add(earlier)
    repo.add(tiebreak)

    assert [c.case_id for c in repo.list_by_instrument(instrument_a)] == [
        earlier.case_id,
        later_id,
        tiebreak_id,
    ]


def test_save_transition_terminal_lifecycle(repo, instrument_a):
    case = _draft(instrument_id=instrument_a)
    repo.add(case)
    for previous, target, at in (
        (ResearchCaseStatus.DRAFT, ResearchCaseStatus.READY, READY_AT),
        (ResearchCaseStatus.READY, ResearchCaseStatus.RUNNING, READY_AT),
        (ResearchCaseStatus.RUNNING, ResearchCaseStatus.COMPLETED, COMPLETED_AT),
    ):
        case = case.transition(target, occurred_at=at)
        repo.save_transition(previous, case)

    persisted = repo.get(case.case_id)
    assert persisted.status is ResearchCaseStatus.COMPLETED
    assert persisted.closed_at == COMPLETED_AT


def test_save_transition_stale_previous_status_raises(repo, instrument_a):
    case = _draft(instrument_id=instrument_a)
    repo.add(case)
    ready = case.transition(ResearchCaseStatus.READY, occurred_at=READY_AT)

    with pytest.raises(ResearchCaseTransitionError):
        repo.save_transition(ResearchCaseStatus.RUNNING, ready)

    assert repo.get(case.case_id).status is ResearchCaseStatus.DRAFT


def test_save_transition_unknown_case_id_raises(repo, instrument_a):
    ready = _draft(instrument_id=instrument_a).transition(
        ResearchCaseStatus.READY, occurred_at=READY_AT
    )

    with pytest.raises(ResearchCaseTransitionError):
        repo.save_transition(ResearchCaseStatus.DRAFT, ready)


def test_uow_rollback_discards_case_write(uow_factory):
    class _Boom(RuntimeError):
        pass

    with uow_factory() as uow:
        uow.instruments.upsert_many(
            [
                Instrument(
                    symbol="510500",
                    name="中证500ETF",
                    exchange="SSE",
                    instrument_type=InstrumentType.ETF,
                    is_active=True,
                )
            ]
        )
        uow.commit()

    with pytest.raises(_Boom), uow_factory() as uow:
        instrument = uow.instruments.get_by_business_key(
            exchange="SSE", symbol="510500"
        )
        assert instrument is not None
        uow.research_cases.add(_draft(instrument_id=instrument.instrument_id.value))
        raise _Boom("simulated failure inside UoW")

    with uow_factory() as uow:
        instrument = uow.instruments.get_by_business_key(
            exchange="SSE", symbol="510500"
        )
        assert instrument is not None
        assert uow.research_cases.list_by_instrument(
            instrument.instrument_id.value
        ) == []


def test_database_rejects_terminal_status_without_closed_at(
    db_session, instrument_a
):
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO analytics.research_cases "
                "(case_id, instrument_id, as_of_date, question, horizon, "
                "status, created_at, closed_at, candidate_pool_run_id) "
                "VALUES (:cid, :iid, :ad, :q, :h, :st, :ca, NULL, NULL)"
            ),
            {
                "cid": str(uuid4()),
                "iid": str(instrument_a),
                "ad": date(2026, 8, 7),
                "q": "active-stamped-terminal",
                "h": "20-60d",
                "st": "completed",
                "ca": CREATED_AT,
            },
        )
