"""Pydantic response schemas for the ``/api/v1/candidate-pool`` read-only endpoints.

The :class:`CandidatePoolLatestResponse` mirrors the latest published
candidate-pool run together with the run-level metadata required by the
Web data workbench (see PR-01 of
``docs/plan/invest-infra-v2-next-stage-web-workbench-plan.md``):

- ``run_id``, ``trade_date``, ``algorithm_key``, ``algorithm_version``
  and ``parameter_set_key`` identify the run uniquely;
- ``snapshot_id`` and ``content_hash`` allow the consumer to audit the
  input snapshot the pool was calculated against;
- ``row_count`` is the input-snapshot row count (== number of items
  returned) which the storage layer guarantees is exactly equal to the
  ``input_row_count`` carried by the :class:`CandidatePoolRun`;
- ``included_count`` / ``excluded_count`` / ``published_at`` complete
  the snapshot the Web Dashboard renders.

Per-item responses (:class:`CandidatePoolItemResponse` and
:class:`CandidatePoolDiffEntry`) carry optional ``symbol`` / ``name`` /
``exchange`` display fields populated by a server-side Instrument
lookup; missing instruments degrade to ``None`` so the read endpoint
never fails because a single row was missing.
"""

from __future__ import annotations

from datetime import date, datetime
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


class InstrumentDisplay(BaseModel):
    """Optional Instrument display fields resolved on the server side."""

    symbol: str | None = None
    name: str | None = None
    exchange: str | None = None


class CandidatePoolItemResponse(BaseModel):
    """One per-instrument judgment from the latest published pool."""

    instrument_id: UUID
    included: bool
    rank: int | None = None
    total_score: Decimal | None = None
    metrics: dict[str, str] = Field(default_factory=dict)
    rule_results: list[RuleOutcomeResponse] = Field(default_factory=list)
    exclusion_reasons: list[ExclusionReasonResponse] = Field(default_factory=list)
    symbol: str | None = None
    name: str | None = None
    exchange: str | None = None


class CandidatePoolLatestResponse(BaseModel):
    """Response envelope for the ``GET /api/v1/candidate-pool/latest`` endpoint."""

    run_id: UUID
    trade_date: date
    algorithm_key: str
    algorithm_version: str
    parameter_set_key: str
    snapshot_id: UUID
    content_hash: str
    row_count: int = Field(ge=0)
    included_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    published_at: datetime | None = None
    items: list[CandidatePoolItemResponse]


class CandidatePoolDiffEntry(BaseModel):
    """One instrument entry in a candidate-pool diff bucket.

    Carries the raw ``instrument_id`` plus the resolved display fields
    so the Web can render the diff without making a follow-up Instrument
    lookup. ``symbol`` / ``name`` / ``exchange`` are ``None`` when the
    instrument row is missing; ordering is deterministic - ``symbol``
    ascending with ``instrument_id`` as the tiebreaker.
    """

    instrument_id: UUID
    symbol: str | None = None
    name: str | None = None
    exchange: str | None = None


class CandidatePoolDiffResponse(BaseModel):
    """Response envelope for the candidate-pool diff endpoints.

    Compares the set of ``included=True`` instruments in the current
    published run against the most recent earlier published run.
    ``added`` is the set of instruments that appear only in the current
    run, ``retained`` is the intersection, and ``removed`` is the set
    that appear only in the previous run. Excluded items (where
    ``included=False``) are NEVER reported in any bucket - the diff
    reflects candidate-pool membership changes, not input-pool changes.
    When no earlier published run exists, ``previous_trade_date`` is
    ``None`` and every included instrument in the current run is
    reported as ``added`` with ``retained`` and ``removed`` both empty.
    """

    trade_date: date
    previous_trade_date: date | None = None
    added: list[CandidatePoolDiffEntry] = Field(default_factory=list)
    retained: list[CandidatePoolDiffEntry] = Field(default_factory=list)
    removed: list[CandidatePoolDiffEntry] = Field(default_factory=list)


__all__ = [
    "CandidatePoolDiffEntry",
    "CandidatePoolDiffResponse",
    "CandidatePoolItemResponse",
    "CandidatePoolLatestResponse",
    "ExclusionReasonResponse",
    "InstrumentDisplay",
    "RuleOutcomeResponse",
]