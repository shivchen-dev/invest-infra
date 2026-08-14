"""Safe, idempotent import of archived WorkBuddy candidate packages.

The bridge deliberately reads only an already completed archive.  It never
executes producer code and never accepts a path supplied by the payload.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from invest_domain.integration import (
    AdmissionStatus,
    ExternalArtifact,
    ExternalObservation,
    ExternalWorkflowRun,
    IntakeStatus,
    ProducerStatus,
)

from invest_pipeline.workbuddy_candidates import parse_candidates_payload
from invest_pipeline.workbuddy_candidates.projection import Resolver, project_candidates


@dataclass(frozen=True, slots=True)
class BridgeImportResult:
    run: ExternalWorkflowRun
    artifact: ExternalArtifact
    observations: tuple[ExternalObservation, ...]
    findings: tuple[dict[str, Any], ...]
    idempotent: bool


def import_archived_candidate_run(
    archive_root: str | Path,
    *,
    trade_date: str,
    workflow_run_id: str,
    uow,
    resolver: Resolver | None = None,
) -> BridgeImportResult:
    """Import one immutable archive into Integration repositories.

    ``archive_root`` is the only filesystem authority.  The date and run id
    are validated before path construction, and the resulting directory is
    checked to remain below that root.  Re-importing the same archive returns
    the existing domain objects without adding duplicates.
    """

    archive_root_path = Path(archive_root).resolve()
    run_dir = _safe_run_dir(archive_root_path, trade_date, workflow_run_id)
    candidates_path = run_dir / "candidates.json"
    manifest_path = run_dir / "manifest.json"
    if not candidates_path.is_file() or not manifest_path.is_file():
        raise ValueError("candidate archive must contain candidates.json and manifest.json")

    payload_bytes = candidates_path.read_bytes()
    manifest = _read_object(manifest_path)
    _verify_manifest(manifest, payload_bytes)
    payload = json.loads(payload_bytes)
    parsed = parse_candidates_payload(payload)

    now = datetime.now(UTC)
    source_uuid = _stable_uuid("workbuddy-run", workflow_run_id)
    artifact_uuid = _stable_uuid("workbuddy-artifact", hashlib.sha256(payload_bytes).hexdigest())
    artifact_uri = f"archive://runs/{parsed.trade_date}/{parsed.workflow_run_id}/candidates.json"
    run = ExternalWorkflowRun(
        run_id=source_uuid,
        producer="workbuddy",
        schema_version="2.0.0",
        producer_status=_producer_status(parsed.status, bool(parsed.rejected)),
        intake_status=_intake_status(parsed),
        started_at=now,
        finished_at=now,
        metadata={
            "external_workflow_run_id": parsed.workflow_run_id,
            "trade_date": parsed.trade_date,
            "strategy_id": parsed.strategy_id,
            "candidate_rules_version": "2.0.0",
            "archive_uri": f"archive://runs/{parsed.trade_date}/{parsed.workflow_run_id}",
        },
    )
    artifact = ExternalArtifact(
        artifact_id=artifact_uuid,
        run_id=source_uuid,
        logical_uri=artifact_uri,
        content_hash=hashlib.sha256(payload_bytes).hexdigest(),
        media_type="application/json",
        size_bytes=len(payload_bytes),
        created_at=now,
        metadata={"kind": "candidate-intake", "manifest": manifest},
    )

    existing_run = uow.external_workflow_runs.get_by_id(run.run_id)
    existing_artifact = uow.external_artifacts.get_by_id(artifact.artifact_id)
    if existing_run is not None and existing_artifact is not None:
        observations = tuple(
            uow.external_observations.list_by_run(run.run_id, limit=10_000)
        )
        return BridgeImportResult(
            existing_run,
            existing_artifact,
            observations,
            tuple(parsed.findings),
            True,
        )

    if existing_run is None:
        uow.external_workflow_runs.add(run)
    if existing_artifact is None:
        uow.external_artifacts.add(artifact)

    symbol_resolver = resolver or (lambda symbol: symbol)
    projection = project_candidates(parsed, symbol_resolver)
    findings = tuple(parsed.findings + projection.findings)
    observations: list[ExternalObservation] = []
    for index, item in enumerate((*projection.accepted, *projection.needs_symbol_resolution)):
        status = "pending_validation" if item in projection.accepted else "needs_symbol_resolution"
        observation_id = _stable_uuid(
            "workbuddy-observation",
            f"{workflow_run_id}:{index}:{json.dumps(item.raw, sort_keys=True, default=str)}",
        )
        observation = ExternalObservation(
            observation_id=observation_id,
            run_id=source_uuid,
            artifact_id=artifact_uuid,
            observed_at=now,
            as_of=date.fromisoformat(parsed.trade_date),
            source_uri=artifact_uri,
            producer="workbuddy",
            payload=item.raw if isinstance(item.raw, dict) else {"raw": item.raw},
            symbol=item.symbol,
            admission_status=AdmissionStatus.PENDING,
            metadata={
                "candidate_index": index,
                "candidate_status": status,
                "strategy_id": parsed.strategy_id,
                "reason": item.reason,
            },
        )
        existing = uow.external_observations.get_by_id(observation_id)
        observations.append(existing or uow.external_observations.add(observation))

    return BridgeImportResult(run, artifact, tuple(observations), findings, False)


def _safe_run_dir(root: Path, trade_date: str, workflow_run_id: str) -> Path:
    parsed_date = date.fromisoformat(trade_date)
    if parsed_date.isoformat() != trade_date:
        raise ValueError("trade_date must be canonical YYYY-MM-DD")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", workflow_run_id) is None:
        raise ValueError("workflow_run_id must be a single path segment")
    candidate = (root / "runs" / trade_date / workflow_run_id).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("archive path escapes archive root")
    return candidate


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _verify_manifest(manifest: dict[str, Any], payload: bytes) -> None:
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise ValueError("manifest files must contain exactly one file entry")
    entry = files[0]
    if entry.get("path") != "candidates.json":
        raise ValueError("manifest does not identify candidates.json")
    digest = hashlib.sha256(payload).hexdigest()
    if entry.get("sha256") != digest or entry.get("size_bytes") != len(payload):
        raise ValueError("candidate archive hash or size does not match manifest")


def _stable_uuid(kind: str, value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"invest-infra:{kind}:{value}")


def _producer_status(status: str, has_rejections: bool) -> ProducerStatus:
    if status == "failed":
        return ProducerStatus.FAILED
    if status == "cancelled":
        return ProducerStatus.CANCELLED
    return ProducerStatus.PARTIAL if has_rejections else ProducerStatus.SUCCEEDED


def _intake_status(parsed) -> IntakeStatus:
    if parsed.accepted and parsed.rejected:
        return IntakeStatus.PARTIAL
    if parsed.accepted:
        return IntakeStatus.ACCEPTED
    return IntakeStatus.REJECTED


__all__ = ["BridgeImportResult", "import_archived_candidate_run"]
