"""Pure parsing and validation for WorkBuddy candidate payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REQUIRED = ("workflow_run_id", "trade_date", "strategy_id", "status", "candidates")


@dataclass
class CandidateItem:
    symbol: str | None
    reason: str | None
    raw: Any
    status: str


@dataclass
class CandidateIntakeResult:
    workflow_run_id: str | None
    trade_date: str | None
    strategy_id: str | None
    status: str
    accepted: list[CandidateItem]
    rejected: list[CandidateItem]
    findings: list[dict[str, Any]]


def parse_candidates_payload(payload: Any) -> CandidateIntakeResult:
    """Parse a WorkBuddy 2.0.0 candidate payload."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    _validate_batch(payload)
    return _extract_items(
        payload["workflow_run_id"],
        payload["trade_date"],
        payload["strategy_id"],
        payload["status"],
        payload["candidates"],
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


def _extract_items(
    workflow_run_id: str,
    trade_date: str,
    strategy_id: str,
    status: str,
    candidates: list[Any],
) -> CandidateIntakeResult:
    accepted: list[CandidateItem] = []
    rejected: list[CandidateItem] = []
    findings: list[dict[str, Any]] = []
    for index, raw in enumerate(candidates):
        if _valid_candidate(raw):
            accepted.append(
                CandidateItem(raw["symbol"], raw["reason"], raw, "needs_symbol_resolution")
            )
        else:
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
    return CandidateIntakeResult(
        workflow_run_id,
        trade_date,
        strategy_id,
        status,
        accepted,
        rejected,
        findings,
    )


def _valid_candidate(raw: Any) -> bool:
    return (
        isinstance(raw, dict)
        and isinstance(raw.get("symbol"), str)
        and bool(raw["symbol"].strip())
        and isinstance(raw.get("reason"), str)
        and bool(raw["reason"].strip())
    )


def _string_field(raw: Any, key: str) -> str | None:
    return raw.get(key) if isinstance(raw, dict) and isinstance(raw.get(key), str) else None


__all__ = [
    "CandidateItem",
    "CandidateIntakeResult",
    "parse_candidates_payload",
    "extract_legacy_candidates",
]
