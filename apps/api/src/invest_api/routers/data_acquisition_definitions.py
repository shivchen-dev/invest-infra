"""GET-only endpoint for deployment-owned data-acquisition definitions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from invest_api.application.data_acquisition_definitions import (
    DataAcquisitionDefinitionArtifactDecodeError,
    DataAcquisitionDefinitionArtifactHashMismatchError,
    DataAcquisitionDefinitionArtifactIdentityError,
    DataAcquisitionDefinitionArtifactReadError,
    DataAcquisitionDefinitionNotFoundError,
    DataAcquisitionDefinitionQueryService,
)
from invest_api.dependencies import get_data_acquisition_definition_query_service
from invest_api.schemas.data_acquisition_definitions import (
    DataAcquisitionDefinitionResponse,
)

router = APIRouter(
    prefix="/api/v1/data-acquisition-definitions",
    tags=["data-acquisition-definitions"],
)

_NOT_FOUND = "Data acquisition definition not found"
_UNAVAILABLE = "Data acquisition definition unavailable"
_INVALID = "Data acquisition definition failed integrity validation"


@router.get(
    "/{definition_key}/active",
    response_model=DataAcquisitionDefinitionResponse,
    responses={
        404: {"description": _NOT_FOUND},
        409: {"description": _INVALID},
        503: {"description": _UNAVAILABLE},
    },
)
def get_active_data_acquisition_definition(
    definition_key: str,
    service: Annotated[
        DataAcquisitionDefinitionQueryService,
        Depends(get_data_acquisition_definition_query_service),
    ],
) -> DataAcquisitionDefinitionResponse:
    try:
        view = service.get_active(definition_key)
    except DataAcquisitionDefinitionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND) from exc
    except DataAcquisitionDefinitionArtifactReadError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _UNAVAILABLE) from exc
    except (
        DataAcquisitionDefinitionArtifactHashMismatchError,
        DataAcquisitionDefinitionArtifactDecodeError,
        DataAcquisitionDefinitionArtifactIdentityError,
    ) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _INVALID) from exc
    return DataAcquisitionDefinitionResponse.from_view(view)


__all__ = ["router"]
