"""Pure helpers for turning provider coverage into a deterministic plan."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from invest_domain.instruments.models import Instrument, InstrumentType
from invest_domain.instruments.values import InstrumentStatus
from invest_domain.shared.values import Exchange

from .provider_coverage_report import CoverageReportModel, SymbolCoverageRow


class ActiveUniverseAmbiguityError(ValueError):
    """Raised when one active ETF symbol appears on multiple exchanges."""


def select_active_etf_symbols(
    instruments: Iterable[Instrument],
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[str, ...]:
    """Return the sorted, unique symbols in the active domestic ETF universe.

    The window arguments are optional and inclusive. When supplied they
    further narrow the universe:

    * ``end_date`` excludes instruments whose ``list_date`` is strictly
      after ``end_date`` — the ETF was not yet listed by the inclusive
      end of the probe window.
    * ``start_date`` excludes instruments whose ``delist_date`` is
      strictly before ``start_date`` — the ETF was already delisted
      before the inclusive start of the probe window.

    Instruments with ``list_date`` or ``delist_date`` set to ``None``
    pass the matching check unchanged, so legacy callers that do not
    record listing dates are not penalised. Passing neither date — or
    passing only one — preserves the historical "active ETF universe"
    semantics bit-for-bit: the optional window is purely additive and
    never relaxes an existing exclusion.
    """

    exchanges_by_symbol: dict[str, set[str]] = {}
    for instrument in instruments:
        if (
            instrument.instrument_type is not InstrumentType.ETF
            or not instrument.is_active
            or instrument.status is not InstrumentStatus.ACTIVE
            or instrument.exchange not in (Exchange.SSE, Exchange.SZSE)
        ):
            continue
        if (
            end_date is not None
            and instrument.list_date is not None
            and instrument.list_date > end_date
        ):
            continue
        if (
            start_date is not None
            and instrument.delist_date is not None
            and instrument.delist_date < start_date
        ):
            continue
        exchanges_by_symbol.setdefault(instrument.symbol, set()).add(
            instrument.exchange
        )

    ambiguous = {
        symbol: sorted(exchanges)
        for symbol, exchanges in exchanges_by_symbol.items()
        if len(exchanges) > 1
    }
    if ambiguous:
        details = ", ".join(
            f"{symbol}: {', '.join(exchanges)}"
            for symbol, exchanges in sorted(ambiguous.items())
        )
        raise ActiveUniverseAmbiguityError(
            f"active ETF symbol has multiple exchanges: {details}"
        )
    return tuple(sorted(exchanges_by_symbol))


@dataclass(frozen=True, slots=True)
class BackfillPlanItem:
    """One provider/symbol row that needs collection or retry."""

    provider_key: str
    symbol: str
    priority: tuple[int, int, str]
    reason: str


def _has_complete_fields(
    row: SymbolCoverageRow, requested_fields: tuple[str, ...] | None
) -> bool:
    fields = row.fields
    if requested_fields is None:
        return bool(fields)
    return set(requested_fields).issubset(fields)


def build_backfill_plan(
    report: CoverageReportModel,
    provider_priority: Mapping[str, int],
) -> tuple[BackfillPlanItem, ...]:
    """Build a stable plan for rows with missing, partial, or failed coverage."""

    if not isinstance(report, CoverageReportModel):
        raise ValueError("report must be a CoverageReportModel")
    if not isinstance(provider_priority, Mapping):
        raise ValueError("provider_priority must be a mapping")

    plan: list[BackfillPlanItem] = []
    for provider in report.providers:
        for row in provider.symbols:
            requested_fields = (
                row.requested_fields
                if row.requested_fields is not None
                else provider.requested_fields
            )
            has_errors = bool(row.errors)
            if _has_complete_fields(row, requested_fields) and not has_errors:
                continue
            priority = (
                provider_priority.get(provider.provider_key, 1000),
                0 if has_errors else 1,
                row.symbol,
            )
            plan.append(
                BackfillPlanItem(
                    provider_key=provider.provider_key,
                    symbol=row.symbol,
                    priority=priority,
                    reason=("failed_probe" if has_errors else "missing_or_partial_coverage"),
                )
            )
    return tuple(sorted(plan, key=lambda item: item.priority))
