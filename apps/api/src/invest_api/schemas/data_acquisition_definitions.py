"""Public response projection for active data-acquisition definitions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from invest_api.application.data_acquisition_definitions import (
    DataAcquisitionDefinitionView,
)


def _materialize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _materialize_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_materialize_json(item) for item in value]
    return value


class DataAcquisitionDefinitionResponse(BaseModel):
    """Minimal public envelope for one deployment-owned active definition."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    definition_key: str
    definition_version: str
    active: bool
    artifact_hash: str
    allowed_connectors: list[str]
    data_request_template: dict[str, Any]
    output_contract: str

    @classmethod
    def from_view(
        cls, view: DataAcquisitionDefinitionView
    ) -> DataAcquisitionDefinitionResponse:
        return cls(
            schema_version=view.schema_version,
            definition_key=view.definition_key,
            definition_version=view.definition_version,
            active=view.active,
            artifact_hash=view.artifact_hash,
            allowed_connectors=list(view.allowed_connectors),
            data_request_template=_materialize_json(view.data_request_template),
            output_contract=view.output_contract,
        )


__all__ = ["DataAcquisitionDefinitionResponse"]
