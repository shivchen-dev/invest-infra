from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from invest_api.application.research_external_evidence import (
    ExternalEvidenceLinkError,
    ResearchExternalEvidenceService,
)
from invest_api.dependencies import get_research_external_evidence_service
from invest_api.schemas.research_external_evidence import ResearchExternalEvidenceResponse

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
