"""Pure parsing and validation for WorkBuddy candidate payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED = ("workflow_run_id", "trade_date", "strategy_id", "status", "candidates")
_LINEAGE_SCHEMA_VERSION = "candidate-lineage/1.0"
_SECTOR_STAGE_KEY = "sector_selection"
_STOCK_STAGE_KEY = "stock_screening"


@dataclass
class CandidateItem:
    symbol: str | None
    reason: str | None
    raw: Any
    status: str


@dataclass(frozen=True)
class LineageStage:
    stage_key: str
    stage_result_id: str
    stage_result_sha256: str
    strategy_key: str
    strategy_version: str
    strategy_artifact_hash: str
    as_of: str
    constituent_snapshot_sha256: str | None = None
    upstream_stage_result_id: str | None = None
    upstream_stage_result_sha256: str | None = None


@dataclass(frozen=True)
class CandidateLineage:
    schema_version: str
    stages: tuple[LineageStage, ...]

    @property
    def sector_selection(self) -> LineageStage:
        return self.stages[0]

    @property
    def stock_screening(self) -> LineageStage:
        return self.stages[1]


@dataclass
class CandidateIntakeResult:
    workflow_run_id: str | None
    trade_date: str | None
    strategy_id: str | None
    status: str
    accepted: list[CandidateItem]
    rejected: list[CandidateItem]
    findings: list[dict[str, Any]]
    lineage: CandidateLineage | None = None


def parse_candidates_payload(payload: Any) -> CandidateIntakeResult:
    """Parse a WorkBuddy 2.0.0 candidate payload.

    When the optional top-level ``lineage`` object is present it is validated
    against the two-stage ``candidate-lineage/1.0`` contract; otherwise the
    legacy read path is preserved with ``lineage=None``.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    _validate_batch(payload)
    lineage = _parse_lineage(payload)
    return _extract_items(
        payload["workflow_run_id"],
        payload["trade_date"],
        payload["strategy_id"],
        payload["status"],
        payload["candidates"],
        lineage,
    )


def extract_legacy_candidates(result_payload: Any) -> CandidateIntakeResult:
    """Extract candidates without requiring legacy report fields."""
    if not isinstance(result_payload, dict):
        raise ValueError("legacy result must be an object")
    if "candidates" not in result_payload or not isinstance(result_payload["candidates"], list):
        raise ValueError("legacy result candidates must be a list")
    workflow_run_id = result_payload.get("workflow_run_id")
    trade_date = result_payload.get("trade_date")
    strategy_id = result_payload.get("strategy_id", result_payload.get("strategy_version"))
    _validate_identity(workflow_run_id, trade_date, strategy_id, "legacy_extracted")
    return _extract_items(
        workflow_run_id,
        trade_date,
        strategy_id,
        "legacy_extracted",
        result_payload["candidates"],
        None,
    )


def _validate_batch(payload: dict[str, Any]) -> None:
    missing = [key for key in _REQUIRED if key not in payload]
    if missing:
        raise ValueError(f"missing field: {missing[0]}")
    _validate_identity(
        payload["workflow_run_id"],
        payload["trade_date"],
        payload["strategy_id"],
        payload["status"],
    )
    if not isinstance(payload["candidates"], list):
        raise ValueError("candidates must be a list")


def _validate_identity(
    workflow_run_id: Any,
    trade_date: Any,
    strategy_id: Any,
    status: Any,
) -> None:
    if not isinstance(workflow_run_id, str) or not _RUN_ID.fullmatch(workflow_run_id):
        raise ValueError("workflow_run_id must be a safe single path segment")
    if not isinstance(trade_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", trade_date):
        raise ValueError("trade_date must be YYYY-MM-DD")
    try:
        date.fromisoformat(trade_date)
    except ValueError as exc:
        raise ValueError("trade_date must be a real YYYY-MM-DD") from exc
    if not isinstance(strategy_id, str) or not isinstance(status, str):
        raise ValueError("identity fields must be strings")


def _parse_lineage(payload: dict[str, Any]) -> CandidateLineage | None:
    lineage = payload.get("lineage")
    if lineage is None:
        return None
    if not isinstance(lineage, dict):
        raise ValueError("invalid_lineage_shape")
    if lineage.get("schema_version") != _LINEAGE_SCHEMA_VERSION:
        raise ValueError("invalid_lineage_shape")
    stages = lineage.get("stages")
    if not isinstance(stages, list) or len(stages) != 2:
        raise ValueError("invalid_lineage_shape")

    sector = _parse_stage(stages[0], _SECTOR_STAGE_KEY)
    stock = _parse_stage(stages[1], _STOCK_STAGE_KEY)
    if stock.upstream_stage_result_id != sector.stage_result_id:
        raise ValueError("upstream_binding_mismatch")
    if stock.upstream_stage_result_sha256 != sector.stage_result_sha256:
        raise ValueError("upstream_binding_mismatch")
    if sector.as_of != stock.as_of:
        raise ValueError("as_of_mismatch")

    return CandidateLineage(
        schema_version=_LINEAGE_SCHEMA_VERSION,
        stages=(sector, stock),
    )


def _parse_stage(stage: Any, expected_key: str) -> LineageStage:
    if not isinstance(stage, dict):
        raise ValueError("invalid_lineage_shape")
    if stage.get("stage_key") != expected_key:
        raise ValueError("invalid_stage_order")

    stage_result_id = stage.get("stage_result_id")
    if not isinstance(stage_result_id, str) or not _RUN_ID.fullmatch(stage_result_id):
        raise ValueError("strategy_identity_mismatch")

    for key in ("strategy_key", "strategy_version", "as_of"):
        value = stage.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError("strategy_identity_mismatch")
    for key in ("stage_result_sha256", "strategy_artifact_hash"):
        value = stage.get(key)
        if not isinstance(value, str) or not _HEX64.fullmatch(value):
            raise ValueError("strategy_identity_mismatch")

    if expected_key == _SECTOR_STAGE_KEY:
        constituent = stage.get("constituent_snapshot_sha256")
        if not isinstance(constituent, str) or not _HEX64.fullmatch(constituent):
            raise ValueError("strategy_identity_mismatch")
        return LineageStage(
            stage_key=stage["stage_key"],
            stage_result_id=stage_result_id,
            stage_result_sha256=stage["stage_result_sha256"],
            strategy_key=stage["strategy_key"],
            strategy_version=stage["strategy_version"],
            strategy_artifact_hash=stage["strategy_artifact_hash"],
            as_of=stage["as_of"],
            constituent_snapshot_sha256=constituent,
        )

    upstream_id = stage.get("upstream_stage_result_id")
    if not isinstance(upstream_id, str) or not _RUN_ID.fullmatch(upstream_id):
        raise ValueError("upstream_binding_mismatch")
    upstream_sha = stage.get("upstream_stage_result_sha256")
    if not isinstance(upstream_sha, str) or not _HEX64.fullmatch(upstream_sha):
        raise ValueError("upstream_binding_mismatch")
    return LineageStage(
        stage_key=stage["stage_key"],
        stage_result_id=stage_result_id,
        stage_result_sha256=stage["stage_result_sha256"],
        strategy_key=stage["strategy_key"],
        strategy_version=stage["strategy_version"],
        strategy_artifact_hash=stage["strategy_artifact_hash"],
        as_of=stage["as_of"],
        upstream_stage_result_id=upstream_id,
        upstream_stage_result_sha256=upstream_sha,
    )


def _extract_items(
    workflow_run_id: str,
    trade_date: str,
    strategy_id: str,
    status: str,
    candidates: list[Any],
    lineage: CandidateLineage | None,
) -> CandidateIntakeResult:
    accepted: list[CandidateItem] = []
    rejected: list[CandidateItem] = []
    findings: list[dict[str, Any]] = []
    terminal_stage = lineage.stock_screening if lineage is not None else None
    for index, raw in enumerate(candidates):
        if not _valid_candidate(raw):
            rejected.append(
                CandidateItem(
                    _string_field(raw, "symbol"), _string_field(raw, "reason"), raw, "rejected"
                )
            )
            findings.append({
                "scope": "item",
                "index": index,
                "error": "symbol and reason must be non-empty strings",
            })
            continue
        if terminal_stage is not None and not _matches_terminal(raw, terminal_stage):
            rejected.append(
                CandidateItem(raw["symbol"], raw["reason"], raw, "rejected")
            )
            findings.append({
                "scope": "item",
                "index": index,
                "error": "candidate_terminal_mismatch",
            })
            continue
        accepted.append(
            CandidateItem(raw["symbol"], raw["reason"], raw, "needs_symbol_resolution")
        )
    return CandidateIntakeResult(
        workflow_run_id,
        trade_date,
        strategy_id,
        status,
        accepted,
        rejected,
        findings,
        lineage,
    )


def _valid_candidate(raw: Any) -> bool:
    return (
        isinstance(raw, dict)
        and isinstance(raw.get("symbol"), str)
        and bool(raw["symbol"].strip())
        and isinstance(raw.get("reason"), str)
        and bool(raw["reason"].strip())
    )


def _matches_terminal(raw: dict[str, Any], terminal_stage: LineageStage) -> bool:
    return (
        raw.get("terminal_stage_result_id") == terminal_stage.stage_result_id
        and raw.get("terminal_stage_result_sha256") == terminal_stage.stage_result_sha256
    )


def _string_field(raw: Any, key: str) -> str | None:
    return raw.get(key) if isinstance(raw, dict) and isinstance(raw.get(key), str) else None


__all__ = [
    "CandidateItem",
    "CandidateIntakeResult",
    "CandidateLineage",
    "LineageStage",
    "parse_candidates_payload",
    "extract_legacy_candidates",
]
