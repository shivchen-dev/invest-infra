"""Focused integration tests for the PR-5.5 ResearchRun / ResearchResult repositories.

Mirrors the existing :mod:`tests.storage.integration.test_research_case_repository`
and :mod:`tests.storage.integration.test_research_evidence_pack_repository`
fixtures so the FK chain (``core.instruments`` -> ``analytics.research_cases``
-> ``analytics.research_evidence_packs`` -> ``analytics.research_runs`` ->
``analytics.research_results``) is built through the existing repository
helpers rather than hand-written SQL.

The PostgreSQL container, schema bootstrap, per-test truncation and
savepoint-isolated ``db_session`` fixture are inherited from
:mod:`tests.storage.integration.conftest`. ``Base.metadata.create_all``
provides a convenient development bootstrap for the integration
container; schema-contract alignment between the ORM models and the
Alembic migrations is separately covered by
``tests/test_migration_chain.py`` together with the
``alembic upgrade head / downgrade base / upgrade head`` cycle in the
``test-migrations`` Make target, so this file focuses on repository
round-trips rather than re-asserting migration fidelity.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from invest_domain.analytics.market_breadth import (
    MarketBreadthInput,
    build_market_breadth,
)
from invest_domain.analytics.market_temperature import (
    REQUIRED_FACTOR_KEYS,
    build_market_temperature,
)
from invest_domain.candidate_pool.models import (
    CandidatePoolRun,
    CandidatePoolStatus,
)
from invest_domain.instruments import Instrument, InstrumentId, InstrumentType
from invest_domain.market_data import Adjust, BarSource, DailyBar, TradingStatus
from invest_domain.research import (
    CaseContext,
    EvidencePack,
    InstrumentSnapshot,
    ResearchCaseStatus,
    ResearchEvidenceBundle,
    ResearchPlaybook,
    SourceReference,
    calculate_market_state_factors,
)
from invest_domain.research.research_case import ResearchCase
from invest_domain.research.research_run import (
    ResearchResult,
    ResearchRun,
    ResearchRunStatus,
)
from invest_pipeline.market_breadth_bundle_service import (
    MarketBreadthBundleSnapshotMissingError,
    build_and_persist_market_breadth_bundle,
)
from invest_storage import (
    ResearchResultConflictError,
    ResearchRunTransitionError,
    SqlAlchemyCandidatePoolRunRepository,
    SqlAlchemyEvidencePackRepository,
    SqlAlchemyMarketObservationSnapshotRepository,
    SqlAlchemyResearchCaseRepository,
    SqlAlchemyResearchEvidenceBundleRepository,
    SqlAlchemyResearchResultRepository,
    SqlAlchemyResearchRunRepository,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.domain.tests.test_research_runner import FakeResearchRunner

INSTRUMENT_ID = UUID("12345678-1234-5678-9234-567812345678")
SOURCE = BarSource(
    provider_key="fixture_dev",
    source_batch_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    observed_at=datetime(2026, 3, 6, 8, tzinfo=UTC),
)
QUESTION = "Will momentum persist over 20-60 trading days?"
AS_OF = date(2026, 8, 7)
CREATED_AT = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
STARTED_AT = datetime(2026, 8, 7, 9, 5, tzinfo=UTC)
FINISHED_AT = datetime(2026, 8, 7, 9, 35, tzinfo=UTC)
RESULT_CREATED_AT = datetime(2026, 8, 7, 9, 36, tzinfo=UTC)
TEST_INPUT_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000001")
INSTRUMENT_SQL = (
    "INSERT INTO core.instruments (id, symbol, exchange, name, "
    "instrument_type, currency, status, is_active, created_at, "
    "updated_at) VALUES (:id, '510300', 'SSE', '沪深300ETF', "
    "'ETF', 'CNY', 'active', true, now(), now()) RETURNING id"
)
SOURCE_REF = SourceReference(
    source_kind="daily_bar",
    source_ref="core.daily_bars:2026-08-07",
    observed_date=AS_OF,
    revision=1,
)


def _bars(
    count: int,
    *,
    instrument_id: UUID | InstrumentId = INSTRUMENT_ID,
) -> tuple[DailyBar, ...]:
    resolved = (
        instrument_id if isinstance(instrument_id, InstrumentId) else InstrumentId(instrument_id)
    )
    start = date(2026, 1, 1)
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
    case_id: UUID | None,
    instrument_id: UUID | InstrumentId = INSTRUMENT_ID,
    bar_count: int = 65,
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


def _result(
    *,
    run: ResearchRun,
    evidence_pack: EvidencePack,
    conclusion: str = "Maintain bullish bias.",
    risks: tuple[str, ...] = ("regulatory", "liquidity"),
    evidence_keys: tuple[str, ...] = ("return_20d", "distance_ma20"),
    report_markdown: str = "# Report\nMomentum persists.",
    model_key: str = "model-x",
    model_version: str = "v1",
    playbook_version: str = "v1",
    adapter_version: str = "v1",
) -> ResearchResult:
    evidence_ids: list[str] = []
    for key in evidence_keys:
        evidence_id = next(
            (item.evidence_id for item in evidence_pack.factors if item.factor_key == key),
            None,
        )
        assert evidence_id is not None, f"factor {key!r} missing from evidence_pack.factors"
        evidence_ids.append(evidence_id)
    return ResearchResult.create(
        run=run,
        evidence_pack=evidence_pack,
        conclusion=conclusion,
        risks=risks,
        evidence_ids=tuple(evidence_ids),
        report_markdown=report_markdown,
        model_key=model_key,
        model_version=model_version,
        playbook_version=playbook_version,
        adapter_version=adapter_version,
        created_at=RESULT_CREATED_AT,
    )


@pytest.fixture()
def instrument(db_session: Session) -> UUID:
    inserted = db_session.execute(text(INSTRUMENT_SQL), {"id": str(INSTRUMENT_ID)}).scalar_one()
    db_session.flush()
    return inserted


@pytest.fixture()
def candidate_pool_run(db_session: Session) -> UUID:
    pool = SqlAlchemyCandidatePoolRunRepository(db_session).add(
        CandidatePoolRun(
            id=uuid4(),
            trade_date=AS_OF,
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
    return pool.id


@pytest.fixture()
def research_case(db_session: Session, instrument: UUID, candidate_pool_run: UUID) -> UUID:
    return (
        SqlAlchemyResearchCaseRepository(db_session)
        .add(
            ResearchCase.create(
                instrument_id=InstrumentId(instrument),
                as_of_date=AS_OF,
                question=QUESTION,
                horizon="20-60d",
                candidate_pool_run_id=candidate_pool_run,
                created_at=CREATED_AT,
            )
        )
        .case_id
    )


@pytest.fixture()
def evidence_pack(db_session: Session, research_case: UUID) -> EvidencePack:
    return SqlAlchemyEvidencePackRepository(db_session).add(_evidence_pack(case_id=research_case))


@pytest.fixture()
def run_repo(db_session: Session) -> SqlAlchemyResearchRunRepository:
    return SqlAlchemyResearchRunRepository(db_session)


@pytest.fixture()
def result_repo(db_session: Session) -> SqlAlchemyResearchResultRepository:
    return SqlAlchemyResearchResultRepository(db_session)


def test_add_get_round_trip_and_list_by_case_orders_deterministically(
    run_repo: SqlAlchemyResearchRunRepository,
    research_case: UUID,
    evidence_pack: EvidencePack,
) -> None:
    assert evidence_pack.pack_id is not None
    pack_id = evidence_pack.pack_id
    first = run_repo.add(
        ResearchRun.create(
            case_id=research_case,
            evidence_pack_id=pack_id,
            runner_key="runner-a",
            playbook_key="playbook-v1",
        )
    )
    later = run_repo.add(
        ResearchRun(
            run_id=UUID(int=first.run_id.int + 1),
            case_id=research_case,
            evidence_pack_id=pack_id,
            runner_key="runner-a",
            playbook_key="playbook-v1",
            status=ResearchRunStatus.QUEUED,
            attempt=1,
        )
    )

    assert first.run_id != later.run_id
    assert run_repo.get(first.run_id) == first
    assert run_repo.get(later.run_id) == later
    assert run_repo.get(uuid4()) is None

    listed = run_repo.list_by_case(research_case)
    assert [run.run_id for run in listed] == [first.run_id, later.run_id]


def test_save_transition_queued_running_succeeded_cas_roundtrip(
    run_repo: SqlAlchemyResearchRunRepository,
    research_case: UUID,
    evidence_pack: EvidencePack,
) -> None:
    assert evidence_pack.pack_id is not None
    queued = run_repo.add(
        ResearchRun.create(
            case_id=research_case,
            evidence_pack_id=evidence_pack.pack_id,
            runner_key="runner-a",
            playbook_key="playbook-v1",
        )
    )

    running = queued.start(occurred_at=STARTED_AT)
    persisted_running = run_repo.save_transition(ResearchRunStatus.QUEUED, running)
    assert persisted_running.status is ResearchRunStatus.RUNNING
    assert persisted_running.started_at == STARTED_AT
    assert persisted_running.finished_at is None
    fetched = run_repo.get(queued.run_id)
    assert fetched is not None and fetched.status is ResearchRunStatus.RUNNING

    succeeded = running.succeed(occurred_at=FINISHED_AT)
    persisted_succeeded = run_repo.save_transition(ResearchRunStatus.RUNNING, succeeded)
    assert persisted_succeeded.status is ResearchRunStatus.SUCCEEDED
    assert persisted_succeeded.started_at == STARTED_AT
    assert persisted_succeeded.finished_at == FINISHED_AT
    assert persisted_succeeded.error_summary is None
    fetched_succeeded = run_repo.get(queued.run_id)
    assert fetched_succeeded is not None
    assert fetched_succeeded.status is ResearchRunStatus.SUCCEEDED


def test_save_transition_stale_previous_status_raises(
    run_repo: SqlAlchemyResearchRunRepository,
    research_case: UUID,
    evidence_pack: EvidencePack,
) -> None:
    assert evidence_pack.pack_id is not None
    queued = run_repo.add(
        ResearchRun.create(
            case_id=research_case,
            evidence_pack_id=evidence_pack.pack_id,
            runner_key="runner-a",
            playbook_key="playbook-v1",
        )
    )
    running = queued.start(occurred_at=STARTED_AT)
    run_repo.save_transition(ResearchRunStatus.QUEUED, running)

    with pytest.raises(ResearchRunTransitionError):
        run_repo.save_transition(ResearchRunStatus.QUEUED, running)

    fetched = run_repo.get(queued.run_id)
    assert fetched is not None and fetched.status is ResearchRunStatus.RUNNING


def test_bind_external_identity_trims_supplied_ids(
    run_repo: SqlAlchemyResearchRunRepository,
    research_case: UUID,
    evidence_pack: EvidencePack,
    db_session: Session,
) -> None:
    assert evidence_pack.pack_id is not None
    queued = run_repo.add(
        ResearchRun.create(
            case_id=research_case,
            evidence_pack_id=evidence_pack.pack_id,
            runner_key="runner-a",
            playbook_key="playbook-v1",
        )
    )

    bound = run_repo.bind_external_identity(
        queued.run_id,
        external_request_id="  req-42  ",
        external_session_id="\tsess-42\n",
    )

    assert bound == queued
    raw = (
        db_session.execute(
            text(
                "SELECT external_request_id, external_session_id "
                "FROM analytics.research_runs WHERE run_id = :rid"
            ),
            {"rid": str(queued.run_id)},
        )
        .mappings()
        .one()
    )
    assert raw["external_request_id"] == "req-42"
    assert raw["external_session_id"] == "sess-42"

    found = run_repo.lookup_by_external_session_id("sess-42")
    assert found == queued
    assert run_repo.lookup_by_external_session_id("  sess-42  ") == queued
    assert run_repo.lookup_by_external_session_id("missing") is None


def test_bind_external_identity_partial_preserves_existing_id(
    run_repo: SqlAlchemyResearchRunRepository,
    research_case: UUID,
    evidence_pack: EvidencePack,
    db_session: Session,
) -> None:
    assert evidence_pack.pack_id is not None
    queued = run_repo.add(
        ResearchRun.create(
            case_id=research_case,
            evidence_pack_id=evidence_pack.pack_id,
            runner_key="runner-a",
            playbook_key="playbook-v1",
        )
    )
    run_repo.bind_external_identity(
        queued.run_id,
        external_request_id="req-existing",
    )

    run_repo.bind_external_identity(
        queued.run_id,
        external_session_id="  sess-42  ",
    )

    raw = (
        db_session.execute(
            text(
                "SELECT external_request_id, external_session_id "
                "FROM analytics.research_runs WHERE run_id = :rid"
            ),
            {"rid": str(queued.run_id)},
        )
        .mappings()
        .one()
    )
    assert raw["external_request_id"] == "req-existing"
    assert raw["external_session_id"] == "sess-42"


def test_result_tuple_json_roundtrip(
    result_repo: SqlAlchemyResearchResultRepository,
    research_case: UUID,
    evidence_pack: EvidencePack,
    run_repo: SqlAlchemyResearchRunRepository,
    db_session: Session,
) -> None:
    assert evidence_pack.pack_id is not None
    queued = run_repo.add(
        ResearchRun.create(
            case_id=research_case,
            evidence_pack_id=evidence_pack.pack_id,
            runner_key="runner-a",
            playbook_key="playbook-v1",
        )
    )
    running = run_repo.save_transition(
        ResearchRunStatus.QUEUED, queued.start(occurred_at=STARTED_AT)
    )
    succeeded = run_repo.save_transition(
        ResearchRunStatus.RUNNING, running.succeed(occurred_at=FINISHED_AT)
    )

    result = _result(
        run=succeeded,
        evidence_pack=evidence_pack,
        risks=("regulatory", "liquidity"),
        evidence_keys=("return_20d", "distance_ma20"),
    )

    persisted = result_repo.add(result)
    fetched = result_repo.get_by_id(persisted.result_id)
    assert fetched is not None
    assert fetched.run_id == succeeded.run_id
    assert fetched.evidence_pack_id == evidence_pack.pack_id
    assert fetched.conclusion == result.conclusion
    assert fetched.report_markdown == result.report_markdown
    assert fetched.model_key == result.model_key
    assert fetched.model_version == result.model_version
    assert fetched.playbook_version == result.playbook_version
    assert fetched.adapter_version == result.adapter_version
    assert fetched.created_at == result.created_at
    assert fetched.risks == ("liquidity", "regulatory")
    assert fetched.evidence_ids == tuple(sorted(result.evidence_ids))
    assert result_repo.get_by_run_id(succeeded.run_id) == fetched

    raw_risks = (
        db_session.execute(
            text(
                "SELECT risks, evidence_ids FROM analytics.research_results WHERE result_id = :rid"
            ),
            {"rid": str(persisted.result_id)},
        )
        .mappings()
        .one()
    )
    assert raw_risks["risks"] == ["liquidity", "regulatory"]
    assert raw_risks["evidence_ids"] == list(fetched.evidence_ids)


def test_seeded_case_observation_bundle_run_result_traceability(
    db_session: Session,
    research_case: UUID,
    evidence_pack: EvidencePack,
) -> None:
    assert evidence_pack.pack_id is not None
    pack_id = evidence_pack.pack_id

    case_repo = SqlAlchemyResearchCaseRepository(db_session)
    run_repo = SqlAlchemyResearchRunRepository(db_session)
    result_repo = SqlAlchemyResearchResultRepository(db_session)
    bundle_repo = SqlAlchemyResearchEvidenceBundleRepository(db_session)
    snapshot_repo = SqlAlchemyMarketObservationSnapshotRepository(db_session)

    market_snapshot = build_market_temperature(
        input_snapshot_id=TEST_INPUT_SNAPSHOT_ID,
        factor_observations=tuple(
            item
            for item in evidence_pack.factors
            if item.factor_key in REQUIRED_FACTOR_KEYS
        ),
        as_of_date=AS_OF,
    )
    persisted_snapshot = snapshot_repo.add(market_snapshot)

    bundle = ResearchEvidenceBundle.build(
        evidence_pack=evidence_pack,
        market_snapshots=(persisted_snapshot,),
        created_at=CREATED_AT,
    )
    persisted_bundle = bundle_repo.add(bundle)

    seeded_case = case_repo.get(research_case)
    assert seeded_case is not None
    draft_to_ready = seeded_case.transition(ResearchCaseStatus.READY, occurred_at=CREATED_AT)
    case_repo.save_transition(ResearchCaseStatus.DRAFT, draft_to_ready)
    ready_to_running = draft_to_ready.transition(ResearchCaseStatus.RUNNING, occurred_at=CREATED_AT)
    case_repo.save_transition(ResearchCaseStatus.READY, ready_to_running)

    playbook = ResearchPlaybook(
        playbook_key="etf_medium_term_assessment", playbook_version="v0.1.0"
    )

    run = run_repo.add(
        ResearchRun.create(
            case_id=research_case,
            evidence_pack_id=pack_id,
            runner_key="fake-runner-v1",
            playbook_key=playbook.playbook_key,
            evidence_bundle_id=persisted_bundle.bundle_id,
        )
    )
    queued_to_running = run.start(occurred_at=CREATED_AT)
    run_repo.save_transition(ResearchRunStatus.QUEUED, queued_to_running)

    running_case = case_repo.get(research_case)
    assert running_case is not None
    running_run = run_repo.get(run.run_id)
    assert running_run is not None

    draft = FakeResearchRunner(clock=lambda: FINISHED_AT).run(
        case=running_case,
        run=running_run,
        evidence_pack=evidence_pack,
        playbook=playbook,
        started_at=CREATED_AT,
    )
    draft_with_bundle = dataclasses.replace(draft, evidence_bundle_id=persisted_bundle.bundle_id)
    succeeded_run = running_run.succeed(occurred_at=FINISHED_AT)
    run_repo.save_transition(ResearchRunStatus.RUNNING, succeeded_run)
    result = draft_with_bundle.to_result(run=succeeded_run, evidence_pack=evidence_pack)
    result_repo.add(result)

    completed_case = running_case.transition(ResearchCaseStatus.COMPLETED, occurred_at=FINISHED_AT)
    case_repo.save_transition(ResearchCaseStatus.RUNNING, completed_case)

    db_session.expire_all()

    reloaded_snapshot = snapshot_repo.get_by_content_hash(persisted_snapshot.content_hash)
    assert reloaded_snapshot is not None
    assert reloaded_snapshot.content_hash == persisted_snapshot.content_hash
    assert reloaded_snapshot.snapshot_id == persisted_snapshot.snapshot_id

    reloaded_bundle = bundle_repo.get_by_id(persisted_bundle.bundle_id)
    assert reloaded_bundle is not None
    assert reloaded_bundle.bundle_hash == persisted_bundle.bundle_hash

    reloaded_case = case_repo.get(research_case)
    assert reloaded_case is not None
    assert reloaded_case.status is ResearchCaseStatus.COMPLETED

    reloaded_run = run_repo.get(run.run_id)
    assert reloaded_run is not None
    assert reloaded_run.status is ResearchRunStatus.SUCCEEDED
    assert reloaded_run.case_id == research_case
    assert reloaded_run.evidence_pack_id == pack_id
    assert reloaded_run.evidence_bundle_id == persisted_bundle.bundle_id
    assert reloaded_run.playbook_key == "etf_medium_term_assessment"

    reloaded_result = result_repo.get_by_run_id(run.run_id)
    assert reloaded_result is not None
    assert reloaded_result.run_id == run.run_id
    assert reloaded_result.evidence_pack_id == pack_id
    assert reloaded_result.evidence_bundle_id == persisted_bundle.bundle_id
    assert set(reloaded_result.evidence_ids).issubset(
        {item.evidence_id for item in evidence_pack.factors if item.evidence_id is not None}
    )

    reloaded_bundle_for_result = bundle_repo.get_by_id(persisted_bundle.bundle_id)
    assert reloaded_bundle_for_result is not None
    assert reloaded_bundle_for_result.evidence_pack_hash == evidence_pack.pack_hash
    assert (
        reloaded_bundle_for_result.market_snapshot_refs[0].snapshot_id
        == reloaded_snapshot.snapshot_id
    )
    assert (
        reloaded_bundle_for_result.market_snapshot_refs[0].content_hash
        == reloaded_snapshot.content_hash
    )


def _seed_market_breadth_bundle_inputs(uow_factory, *, with_snapshot: bool):
    with uow_factory() as uow:
        instrument = Instrument(
            symbol="510300",
            name="沪深300ETF",
            exchange="SSE",
            instrument_type=InstrumentType.ETF,
            is_active=True,
        )
        uow.instruments.upsert_many([instrument])
        persisted_instrument = uow.instruments.get_by_business_key(
            exchange="SSE", symbol="510300"
        )
        assert persisted_instrument is not None
        pool = uow.candidate_pool_runs.add(
            CandidatePoolRun(
                id=uuid4(),
                trade_date=AS_OF,
                algorithm_key="candidate_pool.v1",
                algorithm_version="v1.0",
                parameter_set_key="default",
                parameter_hash="b" * 64,
                input_snapshot_id=TEST_INPUT_SNAPSHOT_ID,
                input_row_count=1,
                included_count=0,
                status=CandidatePoolStatus.CALCULATED,
                created_at=CREATED_AT,
            ),
            quality_summary={"coverage": 1.0},
        )
        case = uow.research_cases.add(
            ResearchCase.create(
                instrument_id=persisted_instrument.instrument_id,
                as_of_date=AS_OF,
                question=QUESTION,
                horizon="20-60d",
                candidate_pool_run_id=pool.id,
                created_at=CREATED_AT,
            )
        )
        pack = uow.research_evidence_packs.add(
            _evidence_pack(
                case_id=case.case_id,
                instrument_id=persisted_instrument.instrument_id,
            )
        )
        snapshot = None
        if with_snapshot:
            snapshot = build_market_breadth(
                input_snapshot_id=TEST_INPUT_SNAPSHOT_ID,
                instruments=(
                    MarketBreadthInput(
                        instrument_id=uuid4(),
                        close=Decimal("11"),
                        prev_close=Decimal("10"),
                        ma20=Decimal("10"),
                        observed_date=AS_OF,
                    ),
                    MarketBreadthInput(
                        instrument_id=uuid4(),
                        close=Decimal("9"),
                        prev_close=Decimal("10"),
                        ma20=Decimal("10"),
                        observed_date=AS_OF,
                    ),
                ),
                as_of_date=AS_OF,
            )
            snapshot = uow.market_observation_snapshots.add(snapshot)
        uow.commit()
        return pack, snapshot


def test_market_breadth_bundle_postgres_round_trip_and_idempotency(uow_factory) -> None:
    pack, snapshot = _seed_market_breadth_bundle_inputs(
        uow_factory, with_snapshot=True
    )
    assert pack.pack_id is not None
    assert snapshot is not None

    first = build_and_persist_market_breadth_bundle(
        uow_factory=uow_factory,
        evidence_pack_id=pack.pack_id,
        created_at=CREATED_AT,
    )
    second = build_and_persist_market_breadth_bundle(
        uow_factory=uow_factory,
        evidence_pack_id=pack.pack_id,
        created_at=CREATED_AT,
    )

    assert second.bundle_id == first.bundle_id
    assert second.bundle_hash == first.bundle_hash
    with uow_factory() as uow:
        reloaded = uow.research_evidence_bundles.get_by_id(first.bundle_id)
        assert reloaded is not None
        assert reloaded.bundle_hash == first.bundle_hash
        assert len(reloaded.market_snapshot_refs) == 1
        ref = reloaded.market_snapshot_refs[0]
        assert ref.snapshot_id == snapshot.snapshot_id
        assert ref.content_hash == snapshot.content_hash
        assert ref.as_of_date == AS_OF


def test_market_breadth_bundle_postgres_missing_snapshot_fails_closed(uow_factory) -> None:
    pack, _ = _seed_market_breadth_bundle_inputs(uow_factory, with_snapshot=False)
    assert pack.pack_id is not None

    with pytest.raises(MarketBreadthBundleSnapshotMissingError):
        build_and_persist_market_breadth_bundle(
            uow_factory=uow_factory,
            evidence_pack_id=pack.pack_id,
            created_at=CREATED_AT,
        )
    with uow_factory() as uow:
        assert uow.research_evidence_bundles.get_by_case_and_pack(
            research_case_id=pack.case.case_id,
            evidence_pack_id=pack.pack_id,
        ) is None


def test_add_identical_result_is_idempotent(
    result_repo: SqlAlchemyResearchResultRepository,
    research_case: UUID,
    evidence_pack: EvidencePack,
    run_repo: SqlAlchemyResearchRunRepository,
    db_session: Session,
) -> None:
    assert evidence_pack.pack_id is not None
    queued = run_repo.add(
        ResearchRun.create(
            case_id=research_case,
            evidence_pack_id=evidence_pack.pack_id,
            runner_key="runner-a",
            playbook_key="playbook-v1",
        )
    )
    started = run_repo.save_transition(
        ResearchRunStatus.QUEUED, queued.start(occurred_at=STARTED_AT)
    )
    succeeded = run_repo.save_transition(
        ResearchRunStatus.RUNNING, started.succeed(occurred_at=FINISHED_AT)
    )

    result = _result(run=succeeded, evidence_pack=evidence_pack)
    first = result_repo.add(result)
    second = result_repo.add(result)

    assert first.result_id == second.result_id == result.result_id
    assert first.run_id == second.run_id
    rows = db_session.execute(text("SELECT COUNT(*) FROM analytics.research_results")).scalar_one()
    assert rows == 1


def test_add_divergent_result_raises_conflict(
    result_repo: SqlAlchemyResearchResultRepository,
    research_case: UUID,
    evidence_pack: EvidencePack,
    run_repo: SqlAlchemyResearchRunRepository,
    db_session: Session,
) -> None:
    assert evidence_pack.pack_id is not None
    queued = run_repo.add(
        ResearchRun.create(
            case_id=research_case,
            evidence_pack_id=evidence_pack.pack_id,
            runner_key="runner-a",
            playbook_key="playbook-v1",
        )
    )
    started = run_repo.save_transition(
        ResearchRunStatus.QUEUED, queued.start(occurred_at=STARTED_AT)
    )
    succeeded = run_repo.save_transition(
        ResearchRunStatus.RUNNING, started.succeed(occurred_at=FINISHED_AT)
    )

    result_repo.add(_result(run=succeeded, evidence_pack=evidence_pack))
    divergent = _result(
        run=succeeded,
        evidence_pack=evidence_pack,
        conclusion="Different conclusion.",
    )

    with pytest.raises(ResearchResultConflictError):
        result_repo.add(divergent)

    rows = db_session.execute(text("SELECT COUNT(*) FROM analytics.research_results")).scalar_one()
    assert rows == 1


def test_database_rejects_second_raw_result_row_for_same_run(
    result_repo: SqlAlchemyResearchResultRepository,
    research_case: UUID,
    evidence_pack: EvidencePack,
    run_repo: SqlAlchemyResearchRunRepository,
    db_session: Session,
) -> None:
    assert evidence_pack.pack_id is not None
    queued = run_repo.add(
        ResearchRun.create(
            case_id=research_case,
            evidence_pack_id=evidence_pack.pack_id,
            runner_key="runner-a",
            playbook_key="playbook-v1",
        )
    )
    started = run_repo.save_transition(
        ResearchRunStatus.QUEUED, queued.start(occurred_at=STARTED_AT)
    )
    succeeded = run_repo.save_transition(
        ResearchRunStatus.RUNNING, started.succeed(occurred_at=FINISHED_AT)
    )

    result = _result(run=succeeded, evidence_pack=evidence_pack)
    persisted = result_repo.add(result)
    run_id = persisted.run_id

    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(
            text(
                "INSERT INTO analytics.research_results "
                "(result_id, run_id, evidence_pack_id, conclusion, "
                "risks, evidence_ids, report_markdown, model_key, "
                "model_version, playbook_version, adapter_version, "
                "created_at) VALUES (:rid, :run, :pack, :conclusion, "
                ":risks, :evidence, :report, :model_key, :model_version, "
                ":playbook_version, :adapter_version, :created_at)"
            ),
            {
                "rid": str(uuid4()),
                "run": str(run_id),
                "pack": str(evidence_pack.pack_id),
                "conclusion": "Second raw row.",
                "risks": "[]",
                "evidence": '["evi-other"]',
                "report": "Second report.",
                "model_key": "model-x",
                "model_version": "v1",
                "playbook_version": "v1",
                "adapter_version": "v1",
                "created_at": RESULT_CREATED_AT,
            },
        )

    rows = db_session.execute(
        text("SELECT COUNT(*) FROM analytics.research_results WHERE run_id = :run"),
        {"run": str(run_id)},
    ).scalar_one()
    assert rows == 1
