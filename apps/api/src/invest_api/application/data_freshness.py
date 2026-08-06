"""Application service for the read-only ``/api/v1/data-freshness`` slice.

The service owns the freshness orchestration the FastAPI router exposes
as a single GET endpoint: it materialises the ``expected_trade_date``
(defaulting to the most recent weekday from the market clock), issues
the four raw-text SQL reads against ``analytics.input_snapshots`` /
``analytics.candidate_pool_runs`` / ``analytics.candidate_pool_items`` /
``core.daily_bars`` and the one read against ``ops.pipeline_runs``,
reduces the results to one of the five :class:`DataFreshnessStatus`
values, and packages the outcome into a small :class:`DataFreshnessView`
dataclass the router can map onto the public Pydantic response shape.

The repository is taken as a narrow :class:`DataFreshnessReader`
:class:`typing.Protocol` so the service depends only on the read-side
surface it actually uses; the dependency factory in
:mod:`invest_api.dependencies` instantiates the concrete
:class:`SqlAlchemyDataFreshnessReader` (which executes the same raw
``text()`` queries the previous router did) against the FastAPI-provided
session and passes it in.

``SQLAlchemyError`` from the reader is translated to
:class:`DataFreshnessQueryError` so the HTTP layer can render a
sanitized 500; the original driver-level exception is intentionally
swallowed so a connection string or driver detail never leaks to the
client. There is intentionally no generic service framework here: the
application layer is a thin domain-use-case wrapper, not an abstraction
over FastAPI or SQLAlchemy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from invest_api import clock as market_clock

JOB_KEY: str = "personal_etf_daily_job"
"""Fixed ``job_key`` the pipeline-run probe is scoped to.

The front-end only ever cares about the personal daily job, so the
service narrows the ``ops.pipeline_runs`` lookup to the same
``job_key`` the rest of the personal-universe use cases are scoped
to; this matches the previous router behaviour byte-for-byte.
"""

_QUERY_ERROR_DETAIL: str = "Data freshness query failed"
"""Exact 500 detail the router surfaces for :class:`DataFreshnessQueryError`.

Kept as a module constant so the router and any future caller can
sanitise the response without re-deriving the string.
"""


class InputSnapshotRow(Protocol):
    """Attribute-level read-side shape of an ``analytics.input_snapshots`` row.

    Captures the three columns the freshness probe touches:
    ``id`` is the snapshot UUID; ``instrument_ids`` is the JSON-shaped
    list of personal-pool members (passed straight back to PostgreSQL
    through the ``uuid[]`` cast); ``row_count`` is the snapshot's own
    ``row_count`` and is the "personal universe" denominator in the
    freshness accounting. Declared as an attribute Protocol so the
    storage-side dataclass returned by the concrete reader
    structurally conforms without forcing the storage layer to import
    a type from the application layer.
    """

    id: UUID
    instrument_ids: tuple[str, ...]
    row_count: int


class PublishedCandidatePoolRunRow(Protocol):
    """Attribute-level read-side shape of a ``PUBLISHED`` candidate-pool run row.

    ``id`` is the run UUID the candidate-item count and (in the
    fallback path) the daily-bar count are keyed off;
    ``trade_date`` is the most recent weekday for which a published
    run exists; ``input_row_count`` is the personal-universe
    denominator used when no input snapshot exists for the expected
    trade date.
    """

    id: UUID
    trade_date: date
    input_row_count: int


class PipelineRunRow(Protocol):
    """Attribute-level read-side shape of an ``ops.pipeline_runs`` probe row.

    ``id`` is the pipeline run UUID surfaced to the client so the
    front-end can link out to the run detail view; ``status`` is the
    textual pipeline-run status used by the freshness state machine
    (``"failed"`` short-circuits the "missing published run" branch).
    """

    id: UUID
    status: str | None


class DataFreshnessReader(Protocol):
    """Narrow read-side surface the freshness service depends on.

    Each method corresponds to one of the raw ``text()`` queries the
    previous router issued. ``count_included_items_for_run`` and the
    two ``count_daily_bars_*`` queries return a single integer; the
    other three return either the populated row or ``None`` so the
    caller can distinguish between "no row" and "row with null
    columns".

    Returned row types are declared as attribute-level Protocols so
    the storage-side dataclass returned by the concrete reader
    structurally conforms without forcing the storage layer to import
    a type from the application layer.
    """

    def get_snapshot_for_trade_date(
        self, trade_date: date
    ) -> InputSnapshotRow | None:
        """Return the most recent snapshot for ``trade_date`` or ``None``."""

    def get_latest_published_candidate_pool_run(
        self,
    ) -> PublishedCandidatePoolRunRow | None:
        """Return the most recent ``PUBLISHED`` candidate-pool run or ``None``."""

    def count_included_items_for_run(self, run_id: UUID) -> int:
        """Return the number of ``included = true`` items for ``run_id``."""

    def count_daily_bars_for_snapshot(
        self, trade_date: date, instrument_ids: tuple[str, ...]
    ) -> int:
        """Return the distinct ``daily_bars.instrument_id`` count for the snapshot."""

    def count_daily_bars_for_published_run(
        self, trade_date: date, run_id: UUID
    ) -> int:
        """Return the distinct daily-bar count scoped to the published run's items."""

    def get_latest_pipeline_run_for_partition(
        self, *, job_key: str, partition_key: str
    ) -> PipelineRunRow | None:
        """Return the latest pipeline run for ``(job_key, partition_key)`` or ``None``."""


def latest_weekday(reference: date) -> date:
    """Return ``reference`` snapped back to the most recent weekday.

    Saturday and Sunday collapse to the preceding Friday; Monday
    through Friday pass through unchanged. Lives in the application
    layer because the default-date fallback is part of the freshness
    orchestration, not a transport concern; exposed at module level so
    any caller (and the existing tests) can drive the helper directly
    without an HTTP round-trip.
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


@dataclass(frozen=True, slots=True)
class DataFreshnessView:
    """Small domain view backing :class:`invest_api.schemas.DataFreshnessResponse`.

    Carries every domain-shaped field the router maps onto the public
    Pydantic response. ``as_of`` is intentionally absent from the view
    because it is a presentation-layer concern (UTC wall clock at the
    moment the HTTP response is materialised); the router stamps it
    when it builds the response so two callers hitting the service in
    the same instant observe the same ``expected_trade_date`` but
    still get their own response timestamp.
    """

    expected_trade_date: date
    latest_published_trade_date: date | None
    universe_count: int
    daily_bar_count: int
    missing_count: int
    candidate_count: int
    snapshot_id: UUID | None
    pipeline_run_id: UUID | None
    pipeline_status: str | None
    status: str


class DataFreshnessQueryError(RuntimeError):
    """Raised when the freshness reader raises :class:`SQLAlchemyError`.

    The HTTP layer converts this into a sanitized 500 response; the
    original driver-level exception is intentionally swallowed so the
    router never leaks a connection string or driver detail to the
    client.
    """


class DataFreshnessQueryService:
    """Application service for the read-only ``/api/v1/data-freshness`` use case.

    The service owns the ``expected_trade_date`` default (latest
    weekday from the market clock), the snapshot-first /
    published-fallback / empty universe chain (PR-02), the
    status-state-machine reduction, the missing-count derivation and
    the :class:`SQLAlchemyError` -> :class:`DataFreshnessQueryError`
    translation. Domain-to-response mapping stays in the router so the
    application layer remains free of FastAPI / Pydantic imports.
    """

    def __init__(self, reader: DataFreshnessReader) -> None:
        self._reader = reader

    def get_freshness(
        self, expected_trade_date: date | None
    ) -> DataFreshnessView:
        """Return the freshness view for ``expected_trade_date``.

        ``expected_trade_date`` defaults to the latest weekday from
        :func:`invest_api.clock.market_today` so callers that omit the
        query parameter observe the same Shanghai-local default the
        previous router did. ``SQLAlchemyError`` from any reader call
        is translated to :class:`DataFreshnessQueryError`; every
        candidate-pool / daily-bar / pipeline probe is sequenced so
        the error boundary covers the whole orchestration rather than
        only one branch.
        """

        expected = expected_trade_date or latest_weekday(
            market_clock.market_today()
        )

        try:
            return self._build_view(expected)
        except SQLAlchemyError as exc:
            raise DataFreshnessQueryError(_QUERY_ERROR_DETAIL) from exc

    def _build_view(self, expected: date) -> DataFreshnessView:
        snapshot = self._reader.get_snapshot_for_trade_date(expected)
        published_row = self._reader.get_latest_published_candidate_pool_run()

        latest_published_date: date | None = None
        candidate_count = 0
        universe_count = 0
        snapshot_id: UUID | None = None

        if snapshot is not None:
            snapshot_id = snapshot.id
            universe_count = snapshot.row_count
            daily_bar_count = self._reader.count_daily_bars_for_snapshot(
                expected, snapshot.instrument_ids
            )
        elif published_row is not None:
            universe_count = int(published_row.input_row_count)
            daily_bar_count = self._reader.count_daily_bars_for_published_run(
                expected, published_row.id
            )
        else:
            daily_bar_count = 0

        if published_row is not None:
            latest_published_date = published_row.trade_date
            candidate_count = self._reader.count_included_items_for_run(
                published_row.id
            )

        missing_count = max(0, universe_count - daily_bar_count)

        pipeline_row = self._reader.get_latest_pipeline_run_for_partition(
            job_key=JOB_KEY,
            partition_key=expected.isoformat(),
        )
        pipeline_run_id: UUID | None = (
            pipeline_row.id if pipeline_row is not None else None
        )
        pipeline_status: str | None = (
            pipeline_row.status if pipeline_row is not None else None
        )

        status_value = _compute_status(
            latest_published_date=latest_published_date,
            expected=expected,
            daily_bar_count=daily_bar_count,
            universe_count=universe_count,
            pipeline_status=pipeline_status,
        )

        return DataFreshnessView(
            expected_trade_date=expected,
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


__all__ = [
    "DataFreshnessQueryError",
    "DataFreshnessQueryService",
    "DataFreshnessReader",
    "DataFreshnessView",
    "InputSnapshotRow",
    "JOB_KEY",
    "PipelineRunRow",
    "PublishedCandidatePoolRunRow",
    "latest_weekday",
]
