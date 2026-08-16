"""Pydantic response schemas for the ``/api/v1/research-center`` read-only endpoint.

The endpoint exposes the contract-pinned :class:`ResearchCenterResponse`
shape (see ``docs/implementation/RESEARCH-CENTER-SLICE0-CONTRACT.md``)
the central ``/dashboard`` page renders. Slice 1 only fills the
``market`` segment (Market Breadth + Data Freshness composition) and
the deterministic capability placeholders; later slices will extend
the response without re-shaping the existing fields.

Field-level invariants worth restating:

* ``schema_version`` mirrors the frozen contract version
  (``"1.0.0"``); the router passes the application-level
  :class:`invest_api.application.research_center.SCHEMA_VERSION`
  constant through unchanged.
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
* The capability section is frozen to the Slice 1 placeholders so the
  response shape is stable while later slices land.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

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


class ResearchCenterResponse(BaseModel):
    """Read-only response envelope for the contract endpoint.

    Mirrors :class:`invest_api.application.research_center.ResearchCenterResponse`
    field-by-field and adds the two router-owned timestamps
    (``generated_at`` and the propagated ``market.data_freshness.checked_at``).
    Both timestamps come from the same ``datetime.now(UTC)`` call so a
    single response always observes identical values; the application
    service intentionally does not own a clock.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0.0"]
    generated_at: datetime
    state: ResearchCenterTopLevelState
    market: ResearchCenterMarketResponse
    capabilities: ResearchCenterCapabilitiesResponse


__all__ = [
    "ResearchCenterBreadthResponse",
    "ResearchCenterCapabilitiesResponse",
    "ResearchCenterCapabilityResponse",
    "ResearchCenterCapabilityState",
    "ResearchCenterDataFreshnessResponse",
    "ResearchCenterFreshnessStatus",
    "ResearchCenterMarketResponse",
    "ResearchCenterMarketState",
    "ResearchCenterObservationResponse",
    "ResearchCenterResponse",
    "ResearchCenterSchemaVersion",
    "ResearchCenterTopLevelState",
]
