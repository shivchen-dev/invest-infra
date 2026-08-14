"""Read-side application service for Stage 4D external workflows."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID


class ExternalWorkflowRunReader(Protocol):
    def get_by_id(self, run_id: UUID): ...
    def list_recent(self, *, limit: int = 50, offset: int = 0): ...


class ExternalArtifactReader(Protocol):
    def get_by_id(self, artifact_id: UUID): ...
    def list_by_run(self, run_id: UUID, *, limit: int = 100, offset: int = 0): ...


class ExternalObservationReader(Protocol):
    def list_by_run(self, run_id: UUID, *, limit: int = 100, offset: int = 0): ...
    def list_recent(self, *, status=None, limit: int = 100, offset: int = 0): ...


class ExternalWorkflowQueryService:
    def __init__(
        self,
        *,
        run_repository: ExternalWorkflowRunReader,
        artifact_repository: ExternalArtifactReader,
        observation_repository: ExternalObservationReader,
    ) -> None:
        self._runs = run_repository
        self._artifacts = artifact_repository
        self._observations = observation_repository

    def list_runs(self, *, limit: int, offset: int) -> Sequence:
        return self._runs.list_recent(limit=limit, offset=offset)

    def get_run(self, run_id: UUID):
        return self._runs.get_by_id(run_id)

    def list_artifacts(self, run_id: UUID, *, limit: int, offset: int) -> Sequence:
        return self._artifacts.list_by_run(run_id, limit=limit, offset=offset)

    def list_observations(self, run_id: UUID, *, limit: int, offset: int) -> Sequence:
        return self._observations.list_by_run(run_id, limit=limit, offset=offset)

    def list_radar(self, *, status=None, limit: int, offset: int) -> Sequence:
        return self._observations.list_recent(status=status, limit=limit, offset=offset)

    def get_artifact(self, artifact_id: UUID):
        return self._artifacts.get_by_id(artifact_id)

    def health(self) -> dict:
        runs = self._runs.list_recent(limit=100, offset=0)
        producer_statuses: dict[str, int] = {}
        intake_statuses: dict[str, int] = {}
        for run in runs:
            producer = run.producer_status.value
            intake = run.intake_status.value
            producer_statuses[producer] = producer_statuses.get(producer, 0) + 1
            intake_statuses[intake] = intake_statuses.get(intake, 0) + 1
        return {
            "status": "healthy" if not producer_statuses.get("failed") else "degraded",
            "sample_size": len(runs),
            "producer_statuses": producer_statuses,
            "intake_statuses": intake_statuses,
            "latest_run_id": runs[0].run_id if runs else None,
        }


__all__ = ["ExternalWorkflowQueryService"]
