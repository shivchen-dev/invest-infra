"""Read-only data-freshness endpoint ``GET /api/v1/data-freshness``.

Returns a coarse, single-shot health summary of the personal-ETF daily
pipeline for ``expected_trade_date`` (defaulting to the latest weekday)
so the front-end can show a single banner without fanning out to five
separate endpoints. The handler issues raw ``text()`` queries against
the existing tables (``core.instruments``,
``analytics.candidate_pool_runs``, ``analytics.candidate_pool_items``,
``core.daily_bars``, ``analytics.input_snapshots``,
``ops.pipeline_runs``) and reduces the results to one of five statuses
defined in :class:`DataFreshnessResponse`.

The five statuses are mutually exclusive and evaluated in this order:

1. ``failed``  - latest ``personal_etf_daily_job`` run for
   ``expected_trade_date`` finished with ``status = 'failed'`` AND
   no candidate-pool run was published for ``expected_trade_date``.
2. ``missing`` - no candidate-pool run was ever published.
3. ``stale``   - the latest published candidate-pool run is for a
   trade_date strictly before ``expected_trade_date``.
4. ``partial`` - the latest published candidate-pool run matches
   ``expected_trade_date`` but ``daily_bar_count < universe_count``.
5. ``fresh``   - the latest published candidate-pool run matches
   ``expected_trade_date`` and ``daily_bar_count >= universe_count``.

Any :class:`sqlalchemy.exc.SQLAlchemyError` raised by the underlying
queries is caught and re-raised as an HTTP 500 with a sanitized detail
string so the original error message (which can include connection
strings or driver internals) never leaks to the client.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from invest_api.dependencies import get_db_session
from invest_api.schemas.data_freshness import DataFreshnessResponse

router = APIRouter(prefix="/api/v1/data-freshness", tags=["data-freshness"])

_JOB_KEY: str = "personal_etf_daily_job"
_ERROR_DETAIL: str = "Data freshness query failed"


def latest_weekday(reference: date) -> date:
    """Return ``reference`` snapped back to the most recent weekday.

    Saturday and Sunday collapse to the preceding Friday; Monday
    through Friday pass through unchanged. Exposed at module level so
    tests can drive the helper directly without an HTTP round-trip.
    """

    if reference.weekday() == 5:
        return reference - timedelta(days=1)
    if reference.weekday() == 6:
        return reference - timedelta(days=2)
    return reference


def _compute_status(
    *,
    latest_published_date: date | None,
    expected: date,
    daily_bar_count: int,
    universe_count: int,
    pipeline_status: str | None,
) -> str:
    if pipeline_status == "failed" and latest_published_date != expected:
        return "failed"
    if latest_published_date is None:
        return "missing"
    if latest_published_date < expected:
        return "stale"
    if daily_bar_count < universe_count:
        return "partial"
    return "fresh"


@router.get("", response_model=DataFreshnessResponse)
def get_data_freshness(
    session: Annotated[Session, Depends(get_db_session)],
    expected_trade_date: Annotated[date | None, Query()] = None,
) -> DataFreshnessResponse:
    """Return the data-freshness summary for ``expected_trade_date``."""

    expected = expected_trade_date or latest_weekday(date.today())
    as_of = datetime.now(UTC)

    try:
        universe_count = int(
            session.execute(
                text("SELECT count(*) FROM core.instruments WHERE is_active = true")
            ).scalar_one()
        )

        published_row = session.execute(
            text(
                """
                SELECT id, trade_date, input_snapshot_id
                FROM analytics.candidate_pool_runs
                WHERE status = 'published'
                ORDER BY trade_date DESC, created_at DESC
                LIMIT 1
                """
            )
        ).first()

        latest_published_date: date | None = None
        candidate_count = 0
        if published_row is not None:
            latest_published_date = published_row[1]
            candidate_count = int(
                session.execute(
                    text(
                        """
                        SELECT count(*) FROM analytics.candidate_pool_items
                        WHERE run_id = :run_id AND included = true
                        """
                    ),
                    {"run_id": published_row[0]},
                ).scalar_one()
            )

        daily_bar_count = int(
            session.execute(
                text(
                    """
                    SELECT count(DISTINCT instrument_id) FROM core.daily_bars
                    WHERE trade_date = :trade_date
                    """
                ),
                {"trade_date": expected},
            ).scalar_one()
        )

        snapshot_row = session.execute(
            text(
                """
                SELECT id FROM analytics.input_snapshots
                WHERE snapshot_date = :trade_date
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"trade_date": expected},
        ).first()
        snapshot_id: UUID | None = snapshot_row[0] if snapshot_row is not None else None

        pipeline_row = session.execute(
            text(
                """
                SELECT id, status FROM ops.pipeline_runs
                WHERE job_key = :job_key AND partition_key = :partition_key
                ORDER BY started_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                """
            ),
            {
                "job_key": _JOB_KEY,
                "partition_key": expected.isoformat(),
            },
        ).first()
        pipeline_run_id: UUID | None = pipeline_row[0] if pipeline_row is not None else None
        pipeline_status: str | None = pipeline_row[1] if pipeline_row is not None else None

        status_value = _compute_status(
            latest_published_date=latest_published_date,
            expected=expected,
            daily_bar_count=daily_bar_count,
            universe_count=universe_count,
            pipeline_status=pipeline_status,
        )

        return DataFreshnessResponse(
            as_of=as_of,
            latest_published_trade_date=latest_published_date,
            universe_count=universe_count,
            daily_bar_count=daily_bar_count,
            missing_count=max(0, universe_count - daily_bar_count),
            candidate_count=candidate_count,
            snapshot_id=snapshot_id,
            pipeline_run_id=pipeline_run_id,
            pipeline_status=pipeline_status,
            status=status_value,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_ERROR_DETAIL,
        ) from exc


__all__ = ["latest_weekday", "router"]
