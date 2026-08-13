from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest
from invest_pipeline.provider_coverage_report import (
    CoverageReportModel,
    ProviderCoverageRow,
    SymbolCoverageRow,
)
from invest_pipeline.provider_health import (
    ProviderHealthSnapshot,
    ProviderHealthStatus,
    derive_provider_health,
)
from invest_pipeline.provider_quality import (
    ProviderDatasetRegistration,
    ProviderQualityScore,
)
from invest_pipeline.provider_routing.datasets import Dataset
from invest_pipeline.provider_routing.probe import DAILY_BARS_FIELDS


def registration(**overrides: object) -> ProviderDatasetRegistration:
    values = {
        "provider_key": "fixture_dev",
        "dataset": Dataset.ETF_DAILY_BARS,
        "priority": 0,
        "reliability_score": Decimal("1"),
        "freshness_sla_days": 0,
        "supported_fields": DAILY_BARS_FIELDS,
    }
    values.update(overrides)
    return ProviderDatasetRegistration(**values)  # type: ignore[arg-type]


def score(**overrides: object) -> ProviderQualityScore:
    values: dict[str, object] = {
        "provider_key": "fixture_dev",
        "dataset": Dataset.ETF_DAILY_BARS,
        "coverage_ratio": Decimal("1"),
        "completeness_ratio": Decimal("1"),
        "freshness_days": 0,
        "freshness_status": "fresh",
        "freshness_score": Decimal("1"),
        "reliability_score": Decimal("1"),
        "quality_score": Decimal("1"),
        "missing_symbols": (),
        "failed_symbols": (),
    }
    values.update(overrides)
    return ProviderQualityScore(**values)  # type: ignore[arg-type]


def symbol_row(
    symbol: str,
    *,
    covered_start: date | None = date(2026, 8, 4),
    covered_end: date | None = date(2026, 8, 4),
) -> SymbolCoverageRow:
    return SymbolCoverageRow(
        symbol=symbol,
        requested_start=date(2026, 8, 4),
        requested_end=date(2026, 8, 4),
        covered_start=covered_start,
        covered_end=covered_end,
        record_count=1,
        fields=tuple(sorted(DAILY_BARS_FIELDS)),
        requested_fields=tuple(sorted(DAILY_BARS_FIELDS)),
        warnings=(),
        errors=(),
    )


def coverage_report(*rows: SymbolCoverageRow) -> CoverageReportModel:
    return CoverageReportModel(
        schema_version=1,
        generated_at="2026-08-04T00:00:00+00:00",
        content_hash="hash",
        providers=(
            ProviderCoverageRow(
                provider_key="fixture_dev",
                symbols=tuple(sorted(rows, key=lambda row: row.symbol)),
                requested_start=date(2026, 8, 4),
                requested_end=date(2026, 8, 4),
                requested_fields=tuple(sorted(DAILY_BARS_FIELDS)),
                raw_payload_hash=None,
            ),
        ),
    )


def test_status_enum_values_are_stable() -> None:
    assert ProviderHealthStatus.UNKNOWN.value == "unknown"
    assert ProviderHealthStatus.DISABLED.value == "disabled"
    assert ProviderHealthStatus.STALE.value == "stale"
    assert ProviderHealthStatus.DEGRADED.value == "degraded"
    assert ProviderHealthStatus.HEALTHY.value == "healthy"


def test_disabled_status_overrides_evidence() -> None:
    as_of = date(2026, 8, 5)
    snapshot = derive_provider_health(
        score(),
        registration(),
        enabled=False,
        as_of=as_of,
    )

    assert snapshot.status is ProviderHealthStatus.DISABLED
    assert snapshot.provider_key == "fixture_dev"
    assert snapshot.dataset is Dataset.ETF_DAILY_BARS
    assert snapshot.as_of is as_of


def test_unknown_status_when_no_evidence() -> None:
    snapshot = derive_provider_health(
        score(
            coverage_ratio=Decimal("0"),
            completeness_ratio=Decimal("0"),
            freshness_days=None,
            freshness_status="failed",
            freshness_score=Decimal("0"),
            quality_score=Decimal("0.20"),
            missing_symbols=("159915", "510300"),
            failed_symbols=("159915", "510300"),
        ),
        registration(),
        enabled=True,
        as_of=date(2026, 8, 4),
    )

    assert snapshot.status is ProviderHealthStatus.UNKNOWN
    assert snapshot.freshness_days is None
    assert snapshot.coverage_ratio == Decimal("0")
    assert snapshot.completeness_ratio == Decimal("0")


def test_stale_status_when_freshness_not_fresh() -> None:
    snapshot = derive_provider_health(
        score(
            freshness_days=2,
            freshness_status="warning",
            freshness_score=Decimal("0.5"),
        ),
        registration(freshness_sla_days=1),
        enabled=True,
        as_of=date(2026, 8, 6),
    )

    assert snapshot.status is ProviderHealthStatus.STALE


def test_stale_status_when_freshness_failed() -> None:
    snapshot = derive_provider_health(
        score(
            freshness_days=3,
            freshness_status="failed",
            freshness_score=Decimal("0"),
        ),
        registration(freshness_sla_days=1),
        enabled=True,
        as_of=date(2026, 8, 7),
    )

    assert snapshot.status is ProviderHealthStatus.STALE


def test_degraded_status_when_coverage_below_one() -> None:
    snapshot = derive_provider_health(
        score(
            coverage_ratio=Decimal("0.5"),
            completeness_ratio=Decimal("1"),
            missing_symbols=("159915",),
        ),
        registration(reliability_score=Decimal("0.70")),
        enabled=True,
        as_of=date(2026, 8, 4),
    )

    assert snapshot.status is ProviderHealthStatus.DEGRADED
    assert snapshot.coverage_ratio == Decimal("0.5")


def test_degraded_status_when_completeness_below_one() -> None:
    snapshot = derive_provider_health(
        score(
            coverage_ratio=Decimal("1"),
            completeness_ratio=Decimal("0.5"),
        ),
        registration(reliability_score=Decimal("0.70")),
        enabled=True,
        as_of=date(2026, 8, 4),
    )

    assert snapshot.status is ProviderHealthStatus.DEGRADED
    assert snapshot.completeness_ratio == Decimal("0.5")


def test_degraded_status_when_failed_symbols_nonempty() -> None:
    snapshot = derive_provider_health(
        score(
            coverage_ratio=Decimal("1"),
            completeness_ratio=Decimal("1"),
            failed_symbols=("510300",),
        ),
        registration(),
        enabled=True,
        as_of=date(2026, 8, 4),
    )

    assert snapshot.status is ProviderHealthStatus.DEGRADED
    assert snapshot.failed_symbols == ("510300",)


def test_healthy_status_when_evidence_is_perfect() -> None:
    snapshot = derive_provider_health(
        score(),
        registration(),
        enabled=True,
        as_of=date(2026, 8, 4),
    )

    assert snapshot.status is ProviderHealthStatus.HEALTHY
    assert snapshot.coverage_ratio == Decimal("1")
    assert snapshot.completeness_ratio == Decimal("1")
    assert snapshot.freshness_days == 0
    assert snapshot.failed_symbols == ()


def test_disabled_overrides_unknown_when_no_evidence() -> None:
    snapshot = derive_provider_health(
        score(
            coverage_ratio=Decimal("0"),
            completeness_ratio=Decimal("0"),
            freshness_days=None,
            freshness_status="failed",
            freshness_score=Decimal("0"),
            quality_score=Decimal("0.20"),
            missing_symbols=("159915",),
            failed_symbols=("159915",),
        ),
        registration(),
        enabled=False,
        as_of=date(2026, 8, 4),
    )

    assert snapshot.status is ProviderHealthStatus.DISABLED


def test_as_of_is_preserved_exactly() -> None:
    as_of = date(2026, 1, 2)
    snapshot = derive_provider_health(
        score(),
        registration(),
        enabled=True,
        as_of=as_of,
    )

    assert snapshot.as_of is as_of
    assert snapshot.as_of == date(2026, 1, 2)


def test_snapshot_is_frozen() -> None:
    snapshot = derive_provider_health(
        score(),
        registration(),
        enabled=True,
        as_of=date(2026, 8, 4),
    )

    assert isinstance(snapshot, ProviderHealthSnapshot)
    with pytest.raises(FrozenInstanceError):
        snapshot.status = ProviderHealthStatus.STALE  # type: ignore[misc]


def test_snapshot_fields_carry_through_unchanged() -> None:
    expected_failed = ("510300",)
    snapshot = derive_provider_health(
        score(
            coverage_ratio=Decimal("1"),
            completeness_ratio=Decimal("1"),
            quality_score=Decimal("0.95"),
            failed_symbols=expected_failed,
        ),
        registration(),
        enabled=True,
        as_of=date(2026, 8, 4),
    )

    assert snapshot.provider_key == "fixture_dev"
    assert snapshot.dataset is Dataset.ETF_DAILY_BARS
    assert snapshot.as_of == date(2026, 8, 4)
    assert snapshot.freshness_days == 0
    assert snapshot.quality_score == Decimal("0.95")
    assert snapshot.coverage_ratio == Decimal("1")
    assert snapshot.completeness_ratio == Decimal("1")
    assert snapshot.failed_symbols == expected_failed


def test_uses_provider_quality_score_without_duplication() -> None:
    """``derive_provider_health`` must read directly from the supplied score.

    The status mapping must consult ``score.freshness_status``,
    ``score.coverage_ratio``, ``score.completeness_ratio``, and
    ``score.failed_symbols`` verbatim; it never re-derives any of
    those values. The test below asserts that an artificially
    perfect-looking score with a non-fresh freshness status is
    still classified as ``STALE`` — proving the function trusts
    the upstream contract rather than recomputing freshness.
    """
    snapshot = derive_provider_health(
        score(
            coverage_ratio=Decimal("1"),
            completeness_ratio=Decimal("1"),
            freshness_days=2,
            freshness_status="warning",
            freshness_score=Decimal("0.5"),
            quality_score=Decimal("0.90"),
            failed_symbols=(),
        ),
        registration(freshness_sla_days=1),
        enabled=True,
        as_of=date(2026, 8, 6),
    )

    assert snapshot.status is ProviderHealthStatus.STALE
    assert snapshot.quality_score == Decimal("0.90")
    assert snapshot.freshness_days == 2


def test_invalid_score_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="score must be a ProviderQualityScore"):
        derive_provider_health(  # type: ignore[arg-type]
            object(),
            registration(),
            enabled=True,
            as_of=date(2026, 8, 4),
        )


def test_invalid_registration_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="registration must be a ProviderDatasetRegistration"):
        derive_provider_health(
            score(),
            object(),  # type: ignore[arg-type]
            enabled=True,
            as_of=date(2026, 8, 4),
        )


def test_invalid_as_of_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="as_of must be a date"):
        derive_provider_health(
            score(),
            registration(),
            enabled=True,
            as_of="2026-08-04",  # type: ignore[arg-type]
        )


def test_mismatched_provider_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="provider_key"):
        derive_provider_health(
            score(provider_key="akshare"),
            registration(),
            enabled=True,
            as_of=date(2026, 8, 4),
        )


def test_mismatched_dataset_is_rejected() -> None:
    with pytest.raises(ValueError, match="dataset"):
        derive_provider_health(
            score(dataset=Dataset.RESEARCH),
            registration(),
            enabled=True,
            as_of=date(2026, 8, 4),
        )


def test_status_enum_supports_string_comparison() -> None:
    assert ProviderHealthStatus.HEALTHY == "healthy"
    assert ProviderHealthStatus.STALE == "stale"
