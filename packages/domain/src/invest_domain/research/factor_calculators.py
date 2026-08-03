from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from typing import Sequence

from invest_domain.instruments import InstrumentId
from invest_domain.market_data import DailyBar, TradingStatus
from invest_domain.research.factor_set import FACTOR_DEFINITIONS, factor_definition
from invest_domain.research.models import (
    DataQuality,
    FactorObservation,
    FreshnessStatus,
    MarketSnapshot,
    QualityStatus,
)

_FACTOR_QUANTUM = Decimal("0.00000001")


@dataclass(frozen=True, slots=True)
class FactorCalculationResult:
    factors: tuple[FactorObservation, ...]
    market_snapshot: MarketSnapshot
    data_quality: DataQuality
    missing_fields: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _BarValue:
    trade_date: date
    close: Decimal | None
    amount: Decimal | None
    suspended: bool
    invalid: bool


def calculate_market_state_factors(
    bars: Sequence[DailyBar],
    *,
    as_of_date: date,
    instrument_id: InstrumentId | None = None,
) -> FactorCalculationResult:
    resolved_instrument_id = _resolve_instrument_id(bars, instrument_id)
    rows, conflicts = _normalize_bars(bars, as_of_date)
    valid_closes = [row.close for row in rows if row.close is not None and not row.invalid]
    valid_amounts = [row.amount for row in rows if row.amount is not None and not row.invalid]
    close_values = [value for value in valid_closes if value is not None]
    amount_values = [value for value in valid_amounts if value is not None]
    latest_row = rows[-1] if rows else None
    invalid_days = sum(row.invalid for row in rows)
    suspended_days = sum(row.suspended for row in rows)
    completeness_rows = rows[-60:]
    complete_prices = sum(
        row.close is not None and not row.invalid for row in completeness_rows
    )
    completeness = _round(Decimal(complete_prices) / Decimal(60))

    values: dict[str, Decimal | None] = {
        "return_20d": _return(close_values, 20),
        "return_60d": _return(close_values, 60),
        "distance_ma20": _distance_ma(close_values, 20),
        "distance_ma60": _distance_ma(close_values, 60),
        "realized_volatility_20d": _realized_volatility(close_values, 20),
        "max_drawdown_60d": _max_drawdown(close_values, 60),
        "avg_turnover_amount_20d": _average(amount_values, 20),
        "data_completeness_60d": completeness,
    }
    factors = tuple(
        FactorObservation(
            factor_key=definition.key,
            instrument_id=resolved_instrument_id,
            value=values[definition.key],
            unit=definition.unit,
            window=definition.window,
            observed_date=as_of_date,
            quality_status=_factor_quality(
                definition.key,
                values[definition.key],
                len(close_values),
                len(amount_values),
                invalid_days,
                conflicts,
            ),
        )
        for definition in FACTOR_DEFINITIONS
    )
    missing_fields = tuple(
        sorted(
            f"factor.{factor.factor_key}"
            for factor in factors
            if factor.value is None
        )
    )
    warnings = _warnings(rows, invalid_days, suspended_days, conflicts, amount_values)
    freshness = _freshness(latest_row, as_of_date)
    quality = _aggregate_quality(
        factors, complete_prices, invalid_days, suspended_days, conflicts
    )
    data_quality = DataQuality(
        freshness_status=freshness,
        quality_status=quality,
        target_trading_days=60,
        observed_trading_days=len(rows),
        valid_price_days=len(close_values),
        invalid_days=invalid_days,
        suspended_days=suspended_days,
        conflict_detected=conflicts,
    )
    latest_valid = next(
        (row for row in reversed(rows) if row.close is not None and not row.invalid),
        None,
    )
    snapshot = MarketSnapshot(
        latest_trade_date=None if latest_valid is None else latest_valid.trade_date,
        latest_close=None if latest_valid is None else latest_valid.close,
        currency="CNY",
        observed_trading_days=len(rows),
        valid_price_days=len(close_values),
        suspended_days=suspended_days,
    )
    return FactorCalculationResult(
        factors=factors,
        market_snapshot=snapshot,
        data_quality=data_quality,
        missing_fields=missing_fields,
        warnings=warnings,
    )


def _resolve_instrument_id(
    bars: Sequence[DailyBar], instrument_id: InstrumentId | None
) -> InstrumentId:
    identities = {bar.instrument_id for bar in bars}
    if len(identities) > 1:
        raise ValueError("all DailyBar inputs must identify the same instrument")
    inferred = next(iter(identities), None)
    if instrument_id is not None and inferred is not None and instrument_id != inferred:
        raise ValueError("instrument_id does not match DailyBar inputs")
    resolved = instrument_id or inferred
    if not isinstance(resolved, InstrumentId):
        raise ValueError("instrument_id is required when bars are empty")
    return resolved


def _normalize_bars(
    bars: Sequence[DailyBar], as_of_date: date
) -> tuple[list[_BarValue], bool]:
    by_date: dict[date, list[DailyBar]] = {}
    for bar in bars:
        if bar.trade_date > as_of_date:
            raise ValueError("DailyBar inputs must not include future trade dates")
        by_date.setdefault(bar.trade_date, []).append(bar)
    rows: list[_BarValue] = []
    conflict = False
    for trade_date in sorted(by_date):
        candidates = by_date[trade_date]
        revision = max(getattr(bar, "revision", 1) for bar in candidates)
        latest = [bar for bar in candidates if getattr(bar, "revision", 1) == revision]
        hashes = {getattr(bar, "row_hash", None) for bar in latest}
        if len(hashes) > 1:
            conflict = True
        bar = sorted(latest, key=lambda item: str(getattr(item, "row_hash", "")))[-1]
        suspended = getattr(bar, "trading_status", None) is TradingStatus.SUSPENDED
        close = getattr(bar, "close", None)
        amount = getattr(bar, "amount", None)
        invalid = not suspended and not _positive_decimal(close)
        if amount is not None and not _non_negative_decimal(amount):
            invalid = True
            amount = None
        rows.append(
            _BarValue(
                trade_date=trade_date,
                close=close if _positive_decimal(close) else None,
                amount=amount if _non_negative_decimal(amount) else None,
                suspended=suspended,
                invalid=invalid,
            )
        )
    return rows, conflict


def _return(closes: list[Decimal], window: int) -> Decimal | None:
    if len(closes) < window + 1:
        return None
    return _round(closes[-1] / closes[-(window + 1)] - Decimal(1))


def _distance_ma(closes: list[Decimal], window: int) -> Decimal | None:
    if len(closes) < window:
        return None
    selected = closes[-window:]
    average = sum(selected, Decimal(0)) / Decimal(window)
    return _round(selected[-1] / average - Decimal(1))


def _realized_volatility(closes: list[Decimal], window: int) -> Decimal | None:
    if len(closes) < window + 1:
        return None
    selected = closes[-(window + 1) :]
    returns = [selected[index] / selected[index - 1] - Decimal(1) for index in range(1, len(selected))]
    mean = sum(returns, Decimal(0)) / Decimal(window)
    variance = sum((value - mean) ** 2 for value in returns) / Decimal(window)
    with localcontext() as context:
        context.prec = 50
        annualized = variance.sqrt() * Decimal(252).sqrt()
    return _round(annualized)


def _max_drawdown(closes: list[Decimal], window: int) -> Decimal | None:
    if len(closes) < window:
        return None
    peak = closes[-window]
    drawdown = Decimal(0)
    for close in closes[-window:]:
        peak = max(peak, close)
        drawdown = min(drawdown, close / peak - Decimal(1))
    return _round(drawdown)


def _average(values: list[Decimal], window: int) -> Decimal | None:
    if len(values) < window:
        return None
    return _round(sum(values[-window:], Decimal(0)) / Decimal(window))


def _round(value: Decimal) -> Decimal:
    return value.quantize(_FACTOR_QUANTUM, rounding=ROUND_HALF_EVEN)


def _factor_quality(
    key: str,
    value: Decimal | None,
    close_count: int,
    amount_count: int,
    invalid_days: int,
    conflict: bool,
) -> QualityStatus:
    if conflict:
        return QualityStatus.CONFLICT
    if value is not None:
        return QualityStatus.COMPLETE
    definition = factor_definition(key)
    available = amount_count if definition.required_amounts else close_count
    required = definition.required_amounts or definition.required_closes
    if invalid_days:
        return QualityStatus.INVALID
    return QualityStatus.MISSING if available == 0 else QualityStatus.PARTIAL


def _aggregate_quality(
    factors: tuple[FactorObservation, ...],
    complete_prices: int,
    invalid_days: int,
    suspended_days: int,
    conflict: bool,
) -> QualityStatus:
    if conflict:
        return QualityStatus.CONFLICT
    if invalid_days:
        return QualityStatus.INVALID
    if not complete_prices:
        return QualityStatus.MISSING
    if (
        complete_prices >= 54
        and not suspended_days
        and all(item.quality_status is QualityStatus.COMPLETE for item in factors)
    ):
        return QualityStatus.COMPLETE
    return QualityStatus.PARTIAL


def _freshness(row: _BarValue | None, as_of_date: date) -> FreshnessStatus:
    if row is None:
        return FreshnessStatus.MISSING
    if row.trade_date < as_of_date:
        return FreshnessStatus.STALE
    if row.invalid:
        return FreshnessStatus.FAILED
    if row.suspended:
        return FreshnessStatus.PARTIAL
    return FreshnessStatus.FRESH


def _warnings(
    rows: list[_BarValue],
    invalid_days: int,
    suspended_days: int,
    conflict: bool,
    amounts: list[Decimal],
) -> tuple[str, ...]:
    warnings: set[str] = set()
    if len(rows) < 60:
        warnings.add("fewer_than_60_observed_trading_days")
    if invalid_days:
        warnings.add("invalid_daily_bar_data")
    if suspended_days:
        warnings.add("suspended_trading_days_present")
    if conflict:
        warnings.add("conflicting_daily_bar_revisions")
    if len(amounts) < 20:
        warnings.add("insufficient_turnover_amount_history")
    return tuple(sorted(warnings))


def _positive_decimal(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value > 0


def _non_negative_decimal(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


__all__ = ["FactorCalculationResult", "calculate_market_state_factors"]
