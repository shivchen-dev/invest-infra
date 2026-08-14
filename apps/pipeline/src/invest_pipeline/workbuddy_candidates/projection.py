"""Pure symbol resolution and candidate-pool projection helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from invest_pipeline.workbuddy_candidates import CandidateIntakeResult, CandidateItem

Resolver = Callable[[str], str | None]
CandidateKey = tuple[str | None, str | None, str]


@dataclass
class ProjectionResult:
    accepted: list[CandidateItem]
    duplicates: list[CandidateItem]
    needs_symbol_resolution: list[CandidateItem]
    findings: list[dict[str, Any]] = field(default_factory=list)


def project_candidates(
    result: CandidateIntakeResult,
    resolver: Resolver,
    seen_keys: Iterable[CandidateKey] = (),
) -> ProjectionResult:
    """Resolve symbols and de-duplicate candidates without database access."""
    seen = set(seen_keys)
    accepted: list[CandidateItem] = []
    duplicates: list[CandidateItem] = []
    unresolved: list[CandidateItem] = []
    findings = [
        {"scope": "item", "status": item.status, "error": "rejected_by_intake"}
        for item in result.rejected
    ]

    for index, item in enumerate(result.accepted):
        try:
            normalized = resolver(item.symbol or "")
        except Exception as exc:  # resolver is an external seam
            normalized = None
            findings.append(
                {"scope": "item", "index": index, "error": f"symbol resolver failed: {exc}"}
            )
        if not normalized:
            unresolved.append(item)
            findings.append(
                {"scope": "item", "index": index, "error": "symbol needs resolution"}
            )
            continue
        key = (result.trade_date, result.strategy_id, normalized)
        projected = replace(item, symbol=normalized, status="pending_validation")
        if key in seen:
            duplicates.append(projected)
            findings.append({"scope": "item", "index": index, "error": "duplicate candidate"})
            continue
        seen.add(key)
        accepted.append(projected)

    return ProjectionResult(accepted, duplicates, unresolved, findings)


__all__ = ["CandidateKey", "ProjectionResult", "Resolver", "project_candidates"]
