"""Application Read Model for the Research Center home page.

The Research Center slice composes three existing read-only
application services — :class:`MarketBreadthQueryService`,
:class:`DataFreshnessQueryService` and :class:`ResearchQueryService`
— into a single :class:`ResearchCenterResponse` view the
``/api/v1/research-center`` router can render.

Per the Slice 1 contract (see
``docs/implementation/RESEARCH-CENTER-SLICE0-CONTRACT.md``):

* the service owns no wall-clock responsibility — ``generated_at``
  and ``checked_at`` are stamped together by the router;
* the underlying sources are fetched independently (no HTTP
  fan-out, no repository, no migration, no singleton);
* only :class:`MarketBreadthQueryError`,
  :class:`DataFreshnessQueryError` and :class:`ResearchQueryError`
  are translated into a missing or failed sub-segment; any other
  exception propagates so the router's generic error boundary
  stays in charge of sanitising driver-level detail;
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

The service depends on the three application service instances
structurally — any object exposing ``get_latest(None)``,
``get_freshness(None)`` and ``get_dashboard()`` respectively
satisfies the constructor — so tests can substitute lightweight
mocks without touching the storage layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from invest_domain.analytics.market_observations import MarketObservationSnapshot

from invest_api.application.data_freshness import (
    DataFreshnessQueryError,
    DataFreshnessQueryService,
    DataFreshnessView,
)
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
    re-shaping any existing field.
    """

    schema_version: str
    state: str
    market: ResearchCenterMarketView
    capabilities: ResearchCenterCapabilitiesView
    research: ResearchCenterResearchSummaryView


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
    :class:`DataFreshnessQueryService` and
    :class:`ResearchQueryService` so the ``research-center`` router
    can render the contract response without duplicating the
    orchestration already owned by the slice services. The service
    intentionally depends on the application service interfaces
    (not on the storage repositories or HTTP clients) so the router
    remains the only place that maps to the public JSON shape and
    the application layer can be exercised end-to-end without a
    live database.

    Each underlying call is wrapped in its own narrow error
    boundary: only :class:`MarketBreadthQueryError`,
    :class:`DataFreshnessQueryError` and :class:`ResearchQueryError`
    are translated into a missing or failed sub-segment; any other
    exception propagates so the router's generic error boundary
    stays in charge of sanitising driver-level detail.
    """

    def __init__(
        self,
        breadth: MarketBreadthQueryService,
        freshness: DataFreshnessQueryService,
        research: ResearchQueryService,
    ) -> None:
        self._breadth = breadth
        self._freshness = freshness
        self._research = research

    def get_research_center(self) -> ResearchCenterResponse:
        """Return the Research Center response view for Slice 2A.

        The breadth, freshness and research reads are issued
        independently (``get_latest(None)``, ``get_freshness(None)``
        and ``get_dashboard()``) so neither side blocks on the
        other; the breadth / freshness results feed the state
        derivation that decides the top-level and market ``state``;
        the research result is projected onto the new ``research``
        sub-segment without affecting the existing state machine.
        """

        breadth_snapshot, breadth_error = self._fetch_breadth()
        freshness_view, freshness_error = self._fetch_freshness()
        research_view, research_error = self._fetch_research()
        return self._build_response(
            breadth_snapshot,
            breadth_error,
            freshness_view,
            freshness_error,
            research_view,
            research_error,
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

    def _build_response(
        self,
        breadth_snapshot: MarketObservationSnapshot | None,
        breadth_error: MarketBreadthQueryError | None,
        freshness_view: DataFreshnessView | None,
        freshness_error: DataFreshnessQueryError | None,
        research_view: ResearchDashboardView | None,
        research_error: ResearchQueryError | None,
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
    "RESEARCH_EMPTY_REASON",
    "RESEARCH_FAILED_REASON",
    "RESEARCH_SCHEMA_VERSION",
    "ResearchCenterBreadthView",
    "ResearchCenterCapabilitiesView",
    "ResearchCenterCapabilityView",
    "ResearchCenterDataFreshnessView",
    "ResearchCenterLatestCaseView",
    "ResearchCenterMarketView",
    "ResearchCenterObservationView",
    "ResearchCenterQueryService",
    "ResearchCenterResearchEvidenceView",
    "ResearchCenterResearchSummaryView",
    "ResearchCenterResponse",
    "SCHEMA_VERSION",
]
