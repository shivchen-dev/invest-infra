"""Read-only opportunity radar over external observations."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from invest_api.application.external_workflows import ExternalWorkflowQueryService
from invest_api.dependencies import get_external_workflow_query_service
from invest_api.routers.external_workflows import _observation
from invest_api.schemas.external_workflows import ExternalObservationResponse

router = APIRouter(prefix="/api/v1/opportunity-radar", tags=["opportunity-radar"])
AdmissionFilter = Literal["pending", "corroborated", "admitted", "rejected", "conflict"]


@router.get("", response_model=list[ExternalObservationResponse])
def list_opportunity_radar(
    service: Annotated[ExternalWorkflowQueryService, Depends(get_external_workflow_query_service)],
    admission_status: Annotated[AdmissionFilter | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ExternalObservationResponse]:
    status = None
    if admission_status is not None:
        from invest_domain.integration import AdmissionStatus

        status = AdmissionStatus(admission_status)
    return [
        _observation(item)
        for item in service.list_radar(status=status, limit=limit, offset=offset)
    ]


__all__ = ["router"]
