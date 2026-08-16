"""Read-only ``GET /api/v1/research-center`` endpoint.

This router is the only public surface of the central Research
Visualization Slice 1 module. It composes the two existing read-only
application services — :class:`MarketBreadthQueryService` and
:class:`DataFreshnessQueryService` — through the
:class:`ResearchCenterQueryService` the application layer owns, then
maps the resulting dataclass view onto the frozen
:class:`ResearchCenterResponse` Pydantic shape from
:mod:`invest_api.schemas.research_center`.

The router is intentionally minimal:

* it does not issue HTTP calls to either of the two underlying
  endpoints — composition happens in the application service against
  the same request-scoped SQLAlchemy session the other read routers
  already use;
* it stamps a single ``datetime.now(UTC)`` value and reuses it for
  both the top-level ``generated_at`` and
  ``market.data_freshness.checked_at`` so two callers hitting the
  endpoint in the same instant observe the same timestamp pair;
* it does not catch unknown exceptions: only the controlled
  per-source failures are already represented explicitly in the 200 response by
  the application service; anything else propagates so FastAPI's
  generic error boundary stays in charge of sanitising driver-level
  detail (no path, connection string or credential text in the
  response body).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from invest_api.application.research_center import (
    ResearchCenterBreadthView,
    ResearchCenterCapabilitiesView,
    ResearchCenterCapabilityView,
    ResearchCenterDataFreshnessView,
    ResearchCenterMarketView,
    ResearchCenterObservationView,
    ResearchCenterQueryService,
)
from invest_api.application.research_center import (
    ResearchCenterResponse as ResearchCenterResponseView,
)
from invest_api.dependencies import get_research_center_query_service
from invest_api.schemas.research_center import (
    ResearchCenterBreadthResponse,
    ResearchCenterCapabilitiesResponse,
    ResearchCenterCapabilityResponse,
    ResearchCenterDataFreshnessResponse,
    ResearchCenterMarketResponse,
    ResearchCenterObservationResponse,
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
