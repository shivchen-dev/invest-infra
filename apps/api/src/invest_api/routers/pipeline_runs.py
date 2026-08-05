"""Read-only pipeline-run endpoints under ``/api/v1/pipeline-runs``.

All endpoints are strictly scoped to ``job_key = "personal_etf_daily_job"``:
a lookup that resolves to a different ``job_key`` returns ``404`` so the
front-end cannot mistake a run from another job for the personal daily
job.

PR-02 adds ``GET /api/v1/pipeline-runs`` for paginated history. The
handler bounds ``limit`` to ``1..100`` and ``offset`` to ``>= 0`` (a
value outside the range returns ``422`` from FastAPI's validation)
before delegating to
:class:`invest_api.application.pipeline_runs.PipelineRunQueryService`,
which owns the fixed job-key scope, the SQL-side pagination, the
latest-row scan, the by-id scoping and the
:class:`sqlalchemy.exc.SQLAlchemyError` translation. The router maps
the resulting domain objects into the public response shape; any
:class:`invest_api.application.pipeline_runs.PipelineRunQueryError`
raised by the service is converted into a sanitized HTTP 500 so a
connection string or driver detail never leaks to the client.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from invest_api.application.pipeline_runs import (
    JOB_KEY,
    PipelineRunQueryError,
    PipelineRunQueryService,
)
from invest_api.dependencies import get_pipeline_run_query_service
from invest_api.schemas.pipeline_runs import (
    PipelineRunListResponse,
    PipelineRunResponse,
)

router = APIRouter(prefix="/api/v1/pipeline-runs", tags=["pipeline-runs"])

_LIST_DEFAULT_LIMIT: int = 20
_LIST_MAX_LIMIT: int = 100
_LIST_ERROR_DETAIL: str = "Pipeline runs query failed"


def _to_response(run) -> PipelineRunResponse:
    """Translate a domain :class:`PipelineRun` into the public response shape."""

    return PipelineRunResponse(
        id=run.id,
        job_key=run.job_key,
        partition_key=run.partition_key,
        trigger_type=run.trigger_type,
        status=run.status_value,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_code=None,
        error_summary=run.error_summary,
    )


@router.get("", response_model=PipelineRunListResponse)
def list_pipeline_runs(
    service: Annotated[
        PipelineRunQueryService, Depends(get_pipeline_run_query_service)
    ],
    limit: Annotated[
        int,
        Query(ge=1, le=_LIST_MAX_LIMIT),
    ] = _LIST_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PipelineRunListResponse:
    """Return a paginated history of ``personal_etf_daily_job`` runs.

    The application service applies the ``job_key`` filter, limit and
    offset in SQL and supplies the exact total from its companion
    count query. ``PipelineRunQueryError`` (raised when the underlying
    repository raises ``SQLAlchemyError``) is caught and re-raised as a
    sanitized HTTP 500.
    """

    try:
        page, total = service.list_runs(limit=limit, offset=offset)
    except PipelineRunQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_LIST_ERROR_DETAIL,
        ) from exc

    return PipelineRunListResponse(
        items=[_to_response(run) for run in page],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/latest", response_model=PipelineRunResponse)
def get_latest_pipeline_run(
    service: Annotated[
        PipelineRunQueryService, Depends(get_pipeline_run_query_service)
    ],
) -> PipelineRunResponse:
    """Return the most recent run of the personal daily job.

    The application service walks the repository's ``list_recent``
    page - ordered by ``started_at`` descending - and returns the first
    run matching ``job_key = "personal_etf_daily_job"``. The router
    surfaces ``404`` when no matching run exists; any run that resolves
    to a different ``job_key`` is intentionally ignored.
    """

    run = service.get_latest_run()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no pipeline run found for job_key {JOB_KEY!r}",
        )
    return _to_response(run)


@router.get("/{run_id}", response_model=PipelineRunResponse)
def get_pipeline_run_by_id(
    service: Annotated[
        PipelineRunQueryService, Depends(get_pipeline_run_query_service)
    ],
    run_id: Annotated[UUID, Path()],
) -> PipelineRunResponse:
    """Return the run for ``run_id`` if it belongs to the personal daily job.

    A missing run OR a run that resolves to a different ``job_key`` both
    surface as ``404``; the front-end cannot distinguish between "the
    UUID does not exist" and "the UUID belongs to a different job".
    """

    run = service.get_run_for_job(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"pipeline run {run_id} not found for job_key {JOB_KEY!r}",
        )
    return _to_response(run)


__all__ = ["router"]