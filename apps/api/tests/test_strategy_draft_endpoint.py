"""Contract tests for the read-only StrategyDraft audit endpoint."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import MappingProxyType
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from invest_api.application.strategy_drafts import (
    StrategyDraftArtifactDecodeError,
    StrategyDraftArtifactHashMismatchError,
    StrategyDraftArtifactReadError,
    StrategyDraftNotFoundError,
    StrategyDraftQueryService,
    StrategyDraftView,
)
from invest_api.dependencies import get_strategy_draft_query_service
from invest_api.main import app
from invest_domain.strategy import SourceRef

DRAFT_ID = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
PATH = f"/api/v1/strategy-drafts/{DRAFT_ID}"
TEMPLATE = "/api/v1/strategy-drafts/{draft_id}"
ARTIFACT_HASH = "a" * 64


def _view() -> StrategyDraftView:
    return StrategyDraftView(
        draft_id=DRAFT_ID,
        strategy_key="sector-strength",
        proposed_version="1.0.0",
        artifact_hash=ARTIFACT_HASH,
        strategy=MappingProxyType({"name": "Sector strength", "rules": ["breadth"]}),
        source_refs=(SourceRef(ref="https://example.invalid/source", content_hash=ARTIFACT_HASH),),
        validation_result=MappingProxyType({"status": "ok"}),
        created_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
    )


@pytest.fixture
def service() -> MagicMock:
    mock = MagicMock(spec=StrategyDraftQueryService)
    app.dependency_overrides[get_strategy_draft_query_service] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_strategy_draft_query_service, None)


def test_success_returns_verified_public_response(service: MagicMock) -> None:
    service.get_draft.return_value = _view()

    response = TestClient(app).get(PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["draft_id"] == str(DRAFT_ID)
    assert body["strategy"] == {"name": "Sector strength", "rules": ["breadth"]}
    assert body["artifact_hash"] == ARTIFACT_HASH
    assert "artifact_ref" not in json.dumps(body)
    assert "host_path" not in json.dumps(body)
    service.get_draft.assert_called_once_with(DRAFT_ID)


def test_not_found_maps_to_fixed_404(service: MagicMock) -> None:
    service.get_draft.side_effect = StrategyDraftNotFoundError(DRAFT_ID)

    response = TestClient(app).get(PATH)

    assert response.status_code == 404
    assert response.json() == {"detail": "Strategy draft not found"}


def test_read_failure_maps_to_sanitized_503(service: MagicMock) -> None:
    secret = "/srv/private/strategy.json postgres://user:hunter2@host/db"
    service.get_draft.side_effect = StrategyDraftArtifactReadError(secret)

    response = TestClient(app).get(PATH)

    assert response.status_code == 503
    assert response.json() == {"detail": "Strategy artifact unavailable"}
    assert all(value not in response.text for value in (secret, "hunter2", "/srv/private"))


@pytest.mark.parametrize(
    "failure",
    [
        StrategyDraftArtifactHashMismatchError("sha256=" + ARTIFACT_HASH),
        StrategyDraftArtifactDecodeError("content at /tmp/strategy.json is invalid"),
    ],
)
def test_invalid_artifact_maps_to_fixed_409(
    service: MagicMock, failure: RuntimeError
) -> None:
    service.get_draft.side_effect = failure

    response = TestClient(app).get(PATH)

    assert response.status_code == 409
    assert response.json() == {"detail": "Strategy artifact failed integrity validation"}
    assert ARTIFACT_HASH not in response.text
    assert "/tmp/strategy.json" not in response.text


def test_openapi_exposes_only_get_and_public_response_schema() -> None:
    path = app.openapi()["paths"][TEMPLATE]

    assert set(path) == {"get"}
    response_schema = path["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema == {
        "$ref": "#/components/schemas/StrategyDraftResponse"
    }
    serialized_schema = json.dumps(
        app.openapi()["components"]["schemas"]["StrategyDraftResponse"]
    )
    assert "artifact_ref" not in serialized_schema
    assert "host_path" not in serialized_schema
