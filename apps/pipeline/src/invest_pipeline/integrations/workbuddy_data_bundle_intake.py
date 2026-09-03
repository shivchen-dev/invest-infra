"""Transactional intake seam for immutable WorkBuddy DataBundle archives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from invest_domain.integration import (
    ExternalArtifact,
    ExternalWorkflowRun,
    IntakeStatus,
    ProducerStatus,
)
from invest_domain.strategy import DataRequest

from invest_pipeline.integrations.workbuddy_data_bundle_archive import (
    DATA_BUNDLE_RELATIVE_PATH,
    DataBundleArchiveOutcome,
    archive_data_bundle,
)

DATA_BUNDLE_RUN_ID_NAME_PREFIX = "invest-infra:data-bundle-intake:run:v1:"
DATA_BUNDLE_ARTIFACT_ID_NAME_PREFIX = "invest-infra:data-bundle-intake:artifact:v1:"
DATA_BUNDLE_METADATA_KIND = "data-bundle-intake"
DATA_BUNDLE_METADATA_SCHEMA = "data-bundle-intake/1.0"

_CONFLICT_CODE = "data_bundle_intake_conflict"
_CONFLICT_MESSAGE = "Data bundle intake conflicts with existing immutable state."
_PERSISTENCE_CODE = "data_bundle_persistence_failure"
_PERSISTENCE_MESSAGE = "Data bundle intake could not be persisted safely."


class DataBundleIntakeError(RuntimeError):
    """Base class for stable, sanitized intake failures."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DataBundleIntakeConflictError(DataBundleIntakeError):
    """Existing database state does not match the immutable intake objects."""


class DataBundlePersistenceError(DataBundleIntakeError):
    """The database operation failed and was rolled back."""


@dataclass(frozen=True, slots=True)
class DataBundleIntakeOutcome:
    archive: DataBundleArchiveOutcome
    run: ExternalWorkflowRun
    artifact: ExternalArtifact
    idempotent: bool


def _expected_objects(
    request: DataRequest,
    archive: DataBundleArchiveOutcome,
) -> tuple[ExternalWorkflowRun, ExternalArtifact]:
    validated = archive.validated_bundle
    bundle = validated.bundle
    run_id = uuid5(NAMESPACE_URL, DATA_BUNDLE_RUN_ID_NAME_PREFIX + request.request_id)
    artifact_id = uuid5(
        NAMESPACE_URL, DATA_BUNDLE_ARTIFACT_ID_NAME_PREFIX + request.request_id
    )
    identity = {
        "request_id": request.request_id,
        "definition_key": request.definition_key,
        "definition_version": request.definition_version,
        "strategy_key": request.strategy_key,
        "strategy_version": request.strategy_version,
        "strategy_artifact_hash": request.strategy_artifact_hash,
        "stage": request.stage,
        "archive_uri": archive.archive_uri,
        "canonical_sha256": validated.canonical_sha256,
        "kind": DATA_BUNDLE_METADATA_KIND,
        "metadata_schema": DATA_BUNDLE_METADATA_SCHEMA,
    }
    run = ExternalWorkflowRun(
        run_id=run_id,
        producer=bundle.producer,
        schema_version=bundle.schema_version,
        producer_status=ProducerStatus.SUCCEEDED,
        intake_status=IntakeStatus.ACCEPTED,
        started_at=bundle.generated_at,
        finished_at=bundle.generated_at,
        metadata=identity,
    )
    artifact = ExternalArtifact(
        artifact_id=artifact_id,
        run_id=run_id,
        logical_uri=f"{archive.archive_uri}/{DATA_BUNDLE_RELATIVE_PATH}",
        content_hash=archive.archived_raw_sha256,
        media_type="application/json",
        size_bytes=archive.archived_size_bytes,
        created_at=bundle.generated_at,
        metadata=identity,
    )
    return run, artifact


def ingest_data_bundle(
    request: DataRequest,
    raw_bytes: bytes,
    archive_root: str | Path,
    uow,
) -> DataBundleIntakeOutcome:
    """Archive a validated DataBundle, then atomically persist its lineage."""

    archive = archive_data_bundle(request, raw_bytes, archive_root)
    run, artifact = _expected_objects(request, archive)

    persistence_failed = False
    try:
        with uow as active_uow:
            existing_run = active_uow.external_workflow_runs.get_by_id(run.run_id)
            existing_artifact = active_uow.external_artifacts.get_by_id(
                artifact.artifact_id
            )
            if existing_run is None and existing_artifact is None:
                active_uow.external_workflow_runs.add(run)
                active_uow.external_artifacts.add(artifact)
                idempotent = False
            elif existing_run == run and existing_artifact is None:
                active_uow.external_artifacts.add(artifact)
                idempotent = False
            elif existing_run == run and existing_artifact == artifact:
                idempotent = True
            else:
                raise DataBundleIntakeConflictError(
                    _CONFLICT_CODE, _CONFLICT_MESSAGE
                )
    except DataBundleIntakeConflictError:
        raise
    except Exception:
        persistence_failed = True

    if persistence_failed:
        raise DataBundlePersistenceError(
            _PERSISTENCE_CODE, _PERSISTENCE_MESSAGE
        ) from None

    return DataBundleIntakeOutcome(archive, run, artifact, idempotent)


__all__ = [
    "DATA_BUNDLE_ARTIFACT_ID_NAME_PREFIX",
    "DATA_BUNDLE_METADATA_KIND",
    "DATA_BUNDLE_METADATA_SCHEMA",
    "DATA_BUNDLE_RUN_ID_NAME_PREFIX",
    "DataBundleIntakeConflictError",
    "DataBundleIntakeError",
    "DataBundleIntakeOutcome",
    "DataBundlePersistenceError",
    "ingest_data_bundle",
]
