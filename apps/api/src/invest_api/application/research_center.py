"""Application Read Model for the Research Center home page.

The Research Center slice composes five existing read-only
application services — :class:`MarketBreadthQueryService`,
:class:`DataFreshnessQueryService`, :class:`ResearchQueryService`,
:class:`CandidatePoolQueryService` and
:class:`ExternalWorkflowQueryService` — into a single
:class:`ResearchCenterResponse` view the
``/api/v1/research-center`` router can render.

Per the Slice 1 contract (see
``docs/implementation/RESEARCH-CENTER-SLICE0-CONTRACT.md``):

* the service owns no wall-clock responsibility — ``generated_at``
  and ``checked_at`` are stamped together by the router;
* the underlying sources are fetched independently (no HTTP
  fan-out, no repository, no migration, no singleton);
* only :class:`MarketBreadthQueryError`,
  :class:`DataFreshnessQueryError`, :class:`ResearchQueryError`,
  :class:`CandidatePoolQueryError`,
  :class:`CandidatePoolSnapshotMissingError` and a
  :class:`sqlalchemy.exc.SQLAlchemyError` raised by the external
  workflow reader are translated into a missing or failed
  sub-segment; any other exception propagates so the router's
  generic error boundary stays in charge of sanitising
  driver-level detail;
* the top-level ``state`` mirrors the market ``state`` for Slice 1
  (later slices may fold the research sub-segment in).

Slice 2A adds the ``research`` sub-segment: it is a thin
projection of :meth:`ResearchQueryService.get_dashboard`, carrying
the exact ``case_count`` / ``run_count``, the latest case identity
and ``as_of_date`` when present, and the evidence ``state`` /
``quality_status`` / ``freshness_status`` already exposed by the
existing :class:`ResearchDashboardView`. No HTTP fan-out, no second
research query implementation, no fabrication: a successful read
that observes zero cases reports ``state="empty"`` (the count is
real, never a stand-in for "unavailable"), and a controlled
:class:`ResearchQueryError` reports ``state="failed"``. Candidate
Pool, external Opportunity Radar, strategy and discipline stays out
of this increment.

Slice 2B adds the ``candidate_pool`` and ``opportunities``
sub-segments on top of the existing ``market``, ``capabilities``
and ``research`` bundle without reshaping any existing field.
Both sub-segments use the same three-state vocabulary
``available | empty | failed`` the Slice 2A ``research``
sub-segment already pins: ``empty`` is reserved for the real
zero-observation / no-published-run path, ``failed`` is reserved
for the controlled error boundaries the underlying services
raise, and the count fields stay ``None`` under ``failed`` so a
fabricated zero cannot masquerade as "data unavailable". Only
bounded source facts are projected: the candidate-pool summary
exposes the latest published run identity / trade date and
``input_row_count`` / ``included_count`` / ``excluded_count``;
the opportunity summary exposes a bounded observation count, the
latest ``as_of`` when present, and admission-status counts keyed
by the existing :class:`invest_domain.integration.AdmissionStatus`
values. Strategy and discipline remain Slice 1 placeholders.

The service depends on the five application service instances
structurally — any object exposing ``get_latest(None)``,
``get_freshness(None)``, ``get_dashboard()``,
``candidate_pool.get_latest()`` and
``external_workflows.list_radar(status=None, limit=..., offset=...)``
respectively satisfies the constructor — so tests can substitute
lightweight mocks without touching the storage layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from invest_domain.analytics.market_observations import MarketObservationSnapshot
from invest_domain.integration.models import AdmissionStatus, ExternalObservation
from sqlalchemy.exc import SQLAlchemyError

from invest_api.application.candidate_pool import (
    CandidatePoolQueryError,
    CandidatePoolQueryService,
    CandidatePoolSnapshotMissingError,
    LatestCandidatePoolView,
)
from invest_api.application.data_freshness import (
    DataFreshnessQueryError,
    DataFreshnessQueryService,
    DataFreshnessView,
)
from invest_api.application.external_workflows import ExternalWorkflowQueryService
from invest_api.application.market_breadth import (
    MarketBreadthQueryError,
    MarketBreadthQueryService,
)
from invest_api.application.research import (
    ResearchDashboardEvidenceStatusView,
    ResearchDashboardResearchSummaryView,
    ResearchDashboardView,
    ResearchQueryError,
    ResearchQueryService,
)

SCHEMA_VERSION: str = "1.0.0"
"""Frozen response ``schema_version`` the router passes through unchanged."""

RESEARCH_SCHEMA_VERSION: str = "1.0.0"
"""Frozen ``research.schema_version`` the router mirrors onto the contract response.

Mirrors the upstream dashboard contract version so the central
``research-center`` endpoint does not invent a separate version. The
router asserts the value against the application-level constant before
serialising so a drift never leaks through the public response.
"""

RESEARCH_FAILED_REASON: str = "research_query_failed"
"""Stable reason emitted for the ``state == "failed"`` research sub-segment.

The router never echoes driver-level detail (no path, connection string
or credential text). The single constant is the only legal reason for
the controlled ``ResearchQueryError`` boundary.
"""

RESEARCH_EMPTY_REASON: str = "no_research_cases"
"""Stable reason emitted when the research read succeeded but observed zero cases.

The dashboard's ``count_all`` returned ``0`` so the sub-segment reports
the explicit empty state without fabricating a value or borrowing
``unavailable`` semantics from the market segment vocabulary.
"""

CANDIDATE_POOL_FAILED_REASON: str = "candidate_pool_query_failed"
"""Stable reason emitted for the ``state == "failed"`` candidate-pool sub-segment.

Mirrors the Slice 2A ``research`` sub-segment convention: the single
constant is the only legal reason for the controlled
:class:`CandidatePoolQueryError` boundary (storage / driver error).
The router never echoes driver-level detail (no path, connection
string or credential text) so the public response can only carry this
opaque reason.
"""

CANDIDATE_POOL_SNAPSHOT_MISSING_REASON: str = "candidate_pool_snapshot_missing"
"""Stable reason emitted when the candidate-pool snapshot integrity check fails.

The published run references an input snapshot that does not exist
anymore; this is a logical integrity violation (storage corruption)
rather than a transient driver error so the public response still
uses ``state == "failed"`` but with a distinct reason so the front-end
can distinguish a missing snapshot from a regular query failure
without leaking the underlying identifier.
"""

OPPORTUNITY_RADAR_LIMIT: int = 50
"""Internal bound for the opportunity-radar summary.

Kept small and constant so the central ``research-center`` summary
never fans out beyond the first page of the existing
:meth:`ExternalWorkflowQueryService.list_radar` contract. The bound
is applied server-side; the front-end never observes an
``observation_count`` larger than this constant regardless of how
many rows exist in storage. The bound is independent from the
``status`` filter (always ``None`` for the summary) so the result is
the freshest admission-agnostic slice of the radar.
"""

OPPORTUNITY_FAILED_REASON: str = "opportunity_radar_query_failed"
"""Stable reason emitted for the ``state == "failed"`` opportunity sub-segment.

The external-workflow reader does not translate
:class:`sqlalchemy.exc.SQLAlchemyError` into a typed application error,
so the Slice 2B read-side catches the storage error directly and
emits this opaque reason instead of any driver-level detail.
"""

OPPORTUNITY_EMPTY_REASON: str = "no_opportunity_observations"
"""Stable reason emitted when the opportunity read succeeded but observed zero rows.

The radar's ``list_recent(status=None, limit=..., offset=0)`` returned
an empty sequence so the sub-segment reports the explicit empty state
without fabricating a non-zero count or borrowing ``unavailable``
semantics from the market segment vocabulary.
"""


@dataclass(frozen=True, slots=True)
class ResearchCenterObservationView:
    """Single Market Breadth observation mapped to the contract field names.

    The contract renames the domain ``observation_key`` to the
    response ``key`` field and preserves every other observation
    field exactly (``value``, ``unit``, ``observed_date``,
    ``source_kind``, ``source_ref``, ``quality_status``). ``value``
    keeps its native ``Decimal | str | None`` type so the router can
    serialise it through the same Pydantic rules the existing
    Market Breadth router already uses.
    """

    key: str
    value: Decimal | str | None
    unit: str
    observed_date: date
    source_kind: str
    source_ref: str
    quality_status: str


@dataclass(frozen=True, slots=True)
class ResearchCenterBreadthView:
    """Market Breadth sub-segment of the research-center response.

    A controlled query error produces a ``state="failed"`` view with
    no payload. A genuinely missing snapshot remains ``None``. A
    successful snapshot uses ``state="available"`` and carries the
    real identity, scope and observations.
    """

    state: Literal["available", "failed"]
    snapshot_id: str | None = None
    algorithm_version: str | None = None
    scope_type: str | None = None
    scope_key: str | None = None
    observations: tuple[ResearchCenterObservationView, ...] | None = None


@dataclass(frozen=True, slots=True)
class ResearchCenterDataFreshnessView:
    """Data Freshness sub-segment of the research-center response.

    Returned whenever the freshness service produced a view. The
    ``state`` field is derived from ``status`` so the UI can render
    ``available | partial | unavailable | failed`` without
    re-reading the underlying five-state vocabulary. The router
    stamps ``checked_at`` when it materialises the response — the
    application service intentionally does not carry a wall clock.
    """

    state: Literal["available", "partial", "unavailable", "failed"]
    latest_published_trade_date: date | None
    universe_count: int | None
    daily_bar_count: int | None
    missing_count: int | None
    status: Literal["fresh", "partial", "stale", "missing", "failed"]


@dataclass(frozen=True, slots=True)
class ResearchCenterMarketView:
    """Market segment of the research-center response.

    ``state`` mirrors the top-level ``state`` for Slice 1 (the
    contract makes the two equivalent). ``as_of_date`` resolves to
    the breadth snapshot date first, falling back to the freshness
    latest published trade date, then ``None`` when neither source
    can offer a date. ``quality_status`` and ``freshness_status``
    carry the breadth domain values verbatim, or ``None`` when no
    breadth snapshot is available.
    """

    state: str
    as_of_date: date | None
    quality_status: str | None
    freshness_status: str | None
    breadth: ResearchCenterBreadthView | None
    data_freshness: ResearchCenterDataFreshnessView | None


@dataclass(frozen=True, slots=True)
class ResearchCenterCapabilityView:
    """Single capability entry.

    Slice 2+ will resolve ``state`` dynamically; Slice 1 pins every
    capability to a deterministic placeholder so the response shape
    is stable and the contract can advance without re-shaping the
    application layer.
    """

    state: str
    reason: str


@dataclass(frozen=True, slots=True)
class ResearchCenterCapabilitiesView:
    """Slice 1 capability bundle — frozen until later slices land."""

    opportunities: ResearchCenterCapabilityView
    research: ResearchCenterCapabilityView
    delivery: ResearchCenterCapabilityView
    strategy: ResearchCenterCapabilityView
    discipline: ResearchCenterCapabilityView


@dataclass(frozen=True, slots=True)
class ResearchCenterLatestCaseView:
    """Identity of the latest research case surfaced by the dashboard.

    The slice 0 contract only requires ``case_id`` (identity) and
    ``as_of_date`` (date); no other field of the underlying
    :class:`ResearchCase` is projected so the central surface stays a
    thin pointer to the detail page that already owns the full case.
    """

    case_id: UUID
    as_of_date: date


@dataclass(frozen=True, slots=True)
class ResearchCenterResearchEvidenceView:
    """Evidence slot that mirrors the dashboard's ``evidence_status`` verbatim.

    Slot-level fields (``pack_id``, ``quality_status``,
    ``freshness_status``) are exposed only when ``state ==
    "available"``; the explicit ``empty`` state carries ``None``
    placeholders so the front-end never has to special-case missing
    values. The sub-view only reflects fields the existing
    :class:`ResearchDashboardView` already produces — no factor-set
    identifiers or schema versions are invented here.
    """

    state: Literal["empty", "available"]
    pack_id: UUID | None
    quality_status: str | None
    freshness_status: str | None


@dataclass(frozen=True, slots=True)
class ResearchCenterResearchSummaryView:
    """Read-only aggregate of the existing research dashboard summary.

    ``state`` vocabulary is a deliberate three-state subset of the
    four-state market vocabulary, because this surface is not a
    dependency of any other system:

    * ``available`` — read succeeded and at least one case exists.
    * ``empty`` — read succeeded, ``count_all`` returned zero; the
      count is a real observation, never a stand-in for unavailable.
    * ``failed`` — the application service raised
      :class:`ResearchQueryError`; ``case_count`` and ``run_count``
      stay absent (the schema uses ``None``) so the UI cannot
      mis-render a fabricated total.

    ``case_count`` and ``run_count`` mirror ``ResearchDashboardView
    .research_summary`` exactly (``count_all`` is exact, not bounded
    by the recent-runs cap). ``latest_case`` is the slice 0
    identity/date projection of the dashboard's
    ``research_summary.latest_case``; ``None`` when no cases exist.
    ``evidence`` always carries a sub-view so the response shape is
    stable across the available / empty / failed transitions.
    """

    state: Literal["available", "empty", "failed"]
    case_count: int | None
    run_count: int | None
    latest_case: ResearchCenterLatestCaseView | None
    evidence: ResearchCenterResearchEvidenceView


@dataclass(frozen=True, slots=True)
class ResearchCenterCandidatePoolSummaryView:
    """Read-only bounded summary of the latest published candidate-pool run.

    ``state`` vocabulary is the same three-state subset Slice 2A pins
    on the ``research`` sub-segment so the central surface never has
    to invent a fourth "no published run yet" vocabulary:

    * ``available`` — :meth:`CandidatePoolQueryService.get_latest`
      returned a populated :class:`LatestCandidatePoolView`; the
      latest published run identity (``run_id``, ``trade_date``) and
      the row/included/excluded counts are exposed verbatim from the
      existing domain source so the central page can deep-link into
      the existing detail endpoint without inventing investment
      conclusions.
    * ``empty`` — :meth:`CandidatePoolQueryService.get_latest`
      returned ``None`` because no published run exists yet. Every
      count field stays ``None`` so the UI cannot mistake the
      "no published run yet" path for a populated zero total.
    * ``failed`` — the read raised a controlled
      :class:`CandidatePoolQueryError` (driver error) or a
      :class:`CandidatePoolSnapshotMissingError` (snapshot integrity
      violation). Every count field stays ``None`` and the opaque
      :data:`CANDIDATE_POOL_FAILED_REASON` /
      :data:`CANDIDATE_POOL_SNAPSHOT_MISSING_REASON` reason is
      surfaced so the UI can render an explicit failure slot.

    The sub-view only reflects fields the existing
    :class:`LatestCandidatePoolView` already produces — no
    policy hash, no per-instrument metrics, no factor-set identifiers
    are invented here.
    """

    state: Literal["available", "empty", "failed"]
    run_id: UUID | None = None
    trade_date: date | None = None
    input_row_count: int | None = None
    included_count: int | None = None
    excluded_count: int | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchCenterOpportunitySummaryView:
    """Read-only bounded summary of the external opportunity radar.

    ``state`` vocabulary is the same three-state subset Slice 2A pins
    on the ``research`` sub-segment:

    * ``available`` — :meth:`ExternalWorkflowQueryService.list_radar`
      returned at least one observation; ``observation_count`` is the
      bounded count (always ``<= OPPORTUNITY_RADAR_LIMIT``),
      ``latest_as_of`` resolves to the maximum ``as_of`` across the
      bounded slice (``None`` when the slice is empty by the time
      we read the dates), and ``admission_status_counts`` is a
      stable-key dictionary built from the existing
      :class:`invest_domain.integration.AdmissionStatus` vocabulary
      so the front-end can render the admission mix without
      fetching the full observation list.
    * ``empty`` — :meth:`ExternalWorkflowQueryService.list_radar`
      returned an empty sequence; ``observation_count`` is ``0``
      (the real observation count, never a stand-in for failure)
      and every other field stays ``None``.
    * ``failed`` — the read raised a
      :class:`sqlalchemy.exc.SQLAlchemyError` (the external-workflow
      reader does not translate storage errors to a typed
      application error); the observation count and admission status
      counts stay ``None`` so the UI cannot mistake the controlled
      failure for a real zero count.

    The sub-view exposes only bounded source facts — never payload
    blobs, never source URIs, never the underlying observation
    identity — so the central surface remains a thin pointer to the
    existing detail page that already owns the full shape. The
    distinction between external observation (the count itself)
    and admission status (the per-status breakdown) is preserved:
    ``observation_count`` is the bounded total and the dictionary
    keys map 1:1 onto the existing :class:`AdmissionStatus` values.
    """

    state: Literal["available", "empty", "failed"]
    observation_count: int | None = None
    latest_as_of: date | None = None
    admission_status_counts: dict[str, int] | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchCenterResponse:
    """Read-only response the router maps onto the public JSON shape.

    ``schema_version`` is the contract version; ``state`` is the
    top-level response state and equals ``market.state`` for Slice
    1. The service does not include ``generated_at`` (a UTC
    wall-clock stamp owned by the future router) — the router
    stamps both ``generated_at`` and ``checked_at`` together so two
    callers hitting the service in the same instant observe the
    same timestamp pair. Slice 2A adds the ``research`` sub-segment
    alongside the existing market / capabilities bundle without
    re-shaping any existing field. Slice 2B adds the
    ``candidate_pool`` and ``opportunities`` sub-segments on top of
    that bundle without re-shaping any existing field either; the
    top-level ``state`` still mirrors ``market.state`` until a
    later slice folds the candidate-pool / opportunity sub-segments
    into the state machine.
    """

    schema_version: str
    state: str
    market: ResearchCenterMarketView
    capabilities: ResearchCenterCapabilitiesView
    research: ResearchCenterResearchSummaryView
    candidate_pool: ResearchCenterCandidatePoolSummaryView
    opportunities: ResearchCenterOpportunitySummaryView


_FRESHNESS_SUBSTATE_BY_STATUS: dict[str, str] = {
    "fresh": "available",
    "partial": "partial",
    "stale": "partial",
    "missing": "unavailable",
    "failed": "failed",
}
"""Mapping from Data Freshness vocabulary to sub-segment ``state`` vocabulary."""


_DEFAULT_CAPABILITIES: ResearchCenterCapabilitiesView = ResearchCenterCapabilitiesView(
    opportunities=ResearchCenterCapabilityView(
        state="deferred", reason="slice_2_not_implemented"
    ),
    research=ResearchCenterCapabilityView(
        state="deferred", reason="slice_2_not_implemented"
    ),
    delivery=ResearchCenterCapabilityView(
        state="deferred", reason="slice_3_not_implemented"
    ),
    strategy=ResearchCenterCapabilityView(
        state="unavailable", reason="strategy_iteration_contract_not_frozen"
    ),
    discipline=ResearchCenterCapabilityView(
        state="unavailable", reason="position_discipline_contract_not_frozen"
    ),
)
"""Frozen Slice 1 capability bundle — Slice 2+ replaces this with real sources."""


class ResearchCenterQueryService:
    """Application Read Model for the Research Center home page.

    Composes the existing :class:`MarketBreadthQueryService`,
    :class:`DataFreshnessQueryService`,
    :class:`ResearchQueryService`,
    :class:`CandidatePoolQueryService` and
    :class:`ExternalWorkflowQueryService` so the
    ``research-center`` router can render the contract response
    without duplicating the orchestration already owned by the
    slice services. The service intentionally depends on the
    application service interfaces (not on the storage
    repositories or HTTP clients) so the router remains the only
    place that maps to the public JSON shape and the application
    layer can be exercised end-to-end without a live database.

    Each underlying call is wrapped in its own narrow error
    boundary: only :class:`MarketBreadthQueryError`,
    :class:`DataFreshnessQueryError`, :class:`ResearchQueryError`,
    :class:`CandidatePoolQueryError`,
    :class:`CandidatePoolSnapshotMissingError` and a
    :class:`sqlalchemy.exc.SQLAlchemyError` raised by the external
    workflow reader are translated into a missing or failed
    sub-segment; any other exception propagates so the router's
    generic error boundary stays in charge of sanitising
    driver-level detail.
    """

    def __init__(
        self,
        breadth: MarketBreadthQueryService,
        freshness: DataFreshnessQueryService,
        research: ResearchQueryService,
        candidate_pool: CandidatePoolQueryService,
        external_workflows: ExternalWorkflowQueryService,
    ) -> None:
        self._breadth = breadth
        self._freshness = freshness
        self._research = research
        self._candidate_pool = candidate_pool
        self._external_workflows = external_workflows

    def get_research_center(self) -> ResearchCenterResponse:
        """Return the Research Center response view for Slice 2B.

        The breadth, freshness, research, candidate-pool and
        opportunity reads are issued independently
        (``get_latest(None)``, ``get_freshness(None)``,
        ``get_dashboard()``, ``candidate_pool.get_latest()`` and
        ``external_workflows.list_radar(status=None, limit=...,
        offset=0)``) so neither side blocks on the other; the
        breadth / freshness results feed the state derivation that
        decides the top-level and market ``state``; the research,
        candidate-pool and opportunity results are projected onto
        the corresponding sub-segments without affecting the
        existing market state machine.
        """

        breadth_snapshot, breadth_error = self._fetch_breadth()
        freshness_view, freshness_error = self._fetch_freshness()
        research_view, research_error = self._fetch_research()
        (
            candidate_pool_view,
            candidate_pool_error,
        ) = self._fetch_candidate_pool()
        observations, opportunity_error = self._fetch_opportunities()
        return self._build_response(
            breadth_snapshot,
            breadth_error,
            freshness_view,
            freshness_error,
            research_view,
            research_error,
            candidate_pool_view,
            candidate_pool_error,
            observations,
            opportunity_error,
        )

    def _fetch_breadth(
        self,
    ) -> tuple[MarketObservationSnapshot | None, MarketBreadthQueryError | None]:
        try:
            return self._breadth.get_latest(None), None
        except MarketBreadthQueryError as exc:
            return None, exc

    def _fetch_freshness(
        self,
    ) -> tuple[DataFreshnessView | None, DataFreshnessQueryError | None]:
        try:
            return self._freshness.get_freshness(None), None
        except DataFreshnessQueryError as exc:
            return None, exc

    def _fetch_research(
        self,
    ) -> tuple[ResearchDashboardView | None, ResearchQueryError | None]:
        try:
            return self._research.get_dashboard(), None
        except ResearchQueryError as exc:
            return None, exc

    def _fetch_candidate_pool(
        self,
    ) -> tuple[
        LatestCandidatePoolView | None,
        CandidatePoolQueryError | CandidatePoolSnapshotMissingError | None,
    ]:
        try:
            return self._candidate_pool.get_latest(), None
        except (
            CandidatePoolQueryError,
            CandidatePoolSnapshotMissingError,
        ) as exc:
            return None, exc

    def _fetch_opportunities(
        self,
    ) -> tuple[Sequence[ExternalObservation] | None, SQLAlchemyError | None]:
        try:
            return (
                tuple(
                    self._external_workflows.list_radar(
                        status=None,
                        limit=OPPORTUNITY_RADAR_LIMIT,
                        offset=0,
                    )
                ),
                None,
            )
        except SQLAlchemyError as exc:
            return None, exc

    def _build_response(
        self,
        breadth_snapshot: MarketObservationSnapshot | None,
        breadth_error: MarketBreadthQueryError | None,
        freshness_view: DataFreshnessView | None,
        freshness_error: DataFreshnessQueryError | None,
        research_view: ResearchDashboardView | None,
        research_error: ResearchQueryError | None,
        candidate_pool_view: LatestCandidatePoolView | None,
        candidate_pool_error: (
            CandidatePoolQueryError | CandidatePoolSnapshotMissingError | None
        ),
        opportunity_observations: Sequence[ExternalObservation] | None,
        opportunity_error: SQLAlchemyError | None,
    ) -> ResearchCenterResponse:
        state = self._derive_state(
            breadth_snapshot, breadth_error, freshness_view, freshness_error
        )
        return ResearchCenterResponse(
            schema_version=SCHEMA_VERSION,
            state=state,
            market=ResearchCenterMarketView(
                state=state,
                as_of_date=self._resolve_as_of_date(
                    breadth_snapshot, freshness_view
                ),
                quality_status=(
                    breadth_snapshot.quality_status.value
                    if breadth_snapshot is not None
                    else None
                ),
                freshness_status=(
                    breadth_snapshot.freshness_status.value
                    if breadth_snapshot is not None
                    else None
                ),
                breadth=self._build_breadth_view(breadth_snapshot, breadth_error),
                data_freshness=self._build_freshness_view(
                    freshness_view, freshness_error
                ),
            ),
            capabilities=_DEFAULT_CAPABILITIES,
            research=self._build_research_view(research_view, research_error),
            candidate_pool=self._build_candidate_pool_view(
                candidate_pool_view, candidate_pool_error
            ),
            opportunities=self._build_opportunity_view(
                opportunity_observations, opportunity_error
            ),
        )

    @staticmethod
    def _build_breadth_view(
        snapshot: MarketObservationSnapshot | None,
        error: MarketBreadthQueryError | None,
    ) -> ResearchCenterBreadthView | None:
        if error is not None:
            return ResearchCenterBreadthView(state="failed")
        if snapshot is None:
            return None
        return ResearchCenterBreadthView(
            state="available",
            snapshot_id=snapshot.snapshot_id,
            algorithm_version=snapshot.algorithm_version,
            scope_type=snapshot.scope_type,
            scope_key=snapshot.scope_key,
            observations=tuple(
                ResearchCenterObservationView(
                    key=observation.observation_key,
                    value=observation.value,
                    unit=observation.unit,
                    observed_date=observation.observed_date,
                    source_kind=observation.source_kind,
                    source_ref=observation.source_ref,
                    quality_status=observation.quality_status.value,
                )
                for observation in snapshot.observations
            ),
        )

    @staticmethod
    def _build_freshness_view(
        view: DataFreshnessView | None,
        error: DataFreshnessQueryError | None,
    ) -> ResearchCenterDataFreshnessView | None:
        if error is not None:
            return ResearchCenterDataFreshnessView(
                state="failed",
                latest_published_trade_date=None,
                universe_count=None,
                daily_bar_count=None,
                missing_count=None,
                status="failed",
            )
        if view is None:
            return None
        return ResearchCenterDataFreshnessView(
            state=_FRESHNESS_SUBSTATE_BY_STATUS.get(view.status, "unavailable"),
            latest_published_trade_date=view.latest_published_trade_date,
            universe_count=view.universe_count,
            daily_bar_count=view.daily_bar_count,
            missing_count=view.missing_count,
            status=view.status,
        )

    @staticmethod
    def _build_research_view(
        view: ResearchDashboardView | None,
        error: ResearchQueryError | None,
    ) -> ResearchCenterResearchSummaryView:
        """Project :class:`ResearchDashboardView` onto the slice 0 sub-segment.

        Three explicit branches carry the slice 0 invariant
        *"never use fabricated zero values to mean unavailable"*:

        * ``ResearchQueryError`` → ``state="failed"`` with
          ``case_count`` and ``run_count`` left ``None``; the front
          end can render an explicit failure slot without mistaking
          ``0`` for "data unavailable".
        * ``view`` resolved with ``case_count == 0`` → ``state="empty"``
          with ``case_count`` / ``run_count`` carrying the real,
          observed values from the dashboard reader and
          ``latest_case`` left ``None``.
        * ``view`` resolved with at least one case → ``state="available"``
          with the dashboard-derived counts and the identity/date
          projection of ``research_summary.latest_case``.
        """

        if error is not None:
            return ResearchCenterResearchSummaryView(
                state="failed",
                case_count=None,
                run_count=None,
                latest_case=None,
                evidence=ResearchCenterResearchEvidenceView(
                    state="empty",
                    pack_id=None,
                    quality_status=None,
                    freshness_status=None,
                ),
            )

        if view is None:
            return ResearchCenterResearchSummaryView(
                state="failed",
                case_count=None,
                run_count=None,
                latest_case=None,
                evidence=ResearchCenterResearchEvidenceView(
                    state="empty",
                    pack_id=None,
                    quality_status=None,
                    freshness_status=None,
                ),
            )

        summary: ResearchDashboardResearchSummaryView = view.research_summary
        evidence: ResearchDashboardEvidenceStatusView = view.evidence_status
        case_count = summary.case_count
        run_count = summary.run_count

        if case_count <= 0:
            return ResearchCenterResearchSummaryView(
                state="empty",
                case_count=case_count,
                run_count=run_count,
                latest_case=None,
                evidence=ResearchCenterResearchEvidenceView(
                    state="empty",
                    pack_id=None,
                    quality_status=None,
                    freshness_status=None,
                ),
            )

        latest = summary.latest_case
        latest_case_view: ResearchCenterLatestCaseView | None
        if latest is not None:
            latest_case_view = ResearchCenterLatestCaseView(
                case_id=latest.case_id,
                as_of_date=latest.as_of_date,
            )
        else:
            latest_case_view = None

        evidence_view = ResearchCenterResearchEvidenceView(
            state=evidence.state,
            pack_id=evidence.pack_id,
            quality_status=evidence.quality_status,
            freshness_status=evidence.freshness_status,
        )

        return ResearchCenterResearchSummaryView(
            state="available",
            case_count=case_count,
            run_count=run_count,
            latest_case=latest_case_view,
            evidence=evidence_view,
        )

    @staticmethod
    def _build_candidate_pool_view(
        view: LatestCandidatePoolView | None,
        error: CandidatePoolQueryError | CandidatePoolSnapshotMissingError | None,
    ) -> ResearchCenterCandidatePoolSummaryView:
        """Project :class:`LatestCandidatePoolView` onto the Slice 2B sub-segment.

        Three explicit branches carry the Slice 2A invariant
        *"never use fabricated zero values to mean unavailable"*:

        * :class:`CandidatePoolQueryError` → ``state="failed"`` with
          :data:`CANDIDATE_POOL_FAILED_REASON`; every count and
          identity field stays ``None`` so the UI cannot mistake a
          controlled driver failure for "no published run yet".
        * :class:`CandidatePoolSnapshotMissingError` → ``state="failed"``
          with :data:`CANDIDATE_POOL_SNAPSHOT_MISSING_REASON`; the
          reason is distinct so the front-end can distinguish a
          snapshot-integrity violation from a regular query failure
          without leaking the underlying identifier.
        * ``view is None`` → ``state="empty"``; the candidate-pool
          reader explicitly observed zero published runs. Every
          count and identity field stays ``None`` so the UI cannot
          mistake the "no published run yet" path for a populated
          zero total.
        * ``view`` resolved → ``state="available"`` with the latest
          published run identity (``run_id``, ``trade_date``) and
          the row/included/excluded counts projected verbatim from
          :class:`LatestCandidatePoolView`. ``excluded_count`` is
          derived from ``input_row_count - included_count`` so the
          sub-view never re-queries the underlying items list.
        """

        if isinstance(error, CandidatePoolSnapshotMissingError):
            return ResearchCenterCandidatePoolSummaryView(
                state="failed",
                reason=CANDIDATE_POOL_SNAPSHOT_MISSING_REASON,
            )
        if isinstance(error, CandidatePoolQueryError):
            return ResearchCenterCandidatePoolSummaryView(
                state="failed",
                reason=CANDIDATE_POOL_FAILED_REASON,
            )
        if view is None:
            return ResearchCenterCandidatePoolSummaryView(state="empty")

        run = view.run
        excluded_count = max(
            run.input_row_count - run.included_count, 0
        )
        return ResearchCenterCandidatePoolSummaryView(
            state="available",
            run_id=run.id,
            trade_date=run.trade_date,
            input_row_count=run.input_row_count,
            included_count=run.included_count,
            excluded_count=excluded_count,
        )

    @staticmethod
    def _build_opportunity_view(
        observations: Sequence[ExternalObservation] | None,
        error: SQLAlchemyError | None,
    ) -> ResearchCenterOpportunitySummaryView:
        """Project the bounded radar slice onto the Slice 2B sub-segment.

        Three explicit branches mirror the Slice 2A research
        convention so the central surface never has to invent a
        fourth "no observations yet" vocabulary:

        * :class:`sqlalchemy.exc.SQLAlchemyError` → ``state="failed"``
          with :data:`OPPORTUNITY_FAILED_REASON`; the observation
          count and admission-status counts stay ``None`` so the UI
          cannot mistake a controlled storage failure for a real
          zero count.
        * ``observations`` empty → ``state="empty"`` with the real
          bounded count of ``0`` and every other field left
          ``None``; the radar reader explicitly observed zero rows.
        * ``observations`` non-empty → ``state="available"`` with
          the bounded observation count, the maximum ``as_of`` across
          the bounded slice (``None`` when every observation has no
          date), and a stable-key
          :class:`AdmissionStatus` -> ``int`` count dictionary built
          from the existing domain vocabulary so the front-end can
          render the admission mix without reaching into the
          observation list. The dictionary is pre-populated with
          every :class:`AdmissionStatus` value (zero-defaulted) so
          the UI never has to special-case missing keys.
        """

        if error is not None:
            return ResearchCenterOpportunitySummaryView(
                state="failed",
                reason=OPPORTUNITY_FAILED_REASON,
            )

        if not observations:
            return ResearchCenterOpportunitySummaryView(
                state="empty",
                observation_count=0,
                reason=OPPORTUNITY_EMPTY_REASON,
            )

        counts: dict[str, int] = {
            status.value: 0 for status in AdmissionStatus
        }
        latest_as_of: date | None = None
        for observation in observations:
            counts[observation.admission_status.value] += 1
            if latest_as_of is None or observation.as_of > latest_as_of:
                latest_as_of = observation.as_of

        return ResearchCenterOpportunitySummaryView(
            state="available",
            observation_count=len(observations),
            latest_as_of=latest_as_of,
            admission_status_counts=counts,
        )

    @staticmethod
    def _derive_state(
        breadth_snapshot: MarketObservationSnapshot | None,
        breadth_error: MarketBreadthQueryError | None,
        freshness_view: DataFreshnessView | None,
        freshness_error: DataFreshnessQueryError | None,
    ) -> str:
        """Resolve the Slice 1 top-level / market ``state``.

        The contract pins the four-state vocabulary strictly:

        * ``failed`` only when **both** market sources raised a
          controlled query error (the response must contain no
          exception text or driver detail);
        * ``unavailable`` only when neither source produced
          displayable data **and** neither source errored;
        * ``available`` only when both sources produced displayable
          data **and** breadth quality is ``complete`` / breadth
          freshness is ``fresh`` / freshness ``status`` is ``fresh``;
        * ``partial`` covers every remaining combination, including
          the explicitly-resolved ambiguity below.

        Ambiguity resolution (documented in the Slice 0 contract
        review notes and tested in
        :mod:`tests.test_research_center_service`):

        * Breadth controlled error + freshness ``status="missing"``
          (no published run, no pipeline run) → ``partial``. The
          contract's ``failed`` definition requires two controlled
          errors and ``unavailable`` requires no controlled error,
          so the only contract-consistent bucket left is
          ``partial`` (one source degraded, the other not
          displayable). This is the safest deterministic
          interpretation because it neither overclaims success
          (``available``) nor fabricates a total system outage
          (``failed``) when only one source query actually raised.
        * Breadth controlled error + freshness ``status="failed"``
          (pipeline failed, no same-day publish) → ``partial`` for
          the same reason: freshness did not raise, only breadth did.
        * Symmetrically, breadth missing + freshness controlled
          error → ``partial`` (the controlled error precludes
          ``unavailable``, and a single error precludes ``failed``).
        """

        breadth_displayable = breadth_snapshot is not None
        freshness_displayable = (
            freshness_view is not None
            and freshness_view.status not in {"missing", "failed"}
        )
        breadth_errored = breadth_error is not None
        freshness_errored = freshness_error is not None

        if breadth_errored and freshness_errored:
            return "failed"

        if (
            not breadth_displayable
            and not freshness_displayable
            and not breadth_errored
            and not freshness_errored
        ):
            return "unavailable"

        if breadth_displayable and freshness_displayable:
            breadth_complete = (
                breadth_snapshot.quality_status.value == "complete"
            )
            breadth_fresh = (
                breadth_snapshot.freshness_status.value == "fresh"
            )
            freshness_fresh = freshness_view.status == "fresh"
            if breadth_complete and breadth_fresh and freshness_fresh:
                return "available"

        return "partial"

    @staticmethod
    def _resolve_as_of_date(
        breadth_snapshot: MarketObservationSnapshot | None,
        freshness_view: DataFreshnessView | None,
    ) -> date | None:
        if breadth_snapshot is not None:
            return breadth_snapshot.as_of_date
        if freshness_view is not None:
            return freshness_view.latest_published_trade_date
        return None


__all__ = [
    "CANDIDATE_POOL_FAILED_REASON",
    "CANDIDATE_POOL_SNAPSHOT_MISSING_REASON",
    "OPPORTUNITY_EMPTY_REASON",
    "OPPORTUNITY_FAILED_REASON",
    "OPPORTUNITY_RADAR_LIMIT",
    "RESEARCH_EMPTY_REASON",
    "RESEARCH_FAILED_REASON",
    "RESEARCH_SCHEMA_VERSION",
    "ResearchCenterBreadthView",
    "ResearchCenterCandidatePoolSummaryView",
    "ResearchCenterCapabilitiesView",
    "ResearchCenterCapabilityView",
    "ResearchCenterDataFreshnessView",
    "ResearchCenterLatestCaseView",
    "ResearchCenterMarketView",
    "ResearchCenterObservationView",
    "ResearchCenterOpportunitySummaryView",
    "ResearchCenterQueryService",
    "ResearchCenterResearchEvidenceView",
    "ResearchCenterResearchSummaryView",
    "ResearchCenterResponse",
    "SCHEMA_VERSION",
]
