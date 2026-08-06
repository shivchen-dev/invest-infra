"""Read-only data-freshness endpoint ``GET /api/v1/data-freshness``.

Returns a coarse, single-shot health summary of the personal-ETF daily
pipeline for ``expected_trade_date`` (defaulting to the latest weekday)
so the front-end can show a single banner without fanning out to five
separate endpoints.

The router only handles query-parameter validation, dependency
injection and the FastAPI / Pydantic response mapping; the freshness
orchestration (the ``expected_trade_date`` defaulting, the
snapshot / published / empty fallback chain, the status-state-machine
reduction, the missing-count derivation and the ``SQLAlchemyError``
boundary) all live in
:class:`invest_api.application.data_freshness.DataFreshnessQueryService`
so this module stays free of raw SQL and direct storage dependencies.
The five possible statuses are returned as the same vocabulary the
service emits (``fresh``, ``partial``, ``stale``, ``missing``,
``failed``); any :class:`invest_api.application.data_freshness.DataFreshnessQueryError`
raised by the service is converted into a sanitized HTTP 500 with the
same ``Data freshness query failed`` detail the previous router did.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from invest_api.application.data_freshness import (
    DataFreshnessQueryError,
    DataFreshnessQueryService,
    latest_weekday,
)
from invest_api.dependencies import get_data_freshness_query_service
from invest_api.schemas.data_freshness import DataFreshnessResponse

router = APIRouter(prefix="/api/v1/data-freshness", tags=["data-freshness"])

_ERROR_DETAIL: str = "Data freshness query failed"


def _to_response(view, *, as_of: datetime) -> DataFreshnessResponse:
    """Translate a :class:`DataFreshnessView` into the public response shape.

    ``as_of`` is intentionally stamped here rather than by the service so
    two callers hitting the service in the same instant still observe
    the wall-clock time at which *their* response was materialised.
    """

    return DataFreshnessResponse(
        as_of=as_of,
        latest_published_trade_date=view.latest_published_trade_date,
        universe_count=view.universe_count,
        daily_bar_count=view.daily_bar_count,
        missing_count=view.missing_count,
        candidate_count=view.candidate_count,
        snapshot_id=view.snapshot_id,
        pipeline_run_id=view.pipeline_run_id,
        pipeline_status=view.pipeline_status,
        status=view.status,
    )


@router.get("", response_model=DataFreshnessResponse)
def get_data_freshness(
    service: Annotated[
        DataFreshnessQueryService, Depends(get_data_freshness_query_service)
    ],
    expected_trade_date: Annotated[date | None, Query()] = None,
) -> DataFreshnessResponse:
    """Return the data-freshness summary for ``expected_trade_date``.

    The application service applies the ``expected_trade_date`` default
    (latest weekday from :func:`invest_api.clock.market_today`), runs
    the snapshot / published / empty fallback chain and the
    status-state-machine reduction, and packages the outcome into a
    small :class:`DataFreshnessView` dataclass. The router only maps
    that view onto the public Pydantic response shape and converts
    :class:`DataFreshnessQueryError` into a sanitized HTTP 500.
    """

    try:
        view = service.get_freshness(expected_trade_date)
    except DataFreshnessQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_ERROR_DETAIL,
        ) from exc
    return _to_response(view, as_of=datetime.now(UTC))


__all__ = ["latest_weekday", "router"]
