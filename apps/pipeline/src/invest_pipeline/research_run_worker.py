"""Worker boundary for executing queued ResearchRun records."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from invest_domain.research.research_run import ResearchRunStatus

from invest_pipeline.research_orchestration_service import (
    ResearchOrchestrationOutcome,
    ResearchOrchestrationService,
    UnitOfWorkFactory,
)

__all__ = ["ResearchRunWorker", "ResearchRunWorkerInputError"]


class ResearchRunWorkerInputError(ValueError):
    """Raised when a requested worker item is absent or not queued."""


@dataclass(frozen=True, slots=True)
class ResearchRunWorker:
    """Consume queued runs without owning the JiuwenSwarm transport boundary."""

    uow_factory: UnitOfWorkFactory
    orchestration: ResearchOrchestrationService

    def run_once(self, run_id: UUID) -> ResearchOrchestrationOutcome:
        """Execute one queued run; lifecycle CAS remains in the orchestrator."""

        with self.uow_factory() as uow:
            run = uow.research_runs.get(run_id)
            if run is None:
                raise ResearchRunWorkerInputError(f"ResearchRun {run_id!s} not found")
            if run.status is not ResearchRunStatus.QUEUED:
                raise ResearchRunWorkerInputError(
                    f"ResearchRun {run_id!s} is not queued: {run.status.value!r}"
                )
            uow.commit()
        return self.orchestration.execute(run_id)

    def run_next(self, *, limit: int = 50) -> ResearchOrchestrationOutcome | None:
        """Find the oldest queued run and execute it, if one is available."""

        if limit < 1:
            raise ValueError("limit must be >= 1")
        with self.uow_factory() as uow:
            candidates = [
                run
                for run in uow.research_runs.list_recent(limit=limit, offset=0)
                if run.status is ResearchRunStatus.QUEUED
            ]
            if not candidates:
                uow.commit()
                return None
            run_id = candidates[0].run_id
            uow.commit()
        return self.run_once(run_id)
