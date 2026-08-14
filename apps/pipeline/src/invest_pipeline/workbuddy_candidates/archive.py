from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from invest_pipeline.workbuddy_candidates import parse_candidates_payload

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _require_trade_date(value: Any) -> str:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError(f"invalid trade_date: {value!r}")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid trade_date: {value!r}") from exc
    return value


def _require_workflow_run_id(value: Any) -> str:
    if not isinstance(value, str) or not _RUN_ID_RE.match(value):
        raise ValueError(f"invalid workflow_run_id: {value!r}")
    return value


@dataclass
class ArchiveOutcome:
    archive_uri: str
    run_dir: str
    manifest_path: str
    idempotent: bool
    conflict: bool
    accepted_count: int
    rejected_count: int
    findings: list = field(default_factory=list)


def _encode_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_of_file(path: str) -> str:
    with open(path, "rb") as fp:
        return hashlib.sha256(fp.read()).hexdigest()


def archive_candidates(payload: Any, archive_root: str) -> ArchiveOutcome:
    parsed = parse_candidates_payload(payload)

    trade_date = _require_trade_date(parsed.trade_date)
    workflow_run_id = _require_workflow_run_id(parsed.workflow_run_id)

    accepted_count = len(parsed.accepted)
    rejected_count = len(parsed.rejected)
    findings = list(parsed.findings)

    run_dir = os.path.join(archive_root, "runs", trade_date, workflow_run_id)
    archive_uri = f"archive://runs/{trade_date}/{workflow_run_id}"

    candidates_relpath = "candidates.json"
    manifest_relpath = "manifest.json"
    final_candidates_path = os.path.join(run_dir, candidates_relpath)
    final_manifest_path = os.path.join(run_dir, manifest_relpath)

    candidates_bytes = _encode_json(payload)
    candidates_sha = hashlib.sha256(candidates_bytes).hexdigest()
    candidates_size = len(candidates_bytes)

    manifest_payload = {
        "schema_version": "candidate-intake.manifest/1.0",
        "workflow_run_id": workflow_run_id,
        "trade_date": trade_date,
        "candidate_rules_version": "2.0.0",
        "files": [
            {
                "path": candidates_relpath,
                "size_bytes": candidates_size,
                "sha256": candidates_sha,
            }
        ],
    }
    manifest_bytes = _encode_json(manifest_payload)

    if os.path.isdir(run_dir):
        existing_sha = (
            _sha256_of_file(final_candidates_path)
            if os.path.isfile(final_candidates_path)
            else None
        )
        same = existing_sha == candidates_sha
        return ArchiveOutcome(
            archive_uri=archive_uri,
            run_dir=run_dir,
            manifest_path=final_manifest_path,
            idempotent=same,
            conflict=not same,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            findings=findings,
        )

    os.makedirs(os.path.dirname(run_dir), exist_ok=True)

    tmp_dir = tempfile.mkdtemp(prefix=".archive-", dir=archive_root)
    try:
        with open(os.path.join(tmp_dir, candidates_relpath), "wb") as fp:
            fp.write(candidates_bytes)
        with open(os.path.join(tmp_dir, manifest_relpath), "wb") as fp:
            fp.write(manifest_bytes)
        os.replace(tmp_dir, run_dir)
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    return ArchiveOutcome(
        archive_uri=archive_uri,
        run_dir=run_dir,
        manifest_path=final_manifest_path,
        idempotent=False,
        conflict=False,
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        findings=findings,
    )


__all__ = ["ArchiveOutcome", "archive_candidates"]
