"""Immutable, atomic archive seam for validated WorkBuddy data bundles."""

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

from invest_domain.strategy import DataRequest

from invest_pipeline.integrations.workbuddy_data_bundle_codec import (
    DataBundleDecodeError,
    DataBundleValidationError,
    ValidatedDataBundle,
    decode_and_validate_data_bundle,
)

MANIFEST_SCHEMA_VERSION = "data-bundle-archive-manifest/1.0"
DATA_BUNDLE_RELATIVE_PATH = "data-bundle.json"
MANIFEST_RELATIVE_PATH = "manifest.json"
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version", "request_id", "definition_key", "definition_version",
        "strategy_key", "strategy_version", "strategy_artifact_hash", "stage",
        "producer", "generated_at", "raw_sha256", "canonical_sha256", "byte_size",
        "data_path",
    }
)


class DataBundleArchiveError(RuntimeError):
    """Base class for sanitized archive failures."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DataBundleArchivePathError(DataBundleArchiveError):
    """The requested destination cannot be used safely."""


class DataBundleArchiveIntegrityError(DataBundleArchiveError):
    """An existing archive is missing, malformed, unsafe, or tampered."""


class DataBundleArchiveConflictError(DataBundleArchiveError):
    """An immutable archive exists for different canonical content."""


class DataBundleArchiveIOError(DataBundleArchiveError):
    """Staging or publication failed."""


@dataclass(frozen=True, slots=True)
class DataBundleArchiveOutcome:
    validated_bundle: ValidatedDataBundle
    archive_uri: str
    run_directory: Path
    manifest_path: Path
    archived_raw_sha256: str
    archived_size_bytes: int
    idempotent: bool


def _path_error() -> DataBundleArchivePathError:
    return DataBundleArchivePathError(
        "unsafe_archive_path", "Data bundle archive destination is unsafe."
    )


def _integrity_error() -> DataBundleArchiveIntegrityError:
    return DataBundleArchiveIntegrityError(
        "archive_integrity_error", "Existing data bundle archive failed integrity validation."
    )


def _io_error() -> DataBundleArchiveIOError:
    return DataBundleArchiveIOError(
        "archive_io_failure", "Data bundle archive could not be published safely."
    )


def _archive_paths(archive_root: str | Path, request_id: str) -> tuple[Path, Path]:
    if not isinstance(archive_root, (str, Path)) or not archive_root:
        raise _path_error() from None
    try:
        supplied = Path(archive_root)
        if ".." in supplied.parts or _REQUEST_ID.fullmatch(request_id) is None:
            raise _path_error() from None
        root = supplied if supplied.is_absolute() else Path.cwd() / supplied
        if root.is_symlink() or not root.is_dir():
            raise _path_error() from None
        runs = root / "runs"
        if runs.is_symlink():
            raise _path_error() from None
        runs.mkdir(mode=0o700, exist_ok=True)
        if not runs.is_dir():
            raise _path_error() from None
        return root, runs
    except DataBundleArchiveError:
        raise
    except (OSError, TypeError, ValueError):
        raise _path_error() from None


def _manifest(request: DataRequest, validated: ValidatedDataBundle, size: int) -> dict[str, Any]:
    bundle = validated.bundle
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "request_id": request.request_id,
        "definition_key": request.definition_key,
        "definition_version": request.definition_version,
        "strategy_key": request.strategy_key,
        "strategy_version": request.strategy_version,
        "strategy_artifact_hash": request.strategy_artifact_hash,
        "stage": request.stage,
        "producer": bundle.producer,
        "generated_at": bundle.generated_at.isoformat(),
        "raw_sha256": validated.raw_sha256,
        "canonical_sha256": validated.canonical_sha256,
        "byte_size": size,
        "data_path": DATA_BUNDLE_RELATIVE_PATH,
    }


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _outcome(
    request: DataRequest,
    validated: ValidatedDataBundle,
    root: Path,
    raw_sha256: str,
    size: int,
    *,
    idempotent: bool,
) -> DataBundleArchiveOutcome:
    final = root / "runs" / request.request_id
    return DataBundleArchiveOutcome(
        validated, f"archive://runs/{request.request_id}", final,
        final / MANIFEST_RELATIVE_PATH, raw_sha256, size, idempotent,
    )


def _read_archive_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise _integrity_error() from None
    try:
        return path.read_bytes()
    except OSError:
        raise _integrity_error() from None


def _inspect_existing(
    request: DataRequest, incoming: ValidatedDataBundle, root: Path
) -> DataBundleArchiveOutcome | None:
    final = root / "runs" / request.request_id
    if not final.exists() and not final.is_symlink():
        return None
    if final.is_symlink() or not final.is_dir():
        raise _integrity_error() from None
    try:
        if {path.name for path in final.iterdir()} != {
            DATA_BUNDLE_RELATIVE_PATH, MANIFEST_RELATIVE_PATH,
        }:
            raise _integrity_error() from None
        raw = _read_archive_file(final / DATA_BUNDLE_RELATIVE_PATH)
        manifest_raw = _read_archive_file(final / MANIFEST_RELATIVE_PATH)
        manifest = json.loads(manifest_raw)
        if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_FIELDS:
            raise _integrity_error() from None
        archived = decode_and_validate_data_bundle(request, raw)
        expected = _manifest(request, archived, len(raw))
        if manifest != expected or manifest_raw != _manifest_bytes(expected):
            raise _integrity_error() from None
        if hashlib.sha256(raw).hexdigest() != manifest["raw_sha256"]:
            raise _integrity_error() from None
    except DataBundleArchiveError:
        raise
    except Exception:
        raise _integrity_error() from None
    if archived.canonical_sha256 != incoming.canonical_sha256:
        raise DataBundleArchiveConflictError(
            "archive_conflict", "A different data bundle is already archived for this request."
        ) from None
    return _outcome(request, archived, root, archived.raw_sha256, len(raw), idempotent=True)


def _archive_data_bundle(
    request: DataRequest, raw_bytes: bytes, archive_root: str | Path
) -> DataBundleArchiveOutcome:
    validated = decode_and_validate_data_bundle(request, raw_bytes)
    root, runs = _archive_paths(archive_root, request.request_id)
    existing = _inspect_existing(request, validated, root)
    if existing is not None:
        return existing
    staging = Path(tempfile.mkdtemp(prefix=".data-bundle-staging-", dir=runs))
    try:
        (staging / DATA_BUNDLE_RELATIVE_PATH).write_bytes(raw_bytes)
        (staging / MANIFEST_RELATIVE_PATH).write_bytes(
            _manifest_bytes(_manifest(request, validated, len(raw_bytes)))
        )
        os.replace(staging, runs / request.request_id)
    except Exception:
        raise _io_error() from None
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return _outcome(
        request, validated, root, validated.raw_sha256, len(raw_bytes), idempotent=False
    )


def archive_data_bundle(
    request: DataRequest, raw_bytes: bytes, archive_root: str | Path
) -> DataBundleArchiveOutcome:
    """Validate and immutably publish one raw DataBundle archive."""

    sanitized_error = None
    try:
        return _archive_data_bundle(request, raw_bytes, archive_root)
    except (DataBundleArchiveConflictError, DataBundleDecodeError, DataBundleValidationError):
        raise
    except DataBundleArchivePathError:
        sanitized_error = _path_error
    except DataBundleArchiveIntegrityError:
        sanitized_error = _integrity_error
    except DataBundleArchiveIOError:
        sanitized_error = _io_error
    except Exception:
        sanitized_error = _io_error
    raise sanitized_error()


__all__ = [
    "DATA_BUNDLE_RELATIVE_PATH", "MANIFEST_RELATIVE_PATH", "MANIFEST_SCHEMA_VERSION",
    "DataBundleArchiveConflictError", "DataBundleArchiveError", "DataBundleArchiveIOError",
    "DataBundleArchiveIntegrityError", "DataBundleArchiveOutcome", "DataBundleArchivePathError",
    "archive_data_bundle",
]
