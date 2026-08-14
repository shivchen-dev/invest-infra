from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from invest_api.application.research_external_evidence import (
    ExternalEvidenceLinkError,
    ResearchExternalEvidenceService,
)
from invest_api.dependencies import get_research_external_evidence_service
from invest_api.schemas.research_external_evidence import (
    ResearchCaseFromObservationRequest,
    ResearchCaseFromObservationResponse,
    ResearchExternalEvidenceResponse,
)

router = APIRouter(prefix="/api/v1", tags=["research"])


@router.post(
    "/research-cases/{case_id}/external-observations/{observation_id}/evidence",
    response_model=ResearchExternalEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
)
def link_external_observation(
    case_id: UUID,
    observation_id: UUID,
    service: Annotated[
        ResearchExternalEvidenceService,
        Depends(get_research_external_evidence_service),
    ],
) -> ResearchExternalEvidenceResponse:
    try:
        item = service.link(case_id=case_id, observation_id=observation_id)
    except ExternalEvidenceLinkError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if detail.endswith("not found")
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=detail) from exc
    return ResearchExternalEvidenceResponse.from_domain(item)


@router.post(
    "/research-cases/from-external-observations/{observation_id}",
    response_model=ResearchCaseFromObservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_case_from_observation(
    observation_id: UUID,
    request: ResearchCaseFromObservationRequest,
    service: Annotated[
        ResearchExternalEvidenceService,
        Depends(get_research_external_evidence_service),
    ],
) -> ResearchCaseFromObservationResponse:
    try:
        result = service.create_case_and_link(
            observation_id=observation_id,
            question=request.question,
            horizon=request.horizon,
        )
    except ExternalEvidenceLinkError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if detail.endswith("not found")
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=detail) from exc
    return ResearchCaseFromObservationResponse(
        case_id=result.case.case_id,
        evidence=ResearchExternalEvidenceResponse.from_domain(result.evidence),
        created_case=result.created_case,
    )
