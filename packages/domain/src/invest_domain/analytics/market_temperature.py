from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import UUID

from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)
from invest_domain.research.models import FactorObservation, FreshnessStatus, QualityStatus

REQUIRED_FACTOR_KEYS: tuple[str, ...] = (
    "return_20d",
    "realized_volatility_20d",
    "avg_turnover_amount_20d",
    "max_drawdown_60d",
)
_OUTPUTS: tuple[str, ...] = (
    "market_temperature_score",
    "market_temperature_state",
    "market_temperature_breadth_score",
    "market_temperature_momentum_score",
    "market_temperature_liquidity_score",
    "market_temperature_risk_score",
)
_QUANTUM = Decimal("0.00000001")

LIQUIDITY_NORMALIZER_VERSION: str = "1.0.0"
LIQUIDITY_SCALE: Decimal = Decimal("100000000")


def build_market_temperature(
    *,
    input_snapshot_id: UUID | str,
    factor_observations: Iterable[FactorObservation],
    as_of_date: date,
    algorithm_version: str = "1.0.0",
) -> MarketObservationSnapshot:
    observations = tuple(factor_observations)
    invalid, reason, freshness = _validate(observations, as_of_date)
    if invalid:
        values: dict[str, Decimal | str | None] = {key: None for key in _OUTPUTS}
        quality = QualityStatus.INVALID
        freshness_status = (
            freshness if freshness is FreshnessStatus.STALE else FreshnessStatus.FAILED
        )
    else:
        grouped = _group_by_key(observations)
        breadth = _clip(_mean(grouped["return_20d"]))
        momentum = _clip(
            (
                _mean(grouped["return_20d"])
                + _mean(grouped["max_drawdown_60d"])
                + Decimal(1)
            )
            / Decimal(2)
        )
        liquidity = _clip(_liquidity_score(_mean(grouped["avg_turnover_amount_20d"])))
        risk = _clip(Decimal(1) - _mean(grouped["realized_volatility_20d"]))
        score = _clip((breadth + momentum + liquidity + risk) / Decimal(4))
        values = {
            "market_temperature_score": score,
            "market_temperature_state": _state(score),
            "market_temperature_breadth_score": breadth,
            "market_temperature_momentum_score": momentum,
            "market_temperature_liquidity_score": liquidity,
            "market_temperature_risk_score": risk,
        }
        quality = QualityStatus.COMPLETE
        freshness_status = FreshnessStatus.FRESH
    result = tuple(
        MarketObservation(
            observation_key=key,
            value=values[key],
            unit="state" if key.endswith("state") else "score",
            observed_date=as_of_date,
            source_kind="analytics",
            source_ref=f"market_temperature:{algorithm_version}",
            quality_status=quality,
        )
        for key in _OUTPUTS
    )
    return MarketObservationSnapshot(
        input_snapshot_id=input_snapshot_id,
        as_of_date=as_of_date,
        observations=result,
        algorithm_version=algorithm_version,
        quality_status=quality,
        freshness_status=freshness_status,
    )


def _validate(
    observations: tuple[FactorObservation, ...],
    as_of_date: date,
) -> tuple[bool, str, FreshnessStatus]:
    if not observations:
        return True, "no_factor_observations", FreshnessStatus.FAILED
    date_mismatch = any(item.observed_date != as_of_date for item in observations)
    if date_mismatch:
        return True, "observed_date_mismatch", FreshnessStatus.STALE
    if any(item.quality_status is not QualityStatus.COMPLETE for item in observations):
        return True, "non_complete_quality", FreshnessStatus.FAILED
    if any(item.value is None for item in observations):
        return True, "none_value", FreshnessStatus.FAILED
    per_instrument: dict[object, list[FactorObservation]] = defaultdict(list)
    for item in observations:
        per_instrument[item.instrument_id].append(item)
    for _instrument_id, items in per_instrument.items():
        keys = [item.factor_key for item in items]
        if len(set(keys)) != len(keys):
            return True, "duplicate_factor_key_for_instrument", FreshnessStatus.FAILED
        if set(keys) != set(REQUIRED_FACTOR_KEYS):
            return True, "missing_or_extra_factor_key_for_instrument", FreshnessStatus.FAILED
    return False, "", FreshnessStatus.FRESH


def _group_by_key(observations: tuple[FactorObservation, ...]) -> dict[str, list[Decimal]]:
    grouped: dict[str, list[Decimal]] = {key: [] for key in REQUIRED_FACTOR_KEYS}
    for item in observations:
        grouped[item.factor_key].append(item.value)  # type: ignore[arg-type]
    return grouped


def _liquidity_score(amount: Decimal) -> Decimal:
    return amount / LIQUIDITY_SCALE


def _mean(values: list[Decimal] | list[Decimal | None]) -> Decimal:
    present = [value for value in values if value is not None]
    return sum(present, Decimal(0)) / Decimal(len(present)) if present else Decimal(0)


def _clip(value: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(1), value)).quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


def _state(score: Decimal) -> str:
    if score < Decimal("0.33"):
        return "cold"
    if score < Decimal("0.67"):
        return "neutral"
    return "hot"
