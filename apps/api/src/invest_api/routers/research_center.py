"""Read-only ``GET /api/v1/research-center`` endpoint.

This router is the only public surface of the central Research
Visualization Slice module. It composes the six existing read-only
application services — :class:`MarketBreadthQueryService`,
:class:`DataFreshnessQueryService`, :class:`ResearchQueryService`,
:class:`CandidatePoolQueryService`,
:class:`ExternalWorkflowQueryService` and
:class:`PipelineRunQueryService` — through the
:class:`ResearchCenterQueryService` the application layer owns, then
maps the resulting dataclass view onto the frozen
:class:`ResearchCenterResponse` Pydantic shape from
:mod:`invest_api.schemas.research_center`.

The router is intentionally minimal:

* it does not issue HTTP calls to any of the underlying endpoints
  — composition happens in the application service against the same
  request-scoped SQLAlchemy session the other read routers already
  use;
* it stamps a single ``datetime.now(UTC)`` value and reuses it for
  both the top-level ``generated_at`` and
  ``market.data_freshness.checked_at`` so two callers hitting the
  endpoint in the same instant observe the same timestamp pair;
* it does not catch unknown exceptions: only the controlled
  per-source failures are already represented explicitly in the 200
  response by the application service; anything else propagates so
  FastAPI's generic error boundary stays in charge of sanitising
  driver-level detail (no path, connection string or credential
  text in the response body);
* the four ``_delivery_*_from_view`` mappers feed
  ``view.source`` through the canonical application-layer
  :func:`sanitize_source_value` filter against the matching
  ``PIPELINE_TRIGGER_TYPE_WHITELIST`` /
  ``INTEGRATION_PRODUCER_WHITELIST`` /
  ``ARCHIVE_MEDIA_TYPE_WHITELIST`` /
  ``RESEARCH_RUNS_RUNNER_KEY_WHITELIST`` whitelist so the API
  boundary stays defence-in-depth — a rogue upstream caller
  who bypasses :class:`ResearchCenterQueryService` cannot
  echo a credential, host path, control character or
  connection string through the response body even when
  the bounded view already carries the malicious text.

Slice 2A adds the ``research`` sub-segment driven by the existing
``ResearchQueryService.get_dashboard`` orchestrator; Slice 2B adds
the ``candidate_pool`` and ``opportunities`` sub-segments driven by
the existing ``CandidatePoolQueryService.get_latest`` and
``ExternalWorkflowQueryService.list_radar`` readers. Slice 3A adds
the ``delivery`` sub-segment driven by the existing
``PipelineRunQueryService.get_latest_run`` and the
``ExternalWorkflowQueryService.health`` /
``list_runs`` / ``list_artifacts`` /
``ResearchQueryService.get_dashboard().recent_runs`` readers. The
router simply projects the application-level views onto the new
Pydantic fields without re-shaping the existing market /
capabilities / research / candidate_pool / opportunities bundle.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from invest_api.application.research_center import (
    ARCHIVE_MEDIA_TYPE_WHITELIST,
    DELIVERY_SCHEMA_VERSION,
    INTEGRATION_PRODUCER_WHITELIST,
    PIPELINE_TRIGGER_TYPE_WHITELIST,
    RESEARCH_RUNS_RUNNER_KEY_WHITELIST,
    RESEARCH_SCHEMA_VERSION,
    ResearchCenterArchiveSummaryView,
    ResearchCenterBreadthView,
    ResearchCenterCandidatePoolSummaryView,
    ResearchCenterCapabilitiesView,
    ResearchCenterCapabilityView,
    ResearchCenterDataFreshnessView,
    ResearchCenterDeliveryView,
    ResearchCenterIntegrationSummaryView,
    ResearchCenterLatestCaseView,
    ResearchCenterMarketView,
    ResearchCenterObservationView,
    ResearchCenterOpportunitySummaryView,
    ResearchCenterPipelineSummaryView,
    ResearchCenterQueryService,
    ResearchCenterResearchEvidenceView,
    ResearchCenterResearchRunsSummaryView,
    ResearchCenterResearchSummaryView,
    sanitize_source_value,
)
from invest_api.application.research_center import (
    ResearchCenterResponse as ResearchCenterResponseView,
)
from invest_api.dependencies import get_research_center_query_service
from invest_api.schemas.research_center import (
    ResearchCenterBreadthResponse,
    ResearchCenterCandidatePoolSummaryResponse,
    ResearchCenterCapabilitiesResponse,
    ResearchCenterCapabilityResponse,
    ResearchCenterDataFreshnessResponse,
    ResearchCenterDeliveryArchiveResponse,
    ResearchCenterDeliveryIntegrationResponse,
    ResearchCenterDeliveryPipelineResponse,
    ResearchCenterDeliveryResearchRunsResponse,
    ResearchCenterDeliveryResponse,
    ResearchCenterLatestCaseResponse,
    ResearchCenterMarketResponse,
    ResearchCenterObservationResponse,
    ResearchCenterOpportunitySummaryResponse,
    ResearchCenterResearchEvidenceResponse,
    ResearchCenterResearchSummaryResponse,
    ResearchCenterResponse,
    ResearchCenterSchemaVersion,
)

router = APIRouter(prefix="/api/v1/research-center", tags=["research-center"])


def _observation_from_view(
    view: ResearchCenterObservationView,
) -> ResearchCenterObservationResponse:
    """Translate one application observation onto the Pydantic shape."""

    return ResearchCenterObservationResponse(
        key=view.key,
        value=view.value,
        unit=view.unit,
        observed_date=view.observed_date,
        source_kind=view.source_kind,
        source_ref=view.source_ref,
        quality_status=view.quality_status,
    )


def _breadth_from_view(
    view: ResearchCenterBreadthView | None,
) -> ResearchCenterBreadthResponse | None:
    """Translate the application breadth view (or its absence) onto the Pydantic shape."""

    if view is None:
        return None
    return ResearchCenterBreadthResponse(
        state=view.state,  # type: ignore[arg-type]
        snapshot_id=view.snapshot_id,
        algorithm_version=view.algorithm_version,
        scope_type=view.scope_type,
        scope_key=view.scope_key,
        observations=(
            [_observation_from_view(item) for item in view.observations]
            if view.observations is not None
            else None
        ),
    )


def _data_freshness_from_view(
    view: ResearchCenterDataFreshnessView | None,
    *,
    checked_at: datetime,
) -> ResearchCenterDataFreshnessResponse | None:
    """Translate the application freshness view onto the Pydantic shape.

    ``checked_at`` is the router-owned UTC wall-clock value reused for
    the top-level ``generated_at``; the application service
    intentionally does not own a clock, so this is the only place the
    timestamp is materialised.
    """

    if view is None:
        return None
    return ResearchCenterDataFreshnessResponse(
        state=view.state,  # type: ignore[arg-type]
        checked_at=checked_at,
        latest_published_trade_date=view.latest_published_trade_date,
        universe_count=view.universe_count,
        daily_bar_count=view.daily_bar_count,
        missing_count=view.missing_count,
        status=view.status,  # type: ignore[arg-type]
    )


def _market_from_view(
    view: ResearchCenterMarketView,
    *,
    checked_at: datetime,
) -> ResearchCenterMarketResponse:
    """Translate the application market view onto the Pydantic shape."""

    return ResearchCenterMarketResponse(
        state=view.state,  # type: ignore[arg-type]
        as_of_date=view.as_of_date,
        quality_status=view.quality_status,
        freshness_status=view.freshness_status,
        breadth=_breadth_from_view(view.breadth),
        data_freshness=_data_freshness_from_view(
            view.data_freshness, checked_at=checked_at
        ),
    )


def _capability_from_view(
    view: ResearchCenterCapabilityView,
) -> ResearchCenterCapabilityResponse:
    """Translate one application capability entry onto the Pydantic shape."""

    return ResearchCenterCapabilityResponse(state=view.state, reason=view.reason)  # type: ignore[arg-type]


def _capabilities_from_view(
    view: ResearchCenterCapabilitiesView,
) -> ResearchCenterCapabilitiesResponse:
    """Translate the Slice 1 capability bundle onto the Pydantic shape."""

    return ResearchCenterCapabilitiesResponse(
        opportunities=_capability_from_view(view.opportunities),
        research=_capability_from_view(view.research),
        delivery=_capability_from_view(view.delivery),
        strategy=_capability_from_view(view.strategy),
        discipline=_capability_from_view(view.discipline),
    )


def _latest_case_from_view(
    view: ResearchCenterLatestCaseView | None,
) -> ResearchCenterLatestCaseResponse | None:
    """Translate the application latest-case view onto the Pydantic shape."""

    if view is None:
        return None
    return ResearchCenterLatestCaseResponse(
        case_id=view.case_id,
        as_of_date=view.as_of_date,
    )


def _research_evidence_from_view(
    view: ResearchCenterResearchEvidenceView,
) -> ResearchCenterResearchEvidenceResponse:
    """Translate the application evidence sub-view onto the Pydantic shape."""

    return ResearchCenterResearchEvidenceResponse(
        state=view.state,  # type: ignore[arg-type]
        pack_id=view.pack_id,
        quality_status=view.quality_status,
        freshness_status=view.freshness_status,
    )


def _research_summary_from_view(
    view: ResearchCenterResearchSummaryView,
) -> ResearchCenterResearchSummaryResponse:
    """Translate the Slice 2A research sub-segment onto the Pydantic shape.

    Asserts ``schema_version`` against the application-level frozen
    constant so any drift between the application view and the
    public contract raises a generic exception *before* Pydantic
    serialisation, identical to the top-level guard.
    """

    if view.state == "failed" and (
        view.case_count is not None or view.run_count is not None
    ):
        raise RuntimeError(
            "research-center research sub-segment reported failure with "
            "non-null counts; refusing to serialise a fabricated total"
        )
    return ResearchCenterResearchSummaryResponse(
        schema_version=RESEARCH_SCHEMA_VERSION,  # type: ignore[arg-type]
        state=view.state,  # type: ignore[arg-type]
        case_count=view.case_count,
        run_count=view.run_count,
        latest_case=_latest_case_from_view(view.latest_case),
        evidence=_research_evidence_from_view(view.evidence),
    )


def _candidate_pool_from_view(
    view: ResearchCenterCandidatePoolSummaryView,
) -> ResearchCenterCandidatePoolSummaryResponse:
    """Translate the Slice 2B candidate-pool sub-segment onto the Pydantic shape.

    Mirrors
    :class:`ResearchCenterCandidatePoolSummaryView` field-by-field;
    the application-level invariant check is enforced there so this
    mapper stays a thin pass-through. No investment conclusions,
    per-instrument metrics or policy hashes are projected so the
    public contract stays a bounded summary.
    """

    return ResearchCenterCandidatePoolSummaryResponse(
        state=view.state,  # type: ignore[arg-type]
        run_id=view.run_id,
        trade_date=view.trade_date,
        input_row_count=view.input_row_count,
        included_count=view.included_count,
        excluded_count=view.excluded_count,
        reason=view.reason,
    )


def _opportunity_from_view(
    view: ResearchCenterOpportunitySummaryView,
) -> ResearchCenterOpportunitySummaryResponse:
    """Translate the Slice 2B opportunity sub-segment onto the Pydantic shape.

    Mirrors
    :class:`ResearchCenterOpportunitySummaryView` field-by-field;
    the bounded observation count, the latest ``as_of`` date and the
    admission-status counts come straight from the application-level
    view so the public contract stays a bounded summary.
    """

    return ResearchCenterOpportunitySummaryResponse(
        state=view.state,  # type: ignore[arg-type]
        observation_count=view.observation_count,
        latest_as_of=view.latest_as_of,
        admission_status_counts=(
            dict(view.admission_status_counts)
            if view.admission_status_counts is not None
            else None
        ),
        reason=view.reason,
    )


def _delivery_pipeline_from_view(
    view: ResearchCenterPipelineSummaryView,
) -> ResearchCenterDeliveryPipelineResponse:
    """Translate the pipeline sub-segment onto the Pydantic shape.

    Mirrors
    :class:`ResearchCenterPipelineSummaryView` field-by-field;
    the application-level invariant check is enforced there so
    this mapper stays a thin pass-through. The pipeline
    sub-segment is the only delivery sub-segment whose ``state``
    vocabulary is extended to five states (``available | empty
    | running | partial | failed``) so the UI can render an
    in-flight or partially-completed run without misclassifying
    it. The Slice 3B ``freshness_at`` anchor is projected
    verbatim from the application-level view so the central
    page can render the freshness badge.

    ``source`` is **not** trusted verbatim: the mapper feeds
    ``view.source`` through the canonical application-layer
    :func:`sanitize_source_value` filter against the
    :data:`PIPELINE_TRIGGER_TYPE_WHITELIST` whitelist so a
    rogue upstream caller who bypasses
    :class:`ResearchCenterQueryService` and hands a
    pre-built view to the API boundary cannot echo a
    credential, host path, control character or
    connection string. Whitelisted labels
    (``"scheduled"`` / ``"manual"`` / ``"dagster"``) round-trip
    verbatim; every other value the whitelist rejects —
    including ``None`` — surfaces as ``None`` on the wire.
    Defence-in-depth: the application service already runs the
    same filter at view construction time, so the router
    mapper re-applies the exact same canonical filter to keep
    the contract intact when a view reaches the boundary
    through any other path (tests, future programmatic
    callers, regression fixtures).
    """

    return ResearchCenterDeliveryPipelineResponse(
        state=view.state,  # type: ignore[arg-type]
        status=view.status,
        started_at=view.started_at,
        finished_at=view.finished_at,
        business_completion_date=view.business_completion_date,
        freshness_at=view.freshness_at,
        source=sanitize_source_value(
            view.source,
            whitelist=PIPELINE_TRIGGER_TYPE_WHITELIST,
        ),
        reason=view.reason,
    )


def _delivery_integration_from_view(
    view: ResearchCenterIntegrationSummaryView,
) -> ResearchCenterDeliveryIntegrationResponse:
    """Translate the integration sub-segment onto the Pydantic shape.

    Mirrors
    :class:`ResearchCenterIntegrationSummaryView` field-by-field;
    the bounded ``sample_size``, the pre-populated
    ``producer_status_counts`` / ``intake_status_counts``
    dictionaries, the latest ``as_of`` date and the bounded
    ``freshness_at`` anchor are projected verbatim from the
    application-level view. No payload blob, source URI, run
    identifier, host path, producer identifier, secret or
    connection string is projected.

    ``source`` is **not** trusted verbatim: the mapper feeds
    ``view.source`` through the canonical application-layer
    :func:`sanitize_source_value` filter against the
    :data:`INTEGRATION_PRODUCER_WHITELIST` whitelist so a
    rogue upstream caller who bypasses
    :class:`ResearchCenterQueryService` cannot echo a
    credential, host path, control character or
    connection string. Whitelisted labels
    (``"workbuddy"`` / ``"cifangquant"`` / ``"fixture"`` /
    ``"fixture_dev"``) round-trip verbatim; every other value
    surfaces as ``None`` on the wire. Defence-in-depth: the
    application service already runs the same filter at view
    construction time, so the router mapper re-applies the
    canonical filter to keep the contract intact for any
    boundary caller (tests, fixtures, future programmatic
    callers).
    """

    return ResearchCenterDeliveryIntegrationResponse(
        state=view.state,  # type: ignore[arg-type]
        status=view.status,
        sample_size=view.sample_size,
        producer_status_counts=(
            dict(view.producer_status_counts)
            if view.producer_status_counts is not None
            else None
        ),
        intake_status_counts=(
            dict(view.intake_status_counts)
            if view.intake_status_counts is not None
            else None
        ),
        latest_as_of=view.latest_as_of,
        freshness_at=view.freshness_at,
        source=sanitize_source_value(
            view.source,
            whitelist=INTEGRATION_PRODUCER_WHITELIST,
        ),
        reason=view.reason,
    )


def _delivery_archive_from_view(
    view: ResearchCenterArchiveSummaryView,
) -> ResearchCenterDeliveryArchiveResponse:
    """Translate the archive sub-segment onto the Pydantic shape.

    Mirrors
    :class:`ResearchCenterArchiveSummaryView` field-by-field;
    the bounded ``artifact_count``, the latest run's
    :attr:`ExternalWorkflowRun.producer_status` value, the
    maximum ``created_at.date()`` across the bounded artifact
    slice and the bounded ``freshness_at`` anchor are
    projected verbatim. No artifact URI, payload, metadata,
    host path, logical URI, content hash, run identifier,
    secret or connection string is projected.

    ``source`` is **not** trusted verbatim: the mapper feeds
    ``view.source`` through the canonical application-layer
    :func:`sanitize_source_value` filter against the
    :data:`ARCHIVE_MEDIA_TYPE_WHITELIST` whitelist so a
    rogue upstream caller who bypasses
    :class:`ResearchCenterQueryService` cannot echo a
    logical URI, host path, content hash, payload blob,
    credential, control character or connection string.
    Whitelisted IANA-registered media types
    (``"application/json"`` / ``"application/pdf"`` /
    ``"application/xml"`` / ``"text/plain"`` /
    ``"text/markdown"`` / ``"text/html"`` / ``"text/csv"``)
    round-trip verbatim; every other value surfaces as
    ``None`` on the wire. Defence-in-depth: the application
    service already runs the same filter at view construction
    time, so the router mapper re-applies the canonical
    filter to keep the contract intact for any boundary
    caller.
    """

    return ResearchCenterDeliveryArchiveResponse(
        state=view.state,  # type: ignore[arg-type]
        artifact_count=view.artifact_count,
        latest_as_of=view.latest_as_of,
        freshness_at=view.freshness_at,
        source=sanitize_source_value(
            view.source,
            whitelist=ARCHIVE_MEDIA_TYPE_WHITELIST,
        ),
        latest_run_status=view.latest_run_status,
        reason=view.reason,
    )


def _delivery_research_runs_from_view(
    view: ResearchCenterResearchRunsSummaryView,
) -> ResearchCenterDeliveryResearchRunsResponse:
    """Translate the research-runs sub-segment onto the Pydantic shape.

    Mirrors
    :class:`ResearchCenterResearchRunsSummaryView` field-by-field;
    the bounded ``run_count``, the pre-populated
    :class:`ResearchRunStatus` -> ``int`` count dictionary, the
    most-recent run's status / start / finish timestamps and
    the bounded ``freshness_at`` anchor are projected
    verbatim. No report body, evidence bundle,
    ``error_summary``, ``case_id``, ``playbook_key`` or
    ``evidence_pack_id`` is projected.

    ``source`` is **not** trusted verbatim: the mapper feeds
    ``view.source`` through the canonical application-layer
    :func:`sanitize_source_value` filter against the
    :data:`RESEARCH_RUNS_RUNNER_KEY_WHITELIST` whitelist so a
    rogue upstream caller who bypasses
    :class:`ResearchCenterQueryService` cannot echo a host
    path, credential, control character, payload blob or
    connection string. Whitelisted runner keys
    (``"jiuwenswarm-runner-v1"`` / ``"jiuwenswarm"`` /
    ``"llm"`` / ``"deterministic"`` / ``"fake-runner-v1"``)
    round-trip verbatim; every other value surfaces as
    ``None`` on the wire. Defence-in-depth: the application
    service already runs the same filter at view construction
    time, so the router mapper re-applies the canonical
    filter to keep the contract intact for any boundary
    caller.
    """

    return ResearchCenterDeliveryResearchRunsResponse(
        state=view.state,  # type: ignore[arg-type]
        run_count=view.run_count,
        status_counts=(
            dict(view.status_counts)
            if view.status_counts is not None
            else None
        ),
        latest_status=view.latest_status,
        latest_started_at=view.latest_started_at,
        latest_finished_at=view.latest_finished_at,
        freshness_at=view.freshness_at,
        source=sanitize_source_value(
            view.source,
            whitelist=RESEARCH_RUNS_RUNNER_KEY_WHITELIST,
        ),
        reason=view.reason,
    )


def _delivery_from_view(
    view: ResearchCenterDeliveryView,
) -> ResearchCenterDeliveryResponse:
    """Translate the Slice 3A delivery sub-segment onto the Pydantic shape.

    Asserts ``schema_version`` against the application-level frozen
    constant so any drift between the application view and the
    public contract raises a generic exception *before* Pydantic
    serialisation, identical to the top-level guard. The four
    sub-segments are translated independently so a single
    controlled failure on one of the four sources can never bleed
    into the other three.
    """

    if view.schema_version != DELIVERY_SCHEMA_VERSION:
        raise RuntimeError(
            "research-center delivery schema version drift; "
            "refusing to serialise"
        )
    return ResearchCenterDeliveryResponse(
        schema_version=DELIVERY_SCHEMA_VERSION,  # type: ignore[arg-type]
        pipeline=_delivery_pipeline_from_view(view.pipeline),
        integration=_delivery_integration_from_view(view.integration),
        archive=_delivery_archive_from_view(view.archive),
        research_runs=_delivery_research_runs_from_view(view.research_runs),
    )


def _response_from_view(
    view: ResearchCenterResponseView,
    *,
    generated_at: datetime,
    checked_at: datetime,
) -> ResearchCenterResponse:
    """Translate the application response view onto the public Pydantic shape.

    ``generated_at`` and ``checked_at`` come from the same
    ``datetime.now(UTC)`` call captured by the handler so the two
    timestamps are always identical for one response. ``schema_version``
    is sourced from the application-level frozen constant; any drift
    between the application view and the public contract is treated as
    an internal invariant violation and raises a generic exception
    *before* any Pydantic serialisation runs, so the unexpected value
    cannot leak through the response body and FastAPI's generic error
    boundary stays in charge of the 500 surface.
    """

    if view.schema_version != ResearchCenterSchemaVersion:
        raise RuntimeError(
            "research-center schema version drift; refusing to serialise"
        )
    return ResearchCenterResponse(
        schema_version=ResearchCenterSchemaVersion,  # type: ignore[arg-type]
        generated_at=generated_at,
        state=view.state,  # type: ignore[arg-type]
        market=_market_from_view(view.market, checked_at=checked_at),
        capabilities=_capabilities_from_view(view.capabilities),
        research=_research_summary_from_view(view.research),
        candidate_pool=_candidate_pool_from_view(view.candidate_pool),
        opportunities=_opportunity_from_view(view.opportunities),
        delivery=_delivery_from_view(view.delivery),
    )


@router.get("", response_model=ResearchCenterResponse)
def get_research_center(
    service: Annotated[
        ResearchCenterQueryService, Depends(get_research_center_query_service)
    ],
) -> ResearchCenterResponse:
    """Return the Slice 1 Research Center contract response.

    The handler owns a single UTC wall-clock value and reuses it for
    both ``generated_at`` and ``market.data_freshness.checked_at`` so
    the two timestamps are always identical. The application service
    converts the two underlying sources' controlled errors into
    explicit failed sub-segments before this router sees them; any
    other exception is intentionally allowed to propagate so FastAPI's
    generic error boundary (and not this router) sanitises the
    response. The endpoint is intentionally GET-only — no POST, PUT,
    PATCH or DELETE handlers exist on this router and the OpenAPI
    spec reflects that.
    """

    generated_at = datetime.now(UTC)
    view = service.get_research_center()
    return _response_from_view(
        view, generated_at=generated_at, checked_at=generated_at
    )


__all__ = ["router"]
