"""Read-only pipeline-run endpoints under ``/api/v1/pipeline-runs``.

Both endpoints are strictly scoped to ``job_key = "personal_etf_daily_job"``:
a lookup that resolves to a different ``job_key`` returns ``404`` so the
front-end cannot mistake a run from another job for the personal daily
job. The lookups go through
:class:`invest_storage.repositories.SqlAlchemyPipelineRunRepository`'s
read-side surface (``list_recent`` / ``get_by_id``) and the per-run
``job_key`` filter is applied in the handler - the storage repository
intentionally stays job-agnostic so it can serve future jobs without an
API-driven change.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status
from invest_storage.repositories import SqlAlchemyPipelineRunRepository
from sqlalchemy.orm import Session

from invest_api.dependencies import get_db_session
from invest_api.schemas.pipeline_runs import PipelineRunResponse

router = APIRouter(prefix="/api/v1/pipeline-runs", tags=["pipeline-runs"])

_JOB_KEY: str = "personal_etf_daily_job"
_LATEST_LIMIT: int = 100


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