"""Immutable archive for WorkBuddy candidate intake batches."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from invest_pipeline.workbuddy_candidates import parse_candidates_payload

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MANIFEST_SCHEMA = "candidate-intake.manifest/1.0"


@dataclass
class ArchiveOutcome:
    archive_uri: str | None
    run_dir: str | None
    manifest_path: str | None
    idempotent: bool = False
    conflict: bool = False
    accepted_count: int = 0
    rejected_count: int = 0
    findings: list[dict[str, Any]] = field(default_factory=list)


def archive_candidates(
    payload: object, archive_root: str | os.PathLike[str]
) -> ArchiveOutcome:
    """Validate and atomically archive one candidate batch."""
    result = parse_candidates_payload(payload)
    trade_date = result.trade_date
    workflow_run_id = result.workflow_run_id
    if not _is_valid_date(trade_date) or not _RUN_ID.fullmatch(workflow_run_id or ""):
        raise ValueError("unsafe archive identity")

    raw_bytes = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    root = Path(archive_root)
    parent = root / "runs" / trade_date
    target = parent / workflow_run_id
    parent.mkdir(parents=True, exist_ok=True)
    candidate_hash = hashlib.sha256(raw_bytes).hexdigest()
    archive_uri = f"archive://runs/{trade_date}/{workflow_run_id}"

    if target.exists():
        existing = target / "candidates.json"
        if existing.is_file() and _sha256(existing.read_bytes()) == candidate_hash:
            return _outcome(result, archive_uri, target, True, False)
        return _outcome(result, archive_uri, target, False, True)

    staging = Path(tempfile.mkdtemp(prefix=".candidate-intake-", dir=parent))
    try:
        candidate_path = staging / "candidates.json"
        candidate_path.write_bytes(raw_bytes)
        manifest = {
            "schema_version": _MANIFEST_SCHEMA,
            "workflow_run_id": workflow_run_id,
            "trade_date": trade_date,
            "candidate_rules_version": "2.0.0",
            "files": [
                {
                    "path": "candidates.json",
                    "size_bytes": len(raw_bytes),
                    "sha256": candidate_hash,
                }
            ],
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            os.replace(staging, target)
        except FileExistsError:
            existing = target / "candidates.json"
            if existing.is_file() and _sha256(existing.read_bytes()) == candidate_hash:
                return _outcome(result, archive_uri, target, True, False)
            return _outcome(result, archive_uri, target, False, True)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return _outcome(result, archive_uri, target, False, False)


def _outcome(result: Any, uri: str, target: Path, idem: bool, conflict: bool) -> ArchiveOutcome:
    return ArchiveOutcome(
        uri,
        str(target),
        str(target / "manifest.json"),
        idem,
        conflict,
        len(result.accepted),
        len(result.rejected),
        list(result.findings),
    )


def _is_valid_date(value: str | None) -> bool:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


__all__ = ["ArchiveOutcome", "archive_candidates"]
