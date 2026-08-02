"""Read-only pipeline-run endpoints under ``/api/v1/pipeline-runs``.

All endpoints are strictly scoped to ``job_key = "personal_etf_daily_job"``:
a lookup that resolves to a different ``job_key`` returns ``404`` so the
front-end cannot mistake a run from another job for the personal daily
job. The lookups go through
:class:`invest_storage.repositories.SqlAlchemyPipelineRunRepository`'s
read-side surface (``list_recent`` / ``list_by_job_key`` / ``get_by_id``); the
latest and ID lookups retain their existing behavior, while history uses the
job-key-scoped pagination and count methods.

PR-02 adds ``GET /api/v1/pipeline-runs`` for paginated history. The
handler bounds ``limit`` to ``1..100`` and ``offset`` to ``>= 0`` (a
value outside the range returns ``422`` from FastAPI's validation)
before delegating to the repository's SQL-filtered page and exact count.
Any :class:`sqlalchemy.exc.SQLAlchemyError` raised by the underlying
queries is caught and re-raised as an HTTP 500 with a sanitized detail
string.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from invest_storage.repositories import SqlAlchemyPipelineRunRepository
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from invest_api.dependencies import get_db_session
from invest_api.schemas.pipeline_runs import (
    PipelineRunListResponse,
    PipelineRunResponse,
)

router = APIRouter(prefix="/api/v1/pipeline-runs", tags=["pipeline-runs"])

_JOB_KEY: str = "personal_etf_daily_job"
_LATEST_LIMIT: int = 100
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
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[
        int,
        Query(ge=1, le=_LIST_MAX_LIMIT),
    ] = _LIST_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PipelineRunListResponse:
    """Return a paginated history of ``personal_etf_daily_job`` runs.

    The repository applies the ``job_key`` filter, limit and offset in SQL,
    and its dedicated count query supplies the exact total. ``SQLAlchemyError``
    is caught and re-raised as a sanitized HTTP 500 so a connection string or
    driver detail never leaks to the client.
    """

    repository = SqlAlchemyPipelineRunRepository(session)
    try:
        page = repository.list_by_job_key(
            _JOB_KEY, limit=limit, offset=offset
        )
        total = repository.count_by_job_key(_JOB_KEY)
    except SQLAlchemyError as exc:
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
    session: Annotated[Session, Depends(get_db_session)],
) -> PipelineRunResponse:
    """Return the most recent run of the personal daily job.

    Walks :meth:`SqlAlchemyPipelineRunRepository.list_recent` - which is
    ordered by ``started_at`` descending - and returns the first run
    matching ``job_key = "personal_etf_daily_job"``. Returns ``404`` when
    no matching run exists; any run that resolves to a different job_key
    is intentionally ignored.
    """

    repository = SqlAlchemyPipelineRunRepository(session)
    recent = repository.list_recent(limit=_LATEST_LIMIT, offset=0)
    for run in recent:
        if run.job_key == _JOB_KEY:
            return _to_response(run)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"no pipeline run found for job_key {_JOB_KEY!r}",
    )


@router.get("/{run_id}", response_model=PipelineRunResponse)
def get_pipeline_run_by_id(
    session: Annotated[Session, Depends(get_db_session)],
    run_id: Annotated[UUID, Path()],
) -> PipelineRunResponse:
    """Return the run for ``run_id`` if it belongs to the personal daily job.

    A missing run OR a run that resolves to a different ``job_key`` both
    surface as ``404``; the front-end cannot distinguish between "the
    UUID does not exist" and "the UUID belongs to a different job", which
    matches the contract spelled out in PR-03 §3.2.
    """

    repository = SqlAlchemyPipelineRunRepository(session)
    run = repository.get_by_id(run_id)
    if run is None or run.job_key != _JOB_KEY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"pipeline run {run_id} not found for job_key {_JOB_KEY!r}",
        )
    return _to_response(run)


__all__ = ["router"]