"""Request and response schemas for the gated admission command."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class AdmissionDecisionRequest(BaseModel):
    """Public command payload for ``POST .../admission-decisions``.

    Client callers only send the :class:`Idempotency-Key` companion.
    Verification facts (identity / freshness / unit / internal cross-check /
    conflict), the rules version and the decision principal are all
    server-controlled: they are derived from the loaded
    :class:`invest_domain.integration.ExternalObservation` and the
    repository's recent observations by the application service.
    """

    idempotency_key: str = Field(min_length=8, max_length=128)


class AdmissionDecisionResponse(BaseModel):
    observation_id: UUID
    admission_status: str
    reason: str
    idempotent: bool


__all__ = ["AdmissionDecisionRequest", "AdmissionDecisionResponse"]
