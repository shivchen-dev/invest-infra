from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from invest_domain.research.models import (
    EvidencePack,
    FreshnessStatus,
    QualityStatus,
)


class QualityGateStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class QualityGateResult:
    status: QualityGateStatus
    reasons: tuple[str, ...]


def evaluate_quality_gate(
    pack: EvidencePack | None,
    *,
    instrument_exists: bool = True,
    hash_succeeded: bool = True,
) -> QualityGateResult:
    failed: set[str] = set()
    partial: set[str] = set()
    if not instrument_exists:
        failed.add("instrument_missing")
    if pack is None:
        failed.add("evidence_pack_missing")
        return QualityGateResult(QualityGateStatus.FAILED, tuple(sorted(failed)))
    if not hash_succeeded or len(pack.pack_hash) != 64:
        failed.add("canonical_hash_failed")
    quality = pack.data_quality
    if quality.conflict_detected or quality.quality_status is QualityStatus.CONFLICT:
        failed.add("evidence_conflict")
    if quality.quality_status is QualityStatus.INVALID or quality.invalid_days:
        failed.add("invalid_market_data")
    if quality.valid_price_days == 0 or pack.market_snapshot.latest_close is None:
        failed.add("valid_market_price_missing")
    if quality.freshness_status is FreshnessStatus.FAILED:
        failed.add("freshness_failed")
    if any(not item.item_hash or not item.evidence_id for item in pack.factors):
        failed.add("evidence_identity_missing")
    if failed:
        return QualityGateResult(QualityGateStatus.FAILED, tuple(sorted(failed)))
    completeness = next(
        (
            item.value
            for item in pack.factors
            if item.factor_key == "data_completeness_60d"
        ),
        None,
    )
    if quality.valid_price_days < 60:
        partial.add("fewer_than_60_valid_trading_days")
    if completeness is None or completeness < Decimal("0.90"):
        partial.add("data_completeness_below_0_90")
    if quality.freshness_status is not FreshnessStatus.FRESH:
        partial.add(f"freshness_{quality.freshness_status.value}")
    if quality.quality_status is not QualityStatus.COMPLETE:
        partial.add(f"quality_{quality.quality_status.value}")
    if any(item.quality_status is not QualityStatus.COMPLETE for item in pack.factors):
        partial.add("factor_set_incomplete")
    if pack.candidate_context is None:
        partial.add("candidate_context_missing")
    if partial:
        return QualityGateResult(QualityGateStatus.PARTIAL, tuple(sorted(partial)))
    return QualityGateResult(QualityGateStatus.COMPLETE, ())


__all__ = ["QualityGateResult", "QualityGateStatus", "evaluate_quality_gate"]
