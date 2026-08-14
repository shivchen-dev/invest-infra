"""Request and response schemas for the gated admission command."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class AdmissionDecisionRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    identity_ok: bool
    freshness_ok: bool
    unit_ok: bool
    internal_cross_check_ok: bool | None = None
    conflict_detected: bool = False
    rules_version: str = Field(default="observation-admission/1.0", min_length=1, max_length=64)
    decided_by: str = Field(default="api", min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=512)


class AdmissionDecisionResponse(BaseModel):
    observation_id: UUID
    admission_status: str
    reason: str
    idempotent: bool


__all__ = ["AdmissionDecisionRequest", "AdmissionDecisionResponse"]
