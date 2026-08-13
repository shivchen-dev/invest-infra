"""WorkBuddy governance immutable archive (M1 + M2 atomic slices).

Implements the archive half of the contract section 7 ("Archive contract"),
the ``import`` CLI command for
``python -m invest_pipeline.workbuddy_reports import``, and the M2
``latest-accepted.json`` pointer updates.

Scope:

* immutable archive build — copy the triplet, write
  ``governed-quality-report.json`` and ``manifest.json``;
* re-read every archived file's bytes and recompute hashes independently;
* atomic rename into ``<root>/runs/<trade_date>/<workflow_run_id>/``;
* idempotency detection and conflict detection via hash-set comparison;
* M2 — atomic ``<root>/latest-accepted.json`` pointer update for
  ``accepted`` runs, sorted by ``(trade_date, finished_at,
  workflow_run_id)``.  Partial / rejected runs archive but never touch
  the pointer.

Path-safety: ``trade_date`` and ``workflow_run_id`` flow directly into
``os.path.join`` to build the run directory.  The validator is the
fail-closed boundary that rejects malformed identity (strict
``YYYY-MM-DD`` for ``trade_date``, single-path-segment characters only
for ``workflow_run_id``); this module re-validates defensively so a
direct caller of ``archive_run`` cannot bypass the check.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from invest_pipeline.workbuddy_reports.validator import (
    ValidationResult,
    discover_triplet,
    is_safe_workflow_run_id,
    is_valid_trade_date,
    validate_triplet,
)

__all__ = [
    "ImportOutcome",
    "LATEST_POINTER_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "archive_run",
]


SCHEMA_VERSION = "invest-pipeline/workbuddy-governed-quality-report@1.0"
MANIFEST_SCHEMA_VERSION = "invest-pipeline/workbuddy-archive-manifest@1.0"
LATEST_POINTER_SCHEMA_VERSION = (
    "invest-pipeline/workbuddy-latest-accepted-pointer@1.0"
)
_MANIFEST_FILENAME = "manifest.json"
_GOVERNED_REPORT_FILENAME = "governed-quality-report.json"
_LATEST_POINTER_FILENAME = "latest-accepted.json"
# Fixed lock-file name used to serialize ``latest-accepted.json`` writers
# across processes via ``fcntl.flock``.  Lives next to the pointer inside
# ``governance_root``; never deleted (so it survives the cleanup ``finally``)
# and never matches the ``.tmp-*`` pattern tests scan for.
_LATEST_POINTER_LOCK_FILENAME = ".latest-accepted.lock"

# Pointer-update outcome (also drives ImportOutcome.pointer_status).
_POINTER_STATUS_NOT_ATTEMPTED = "not_attempted"
_POINTER_STATUS_UPDATED = "updated"
_POINTER_STATUS_SKIPPED = "skipped"
_POINTER_STATUS_CORRUPT = "corrupt"
_POINTER_STATUS_IO_ERROR = "io_error"


@dataclass(slots=True)
class ImportOutcome:
    """Result of :func:`archive_run` / CLI ``import``.

    Mirrors the contract section 9 single-JSON stdout payload plus the
    bookkeeping needed for tests (final paths, idempotent/conflict flags,
    I/O error code, pointer-update outcome).
    """

    governance_status: str
    workflow_run_id: str | None
    trade_date: str | None
    producer_status: str | None
    errors: list[str]
    warnings: list[str]
    validated_at: str
    file_hashes: dict[str, dict[str, int | str]] = field(default_factory=dict)
    run_dir: str | None = None
    manifest_path: str | None = None
    governed_report_path: str | None = None
    is_idempotent: bool = False
    is_conflict: bool = False
    error_codes: list[str] = field(default_factory=list)
    pointer_updated: bool = False
    pointer_path: str | None = None
    pointer_status: str = _POINTER_STATUS_NOT_ATTEMPTED

    @property
    def exit_code(self) -> int:
        if self.is_conflict:
            return 5
        if self.pointer_status == _POINTER_STATUS_CORRUPT:
            return 5
        if self.pointer_status == _POINTER_STATUS_IO_ERROR:
            return 5
        if self.governance_status == "accepted":
            return 0
        if self.governance_status == "partial":
            return 2
        if self.governance_status == "rejected":
            if "input_error" in self.error_codes or "unsupported_version" in self.error_codes:
                return 4
            return 3
        return 4

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "governance_status": self.governance_status,
            "workflow_run_id": self.workflow_run_id,
            "trade_date": self.trade_date,
            "producer_status": self.producer_status,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "validated_at": self.validated_at,
            "file_hashes": {
                role: dict(details) for role, details in self.file_hashes.items()
            },
            "run_dir": self.run_dir,
            "manifest_path": self.manifest_path,
            "governed_report_path": self.governed_report_path,
            "is_idempotent": self.is_idempotent,
            "is_conflict": self.is_conflict,
            "pointer_updated": self.pointer_updated,
            "pointer_path": self.pointer_path,
            "exit_code": self.exit_code,
        }


def archive_run(
    source_dir: str | os.PathLike[str],
    governance_root: str | os.PathLike[str],
) -> ImportOutcome:
    """Build the immutable archive for one WorkBuddy governance run.

    The function is idempotent at the archive level: re-importing the
    same source triplet for the same ``(trade_date, workflow_run_id)``
    returns a success outcome with ``is_idempotent=True``.  Re-importing
    a different triplet for the same identity returns a conflict outcome
    and never overwrites the existing archive.

    Archive layout::

        <governance_root>/runs/<trade_date>/<workflow_run_id>/
            <original basenames>
            governed-quality-report.json
            manifest.json

    Archive determinism: ``validated_at`` is derived from the source
    triplet's max mtime so that re-importing an unchanged source yields
    byte-identical archive contents and triggers the idempotency path.
    """
    try:
        source_dir = os.fspath(source_dir)
        governance_root = os.fspath(governance_root)
    except (TypeError, ValueError) as exc:
        return _input_error_outcome(f"invalid path argument: {exc}")

    triple = discover_triplet(source_dir)
    if triple is None:
        return _input_error_outcome(
            "could not locate sector_result*.json + 板块强度排行榜*.md + "
            "sector_quality*.json (or legacy result*.json + report*.md + "
            f"quality_report*.json) inside {source_dir!r}"
        )

    result_path, report_path, quality_path = triple
    verdict = validate_triplet(
        result_path=result_path,
        report_path=report_path,
        quality_path=quality_path,
    )

    if not verdict.workflow_run_id or not verdict.trade_date:
        return _verdict_only_outcome(
            verdict,
            validated_at=_derive_validated_at([result_path, report_path, quality_path]),
        )

    return _archive_verdict(
        verdict,
        result_path=result_path,
        report_path=report_path,
        quality_path=quality_path,
        governance_root=governance_root,
        validated_at=_derive_validated_at([result_path, report_path, quality_path]),
    )


# ---------------------------------------------------------------------------
# Internal: archive construction
# ---------------------------------------------------------------------------


def _archive_verdict(
    verdict: ValidationResult,
    *,
    result_path: str,
    report_path: str,
    quality_path: str,
    governance_root: str,
    validated_at: str,
) -> ImportOutcome:
    trade_date = verdict.trade_date or ""
    workflow_run_id = verdict.workflow_run_id or ""

    if not is_valid_trade_date(trade_date) or not is_safe_workflow_run_id(
        workflow_run_id
    ):
        return _input_error_outcome(
            "archive rejected unsafe path identity: "
            f"trade_date={trade_date!r} workflow_run_id={workflow_run_id!r}"
        )

    runs_trade_date = os.path.join(governance_root, "runs", trade_date)
    target_dir = os.path.join(runs_trade_date, workflow_run_id)

    try:
        os.makedirs(runs_trade_date, exist_ok=True)
    except OSError as exc:
        return _io_outcome(verdict, f"failed to create {runs_trade_date!r}: {exc}", validated_at)

    staging_dir = tempfile.mkdtemp(prefix=".tmp-", dir=runs_trade_date)

    try:
        try:
            copied = _copy_triplet(
                result_path=result_path,
                report_path=report_path,
                quality_path=quality_path,
                staging_dir=staging_dir,
            )
        except OSError as exc:
            return _io_outcome(verdict, f"failed to copy triplet: {exc}", validated_at)

        governed_payload = _build_governed_report(verdict, validated_at=validated_at)
        governed_bytes = _dump_json_bytes(governed_payload)
        governed_path = os.path.join(staging_dir, _GOVERNED_REPORT_FILENAME)
        try:
            _write_bytes(governed_path, governed_bytes)
        except OSError as exc:
            return _io_outcome(verdict, f"failed to write governed report: {exc}", validated_at)

        archived_files: dict[str, str] = dict(copied)
        archived_files[_GOVERNED_REPORT_FILENAME] = governed_path

        try:
            recomputed = {name: _hash_file(path) for name, path in archived_files.items()}
        except OSError as exc:
            return _io_outcome(verdict, f"failed to hash staged file: {exc}", validated_at)

        manifest_payload = _build_manifest_payload(recomputed)
        manifest_bytes = _dump_json_bytes(manifest_payload)
        manifest_path = os.path.join(staging_dir, _MANIFEST_FILENAME)
        try:
            _write_bytes(manifest_path, manifest_bytes)
        except OSError as exc:
            return _io_outcome(verdict, f"failed to write manifest: {exc}", validated_at)

        try:
            with open(manifest_path, "rb") as fh:
                manifest_on_disk = json.loads(fh.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return _io_outcome(verdict, f"failed to verify manifest on disk: {exc}", validated_at)
        if not _manifest_matches(recomputed, manifest_on_disk):
            return _io_outcome(
                verdict,
                "manifest entries inconsistent with archived bytes",
                validated_at,
            )

        existing_manifest = _read_existing_manifest(target_dir)
        if existing_manifest is not None:
            if _manifest_hash_set_matches(existing_manifest, manifest_on_disk):
                pointer = _maybe_update_pointer(
                    verdict=verdict,
                    target_dir=target_dir,
                    result_path=result_path,
                    governance_root=governance_root,
                    validated_at=validated_at,
                )
                return _success_outcome(
                    verdict,
                    target_dir=target_dir,
                    validated_at=validated_at,
                    is_idempotent=True,
                    pointer_updated=pointer[0],
                    pointer_path=pointer[2],
                    pointer_status=pointer[1],
                )
            return _conflict_outcome(verdict, target_dir, validated_at)

        if os.path.isdir(target_dir):
            return _conflict_outcome(verdict, target_dir, validated_at)

        try:
            os.replace(staging_dir, target_dir)
        except OSError as exc:
            if exc.errno in (errno.EEXIST, errno.ENOTEMPTY):
                existing_manifest = _read_existing_manifest(target_dir)
                if existing_manifest is not None and _manifest_hash_set_matches(
                    existing_manifest, manifest_on_disk
                ):
                    pointer = _maybe_update_pointer(
                        verdict=verdict,
                        target_dir=target_dir,
                        result_path=result_path,
                        governance_root=governance_root,
                        validated_at=validated_at,
                    )
                    return _success_outcome(
                        verdict,
                        target_dir=target_dir,
                        validated_at=validated_at,
                        is_idempotent=True,
                        pointer_updated=pointer[0],
                        pointer_path=pointer[2],
                        pointer_status=pointer[1],
                    )
                return _conflict_outcome(verdict, target_dir, validated_at)
            return _io_outcome(verdict, f"atomic rename failed: {exc}", validated_at)

        pointer = _maybe_update_pointer(
            verdict=verdict,
            target_dir=target_dir,
            result_path=result_path,
            governance_root=governance_root,
            validated_at=validated_at,
        )
        return _success_outcome(
            verdict,
            target_dir=target_dir,
            validated_at=validated_at,
            pointer_updated=pointer[0],
            pointer_path=pointer[2],
            pointer_status=pointer[1],
        )
    finally:
        _cleanup_staging(staging_dir)


def _copy_triplet(
    *,
    result_path: str,
    report_path: str,
    quality_path: str,
    staging_dir: str,
) -> dict[str, str]:
    copied: dict[str, str] = {}
    for src in (result_path, report_path, quality_path):
        dst = os.path.join(staging_dir, os.path.basename(src))
        shutil.copy2(src, dst)
        copied[os.path.basename(src)] = dst
    return copied


def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(data)


def _hash_file(path: str) -> dict[str, int | str]:
    with open(path, "rb") as fh:
        payload = fh.read()
    return {
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _build_governed_report(verdict: ValidationResult, *, validated_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "workflow_run_id": verdict.workflow_run_id,
        "trade_date": verdict.trade_date,
        "producer_status": verdict.producer_status,
        "governance_status": verdict.governance_status,
        "validated_at": validated_at,
        "errors": list(verdict.errors),
        "warnings": list(verdict.warnings),
        "file_hashes": {
            role: dict(details) for role, details in verdict.file_hashes.items()
        },
    }


def _build_manifest_payload(recomputed: dict[str, dict[str, int | str]]) -> dict[str, Any]:
    entries = [
        {
            "path": name,
            "size_bytes": details["size_bytes"],
            "sha256": details["sha256"],
        }
        for name, details in sorted(recomputed.items())
    ]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "entries": entries,
    }


def _manifest_matches(
    recomputed: dict[str, dict[str, int | str]],
    manifest: dict[str, Any],
) -> bool:
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        return False
    by_path: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            return False
        path = entry.get("path")
        if not isinstance(path, str):
            return False
        by_path[path] = entry
    if set(by_path) != set(recomputed):
        return False
    for name, expected in recomputed.items():
        entry = by_path[name]
        if entry.get("size_bytes") != expected["size_bytes"]:
            return False
        if entry.get("sha256") != expected["sha256"]:
            return False
    return True


def _manifest_hash_set_matches(existing: dict[str, Any], new: dict[str, Any]) -> bool:
    return _hash_set(existing) == _hash_set(new)


def _hash_set(payload: dict[str, Any]) -> set[tuple[str, int, str]]:
    entries = payload.get("entries") or []
    out: set[tuple[str, int, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        size = entry.get("size_bytes")
        sha = entry.get("sha256")
        if isinstance(path, str) and isinstance(size, int) and isinstance(sha, str):
            out.add((path, size, sha))
    return out


def _read_existing_manifest(target_dir: str) -> dict[str, Any] | None:
    manifest_path = os.path.join(target_dir, _MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        return None
    try:
        with open(manifest_path, "rb") as fh:
            return json.loads(fh.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _cleanup_staging(staging_dir: str) -> None:
    if not staging_dir:
        return
    if os.path.isdir(staging_dir):
        shutil.rmtree(staging_dir, ignore_errors=True)


def _dump_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _derive_validated_at(source_paths: list[str]) -> str:
    """Derive ``validated_at`` deterministically from the source triplet.

    Using the max mtime of the source files guarantees that re-importing
    an unchanged source triplet produces byte-identical archive contents
    (and therefore triggers the idempotency path).  If the source files
    are inaccessible we fall back to the current UTC time — the archive
    is still usable, just not idempotency-stable across re-runs.
    """
    try:
        max_mtime = max(os.path.getmtime(p) for p in source_paths)
    except OSError:
        return _now_iso()
    return datetime.fromtimestamp(max_mtime, tz=UTC).isoformat()


# ---------------------------------------------------------------------------
# Internal: outcome builders
# ---------------------------------------------------------------------------


def _input_error_outcome(message: str) -> ImportOutcome:
    return ImportOutcome(
        governance_status="rejected",
        workflow_run_id=None,
        trade_date=None,
        producer_status=None,
        errors=[message],
        warnings=[],
        validated_at=_now_iso(),
        error_codes=["input_error"],
    )


def _verdict_only_outcome(verdict: ValidationResult, *, validated_at: str) -> ImportOutcome:
    return ImportOutcome(
        governance_status=verdict.governance_status,
        workflow_run_id=verdict.workflow_run_id,
        trade_date=verdict.trade_date,
        producer_status=verdict.producer_status,
        errors=list(verdict.errors),
        warnings=list(verdict.warnings),
        file_hashes={
            role: dict(details) for role, details in verdict.file_hashes.items()
        },
        validated_at=validated_at,
        error_codes=list(verdict.error_codes),
    )


def _io_outcome(
    verdict: ValidationResult,
    message: str,
    validated_at: str,
) -> ImportOutcome:
    return ImportOutcome(
        governance_status="rejected",
        workflow_run_id=verdict.workflow_run_id,
        trade_date=verdict.trade_date,
        producer_status=verdict.producer_status,
        errors=[message],
        warnings=list(verdict.warnings),
        file_hashes={
            role: dict(details) for role, details in verdict.file_hashes.items()
        },
        validated_at=validated_at,
        error_codes=list(verdict.error_codes) + ["io_error"],
    )


def _conflict_outcome(
    verdict: ValidationResult,
    target_dir: str,
    validated_at: str,
) -> ImportOutcome:
    return ImportOutcome(
        governance_status=verdict.governance_status,
        workflow_run_id=verdict.workflow_run_id,
        trade_date=verdict.trade_date,
        producer_status=verdict.producer_status,
        errors=[
            f"archive conflict at {target_dir!r}: existing archive differs "
            "from incoming run; existing archive left untouched"
        ],
        warnings=list(verdict.warnings),
        file_hashes={
            role: dict(details) for role, details in verdict.file_hashes.items()
        },
        run_dir=target_dir,
        validated_at=validated_at,
        is_conflict=True,
        error_codes=list(verdict.error_codes),
    )


def _success_outcome(
    verdict: ValidationResult,
    *,
    target_dir: str,
    validated_at: str,
    is_idempotent: bool = False,
    pointer_updated: bool = False,
    pointer_path: str | None = None,
    pointer_status: str = _POINTER_STATUS_NOT_ATTEMPTED,
) -> ImportOutcome:
    return ImportOutcome(
        governance_status=verdict.governance_status,
        workflow_run_id=verdict.workflow_run_id,
        trade_date=verdict.trade_date,
        producer_status=verdict.producer_status,
        errors=list(verdict.errors),
        warnings=list(verdict.warnings),
        file_hashes={
            role: dict(details) for role, details in verdict.file_hashes.items()
        },
        run_dir=target_dir,
        manifest_path=os.path.join(target_dir, _MANIFEST_FILENAME),
        governed_report_path=os.path.join(target_dir, _GOVERNED_REPORT_FILENAME),
        is_idempotent=is_idempotent,
        validated_at=validated_at,
        error_codes=list(verdict.error_codes),
        pointer_updated=pointer_updated,
        pointer_path=pointer_path,
        pointer_status=pointer_status,
    )


# ---------------------------------------------------------------------------
# Internal: M2 latest-accepted pointer
# ---------------------------------------------------------------------------


class _LatestPointerCorrupt(Exception):
    """Raised when the on-disk latest-accepted pointer cannot be parsed."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


def _maybe_update_pointer(
    *,
    verdict: ValidationResult,
    target_dir: str,
    result_path: str,
    governance_root: str,
    validated_at: str,
) -> tuple[bool, str, str | None]:
    """Gate pointer updates behind ``governance_status == 'accepted'``.

    Returns ``(pointer_updated, pointer_status, pointer_path)`` for the
    ImportOutcome.  Non-accepted runs return ``not_attempted`` so the
    caller can drop them on the floor.  Archive-failure paths short-circuit
    before reaching this function, so a "not_attempted" result also
    implies the caller already knows the archive succeeded.
    """
    pointer_path = os.path.join(governance_root, _LATEST_POINTER_FILENAME)
    if verdict.governance_status != "accepted":
        return False, _POINTER_STATUS_NOT_ATTEMPTED, pointer_path
    return _update_latest_pointer(
        target_dir=target_dir,
        result_basename=os.path.basename(result_path),
        governance_root=governance_root,
        validated_at=validated_at,
    )


def _update_latest_pointer(
    *,
    target_dir: str,
    result_basename: str,
    governance_root: str,
    validated_at: str,
) -> tuple[bool, str, str | None]:
    """Atomically write ``latest-accepted.json`` for one accepted run.

    Sort key is ``(trade_date, finished_at, workflow_run_id)``; the
    pointer is updated only when the candidate is strictly greater than
    the existing on-disk pointer.

    Concurrency: ``fcntl.flock(LOCK_EX)`` on a fixed lock file inside
    ``governance_root`` serializes every accepted-run writer process for
    the duration of the existing-pointer read, candidate comparison,
    temp-file write+fsync, and ``os.replace``.  Holding the lock across
    the whole critical section replaces the older "second read"
    compare-and-set guard — under the lock the second read can only
    ever see the value the lock holder just installed, so an older
    candidate can never overwrite a newer pointer.  The lock is
    released in ``finally`` regardless of outcome, and any leftover
    temp file is removed there too.
    """
    pointer_path = os.path.join(governance_root, _LATEST_POINTER_FILENAME)
    lock_path = os.path.join(governance_root, _LATEST_POINTER_LOCK_FILENAME)

    governed_path = os.path.join(target_dir, _GOVERNED_REPORT_FILENAME)
    manifest_path = os.path.join(target_dir, _MANIFEST_FILENAME)
    archived_result_path = os.path.join(target_dir, result_basename)

    try:
        governed_sha = _hash_file(governed_path)["sha256"]
        manifest_sha = _hash_file(manifest_path)["sha256"]
    except OSError:
        return False, _POINTER_STATUS_IO_ERROR, pointer_path

    finished_at = _resolve_finished_at(
        result_path=archived_result_path,
        fallback=validated_at,
    )

    trade_date_field = _extract_field(governed_path, "trade_date")
    workflow_run_id_field = _extract_field(governed_path, "workflow_run_id")
    candidate_payload: dict[str, Any] = {
        "schema_version": LATEST_POINTER_SCHEMA_VERSION,
        "trade_date": trade_date_field,
        "workflow_run_id": workflow_run_id_field,
        "relative_run_path": (
            f"runs/{trade_date_field}/{workflow_run_id_field}"
        ),
        "governance_status": "accepted",
        "governed_report_sha256": governed_sha,
        "manifest_sha256": manifest_sha,
        "finished_at": finished_at,
        "updated_at": _now_iso(),
    }
    try:
        candidate_key = _pointer_sort_key(candidate_payload)
    except _LatestPointerCorrupt:
        return False, _POINTER_STATUS_IO_ERROR, pointer_path

    try:
        with _pointer_lock(lock_path):
            return _update_latest_pointer_locked(
                governance_root=governance_root,
                pointer_path=pointer_path,
                candidate_payload=candidate_payload,
                candidate_key=candidate_key,
            )
    except OSError:
        return False, _POINTER_STATUS_IO_ERROR, pointer_path


@contextlib.contextmanager
def _pointer_lock(lock_path: str):
    """Hold an exclusive ``fcntl.flock`` on the sentinel file at
    ``lock_path`` for the lifetime of the ``with`` block.  Releases the
    lock and closes the descriptor on exit (even on exception)."""
    # Open without ``with`` because the descriptor must stay open for the
    # duration of the critical section yielded below; ``close`` runs in
    # the surrounding ``finally``.
    lock_fd = open(lock_path, "w")  # noqa: SIM115
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        yield lock_fd
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


def _update_latest_pointer_locked(
    *,
    governance_root: str,
    pointer_path: str,
    candidate_payload: dict[str, Any],
    candidate_key: tuple[str, str, str],
) -> tuple[bool, str, str | None]:
    """Critical section for the latest-accepted pointer update.

    The caller must already hold ``_pointer_lock`` on the sentinel file
    inside ``governance_root``; every accepted-run writer process
    serializes through this lock for the full read → compare → write →
    replace sequence.  Any OSError from the filesystem surfaces as
    ``io_error``; parse failures on the existing pointer surface as
    ``corrupt`` (safety halt, never overwritten).
    """
    tmp_path: str | None = None
    try:
        existing = _read_pointer(governance_root)
    except _LatestPointerCorrupt:
        return False, _POINTER_STATUS_CORRUPT, pointer_path

    if existing is not None:
        try:
            existing_key = _pointer_sort_key(existing)
        except _LatestPointerCorrupt:
            return False, _POINTER_STATUS_CORRUPT, pointer_path
        if not _strictly_greater(candidate_key, existing_key):
            return False, _POINTER_STATUS_SKIPPED, pointer_path

    try:
        payload_bytes = _dump_json_bytes(candidate_payload)
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=governance_root)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload_bytes)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            return False, _POINTER_STATUS_IO_ERROR, pointer_path

        try:
            os.replace(tmp_path, pointer_path)
        except OSError:
            return False, _POINTER_STATUS_IO_ERROR, pointer_path
        tmp_path = None
        return True, _POINTER_STATUS_UPDATED, pointer_path
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                os.remove(tmp_path)


def _read_pointer(governance_root: str) -> dict[str, Any] | None:
    """Read ``latest-accepted.json``; raise :class:`_LatestPointerCorrupt`
    when the file exists but cannot be parsed as a JSON object."""
    pointer_path = os.path.join(governance_root, _LATEST_POINTER_FILENAME)
    if not os.path.isfile(pointer_path):
        return None
    try:
        with open(pointer_path, "rb") as fh:
            payload = json.loads(fh.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _LatestPointerCorrupt(f"failed to parse pointer: {exc}") from exc
    if not isinstance(payload, dict):
        raise _LatestPointerCorrupt("pointer JSON must be an object")
    return payload


def _pointer_sort_key(payload: dict[str, Any]) -> tuple[str, str, str]:
    """Return ``(trade_date, finished_at, workflow_run_id)`` for sorting.

    Raises :class:`_LatestPointerCorrupt` when any required field is
    missing or not a non-empty string; the caller treats that as a
    safety halt that must not overwrite the on-disk pointer.
    """
    trade_date = payload.get("trade_date")
    finished_at = payload.get("finished_at")
    workflow_run_id = payload.get("workflow_run_id")
    if not (isinstance(trade_date, str) and trade_date):
        raise _LatestPointerCorrupt("trade_date missing or invalid")
    if not (isinstance(finished_at, str) and finished_at):
        raise _LatestPointerCorrupt("finished_at missing or invalid")
    if not (isinstance(workflow_run_id, str) and workflow_run_id):
        raise _LatestPointerCorrupt("workflow_run_id missing or invalid")
    return (trade_date, finished_at, workflow_run_id)


def _strictly_greater(candidate: tuple[str, str, str], current: tuple[str, str, str]) -> bool:
    return candidate > current


def _resolve_finished_at(*, result_path: str, fallback: str) -> str:
    """Prefer ``finished_at`` from the archived result JSON; fall back to
    the deterministic ``validated_at`` when the field is missing or
    unparseable so that re-imports do not drift.
    """
    try:
        with open(result_path, "rb") as fh:
            payload = json.loads(fh.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return fallback
    if not isinstance(payload, dict):
        return fallback
    raw = payload.get("finished_at")
    if not isinstance(raw, str) or not raw:
        return fallback
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    return raw


def _extract_field(governed_report_path: str, field_name: str) -> str:
    """Read a required string identity field from governed-quality-report.json.

    Falls back to an empty string when the field is absent so the caller
    surfaces a sort-key corruption error rather than a KeyError.
    """
    try:
        with open(governed_report_path, "rb") as fh:
            payload = json.loads(fh.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    value = payload.get(field_name)
    return value if isinstance(value, str) else ""