"""HTTP contract tests for the Slice 1A active StrategyVersion endpoint.

The endpoint under test is ``GET /api/v1/strategies/{strategy_key}/active``
which returns the verified public envelope for the unique active
version of the requested ``strategy_key``. Error mapping is fixed and
sanitised:

- :class:`StrategyVersionNotFoundError` -> 404
- :class:`StrategyVersionArtifactReadError` -> 503
- :class:`StrategyVersionArtifactHashMismatchError` /
  :class:`StrategyVersionArtifactDecodeError` -> 409

The tests use :func:`fastapi.Depends` overrides through
``app.dependency_overrides`` to inject a mocked
:class:`StrategyVersionQueryService`, so no real database or
filesystem access happens during these contract tests.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from types import MappingProxyType
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from invest_api.application.strategy_versions import (
    StrategyVersionArtifactDecodeError,
    StrategyVersionArtifactHashMismatchError,
    StrategyVersionArtifactReadError,
    StrategyVersionNotFoundError,
    StrategyVersionQueryService,
    StrategyVersionView,
)
from invest_api.dependencies import get_strategy_version_query_service
from invest_api.main import app
from invest_api.strategy_artifacts import READ_ERROR

STRATEGY_KEY = "sector-strength-ranking"
PATH = f"/api/v1/strategies/{STRATEGY_KEY}/active"
TEMPLATE = "/api/v1/strategies/{strategy_key}/active"

ARTIFACT_HASH = "a" * 64
APPROVED = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
ACTIVATED = datetime(2026, 8, 26, 13, 0, tzinfo=UTC)

GOVERNANCE_FIELDS: tuple[str, ...] = (
    "artifact_ref",
    "decision_ref",
    "decision_hash",
    "decided_by_agent_id",
    "source_hashes",
    "audit_id",
    "strategy_id",
)

AUTHORED_STRATEGY: dict[str, object] = {
    "schema_version": "strategy-proposal/1.0",
    "strategy_key": STRATEGY_KEY,
    "name": "Sector strength ranking",
    "rules": ["rank-by-breadth"],
}


def _view(strategy: dict[str, object] | None = None) -> StrategyVersionView:
    body = strategy if strategy is not None else AUTHORED_STRATEGY
    return StrategyVersionView(
        strategy_key=STRATEGY_KEY,
        version="2.0.0",
        active=True,
        artifact_hash=ARTIFACT_HASH,
        strategy=MappingProxyType(body),
        approved_at=APPROVED,
        activated_at=ACTIVATED,
    )


@pytest.fixture
def service() -> Iterator[MagicMock]:
    mock = MagicMock(spec=StrategyVersionQueryService)
    app.dependency_overrides[get_strategy_version_query_service] = lambda: mock
    try:
        yield mock
    finally:
        app.dependency_overrides.pop(get_strategy_version_query_service, None)


def test_success_returns_verified_public_response(service: MagicMock) -> None:
    service.get_active.return_value = _view()

    response = TestClient(app).get(PATH)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "schema_version",
        "strategy_key",
        "version",
        "active",
        "artifact_hash",
        "strategy",
        "approved_at",
        "activated_at",
    }
    assert body["strategy_key"] == STRATEGY_KEY
    assert body["version"] == "2.0.0"
    assert body["active"] is True
    assert body["schema_version"] == "strategy-proposal/1.0"
    assert body["artifact_hash"] == ARTIFACT_HASH
    assert body["strategy"] == AUTHORED_STRATEGY
    assert body["approved_at"].startswith("2026-08-26T12:00:00")
    assert body["activated_at"].startswith("2026-08-26T13:00:00")
    serialized = json.dumps(body)
    for forbidden in GOVERNANCE_FIELDS:
        assert forbidden not in serialized
    service.get_active.assert_called_once_with(STRATEGY_KEY)


def test_success_preserves_complete_authored_strategy_json(
    service: MagicMock,
) -> None:
    strategy = {
        "schema_version": "strategy-proposal/1.0",
        "rules": [
            {
                "id": "R-A1",
                "reference_marker": r"Z:\workbuddy\strategy\inbox\fixture.json",
                "absolute_url": "https://example.test/source",
                "narrative": "treat /srv/private/source.json as untrusted",
            },
        ],
        "nested": {
            "values": [
                {"label": "internal", "host_path": "/srv/private/x.json"},
                "relative/business-label",
            ],
        },
    }
    service.get_active.return_value = _view(strategy)

    response = TestClient(app).get(PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == strategy
    assert (
        body["strategy"]["rules"][0]["reference_marker"]
        == r"Z:\workbuddy\strategy\inbox\fixture.json"
    )
    assert (
        body["strategy"]["nested"]["values"][0]["host_path"]
        == "/srv/private/x.json"
    )
    assert body["strategy"]["nested"]["values"][1] == "relative/business-label"


def test_unknown_key_maps_to_fixed_sanitized_404(service: MagicMock) -> None:
    service.get_active.side_effect = StrategyVersionNotFoundError("missing-key")

    response = TestClient(app).get("/api/v1/strategies/missing-key/active")

    assert response.status_code == 404
    assert response.json() == {"detail": "Strategy version not found"}
    assert "missing-key" not in response.text


@pytest.mark.parametrize(
    "leak_message,forbidden",
    [
        pytest.param(
            "missing sector-strength-ranking/2.0.0/strategy.json",
            "sector-strength-ranking/2.0.0",
            id="artifact-ref",
        ),
        pytest.param(
            "cannot read /srv/secrets/strategy.json: permission denied",
            "/srv/secrets/strategy.json",
            id="host-path",
        ),
        pytest.param(
            "connection failed: postgres://user:hunter2@host/db",
            "hunter2",
            id="credential",
        ),
        pytest.param(
            "ENOSYS: native strategy loader unavailable",
            "native strategy loader",
            id="raw-os-error",
        ),
    ],
)
def test_artifact_read_failure_maps_to_sanitized_503(
    service: MagicMock, leak_message: str, forbidden: str
) -> None:
    service.get_active.side_effect = StrategyVersionArtifactReadError(leak_message)

    response = TestClient(app).get(PATH)

    assert response.status_code == 503
    assert response.json() == {"detail": "Strategy artifact unavailable"}
    assert forbidden not in response.text
    assert READ_ERROR not in response.text
    for governance in GOVERNANCE_FIELDS:
        assert governance not in response.text


@pytest.mark.parametrize(
    "failure,forbidden",
    [
        pytest.param(
            StrategyVersionArtifactHashMismatchError(
                "sha256=" + "a" * 64 + " expected " + "b" * 64
            ),
            "sha256=",
            id="hash-mismatch",
        ),
        pytest.param(
            StrategyVersionArtifactDecodeError(
                "invalid utf-8 byte 0xff at offset 3 of /tmp/strategy.json"
            ),
            "/tmp/strategy.json",
            id="invalid-utf8",
        ),
        pytest.param(
            StrategyVersionArtifactDecodeError(
                "malformed JSON at position 0 of /srv/private/strategy.json"
            ),
            "/srv/private/strategy.json",
            id="malformed-json",
        ),
        pytest.param(
            StrategyVersionArtifactDecodeError(
                "non-object payload [1, 2, 3] cannot be enforced as JSON object"
            ),
            "non-object payload",
            id="non-object-json",
        ),
    ],
)
def test_integrity_failure_maps_to_fixed_sanitized_409(
    service: MagicMock, failure: StrategyVersionArtifactHashMismatchError
    | StrategyVersionArtifactDecodeError, forbidden: str
) -> None:
    service.get_active.side_effect = failure

    response = TestClient(app).get(PATH)

    assert response.status_code == 409
    assert response.json() == {"detail": "Strategy artifact failed integrity validation"}
    assert forbidden not in response.text
    for governance in GOVERNANCE_FIELDS:
        assert governance not in response.text


def test_openapi_declares_fixed_sanitized_error_responses() -> None:
    spec = app.openapi()
    path = spec["paths"][TEMPLATE]

    assert set(path) == {"get"}
    for verb in ("post", "put", "patch", "delete"):
        assert verb not in path

    responses = path["get"]["responses"]
    assert set(responses) == {"200", "404", "409", "422", "503"}

    success_schema = responses["200"]["content"]["application/json"]["schema"]
    assert success_schema == {
        "$ref": "#/components/schemas/StrategyVersionResponse"
    }

    expected_error_descriptions = {
        "404": "Strategy version not found",
        "409": "Strategy artifact failed integrity validation",
        "503": "Strategy artifact unavailable",
    }
    for status_code, description in expected_error_descriptions.items():
        assert responses[status_code]["description"] == description

    validation_schema = responses["422"]["content"]["application/json"]["schema"]
    assert validation_schema == {"$ref": "#/components/schemas/HTTPValidationError"}

    serialized_path = json.dumps(path)
    for governance in GOVERNANCE_FIELDS:
        assert governance not in serialized_path
    for status_code, description in expected_error_descriptions.items():
        for forbidden in (*GOVERNANCE_FIELDS, "/srv/", "/tmp/", "postgres://"):
            assert forbidden not in description, (
                f"response {status_code} description leaks {forbidden!r}"
            )

    schema = spec["components"]["schemas"]["StrategyVersionResponse"]
    assert set(schema["properties"]) == {
        "schema_version",
        "strategy_key",
        "version",
        "active",
        "artifact_hash",
        "strategy",
        "approved_at",
        "activated_at",
    }
    serialized_schema = json.dumps(schema)
    for forbidden in (*GOVERNANCE_FIELDS, "/srv/", "/tmp/", "postgres://"):
        assert forbidden not in serialized_schema

    http_validation_error = json.dumps(
        spec["components"]["schemas"]["HTTPValidationError"]
    )
    validation_error = json.dumps(spec["components"]["schemas"]["ValidationError"])
    for forbidden in (*GOVERNANCE_FIELDS, "/srv/", "/tmp/", "postgres://"):
        assert forbidden not in http_validation_error
        assert forbidden not in validation_error


__all__ = [
    "test_artifact_read_failure_maps_to_sanitized_503",
    "test_integrity_failure_maps_to_fixed_sanitized_409",
    "test_openapi_declares_fixed_sanitized_error_responses",
    "test_success_returns_verified_public_response",
    "test_success_preserves_complete_authored_strategy_json",
    "test_unknown_key_maps_to_fixed_sanitized_404",
]
