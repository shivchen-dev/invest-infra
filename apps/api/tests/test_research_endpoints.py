from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from invest_api.application.research import ResearchQueryError
from invest_api.dependencies import get_research_query_service
from invest_api.main import app
from invest_domain.instruments import InstrumentId
from invest_domain.research import ResearchCase, ResearchCaseStatus
from invest_domain.research.research_run import ResearchRun, ResearchRunStatus


@pytest.fixture()
def research_service():
    service = MagicMock(name="ResearchQueryService")
    app.dependency_overrides[get_research_query_service] = lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.pop(get_research_query_service, None)


def make_case():
    return ResearchCase(
        case_id=uuid4(),
        instrument_id=InstrumentId(uuid4()),
        as_of_date=date(2026, 8, 7),
        question="Assess medium-term risks",
        horizon="20-60d",
        status=ResearchCaseStatus.DRAFT,
        created_at=datetime(2026, 8, 7, 9, tzinfo=UTC),
    )


def make_run(case_id):
    return ResearchRun(
        run_id=uuid4(),
        case_id=case_id,
        evidence_pack_id=uuid4(),
        runner_key="jiuwenswarm",
        playbook_key="etf_medium_term_assessment",
        status=ResearchRunStatus.QUEUED,
        attempt=1,
    )


def test_exactly_six_frozen_research_get_routes_and_no_write_routes():
    expected = {
        "/api/v1/research-cases",
        "/api/v1/research-cases/{case_id}",
        "/api/v1/research-cases/{case_id}/evidence",
        "/api/v1/research-runs",
        "/api/v1/research-runs/{run_id}",
        "/api/v1/research-runs/{run_id}/result",
    }
    paths = app.openapi()["paths"]
    research_paths = {path: paths[path] for path in expected}

    assert set(research_paths) == expected
    assert sum(len(operations) for operations in research_paths.values()) == 6
    assert all(set(operations) == {"get"} for operations in research_paths.values())


def test_case_and_run_lists_are_bounded_and_paginated(
    client: TestClient, research_service: MagicMock
):
    case = make_case()
    run = make_run(case.case_id)
    research_service.list_cases.return_value = ([case], 3)
    research_service.list_runs.return_value = ([run], 4)

    cases = client.get("/api/v1/research-cases?limit=25&offset=2")
    runs = client.get("/api/v1/research-runs?limit=10&offset=1")

    assert cases.status_code == 200
    assert cases.json()["total"] == 3
    assert runs.status_code == 200
    assert runs.json()["total"] == 4
    research_service.list_cases.assert_called_once_with(limit=25, offset=2)
    research_service.list_runs.assert_called_once_with(limit=10, offset=1)
    assert client.get("/api/v1/research-cases?limit=101").status_code == 422
    assert client.get("/api/v1/research-runs?limit=0").status_code == 422


def test_details_and_related_resources_return_404(
    client: TestClient, research_service: MagicMock
):
    research_service.get_case.return_value = None
    research_service.get_case_evidence.return_value = None
    research_service.get_run.return_value = None
    research_service.get_run_result.return_value = None
    case_id = uuid4()
    run_id = uuid4()

    assert client.get(f"/api/v1/research-cases/{case_id}").status_code == 404
    assert client.get(f"/api/v1/research-cases/{case_id}/evidence").status_code == 404
    assert client.get(f"/api/v1/research-runs/{run_id}").status_code == 404
    assert client.get(f"/api/v1/research-runs/{run_id}/result").status_code == 404


def test_invalid_ids_return_422(client: TestClient, research_service: MagicMock):
    assert client.get("/api/v1/research-cases/not-a-uuid").status_code == 422
    assert client.get("/api/v1/research-runs/not-a-uuid/result").status_code == 422


def test_query_errors_return_sanitized_500(
    client: TestClient, research_service: MagicMock
):
    research_service.list_cases.side_effect = ResearchQueryError("password=secret")

    response = client.get("/api/v1/research-cases")

    assert response.status_code == 500
    assert response.json() == {"detail": "Research query failed"}
    assert "secret" not in response.text


def test_unsupported_write_methods_are_absent(client: TestClient):
    assert client.post("/api/v1/research-cases", json={}).status_code == 405
    assert client.patch(f"/api/v1/research-runs/{uuid4()}", json={}).status_code == 405
