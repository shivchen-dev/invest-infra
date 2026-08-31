"""Public read-only schemas for external workflow integration data."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ExternalWorkflowRunResponse(BaseModel):
    run_id: UUID
    producer: str
    schema_version: str
    producer_status: str
    intake_status: str
    started_at: datetime
    finished_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalArtifactResponse(BaseModel):
    artifact_id: UUID
    run_id: UUID
    logical_uri: str
    content_hash: str
    media_type: str
    size_bytes: int = Field(ge=0)
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalObservationResponse(BaseModel):
    observation_id: UUID
    run_id: UUID
    artifact_id: UUID | None = None
    observed_at: datetime
    as_of: date
    source_uri: str
    producer: str
    payload: dict[str, Any]
    symbol: str | None = None
    instrument_id: UUID | None = None
    admission_status: str
    candidate_status: str | None = None
    reason: str | None = Field(default=None, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalWorkflowRunListResponse(BaseModel):
    items: list[ExternalWorkflowRunResponse]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class CandidateStageResponse(BaseModel):
    stage_key: str
    stage_result_id: str
    stage_result_sha256: str
    strategy_key: str
    strategy_version: str
    strategy_artifact_hash: str
    as_of: str
    constituent_snapshot_sha256: str | None = None
    upstream_stage_result_id: str | None = None
    upstream_stage_result_sha256: str | None = None


class CandidateLineageResponse(BaseModel):
    schema_version: str
    stages: list[CandidateStageResponse] = Field(min_length=2, max_length=2)


class CandidateLineageAvailabilityResponse(BaseModel):
    run_id: UUID
    availability: Literal["available", "unavailable"]
    lineage: CandidateLineageResponse | None = None


__all__ = [
    "CandidateLineageAvailabilityResponse",
    "CandidateLineageResponse",
    "CandidateStageResponse",
    "ExternalArtifactResponse",
    "ExternalObservationResponse",
    "ExternalWorkflowRunListResponse",
    "ExternalWorkflowRunResponse",
]
