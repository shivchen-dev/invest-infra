"""Shared-directory adapter for WorkBuddy ready packages.

The adapter owns filesystem state transitions only.  Candidate semantics stay
in ``workbuddy_candidates`` and persistence stays behind the Bridge/UoW.
"""

from __future__ import annotations

import json
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
from invest_pipeline.workbuddy_candidates.archive import archive_candidates

_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.ready$")
_MAX_JSON_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SharedDirectoryImport:
    package: str
    result: BridgeImportResult | None
    error: str | None = None


class SharedDirectoryWorkBuddyGateway:
    """Claim and process WorkBuddy packages with atomic directory moves."""

    def __init__(self, bridge_root: str | Path, source_dir: str | Path | None = None) -> None:
        self.root = Path(bridge_root).resolve()
        self.source = (
            Path(source_dir).resolve()
            if source_dir is not None
            else self.root / "选股报告"
        )
        self.inbox = self.root / "workbuddy" / "results"
        self.processing = self.root / "workbuddy" / "processing"
        self.archive = self.root / "workbuddy" / "archive"
        self.failed = self.root / "workbuddy" / "failed"
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

    def process_once(self, *, uow, resolver=None) -> tuple[SharedDirectoryImport, ...]:
        """Claim every package visible at the start and process it once."""
        outcomes: list[SharedDirectoryImport] = []
        for ready_path in self.discover_ready():
            package_name = ready_path.name
            try:
                claimed = self._claim(ready_path)
            except FileNotFoundError:
                continue
            try:
                payload = self._load_payload(claimed)
                normalized = self._normalize_payload(payload)
                archive_outcome = archive_candidates(normalized, str(self.import_archive))
                if archive_outcome.conflict:
                    raise ValueError("archive conflict for workflow run")
                result = import_archived_candidate_run(
                    self.import_archive,
                    trade_date=normalized["trade_date"],
                    workflow_run_id=normalized["workflow_run_id"],
                    uow=uow,
                    resolver=resolver,
                )
                self._finish(claimed, self.archive / package_name.removesuffix(".ready"))
                outcomes.append(SharedDirectoryImport(package_name, result))
            except Exception as exc:
                self._finish(claimed, self.failed / package_name.removesuffix(".ready"))
                outcomes.append(SharedDirectoryImport(package_name, None, str(exc)))
        for candidate_path in self.discover_candidates():
            package_name = candidate_path.name
            try:
                claimed = self._claim_file(candidate_path)
            except FileNotFoundError:
                continue
            try:
                payload = _read_json(claimed)
                result = self._import_payload(payload, uow=uow, resolver=resolver)
                self._finish(claimed, self.archive / package_name)
                outcomes.append(SharedDirectoryImport(package_name, result))
            except Exception as exc:
                self._finish(claimed, self.failed / package_name)
                outcomes.append(SharedDirectoryImport(package_name, None, str(exc)))
        return tuple(outcomes)

    def _import_payload(self, payload: dict[str, Any], *, uow, resolver=None) -> BridgeImportResult:
        normalized = self._normalize_payload(payload)
        archive_outcome = archive_candidates(normalized, str(self.import_archive))
        if archive_outcome.conflict:
            raise ValueError("archive conflict for workflow run")
        return import_archived_candidate_run(
            self.import_archive,
            trade_date=normalized["trade_date"],
            workflow_run_id=normalized["workflow_run_id"],
            uow=uow,
            resolver=resolver,
        )

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


__all__ = ["SharedDirectoryImport", "SharedDirectoryWorkBuddyGateway"]
