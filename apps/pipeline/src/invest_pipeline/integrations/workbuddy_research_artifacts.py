"""Safe, local ingestion of generic WorkBuddy research result artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSION = "workbuddy.invest-result/1.0"
STATUSES = frozenset({"success", "partial", "failed", "blocked_no_data"})
_TEMPORARY_PREFIX = ".workbuddy-"
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_RESULT_BYTES = 16 * 1024 * 1024
_MAX_REPORT_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ResearchArtifactImport:
    status: str
    task_id: str | None
    schema_version: str | None
    content_hash: str | None
    archive_dir: Path | None
    idempotent: bool
    diagnostics: tuple[str, ...] = ()


def discover_research_artifact_packages(results_root: str | Path) -> list[Path]:
    """Return direct-child ``result.json``/``report.md`` packages under ``results_root``.

    Only ordinary directories are scanned; symlinked directories and entries
    whose ``result.json`` or ``report.md`` is itself a symlink are skipped.
    Temporary directories (prefix ``.workbuddy-``) created by
    :func:`ingest_research_artifact` are excluded. Results are returned in
    stable sorted order by path.
    """
    root = Path(results_root)
    packages: list[Path] = []
    for entry in root.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            continue
        if entry.name.startswith(_TEMPORARY_PREFIX):
            continue
        if not _has_regular_file(entry, "result.json"):
            continue
        if not _has_regular_file(entry, "report.md"):
            continue
        packages.append(entry)
    return sorted(packages)


def _has_regular_file(package: Path, name: str) -> bool:
    path = package / name
    return path.is_file() and not path.is_symlink()


def ingest_research_artifact(
    package_dir: str | Path,
    archive_root: str | Path,
    *,
    expected_task_id: str | None = None,
) -> ResearchArtifactImport:
    """Validate and immutably archive one ``result.json``/``report.md`` pair.

    This boundary intentionally has no database or candidate-intake coupling.
    Invalid packages return a diagnostic failed outcome and are never archived.
    """
    package = Path(package_dir).resolve()
    root = Path(archive_root).resolve()
    try:
        result_path = _regular_child(package, "result.json")
        report_path = _regular_child(package, "report.md")
        result_bytes = _read_bounded(result_path, _MAX_RESULT_BYTES)
        report_bytes = _read_bounded(report_path, _MAX_REPORT_BYTES)
        report_bytes.decode("utf-8")
        result = _parse_result(result_bytes)
        task_id = _require_task_id(result.get("task_id"))
        if expected_task_id is not None and task_id != expected_task_id:
            raise ValueError("task_id does not match package identity")
        schema_version = result.get("schema_version")
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {schema_version!r}")
        status = result.get("status")
        if status not in STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        _verify_hashes(result, result_bytes, report_bytes)
        content_hash = _content_hash(result_bytes, report_bytes)
        destination = root / task_id / schema_version / content_hash
        _ensure_below(root, destination.resolve())
        existing = _find_existing(root / task_id / schema_version, content_hash)
        if existing is not None:
            _verify_archived(existing, result_bytes, report_bytes)
            return ResearchArtifactImport(
                status, task_id, schema_version, content_hash, existing, True
            )
        if (root / task_id / schema_version).exists():
            raise ValueError("conflicting delivery: task_id/schema_version already archived")
        _atomic_archive(destination, result_bytes, report_bytes)
        return ResearchArtifactImport(
            status, task_id, schema_version, content_hash, destination, False
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return ResearchArtifactImport(
            "failed", locals().get("task_id"), locals().get("schema_version"),
            locals().get("content_hash"), None, False, (str(exc),)
        )


def _regular_child(package: Path, name: str) -> Path:
    if not package.is_dir():
        raise ValueError("package directory does not exist")
    path = package / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != package:
        raise ValueError(f"unsafe or missing package file: {name}")
    return path


def _read_bounded(path: Path, limit: int) -> bytes:
    size = path.stat().st_size
    if size > limit:
        raise ValueError(f"{path.name} exceeds maximum size")
    return path.read_bytes()


def _parse_result(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("result.json must contain an object")
    return value


def _require_task_id(value: Any) -> str:
    if not isinstance(value, str) or _TASK_ID.fullmatch(value) is None:
        raise ValueError("task_id must be a safe single path segment")
    return value


def _verify_hashes(result: dict[str, Any], result_bytes: bytes, report_bytes: bytes) -> None:
    expected_result = result.get("result_hash")
    unsigned = dict(result)
    unsigned.pop("result_hash", None)
    canonical = json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if expected_result != hashlib.sha256(canonical).hexdigest():
        raise ValueError("result_hash does not match canonical result")
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1 or not isinstance(artifacts[0], dict):
        raise ValueError("artifacts must contain exactly one report.md entry")
    artifact = artifacts[0]
    if artifact.get("path") != "report.md":
        raise ValueError("report artifact path must be report.md")
    if artifact.get("sha256") != hashlib.sha256(report_bytes).hexdigest():
        raise ValueError("report.md hash does not match result")


def _content_hash(result_bytes: bytes, report_bytes: bytes) -> str:
    digest = hashlib.sha256()
    for payload in (result_bytes, report_bytes):
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _ensure_below(root: Path, path: Path) -> None:
    if path != root and root not in path.parents:
        raise ValueError("archive path escapes archive root")


def _find_existing(identity: Path, content_hash: str) -> Path | None:
    candidate = identity / content_hash
    return candidate if candidate.is_dir() else None


def _verify_archived(destination: Path, result_bytes: bytes, report_bytes: bytes) -> None:
    if _read_bounded(_regular_child(destination, "result.json"), _MAX_RESULT_BYTES) != result_bytes:
        raise ValueError("duplicate delivery has different result bytes")
    if _read_bounded(_regular_child(destination, "report.md"), _MAX_REPORT_BYTES) != report_bytes:
        raise ValueError("duplicate delivery has different report bytes")


def _atomic_archive(destination: Path, result_bytes: bytes, report_bytes: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("archive destination already exists")
    temporary = Path(tempfile.mkdtemp(prefix=".workbuddy-", dir=destination.parent))
    try:
        (temporary / "result.json").write_bytes(result_bytes)
        (temporary / "report.md").write_bytes(report_bytes)
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


__all__ = [
    "ResearchArtifactImport",
    "SUPPORTED_SCHEMA_VERSION",
    "discover_research_artifact_packages",
    "ingest_research_artifact",
]
