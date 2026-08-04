"""Provider quality policy registry for DC1-A.

All priorities, reliability scores, and freshness SLAs below are explicit
provisional policy values, not measured provider-quality statistics. The
provisional order is fixture_dev (0), cifangquant (10), akshare (20),
eastmoney (30), sina (40), and tonghuashun (50). Their provisional
reliability scores are 1.00, 0.80, 0.70, 0.60, 0.60, and 0.60; their
freshness SLAs are respectively 0, 1, 1, 1, 1, and 1 days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from invest_pipeline.provider_catalog import lookup_provider
from invest_pipeline.provider_coverage_report import (
    CoverageReportModel,
    ProviderCoverageRow,
    SymbolCoverageRow,
)
from invest_pipeline.provider_routing.datasets import Dataset, required_capability_for
from invest_pipeline.provider_routing.probe import DAILY_BARS_FIELDS


@dataclass(frozen=True, slots=True)
class ProviderDatasetRegistration:
    provider_key: str
    dataset: Dataset
    priority: int
    reliability_score: Decimal
    freshness_sla_days: int
    supported_fields: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_key, str) or not self.provider_key.strip():
            raise ValueError("provider_key must be a non-empty string")
        if not isinstance(self.dataset, Dataset):
            raise ValueError("dataset must be a Dataset instance")
        if (
            not isinstance(self.priority, int)
            or isinstance(self.priority, bool)
            or self.priority < 0
        ):
            raise ValueError("priority must be a non-negative integer")
        if not isinstance(self.reliability_score, Decimal):
            raise ValueError("reliability_score must be a Decimal")
        if not self.reliability_score.is_finite() or not (
            Decimal("0") <= self.reliability_score <= Decimal("1")
        ):
            raise ValueError("reliability_score must be between 0 and 1")
        if (
            not isinstance(self.freshness_sla_days, int)
            or isinstance(self.freshness_sla_days, bool)
            or self.freshness_sla_days < 0
        ):
            raise ValueError("freshness_sla_days must be a non-negative integer")
        if not isinstance(self.supported_fields, frozenset) or not self.supported_fields:
            raise ValueError("supported_fields must be a non-empty frozenset")
        if any(
            not isinstance(field, str) or not field.strip()
            for field in self.supported_fields
        ):
            raise ValueError("supported_fields must contain non-empty strings")

        declaration = lookup_provider(self.provider_key)
        required_capability = required_capability_for(self.dataset)
        if required_capability not in declaration.capabilities:
            raise ValueError(
                f"provider {self.provider_key!r} does not support dataset "
                f"{self.dataset.value!r}"
            )


def _etf_registration(
    provider_key: str,
    priority: int,
    reliability_score: str,
    freshness_sla_days: int,
) -> ProviderDatasetRegistration:
    return ProviderDatasetRegistration(
        provider_key=provider_key,
        dataset=Dataset.ETF_DAILY_BARS,
        priority=priority,
        reliability_score=Decimal(reliability_score),
        freshness_sla_days=freshness_sla_days,
        supported_fields=DAILY_BARS_FIELDS,
    )


ETF_DAILY_BAR_REGISTRY: tuple[ProviderDatasetRegistration, ...] = (
    _etf_registration("fixture_dev", 0, "1.00", 0),
    _etf_registration("cifangquant", 10, "0.80", 1),
    _etf_registration("akshare", 20, "0.70", 1),
    _etf_registration("eastmoney", 30, "0.60", 1),
    _etf_registration("sina", 40, "0.60", 1),
    _etf_registration("tonghuashun", 50, "0.60", 1),
)


def iter_etf_daily_bar_registrations() -> tuple[ProviderDatasetRegistration, ...]:
    return tuple(
        sorted(
            ETF_DAILY_BAR_REGISTRY,
            key=lambda registration: (registration.priority, registration.provider_key),
        )
    )


FreshnessStatus = Literal["fresh", "warning", "failed"]


@dataclass(frozen=True, slots=True)
class ProviderQualityScore:
    provider_key: str
    dataset: Dataset
    coverage_ratio: Decimal
    completeness_ratio: Decimal
    freshness_days: int | None
    freshness_status: FreshnessStatus
    freshness_score: Decimal
    reliability_score: Decimal
    quality_score: Decimal
    missing_symbols: tuple[str, ...]
    failed_symbols: tuple[str, ...]


def _validated_expected_symbols(expected_symbols: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(expected_symbols, tuple) or not expected_symbols:
        raise ValueError("expected_symbols must be a non-empty tuple")
    if any(not isinstance(symbol, str) or not symbol.strip() for symbol in expected_symbols):
        raise ValueError("expected_symbols must contain non-empty strings")
    if len(set(expected_symbols)) != len(expected_symbols):
        raise ValueError("expected_symbols must not contain duplicates")
    return tuple(sorted(expected_symbols))


def _provider_row(
    report: CoverageReportModel, provider_key: str
) -> ProviderCoverageRow | None:
    return next(
        (row for row in report.providers if row.provider_key == provider_key),
        None,
    )


def _has_complete_fields(
    row: SymbolCoverageRow, supported_fields: frozenset[str]
) -> bool:
    return supported_fields.issubset(row.fields)


def _freshness(
    latest_covered_end: date | None,
    as_of_date: date,
    freshness_sla_days: int,
) -> tuple[int | None, FreshnessStatus, Decimal]:
    if latest_covered_end is None:
        return None, "failed", Decimal("0")
    days = (as_of_date - latest_covered_end).days
    if freshness_sla_days == 0:
        status: FreshnessStatus = "fresh" if days == 0 else "failed"
    elif days <= freshness_sla_days:
        status = "fresh"
    elif days <= 2 * freshness_sla_days:
        status = "warning"
    else:
        status = "failed"
    score = {
        "fresh": Decimal("1"),
        "warning": Decimal("0.5"),
        "failed": Decimal("0"),
    }[status]
    return days, status, score


def evaluate_provider_quality(
    report: CoverageReportModel,
    registration: ProviderDatasetRegistration,
    expected_symbols: tuple[str, ...],
    as_of_date: date,
) -> ProviderQualityScore:
    if not isinstance(report, CoverageReportModel):
        raise ValueError("report must be a CoverageReportModel")
    if not isinstance(registration, ProviderDatasetRegistration):
        raise ValueError("registration must be a ProviderDatasetRegistration")
    if type(as_of_date) is not date:
        raise ValueError("as_of_date must be a date")

    symbols = _validated_expected_symbols(expected_symbols)
    provider = _provider_row(report, registration.provider_key)
    rows = {} if provider is None else {row.symbol: row for row in provider.symbols}
    missing_symbols = tuple(symbol for symbol in symbols if symbol not in rows)
    field_complete_count = sum(
        _has_complete_fields(rows[symbol], registration.supported_fields)
        for symbol in symbols
        if symbol in rows
    )
    failed_symbols = (
        symbols
        if provider is None
        else tuple(
            symbol
            for symbol in symbols
            if symbol in rows
            and (
                rows[symbol].covered_start is None
                or rows[symbol].covered_end is None
                or not _has_complete_fields(
                    rows[symbol], registration.supported_fields
                )
                or bool(rows[symbol].errors)
            )
        )
    )
    covered_count = (
        0
        if provider is None
        else len(symbols) - len(missing_symbols) - len(failed_symbols)
    )
    covered_ends = tuple(
        rows[symbol].covered_end
        for symbol in symbols
        if symbol in rows and rows[symbol].covered_end is not None
    )
    latest_covered_end = max(covered_ends, default=None)
    freshness_days, freshness_status, freshness_score = _freshness(
        latest_covered_end,
        as_of_date,
        registration.freshness_sla_days,
    )

    with localcontext() as context:
        context.prec = 28
        total = Decimal(len(symbols))
        coverage_ratio = Decimal(covered_count) / total
        completeness_ratio = Decimal(field_complete_count) / total
        quality_score = (
            coverage_ratio * Decimal("0.30")
            + completeness_ratio * Decimal("0.30")
            + freshness_score * Decimal("0.20")
            + registration.reliability_score * Decimal("0.20")
        )
    quality_score = min(Decimal("1"), max(Decimal("0"), quality_score))

    return ProviderQualityScore(
        provider_key=registration.provider_key,
        dataset=registration.dataset,
        coverage_ratio=coverage_ratio,
        completeness_ratio=completeness_ratio,
        freshness_days=freshness_days,
        freshness_status=freshness_status,
        freshness_score=freshness_score,
        reliability_score=registration.reliability_score,
        quality_score=quality_score,
        missing_symbols=missing_symbols,
        failed_symbols=failed_symbols,
    )


__all__ = [
    "ETF_DAILY_BAR_REGISTRY",
    "FreshnessStatus",
    "ProviderDatasetRegistration",
    "ProviderQualityScore",
    "evaluate_provider_quality",
    "iter_etf_daily_bar_registrations",
]
