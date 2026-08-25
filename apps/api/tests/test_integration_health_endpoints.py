"""Focused endpoint tests for ``/api/v1/integration``.

The router exposes two read-only routes (``GET /api/v1/integration/health``
and ``GET /api/v1/integration/artifacts/{artifact_id}``) that proxy
through :class:`invest_api.application.external_workflows.ExternalWorkflowQueryService`.

The tests drive the router through ``fastapi.testclient.TestClient``
with the application service replaced by a ``MagicMock`` so the HTTP
contract (status codes, response shape, missing resource 404s, invalid
UUID 422s and OpenAPI declarations) can be exercised without a live
PostgreSQL connection. The service-level tests in
:mod:`tests.test_external_workflow_service` cover the delegation
contract against mock repositories.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from invest_api.dependencies import get_external_workflow_query_service
from invest_api.main import app
from invest_domain.integration.models import (
    ExternalArtifact,
    ExternalWorkflowRun,
    IntakeStatus,
    ProducerStatus,
)

HEALTH_PATH = "/api/v1/integration/health"
ARTIFACT_TEMPLATE = "/api/v1/integration/artifacts/{artifact_id}"

HASH_A = "a" * 64


def _run(
    *,
    run_id: UUID | None = None,
    producer: str = "workbuddy",
    schema_version: str = "2.0.0",
    producer_status: ProducerStatus = ProducerStatus.SUCCEEDED,
    intake_status: IntakeStatus = IntakeStatus.ACCEPTED,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> ExternalWorkflowRun:
    return ExternalWorkflowRun(
        run_id=run_id or uuid4(),
        producer=producer,
        schema_version=schema_version,
        producer_status=producer_status,
        intake_status=intake_status,
        started_at=started_at or datetime(2026, 8, 7, 9, tzinfo=UTC),
        finished_at=finished_at or datetime(2026, 8, 7, 10, tzinfo=UTC),
        metadata={},
    )


def _artifact(
    *,
    run_id: UUID,
    artifact_id: UUID | None = None,
    logical_uri: str = "run://run-1/manifest.json",
    content_hash: str = HASH_A,
    media_type: str = "application/json",
    size_bytes: int = 256,
    created_at: datetime | None = None,
    metadata: dict | None = None,
) -> ExternalArtifact:
    return ExternalArtifact(
        artifact_id=artifact_id or uuid4(),
        run_id=run_id,
        logical_uri=logical_uri,
        content_hash=content_hash,
        media_type=media_type,
        size_bytes=size_bytes,
        created_at=created_at or datetime(2026, 8, 7, 9, 30, tzinfo=UTC),
        metadata=dict(metadata or {}),
    )


@pytest.fixture()
def external_workflow_service(
    monkeypatch: pytest.MonkeyPatch,
) -> MagicMock:
    """Inject a mock :class:`ExternalWorkflowQueryService` into the integration router.

    Overrides :func:`invest_api.dependencies.get_external_workflow_query_service`
    so the router receives a ``MagicMock`` that quacks like the
    application service. Endpoint tests configure return values and
    side effects on this mock; the service-level tests bypass the HTTP
    layer and construct the real service against mock repositories
    instead.
    """

    mock = MagicMock(name="ExternalWorkflowQueryService")
    app.dependency_overrides[get_external_workflow_query_service] = lambda: mock
    try:
        yield mock
    finally:
        app.dependency_overrides.pop(get_external_workflow_query_service, None)


class TestIntegrationHealth:
    """Coverage for the read-only health endpoint."""

    def test_health_reports_empty_state_when_no_runs(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        external_workflow_service.health.return_value = {
            "status": "healthy",
            "sample_size": 0,
            "producer_statuses": {},
            "intake_statuses": {},
            "latest_run_id": None,
        }

        response = client.get(HEALTH_PATH)

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "status": "healthy",
            "sample_size": 0,
            "producer_statuses": {},
            "intake_statuses": {},
            "latest_run_id": None,
        }
        external_workflow_service.health.assert_called_once_with()

    def test_health_aggregates_producer_and_intake_statuses(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        latest = _run()
        earlier = _run(
            producer_status=ProducerStatus.PARTIAL,
            intake_status=IntakeStatus.PARTIAL,
        )
        external_workflow_service.health.return_value = {
            "status": "healthy",
            "sample_size": 2,
            "producer_statuses": {
                ProducerStatus.SUCCEEDED.value: 1,
                ProducerStatus.PARTIAL.value: 1,
            },
            "intake_statuses": {
                IntakeStatus.ACCEPTED.value: 1,
                IntakeStatus.PARTIAL.value: 1,
            },
            "latest_run_id": latest.run_id,
        }

        response = client.get(HEALTH_PATH)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["sample_size"] == 2
        assert body["producer_statuses"] == {"succeeded": 1, "partial": 1}
        assert body["intake_statuses"] == {"accepted": 1, "partial": 1}
        assert body["latest_run_id"] == str(latest.run_id)
        # Earlier runs must not leak through the latest_run_id anchor.
        assert body["latest_run_id"] != str(earlier.run_id)

    def test_health_marks_status_degraded_when_producer_failed(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        failed = _run(producer_status=ProducerStatus.FAILED)
        external_workflow_service.health.return_value = {
            "status": "degraded",
            "sample_size": 1,
            "producer_statuses": {ProducerStatus.FAILED.value: 1},
            "intake_statuses": {failed.intake_status.value: 1},
            "latest_run_id": failed.run_id,
        }

        response = client.get(HEALTH_PATH)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["producer_statuses"] == {"failed": 1}
        assert body["latest_run_id"] == str(failed.run_id)


class TestArtifactPreview:
    """Coverage for the artifact preview endpoint and its missing/invalid inputs."""

    def test_artifact_preview_serializes_full_payload(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run_id = uuid4()
        artifact = _artifact(
            run_id=run_id,
            logical_uri="run://run-1/manifest.json",
            metadata={"source_kind": "workbuddy", "items": 3},
        )
        external_workflow_service.get_artifact.return_value = artifact

        response = client.get(ARTIFACT_TEMPLATE.format(artifact_id=artifact.artifact_id))

        assert response.status_code == 200
        body = response.json()
        assert body["artifact_id"] == str(artifact.artifact_id)
        assert body["run_id"] == str(run_id)
        assert body["logical_uri"] == "run://run-1/manifest.json"
        assert body["content_hash"] == HASH_A
        assert body["media_type"] == "application/json"
        assert body["size_bytes"] == 256
        assert body["created_at"].startswith(
            artifact.created_at.isoformat().replace("+00:00", "")
        )
        assert body["metadata"] == {"source_kind": "workbuddy", "items": 3}
        external_workflow_service.get_artifact.assert_called_once_with(artifact.artifact_id)

    def test_artifact_preview_returns_404_when_missing(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        external_workflow_service.get_artifact.return_value = None

        response = client.get(ARTIFACT_TEMPLATE.format(artifact_id=uuid4()))

        assert response.status_code == 404
        assert response.json() == {"detail": "external artifact not found"}

    def test_artifact_preview_returns_422_for_invalid_uuid(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        response = client.get("/api/v1/integration/artifacts/not-a-uuid")

        assert response.status_code == 422
        external_workflow_service.get_artifact.assert_not_called()


class TestIntegrationHealthOpenAPI:
    """The router surface is GET-only and references the contract schemas."""

    def test_health_path_declares_only_get(self) -> None:
        path = app.openapi()["paths"][HEALTH_PATH]

        assert set(path) == {"get"}
        responses = path["get"]["responses"]
        assert "200" in responses
        assert responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "IntegrationHealthResponse"
        )

    def test_artifact_path_declares_only_get(self) -> None:
        path = app.openapi()["paths"][ARTIFACT_TEMPLATE]

        assert set(path) == {"get"}
        responses = path["get"]["responses"]
        assert "200" in responses
        assert responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "ArtifactPreviewResponse"
        )
        # FastAPI surfaces 422 validation errors via HTTPValidationError.
        assert "422" in responses
        assert responses["422"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "HTTPValidationError"
        )


__all__ = [
    "ARTIFACT_TEMPLATE",
    "HEALTH_PATH",
    "TestArtifactPreview",
    "TestIntegrationHealth",
    "TestIntegrationHealthOpenAPI",
    "external_workflow_service",
]
