"""Pydantic response schemas for the ``/api/v1/research-center`` read-only endpoint.

The endpoint exposes the contract-pinned :class:`ResearchCenterResponse`
shape (see ``docs/implementation/RESEARCH-CENTER-SLICE0-CONTRACT.md``)
the central ``/dashboard`` page renders. Slice 1 fills the ``market``
segment (Market Breadth + Data Freshness composition) and the
deterministic capability placeholders; Slice 2A adds the ``research``
sub-segment driven by the existing
:meth:`invest_api.application.research.ResearchQueryService.get_dashboard`
orchestration. Later slices will extend the response without
re-shaping the existing fields.

Field-level invariants worth restating:

* ``schema_version`` mirrors the frozen contract version
  (``"1.0.0"``); the router passes the application-level
  :class:`invest_api.application.research_center.SCHEMA_VERSION`
  constant through unchanged.
* ``research.schema_version`` mirrors the dashboard contract version
  (``"1.0.0"``) so the central surface does not invent a parallel
  version; the router asserts the application-level
  :class:`invest_api.application.research_center.RESEARCH_SCHEMA_VERSION`
  constant before serialising.
* ``generated_at`` and ``market.data_freshness.checked_at`` are stamped
  by the router from a single UTC wall-clock call so two callers
  hitting the endpoint in the same instant observe the same timestamp
  pair; the application service intentionally does not own a clock.
* Market Breadth ``observations`` rename the domain
  ``observation_key`` to ``key`` and preserve every other field
  (``value``, ``unit``, ``observed_date``, ``source_kind``,
  ``source_ref``, ``quality_status``) verbatim. ``value`` keeps its
  native ``Decimal | str | None`` type so Pydantic serialises it the
  same way :class:`invest_api.schemas.market_breadth.MarketBreadthObservationResponse`
  already does.
* ``research.case_count`` and ``research.run_count`` mirror the
  dashboard reader's ``count_all`` exactly. ``research.latest_case``
  carries only ``case_id`` (identity) and ``as_of_date`` (date) — the
  front-end can deep-link into the existing case-detail page for the
  full shape.
* The ``research`` sub-segment uses its own three-state vocabulary
  (``available | empty | failed``) so the dashboard never confuses an
  explicit ``0`` total with "data unavailable"; ``failed`` is reserved
  for the controlled
  :class:`invest_api.application.research.ResearchQueryError` boundary,
  while ``empty`` is the exact-zero count path. The capability section
  remains frozen to the Slice 1 placeholders so the response shape is
  stable while later slices land.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

ResearchCenterSchemaVersion: str = "1.0.0"
"""Frozen response ``schema_version`` mirrored by the router."""

ResearchCenterTopLevelState = Literal["available", "partial", "unavailable", "failed"]
"""Pinned top-level ``state`` vocabulary.

Mirrors the four-state contract vocabulary the application service
derives for Slice 1. ``state`` describes only the response
availability — never market quality or investment conclusions.
"""

ResearchCenterMarketState = ResearchCenterTopLevelState
"""Pinned ``market.state`` vocabulary — same four states as the top level."""

ResearchCenterFreshnessStatus = Literal[
    "fresh", "partial", "stale", "missing", "failed"
]
"""Five-state Data Freshness vocabulary passed through unchanged."""

ResearchCenterCapabilityState = Literal["deferred", "unavailable"]
"""Pinned capability ``state`` vocabulary for Slice 1 placeholders."""

ResearchCenterResearchState = Literal["available", "empty", "failed"]
"""Three-state vocabulary for the ``research.state`` sub-segment.

Distinct from the top-level four-state vocabulary because this
sub-segment is read-only and never participates in the market state
machine. ``available`` requires at least one case; ``empty`` is the
explicit zero-count path; ``failed`` is the controlled
:class:`ResearchQueryError` boundary.
"""

ResearchCenterResearchEvidenceState = Literal["empty", "available"]
"""Two-state vocabulary for ``research.evidence.state``.

Mirrors the dashboard ``evidence_status.state`` verbatim; the front
end can render the same empty / available distinction without a
second vocabulary.
"""


class ResearchCenterObservationResponse(BaseModel):
    """One Market Breadth observation on the contract response shape.

    Maps the application-level
    :class:`invest_api.application.research_center.ResearchCenterObservationView`
    onto the public JSON field names: ``observation_key`` is renamed
    to ``key``; every other observation field is preserved verbatim.
    ``value`` keeps its native ``Decimal | str | None`` type so
    Pydantic renders ``Decimal`` as a string (matching the existing
    Market Breadth endpoint) while a plain textual value stays a
    string and ``None`` stays ``null``.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    value: Decimal | str | None
    unit: str
    observed_date: date
    source_kind: str
    source_ref: str
    quality_status: str


class ResearchCenterBreadthResponse(BaseModel):
    """Market Breadth sub-segment of the contract response.

    Mirrors :class:`invest_api.application.research_center.ResearchCenterBreadthView`
    field-by-field. A controlled error is an explicit ``failed``
    object whose payload fields are null; a genuinely missing snapshot
    remains ``None``. No identity, scope or observation is fabricated.
    """

    model_config = ConfigDict(frozen=True)

    state: Literal["available", "failed"]
    snapshot_id: str | None = None
    algorithm_version: str | None = None
    scope_type: str | None = None
    scope_key: str | None = None
    observations: list[ResearchCenterObservationResponse] | None = None


class ResearchCenterDataFreshnessResponse(BaseModel):
    """Data Freshness sub-segment of the contract response.

    ``checked_at`` is the router-stamped UTC wall-clock value the
    application service intentionally omits; the router reuses the
    same ``datetime.now(UTC)`` value it stamps on the top-level
    ``generated_at`` so the two timestamps are always identical for a
    given response. ``state`` is the four-state substate derived from
    ``status`` so the UI can render without re-reading the underlying
    five-state vocabulary; ``status`` carries the original
    ``fresh | partial | stale | missing | failed`` value verbatim.
    """

    model_config = ConfigDict(frozen=True)

    state: ResearchCenterMarketState
    checked_at: datetime
    latest_published_trade_date: date | None = None
    universe_count: int | None = None
    daily_bar_count: int | None = None
    missing_count: int | None = None
    status: ResearchCenterFreshnessStatus


class ResearchCenterMarketResponse(BaseModel):
    """Market segment of the contract response.

    ``state`` mirrors the top-level ``state`` for Slice 1 (the
    contract makes the two equivalent). ``as_of_date`` prefers the
    breadth snapshot date, falls back to the freshness latest
    published trade date, and is ``None`` when neither source has a
    date. ``quality_status`` and ``freshness_status`` carry the
    breadth domain values verbatim, or ``None`` when no breadth
    snapshot is available. ``breadth`` and ``data_freshness`` are the
    per-source sub-segments. Genuine absence is ``None`` while a
    controlled error is represented by an explicit failed object.
    """

    model_config = ConfigDict(frozen=True)

    state: ResearchCenterMarketState
    as_of_date: date | None = None
    quality_status: str | None = None
    freshness_status: str | None = None
    breadth: ResearchCenterBreadthResponse | None = None
    data_freshness: ResearchCenterDataFreshnessResponse | None = None


class ResearchCenterCapabilityResponse(BaseModel):
    """One capability entry on the contract response shape.

    Slice 1 pins every capability to a deterministic placeholder so
    the response shape is stable and later slices can replace
    individual entries without re-shaping the application layer.
    """

    model_config = ConfigDict(frozen=True)

    state: ResearchCenterCapabilityState
    reason: str


class ResearchCenterCapabilitiesResponse(BaseModel):
    """Slice 1 capability bundle — frozen until later slices land."""

    model_config = ConfigDict(frozen=True)

    opportunities: ResearchCenterCapabilityResponse
    research: ResearchCenterCapabilityResponse
    delivery: ResearchCenterCapabilityResponse
    strategy: ResearchCenterCapabilityResponse
    discipline: ResearchCenterCapabilityResponse


class ResearchCenterLatestCaseResponse(BaseModel):
    """Identity-only projection of the dashboard ``research_summary.latest_case``.

    The contract surfaces only the two fields the central page needs
    for a deep-link (``case_id``) and a date label (``as_of_date``);
    no additional :class:`ResearchCase` field is exposed here so the
    existing case-detail endpoint remains the single source of truth
    for the full case shape.
    """

    model_config = ConfigDict(frozen=True)

    case_id: UUID
    as_of_date: date


class ResearchCenterResearchEvidenceResponse(BaseModel):
    """Evidence sub-segment of ``research`` mirroring the dashboard verbatim.

    ``state`` is the dashboard ``empty | available`` vocabulary; the
    three slot-level fields (``pack_id``, ``quality_status``,
    ``freshness_status``) stay ``None`` whenever ``state == "empty"``
    so the front-end can render an explicit empty evidence slot
    without special-casing ``None`` vs. unset.
    """

    model_config = ConfigDict(frozen=True)

    state: ResearchCenterResearchEvidenceState
    pack_id: UUID | None = None
    quality_status: str | None = None
    freshness_status: str | None = None


class ResearchCenterResearchSummaryResponse(BaseModel):
    """``research`` sub-segment of the contract response (Slice 2A).

    Mirrors :class:`invest_api.application.research_center.ResearchCenterResearchSummaryView`
    field-by-field and adds the router-owned ``schema_version``.
    The ``state`` vocabulary is the three-state
    ``available | empty | failed`` set; ``case_count`` /
    ``run_count`` are ``None`` only when ``state == "failed"`` so a
    fabricated zero can never masquerade as "data unavailable".
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0.0"]
    state: ResearchCenterResearchState
    case_count: int | None = None
    run_count: int | None = None
    latest_case: ResearchCenterLatestCaseResponse | None = None
    evidence: ResearchCenterResearchEvidenceResponse


class ResearchCenterResponse(BaseModel):
    """Read-only response envelope for the contract endpoint.

    Mirrors :class:`invest_api.application.research_center.ResearchCenterResponse`
    field-by-field and adds the two router-owned timestamps
    (``generated_at`` and the propagated ``market.data_freshness.checked_at``).
    Both timestamps come from the same ``datetime.now(UTC)`` call so a
    single response always observes identical values; the application
    service intentionally does not own a clock. Slice 2A adds the
    ``research`` sub-segment alongside the market / capabilities
    bundle without re-shaping any existing field.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0.0"]
    generated_at: datetime
    state: ResearchCenterTopLevelState
    market: ResearchCenterMarketResponse
    capabilities: ResearchCenterCapabilitiesResponse
    research: ResearchCenterResearchSummaryResponse


__all__ = [
    "ResearchCenterBreadthResponse",
    "ResearchCenterCapabilitiesResponse",
    "ResearchCenterCapabilityResponse",
    "ResearchCenterCapabilityState",
    "ResearchCenterDataFreshnessResponse",
    "ResearchCenterFreshnessStatus",
    "ResearchCenterLatestCaseResponse",
    "ResearchCenterMarketResponse",
    "ResearchCenterMarketState",
    "ResearchCenterObservationResponse",
    "ResearchCenterResearchEvidenceResponse",
    "ResearchCenterResearchEvidenceState",
    "ResearchCenterResearchState",
    "ResearchCenterResearchSummaryResponse",
    "ResearchCenterResponse",
    "ResearchCenterSchemaVersion",
    "ResearchCenterTopLevelState",
]
