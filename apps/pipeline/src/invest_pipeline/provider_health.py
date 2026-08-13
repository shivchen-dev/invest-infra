"""Provider health derivation for DC1-A.

This module turns a :class:`ProviderQualityScore` and the matching
:class:`ProviderDatasetRegistration` into a single, immutable
:class:`ProviderHealthSnapshot`. The function is intentionally tiny
and side-effect free: it never calls the coverage engine, it never
re-derives a quality score, and it never queries a clock. The caller
hands in everything it needs (including the ``as_of`` date) so the
snapshot is reproducible from its arguments alone.

Status priority order (highest first):

1. ``DISABLED``  — the provider is registered but disabled at the
   call site.
2. ``UNKNOWN``   — no coverage evidence is available for the
   provider, i.e. ``freshness_days`` is ``None`` **and**
   ``coverage_ratio`` and ``completeness_ratio`` are both zero.
3. ``STALE``     — the latest evidence is older than the freshness
   SLA (``freshness_status`` is not ``"fresh"``).
4. ``DEGRADED``  — coverage / completeness is below the perfect
   threshold or at least one symbol failed.
5. ``HEALTHY``   — coverage and completeness are both ``1`` and
   freshness is ``"fresh"``.

The derivation never lowers a ``DISABLED`` / ``UNKNOWN`` / ``STALE``
result to ``DEGRADED`` / ``HEALTHY`` even when the underlying
quality ratios look perfect — those higher-precedence statuses
describe the *evidence state* rather than the *quality state* and
must win.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from invest_pipeline.provider_quality import (
    ProviderDatasetRegistration,
    ProviderQualityScore,
)
from invest_pipeline.provider_routing.datasets import Dataset


class ProviderHealthStatus(StrEnum):
    """Coarse-grained provider health status values.

    The string values are the on-the-wire codes consumers (CI gates,
    dashboards, alerting rules) see; they must stay stable so a
    snapshot can be compared across runs without translation.
    """

    UNKNOWN = "unknown"
    DISABLED = "disabled"
    STALE = "stale"
    DEGRADED = "degraded"
    HEALTHY = "healthy"


@dataclass(frozen=True, slots=True)
class ProviderHealthSnapshot:
    """Immutable snapshot of a provider's health for a given dataset.

    ``as_of`` is preserved exactly as the caller passed it so the
    snapshot can be diffed run-to-run without any timezone juggling.
    ``freshness_days`` mirrors the
    :class:`ProviderQualityScore.freshness_days` value (``None`` when
    no coverage evidence is available); the ratios are copied from
    the same source rather than recomputed.
    """

    provider_key: str
    dataset: Dataset
    status: ProviderHealthStatus
    as_of: date
    freshness_days: int | None
    quality_score: Decimal
    coverage_ratio: Decimal
    completeness_ratio: Decimal
    failed_symbols: tuple[str, ...]


def _validated_score(score: object) -> ProviderQualityScore:
    if not isinstance(score, ProviderQualityScore):
        raise ValueError("score must be a ProviderQualityScore")
    return score


def _validated_registration(
    registration: object,
) -> ProviderDatasetRegistration:
    if not isinstance(registration, ProviderDatasetRegistration):
        raise ValueError("registration must be a ProviderDatasetRegistration")
    return registration


def _validated_as_of(as_of: object) -> date:
    if type(as_of) is not date:
        raise ValueError("as_of must be a date")
    return as_of


def _is_no_evidence(score: ProviderQualityScore) -> bool:
    return (
        score.freshness_days is None
        and score.coverage_ratio == 0
        and score.completeness_ratio == 0
    )


def _classify(
    score: ProviderQualityScore,
    *,
    enabled: bool,
) -> ProviderHealthStatus:
    if not enabled:
        return ProviderHealthStatus.DISABLED
    if _is_no_evidence(score):
        return ProviderHealthStatus.UNKNOWN
    if score.freshness_status != "fresh":
        return ProviderHealthStatus.STALE
    if (
        score.coverage_ratio < 1
        or score.completeness_ratio < 1
        or bool(score.failed_symbols)
    ):
        return ProviderHealthStatus.DEGRADED
    return ProviderHealthStatus.HEALTHY


def derive_provider_health(
    score: ProviderQualityScore,
    registration: ProviderDatasetRegistration,
    *,
    enabled: bool,
    as_of: date,
) -> ProviderHealthSnapshot:
    """Derive a frozen :class:`ProviderHealthSnapshot` from a quality score.

    ``score`` and ``registration`` must agree on ``provider_key`` and
    ``dataset``; mismatches raise :class:`ValueError` so a caller
    cannot accidentally mix evidence from two providers into a
    single snapshot. ``enabled`` is a keyword-only flag so the
    intent ("the provider is currently disabled at the call site")
    is explicit at every call site. ``as_of`` is preserved exactly.
    """
    validated_score = _validated_score(score)
    validated_registration = _validated_registration(registration)

    if validated_score.provider_key != validated_registration.provider_key:
        raise ValueError("score and registration must share provider_key")
    if validated_score.dataset is not validated_registration.dataset:
        raise ValueError("score and registration must share dataset")

    validated_as_of = _validated_as_of(as_of)
    status = _classify(validated_score, enabled=enabled)

    return ProviderHealthSnapshot(
        provider_key=validated_score.provider_key,
        dataset=validated_score.dataset,
        status=status,
        as_of=validated_as_of,
        freshness_days=validated_score.freshness_days,
        quality_score=validated_score.quality_score,
        coverage_ratio=validated_score.coverage_ratio,
        completeness_ratio=validated_score.completeness_ratio,
        failed_symbols=validated_score.failed_symbols,
    )


__all__ = [
    "ProviderHealthSnapshot",
    "ProviderHealthStatus",
    "derive_provider_health",
]
