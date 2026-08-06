"""Focused integration tests for :class:`SqlAlchemyEvidencePackRepository`."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from invest_domain.candidate_pool.models import CandidatePoolRun, CandidatePoolStatus
from invest_domain.instruments import Instrument, InstrumentId, InstrumentType
from invest_domain.market_data import Adjust, BarSource, DailyBar, TradingStatus
from invest_domain.research import (
    CaseContext,
    EvidencePack,
    InstrumentSnapshot,
    SourceReference,
    calculate_market_state_factors,
)
from invest_domain.research.research_case import ResearchCase
from invest_storage import (
    SqlAlchemyCandidatePoolRunRepository,
    SqlAlchemyEvidencePackRepository,
    SqlAlchemyResearchCaseRepository,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

INSTRUMENT_ID = UUID("12345678-1234-5678-9234-567812345678")
SOURCE = BarSource(
    provider_key="fixture_dev",
    source_batch_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    observed_at=datetime(2026, 3, 6, 8, tzinfo=UTC),
)
QUESTION = "评估该 ETF 当前市场状态与未来 20-60 个交易日主要风险"
AS_OF = date(2026, 3, 6)
CREATED_AT = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
TEST_INPUT_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000001")
INSTRUMENT_SQL = (
    "INSERT INTO core.instruments (id, symbol, exchange, name, "
    "instrument_type, currency, status, is_active, created_at, "
    "updated_at) VALUES (:id, '510300', 'SSE', '沪深300ETF', "
    "'ETF', 'CNY', 'active', true, now(), now()) RETURNING id"
)
SOURCE_REF = SourceReference(
    source_kind="daily_bar",
    source_ref="core.daily_bars:2026-03-06",
    observed_date=AS_OF,
    revision=1,
)


def _bars(
    count: int,
    instrument_id: UUID | InstrumentId = INSTRUMENT_ID,
) -> tuple[DailyBar, ...]:
    start = date(2026, 1, 1)
    resolved = (
        instrument_id if isinstance(instrument_id, InstrumentId) else InstrumentId(instrument_id)
    )
    return tuple(
        DailyBar.build(
            instrument_id=resolved,
            trade_date=start + timedelta(days=i),
            open=Decimal(100 + i),
            high=Decimal(101 + i),
            low=Decimal(99 + i),
            close=Decimal(100 + i),
            prev_close=Decimal(99 + i) if i > 0 else None,
            volume=Decimal(1000 + i),
            amount=Decimal(1_000_000 + i * 1000),
            adjustment=Adjust.NONE,
            trading_status=TradingStatus.NORMAL,
            source=SOURCE,
            revision=1,
        )
        for i in range(count)
    )


def _evidence_pack(
    *,
    bar_count: int = 65,
    case_id: UUID | str | None = None,
    instrument_id: UUID | InstrumentId = INSTRUMENT_ID,
) -> EvidencePack:
    resolved = (
        instrument_id if isinstance(instrument_id, InstrumentId) else InstrumentId(instrument_id)
    )
    calc = calculate_market_state_factors(
        _bars(bar_count, instrument_id=resolved),
        as_of_date=AS_OF,
        instrument_id=resolved,
    )
    return EvidencePack(
        case=CaseContext(
            instrument_id=resolved,
            as_of_date=AS_OF,
            question=QUESTION,
            case_id=case_id,
        ),
        instrument=InstrumentSnapshot(
            instrument_id=resolved,
            symbol="510300",
            name="沪深300ETF",
            exchange="SSE",
        ),
        candidate_context=None,
        market_snapshot=calc.market_snapshot,
        factors=calc.factors,
        data_quality=calc.data_quality,
        missing_fields=calc.missing_fields,
        warnings=calc.warnings,
        source_refs=(SOURCE_REF,),
    )


@pytest.fixture()
def instrument(db_session: Session) -> UUID:
    inserted = db_session.execute(
        text(INSTRUMENT_SQL), {"id": str(INSTRUMENT_ID)}
    ).scalar_one()
    db_session.flush()
    return inserted


@pytest.fixture()
def repo(db_session: Session) -> SqlAlchemyEvidencePackRepository:
    return SqlAlchemyEvidencePackRepository(db_session)


@pytest.fixture()
def research_case(db_session: Session, instrument: UUID) -> UUID:
    pool = SqlAlchemyCandidatePoolRunRepository(db_session).add(
        CandidatePoolRun(
            id=uuid4(),
            trade_date=date(2026, 8, 7),
            algorithm_key="candidate_pool.v1",
            algorithm_version="v1.0",
            parameter_set_key="default",
            parameter_hash="a" * 64,
            input_snapshot_id=TEST_INPUT_SNAPSHOT_ID,
            input_row_count=1,
            included_count=0,
            status=CandidatePoolStatus.CALCULATED,
            created_at=CREATED_AT,
        ),
        quality_summary={"coverage": 0.97},
    )
    return SqlAlchemyResearchCaseRepository(db_session).add(
        ResearchCase.create(
            instrument_id=InstrumentId(instrument),
            as_of_date=date(2026, 8, 7),
            question="Will momentum persist?",
            horizon="20-60d",
            candidate_pool_run_id=pool.id,
            created_at=CREATED_AT,
        )
    ).case_id


def test_round_trip_preserves_pack_hash_and_reconstructs_exact_pack(repo, instrument):
    pack = _evidence_pack(case_id=None)
    persisted = repo.add(pack)
    assert persisted.pack_id is not None
    assert persisted.pack_hash == pack.pack_hash
    assert persisted.generated_at is not None
    assert persisted.workspace_path is None
    assert persisted.e2a_request_id is None
    assert persisted.e2a_session_id is None
    assert persisted.pipeline_run_id is None
    assert persisted.case == pack.case
    assert persisted.instrument == pack.instrument
    assert persisted.factors == pack.factors
    assert persisted.data_quality == pack.data_quality
    assert persisted.market_snapshot == pack.market_snapshot
    assert persisted.candidate_context == pack.candidate_context
    assert repo.get_by_id(persisted.pack_id) == persisted
    assert repo.get_by_content_hash(persisted.pack_hash) == persisted


def test_same_content_is_idempotent_and_distinct_content_yields_new_pack(
    repo, instrument, db_session
):
    full = _evidence_pack()
    short = _evidence_pack(bar_count=20)
    assert short.pack_hash != full.pack_hash
    first = repo.add(_evidence_pack(case_id=None))
    second = repo.add(_evidence_pack(case_id=None))
    assert first.pack_id == second.pack_id
    rows_for_idempotent_hash = db_session.execute(
        text(
            "SELECT COUNT(*) FROM analytics.research_evidence_packs "
            "WHERE content_hash = :hash"
        ),
        {"hash": first.pack_hash},
    ).scalar_one()
    assert rows_for_idempotent_hash == 1
    short_persisted = repo.add(short)
    full_persisted = repo.add(full)
    assert short_persisted.pack_id != full_persisted.pack_id
    assert repo.get_by_content_hash(short.pack_hash).pack_id == short_persisted.pack_id
    assert repo.get_by_content_hash(full.pack_hash).pack_id == full_persisted.pack_id


def test_case_id_uuid_round_trips_and_lists_per_case(repo, instrument, research_case):
    first = repo.add(_evidence_pack(case_id=research_case))
    second = repo.add(_evidence_pack(bar_count=20, case_id=research_case))
    assert first.case.case_id == research_case
    assert second.case.case_id == research_case
    result = repo.list_by_case(research_case)
    assert len(result) == 2
    assert {pack.pack_id for pack in result} == {first.pack_id, second.pack_id}
    legacy = repo.add(_evidence_pack(bar_count=10, case_id=None))
    assert legacy.case.case_id is None
    assert repo.get_by_id(legacy.pack_id).case.case_id is None
    assert list(repo.list_by_case(uuid4())) == []


def test_same_content_with_different_case_binding_fails_closed(
    repo, instrument, research_case, db_session
):
    bound = repo.add(_evidence_pack(case_id=research_case))
    with pytest.raises(ValueError, match="research_case_id mismatch"):
        repo.add(_evidence_pack(case_id=None))
    rows = db_session.execute(
        text(
            "SELECT COUNT(*) FROM analytics.research_evidence_packs "
            "WHERE content_hash = :hash"
        ),
        {"hash": bound.pack_hash},
    ).scalar_one()
    assert rows == 1


def test_unknown_research_case_id_rejected_by_database(repo, instrument):
    with pytest.raises(IntegrityError):
        repo.add(_evidence_pack(case_id=uuid4()))


def test_unknown_instrument_id_rejected_by_database(repo):
    with pytest.raises(IntegrityError):
        repo.add(_evidence_pack())


def test_list_by_instrument_orders_deterministically(repo, instrument):
    persisted_65 = repo.add(_evidence_pack(bar_count=65, case_id=None))
    persisted_20 = repo.add(_evidence_pack(bar_count=20, case_id=None))
    assert persisted_65.pack_hash != persisted_20.pack_hash
    expected_ids = [persisted_65.pack_id, persisted_20.pack_id]
    full_listing = [pack.pack_id for pack in repo.list_by_instrument(INSTRUMENT_ID)]
    assert set(full_listing) == set(expected_ids)
    assert len(full_listing) == 2
    assert [pack.pack_id for pack in repo.list_by_instrument(INSTRUMENT_ID)] == full_listing
    as_of_listing = [
        pack.pack_id
        for pack in repo.list_by_instrument(INSTRUMENT_ID, as_of_date=AS_OF)
    ]
    assert set(as_of_listing) == set(expected_ids)
    assert len(as_of_listing) == 2
    assert [
        pack.pack_id
        for pack in repo.list_by_instrument(INSTRUMENT_ID, as_of_date=AS_OF)
    ] == as_of_listing
    assert repo.list_by_instrument(INSTRUMENT_ID, as_of_date=date(2030, 1, 1)) == []


def test_non_uuid_compatible_case_id_rejected(repo, instrument):
    with pytest.raises(ValueError, match="UUID-compatible"):
        repo.add(_evidence_pack(case_id="not-a-uuid"))


def test_corrupt_payload_fails_closed(repo, instrument, db_session):
    persisted = repo.add(_evidence_pack(case_id=None))
    db_session.execute(
        text(
            "UPDATE analytics.research_evidence_packs SET payload = :payload "
            "WHERE id = :id"
        ),
        {
            "payload": '{"pack_hash": "deadbeef", "case": {}, "factors": []}',
            "id": str(persisted.pack_id),
        },
    )
    db_session.flush()
    with pytest.raises(ValueError):
        repo.get_by_id(persisted.pack_id)


def test_nested_candidate_context_corruption_fails_closed(repo, instrument, db_session):
    persisted = repo.add(_evidence_pack(case_id=None))
    db_session.execute(
        text(
            "UPDATE analytics.research_evidence_packs "
            "SET payload = jsonb_set(payload, '{candidate_context}', '[]'::jsonb) "
            "WHERE id = :id"
        ),
        {"id": str(persisted.pack_id)},
    )
    db_session.flush()
    with pytest.raises(ValueError, match="payload.candidate_context"):
        repo.get_by_id(persisted.pack_id)


def test_column_payload_mismatch_fails_closed(repo, instrument, db_session):
    persisted = repo.add(_evidence_pack(case_id=None))
    db_session.execute(
        text(
            "UPDATE analytics.research_evidence_packs SET freshness_status = "
            "'stale' WHERE id = :id"
        ),
        {"id": str(persisted.pack_id)},
    )
    db_session.flush()
    with pytest.raises(ValueError, match="freshness_status"):
        repo.get_by_id(persisted.pack_id)


def test_uow_commit_and_rollback(uow_factory, session_factory_fixture):
    new_instrument_id = InstrumentId.generate()
    with uow_factory() as uow:
        uow.instruments.upsert_many(
            [
                Instrument(
                    instrument_id=new_instrument_id,
                    symbol="510300",
                    name="沪深300ETF",
                    exchange="SSE",
                    instrument_type=InstrumentType.ETF,
                    is_active=True,
                )
            ]
        )
        uow.commit()
    captured_id = new_instrument_id
    pack = _evidence_pack(case_id=None, instrument_id=captured_id)
    with uow_factory() as uow:
        assert isinstance(uow.research_evidence_packs, SqlAlchemyEvidencePackRepository)
        assert uow.research_evidence_packs is uow.research_evidence_packs
        persisted = uow.research_evidence_packs.add(pack)
        uow.commit()
        committed_id = persisted.pack_id
    with session_factory_fixture() as verify_session:
        assert (
            verify_session.execute(
                text(
                    "SELECT id FROM analytics.research_evidence_packs WHERE id = :id"
                ),
                {"id": str(committed_id)},
            ).first()
            is not None
        )

    class _Boom(RuntimeError):
        pass

    rollback_pack = _evidence_pack(
        bar_count=20, case_id=None, instrument_id=captured_id
    )
    with pytest.raises(_Boom), uow_factory() as uow:
        uow.research_evidence_packs.add(rollback_pack)
        raise _Boom("simulated failure inside UoW")

    with session_factory_fixture() as verify_session:
        assert (
            verify_session.execute(
                text("SELECT COUNT(*) FROM analytics.research_evidence_packs")
            ).scalar_one()
            == 1
        )
