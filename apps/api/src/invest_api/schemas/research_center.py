"""Pydantic response schemas for the ``/api/v1/research-center`` read-only endpoint.

The endpoint exposes the contract-pinned :class:`ResearchCenterResponse`
shape (see ``docs/implementation/RESEARCH-CENTER-SLICE0-CONTRACT.md``)
the central ``/dashboard`` page renders. Slice 1 fills the ``market``
segment (Market Breadth + Data Freshness composition) and the
deterministic capability placeholders; Slice 2A adds the ``research``
sub-segment driven by the existing
:meth:`invest_api.application.research.ResearchQueryService.get_dashboard`
orchestration. Slice 2B adds the ``candidate_pool`` and ``opportunities``
sub-segments driven by the existing
:meth:`invest_api.application.candidate_pool.CandidatePoolQueryService.get_latest`
and
:meth:`invest_api.application.external_workflows.ExternalWorkflowQueryService.list_radar`
readers. Slice 3A adds the ``delivery`` sub-segment driven by the
existing personal-daily pipeline run reader
(:meth:`invest_api.application.pipeline_runs.PipelineRunQueryService.get_latest_run`),
the external integration health reader
(:meth:`invest_api.application.external_workflows.ExternalWorkflowQueryService.health`),
the external artifact reader
(:meth:`invest_api.application.external_workflows.ExternalWorkflowQueryService.list_artifacts`)
and the research dashboard's bounded ``recent_runs`` reader
(:attr:`invest_api.application.research.ResearchDashboardView.recent_runs`).
Later slices will extend the response without re-shaping the existing
fields.

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
* ``delivery.schema_version`` mirrors the central contract version
  (``"1.0.0"``) for the same reason; the router asserts the
  application-level
  :class:`invest_api.application.research_center.DELIVERY_SCHEMA_VERSION`
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
* ``candidate_pool`` exposes only bounded source facts the existing
  :class:`invest_api.application.candidate_pool.LatestCandidatePoolView`
  already produces: the latest published run identity
  (``run_id``, ``trade_date``) and the row/included/excluded counts.
  No investment conclusions, no per-instrument metrics and no
  policy hash are projected. The sub-segment uses the same
  three-state vocabulary (``available | empty | failed``) so the
  UI cannot mistake a populated zero total for "data unavailable";
  ``failed`` is reserved for the controlled
  :class:`invest_api.application.candidate_pool.CandidatePoolQueryError`
  and
  :class:`invest_api.application.candidate_pool.CandidatePoolSnapshotMissingError`
  boundaries, while ``empty`` is the explicit "no published run yet"
  path.
* ``opportunities`` exposes a bounded observation count (always
  ``<= OPPORTUNITY_RADAR_LIMIT``), the latest ``as_of`` date when
  at least one observation exists, and admission-status counts keyed
  by the existing
  :class:`invest_domain.integration.AdmissionStatus` values so the
  front-end can render the admission mix without reaching into the
  underlying observation list. The sub-segment uses the same
  three-state vocabulary and ``failed`` is reserved for the
  controlled
  :class:`sqlalchemy.exc.SQLAlchemyError` boundary raised by the
  external-workflow reader.
* The ``research`` sub-segment uses its own three-state vocabulary
  (``available | empty | failed``) so the dashboard never confuses an
  explicit ``0`` total with "data unavailable"; ``failed`` is reserved
  for the controlled
  :class:`invest_api.application.research.ResearchQueryError` boundary,
  while ``empty`` is the exact-zero count path. The capability section
  remains frozen to the Slice 1 placeholders so the response shape is
  stable while later slices land.
* ``delivery`` exposes the four bounded sub-segments the central
  delivery-chain card consumes: ``pipeline`` (the latest
  personal-daily :class:`invest_domain.pipeline.PipelineRun` projected
  as ``available | empty | running | partial | failed``),
  ``integration`` (the bounded external health dictionary
  projected as ``available | empty | failed``),
  ``archive`` (the bounded per-run artifact slice projected as
  ``available | empty | failed``) and ``research_runs`` (the
  dashboard's bounded ``recent_runs`` page projected as
  ``available | empty | failed``). No artifact URI, payload, host
  path, logical URI, content hash, report body, evidence bundle,
  ``error_summary`` or credential is projected so the public
  response stays a thin pointer to the existing detail pages.
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

ResearchCenterCapabilityState = Literal["deferred", "unavailable", "available"]
"""Pinned capability ``state`` vocabulary for the contract response.

The two-state ``deferred | unavailable`` vocabulary covered the
Slice 1 placeholder bundle. Slice 3B extends the vocabulary with
``available`` so :attr:`capabilities.delivery` can flip from
``deferred`` to ``available`` once the bounded ``delivery``
sub-segment renders end-to-end; the other capability entries
remain on ``deferred`` / ``unavailable`` because their contracts
are still frozen. The extension is backward-compatible — every
client that previously accepted ``"deferred"`` or
``"unavailable"`` continues to observe those values for the
un-affected capability entries; the new ``"available"`` value is
the only legal state the delivery capability can carry going
forward.
"""

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

ResearchCenterCandidatePoolState = Literal["available", "empty", "failed"]
"""Three-state vocabulary for the ``candidate_pool.state`` sub-segment.

Mirrors the Slice 2A ``research.state`` vocabulary so the central
surface never has to invent a fourth "no published run yet" token;
``available`` means the latest published run was found,
``empty`` means :meth:`CandidatePoolQueryService.get_latest`
returned ``None``, and ``failed`` is reserved for the controlled
:class:`invest_api.application.candidate_pool.CandidatePoolQueryError`
and
:class:`invest_api.application.candidate_pool.CandidatePoolSnapshotMissingError`
boundaries.
"""

ResearchCenterOpportunityState = Literal["available", "empty", "failed"]
"""Three-state vocabulary for the ``opportunities.state`` sub-segment.

Mirrors the Slice 2A ``research.state`` vocabulary so the central
surface never has to invent a fourth "no observations yet" token;
``available`` means the bounded radar slice is non-empty,
``empty`` means the radar reader returned an empty sequence, and
``failed`` is reserved for the controlled
:class:`sqlalchemy.exc.SQLAlchemyError` boundary raised by the
external-workflow reader.
"""

ResearchCenterDeliveryPipelineState = Literal[
    "available", "empty", "failed", "running", "partial"
]
"""Five-state vocabulary for the ``delivery.pipeline.state`` sub-segment.

The pipeline sub-segment is the only Slice 3A sub-segment that
exposes the in-flight ``running`` and terminal ``partial`` states
in addition to the three-state
``available | empty | failed`` set. ``available`` is the
terminal ``succeeded`` path; ``running`` is the in-flight path
(``started_at`` set, ``finished_at`` ``None``); ``partial`` is
the terminal ``partial`` path; ``empty`` is the
"no run yet" path; ``failed`` is the controlled
:class:`invest_api.application.pipeline_runs.PipelineRunQueryError`
boundary.
"""

ResearchCenterDeliveryThreeState = Literal["available", "empty", "failed"]
"""Three-state vocabulary reused by the Slice 3A delivery sub-segments.

``integration``, ``archive`` and ``research_runs`` all use this
exact three-state vocabulary so the front-end can render the
three slots with a single switch and so the contract stays a
thin pointer to the existing detail pages. ``empty`` is the
real zero / no run / no observation path; ``failed`` is the
controlled error boundary; ``available`` is the populated path.
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

    The capability section is frozen to a deterministic
    vocabulary (``deferred`` / ``unavailable`` /
    ``available``) so the response shape is stable and later
    slices can replace individual entries without re-shaping
    the application layer. Slice 3B promotes ``delivery`` to
    ``available`` because the bounded ``delivery`` sub-segment
    now renders end-to-end; the other capability entries
    remain on ``deferred`` / ``unavailable`` placeholders.
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


class ResearchCenterCandidatePoolSummaryResponse(BaseModel):
    """``candidate_pool`` sub-segment of the contract response (Slice 2B).

    Mirrors
    :class:`invest_api.application.research_center.ResearchCenterCandidatePoolSummaryView`
    field-by-field. The sub-segment exposes only bounded source
    facts the existing
    :class:`invest_api.application.candidate_pool.LatestCandidatePoolView`
    already produces — the latest published run identity and the
    row/included/excluded counts. No investment conclusions,
    per-instrument metrics or policy hashes are projected.

    The three-state vocabulary mirrors Slice 2A's ``research``
    contract so the central surface never has to invent a fourth
    "no published run yet" token. ``run_id``, ``trade_date``,
    ``input_row_count``, ``included_count`` and ``excluded_count``
    stay ``None`` whenever ``state != "available"`` so a fabricated
    zero cannot masquerade as "data unavailable".
    """

    model_config = ConfigDict(frozen=True)

    state: ResearchCenterCandidatePoolState
    run_id: UUID | None = None
    trade_date: date | None = None
    input_row_count: int | None = None
    included_count: int | None = None
    excluded_count: int | None = None
    reason: str | None = None


class ResearchCenterOpportunitySummaryResponse(BaseModel):
    """``opportunities`` sub-segment of the contract response (Slice 2B).

    Mirrors
    :class:`invest_api.application.research_center.ResearchCenterOpportunitySummaryView`
    field-by-field. The sub-segment exposes only bounded source
    facts the existing
    :meth:`invest_api.application.external_workflows.ExternalWorkflowQueryService.list_radar`
    already produces — a bounded observation count, the latest
    ``as_of`` date when at least one observation exists, and an
    admission-status count dictionary keyed by the existing
    :class:`invest_domain.integration.AdmissionStatus` values.

    No payload blobs, source URIs or per-observation identifiers are
    projected so the central surface remains a thin pointer to the
    existing detail page. The three-state vocabulary mirrors Slice
    2A's ``research`` contract so the central surface never has to
    invent a fourth "no observations yet" token. ``observation_count``,
    ``latest_as_of`` and ``admission_status_counts`` stay ``None``
    whenever ``state != "available"`` so a fabricated zero cannot
    masquerade as "data unavailable".
    """

    model_config = ConfigDict(frozen=True)

    state: ResearchCenterOpportunityState
    observation_count: int | None = None
    latest_as_of: date | None = None
    admission_status_counts: dict[str, int] | None = None
    reason: str | None = None


class ResearchCenterDeliveryPipelineResponse(BaseModel):
    """``delivery.pipeline`` sub-segment of the contract response (Slice 3B).

    Mirrors
    :class:`invest_api.application.research_center.ResearchCenterPipelineSummaryView`
    field-by-field. The sub-segment exposes only bounded source
    facts the existing
    :meth:`invest_api.application.pipeline_runs.PipelineRunQueryService.get_latest_run`
    already produces — the latest run's ``status`` value, the
    timezone-aware execution timestamps (``started_at`` and
    ``finished_at``), the business completion date (derived
    from ``finished_at``), the bounded ``freshness_at`` anchor
    (calendar day the run produced terminal output, mirroring
    :attr:`business_completion_date`) and the bounded ``source``
    label (the run's :attr:`PipelineRun.trigger_type`, e.g.
    ``"scheduled"`` / ``"manual"``). ``error_summary`` is
    **never** projected so a driver-level message can never leak
    through the response body; the bounded ``source`` value is
    the non-blank string the domain validator already enforces
    so the public surface can never echo a host path or credential or
    connection string.

    The five-state vocabulary
    ``available | empty | running | partial | failed`` is the
    pipeline sub-segment vocabulary that exposes the in-flight
    ``running`` and terminal ``partial`` states in addition to
    the three-state ``available | empty | failed`` set so the
    UI can render an in-flight or partially-completed run
    without misclassifying it. ``available`` is reserved for
    terminal ``succeeded`` runs only — ``failed`` /
    ``cancelled`` runs never borrow the ``available`` vocabulary;
    ``running`` covers both ``running`` and ``queued`` runs;
    ``partial`` covers ``partial``, ``cancelled`` and orphan
    terminal-without-success runs so the front-end can render
    the explainable-but-uncertain slot; ``failed`` covers a
    controlled
    :class:`invest_api.application.pipeline_runs.PipelineRunQueryError`
    boundary **or** a terminal ``failed`` run. ``status``
    carries the canonical
    :class:`invest_domain.pipeline.PipelineRunStatus` value;
    ``reason`` stays ``None`` whenever
    ``state != "failed"``, and the only legal ``reason`` value
    (when ``state == "failed"``) is
    :data:`invest_api.application.research_center.PIPELINE_FAILED_REASON`
    for the controlled query-error path.
    """

    model_config = ConfigDict(frozen=True)

    state: ResearchCenterDeliveryPipelineState
    status: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    business_completion_date: date | None = None
    freshness_at: date | None = None
    source: str | None = None
    reason: str | None = None


class ResearchCenterDeliveryIntegrationResponse(BaseModel):
    """``delivery.integration`` sub-segment of the contract response (Slice 3B).

    Mirrors
    :class:`invest_api.application.research_center.ResearchCenterIntegrationSummaryView`
    field-by-field. The sub-segment exposes only bounded source
    facts the existing
    :meth:`invest_api.application.external_workflows.ExternalWorkflowQueryService.health`
    already produces — the bounded ``sample_size`` (always
    ``<= INTEGRATION_HEALTH_RUN_LIMIT``), the ``status``
    (``healthy`` / ``degraded``), the pre-populated
    ``producer_status_counts`` / ``intake_status_counts``
    dictionaries, the latest ``as_of`` date resolved from the
    most recent run, the bounded ``freshness_at`` anchor
    (mirrors ``latest_as_of``) and the bounded ``source``
    ``producer`` label of the latest run (e.g.
    ``"workbuddy"``). No payload blob, source URI, run
    identifier, host path, producer identifier, credential or
    connection string is projected so the central surface
    remains a thin pointer to the existing detail page.

    The three-state vocabulary
    ``available | empty | failed`` mirrors Slice 2A's
    ``research`` contract so the central surface never has to
    invent a fourth "no external run yet" token. Every field
    stays ``None`` whenever ``state == "failed"`` so a
    fabricated zero cannot masquerade as "data unavailable".
    The bounded ``source`` projects only the storage-layer
    ``producer`` value (length-bounded by the schema) so the
    public surface cannot echo a credential or path.
    """

    model_config = ConfigDict(frozen=True)

    state: ResearchCenterDeliveryThreeState
    status: str | None = None
    sample_size: int | None = None
    producer_status_counts: dict[str, int] | None = None
    intake_status_counts: dict[str, int] | None = None
    latest_as_of: date | None = None
    freshness_at: date | None = None
    source: str | None = None
    reason: str | None = None


class ResearchCenterDeliveryArchiveResponse(BaseModel):
    """``delivery.archive`` sub-segment of the contract response (Slice 3B).

    Mirrors
    :class:`invest_api.application.research_center.ResearchCenterArchiveSummaryView`
    field-by-field. The sub-segment exposes only bounded source
    facts the existing
    :meth:`invest_api.application.external_workflows.ExternalWorkflowQueryService.list_artifacts`
    already produces — the bounded ``artifact_count`` (always
    ``<= ARCHIVE_ARTIFACT_LIMIT``), the latest run's
    :attr:`ExternalWorkflowRun.producer_status` value, the
    maximum ``created_at.date()`` across the bounded artifact
    slice, the bounded ``freshness_at`` anchor (mirrors
    ``latest_as_of``) and the bounded ``source`` ``media_type``
    label of the most-recent artifact (e.g.
    ``"application/json"``). No artifact URI, payload,
    metadata, host path, logical URI, content hash, run
    identifier, credential or connection string is projected so the
    central surface remains a thin pointer to the existing
    detail page. The bounded ``source`` projects only the
    storage-layer ``media_type`` value (length-bounded by the
    schema) so the public surface cannot echo a logical URI,
    host path, content hash, payload blob or connection string.

    The three-state vocabulary
    ``available | empty | failed`` mirrors Slice 2A's
    ``research`` contract so the central surface never has to
    invent a fourth "no artifact yet" token. ``artifact_count``
    is the real bounded count (or ``None`` under
    ``state == "failed"``).
    """

    model_config = ConfigDict(frozen=True)

    state: ResearchCenterDeliveryThreeState
    artifact_count: int | None = None
    latest_as_of: date | None = None
    freshness_at: date | None = None
    source: str | None = None
    latest_run_status: str | None = None
    reason: str | None = None


class ResearchCenterDeliveryResearchRunsResponse(BaseModel):
    """``delivery.research_runs`` sub-segment of the contract response (Slice 3B).

    Mirrors
    :class:`invest_api.application.research_center.ResearchCenterResearchRunsSummaryView`
    field-by-field. The sub-segment exposes only bounded source
    facts the dashboard reader's bounded ``recent_runs`` page
    already produces — the bounded ``run_count`` (always
    ``<= DASHBOARD_RECENT_RUNS_LIMIT``), the
    :class:`invest_domain.research.research_run.ResearchRunStatus`
    -> ``int`` count dictionary, the most-recent run's
    status / start / finish timestamps, the bounded
    ``freshness_at`` anchor (mirrors ``latest_finished_at``)
    and the bounded ``source`` ``runner_key`` label of the
    latest run (e.g. ``"llm"``). No report body, evidence
    bundle, ``error_summary``, ``case_id``, ``playbook_key``
    or ``evidence_pack_id`` is projected so the public surface
    stays a thin pointer to the existing research-runs detail
    page. The bounded ``source`` projects only the
    domain-validated ``runner_key`` so the public surface
    cannot echo a host path or credential, payload blob or
    connection string.

    The three-state vocabulary
    ``available | empty | failed`` mirrors Slice 2A's
    ``research`` contract so the central surface never has to
    invent a fourth "no run yet" token. Every field stays
    ``None`` whenever ``state == "failed"`` so a fabricated
    zero cannot masquerade as "data unavailable".
    """

    model_config = ConfigDict(frozen=True)

    state: ResearchCenterDeliveryThreeState
    run_count: int | None = None
    status_counts: dict[str, int] | None = None
    latest_status: str | None = None
    latest_started_at: datetime | None = None
    latest_finished_at: datetime | None = None
    freshness_at: datetime | None = None
    source: str | None = None
    reason: str | None = None


class ResearchCenterDeliveryResponse(BaseModel):
    """``delivery`` sub-segment of the contract response (Slice 3A).

    Mirrors
    :class:`invest_api.application.research_center.ResearchCenterDeliveryView`
    field-by-field. The sub-segment bundles the four bounded
    read-only sub-segments (pipeline, integration, archive,
    research runs) the central delivery-chain card consumes. Each
    sub-segment is fetched and translated independently so a
    single controlled failure on one of the four sources can never
    bleed into the other three; the front-end renders each slot
    on its own failure shape.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0.0"]
    pipeline: ResearchCenterDeliveryPipelineResponse
    integration: ResearchCenterDeliveryIntegrationResponse
    archive: ResearchCenterDeliveryArchiveResponse
    research_runs: ResearchCenterDeliveryResearchRunsResponse


class ResearchCenterResponse(BaseModel):
    """Read-only response envelope for the contract endpoint.

    Mirrors :class:`invest_api.application.research_center.ResearchCenterResponse`
    field-by-field and adds the two router-owned timestamps
    (``generated_at`` and the propagated ``market.data_freshness.checked_at``).
    Both timestamps come from the same ``datetime.now(UTC)`` call so a
    single response always observes identical values; the application
    service intentionally does not own a clock. Slice 2A adds the
    ``research`` sub-segment alongside the market / capabilities
    bundle without re-shaping any existing field. Slice 2B adds the
    ``candidate_pool`` and ``opportunities`` sub-segments on top of
    that bundle without re-shaping any existing field either. Slice
    3A adds the ``delivery`` sub-segment on top of the same bundle
    without re-shaping any existing field.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0.0"]
    generated_at: datetime
    state: ResearchCenterTopLevelState
    market: ResearchCenterMarketResponse
    capabilities: ResearchCenterCapabilitiesResponse
    research: ResearchCenterResearchSummaryResponse
    candidate_pool: ResearchCenterCandidatePoolSummaryResponse
    opportunities: ResearchCenterOpportunitySummaryResponse
    delivery: ResearchCenterDeliveryResponse


__all__ = [
    "ResearchCenterBreadthResponse",
    "ResearchCenterCandidatePoolState",
    "ResearchCenterCandidatePoolSummaryResponse",
    "ResearchCenterCapabilitiesResponse",
    "ResearchCenterCapabilityResponse",
    "ResearchCenterCapabilityState",
    "ResearchCenterDataFreshnessResponse",
    "ResearchCenterDeliveryArchiveResponse",
    "ResearchCenterDeliveryIntegrationResponse",
    "ResearchCenterDeliveryPipelineResponse",
    "ResearchCenterDeliveryPipelineState",
    "ResearchCenterDeliveryResearchRunsResponse",
    "ResearchCenterDeliveryResponse",
    "ResearchCenterDeliveryThreeState",
    "ResearchCenterFreshnessStatus",
    "ResearchCenterLatestCaseResponse",
    "ResearchCenterMarketResponse",
    "ResearchCenterMarketState",
    "ResearchCenterObservationResponse",
    "ResearchCenterOpportunityState",
    "ResearchCenterOpportunitySummaryResponse",
    "ResearchCenterResearchEvidenceResponse",
    "ResearchCenterResearchEvidenceState",
    "ResearchCenterResearchState",
    "ResearchCenterResearchSummaryResponse",
    "ResearchCenterResponse",
    "ResearchCenterSchemaVersion",
    "ResearchCenterTopLevelState",
]
