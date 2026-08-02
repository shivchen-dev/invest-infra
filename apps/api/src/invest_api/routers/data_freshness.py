"""Read-only data-freshness endpoint ``GET /api/v1/data-freshness``.

Returns a coarse, single-shot health summary of the personal-ETF daily
pipeline for ``expected_trade_date`` (defaulting to the latest weekday)
so the front-end can show a single banner without fanning out to five
separate endpoints. The handler issues raw ``text()`` queries against
the existing tables (``analytics.input_snapshots``,
``analytics.candidate_pool_runs``, ``analytics.candidate_pool_items``,
``core.daily_bars``, ``ops.pipeline_runs``) and reduces the results to
one of five statuses defined in :class:`DataFreshnessResponse`.

PR-02 tightens the personal-universe accounting so the handler never
blends market-wide ETFs into the personal pool:

- ``universe_count`` is sourced from the input snapshot
  (``analytics.input_snapshots.row_count``) for the expected date when
  one exists; if no snapshot exists for the expected date the handler
  falls back to ``input_row_count`` of the most recently
  ``published`` ``analytics.candidate_pool_runs`` row; with no
  published row either the universe is ``0``.
- ``daily_bar_count`` and ``missing_count`` are scoped to the input
  snapshot's ``instrument_ids`` when available so a half-empty market
  day does not inflate the personal missing-count. The fallback path
  uses the published run's ``analytics.candidate_pool_items`` membership
  so the count still reflects the personal universe rather than every
  ETF in ``core.daily_bars``.

The five statuses are mutually exclusive and evaluated in this order:

1. ``failed``  - latest ``personal_etf_daily_job`` run for
   ``expected_trade_date`` finished with ``status = 'failed'`` AND
   no candidate-pool run was published for ``expected_trade_date``.
2. ``missing`` - no candidate-pool run was ever published.
3. ``stale``   - the latest published candidate-pool run is for a
   trade_date strictly before ``expected_trade_date``.
4. ``partial`` - the latest published candidate-pool run matches
   ``expected_trade_date`` and ``daily_bar_count < universe_count``
   (only meaningful when a snapshot scoped the universe).
5. ``fresh``   - the latest published candidate-pool run matches
   ``expected_trade_date`` and ``daily_bar_count >= universe_count``.

Any :class:`sqlalchemy.exc.SQLAlchemyError` raised by the underlying
queries is caught and re-raised as an HTTP 500 with a sanitized detail
string so the original error message (which can include connection
strings or driver internals) never leaks to the client.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
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


def _snapshot_row(
    session: Session, expected: date
) -> tuple[UUID, list[str], int] | None:
    """Return ``(id, instrument_ids, row_count)`` for the expected date.

    The most recently created snapshot wins; when ``created_at`` ties,
    the larger ``id`` wins deterministically so a same-day rerun never
    returns a stale row. The handler ignores snapshots for other trade
    dates so the personal universe never leaks across days.
    """

    row = session.execute(
        text(
            """
            SELECT id, instrument_ids, row_count
            FROM analytics.input_snapshots
            WHERE snapshot_date = :trade_date
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ),
        {"trade_date": expected},
    ).first()
    if row is None:
        return None
    raw_ids = row[1]
    instrument_ids: list[str] = (
        list(raw_ids) if isinstance(raw_ids, (list, tuple)) else []
    )
    return row[0], instrument_ids, int(row[2])


def _published_row(session: Session) -> tuple[Any, ...] | None:
    """Return the latest ``published`` candidate-pool run row.

    ``analytics.candidate_pool_runs`` is ordered by ``trade_date``
    descending and then ``created_at`` descending so a later same-day
    rerun supersedes the earlier one; the handler ignores rows that
    have not been published yet.
    """

    return session.execute(
        text(
            """
            SELECT id, trade_date, input_row_count
            FROM analytics.candidate_pool_runs
            WHERE status = 'published'
            ORDER BY trade_date DESC, created_at DESC
            LIMIT 1
            """
        )
    ).first()


def _candidate_count(session: Session, run_id: UUID) -> int:
    """Return the number of ``included = true`` items for ``run_id``."""

    return int(
        session.execute(
            text(
                """
                SELECT count(*) FROM analytics.candidate_pool_items
                WHERE run_id = :run_id AND included = true
                """
            ),
            {"run_id": run_id},
        ).scalar_one()
    )


def _daily_bar_count_snapshot(
    session: Session, expected: date, instrument_ids: list[str]
) -> int:
    """Return the distinct ``daily_bars.instrument_id`` count.

    Scoped to ``instrument_ids`` (the personal snapshot's membership)
    so the count reflects only the personal pool rather than every ETF
    present in ``core.daily_bars``. ``instrument_id`` is a ``uuid`` and
    ``analytics.input_snapshots.instrument_ids`` is a JSONB array of
    strings, so the array is cast to ``uuid[]`` before the ``ANY``
    comparison to keep PostgreSQL happy.
    """

    if not instrument_ids:
        return 0
    return int(
        session.execute(
            text(
                """
                SELECT count(DISTINCT instrument_id) FROM core.daily_bars
                WHERE trade_date = :trade_date
                  AND instrument_id = ANY(CAST(:ids AS uuid[]))
                """
            ),
            {"trade_date": expected, "ids": instrument_ids},
        ).scalar_one()
    )


def _daily_bar_count_published(
    session: Session, expected: date, run_id: UUID
) -> int:
    """Return distinct daily bars for the published run's personal pool.

    The membership comes from ``analytics.candidate_pool_items`` for the
    most recently published run so the count remains scoped to the
    personal universe even when no same-day snapshot exists. The
    ``IN`` sub-select avoids depending on the snapshot's JSONB shape.
    """

    return int(
        session.execute(
            text(
                """
                SELECT count(DISTINCT db.instrument_id)
                FROM core.daily_bars db
                WHERE db.trade_date = :trade_date
                  AND db.instrument_id IN (
                      SELECT instrument_id
                      FROM analytics.candidate_pool_items
                      WHERE run_id = :run_id
                  )
                """
            ),
            {"trade_date": expected, "run_id": run_id},
        ).scalar_one()
    )


@router.get("", response_model=DataFreshnessResponse)
def get_data_freshness(
    session: Annotated[Session, Depends(get_db_session)],
    expected_trade_date: Annotated[date | None, Query()] = None,
) -> DataFreshnessResponse:
    """Return the data-freshness summary for ``expected_trade_date``."""

    expected = expected_trade_date or latest_weekday(date.today())
    as_of = datetime.now(UTC)

    try:
        snapshot = _snapshot_row(session, expected)
        published_row = _published_row(session)

        latest_published_date: date | None = None
        candidate_count = 0
        universe_count = 0
        snapshot_id: UUID | None = None

        if snapshot is not None:
            snapshot_id, snapshot_ids, universe_count = snapshot
            daily_bar_count = _daily_bar_count_snapshot(
                session, expected, snapshot_ids
            )
        elif published_row is not None:
            universe_count = int(published_row[2])
            daily_bar_count = _daily_bar_count_published(
                session, expected, published_row[0]
            )
        else:
            daily_bar_count = 0

        if published_row is not None:
            latest_published_date = published_row[1]
            candidate_count = _candidate_count(session, published_row[0])

        missing_count = max(0, universe_count - daily_bar_count)

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
            missing_count=missing_count,
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