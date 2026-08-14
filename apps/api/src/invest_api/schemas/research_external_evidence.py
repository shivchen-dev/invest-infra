from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ResearchExternalEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evidence_id: str
    observation_id: UUID
    run_id: UUID
    artifact_id: UUID | None
    artifact_content_hash: str | None
    observed_at: datetime
    as_of: date
    source_uri: str
    producer: str
    payload: dict[str, Any]
    admission: dict[str, Any]
    content_hash: str

    @classmethod
    def from_domain(cls, item) -> ResearchExternalEvidenceResponse:
        return cls(
            evidence_id=item.evidence_id,
            observation_id=item.observation_id,
            run_id=item.run_id,
            artifact_id=item.artifact_id,
            artifact_content_hash=item.artifact_content_hash,
            observed_at=item.observed_at,
            as_of=item.as_of,
            source_uri=item.source_uri,
            producer=item.producer,
            payload=dict(item.payload),
            admission=dict(item.admission),
            content_hash=item.content_hash,
        )
