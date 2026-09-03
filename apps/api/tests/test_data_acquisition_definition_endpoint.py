"""HTTP contract tests for the Slice 1B active-definition endpoint."""

from __future__ import annotations

import json
from collections.abc import Iterator
from types import MappingProxyType
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from invest_api.application.data_acquisition_definitions import (
    DataAcquisitionDefinitionArtifactDecodeError,
    DataAcquisitionDefinitionArtifactHashMismatchError,
    DataAcquisitionDefinitionArtifactIdentityError,
    DataAcquisitionDefinitionArtifactReadError,
    DataAcquisitionDefinitionNotFoundError,
    DataAcquisitionDefinitionQueryService,
    DataAcquisitionDefinitionView,
)
from invest_api.dependencies import get_data_acquisition_definition_query_service
from invest_api.main import app
from invest_api.routers.data_acquisition_definitions import (
    get_active_data_acquisition_definition,
    router,
)
from starlette.routing import Match

DEFINITION_KEY = "sector-strength-ranking"
PATH = f"/api/v1/data-acquisition-definitions/{DEFINITION_KEY}/active"
TEMPLATE = "/api/v1/data-acquisition-definitions/{definition_key}/active"
ARTIFACT_HASH = "a" * 64


def _view() -> DataAcquisitionDefinitionView:
    return DataAcquisitionDefinitionView(
        schema_version="data-acquisition-definition/1.0",
        definition_key=DEFINITION_KEY,
        definition_version="1.0.0",
        active=True,
        artifact_hash=ARTIFACT_HASH,
        allowed_connectors=("tdx-connector", "westock-mcp"),
        data_request_template=MappingProxyType(
            {
                "schema_version": "workbuddy-data-request/1.0",
                "definition_key": DEFINITION_KEY,
            }
        ),
        output_contract="workbuddy-data-bundle/1.0",
    )


@pytest.fixture
def service() -> Iterator[MagicMock]:
    mock = MagicMock(spec=DataAcquisitionDefinitionQueryService)
    app.dependency_overrides[
        get_data_acquisition_definition_query_service
    ] = lambda: mock
    try:
        yield mock
    finally:
        app.dependency_overrides.pop(
            get_data_acquisition_definition_query_service, None
        )


def test_success_returns_only_the_public_response_fields(service: MagicMock) -> None:
    service.get_active.return_value = _view()

    response = get_active_data_acquisition_definition(DEFINITION_KEY, service)

    body = response.model_dump(mode="json")
    assert set(body) == {
        "schema_version",
        "definition_key",
        "definition_version",
        "active",
        "artifact_hash",
        "allowed_connectors",
        "data_request_template",
        "output_contract",
    }
    assert body == {
        "schema_version": "data-acquisition-definition/1.0",
        "definition_key": DEFINITION_KEY,
        "definition_version": "1.0.0",
        "active": True,
        "artifact_hash": ARTIFACT_HASH,
        "allowed_connectors": ["tdx-connector", "westock-mcp"],
        "data_request_template": {
            "schema_version": "workbuddy-data-request/1.0",
            "definition_key": DEFINITION_KEY,
        },
        "output_contract": "workbuddy-data-bundle/1.0",
    }
    serialized = json.dumps(body)
    for internal_field in ("relative_path", "reader_root", "artifact_path"):
        assert internal_field not in serialized
    service.get_active.assert_called_once_with(DEFINITION_KEY)


@pytest.mark.parametrize("key", ["unknown-definition", "..%5Cprivate-artifact"])
def test_unknown_and_traversal_like_keys_return_sanitized_404(
    service: MagicMock, key: str
) -> None:
    leaked_key = key.replace("%5C", "\\")
    service.get_active.side_effect = DataAcquisitionDefinitionNotFoundError(leaked_key)

    with pytest.raises(HTTPException) as caught:
        get_active_data_acquisition_definition(leaked_key, service)

    assert caught.value.status_code == 404
    assert caught.value.detail == "Data acquisition definition not found"
    assert leaked_key not in caught.value.detail


def test_missing_artifact_returns_sanitized_404(service: MagicMock) -> None:
    service.get_active.side_effect = DataAcquisitionDefinitionNotFoundError(
        "/srv/private/missing.json"
    )

    with pytest.raises(HTTPException) as caught:
        get_active_data_acquisition_definition(DEFINITION_KEY, service)

    assert caught.value.status_code == 404
    assert caught.value.detail == "Data acquisition definition not found"
    assert "/srv/private/missing.json" not in caught.value.detail


def test_unreadable_artifact_returns_sanitized_503(service: MagicMock) -> None:
    service.get_active.side_effect = DataAcquisitionDefinitionArtifactReadError(
        "permission denied reading /srv/private/definition.json"
    )

    with pytest.raises(HTTPException) as caught:
        get_active_data_acquisition_definition(DEFINITION_KEY, service)

    assert caught.value.status_code == 503
    assert caught.value.detail == "Data acquisition definition unavailable"
    assert "permission denied" not in caught.value.detail
    assert "/srv/private/definition.json" not in caught.value.detail


@pytest.mark.parametrize(
    "failure",
    [
        DataAcquisitionDefinitionArtifactHashMismatchError(
            "expected deadbeef for /srv/private/definition.json"
        ),
        DataAcquisitionDefinitionArtifactDecodeError("invalid UTF-8 byte 0xff"),
        DataAcquisitionDefinitionArtifactDecodeError("JSON error at byte 4"),
        DataAcquisitionDefinitionArtifactDecodeError("artifact was [secret]"),
        DataAcquisitionDefinitionArtifactIdentityError(
            "catalog key differs from secret-artifact-key"
        ),
    ],
    ids=["hash", "utf8", "json", "non-object", "identity"],
)
def test_integrity_failures_return_sanitized_409(
    service: MagicMock, failure: RuntimeError
) -> None:
    service.get_active.side_effect = failure

    with pytest.raises(HTTPException) as caught:
        get_active_data_acquisition_definition(DEFINITION_KEY, service)

    assert caught.value.status_code == 409
    assert (
        caught.value.detail
        == "Data acquisition definition failed integrity validation"
    )
    assert str(failure) not in caught.value.detail


def test_openapi_exposes_exactly_the_get_operation_for_this_route() -> None:
    operations = app.openapi()["paths"][TEMPLATE]

    assert set(operations) == {"get"}
    assert operations["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {
        "$ref": "#/components/schemas/DataAcquisitionDefinitionResponse"
    }
    assert {"404", "409", "503"} <= set(operations["get"]["responses"])


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_write_verbs_are_not_exposed(service: MagicMock, method: str) -> None:
    route = next(
        route for route in router.routes if getattr(route, "path", None) == TEMPLATE
    )
    match, _ = route.matches(
        {
            "type": "http",
            "path": PATH,
            "root_path": "",
            "method": method.upper(),
            "headers": [],
        }
    )

    assert route.methods == {"GET"}
    assert match is Match.PARTIAL
    service.get_active.assert_not_called()
