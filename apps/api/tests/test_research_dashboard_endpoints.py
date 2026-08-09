"""HTTP-seam tests for the ``GET /api/v1/research-dashboard`` endpoint (PR-W03).

The endpoint is exercised through ``fastapi.testclient.TestClient`` with
the application-layer :class:`ResearchQueryService` replaced through a
``MagicMock`` so the handler can be driven without a live PostgreSQL
connection. The router-level tests assert the HTTP contract (status
codes, response shape, sanitized 500 detail, deterministic ordering,
the explicit ``market_status.unavailable`` state and the bounded
``recent_runs`` list) without touching the real service logic.

The service-level orchestration (``count_all`` vs ``list_recent``
sequencing, freshness derivation, evidence-status state machine and
the ``SQLAlchemyError`` boundary) is exercised in
:mod:`tests.test_research_dashboard_service`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from invest_api.application.research import (
    DASHBOARD_MARKET_UNAVAILABLE_REASON,
    DASHBOARD_RECENT_RUNS_LIMIT,
    DASHBOARD_SCHEMA_VERSION,
    ResearchDashboardEvidenceStatusView,
    ResearchDashboardMarketStatusView,
    ResearchDashboardResearchSummaryView,
    ResearchDashboardView,
    ResearchQueryError,
)
from invest_domain.instruments import InstrumentId
from invest_domain.research import ResearchCase, ResearchCaseStatus
from invest_domain.research.research_run import ResearchRun, ResearchRunStatus

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


ENDPOINT = "/api/v1/research-dashboard"


def _view(
    *,
    schema_version: str = DASHBOARD_SCHEMA_VERSION,
    as_of_date: date | None = None,
    data_quality: str = "empty",
    freshness: str = "unknown",
    market_status: ResearchDashboardMarketStatusView | None = None,
    research_summary: ResearchDashboardResearchSummaryView | None = None,
    evidence_status: ResearchDashboardEvidenceStatusView | None = None,
    recent_runs: list | None = None,
) -> ResearchDashboardView:
    """Build a :class:`ResearchDashboardView` for endpoint tests."""

    return ResearchDashboardView(
        schema_version=schema_version,
        as_of_date=as_of_date,
        data_quality=data_quality,
        freshness=freshness,
        market_status=market_status
        or ResearchDashboardMarketStatusView(
            state="unavailable",
            reason=DASHBOARD_MARKET_UNAVAILABLE_REASON,
        ),
        research_summary=research_summary
        or ResearchDashboardResearchSummaryView(
            case_count=0, run_count=0, latest_case=None
        ),
        evidence_status=evidence_status
        or ResearchDashboardEvidenceStatusView(
            state="empty",
            case_id=None,
            pack_id=None,
            schema_version=None,
            factor_set_key=None,
            factor_set_version=None,
            quality_status=None,
            freshness_status=None,
        ),
        recent_runs=list(recent_runs or []),
    )


def make_case(as_of_date: date | None = None) -> ResearchCase:
    """Return a real :class:`ResearchCase` for the router's ``from_domain`` mapper."""

    return ResearchCase(
        case_id=uuid4(),
        instrument_id=InstrumentId(uuid4()),
        as_of_date=as_of_date or date(2026, 8, 7),
        question="Assess medium-term risks",
        horizon="20-60d",
        status=ResearchCaseStatus.DRAFT,
        created_at=datetime(2026, 8, 7, 9, tzinfo=UTC),
    )


def make_run(case_id) -> ResearchRun:
    """Return a real :class:`ResearchRun` for the router's ``from_domain`` mapper."""

    return ResearchRun(
        run_id=uuid4(),
        case_id=case_id,
        evidence_pack_id=uuid4(),
        runner_key="jiuwenswarm",
        playbook_key="etf_medium_term_assessment",
        status=ResearchRunStatus.QUEUED,
        attempt=1,
    )


class TestResearchDashboardEndpoint:
    """Coverage for the ``GET /api/v1/research-dashboard`` HTTP contract."""

    def test_empty_state_reports_explicit_unavailable_and_unknown(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        research_service.get_dashboard.return_value = _view()

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["schema_version"] == DASHBOARD_SCHEMA_VERSION
        assert body["as_of_date"] is None
        assert body["data_quality"] == "empty"
        assert body["freshness"] == "unknown"
        assert body["market_status"] == {
            "state": "unavailable",
            "reason": DASHBOARD_MARKET_UNAVAILABLE_REASON,
        }
        assert body["research_summary"] == {
            "case_count": 0,
            "run_count": 0,
            "latest_case": None,
        }
        assert body["evidence_status"] == {
            "state": "empty",
            "case_id": None,
            "pack_id": None,
            "schema_version": None,
            "factor_set_key": None,
            "factor_set_version": None,
            "quality_status": None,
            "freshness_status": None,
        }
        assert body["recent_runs"] == []
        assert body["generated_at"].endswith("Z")
        research_service.get_dashboard.assert_called_once_with()

    def test_partial_state_reports_empty_evidence_with_case_id(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        case = make_case()
        summary = ResearchDashboardResearchSummaryView(
            case_count=2, run_count=0, latest_case=case
        )
        evidence = ResearchDashboardEvidenceStatusView(
            state="empty",
            case_id=case.case_id,
            pack_id=None,
            schema_version=None,
            factor_set_key=None,
            factor_set_version=None,
            quality_status=None,
            freshness_status=None,
        )
        view = _view(
            as_of_date=case.as_of_date,
            data_quality="partial",
            freshness="current",
            research_summary=summary,
            evidence_status=evidence,
        )
        research_service.get_dashboard.return_value = view

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["data_quality"] == "partial"
        assert body["freshness"] == "current"
        assert body["as_of_date"] == case.as_of_date.isoformat()
        assert body["evidence_status"]["state"] == "empty"
        assert body["evidence_status"]["case_id"] == str(case.case_id)
        assert body["evidence_status"]["pack_id"] is None
        latest = body["research_summary"]["latest_case"]
        assert latest["case_id"] == str(case.case_id)
        assert latest["as_of_date"] == case.as_of_date.isoformat()
        assert body["recent_runs"] == []

    def test_complete_state_summarises_first_bound_pack_only(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        case = make_case()
        pack_id = uuid4()
        evidence = ResearchDashboardEvidenceStatusView(
            state="available",
            case_id=case.case_id,
            pack_id=pack_id,
            schema_version="1.0.0",
            factor_set_key="etf_market_state_daily",
            factor_set_version="1.0.0",
            quality_status="complete",
            freshness_status="fresh",
        )
        runs = [make_run(case.case_id) for _ in range(3)]
        summary = ResearchDashboardResearchSummaryView(
            case_count=4, run_count=3, latest_case=case
        )
        view = _view(
            as_of_date=case.as_of_date,
            data_quality="complete",
            freshness="current",
            research_summary=summary,
            evidence_status=evidence,
            recent_runs=runs,
        )
        research_service.get_dashboard.return_value = view

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["data_quality"] == "complete"
        assert body["evidence_status"]["state"] == "available"
        assert body["evidence_status"]["pack_id"] == str(pack_id)
        assert body["evidence_status"]["schema_version"] == "1.0.0"
        assert body["evidence_status"]["factor_set_key"] == "etf_market_state_daily"
        assert body["evidence_status"]["factor_set_version"] == "1.0.0"
        assert body["evidence_status"]["quality_status"] == "complete"
        assert body["evidence_status"]["freshness_status"] == "fresh"
        assert body["research_summary"]["case_count"] == 4
        assert body["research_summary"]["run_count"] == 3
        assert len(body["recent_runs"]) == 3
        # The first run is the most-recent row, surfaced in deterministic
        # ``list_recent`` order. The router maps domain -> response via
        # :meth:`ResearchRunResponse.from_domain`, which uses Pydantic's
        # ``model_validate(..., from_attributes=True)`` so the JSON
        # schema must include the documented run fields.
        first = body["recent_runs"][0]
        assert first["case_id"] == str(case.case_id)
        assert first["runner_key"] == "jiuwenswarm"
        assert first["playbook_key"] == "etf_medium_term_assessment"
        assert first["status"] == "queued"
        assert first["attempt"] == 1
        assert first["started_at"] is None
        assert first["finished_at"] is None
        assert first["error_summary"] is None

    def test_recent_runs_is_bounded_by_internal_constant(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        case = make_case()
        runs = [make_run(case.case_id) for _ in range(DASHBOARD_RECENT_RUNS_LIMIT)]
        evidence = ResearchDashboardEvidenceStatusView(
            state="empty",
            case_id=case.case_id,
            pack_id=None,
            schema_version=None,
            factor_set_key=None,
            factor_set_version=None,
            quality_status=None,
            freshness_status=None,
        )
        summary = ResearchDashboardResearchSummaryView(
            case_count=1, run_count=20, latest_case=case
        )
        view = _view(
            research_summary=summary,
            evidence_status=evidence,
            recent_runs=runs,
        )
        research_service.get_dashboard.return_value = view

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert len(body["recent_runs"]) == DASHBOARD_RECENT_RUNS_LIMIT
        # Counts are exact, not bounded by the recent_runs cap.
        assert body["research_summary"]["run_count"] == 20
        assert body["research_summary"]["case_count"] == 1

    def test_market_status_is_always_unavailable(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        # Even when the rest of the dashboard reports complete state,
        # PR-W03 never invents market / factor values: the slot stays
        # at ``{"state": "unavailable", "reason": "..."}`` so the UI
        # can render a stable empty placeholder.
        case = make_case()
        evidence = ResearchDashboardEvidenceStatusView(
            state="available",
            case_id=case.case_id,
            pack_id=uuid4(),
            schema_version="1.0.0",
            factor_set_key="etf_market_state_daily",
            factor_set_version="1.0.0",
            quality_status="complete",
            freshness_status="fresh",
        )
        summary = ResearchDashboardResearchSummaryView(
            case_count=1, run_count=1, latest_case=case
        )
        view = _view(
            data_quality="complete",
            freshness="current",
            research_summary=summary,
            evidence_status=evidence,
            recent_runs=[make_run(case.case_id)],
        )
        research_service.get_dashboard.return_value = view

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["market_status"] == {
            "state": "unavailable",
            "reason": DASHBOARD_MARKET_UNAVAILABLE_REASON,
        }

    def test_generated_at_is_utc_aware_timestamp(
        self,
        client: TestClient,
        research_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``generated_at`` is stamped by the router and must remain UTC-aware."""

        captured: dict[str, object] = {}

        class _AwareDatetime(datetime):
            @classmethod
            def now(cls, tz: object | None = None) -> datetime:
                captured["tz"] = tz
                return datetime(2026, 8, 9, 1, 15, tzinfo=tz)  # type: ignore[arg-type]

        from invest_api.routers import research as research_router_module

        monkeypatch.setattr(research_router_module, "datetime", _AwareDatetime)

        research_service.get_dashboard.return_value = _view()

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        assert captured["tz"] is UTC
        body = response.json()
        assert body["generated_at"].endswith("Z")
        assert body["generated_at"].startswith("2026-08-09T")


class TestResearchDashboardSanitization:
    """A :class:`ResearchQueryError` must surface as a sanitized HTTP 500."""

    def test_returns_500_with_sanitized_detail(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        research_service.get_dashboard.side_effect = ResearchQueryError(
            "connection string: postgres://user:secret@host/db"
        )

        response = client.get(ENDPOINT)

        assert response.status_code == 500
        assert response.json() == {"detail": "Research query failed"}
        assert "secret" not in response.text
        assert "ResearchQueryError" not in response.text


class TestResearchDashboardMethodSurface:
    """The :class:`ResearchQueryService` must expose ``get_dashboard``."""

    def test_service_exposes_get_dashboard(self, research_service: MagicMock) -> None:
        # The fixture installs a MagicMock that quacks like the service,
        # so the attribute must exist for the router to wire through.
        assert hasattr(research_service, "get_dashboard")


__all__ = [
    "TestResearchDashboardEndpoint",
    "TestResearchDashboardMethodSurface",
    "TestResearchDashboardSanitization",
]
