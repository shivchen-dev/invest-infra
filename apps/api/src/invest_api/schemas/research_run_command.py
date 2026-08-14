from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from invest_api.schemas.research import ResearchRunResponse


class ResearchRunCommandRequest(BaseModel):
    evidence_pack_id: UUID
    playbook_key: str = Field(min_length=1, max_length=128)
    playbook_version: str = Field(min_length=1, max_length=64)


class ResearchRunCommandResponse(BaseModel):
    run: ResearchRunResponse
    idempotent: bool


__all__ = ["ResearchRunCommandRequest", "ResearchRunCommandResponse"]
