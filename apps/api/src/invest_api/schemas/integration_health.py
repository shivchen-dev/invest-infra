"""Public schemas for Stage 4D integration health and artifact preview."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IntegrationHealthResponse(BaseModel):
    status: str
    sample_size: int = Field(ge=0)
    producer_statuses: dict[str, int]
    intake_statuses: dict[str, int]
    latest_run_id: UUID | None = None


class ArtifactPreviewResponse(BaseModel):
    artifact_id: UUID
    run_id: UUID
    logical_uri: str
    content_hash: str
    media_type: str
    size_bytes: int = Field(ge=0)
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["ArtifactPreviewResponse", "IntegrationHealthResponse"]
