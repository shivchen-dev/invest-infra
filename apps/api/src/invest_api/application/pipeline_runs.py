"""Application service for the read-only ``/api/v1/pipeline-runs`` slice.

The service owns three read-side use cases the FastAPI router exposes:

* paginated history scoped to a fixed ``job_key``
  (:data:`JOB_KEY`),
* the most recent run for the same fixed ``job_key``,
* a by-id lookup that is scoped to the same fixed ``job_key``.

The router delegates the orchestration - session handling, repository
construction, job-key selection, latest-row scanning, the
:class:`sqlalchemy.exc.SQLAlchemyError` boundary - to this service so
the HTTP layer only translates domain objects into Pydantic response
shapes and converts the application exception into an HTTP error.

The repository is taken as a :class:`PipelineRunReader` Protocol so
the service depends only on the narrow read-side surface it actually
uses; the dependency factory in :mod:`invest_api.dependencies`
instantiates the concrete
:class:`invest_storage.repositories.SqlAlchemyPipelineRunRepository`
and passes it in. There is intentionally no generic service framework
here: the application layer is a thin domain-use-case wrapper, not an
abstraction over FastAPI or SQLAlchemy.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from invest_domain.pipeline import PipelineRun
from sqlalchemy.exc import SQLAlchemyError

JOB_KEY: str = "personal_etf_daily_job"
"""Fixed ``job_key`` every public pipeline-run read use case is scoped to.

The front-end cannot distinguish "the UUID does not exist" from "the
UUID belongs to a different job" - both surface as ``404`` - so the
personal daily job never leaks runs from unrelated jobs.
"""

LATEST_LOOKBACK_LIMIT: int = 100
"""Maximum number of recent runs the latest-selection use case scans.

The repository's :meth:`list_recent` returns runs ordered by
``started_at`` descending; we walk the page until we find a matching
job_key, so the bound only needs to cover the realistic gap between
the newest unrelated run and the newest personal daily run.
"""


class PipelineRunReader(Protocol):
    """Narrow read-side surface of the pipeline-run repository.

    Defined as a :class:`typing.Protocol` so the application layer
    stays decoupled from the concrete storage class. The dependency
    factory in :mod:`invest_api.dependencies` injects
    :class:`invest_storage.repositories.SqlAlchemyPipelineRunRepository`,
    which satisfies this surface.
    """

    def get_by_id(self, run_id: UUID) -> PipelineRun | None:
        """Return the run for ``run_id`` or ``None`` if absent."""
        ...

    def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[PipelineRun]:
        """Return runs ordered by ``started_at`` descending."""
        ...

    def list_by_job_key(
        self, job_key: str, *, limit: int = 50, offset: int = 0
    ) -> list[PipelineRun]:
        """Return one job's runs ordered by ``started_at`` descending."""
        ...

    def count_by_job_key(self, job_key: str) -> int:
        """Return the number of runs for ``job_key``."""
        ...


class PipelineRunQueryError(RuntimeError):
    """Raised when the pipeline-run repository raises :class:`SQLAlchemyError`.

    The HTTP layer converts this into a sanitized 500 response; the
    original driver-level exception is intentionally swallowed so the
    router never leaks a connection string or driver detail to the
    client.
    """


class PipelineRunQueryService:
    """Application service for the read-only ``/api/v1/pipeline-runs`` use cases.

    The service is intentionally small: it owns the fixed :data:`JOB_KEY`
    scope, the pagination argument plumbing, the latest-row selection
    scan, the by-id job-key scoping, and the
    :class:`SQLAlchemyError` -> :class:`PipelineRunQueryError`
    translation. Domain-to-response mapping stays in the router so the
    application layer remains free of FastAPI / Pydantic imports.
    """

    def __init__(self, repository: PipelineRunReader) -> None:
        self._repository = repository

    def list_runs(self, *, limit: int, offset: int) -> tuple[list[PipelineRun], int]:
        """Return ``(page, total)`` for the fixed :data:`JOB_KEY` history.

        Delegates the job-key filter, limit and offset to the
        repository's SQL-side surface so pagination stays in SQL; the
        companion count query supplies the exact unbounded total.
        :class:`SQLAlchemyError` is caught and re-raised as
        :class:`PipelineRunQueryError` so the HTTP layer can render a
        sanitized 500.
        """

        try:
            page = self._repository.list_by_job_key(JOB_KEY, limit=limit, offset=offset)
            total = self._repository.count_by_job_key(JOB_KEY)
        except SQLAlchemyError as exc:
            raise PipelineRunQueryError("pipeline run query failed") from exc
        return page, total

    def get_latest_run(self) -> PipelineRun | None:
        """Return the most recent run matching :data:`JOB_KEY`, or ``None``.

        Walks the repository's :meth:`list_recent` (ordered by
        ``started_at`` descending) and returns the first row whose
        ``job_key`` matches :data:`JOB_KEY`. Returns ``None`` when no
        such run exists or the page only contains runs from other jobs;
        :class:`SQLAlchemyError` is translated to
        :class:`PipelineRunQueryError`.
        """

        try:
            recent = self._repository.list_recent(
                limit=LATEST_LOOKBACK_LIMIT, offset=0
            )
        except SQLAlchemyError as exc:
            raise PipelineRunQueryError("pipeline run query failed") from exc
        for run in recent:
            if run.job_key == JOB_KEY:
                return run
        return None

    def get_run_for_job(self, run_id: UUID) -> PipelineRun | None:
        """Return the run for ``run_id`` only when it matches :data:`JOB_KEY`.

        Returns ``None`` when the run is missing or belongs to a
        different ``job_key`` so the router can surface a single
        indistinguishable 404 message. :class:`SQLAlchemyError` is
        translated to :class:`PipelineRunQueryError`.
        """

        try:
            run = self._repository.get_by_id(run_id)
        except SQLAlchemyError as exc:
            raise PipelineRunQueryError("pipeline run query failed") from exc
        if run is None or run.job_key != JOB_KEY:
            return None
        return run


__all__ = [
    "JOB_KEY",
    "LATEST_LOOKBACK_LIMIT",
    "PipelineRunQueryError",
    "PipelineRunQueryService",
    "PipelineRunReader",
]