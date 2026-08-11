"""PR-6 Slice 3 research orchestration service tests.

Drives the :class:`ResearchOrchestrationService` end-to-end through
normal completion, replay, duplicate-session rejection, uncertain
timeout, adapter failure, persistence conflict, and the
already-bound-running reconciliation guard. Every test injects a
hand-rolled ``_FakeRunner`` and ``_FakeUoW`` so the slice is exercised
without booting the real Gateway or storage.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import patch
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
    ResearchEvidenceBundle,
    ResearchPlaybook,
    ResearchResult,
    ResearchRunnerDraft,
    calculate_market_state_factors,
)
from invest_domain.research.research_case import ResearchCase, ResearchCaseStatus
from invest_domain.research.research_run import ResearchRun, ResearchRunStatus
from invest_pipeline.adapters.jiuwenswarm import (
    JIUWENSWARM_SCHEMA_VERSION,
    JiuwenSwarmAcceptance,
    JiuwenSwarmMalformedResultError,
    JiuwenSwarmRemoteFailureError,
    JiuwenSwarmTimeoutUncertainError,
)
from invest_pipeline.adapters.jiuwenswarm.codec import coerce_completion
from invest_pipeline.adapters.jiuwenswarm.mapping import build_draft
from invest_pipeline.adapters.jiuwenswarm.runner import JiuwenSwarmRunOutcome
from invest_pipeline.research_context_projection import ContextProjectionLoadError
from invest_pipeline.research_orchestration_service import (
    ResearchOrchestrationConflictError,
    ResearchOrchestrationFailedError,
    ResearchOrchestrationInputError,
    ResearchOrchestrationReconciliationRequiredError,
    ResearchOrchestrationService,
    ResearchOrchestrationUncertainError,
)

# Constants + minimal fixture aligned with the Slice 1 tests

_INSTRUMENT_ID = InstrumentId(UUID("11111111-1114-4118-9111-111111111111"))
_PACK_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_BUNDLE_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
_CASE_ID = UUID("22222222-2224-4228-9222-222222222222")
_RUN_ID = UUID("33333333-3334-4338-9333-333333333333")
_OTHER_RUN_ID = UUID("99999999-9994-4998-9999-999999999999")

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
_RUNNER_KEY = "jiuwenswarm-runner-v1"
_ADAPTER_VERSION = "jiuwenswarm-adapter-v1"

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


def _build_draft(
    *,
    evidence_pack: EvidencePack,
    evidence_bundle_id: UUID | None = None,
) -> ResearchRunnerDraft:
    payload = {
        "schema_version": JIUWENSWARM_SCHEMA_VERSION,
        "playbook_key": _PLAYBOOK_KEY,
        "playbook_version": _PLAYBOOK_VERSION,
        "adapter_version": _ADAPTER_VERSION,
        "model_key": "jiuwen-model-v1",
        "model_version": "jiuwen-model-v1",
        "conclusion": "Sample conclusion.",
        "risks": ["execution_risk", "data_staleness"],
        "evidence_ids": [
            item.evidence_id for item in evidence_pack.factors if item.evidence_id
        ],
        "report_markdown": "# Report\n",
        "acceptance": JiuwenSwarmAcceptance.ACCEPTED.value,
    }
    completion = coerce_completion(payload)
    return build_draft(
        completion=completion,
        playbook=_playbook(),
        adapter_version=_ADAPTER_VERSION,
        now=_STARTED_AT,
        evidence_bundle_id=evidence_bundle_id,
    )


def _accepted_outcome(
    *, request_id: str, session_id: str, draft: ResearchRunnerDraft
) -> JiuwenSwarmRunOutcome:
    return JiuwenSwarmRunOutcome(
        request_id=request_id,
        session_id=session_id,
        acceptance=JiuwenSwarmAcceptance.ACCEPTED,
        draft=draft,
    )


# Fake runner + fake Unit-of-Work


@dataclass
class _FakeRunner:
    """In-memory fake for :meth:`ResearchRunnerWithIdentity.run_with_identity`."""

    runner_key: str = _RUNNER_KEY
    adapter_version: str = _ADAPTER_VERSION
    outcome: JiuwenSwarmRunOutcome | None = None
    raise_exc: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def run_with_identity(self, **_: Any) -> JiuwenSwarmRunOutcome:
        self.calls.append({})
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.outcome is None:
            raise AssertionError("FakeRunner has no outcome configured")
        return self.outcome


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
    explode_on_queued_save: bool = False

    def get(self, run_id: UUID) -> ResearchRun | None:
        return self.runs.get(run_id)

    def save_transition(
        self,
        previous_status: ResearchRunStatus,
        transitioned_run: ResearchRun,
    ) -> ResearchRun:
        if (
            self.explode_on_queued_save
            and previous_status is ResearchRunStatus.QUEUED
        ):
            raise AssertionError("simulated CAS conflict on queued→running")
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
    """In-memory fake for ``SqlAlchemyEvidencePackRepository.get_by_id``."""

    by_id: dict[UUID, EvidencePack] = field(default_factory=dict)

    def get_by_id(self, pack_id: UUID) -> EvidencePack | None:
        return self.by_id.get(pack_id)


@dataclass
class _FakeEvidenceBundleRepo:
    """In-memory fake for ``ResearchEvidenceBundleRepositoryPort.get_by_id``."""

    by_id: dict[UUID, ResearchEvidenceBundle] = field(default_factory=dict)

    def get_by_id(self, bundle_id: UUID) -> ResearchEvidenceBundle | None:
        return self.by_id.get(bundle_id)


@dataclass
class _FakeUoW:
    cases: _FakeCaseRepo
    runs: _FakeRunRepo
    evidence_packs: _FakeEvidencePackRepo
    results: _FakeResultRepo
    evidence_bundles: _FakeEvidenceBundleRepo = field(
        default_factory=_FakeEvidenceBundleRepo
    )
    commit_count: int = 0
    rollback_count: int = 0
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
        if name == "research_evidence_bundles":
            return self.evidence_bundles
        raise AttributeError(
            f"'_FakeUoW' object has no attribute {name!r}"
        )

    def commit(self) -> None:
        if not self.in_use:
            raise AssertionError("commit() called outside 'with' block")
        self.commit_count += 1

    def rollback(self) -> None:
        if not self.in_use:
            raise AssertionError("rollback() called outside 'with' block")
        self.rollback_count += 1

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
    result: ResearchResult | None = None,
    fake_runner: _FakeRunner | None = None,
    run_repo: _FakeRunRepo | None = None,
    bundle_repo: _FakeEvidenceBundleRepo | None = None,
    bundle: ResearchEvidenceBundle | None = None,
) -> tuple[ResearchOrchestrationService, _FakeUoW, _FakeRunner]:
    runs = run_repo or _FakeRunRepo(runs={run.run_id: run})
    if run.run_id not in runs.runs:
        runs.runs[run.run_id] = run
    result_repo = _FakeResultRepo()
    if result is not None:
        result_repo.by_run[result.run_id] = result
    evidence_bundles = bundle_repo or _FakeEvidenceBundleRepo()
    if bundle is not None:
        evidence_bundles.by_id[bundle.bundle_id] = bundle
    uow = _FakeUoW(
        cases=_FakeCaseRepo(cases={case.case_id: case}),
        runs=runs,
        evidence_packs=_FakeEvidencePackRepo(by_id={pack.pack_id: pack}),
        results=result_repo,
        evidence_bundles=evidence_bundles,
    )
    runner = fake_runner or _FakeRunner()
    service = ResearchOrchestrationService(
        runner=runner,
        playbook=_playbook(),
        uow_factory=lambda: uow,
        clock=lambda: _STARTED_AT + timedelta(seconds=90),
    )
    return service, uow, runner


def _ready_case_and_queued_run(
    *, evidence_bundle_id: UUID | None = None
) -> tuple[ResearchCase, ResearchRun, EvidencePack]:
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
        runner_key=_RUNNER_KEY,
        playbook_key=_PLAYBOOK_KEY,
        evidence_bundle_id=evidence_bundle_id,
    )
    return case, run, pack


def _running_case_and_run(
    *, evidence_bundle_id: UUID | None = None
) -> tuple[ResearchCase, ResearchRun, EvidencePack]:
    case, run, pack = _ready_case_and_queued_run(
        evidence_bundle_id=evidence_bundle_id
    )
    return (
        case.transition(ResearchCaseStatus.RUNNING, occurred_at=_STARTED_AT),
        run.start(occurred_at=_STARTED_AT),
        pack,
    )


def _build_bundle(
    *,
    pack: EvidencePack,
    bundle_id: UUID = _BUNDLE_ID,
    research_case_id: UUID | None = None,
    evidence_pack_id: UUID | None = None,
) -> ResearchEvidenceBundle:
    return ResearchEvidenceBundle(
        bundle_id=bundle_id,
        research_case_id=(
            research_case_id if research_case_id is not None else pack.case.case_id
        ),
        evidence_pack_id=(
            evidence_pack_id if evidence_pack_id is not None else pack.pack_id
        ),
        evidence_pack_hash=pack.pack_hash,
        market_snapshot_refs=(),
        schema_version="1.0.0",
        bundle_hash="",
        created_at=_STARTED_AT,
        as_of_date=pack.case.as_of_date,
    )


# Tests


class NormalCompletionTest(unittest.TestCase):
    """The happy path persists one result and closes the lifecycle."""

    def test_queued_to_succeeded_persists_result_and_binds_identity(self) -> None:
        case, run, pack = _ready_case_and_queued_run()
        draft = _build_draft(evidence_pack=pack)
        runner = _FakeRunner(
            outcome=_accepted_outcome(
                request_id="req-1", session_id="sess-1", draft=draft
            )
        )
        service, uow, _r = _build_service(
            case=case, run=run, pack=pack, fake_runner=runner
        )

        outcome = service.execute(run.run_id)

        self.assertFalse(outcome.replay)
        self.assertIsNotNone(outcome.result)
        self.assertEqual(outcome.run.status, ResearchRunStatus.SUCCEEDED)
        self.assertEqual(outcome.case.status, ResearchCaseStatus.COMPLETED)
        self.assertEqual(uow.runs.external_session_index, {"sess-1": run.run_id})
        self.assertIn(run.run_id, uow.results.by_run)


class ReplayTest(unittest.TestCase):
    """Previously-succeeded / running-with-result rows return the existing result."""

    def test_succeeded_run_replays_existing_result(self) -> None:
        case, run, pack = _ready_case_and_queued_run()
        running_run = run.start(occurred_at=_STARTED_AT)
        succeeded_run = running_run.succeed(occurred_at=_STARTED_AT)
        running_case = case.transition(
            ResearchCaseStatus.RUNNING, occurred_at=_STARTED_AT
        )
        completed_case = running_case.transition(
            ResearchCaseStatus.COMPLETED, occurred_at=_STARTED_AT
        )
        result = _build_draft(evidence_pack=pack).to_result(
            run=succeeded_run, evidence_pack=pack
        )
        runner = _FakeRunner()
        service, _uow, runner = _build_service(
            case=completed_case,
            run=succeeded_run,
            pack=pack,
            result=result,
            fake_runner=runner,
        )

        outcome = service.execute(run.run_id)

        self.assertTrue(outcome.replay)
        self.assertEqual(outcome.result, result)
        self.assertEqual(runner.calls, [])

    def test_running_run_with_result_replays_without_gateway(self) -> None:
        case, run, pack = _running_case_and_run()
        succeeded_run = run.succeed(occurred_at=_STARTED_AT)
        result = _build_draft(evidence_pack=pack).to_result(
            run=succeeded_run, evidence_pack=pack
        )
        runner = _FakeRunner()
        service, _uow, runner = _build_service(
            case=case, run=succeeded_run, pack=pack, result=result, fake_runner=runner
        )

        outcome = service.execute(run.run_id)

        self.assertTrue(outcome.replay)
        self.assertEqual(runner.calls, [])


class DuplicateSessionTest(unittest.TestCase):
    """A second run claiming the same external session_id is rejected as a conflict."""

    def test_duplicate_session_id_raises_conflict(self) -> None:
        case, run, pack = _ready_case_and_queued_run()
        draft = _build_draft(evidence_pack=pack)
        runner = _FakeRunner(
            outcome=_accepted_outcome(
                request_id="req-2", session_id="sess-shared", draft=draft
            )
        )
        service, uow, _r = _build_service(
            case=case, run=run, pack=pack, fake_runner=runner
        )
        uow.runs.runs[_OTHER_RUN_ID] = ResearchRun(
            run_id=_OTHER_RUN_ID,
            case_id=case.case_id,
            evidence_pack_id=pack.pack_id,
            runner_key=_RUNNER_KEY,
            playbook_key=_PLAYBOOK_KEY,
            status=ResearchRunStatus.QUEUED,
            attempt=1,
        )
        uow.runs.external_session_index["sess-shared"] = _OTHER_RUN_ID

        with self.assertRaises(ResearchOrchestrationConflictError):
            service.execute(run.run_id)

        # The queued→running transition already committed before the Tx2
        # duplicate check raised; the run stays in running.
        self.assertEqual(
            uow.runs.runs[run.run_id].status, ResearchRunStatus.RUNNING
        )


class TimeoutTest(unittest.TestCase):
    """Uncertain timeout binds identity but leaves the run / case in ``running``."""

    def test_timeout_binds_identity_and_raises_uncertain(self) -> None:
        case, run, pack = _ready_case_and_queued_run()
        runner = _FakeRunner(
            raise_exc=JiuwenSwarmTimeoutUncertainError(
                "local watchdog fired",
                request_id="req-timeout",
                session_id="sess-timeout",
            )
        )
        service, uow, _r = _build_service(
            case=case, run=run, pack=pack, fake_runner=runner
        )

        with self.assertRaises(ResearchOrchestrationUncertainError) as ctx:
            service.execute(run.run_id)

        exc = ctx.exception
        self.assertEqual(exc.request_id, "req-timeout")
        self.assertEqual(exc.session_id, "sess-timeout")
        self.assertEqual(
            uow.runs.runs[run.run_id].status, ResearchRunStatus.RUNNING
        )
        self.assertEqual(
            uow.runs.external_session_index.get("sess-timeout"), run.run_id
        )
        self.assertNotIn(run.run_id, uow.results.by_run)


class AdapterFailureTest(unittest.TestCase):
    """Non-timeout adapter failures mark the run / case failed with a safe summary."""

    def _run_with_failure(self, *, exc: Exception) -> _FakeUoW:
        case, run, pack = _ready_case_and_queued_run()
        runner = _FakeRunner(raise_exc=exc)
        service, uow, _r = _build_service(
            case=case, run=run, pack=pack, fake_runner=runner
        )
        with self.assertRaises(ResearchOrchestrationFailedError):
            service.execute(run.run_id)
        return uow, run

    def test_malformed_result_marks_failed_truncates_summary_and_binds_identity(
        self,
    ) -> None:
        uow, run = self._run_with_failure(
            exc=JiuwenSwarmMalformedResultError(
                "boom " * 200, request_id="req-bad", session_id="sess-bad"
            )
        )
        persisted = uow.runs.runs[run.run_id]
        self.assertEqual(persisted.status, ResearchRunStatus.FAILED)
        self.assertIsNotNone(persisted.error_summary)
        self.assertLessEqual(len(persisted.error_summary), 500)
        self.assertNotIn(run.run_id, uow.results.by_run)
        self.assertEqual(
            uow.runs.external_session_index.get("sess-bad"), run.run_id
        )

    def test_remote_failure_marks_failed_without_result(self) -> None:
        uow, run = self._run_with_failure(
            exc=JiuwenSwarmRemoteFailureError(
                "gateway rejected",
                request_id="req-remote",
                session_id="sess-remote",
            )
        )
        self.assertEqual(
            uow.runs.runs[run.run_id].status, ResearchRunStatus.FAILED
        )
        self.assertNotIn(run.run_id, uow.results.by_run)


class PersistenceConflictTest(unittest.TestCase):
    """A CAS-aware save_transition failure surfaces as an orchestration conflict."""

    def test_queued_to_running_cas_failure_is_orchestration_conflict(self) -> None:
        case, run, pack = _ready_case_and_queued_run()
        run_repo = _FakeRunRepo(
            runs={run.run_id: run}, explode_on_queued_save=True
        )
        draft = _build_draft(evidence_pack=pack)
        runner = _FakeRunner(
            outcome=_accepted_outcome(
                request_id="req-conflict",
                session_id="sess-conflict",
                draft=draft,
            )
        )
        service, uow, _r = _build_service(
            case=case,
            run=run,
            pack=pack,
            fake_runner=runner,
            run_repo=run_repo,
        )

        with self.assertRaises(ResearchOrchestrationConflictError):
            service.execute(run.run_id)

        self.assertEqual(
            uow.runs.runs[run.run_id].status, ResearchRunStatus.QUEUED
        )


class AlreadyBoundRunningTest(unittest.TestCase):
    """A duplicate execute on a RUNNING run raises reconciliation-required."""

    def test_running_run_without_result_raises_reconciliation(self) -> None:
        case, run, pack = _running_case_and_run()
        runner = _FakeRunner()
        service, uow, runner = _build_service(
            case=case, run=run, pack=pack, fake_runner=runner
        )

        with self.assertRaises(ResearchOrchestrationReconciliationRequiredError):
            service.execute(run.run_id)

        self.assertEqual(runner.calls, [])
        # Load + existing-result lookup transactions both committed before
        # the reconciliation error surfaced; no start transaction was needed.
        self.assertEqual(uow.commit_count, 2)


class EvidenceBundleBindingTest(unittest.TestCase):
    """Optional ``evidence_bundle_id`` on the run is loaded, validated, and propagated."""

    def test_missing_bundle_raises_input_error(self) -> None:
        case, run, pack = _ready_case_and_queued_run(evidence_bundle_id=_BUNDLE_ID)
        runner = _FakeRunner()
        service, uow, runner = _build_service(
            case=case, run=run, pack=pack, fake_runner=runner
        )

        with self.assertRaises(ResearchOrchestrationInputError) as ctx:
            service.execute(run.run_id)

        self.assertIn(str(_BUNDLE_ID), str(ctx.exception))
        self.assertEqual(runner.calls, [])

    def test_bundle_with_wrong_case_raises_input_error(self) -> None:
        case, run, pack = _ready_case_and_queued_run(evidence_bundle_id=_BUNDLE_ID)
        wrong_case = UUID("77777777-7774-4778-9777-777777777777")
        bundle = _build_bundle(pack=pack, research_case_id=wrong_case)
        runner = _FakeRunner()
        service, _uow, runner = _build_service(
            case=case, run=run, pack=pack, fake_runner=runner, bundle=bundle
        )

        with self.assertRaises(ResearchOrchestrationInputError) as ctx:
            service.execute(run.run_id)

        self.assertIn("research_case_id", str(ctx.exception))
        self.assertEqual(runner.calls, [])

    def test_bundle_with_wrong_pack_raises_input_error(self) -> None:
        case, run, pack = _ready_case_and_queued_run(evidence_bundle_id=_BUNDLE_ID)
        wrong_pack = UUID("88888888-8884-4888-9888-888888888888")
        bundle = _build_bundle(pack=pack, evidence_pack_id=wrong_pack)
        runner = _FakeRunner()
        service, _uow, runner = _build_service(
            case=case, run=run, pack=pack, fake_runner=runner, bundle=bundle
        )

        with self.assertRaises(ResearchOrchestrationInputError) as ctx:
            service.execute(run.run_id)

        self.assertIn("evidence_pack_id", str(ctx.exception))
        self.assertEqual(runner.calls, [])

    def test_run_without_bundle_id_is_accepted(self) -> None:
        case, run, pack = _ready_case_and_queued_run()
        self.assertIsNone(run.evidence_bundle_id)
        draft = _build_draft(evidence_pack=pack)
        runner = _FakeRunner(
            outcome=_accepted_outcome(
                request_id="req-no-bundle", session_id="sess-no-bundle", draft=draft
            )
        )
        service, _uow, _r = _build_service(
            case=case, run=run, pack=pack, fake_runner=runner
        )

        with patch(
            "invest_pipeline.research_orchestration_service.load_context_projection"
        ) as load_projection:
            outcome = service.execute(run.run_id)

        self.assertIsNotNone(outcome.result)
        self.assertIsNone(outcome.result.evidence_bundle_id)
        load_projection.assert_not_called()

    def test_run_with_valid_bundle_propagates_id_to_result(self) -> None:
        case, run, pack = _ready_case_and_queued_run(evidence_bundle_id=_BUNDLE_ID)
        bundle = _build_bundle(pack=pack)
        draft = _build_draft(
            evidence_pack=pack, evidence_bundle_id=run.evidence_bundle_id
        )
        self.assertEqual(run.evidence_bundle_id, _BUNDLE_ID)
        self.assertEqual(draft.evidence_bundle_id, _BUNDLE_ID)
        runner = _FakeRunner(
            outcome=_accepted_outcome(
                request_id="req-bundle", session_id="sess-bundle", draft=draft
            )
        )
        service, _uow, _r = _build_service(
            case=case,
            run=run,
            pack=pack,
            fake_runner=runner,
            bundle=bundle,
        )

        with patch(
            "invest_pipeline.research_orchestration_service.load_context_projection",
            return_value=object(),
        ) as load_projection:
            outcome = service.execute(run.run_id)

        self.assertFalse(outcome.replay)
        self.assertIsNotNone(outcome.result)
        self.assertEqual(outcome.result.evidence_bundle_id, _BUNDLE_ID)
        load_projection.assert_called_once()

    def test_bundle_bound_run_loads_projection_inside_tx1(self) -> None:
        case, run, pack = _ready_case_and_queued_run(evidence_bundle_id=_BUNDLE_ID)
        bundle = _build_bundle(pack=pack)
        runner = _FakeRunner(
            outcome=_accepted_outcome(
                request_id="req-projection", session_id="sess-projection",
                draft=_build_draft(
                    evidence_pack=pack, evidence_bundle_id=_BUNDLE_ID
                ),
            )
        )
        service, uow, _runner = _build_service(
            case=case, run=run, pack=pack, fake_runner=runner, bundle=bundle
        )

        def load_in_tx1(loaded_uow: Any, **_kwargs: Any) -> object:
            self.assertTrue(loaded_uow.in_use)
            return object()

        with patch(
            "invest_pipeline.research_orchestration_service.load_context_projection",
            side_effect=load_in_tx1,
        ) as load_projection:
            service.execute(run.run_id)

        args, kwargs = load_projection.call_args
        self.assertEqual(len(args), 1)
        self.assertIs(kwargs["case"], case)
        self.assertIs(kwargs["run"], run)
        self.assertIs(kwargs["evidence_pack"], pack)

    def test_projection_loader_failures_are_input_errors(self) -> None:
        case, run, pack = _ready_case_and_queued_run(evidence_bundle_id=_BUNDLE_ID)
        bundle = _build_bundle(pack=pack)

        for failure in (
            ContextProjectionLoadError("bad projection"),
            ValueError("bad projection"),
        ):
            with self.subTest(failure=type(failure).__name__):
                service, _uow, runner = _build_service(
                    case=case,
                    run=run,
                    pack=pack,
                    fake_runner=_FakeRunner(),
                    bundle=bundle,
                )
                with (
                    patch(
                        "invest_pipeline.research_orchestration_service.load_context_projection",
                        side_effect=failure,
                    ),
                    self.assertRaises(ResearchOrchestrationInputError) as ctx,
                ):
                    service.execute(run.run_id)

                self.assertIn("bad projection", str(ctx.exception))
                self.assertEqual(runner.calls, [])



if __name__ == "__main__":
    unittest.main()
