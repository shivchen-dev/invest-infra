"""Pydantic response schemas for the ``/api/v1/pipeline-runs`` read-only endpoints.

PR-03 exposes a minimal, read-only surface over the ``ops.pipeline_runs``
table. The endpoints are intentionally scoped to ``job_key =
"personal_etf_daily_job"`` so the front-end can render the personal
daily-job status without leaking unrelated runs from other jobs.

``error_code`` is part of the response contract but is always ``None`` in
PR-03: the storage layer does not yet persist a separate error code for
``ops.pipeline_runs``; the structured error field lands in a later PR.
``error_summary`` continues to carry the human-readable failure
description produced by :class:`SqlAlchemyPipelineRunRepository.mark_failed`.

PR-02 adds :class:`PipelineRunListResponse` to expose the chronological
history of the personal daily job through ``GET /api/v1/pipeline-runs``.
The envelope mirrors the other paginated responses in the API
(``items``, ``total``, ``limit``, ``offset``); ``total`` is the count of
``personal_etf_daily_job`` runs regardless of the page bounds so the
front-end can compute the full page count deterministically.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PipelineRunResponse(BaseModel):
    """Public representation of one ``ops.pipeline_runs`` row.

    Mirrors the storage/domain :class:`invest_domain.pipeline.PipelineRun`
    fields that PR-03 needs on the read path; storage-internal handles
    (``dagster_run_id``, ``algorithm_version``, ``config_snapshot``,
    ``created_at``, ``updated_at``) are deliberately omitted.
    """

    id: UUID
    job_key: str
    partition_key: str | None = None
    trigger_type: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_summary: str | None = None


class PipelineRunListResponse(BaseModel):
    """Paginated envelope for the ``GET /api/v1/pipeline-runs`` endpoint.

    ``total`` counts every ``personal_etf_daily_job`` run (i.e. it is
    computed independently of ``limit`` / ``offset``) so the UI can
    render the page count without an extra round trip. ``items`` is
    always ordered by ``started_at`` descending and then ``id``
    ascending so successive pages are stable.
    """

    items: list[PipelineRunResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


__all__ = ["PipelineRunListResponse", "PipelineRunResponse"]