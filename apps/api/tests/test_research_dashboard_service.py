"""Tests for :meth:`invest_api.application.research.ResearchQueryService.get_dashboard`.

The endpoint tests in :mod:`tests.test_research_dashboard_endpoints`
mock the application service at the FastAPI boundary and verify the
HTTP contract. These tests bypass the HTTP layer: they construct the
real service against structurally-compatible mocks so they can assert
that the service itself owns the dashboard orchestration:

- exact ``count_all`` sequencing for case / run totals,
- the deterministic ``list_recent(limit=1)`` resolution of the latest
  case,
- the bounded ``recent_runs`` page
  (``DASHBOARD_RECENT_RUNS_LIMIT``),
- the empty / available evidence-status state machine,
- the freshness derivation against :func:`invest_api.clock.market_today`
  via :func:`invest_api.application.data_freshness.latest_weekday`,
- the ``data_quality`` derivation,
- the explicit ``market_status.unavailable`` slot,
- the :class:`sqlalchemy.exc.SQLAlchemyError` translation to
  :class:`ResearchQueryError`.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from invest_api import clock as clock_module
from invest_api.application.research import (
    DASHBOARD_MARKET_UNAVAILABLE_REASON,
    DASHBOARD_RECENT_RUNS_LIMIT,
    DASHBOARD_SCHEMA_VERSION,
    ResearchQueryError,
    ResearchQueryService,
)
from sqlalchemy.exc import OperationalError


def _case_shim(*, case_id, as_of_date, created_at=None):
    """Return a structurally-compatible ``ResearchCase`` shim."""

    return SimpleNamespace(
        case_id=case_id,
        instrument_id=SimpleNamespace(value=uuid4()),
        as_of_date=as_of_date,
        question="Assess medium-term risks",
        horizon="20-60d",
        status=SimpleNamespace(value="draft"),
        created_at=created_at,
        closed_at=None,
        candidate_pool_run_id=None,
    )


def _pack_shim(
    *,
    pack_id,
    schema_version="1.0.0",
    factor_set_key="etf_market_state_daily",
    factor_set_version="1.0.0",
    quality_status="complete",
    freshness_status="fresh",
):
    """Return a structurally-compatible ``EvidencePack`` shim."""

    return SimpleNamespace(
        pack_id=pack_id,
        schema_version=schema_version,
        factor_set=SimpleNamespace(key=factor_set_key, version=factor_set_version),
        data_quality=SimpleNamespace(
            quality_status=SimpleNamespace(value=quality_status),
            freshness_status=SimpleNamespace(value=freshness_status),
        ),
    )


def _run_shim(*, run_id, case_id):
    """Return a structurally-compatible ``ResearchRun`` shim."""

    return SimpleNamespace(
        run_id=run_id,
        case_id=case_id,
        evidence_pack_id=uuid4(),
        runner_key="jiuwenswarm",
        playbook_key="etf_medium_term_assessment",
        status="queued",
        attempt=1,
        started_at=None,
        finished_at=None,
        error_summary=None,
    )


def _build_repositories(
    *,
    case_count=0,
    latest_case=None,
    run_count=0,
    recent_runs=(),
    packs_by_case=None,
):
    """Return a tuple of mock repositories configured for the dashboard tests.

    ``packs_by_case`` is a mapping ``{case_id: [pack, ...]}`` keyed by
    the case UUID the dashboard probes for evidence. Cases absent from
    the mapping resolve to ``[]`` so the empty / partial branches are
    trivially driveable.
    """

    packs = packs_by_case or {}

    cases = MagicMock(name="ResearchCaseRepository")
    cases.count_all.return_value = case_count
    cases.list_recent.return_value = [latest_case] if latest_case is not None else []

    runs = MagicMock(name="ResearchRunRepository")
    runs.count_all.return_value = run_count
    runs.list_recent.return_value = list(recent_runs)

    evidence = MagicMock(name="ResearchEvidenceRepository")
    evidence.list_by_case.side_effect = lambda case_id: list(packs.get(case_id, []))

    results = MagicMock(name="ResearchResultRepository")
    return cases, evidence, runs, results


class TestEmptyDashboard:
    """Coverage for the ``data_quality == "empty"`` path."""

    def test_no_cases_or_runs_returns_empty_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(clock_module, "market_today", lambda: date(2026, 8, 7))
        cases, evidence, runs, results = _build_repositories()

        service = ResearchQueryService(cases, evidence, runs, results)
        view = service.get_dashboard()

        assert view.schema_version == DASHBOARD_SCHEMA_VERSION
        assert view.as_of_date is None
        assert view.data_quality == "empty"
        assert view.freshness == "unknown"
        assert view.market_status.state == "unavailable"
        assert view.market_status.reason == DASHBOARD_MARKET_UNAVAILABLE_REASON
        assert view.research_summary.case_count == 0
        assert view.research_summary.run_count == 0
        assert view.research_summary.latest_case is None
        assert view.evidence_status.state == "empty"
        assert view.evidence_status.case_id is None
        assert view.evidence_status.pack_id is None
        assert view.recent_runs == []

        cases.count_all.assert_called_once_with()
        runs.count_all.assert_called_once_with()
        # No cases -> no ``list_recent`` call on the case reader.
        cases.list_recent.assert_not_called()
        # ``recent_runs`` is still bounded even when there are no runs.
        runs.list_recent.assert_called_once_with(
            limit=DASHBOARD_RECENT_RUNS_LIMIT, offset=0
        )
        # No latest case -> no evidence probe.
        evidence.list_by_case.assert_not_called()


class TestPartialDashboard:
    """Coverage for the ``data_quality == "partial"`` path (case, no evidence)."""

    def test_latest_case_without_evidence_reports_empty_evidence_slot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(clock_module, "market_today", lambda: date(2026, 8, 7))
        latest_case = _case_shim(case_id=uuid4(), as_of_date=date(2026, 8, 7))
        cases, evidence, runs, results = _build_repositories(
            case_count=2, latest_case=latest_case
        )

        service = ResearchQueryService(cases, evidence, runs, results)
        view = service.get_dashboard()

        assert view.data_quality == "partial"
        assert view.freshness == "current"
        assert view.as_of_date == date(2026, 8, 7)
        assert view.research_summary.latest_case is latest_case
        assert view.evidence_status.state == "empty"
        assert view.evidence_status.case_id == latest_case.case_id
        assert view.evidence_status.pack_id is None
        assert view.evidence_status.schema_version is None
        # ``list_recent`` is invoked with limit=1 because the service
        # only needs the canonical latest case.
        cases.list_recent.assert_called_once_with(limit=1, offset=0)
        evidence.list_by_case.assert_called_once_with(latest_case.case_id)

    def test_freshness_is_stale_when_latest_case_predates_expected_weekday(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force the market clock to read "Friday 2026-08-07" so a case
        # dated 2026-07-31 (the previous Friday) is stale.
        monkeypatch.setattr(clock_module, "market_today", lambda: date(2026, 8, 7))
        latest_case = _case_shim(case_id=uuid4(), as_of_date=date(2026, 7, 31))
        cases, evidence, runs, results = _build_repositories(
            case_count=1, latest_case=latest_case
        )

        service = ResearchQueryService(cases, evidence, runs, results)
        view = service.get_dashboard()

        assert view.freshness == "stale"
        assert view.as_of_date == date(2026, 7, 31)
        assert view.data_quality == "partial"

    def test_freshness_is_current_when_latest_case_matches_expected_weekday(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(clock_module, "market_today", lambda: date(2026, 8, 7))
        latest_case = _case_shim(case_id=uuid4(), as_of_date=date(2026, 8, 7))
        cases, evidence, runs, results = _build_repositories(
            case_count=1, latest_case=latest_case
        )

        service = ResearchQueryService(cases, evidence, runs, results)
        view = service.get_dashboard()

        assert view.freshness == "current"


class TestCompleteDashboard:
    """Coverage for the ``data_quality == "complete"`` path (case + evidence)."""

    def test_latest_case_with_bound_pack_reports_available_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(clock_module, "market_today", lambda: date(2026, 8, 7))
        latest_case = _case_shim(case_id=uuid4(), as_of_date=date(2026, 8, 7))
        pack = _pack_shim(
            pack_id=uuid4(),
            quality_status="complete",
            freshness_status="fresh",
        )
        cases, evidence, runs, results = _build_repositories(
            case_count=1,
            latest_case=latest_case,
            packs_by_case={latest_case.case_id: [pack]},
        )

        service = ResearchQueryService(cases, evidence, runs, results)
        view = service.get_dashboard()

        assert view.data_quality == "complete"
        assert view.evidence_status.state == "available"
        assert view.evidence_status.case_id == latest_case.case_id
        assert view.evidence_status.pack_id == pack.pack_id
        assert view.evidence_status.schema_version == "1.0.0"
        assert view.evidence_status.factor_set_key == "etf_market_state_daily"
        assert view.evidence_status.factor_set_version == "1.0.0"
        assert view.evidence_status.quality_status == "complete"
        assert view.evidence_status.freshness_status == "fresh"

    def test_only_first_bound_pack_is_summarised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(clock_module, "market_today", lambda: date(2026, 8, 7))
        latest_case = _case_shim(case_id=uuid4(), as_of_date=date(2026, 8, 7))
        first_pack = _pack_shim(
            pack_id=uuid4(),
            quality_status="complete",
            freshness_status="fresh",
        )
        second_pack = _pack_shim(
            pack_id=uuid4(),
            schema_version="9.9.9",
            quality_status="partial",
            freshness_status="stale",
        )
        cases, evidence, runs, results = _build_repositories(
            case_count=1,
            latest_case=latest_case,
            packs_by_case={latest_case.case_id: [first_pack, second_pack]},
        )

        service = ResearchQueryService(cases, evidence, runs, results)
        view = service.get_dashboard()

        assert view.evidence_status.state == "available"
        assert view.evidence_status.pack_id == first_pack.pack_id
        assert view.evidence_status.schema_version == "1.0.0"
        assert view.evidence_status.quality_status == "complete"
        assert view.evidence_status.freshness_status == "fresh"


class TestRecentRunsBound:
    """Coverage for the bounded ``recent_runs`` list."""

    def test_recent_runs_uses_internal_constant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(clock_module, "market_today", lambda: date(2026, 8, 7))
        runs_list = [_run_shim(run_id=uuid4(), case_id=uuid4()) for _ in range(5)]
        cases, evidence, runs, results = _build_repositories(
            case_count=0, run_count=10, recent_runs=runs_list
        )

        service = ResearchQueryService(cases, evidence, runs, results)
        view = service.get_dashboard()

        assert view.recent_runs == runs_list
        runs.list_recent.assert_called_once_with(
            limit=DASHBOARD_RECENT_RUNS_LIMIT, offset=0
        )
        # Counts are exact, independent of the recent_runs bound.
        assert view.research_summary.run_count == 10


class TestSqlAlchemyErrorBoundary:
    """``SQLAlchemyError`` must be translated to ``ResearchQueryError``."""

    @pytest.mark.parametrize(
        "configure",
        [
            lambda cases, _, runs, __: setattr(
                cases.count_all, "side_effect",
                OperationalError("SELECT count", {}, Exception("boom")),
            ),
            lambda cases, evidence, runs, results: setattr(
                cases.list_recent, "side_effect",
                OperationalError("SELECT cases", {}, Exception("boom")),
            ),
            lambda cases, evidence, runs, results: setattr(
                runs.count_all, "side_effect",
                OperationalError("SELECT count", {}, Exception("boom")),
            ),
            lambda cases, evidence, runs, results: setattr(
                runs.list_recent, "side_effect",
                OperationalError("SELECT runs", {}, Exception("boom")),
            ),
            lambda cases, evidence, runs, results: setattr(
                evidence.list_by_case, "side_effect",
                OperationalError("SELECT packs", {}, Exception("boom")),
            ),
        ],
    )
    def test_translates_sqlalchemy_errors_without_details(
        self, monkeypatch: pytest.MonkeyPatch, configure
    ) -> None:
        # Use a real latest case so the evidence probe branch is also
        # exercised; ``configure`` raises from one of the repositories.
        monkeypatch.setattr(clock_module, "market_today", lambda: date(2026, 8, 7))
        latest_case = _case_shim(case_id=uuid4(), as_of_date=date(2026, 8, 7))
        pack = _pack_shim(pack_id=uuid4())
        cases, evidence, runs, results = _build_repositories(
            case_count=1,
            latest_case=latest_case,
            packs_by_case={latest_case.case_id: [pack]},
        )
        configure(cases, evidence, runs, results)

        with pytest.raises(ResearchQueryError) as exc_info:
            ResearchQueryService(cases, evidence, runs, results).get_dashboard()

        assert str(exc_info.value) == "research query failed"
        # Sanitized: no driver-level detail leaks.
        assert "boom" not in str(exc_info.value)


class TestMarketStatus:
    """``market_status`` is always the explicit ``unavailable`` slot."""

    def test_market_status_unavailable_when_no_cases(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(clock_module, "market_today", lambda: date(2026, 8, 7))
        cases, evidence, runs, results = _build_repositories()
        service = ResearchQueryService(cases, evidence, runs, results)

        view = service.get_dashboard()

        assert view.market_status.state == "unavailable"
        assert view.market_status.reason == DASHBOARD_MARKET_UNAVAILABLE_REASON

    def test_market_status_unavailable_when_complete(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(clock_module, "market_today", lambda: date(2026, 8, 7))
        latest_case = _case_shim(case_id=uuid4(), as_of_date=date(2026, 8, 7))
        pack = _pack_shim(pack_id=uuid4())
        cases, evidence, runs, results = _build_repositories(
            case_count=1,
            latest_case=latest_case,
            packs_by_case={latest_case.case_id: [pack]},
            recent_runs=[_run_shim(run_id=uuid4(), case_id=latest_case.case_id)],
            run_count=1,
        )

        service = ResearchQueryService(cases, evidence, runs, results)
        view = service.get_dashboard()

        assert view.data_quality == "complete"
        # PR-W03 never invents market / factor values: the slot must
        # stay at the explicit ``unavailable`` state regardless of
        # upstream evidence availability.
        assert view.market_status.state == "unavailable"
        assert view.market_status.reason == DASHBOARD_MARKET_UNAVAILABLE_REASON


__all__ = [
    "TestCompleteDashboard",
    "TestEmptyDashboard",
    "TestMarketStatus",
    "TestPartialDashboard",
    "TestRecentRunsBound",
    "TestSqlAlchemyErrorBoundary",
]
