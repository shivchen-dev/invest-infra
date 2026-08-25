"""Focused endpoint tests for ``/api/v1/opportunity-radar``.

The router exposes a single read-only ``GET /api/v1/opportunity-radar``
route that proxies through
:class:`invest_api.application.external_workflows.ExternalWorkflowQueryService`
with an optional ``admission_status`` filter and bounded
``limit``/``offset`` pagination.

The tests drive the router through ``fastapi.testclient.TestClient``
with the application service replaced by a ``MagicMock`` so the HTTP
contract (status codes, response shape, pagination forwarding,
admission-status enum validation, pagination bounds and OpenAPI
declarations) can be exercised without a live PostgreSQL connection.
The service-level tests in :mod:`tests.test_external_workflow_service`
cover the delegation contract against mock repositories.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from invest_api.dependencies import get_external_workflow_query_service
from invest_api.main import app
from invest_domain.integration.models import (
    AdmissionStatus,
    ExternalObservation,
)

RADAR_PATH = "/api/v1/opportunity-radar"


def _observation(
    *,
    run_id: UUID,
    observation_id: UUID | None = None,
    artifact_id: UUID | None = None,
    observed_at: datetime | None = None,
    as_of: date | None = None,
    source_uri: str = "workbuddy://run-1/observation-1",
    producer: str = "workbuddy",
    payload: dict | None = None,
    symbol: str | None = "510050",
    instrument_id: UUID | None = None,
    admission_status: AdmissionStatus = AdmissionStatus.PENDING,
) -> ExternalObservation:
    return ExternalObservation(
        observation_id=observation_id or uuid4(),
        run_id=run_id,
        artifact_id=artifact_id,
        observed_at=observed_at or datetime(2026, 8, 7, 9, 45, tzinfo=UTC),
        as_of=as_of or date(2026, 8, 7),
        source_uri=source_uri,
        producer=producer,
        payload=dict(payload or {"field": "value"}),
        symbol=symbol,
        instrument_id=instrument_id,
        admission_status=admission_status,
        metadata={},
    )


@pytest.fixture()
def external_workflow_service(
    monkeypatch: pytest.MonkeyPatch,
) -> MagicMock:
    """Inject a mock :class:`ExternalWorkflowQueryService` into the routers.

    Overrides :func:`invest_api.dependencies.get_external_workflow_query_service`
    so the ``/api/v1/opportunity-radar`` (and the external-workflows)
    router receives a ``MagicMock`` that quacks like the application
    service. Endpoint tests configure return values and side effects on
    this mock; the service-level tests bypass the HTTP layer and
    construct the real service against mock repositories instead.
    """

    mock = MagicMock(name="ExternalWorkflowQueryService")
    app.dependency_overrides[get_external_workflow_query_service] = lambda: mock
    try:
        yield mock
    finally:
        app.dependency_overrides.pop(get_external_workflow_query_service, None)


class TestOpportunityRadarList:
    """Coverage for the happy-path list endpoint, pagination and admission filter."""

    def test_list_serializes_observations_with_default_pagination(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run_id = uuid4()
        observation = _observation(run_id=run_id, symbol="510050")
        external_workflow_service.list_radar.return_value = [observation]

        response = client.get(RADAR_PATH)

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 1
        item = body[0]
        assert item["observation_id"] == str(observation.observation_id)
        assert item["run_id"] == str(run_id)
        assert item["as_of"] == observation.as_of.isoformat()
        assert item["admission_status"] == "pending"
        assert item["payload"] == {"field": "value"}
        assert item["symbol"] == "510050"
        external_workflow_service.list_radar.assert_called_once_with(
            status=None, limit=50, offset=0
        )

    def test_list_forwards_explicit_pagination(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        external_workflow_service.list_radar.return_value = []

        response = client.get(RADAR_PATH, params={"limit": 25, "offset": 10})

        assert response.status_code == 200
        assert response.json() == []
        external_workflow_service.list_radar.assert_called_once_with(
            status=None, limit=25, offset=10
        )

    def test_list_forwards_each_admission_status_value(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        external_workflow_service.list_radar.return_value = []

        for status_value in ("pending", "corroborated", "admitted", "rejected", "conflict"):
            external_workflow_service.list_radar.reset_mock()
            response = client.get(
                RADAR_PATH, params={"admission_status": status_value, "limit": 5, "offset": 2}
            )

            assert response.status_code == 200, status_value
            assert response.json() == []
            external_workflow_service.list_radar.assert_called_once_with(
                status=AdmissionStatus(status_value), limit=5, offset=2
            )

    def test_list_propagates_terminal_admission_statuses(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run_id = uuid4()
        observation = _observation(
            run_id=run_id,
            admission_status=AdmissionStatus.ADMITTED,
            symbol="510050",
        )
        external_workflow_service.list_radar.return_value = [observation]

        response = client.get(RADAR_PATH)

        assert response.status_code == 200
        body = response.json()
        assert body[0]["admission_status"] == "admitted"
        external_workflow_service.list_radar.assert_called_once_with(
            status=None, limit=50, offset=0
        )

    def test_list_returns_empty_array_when_no_observations(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        external_workflow_service.list_radar.return_value = []

        response = client.get(RADAR_PATH)

        assert response.status_code == 200
        assert response.json() == []
        external_workflow_service.list_radar.assert_called_once_with(
            status=None, limit=50, offset=0
        )


class TestOpportunityRadarValidation:
    """FastAPI rejects out-of-bounds pagination and unknown admission statuses."""

    def test_list_rejects_out_of_bounds_pagination(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        assert client.get(RADAR_PATH, params={"limit": 0}).status_code == 422
        assert client.get(RADAR_PATH, params={"limit": 101}).status_code == 422
        assert client.get(RADAR_PATH, params={"offset": -1}).status_code == 422
        external_workflow_service.list_radar.assert_not_called()

    def test_list_rejects_unknown_admission_status(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        response = client.get(RADAR_PATH, params={"admission_status": "not-a-status"})

        assert response.status_code == 422
        external_workflow_service.list_radar.assert_not_called()

    def test_list_rejects_non_string_admission_status(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        response = client.get(RADAR_PATH, params={"admission_status": "PENDING"})

        assert response.status_code == 422
        external_workflow_service.list_radar.assert_not_called()


class TestOpportunityRadarOpenAPI:
    """The radar surface is a single GET and references the observation array schema."""

    def test_path_declares_only_get_operation(self) -> None:
        path = app.openapi()["paths"][RADAR_PATH]

        assert set(path) == {"get"}

    def test_list_response_references_observation_array(self) -> None:
        schema = (
            app.openapi()["paths"][RADAR_PATH]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
        )

        assert schema["type"] == "array"
        assert schema["items"]["$ref"].endswith("ExternalObservationResponse")


__all__ = [
    "RADAR_PATH",
    "TestOpportunityRadarList",
    "TestOpportunityRadarOpenAPI",
    "TestOpportunityRadarValidation",
    "external_workflow_service",
]