"""Shared-directory adapter for WorkBuddy ready packages.

The adapter owns filesystem state transitions only.  Candidate semantics stay
in ``workbuddy_candidates`` and persistence stays behind the Bridge/UoW.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from invest_pipeline.integrations.bridge_ingestor import (
    BridgeImportResult,
    import_archived_candidate_run,
)
from invest_pipeline.workbuddy_candidates import extract_legacy_candidates
from invest_pipeline.workbuddy_candidates.archive import (
    ArchiveOutcome,
    archive_candidates,
)

_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.ready$")
_PROCESSING_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_JSON_BYTES = 16 * 1024 * 1024
_LOGGER = logging.getLogger(__name__)


class ArchiveConflictError(Exception):
    """Raised when an archive for a workflow run already exists with different bytes.

    Carries the run identity and archive URI so callers can route the package
    into a dedicated ``conflict/`` bucket distinct from generic failures.
    """

    def __init__(
        self,
        *,
        workflow_run_id: str,
        trade_date: str,
        archive_uri: str,
    ) -> None:
        super().__init__(
            "archive conflict for workflow_run_id="
            f"{workflow_run_id} trade_date={trade_date} archive_uri={archive_uri}"
        )
        self.workflow_run_id = workflow_run_id
        self.trade_date = trade_date
        self.archive_uri = archive_uri


@dataclass(frozen=True, slots=True)
class SharedDirectoryImport:
    package: str
    result: BridgeImportResult | None
    error: str | None = None
    archive_uri: str | None = None
    accepted_count: int | None = None
    rejected_count: int | None = None
    needs_symbol_resolution_count: int | None = None
    findings: tuple[dict[str, Any], ...] = ()
    archive_idempotent: bool | None = None
    import_idempotent: bool | None = None
    conflict: bool | None = None


class SharedDirectoryWorkBuddyGateway:
    """Claim and process WorkBuddy packages with atomic directory moves."""

    def __init__(self, bridge_root: str | Path, source_dir: str | Path | None = None) -> None:
        self.root = Path(bridge_root).resolve()
        self.source = (
            Path(source_dir).resolve()
            if source_dir is not None
            else self.root / "candidate" / "results"
        )
        self.inbox = self.root / "candidate" / "results"
        self.processing = self.root / "candidate" / "processing"
        self.archive = self.root / "candidate" / "archive"
        self.failed = self.root / "candidate" / "failed"
        self.conflict = self.root / "candidate" / "conflict"
        self.import_archive = self.root / "invest-infra" / "archive"

    def discover_ready(self) -> tuple[Path, ...]:
        """Return ready package directories in deterministic order."""
        if not self.inbox.is_dir():
            return ()
        return tuple(
            path
            for path in sorted(self.inbox.iterdir(), key=lambda item: item.name)
            if path.is_dir() and _PACKAGE_RE.fullmatch(path.name)
        )

    def discover_candidates(self) -> tuple[Path, ...]:
        """Return flat candidate JSON files in deterministic order."""
        if not self.source.is_dir():
            return ()
        return tuple(sorted(self.source.glob("candidates_*.json"), key=lambda item: item.name))

    def discover_processing(self) -> tuple[Path, ...]:
        """Return safe direct children left after an interrupted claim."""
        if not self.processing.is_dir():
            return ()
        return tuple(
            path
            for path in sorted(self.processing.iterdir(), key=lambda item: item.name)
            if (
                _PROCESSING_RE.fullmatch(path.name)
                and not path.name.endswith(".tmp")
                and (path.is_dir() or path.is_file())
            )
        )

    def process_once(self, *, uow, resolver=None) -> tuple[SharedDirectoryImport, ...]:
        """Claim every package visible at the start and process it once."""
        _LOGGER.info("workbuddy_event", extra={"event": "scan_started", "mode": "normal"})
        outcomes: list[SharedDirectoryImport] = []
        for ready_path in self.discover_ready():
            package_name = ready_path.name
            try:
                claimed = self._claim(ready_path)
            except FileNotFoundError:
                continue
            outcomes.append(
                self._process_claimed(
                    claimed,
                    package_name,
                    ready_kind=True,
                    uow=uow,
                    resolver=resolver,
                )
            )
        for candidate_path in self.discover_candidates():
            package_name = candidate_path.name
            try:
                claimed = self._claim_file(candidate_path)
            except FileNotFoundError:
                continue
            outcomes.append(
                self._process_claimed(
                    claimed,
                    package_name,
                    ready_kind=False,
                    uow=uow,
                    resolver=resolver,
                )
            )
        return tuple(outcomes)

    def recover_once(self, *, uow, resolver=None) -> tuple[SharedDirectoryImport, ...]:
        """Resume packages already claimed into ``processing/``."""
        _LOGGER.info("workbuddy_event", extra={"event": "scan_started", "mode": "recovery"})
        outcomes: list[SharedDirectoryImport] = []
        for claimed in self.discover_processing():
            ready_kind = claimed.is_dir()
            package_name = f"{claimed.name}.ready" if ready_kind else claimed.name
            outcomes.append(
                self._process_claimed(
                    claimed,
                    package_name,
                    ready_kind=ready_kind,
                    uow=uow,
                    resolver=resolver,
                )
            )
        _LOGGER.info(
            "workbuddy_event",
            extra={"event": "scan_finished", "mode": "recovery", "count": len(outcomes)},
        )
        return tuple(outcomes)

    def _process_claimed(
        self,
        claimed: Path,
        package_name: str,
        *,
        ready_kind: bool,
        uow,
        resolver,
    ) -> SharedDirectoryImport:
        base = package_name.removesuffix(".ready") if ready_kind else package_name
        archive_target = self.archive / base
        conflict_target = self.conflict / base
        failed_target = self.failed / base
        try:
            payload = self._load_payload(claimed) if ready_kind else _read_json(claimed)
            normalized = self._normalize_payload(payload)
            archive_outcome = archive_candidates(normalized, str(self.import_archive))
            if archive_outcome.conflict:
                raise ArchiveConflictError(
                    workflow_run_id=normalized["workflow_run_id"],
                    trade_date=normalized["trade_date"],
                    archive_uri=archive_outcome.archive_uri,
                )
            result = import_archived_candidate_run(
                self.import_archive,
                trade_date=normalized["trade_date"],
                workflow_run_id=normalized["workflow_run_id"],
                uow=uow,
                resolver=resolver,
            )
            self._finish(claimed, archive_target)
            _LOGGER.info(
                "workbuddy_event",
                extra={
                    "event": "package_finished",
                    "package": package_name,
                    "status": "success",
                },
            )
            return _build_success(package_name, archive_outcome, result)
        except ArchiveConflictError as exc:
            self._finish(claimed, conflict_target)
            _LOGGER.warning(
                "workbuddy_event",
                extra={
                    "event": "package_finished",
                    "package": package_name,
                    "status": "conflict",
                },
            )
            return _build_conflict(package_name, exc, archive_outcome)
        except Exception as exc:
            self._finish(claimed, failed_target)
            _LOGGER.error(
                "workbuddy_event",
                extra={
                    "event": "package_finished",
                    "package": package_name,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            return SharedDirectoryImport(package=package_name, result=None, error=str(exc))

    def _claim(self, ready_path: Path) -> Path:
        self.processing.mkdir(parents=True, exist_ok=True)
        target = self.processing / ready_path.name.removesuffix(".ready")
        os.replace(ready_path, target)
        return target

    def _claim_file(self, candidate_path: Path) -> Path:
        self.processing.mkdir(parents=True, exist_ok=True)
        target = self.processing / candidate_path.name
        os.replace(candidate_path, target)
        return target

    def _finish(self, claimed: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(f"destination package already exists: {target}")
        os.replace(claimed, target)

    def _load_payload(self, package: Path) -> dict[str, Any]:
        candidates = package / "candidates.json"
        if candidates.is_file():
            return _read_json(candidates)
        legacy_files = sorted(
            (*package.glob("sector_result*.json"), *package.glob("result*.json")),
            key=lambda item: item.name,
        )
        if not legacy_files:
            raise ValueError("ready package has no candidates.json or legacy result JSON")
        return _read_json(legacy_files[0])

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = {"workflow_run_id", "trade_date", "strategy_id", "status", "candidates"}
        if required <= payload.keys():
            return payload
        extracted = extract_legacy_candidates(payload)
        return {
            "workflow_run_id": extracted.workflow_run_id,
            "trade_date": extracted.trade_date,
            "strategy_id": extracted.strategy_id,
            "status": extracted.status,
            "candidates": [item.raw for item in (*extracted.accepted, *extracted.rejected)],
        }


def _build_success(
    package_name: str,
    archive_outcome: ArchiveOutcome,
    result: BridgeImportResult,
) -> SharedDirectoryImport:
    return SharedDirectoryImport(
        package=package_name,
        result=result,
        error=None,
        archive_uri=archive_outcome.archive_uri,
        accepted_count=archive_outcome.accepted_count,
        rejected_count=archive_outcome.rejected_count,
        needs_symbol_resolution_count=_count_needs_symbol_resolution(result),
        findings=tuple(result.findings),
        archive_idempotent=archive_outcome.idempotent,
        import_idempotent=result.idempotent,
        conflict=False,
    )


def _build_conflict(
    package_name: str,
    exc: ArchiveConflictError,
    archive_outcome: ArchiveOutcome,
) -> SharedDirectoryImport:
    return SharedDirectoryImport(
        package=package_name,
        result=None,
        error=str(exc),
        archive_uri=exc.archive_uri,
        accepted_count=archive_outcome.accepted_count,
        rejected_count=archive_outcome.rejected_count,
        findings=tuple(archive_outcome.findings),
        archive_idempotent=archive_outcome.idempotent,
        import_idempotent=None,
        conflict=True,
    )


def _count_needs_symbol_resolution(result: BridgeImportResult) -> int:
    return sum(
        1
        for observation in result.observations
        if observation.metadata.get("candidate_status") == "needs_symbol_resolution"
    )


def _read_json(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if resolved.parent != path.parent.resolve():
        raise ValueError("package file escapes package directory")
    size = resolved.stat().st_size
    if size > _MAX_JSON_BYTES:
        raise ValueError("package JSON exceeds maximum size")
    value = json.loads(resolved.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


__all__ = [
    "ArchiveConflictError",
    "SharedDirectoryImport",
    "SharedDirectoryWorkBuddyGateway",
]
