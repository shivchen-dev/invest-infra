"""Public projection and zero-database dependency tests for Slice 1B."""

from __future__ import annotations

from types import MappingProxyType

import pytest
from fastapi.dependencies.utils import get_dependant
from invest_api import dependencies
from invest_api.application.data_acquisition_definitions import (
    DataAcquisitionDefinitionQueryService,
    DataAcquisitionDefinitionView,
)
from invest_api.dependencies import (
    get_data_acquisition_definition_query_service,
)
from invest_api.schemas.data_acquisition_definitions import (
    DataAcquisitionDefinitionResponse,
)


def _view() -> DataAcquisitionDefinitionView:
    return DataAcquisitionDefinitionView(
        schema_version="data-acquisition-definition/1.0",
        definition_key="sector-strength-ranking",
        definition_version="1.0.0",
        active=True,
        artifact_hash="a" * 64,
        allowed_connectors=("tdx-connector", "westock-mcp"),
        data_request_template=MappingProxyType(
            {
                "definition_key": "sector-strength-ranking",
                "datasets": (
                    MappingProxyType(
                        {
                            "dataset_key": "sector-ranking",
                            "required_fields": ("sector_code", "limit_up_count"),
                        }
                    ),
                ),
            }
        ),
        output_contract="workbuddy-data-bundle/1.0",
    )


def test_response_from_view_materializes_only_public_json_data() -> None:
    response = DataAcquisitionDefinitionResponse.from_view(_view())

    assert set(type(response).model_fields) == {
        "schema_version",
        "definition_key",
        "definition_version",
        "active",
        "artifact_hash",
        "allowed_connectors",
        "data_request_template",
        "output_contract",
    }
    assert response.model_dump(mode="json") == {
        "schema_version": "data-acquisition-definition/1.0",
        "definition_key": "sector-strength-ranking",
        "definition_version": "1.0.0",
        "active": True,
        "artifact_hash": "a" * 64,
        "allowed_connectors": ["tdx-connector", "westock-mcp"],
        "data_request_template": {
            "definition_key": "sector-strength-ranking",
            "datasets": [
                {
                    "dataset_key": "sector-ranking",
                    "required_fields": ["sector_code", "limit_up_count"],
                }
            ],
        },
        "output_contract": "workbuddy-data-bundle/1.0",
    }
    assert isinstance(response.allowed_connectors, list)
    assert isinstance(response.data_request_template["datasets"], list)
    assert isinstance(response.data_request_template["datasets"][0], dict)


def test_provider_resolves_without_creating_or_accessing_a_db_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the static definition provider must not access the DB")

    monkeypatch.setattr(dependencies, "get_db_session", forbidden_call)
    monkeypatch.setattr(dependencies, "get_session_factory", forbidden_call)
    monkeypatch.setattr(dependencies, "get_settings", forbidden_call)

    dependant = get_dependant(
        path="/probe", call=get_data_acquisition_definition_query_service
    )
    service = get_data_acquisition_definition_query_service()

    assert dependant.dependencies == []
    assert isinstance(service, DataAcquisitionDefinitionQueryService)
