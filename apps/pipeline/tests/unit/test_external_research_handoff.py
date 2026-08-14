from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from invest_domain.instruments import InstrumentId
from invest_domain.market_data import Adjust, BarSource, Currency, DailyBar, TradingStatus
from invest_domain.research import (
    CaseContext,
    DataQuality,
    EvidencePack,
    FreshnessStatus,
    InstrumentSnapshot,
    MarketSnapshot,
    QualityStatus,
    ResearchPlaybook,
    ResearchRunnerDraft,
    calculate_market_state_factors,
)
from invest_domain.research.research_case import ResearchCase, ResearchCaseStatus
from invest_domain.research.research_run import ResearchRunStatus
from invest_pipeline.adapters.jiuwenswarm.runner import (
    JiuwenSwarmAcceptance,
    JiuwenSwarmRunOutcome,
)
from invest_pipeline.external_research_handoff import (
    ExternalResearchHandoffInputError,
    ExternalResearchHandoffService,
)

_INSTRUMENT_ID = InstrumentId(UUID("11111111-1111-4111-8111-111111111111"))
_CASE_ID = UUID("22222222-2222-4222-8222-222222222222")
_PACK_ID = UUID("33333333-3333-4333-8333-333333333333")
_NOW = datetime(2026, 3, 6, 8, tzinfo=UTC)


def _pack() -> EvidencePack:
    bars = tuple(
        DailyBar.build(
            instrument_id=_INSTRUMENT_ID,
            trade_date=date(2026, 1, 1) + timedelta(days=index),
            open=Decimal(100 + index),
            high=Decimal(101 + index),
            low=Decimal(99 + index),
            close=Decimal(100 + index),
            prev_close=None if index == 0 else Decimal(99 + index),
            volume=Decimal(1000),
            amount=Decimal(100000),
            adjustment=Adjust.NONE,
            trading_status=TradingStatus.NORMAL,
            source=BarSource(
                provider_key="fixture",
                source_batch_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
                observed_at=_NOW,
            ),
            revision=1,
            currency=Currency.CNY,
        )
        for index in range(65)
    )
    factors = calculate_market_state_factors(
        bars, as_of_date=date(2026, 3, 6), instrument_id=_INSTRUMENT_ID
    ).factors
    return EvidencePack(
        case=CaseContext(
            instrument_id=_INSTRUMENT_ID,
            as_of_date=date(2026, 3, 6),
            question="评估当前市场状态",
            horizon="20-60d",
            case_id=_CASE_ID,
        ),
        instrument=InstrumentSnapshot(
            instrument_id=_INSTRUMENT_ID,
            symbol="510300",
            name="沪深300ETF",
            exchange="SSE",
        ),
        market_snapshot=MarketSnapshot(
            latest_trade_date=date(2026, 3, 6),
            latest_close=Decimal(164),
            currency="CNY",
            observed_trading_days=65,
            valid_price_days=65,
        ),
        factors=factors,
        data_quality=DataQuality(
            freshness_status=FreshnessStatus.FRESH,
            quality_status=QualityStatus.COMPLETE,
            target_trading_days=65,
            observed_trading_days=65,
            valid_price_days=65,
        ),
        pack_id=_PACK_ID,
    )


class _Repo:
    def __init__(self, *, case=None, pack=None, linked=True):
        self.case = case
        self.pack = pack
        self.linked = linked
        self.runs = []

    def get(self, _case_id):
        return self.case

    def get_by_id(self, _pack_id):
        return self.pack

    def list_by_case(self, _case_id):
        return [SimpleNamespace()] if self.linked else []

    def save_transition(self, _previous, transitioned):
        self.case = transitioned
        return transitioned

    def add(self, run):
        self.runs.append(run)
        return run

    def list_by_case_runs(self, _case_id):
        return self.runs


class _Runs(_Repo):
    def get(self, run_id):
        return next((run for run in self.runs if run.run_id == run_id), None)

    def save_transition(self, previous_status, transitioned_run):
        for index, run in enumerate(self.runs):
            if run.run_id == transitioned_run.run_id:
                if run.status is not previous_status:
                    raise AssertionError("unexpected previous run status")
                self.runs[index] = transitioned_run
                return transitioned_run
        raise AssertionError("run was not found")

    def bind_external_identity(self, run_id, *, external_request_id=None, external_session_id=None):
        return self.get(run_id)

    def lookup_by_external_session_id(self, _session_id):
        return None

    def list_by_case(self, _case_id):
        return self.runs


class _Results:
    def __init__(self):
        self.items = []

    def add(self, result):
        self.items.append(result)
        return result

    def get_by_run_id(self, run_id):
        return next((item for item in self.items if item.run_id == run_id), None)


class _Uow:
    def __init__(self, case, pack, linked=True):
        self.research_cases = _Repo(case=case)
        self.research_evidence_packs = _Repo(pack=pack)
        self.research_external_evidence = _Repo(linked=linked)
        self.research_runs = _Runs()
        self.research_results = _Results()
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def commit(self):
        self.commits += 1


class ExternalResearchHandoffTest(unittest.TestCase):
    def test_queue_requires_linked_external_evidence(self):
        pack = _pack()
        case = ResearchCase.create(
            instrument_id=_INSTRUMENT_ID,
            as_of_date=pack.case.as_of_date,
            question=pack.case.question,
            horizon=pack.case.horizon,
            created_at=_NOW,
        )
        case = ResearchCase(
            case_id=_CASE_ID,
            instrument_id=case.instrument_id,
            as_of_date=case.as_of_date,
            question=case.question,
            horizon=case.horizon,
            status=ResearchCaseStatus.DRAFT,
            created_at=case.created_at,
        )
        uow = _Uow(case, pack, linked=False)
        service = ExternalResearchHandoffService(lambda: uow, lambda: _NOW)

        with self.assertRaises(ExternalResearchHandoffInputError):
            service.queue(
                case_id=_CASE_ID,
                evidence_pack_id=_PACK_ID,
                playbook=ResearchPlaybook(
                    playbook_key="etf_medium_term_assessment",
                    playbook_version="v0.1.0",
                ),
            )

    def test_queue_promotes_draft_and_creates_run(self):
        pack = _pack()
        case = ResearchCase(
            case_id=_CASE_ID,
            instrument_id=_INSTRUMENT_ID,
            as_of_date=pack.case.as_of_date,
            question=pack.case.question,
            horizon=pack.case.horizon,
            status=ResearchCaseStatus.DRAFT,
            created_at=_NOW,
        )
        uow = _Uow(case, pack)
        service = ExternalResearchHandoffService(lambda: uow, lambda: _NOW)

        run = service.queue(
            case_id=_CASE_ID,
            evidence_pack_id=_PACK_ID,
            playbook=ResearchPlaybook(
                playbook_key="etf_medium_term_assessment", playbook_version="v0.1.0"
            ),
        )

        self.assertEqual(run.status.value, "queued")
        self.assertEqual(uow.research_cases.case.status.value, "ready")
        self.assertEqual(uow.commits, 1)

    def test_execute_runs_existing_orchestration_with_fake_runner(self):
        pack = _pack()
        case = ResearchCase(
            case_id=_CASE_ID,
            instrument_id=_INSTRUMENT_ID,
            as_of_date=pack.case.as_of_date,
            question=pack.case.question,
            horizon=pack.case.horizon,
            status=ResearchCaseStatus.DRAFT,
            created_at=_NOW,
        )
        uow = _Uow(case, pack)
        playbook = ResearchPlaybook(
            playbook_key="etf_medium_term_assessment", playbook_version="v0.1.0"
        )
        evidence_id = next(factor.evidence_id for factor in pack.factors if factor.evidence_id)
        draft = ResearchRunnerDraft(
            conclusion="Fake JiuwenSwarm conclusion",
            risks=("data_risk",),
            evidence_ids=(evidence_id,),
            report_markdown="# Fake report",
            model_key="fake-model",
            model_version="fake-v1",
            playbook_version=playbook.playbook_version,
            adapter_version="fake-adapter-v1",
            created_at=_NOW,
        )

        class _FakeRunner:
            runner_key = "jiuwenswarm-runner-v1"
            adapter_version = "fake-adapter-v1"

            def run_with_identity(self, **_kwargs):
                return JiuwenSwarmRunOutcome(
                    request_id="fake-request",
                    session_id="fake-session",
                    acceptance=JiuwenSwarmAcceptance.ACCEPTED,
                    draft=draft,
                )

        from invest_pipeline.research_orchestration_service import (
            ResearchOrchestrationService,
        )

        orchestration = ResearchOrchestrationService(
            runner=_FakeRunner(),
            playbook=playbook,
            uow_factory=lambda: uow,
            clock=lambda: _NOW,
        )
        service = ExternalResearchHandoffService(lambda: uow, lambda: _NOW)

        outcome = service.execute(
            case_id=_CASE_ID,
            evidence_pack_id=_PACK_ID,
            playbook=playbook,
            orchestration=orchestration,
        )

        self.assertEqual(outcome.run.status, ResearchRunStatus.SUCCEEDED)
        self.assertEqual(outcome.case.status, ResearchCaseStatus.COMPLETED)
        self.assertEqual(len(uow.research_results.items), 1)


if __name__ == "__main__":
    unittest.main()
