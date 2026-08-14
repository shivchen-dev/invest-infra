"""Read-only Stage 4D external workflow endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from invest_api.application.external_workflows import ExternalWorkflowQueryService
from invest_api.dependencies import get_external_workflow_query_service
from invest_api.schemas.external_workflows import (
    ExternalArtifactResponse,
    ExternalObservationResponse,
    ExternalWorkflowRunListResponse,
    ExternalWorkflowRunResponse,
)

router = APIRouter(prefix="/api/v1/external-workflows", tags=["external-workflows"])


def _run(run) -> ExternalWorkflowRunResponse:
    return ExternalWorkflowRunResponse(
        run_id=run.run_id,
        producer=run.producer,
        schema_version=run.schema_version,
        producer_status=run.producer_status.value,
        intake_status=run.intake_status.value,
        started_at=run.started_at,
        finished_at=run.finished_at,
        metadata=dict(run.metadata),
    )


def _artifact(artifact) -> ExternalArtifactResponse:
    return ExternalArtifactResponse(
        artifact_id=artifact.artifact_id,
        run_id=artifact.run_id,
        logical_uri=artifact.logical_uri,
        content_hash=artifact.content_hash,
        media_type=artifact.media_type,
        size_bytes=artifact.size_bytes,
        created_at=artifact.created_at,
        metadata=dict(artifact.metadata),
    )


def _observation(observation) -> ExternalObservationResponse:
    return ExternalObservationResponse(
        observation_id=observation.observation_id,
        run_id=observation.run_id,
        artifact_id=observation.artifact_id,
        observed_at=observation.observed_at,
        as_of=observation.as_of,
        source_uri=observation.source_uri,
        producer=observation.producer,
        payload=dict(observation.payload),
        symbol=observation.symbol,
        instrument_id=observation.instrument_id,
        admission_status=observation.admission_status.value,
        metadata=dict(observation.metadata),
    )


@router.get("", response_model=ExternalWorkflowRunListResponse)
def list_external_workflows(
    service: Annotated[ExternalWorkflowQueryService, Depends(get_external_workflow_query_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ExternalWorkflowRunListResponse:
    return ExternalWorkflowRunListResponse(
        items=[_run(item) for item in service.list_runs(limit=limit, offset=offset)],
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}", response_model=ExternalWorkflowRunResponse)
def get_external_workflow(
    run_id: UUID,
    service: Annotated[ExternalWorkflowQueryService, Depends(get_external_workflow_query_service)],
) -> ExternalWorkflowRunResponse:
    run = service.get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="external workflow run not found",
        )
    return _run(run)


@router.get("/{run_id}/artifacts", response_model=list[ExternalArtifactResponse])
def list_external_artifacts(
    run_id: UUID,
    service: Annotated[ExternalWorkflowQueryService, Depends(get_external_workflow_query_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ExternalArtifactResponse]:
    if service.get_run(run_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="external workflow run not found",
        )
    return [_artifact(item) for item in service.list_artifacts(run_id, limit=limit, offset=offset)]


@router.get("/{run_id}/observations", response_model=list[ExternalObservationResponse])
def list_external_observations(
    run_id: UUID,
    service: Annotated[ExternalWorkflowQueryService, Depends(get_external_workflow_query_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ExternalObservationResponse]:
    if service.get_run(run_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="external workflow run not found",
        )
    return [
        _observation(item)
        for item in service.list_observations(run_id, limit=limit, offset=offset)
    ]


__all__ = ["router"]
