"""Read-side application service for Stage 4D external workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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

    def get_candidate_lineage(self, run_id: UUID):
        run = self._runs.get_by_id(run_id)
        if run is None:
            return None
        metadata = getattr(run, "metadata", None)
        return project_candidate_lineage(metadata)

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


_COMMON_STAGE_FIELDS = (
    "stage_result_id",
    "stage_result_sha256",
    "strategy_key",
    "strategy_version",
    "strategy_artifact_hash",
    "as_of",
)


def _project_stage(stage, expected_key, extra_keys):
    projected = {"stage_key": expected_key}
    for key in _COMMON_STAGE_FIELDS:
        value = stage.get(key)
        if not isinstance(value, str) or not value:
            return None
        projected[key] = value
    for key in extra_keys:
        value = stage.get(key)
        if not isinstance(value, str) or not value:
            return None
        projected[key] = value
    return projected


def project_candidate_lineage(metadata):
    if not isinstance(metadata, Mapping):
        return None
    lineage = metadata.get("lineage")
    if not isinstance(lineage, Mapping):
        return None
    if lineage.get("schema_version") != "candidate-lineage/1.0":
        return None
    stages = lineage.get("stages")
    if (
        not isinstance(stages, Sequence)
        or isinstance(stages, (str, bytes, bytearray))
        or len(stages) != 2
    ):
        return None
    sector_src, stock_src = stages
    if not isinstance(sector_src, Mapping) or not isinstance(stock_src, Mapping):
        return None
    if sector_src.get("stage_key") != "sector_selection":
        return None
    if stock_src.get("stage_key") != "stock_screening":
        return None

    sector = _project_stage(sector_src, "sector_selection", ("constituent_snapshot_sha256",))
    if sector is None:
        return None
    stock = _project_stage(
        stock_src,
        "stock_screening",
        ("upstream_stage_result_id", "upstream_stage_result_sha256"),
    )
    if stock is None:
        return None

    return {
        "schema_version": "candidate-lineage/1.0",
        "stages": [sector, stock],
    }


__all__ = ["ExternalWorkflowQueryService", "project_candidate_lineage"]
