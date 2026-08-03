"""Pure dynamic ETF universe qualification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from invest_domain.instruments.models import Instrument, InstrumentId, InstrumentType
from invest_domain.instruments.values import InstrumentStatus
from invest_domain.market_data.models import DailyBar
from invest_domain.market_data.values import TradingStatus


class UniverseEligibility(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    INELIGIBLE = "ineligible"


@dataclass(frozen=True, slots=True)
class UniverseCandidate:
    instrument_id: InstrumentId
    symbol: str
    exchange: str
    eligibility: UniverseEligibility
    history_days: int
    latest_trade_date: date | None
    latest_close: object | None
    stale_days: int | None
    reasons: tuple[str, ...]
    can_enter_watch_only: bool


def build_etf_universe(
    instruments: Sequence[Instrument],
    bars_by_instrument: Mapping[InstrumentId, Sequence[DailyBar]],
    as_of_date: date,
    minimum_full_history_days: int = 60,
    minimum_partial_history_days: int = 20,
    max_stale_days: int = 3,
) -> tuple[UniverseCandidate, ...]:
    """Classify ETF instruments from a deterministic, revision-aware bar window."""
    if minimum_partial_history_days < 1 or minimum_full_history_days < minimum_partial_history_days:
        raise ValueError("history thresholds are invalid")
    if max_stale_days < 0:
        raise ValueError("max_stale_days must be non-negative")

    selected: dict[InstrumentId, Instrument] = {}
    duplicate_reasons: dict[InstrumentId, set[str]] = {}
    for instrument in instruments:
        instrument_id = instrument.instrument_id
        if instrument_id is None:
            continue
        if instrument_id in selected:
            duplicate_reasons.setdefault(instrument_id, set()).add("duplicate_instrument")
            if _instrument_key(instrument) != _instrument_key(selected[instrument_id]):
                duplicate_reasons[instrument_id].add("instrument_conflict")
            continue
        selected[instrument_id] = instrument

    output: list[UniverseCandidate] = []
    for instrument_id in sorted(selected, key=str):
        instrument = selected[instrument_id]
        reasons = set(duplicate_reasons.get(instrument_id, ()))
        bars = _deduplicate_bars(bars_by_instrument.get(instrument_id, ()), as_of_date, reasons)
        valid = [bar for bar in bars if bar.trading_status is TradingStatus.NORMAL and bar.close is not None]
        valid.sort(key=lambda bar: bar.trade_date)
        latest = valid[-1] if valid else None
        history_days = len({bar.trade_date for bar in valid})
        stale_days = (as_of_date - latest.trade_date).days if latest else None
        if any(bar.trading_status is TradingStatus.SUSPENDED for bar in bars):
            reasons.add("suspended")
        if latest is None:
            reasons.add("no_valid_price")
        elif stale_days is not None and stale_days > max_stale_days:
            reasons.add("stale")
        if instrument.instrument_type is not InstrumentType.ETF:
            reasons.add("not_etf")
        if not instrument.is_active or instrument.status is not InstrumentStatus.ACTIVE:
            reasons.add("inactive")
        if instrument.exchange not in {"SSE", "SZSE"}:
            reasons.add("unsupported_exchange")
        fresh = latest is not None and stale_days is not None and stale_days <= max_stale_days
        if fresh and history_days >= minimum_full_history_days and not reasons - {"duplicate_instrument"}:
            eligibility = UniverseEligibility.FULL
        elif fresh and history_days >= minimum_partial_history_days and not reasons - {"duplicate_instrument"}:
            eligibility = UniverseEligibility.PARTIAL
        else:
            eligibility = UniverseEligibility.INELIGIBLE
            if history_days < minimum_partial_history_days:
                reasons.add("insufficient_history")
        output.append(UniverseCandidate(
            instrument_id=instrument_id, symbol=instrument.symbol, exchange=instrument.exchange,
            eligibility=eligibility, history_days=history_days,
            latest_trade_date=latest.trade_date if latest else None,
            latest_close=latest.close if latest else None, stale_days=stale_days,
            reasons=tuple(sorted(reasons)), can_enter_watch_only=eligibility is UniverseEligibility.PARTIAL,
        ))
    return tuple(output)


def _instrument_key(instrument: Instrument) -> tuple[object, ...]:
    return (instrument.symbol, instrument.name, instrument.exchange, instrument.instrument_type, instrument.is_active, instrument.status)


def _deduplicate_bars(bars: Sequence[DailyBar], as_of_date: date, reasons: set[str]) -> list[DailyBar]:
    by_date: dict[date, DailyBar] = {}
    for bar in bars:
        if bar.trade_date > as_of_date:
            reasons.add("future_bar")
            continue
        existing = by_date.get(bar.trade_date)
        if existing is None or bar.revision > existing.revision:
            if existing is not None and existing.revision == bar.revision and existing.row_hash != bar.row_hash:
                reasons.add("bar_revision_conflict")
                if bar.row_hash < existing.row_hash:
                    by_date[bar.trade_date] = bar
            else:
                by_date[bar.trade_date] = bar
        elif existing.revision == bar.revision and existing.row_hash != bar.row_hash:
            reasons.add("bar_revision_conflict")
            if bar.row_hash is not None and existing.row_hash is not None and bar.row_hash < existing.row_hash:
                by_date[bar.trade_date] = bar
    return list(by_date.values())


__all__ = ["UniverseCandidate", "UniverseEligibility", "build_etf_universe"]
