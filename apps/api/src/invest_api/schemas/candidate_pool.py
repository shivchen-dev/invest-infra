"""Pydantic response schemas for the ``/api/v1/candidate-pool`` read-only endpoints.

The :class:`CandidatePoolLatestResponse` mirrors the latest published
candidate-pool run, including the input snapshot's ``content_hash`` so
downstream consumers can audit what the pool was calculated against.
``row_count`` is the input-snapshot row count (== number of items
returned) which the storage layer guarantees is exactly equal to the
``input_row_count`` carried by the :class:`CandidatePoolRun`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class RuleOutcomeResponse(BaseModel):
    """Outcome of one rule applied to one instrument in a pool."""

    rule_key: str
    passed: bool
    severity: str
    value: Decimal | None = None
    threshold: Decimal | None = None
    message: str | None = None


class ExclusionReasonResponse(BaseModel):
    """Machine-readable reason an instrument was excluded."""

    code: str
    message: str


class CandidatePoolItemResponse(BaseModel):
    """One per-instrument judgment from the latest published pool."""

    instrument_id: UUID
    included: bool
    rank: int | None = None
    total_score: Decimal | None = None
    metrics: dict[str, str] = Field(default_factory=dict)
    rule_results: list[RuleOutcomeResponse] = Field(default_factory=list)
    exclusion_reasons: list[ExclusionReasonResponse] = Field(default_factory=list)


class CandidatePoolLatestResponse(BaseModel):
    """Response envelope for the ``GET /api/v1/candidate-pool/latest`` endpoint."""

    snapshot_date: date
    row_count: int = Field(ge=0)
    content_hash: str
    items: list[CandidatePoolItemResponse]


__all__ = [
    "CandidatePoolItemResponse",
    "CandidatePoolLatestResponse",
    "ExclusionReasonResponse",
    "RuleOutcomeResponse",
]
