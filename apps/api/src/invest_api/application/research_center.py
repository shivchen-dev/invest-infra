"""Application Read Model for the Research Center home page.

The Research Center slice composes the two existing read-only
application services — :class:`MarketBreadthQueryService` and
:class:`DataFreshnessQueryService` — into a single
:class:`ResearchCenterResponse` view the future
``/api/v1/research-center`` router can render.

Per the Slice 1 contract (see
``docs/implementation/RESEARCH-CENTER-SLICE0-CONTRACT.md``):

* the service owns no wall-clock responsibility — ``generated_at``
  and ``checked_at`` are stamped together by the future router;
* the two underlying sources are fetched independently (no HTTP
  fan-out, no repository, no migration, no singleton);
* only :class:`MarketBreadthQueryError` and
  :class:`DataFreshnessQueryError` are translated into a missing or
  failed sub-segment; any other exception propagates so the router's
  generic error boundary stays in charge of sanitising driver-level
  detail;
* the top-level ``state`` mirrors the market ``state`` for Slice 1.

The service depends on the two application service instances
structurally — any object exposing ``get_latest(None)`` and
``get_freshness(None)`` respectively satisfies the constructor — so
tests can substitute lightweight mocks without touching the
storage layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

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

SCHEMA_VERSION: str = "1.0.0"
"""Frozen response ``schema_version`` the router passes through unchanged."""


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
class ResearchCenterResponse:
    """Read-only response the router maps onto the public JSON shape.

    ``schema_version`` is the contract version; ``state`` is the
    top-level response state and equals ``market.state`` for Slice
    1. The service does not include ``generated_at`` (a UTC
    wall-clock stamp owned by the future router) — the router
    stamps both ``generated_at`` and ``checked_at`` together so two
    callers hitting the service in the same instant observe the
    same timestamp pair.
    """

    schema_version: str
    state: str
    market: ResearchCenterMarketView
    capabilities: ResearchCenterCapabilitiesView


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

    Composes the existing :class:`MarketBreadthQueryService` and
    :class:`DataFreshnessQueryService` so the future
    ``research-center`` router can render the contract response
    without duplicating the orchestration already owned by the two
    slice services. The service intentionally depends on the
    application service interfaces (not on the storage
    repositories or HTTP clients) so the router remains the only
    place that maps to the public JSON shape and the application
    layer can be exercised end-to-end without a live database.

    Each underlying call is wrapped in its own narrow error
    boundary: only :class:`MarketBreadthQueryError` and
    :class:`DataFreshnessQueryError` are translated into a missing
    or failed sub-segment; any other exception propagates so the
    router's generic error boundary stays in charge of sanitising
    driver-level detail.
    """

    def __init__(
        self,
        breadth: MarketBreadthQueryService,
        freshness: DataFreshnessQueryService,
    ) -> None:
        self._breadth = breadth
        self._freshness = freshness

    def get_research_center(self) -> ResearchCenterResponse:
        """Return the Research Center response view for Slice 1.

        The breadth and freshness reads are issued independently
        (``get_latest(None)`` and ``get_freshness(None)``) so neither
        side blocks on the other; their results feed a single
        state derivation that decides the top-level and market
        ``state`` together.
        """

        breadth_snapshot, breadth_error = self._fetch_breadth()
        freshness_view, freshness_error = self._fetch_freshness()
        return self._build_response(
            breadth_snapshot, breadth_error, freshness_view, freshness_error
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

    def _build_response(
        self,
        breadth_snapshot: MarketObservationSnapshot | None,
        breadth_error: MarketBreadthQueryError | None,
        freshness_view: DataFreshnessView | None,
        freshness_error: DataFreshnessQueryError | None,
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
    "ResearchCenterBreadthView",
    "ResearchCenterCapabilitiesView",
    "ResearchCenterCapabilityView",
    "ResearchCenterDataFreshnessView",
    "ResearchCenterMarketView",
    "ResearchCenterObservationView",
    "ResearchCenterQueryService",
    "ResearchCenterResponse",
    "SCHEMA_VERSION",
]
