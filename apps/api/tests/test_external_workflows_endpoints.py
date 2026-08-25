"""Focused endpoint tests for ``/api/v1/external-workflows``.

The router exposes four read-only routes
(``list_external_workflows``, ``get_external_workflow``,
``list_external_artifacts`` and ``list_external_observations``)
that proxy through :class:`invest_api.application.external_workflows.ExternalWorkflowQueryService`.

The tests drive the routers through ``fastapi.testclient.TestClient``
with the application service replaced by a ``MagicMock`` so the HTTP
contract (status codes, response shape, pagination forwarding, missing
resource 404s, invalid UUID 422s and OpenAPI declarations) can be
exercised without a live PostgreSQL connection. The service-level
tests in :mod:`tests.test_external_workflow_service` cover the
delegation contract against mock repositories.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import MappingProxyType
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from invest_api.dependencies import get_external_workflow_query_service
from invest_api.main import app
from invest_domain.integration.models import (
    AdmissionStatus,
    ExternalArtifact,
    ExternalObservation,
    ExternalWorkflowRun,
    IntakeStatus,
    ProducerStatus,
)

LIST_PATH = "/api/v1/external-workflows"
DETAIL_TEMPLATE = "/api/v1/external-workflows/{run_id}"
ARTIFACTS_TEMPLATE = "/api/v1/external-workflows/{run_id}/artifacts"
OBSERVATIONS_TEMPLATE = "/api/v1/external-workflows/{run_id}/observations"

HASH_A = "a" * 64
HASH_B = "b" * 64


def _run(
    *,
    run_id: UUID | None = None,
    producer: str = "workbuddy",
    schema_version: str = "2.0.0",
    producer_status: ProducerStatus = ProducerStatus.SUCCEEDED,
    intake_status: IntakeStatus = IntakeStatus.ACCEPTED,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    metadata: MappingProxyType | dict | None = None,
) -> ExternalWorkflowRun:
    effective_started = started_at or datetime(2026, 8, 7, 9, tzinfo=UTC)
    effective_finished = finished_at or datetime(2026, 8, 7, 10, tzinfo=UTC)
    return ExternalWorkflowRun(
        run_id=run_id or uuid4(),
        producer=producer,
        schema_version=schema_version,
        producer_status=producer_status,
        intake_status=intake_status,
        started_at=effective_started,
        finished_at=effective_finished,
        metadata=dict(metadata or {}),
    )


def _artifact(
    *,
    run_id: UUID,
    artifact_id: UUID | None = None,
    logical_uri: str = "run://run-1/manifest.json",
    content_hash: str = HASH_A,
    media_type: str = "application/json",
    size_bytes: int = 128,
    created_at: datetime | None = None,
) -> ExternalArtifact:
    return ExternalArtifact(
        artifact_id=artifact_id or uuid4(),
        run_id=run_id,
        logical_uri=logical_uri,
        content_hash=content_hash,
        media_type=media_type,
        size_bytes=size_bytes,
        created_at=created_at or datetime(2026, 8, 7, 9, 30, tzinfo=UTC),
        metadata={},
    )


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
    metadata: MappingProxyType | dict | None = None,
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
        metadata=dict(metadata or {}),
    )


@pytest.fixture()
def external_workflow_service(
    monkeypatch: pytest.MonkeyPatch,
) -> MagicMock:
    """Inject a mock :class:`ExternalWorkflowQueryService` into the external-workflows router.

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


class TestExternalWorkflowsList:
    """Coverage for the happy-path list endpoint and pagination passthrough."""

    def test_list_serializes_runs_and_forwards_default_pagination(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        external_workflow_service.list_runs.return_value = [run]

        response = client.get(LIST_PATH)

        assert response.status_code == 200
        body = response.json()
        assert body["limit"] == 20
        assert body["offset"] == 0
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["run_id"] == str(run.run_id)
        assert item["producer"] == run.producer
        assert item["schema_version"] == run.schema_version
        assert item["producer_status"] == run.producer_status.value
        assert item["intake_status"] == run.intake_status.value
        assert item["started_at"].startswith(run.started_at.isoformat().replace("+00:00", ""))
        assert item["finished_at"].startswith(run.finished_at.isoformat().replace("+00:00", ""))
        assert item["metadata"] == {}
        external_workflow_service.list_runs.assert_called_once_with(limit=20, offset=0)

    def test_list_forwards_explicit_pagination(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        external_workflow_service.list_runs.return_value = []

        response = client.get(LIST_PATH, params={"limit": 5, "offset": 10})

        assert response.status_code == 200
        assert response.json() == {"items": [], "limit": 5, "offset": 10}
        external_workflow_service.list_runs.assert_called_once_with(limit=5, offset=10)

    def test_list_returns_empty_payload_when_no_runs(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        external_workflow_service.list_runs.return_value = []

        response = client.get(LIST_PATH)

        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["limit"] == 20
        assert response.json()["offset"] == 0

    def test_list_propagates_terminal_statuses(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        failed_run = _run(
            producer_status=ProducerStatus.FAILED,
            intake_status=IntakeStatus.REJECTED,
            finished_at=datetime(2026, 8, 7, 9, 30, tzinfo=UTC),
            metadata={"reason": "bad-batch"},
        )
        external_workflow_service.list_runs.return_value = [failed_run]

        response = client.get(LIST_PATH)

        assert response.status_code == 200
        body = response.json()
        assert body["items"][0]["producer_status"] == "failed"
        assert body["items"][0]["intake_status"] == "rejected"
        assert body["items"][0]["metadata"] == {"reason": "bad-batch"}

    def test_list_rejects_out_of_bounds_pagination(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        assert client.get(LIST_PATH, params={"limit": 0}).status_code == 422
        assert client.get(LIST_PATH, params={"limit": 101}).status_code == 422
        assert client.get(LIST_PATH, params={"offset": -1}).status_code == 422
        external_workflow_service.list_runs.assert_not_called()


class TestExternalWorkflowDetail:
    """Coverage for the per-run detail endpoint and its missing/invalid inputs."""

    def test_detail_returns_serialized_run(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        external_workflow_service.get_run.return_value = run

        response = client.get(DETAIL_TEMPLATE.format(run_id=run.run_id))

        assert response.status_code == 200
        body = response.json()
        assert body["run_id"] == str(run.run_id)
        assert body["producer"] == run.producer
        assert body["producer_status"] == run.producer_status.value
        assert body["intake_status"] == run.intake_status.value
        external_workflow_service.get_run.assert_called_once_with(run.run_id)

    def test_detail_returns_404_when_run_missing(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        external_workflow_service.get_run.return_value = None

        response = client.get(DETAIL_TEMPLATE.format(run_id=uuid4()))

        assert response.status_code == 404
        assert response.json() == {"detail": "external workflow run not found"}

    def test_detail_returns_422_for_invalid_uuid(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        response = client.get("/api/v1/external-workflows/not-a-uuid")

        assert response.status_code == 422
        external_workflow_service.get_run.assert_not_called()


class TestExternalArtifacts:
    """Coverage for the artifacts sub-route and its missing/invalid inputs."""

    def test_artifacts_returns_serialized_list(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        artifact = _artifact(run_id=run.run_id, logical_uri="run://run-1/manifest.json")
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_artifacts.return_value = [artifact]

        response = client.get(ARTIFACTS_TEMPLATE.format(run_id=run.run_id))

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        item = body[0]
        assert item["artifact_id"] == str(artifact.artifact_id)
        assert item["run_id"] == str(run.run_id)
        assert item["logical_uri"] == artifact.logical_uri
        assert item["content_hash"] == HASH_A
        assert item["media_type"] == artifact.media_type
        assert item["size_bytes"] == artifact.size_bytes
        assert item["created_at"].startswith(artifact.created_at.isoformat().replace("+00:00", ""))
        assert item["metadata"] == {}
        external_workflow_service.get_run.assert_called_once_with(run.run_id)
        external_workflow_service.list_artifacts.assert_called_once_with(
            run.run_id, limit=100, offset=0
        )

    def test_artifacts_forwards_explicit_pagination(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_artifacts.return_value = []

        response = client.get(
            ARTIFACTS_TEMPLATE.format(run_id=run.run_id),
            params={"limit": 7, "offset": 3},
        )

        assert response.status_code == 200
        assert response.json() == []
        external_workflow_service.list_artifacts.assert_called_once_with(
            run.run_id, limit=7, offset=3
        )

    def test_artifacts_returns_empty_list_for_known_run_without_artifacts(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_artifacts.return_value = []

        response = client.get(ARTIFACTS_TEMPLATE.format(run_id=run.run_id))

        assert response.status_code == 200
        assert response.json() == []

    def test_artifacts_returns_404_when_run_missing(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        external_workflow_service.get_run.return_value = None

        response = client.get(ARTIFACTS_TEMPLATE.format(run_id=uuid4()))

        assert response.status_code == 404
        assert response.json() == {"detail": "external workflow run not found"}
        external_workflow_service.list_artifacts.assert_not_called()

    def test_artifacts_returns_422_for_invalid_uuid(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        response = client.get("/api/v1/external-workflows/not-a-uuid/artifacts")

        assert response.status_code == 422
        external_workflow_service.get_run.assert_not_called()
        external_workflow_service.list_artifacts.assert_not_called()

    def test_artifacts_rejects_out_of_bounds_pagination(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_artifacts.return_value = []

        assert (
            client.get(
                ARTIFACTS_TEMPLATE.format(run_id=run.run_id), params={"limit": 0}
            ).status_code
            == 422
        )
        assert (
            client.get(
                ARTIFACTS_TEMPLATE.format(run_id=run.run_id), params={"limit": 101}
            ).status_code
            == 422
        )
        assert (
            client.get(
                ARTIFACTS_TEMPLATE.format(run_id=run.run_id), params={"offset": -1}
            ).status_code
            == 422
        )
        external_workflow_service.list_artifacts.assert_not_called()


class TestExternalObservations:
    """Coverage for the observations sub-route and its missing/invalid inputs."""

    def test_observations_returns_serialized_list(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        observation = _observation(
            run_id=run.run_id,
            admission_status=AdmissionStatus.CORROBORATED,
            symbol="510050",
        )
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_observations.return_value = [observation]

        response = client.get(OBSERVATIONS_TEMPLATE.format(run_id=run.run_id))

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["observation_id"] == str(observation.observation_id)
        assert body[0]["run_id"] == str(run.run_id)
        assert body[0]["as_of"] == observation.as_of.isoformat()
        assert body[0]["admission_status"] == "corroborated"
        assert body[0]["payload"] == {"field": "value"}
        assert body[0]["symbol"] == "510050"
        assert body[0]["candidate_status"] is None
        assert body[0]["reason"] is None
        assert body[0]["metadata"] == {}
        external_workflow_service.get_run.assert_called_once_with(run.run_id)
        external_workflow_service.list_observations.assert_called_once_with(
            run.run_id, limit=100, offset=0
        )

    def test_observations_forwards_explicit_pagination(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_observations.return_value = []

        response = client.get(
            OBSERVATIONS_TEMPLATE.format(run_id=run.run_id),
            params={"limit": 12, "offset": 4},
        )

        assert response.status_code == 200
        assert response.json() == []
        external_workflow_service.list_observations.assert_called_once_with(
            run.run_id, limit=12, offset=4
        )

    def test_observations_returns_empty_list_for_known_run_without_observations(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_observations.return_value = []

        response = client.get(OBSERVATIONS_TEMPLATE.format(run_id=run.run_id))

        assert response.status_code == 200
        assert response.json() == []

    def test_observations_returns_404_when_run_missing(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        external_workflow_service.get_run.return_value = None

        response = client.get(OBSERVATIONS_TEMPLATE.format(run_id=uuid4()))

        assert response.status_code == 404
        assert response.json() == {"detail": "external workflow run not found"}
        external_workflow_service.list_observations.assert_not_called()

    def test_observations_returns_422_for_invalid_uuid(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        response = client.get("/api/v1/external-workflows/not-a-uuid/observations")

        assert response.status_code == 422
        external_workflow_service.get_run.assert_not_called()
        external_workflow_service.list_observations.assert_not_called()


class TestExternalObservationDiagnostics:
    """Coverage for bounded ``candidate_status`` and ``reason`` diagnostics.

    The WorkBuddy / import pipeline stamps ``candidate_status`` and a short
    ``reason`` into observation ``metadata``. The endpoint must surface the
    known values verbatim, leave the fields ``null`` when absent or
    malformed, and reject overlong reasons without leaking arbitrary
    metadata, paths, or exception strings.
    """

    def test_populated_metadata_returns_pending_validation(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        observation = _observation(
            run_id=run.run_id,
            metadata={
                "candidate_index": 0,
                "candidate_status": "pending_validation",
                "strategy_id": "strategy-v1",
                "reason": "rule matched sector filter",
            },
        )
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_observations.return_value = [observation]

        response = client.get(OBSERVATIONS_TEMPLATE.format(run_id=run.run_id))

        assert response.status_code == 200
        item = response.json()[0]
        assert item["candidate_status"] == "pending_validation"
        assert item["reason"] == "rule matched sector filter"
        assert item["metadata"] == observation.metadata
        assert item["payload"] == {"field": "value"}

    def test_populated_metadata_returns_needs_symbol_resolution(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        observation = _observation(
            run_id=run.run_id,
            metadata={
                "candidate_status": "needs_symbol_resolution",
                "reason": "symbol not in resolver",
            },
        )
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_observations.return_value = [observation]

        response = client.get(OBSERVATIONS_TEMPLATE.format(run_id=run.run_id))

        assert response.status_code == 200
        item = response.json()[0]
        assert item["candidate_status"] == "needs_symbol_resolution"
        assert item["reason"] == "symbol not in resolver"

    def test_absent_metadata_leaves_diagnostics_null(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        observation = _observation(
            run_id=run.run_id,
            metadata={"strategy_id": "strategy-v1"},
        )
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_observations.return_value = [observation]

        response = client.get(OBSERVATIONS_TEMPLATE.format(run_id=run.run_id))

        assert response.status_code == 200
        item = response.json()[0]
        assert item["candidate_status"] is None
        assert item["reason"] is None

    def test_unknown_candidate_status_collapses_to_null(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        observation = _observation(
            run_id=run.run_id,
            metadata={"candidate_status": "approved", "reason": "trusted source"},
        )
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_observations.return_value = [observation]

        response = client.get(OBSERVATIONS_TEMPLATE.format(run_id=run.run_id))

        assert response.status_code == 200
        item = response.json()[0]
        assert item["candidate_status"] is None
        assert item["reason"] == "trusted source"

    def test_non_string_candidate_status_collapses_to_null(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        observation = _observation(
            run_id=run.run_id,
            metadata={"candidate_status": 42, "reason": "x" * 5},
        )
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_observations.return_value = [observation]

        response = client.get(OBSERVATIONS_TEMPLATE.format(run_id=run.run_id))

        assert response.status_code == 200
        item = response.json()[0]
        assert item["candidate_status"] is None
        assert item["reason"] == "x" * 5

    def test_overlong_reason_collapses_to_null(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        observation = _observation(
            run_id=run.run_id,
            metadata={
                "candidate_status": "pending_validation",
                "reason": "x" * 201,
            },
        )
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_observations.return_value = [observation]

        response = client.get(OBSERVATIONS_TEMPLATE.format(run_id=run.run_id))

        assert response.status_code == 200
        item = response.json()[0]
        assert item["candidate_status"] == "pending_validation"
        assert item["reason"] is None

    def test_non_string_reason_collapses_to_null(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        observation = _observation(
            run_id=run.run_id,
            metadata={
                "candidate_status": "pending_validation",
                "reason": {"internal": "should not leak"},
            },
        )
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_observations.return_value = [observation]

        response = client.get(OBSERVATIONS_TEMPLATE.format(run_id=run.run_id))

        assert response.status_code == 200
        item = response.json()[0]
        assert item["candidate_status"] == "pending_validation"
        assert item["reason"] is None

    def test_blank_reason_collapses_to_null(
        self,
        client: TestClient,
        external_workflow_service: MagicMock,
    ) -> None:
        run = _run()
        observation = _observation(
            run_id=run.run_id,
            metadata={
                "candidate_status": "pending_validation",
                "reason": "   ",
            },
        )
        external_workflow_service.get_run.return_value = run
        external_workflow_service.list_observations.return_value = [observation]

        response = client.get(OBSERVATIONS_TEMPLATE.format(run_id=run.run_id))

        assert response.status_code == 200
        item = response.json()[0]
        assert item["candidate_status"] == "pending_validation"
        assert item["reason"] is None


class TestExternalWorkflowsOpenAPI:
    """The router surface is GET-only and references the contract schemas."""

    def test_external_workflows_declare_only_get_operations(self) -> None:
        paths = app.openapi()["paths"]
        external_paths = {
            path: paths[path]
            for path in (
                LIST_PATH,
                DETAIL_TEMPLATE,
                ARTIFACTS_TEMPLATE,
                OBSERVATIONS_TEMPLATE,
            )
        }

        assert set(external_paths) == {
            LIST_PATH,
            DETAIL_TEMPLATE,
            ARTIFACTS_TEMPLATE,
            OBSERVATIONS_TEMPLATE,
        }
        assert all(set(operations) == {"get"} for operations in external_paths.values())

    def test_list_path_references_run_list_response_schema(self) -> None:
        responses = app.openapi()["paths"][LIST_PATH]["get"]["responses"]

        assert responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "ExternalWorkflowRunListResponse"
        )

    def test_detail_path_references_run_response_schema(self) -> None:
        responses = app.openapi()["paths"][DETAIL_TEMPLATE]["get"]["responses"]

        assert responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "ExternalWorkflowRunResponse"
        )

    def test_artifacts_path_references_artifact_array(self) -> None:
        schema = (
            app.openapi()["paths"][ARTIFACTS_TEMPLATE]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
        )

        assert schema["type"] == "array"
        assert schema["items"]["$ref"].endswith("ExternalArtifactResponse")

    def test_observations_path_references_observation_array(self) -> None:
        schema = (
            app.openapi()["paths"][OBSERVATIONS_TEMPLATE]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
        )

        assert schema["type"] == "array"
        assert schema["items"]["$ref"].endswith("ExternalObservationResponse")

    def test_observation_response_schema_declares_bounded_diagnostics(self) -> None:
        components = app.openapi()["components"]["schemas"]
        observation_schema = components["ExternalObservationResponse"]
        properties = observation_schema["properties"]

        candidate_status = properties["candidate_status"]
        reason = properties["reason"]

        assert candidate_status == {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "title": "Candidate Status",
        }
        assert reason == {
            "anyOf": [{"type": "string", "maxLength": 200}, {"type": "null"}],
            "title": "Reason",
        }


__all__ = [
    "LIST_PATH",
    "DETAIL_TEMPLATE",
    "ARTIFACTS_TEMPLATE",
    "OBSERVATIONS_TEMPLATE",
    "TestExternalArtifacts",
    "TestExternalWorkflowDetail",
    "TestExternalWorkflowsList",
    "TestExternalWorkflowsOpenAPI",
    "TestExternalObservations",
    "external_workflow_service",
]
