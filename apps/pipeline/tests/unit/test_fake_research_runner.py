"""PR-6 Slice D :class:`FakeResearchRunner` tests.

Direct tests pin the deterministic happy-path draft, the failure-injection
defaults, and the factory wiring. One end-to-end failure-classification
test drives a defaulted :class:`FakeResearchRunner` through
:class:`ResearchOrchestrationService.execute` so the orchestrator-side
:class:`ResearchOrchestrationFailedError` mapping is exercised on the
exact exception type the runner defaults to.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from invest_domain.instruments import InstrumentId
from invest_domain.market_data import (
    Adjust,
    BarSource,
    Currency,
    DailyBar,
    TradingStatus,
)
from invest_domain.research import (
    CandidateContext,
    CaseContext,
    DataQuality,
    EvidencePack,
    FreshnessStatus,
    InstrumentSnapshot,
    MarketSnapshot,
    QualityStatus,
    ResearchPlaybook,
    ResearchResult,
    calculate_market_state_factors,
)
from invest_domain.research.research_case import ResearchCase, ResearchCaseStatus
from invest_domain.research.research_run import ResearchRun, ResearchRunStatus
from invest_pipeline.adapters.jiuwenswarm import (
    JiuwenSwarmAcceptance,
    JiuwenSwarmError,
    JiuwenSwarmRemoteFailureError,
)
from invest_pipeline.fake_research_runner import (
    DEFAULT_FAKE_RUNNER_ADAPTER_VERSION,
    FAKE_RUNNER_KEY,
    FakeResearchRunner,
    build_fake_research_runner,
)
from invest_pipeline.research_orchestration_service import (
    ResearchOrchestrationFailedError,
    ResearchOrchestrationService,
)

# ---------------------------------------------------------------------------
# Constants + minimal EvidencePack / case / run builders
# ---------------------------------------------------------------------------


_INSTRUMENT_ID = InstrumentId(UUID("11111111-1114-4118-9111-111111111111"))
_PACK_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_CASE_ID = UUID("22222222-2224-4228-9222-222222222222")
_RUN_ID = UUID("33333333-3334-4338-9333-333333333333")

_AS_OF = date(2026, 3, 6)
_QUESTION = "评估该 ETF 当前市场状态与未来 20-60 个交易日主要风险"
_HORIZON = "20-60d"
_SOURCE = BarSource(
    provider_key="fixture_dev",
    source_batch_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    observed_at=datetime(2026, 3, 6, 8, tzinfo=UTC),
)
_PLAYBOOK_KEY = "etf_medium_term_assessment"
_PLAYBOOK_VERSION = "v0.1.0"

_STARTED_AT = datetime(2026, 3, 6, 7, 6, tzinfo=UTC)
_CREATED_AT = _STARTED_AT - timedelta(minutes=5)


def _bars(count: int) -> tuple[DailyBar, ...]:
    start = date(2026, 1, 1)
    out: list[DailyBar] = []
    for index in range(count):
        trade_date = start + timedelta(days=index)
        close = Decimal(100 + index)
        out.append(
            DailyBar.build(
                instrument_id=_INSTRUMENT_ID,
                trade_date=trade_date,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                prev_close=None if index == 0 else Decimal(99 + index),
                volume=Decimal(1000 + index),
                amount=Decimal(1_000_000 + index * 1000),
                adjustment=Adjust.NONE,
                trading_status=TradingStatus.NORMAL,
                source=_SOURCE,
                revision=1,
                currency=Currency.CNY,
            )
        )
    return tuple(out)


def _build_pack() -> EvidencePack:
    selected = _bars(65)
    calculation = calculate_market_state_factors(
        selected, as_of_date=selected[-1].trade_date, instrument_id=_INSTRUMENT_ID
    )
    return EvidencePack(
        case=CaseContext(
            instrument_id=_INSTRUMENT_ID,
            as_of_date=_AS_OF,
            question=_QUESTION,
            horizon=_HORIZON,
            case_id=_CASE_ID,
        ),
        instrument=InstrumentSnapshot(
            instrument_id=_INSTRUMENT_ID,
            symbol="510300",
            name="沪深300ETF",
            exchange="SSE",
        ),
        candidate_context=CandidateContext(
            included=True, rank=1, total_score=Decimal("0.5"), exclusion_codes=()
        ),
        market_snapshot=MarketSnapshot(
            latest_trade_date=_AS_OF,
            latest_close=Decimal("164"),
            currency="CNY",
            observed_trading_days=65,
            valid_price_days=65,
        ),
        factors=tuple(reversed(calculation.factors)),
        data_quality=DataQuality(
            freshness_status=FreshnessStatus.FRESH,
            quality_status=QualityStatus.COMPLETE,
            target_trading_days=65,
            observed_trading_days=65,
            valid_price_days=65,
        ),
        pack_id=_PACK_ID,
    )


def _playbook() -> ResearchPlaybook:
    return ResearchPlaybook(
        playbook_key=_PLAYBOOK_KEY, playbook_version=_PLAYBOOK_VERSION
    )


def _ready_case_and_queued_run() -> tuple[ResearchCase, ResearchRun, EvidencePack]:
    pack = _build_pack()
    case = ResearchCase(
        case_id=_CASE_ID,
        instrument_id=pack.instrument.instrument_id,
        as_of_date=pack.case.as_of_date,
        question=pack.case.question,
        horizon=pack.case.horizon,
        status=ResearchCaseStatus.READY,
        created_at=_CREATED_AT,
        closed_at=None,
    )
    run = ResearchRun.create(
        case_id=case.case_id,
        evidence_pack_id=pack.pack_id,
        runner_key=FAKE_RUNNER_KEY,
        playbook_key=_PLAYBOOK_KEY,
    )
    return case, run, pack


# ---------------------------------------------------------------------------
# Minimal in-memory UoW for the failure-classification test
# ---------------------------------------------------------------------------


@dataclass
class _FakeCaseRepo:
    cases: dict[UUID, ResearchCase] = field(default_factory=dict)

    def get(self, case_id: UUID) -> ResearchCase | None:
        return self.cases.get(case_id)

    def save_transition(
        self,
        previous_status: ResearchCaseStatus,
        transitioned_case: ResearchCase,
    ) -> ResearchCase:
        existing = self.cases.get(transitioned_case.case_id)
        if existing is None or existing.status is not previous_status:
            raise AssertionError(
                "FakeCaseRepo.save_transition previous status mismatch"
            )
        self.cases[transitioned_case.case_id] = transitioned_case
        return transitioned_case


@dataclass
class _FakeRunRepo:
    runs: dict[UUID, ResearchRun] = field(default_factory=dict)
    external_session_index: dict[str, UUID] = field(default_factory=dict)

    def get(self, run_id: UUID) -> ResearchRun | None:
        return self.runs.get(run_id)

    def save_transition(
        self,
        previous_status: ResearchRunStatus,
        transitioned_run: ResearchRun,
    ) -> ResearchRun:
        existing = self.runs.get(transitioned_run.run_id)
        if existing is None or existing.status is not previous_status:
            raise AssertionError(
                "FakeRunRepo.save_transition previous status mismatch"
            )
        self.runs[transitioned_run.run_id] = transitioned_run
        return transitioned_run

    def bind_external_identity(
        self,
        run_id: UUID,
        *,
        external_request_id: str | None = None,
        external_session_id: str | None = None,
    ) -> ResearchRun:
        if external_request_id is None and external_session_id is None:
            raise ValueError("bind_external_identity requires at least one identity")
        if external_session_id is not None:
            bound = self.external_session_index.get(external_session_id)
            if bound is not None and bound != run_id:
                raise AssertionError(
                    f"session_id {external_session_id!r} already bound to {bound!s}"
                )
            self.external_session_index[external_session_id] = run_id
        return self.runs[run_id]

    def lookup_by_external_session_id(
        self, external_session_id: str
    ) -> ResearchRun | None:
        run_id = self.external_session_index.get(external_session_id)
        return self.runs.get(run_id) if run_id is not None else None


@dataclass
class _FakeResultRepo:
    by_run: dict[UUID, ResearchResult] = field(default_factory=dict)

    def add(self, result: ResearchResult) -> ResearchResult:
        existing = self.by_run.get(result.run_id)
        if existing is not None:
            return existing
        self.by_run[result.run_id] = result
        return result

    def get_by_run_id(self, run_id: UUID) -> ResearchResult | None:
        return self.by_run.get(run_id)


@dataclass
class _FakeEvidencePackRepo:
    by_id: dict[UUID, EvidencePack] = field(default_factory=dict)

    def get_by_id(self, pack_id: UUID) -> EvidencePack | None:
        return self.by_id.get(pack_id)


@dataclass
class _FakeUoW:
    cases: _FakeCaseRepo
    runs: _FakeRunRepo
    evidence_packs: _FakeEvidencePackRepo
    results: _FakeResultRepo
    in_use: bool = False

    def __getattr__(self, name: str) -> Any:
        if name == "research_cases":
            return self.cases
        if name == "research_runs":
            return self.runs
        if name == "research_evidence_packs":
            return self.evidence_packs
        if name == "research_results":
            return self.results
        raise AttributeError(f"'_FakeUoW' object has no attribute {name!r}")

    def commit(self) -> None:
        if not self.in_use:
            raise AssertionError("commit() called outside 'with' block")

    def rollback(self) -> None:
        if not self.in_use:
            raise AssertionError("rollback() called outside 'with' block")

    def __enter__(self) -> _FakeUoW:
        self.in_use = True
        return self

    def __exit__(self, *_args: Any) -> None:
        self.in_use = False


def _build_service(
    *,
    case: ResearchCase,
    run: ResearchRun,
    pack: EvidencePack,
    runner: FakeResearchRunner,
) -> tuple[ResearchOrchestrationService, _FakeUoW]:
    uow = _FakeUoW(
        cases=_FakeCaseRepo(cases={case.case_id: case}),
        runs=_FakeRunRepo(runs={run.run_id: run}),
        evidence_packs=_FakeEvidencePackRepo(by_id={pack.pack_id: pack}),
        results=_FakeResultRepo(),
    )
    service = ResearchOrchestrationService(
        runner=runner,
        playbook=_playbook(),
        uow_factory=lambda: uow,
        clock=lambda: _STARTED_AT + timedelta(seconds=90),
    )
    return service, uow


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class DefaultsTest(unittest.TestCase):
    """The dataclass ships a failure-injecting default."""

    def test_default_raise_exc_is_fresh_remote_failure_per_instance(self) -> None:
        first = FakeResearchRunner()
        second = FakeResearchRunner()
        self.assertIsInstance(first.raise_exc, JiuwenSwarmRemoteFailureError)
        self.assertIsInstance(second.raise_exc, JiuwenSwarmRemoteFailureError)
        # Per-instance factory guarantees the two defaults do not alias.
        self.assertIsNot(first.raise_exc, second.raise_exc)
        self.assertIsInstance(first.raise_exc, JiuwenSwarmError)
        self.assertEqual(first.runner_key, FAKE_RUNNER_KEY)
        self.assertEqual(first.adapter_version, DEFAULT_FAKE_RUNNER_ADAPTER_VERSION)

    def test_run_with_identity_re_raises_default_injection(self) -> None:
        case, run, pack = _ready_case_and_queued_run()
        runner = FakeResearchRunner()
        with self.assertRaises(JiuwenSwarmRemoteFailureError) as ctx:
            runner.run_with_identity(
                case=case,
                run=run,
                evidence_pack=pack,
                playbook=_playbook(),
                started_at=_STARTED_AT,
            )
        self.assertEqual(
            str(ctx.exception), "FakeResearchRunner default injected failure"
        )
        # The call is recorded before the injection fires so the orchestrator
        # trace can still inspect what the runner saw.
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0]["run_id"], run.run_id)


class HappyPathTest(unittest.TestCase):
    """``raise_exc=None`` returns a deterministic accepted outcome."""

    def test_returns_accepted_outcome_with_deterministic_draft(self) -> None:
        case, run, pack = _ready_case_and_queued_run()
        runner = FakeResearchRunner(raise_exc=None)
        outcome = runner.run_with_identity(
            case=case,
            run=run,
            evidence_pack=pack,
            playbook=_playbook(),
            started_at=_STARTED_AT,
        )
        self.assertEqual(outcome.acceptance, JiuwenSwarmAcceptance.ACCEPTED)
        self.assertEqual(outcome.request_id, f"fake-req-{run.run_id!s}")
        self.assertEqual(outcome.session_id, f"fake-sess-{run.run_id!s}")
        self.assertIsNotNone(outcome.draft)
        draft = outcome.draft
        self.assertEqual(draft.model_key, "fake-model")
        self.assertEqual(draft.model_version, "fake-model-v1")
        self.assertEqual(draft.adapter_version, DEFAULT_FAKE_RUNNER_ADAPTER_VERSION)
        self.assertEqual(draft.playbook_version, _PLAYBOOK_VERSION)
        self.assertEqual(draft.created_at, _STARTED_AT)
        self.assertEqual(len(draft.evidence_ids), len(pack.factors))
        self.assertIn("quality=complete", draft.conclusion)
        self.assertIn("freshness=fresh", draft.conclusion)


class FactoryTest(unittest.TestCase):
    """``build_fake_research_runner`` defaults to the happy path."""

    def test_factory_default_is_happy_path(self) -> None:
        runner = build_fake_research_runner()
        self.assertIsNone(runner.raise_exc)
        self.assertEqual(runner.adapter_version, DEFAULT_FAKE_RUNNER_ADAPTER_VERSION)

    def test_factory_can_re_inject_remote_failure(self) -> None:
        runner = build_fake_research_runner(
            raise_exc=JiuwenSwarmRemoteFailureError("manual")
        )
        self.assertIsInstance(runner.raise_exc, JiuwenSwarmRemoteFailureError)
        self.assertEqual(str(runner.raise_exc), "manual")

    def test_factory_rejects_blank_adapter_version(self) -> None:
        with self.assertRaises(ValueError):
            build_fake_research_runner(adapter_version="   ")

    def test_factory_rejects_non_exception_raise_exc(self) -> None:
        with self.assertRaises(TypeError):
            build_fake_research_runner(raise_exc="not an exception")  # type: ignore[arg-type]


class FailureClassificationTest(unittest.TestCase):
    """The default injection is classified as a permanent failure."""

    def test_default_injection_is_classified_as_orchestration_failure(self) -> None:
        case, run, pack = _ready_case_and_queued_run()
        # Default ctor ships with a JiuwenSwarmRemoteFailureError — the
        # orchestrator's ``except JiuwenSwarmError`` arm must translate
        # it into a deterministic ``ResearchOrchestrationFailedError``.
        runner = FakeResearchRunner()
        self.assertIsInstance(runner.raise_exc, JiuwenSwarmRemoteFailureError)
        service, uow = _build_service(case=case, run=run, pack=pack, runner=runner)

        with self.assertRaises(ResearchOrchestrationFailedError) as ctx:
            service.execute(run.run_id)

        self.assertIn("JiuwenSwarmRemoteFailureError", str(ctx.exception))
        self.assertIn(str(run.run_id), str(ctx.exception))
        persisted_run = uow.runs.runs[run.run_id]
        self.assertEqual(persisted_run.status, ResearchRunStatus.FAILED)
        self.assertEqual(
            uow.cases.cases[case.case_id].status, ResearchCaseStatus.FAILED
        )
        self.assertNotIn(run.run_id, uow.results.by_run)


if __name__ == "__main__":
    unittest.main()