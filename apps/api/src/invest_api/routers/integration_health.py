"""Integration health and safe artifact preview endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from invest_api.application.external_workflows import ExternalWorkflowQueryService
from invest_api.dependencies import get_external_workflow_query_service
from invest_api.schemas.integration_health import (
    ArtifactPreviewResponse,
    IntegrationHealthResponse,
)

router = APIRouter(prefix="/api/v1/integration", tags=["integration"])


@router.get("/health", response_model=IntegrationHealthResponse)
def get_integration_health(
    service: Annotated[ExternalWorkflowQueryService, Depends(get_external_workflow_query_service)],
) -> IntegrationHealthResponse:
    return IntegrationHealthResponse(**service.health())


@router.get("/artifacts/{artifact_id}", response_model=ArtifactPreviewResponse)
def preview_artifact(
    artifact_id: UUID,
    service: Annotated[ExternalWorkflowQueryService, Depends(get_external_workflow_query_service)],
) -> ArtifactPreviewResponse:
    artifact = service.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="external artifact not found",
        )
    return ArtifactPreviewResponse(
        artifact_id=artifact.artifact_id,
        run_id=artifact.run_id,
        logical_uri=artifact.logical_uri,
        content_hash=artifact.content_hash,
        media_type=artifact.media_type,
        size_bytes=artifact.size_bytes,
        created_at=artifact.created_at,
        metadata=dict(artifact.metadata),
    )


__all__ = ["router"]
