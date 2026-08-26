"""Public Pydantic response for the RAA ``StrategyDraft`` audit endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from invest_domain.strategy import SourceRef
from pydantic import BaseModel, Field

from invest_api.application.strategy_drafts import (
    StrategyDraftAuditSummary,
    StrategyDraftView,
)


class SourceRefResponse(BaseModel):
    ref: str
    content_hash: str

    @classmethod
    def from_domain(cls, source_ref: SourceRef) -> SourceRefResponse:
        return cls(ref=source_ref.ref, content_hash=source_ref.content_hash)


class StrategyDraftAuditSummaryResponse(BaseModel):
    audit_id: UUID
    artifact_hash: str
    verdict: str
    audited_at: datetime

    @classmethod
    def from_domain(
        cls, summary: StrategyDraftAuditSummary
    ) -> StrategyDraftAuditSummaryResponse:
        return cls(
            audit_id=summary.audit_id,
            artifact_hash=summary.artifact_hash,
            verdict=summary.verdict,
            audited_at=summary.audited_at,
        )


class StrategyDraftResponse(BaseModel):
    draft_id: UUID
    strategy_key: str
    proposed_version: str
    artifact_hash: str
    strategy: dict[str, Any]
    source_refs: list[SourceRefResponse]
    validation_result: dict[str, Any]
    created_at: datetime
    audit_summaries: list[StrategyDraftAuditSummaryResponse] = Field(default_factory=list)

    @classmethod
    def from_view(cls, view: StrategyDraftView) -> StrategyDraftResponse:
        return cls(
            draft_id=view.draft_id,
            strategy_key=view.strategy_key,
            proposed_version=view.proposed_version,
            artifact_hash=view.artifact_hash,
            strategy=dict(view.strategy),
            source_refs=[SourceRefResponse.from_domain(s) for s in view.source_refs],
            validation_result=dict(view.validation_result),
            created_at=view.created_at,
            audit_summaries=[
                StrategyDraftAuditSummaryResponse.from_domain(s)
                for s in view.audit_summaries
            ],
        )


__all__ = [
    "SourceRefResponse",
    "StrategyDraftAuditSummaryResponse",
    "StrategyDraftResponse",
]
