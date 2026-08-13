from dataclasses import FrozenInstanceError
from datetime import date, datetime
from decimal import Decimal

import pytest
from invest_pipeline.provider_coverage_report import (
    CoverageError,
    CoverageReportModel,
    ProviderCoverageRow,
    SymbolCoverageRow,
)
from invest_pipeline.provider_quality import (
    DECISION_REASON_FAILED_SYMBOLS,
    DECISION_REASON_LOW_COMPLETENESS,
    DECISION_REASON_LOW_COVERAGE,
    DECISION_REASON_STALE_OR_FAILED_FRESHNESS,
    DEFAULT_MIN_COMPLETENESS_RATIO,
    DEFAULT_MIN_COVERAGE_RATIO,
    ETF_DAILY_BAR_REGISTRY,
    ProviderDatasetRegistration,
    ProviderPublishDecision,
    decide_provider_publishability,
    decision_from_score,
    evaluate_provider_quality,
    iter_etf_daily_bar_registrations,
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


def symbol_row(
    symbol: str,
    *,
    covered_start: date | None = date(2026, 8, 4),
    covered_end: date | None = date(2026, 8, 4),
    fields: tuple[str, ...] | None = None,
    errors: tuple[CoverageError, ...] = (),
) -> SymbolCoverageRow:
    return SymbolCoverageRow(
        symbol=symbol,
        requested_start=date(2026, 8, 4),
        requested_end=date(2026, 8, 4),
        covered_start=covered_start,
        covered_end=covered_end,
        record_count=1,
        fields=tuple(sorted(DAILY_BARS_FIELDS)) if fields is None else fields,
        requested_fields=tuple(sorted(DAILY_BARS_FIELDS)),
        warnings=(),
        errors=errors,
    )


def coverage_report(
    *rows: SymbolCoverageRow,
    provider_key: str | None = "fixture_dev",
) -> CoverageReportModel:
    providers = ()
    if provider_key is not None:
        providers = (
            ProviderCoverageRow(
                provider_key=provider_key,
                symbols=tuple(sorted(rows, key=lambda row: row.symbol)),
                requested_start=date(2026, 8, 4),
                requested_end=date(2026, 8, 4),
                requested_fields=tuple(sorted(DAILY_BARS_FIELDS)),
                raw_payload_hash=None,
            ),
        )
    return CoverageReportModel(
        schema_version=1,
        generated_at="2026-08-04T00:00:00+00:00",
        content_hash="hash",
        providers=providers,
    )


def test_registry_contains_valid_frozen_entries() -> None:
    assert {entry.provider_key for entry in ETF_DAILY_BAR_REGISTRY} == {
        "fixture_dev",
        "cifangquant",
        "akshare",
    }
    assert all(entry.dataset is Dataset.ETF_DAILY_BARS for entry in ETF_DAILY_BAR_REGISTRY)
    assert all(entry.supported_fields == DAILY_BARS_FIELDS for entry in ETF_DAILY_BAR_REGISTRY)
    with pytest.raises(FrozenInstanceError):
        ETF_DAILY_BAR_REGISTRY[0].priority = 99  # type: ignore[misc]


def test_registry_excludes_three_provider_plan_keys() -> None:
    # The historical V2 three-provider plan (``eastmoney`` / ``sina``
    # / ``tonghuashun``) proposed additional ETF daily-bar providers;
    # that plan has been de-scoped and the registry must not carry
    # entries for them. The three sources remain internal upstreams
    # of the AkShare aggregator (``ak.fund_etf_hist_sina`` /
    # ``ak.fund_etf_hist_em``).
    registered_keys = {entry.provider_key for entry in ETF_DAILY_BAR_REGISTRY}
    for key in ("eastmoney", "sina", "tonghuashun"):
        assert key not in registered_keys


def test_registry_iteration_has_stable_policy_order() -> None:
    first = iter_etf_daily_bar_registrations()
    second = iter_etf_daily_bar_registrations()
    assert first == second
    assert [(entry.priority, entry.provider_key) for entry in first] == sorted(
        (entry.priority, entry.provider_key) for entry in ETF_DAILY_BAR_REGISTRY
    )


def test_capability_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="does not support dataset"):
        registration(provider_key="rsscast")


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(KeyError) as exc_info:
        registration(provider_key="unknown")
    assert exc_info.value.args == ("unknown",)


@pytest.mark.parametrize("score", [Decimal("-0.01"), Decimal("1.01"), Decimal("NaN")])
def test_invalid_reliability_ranges_are_rejected(score: Decimal) -> None:
    with pytest.raises(ValueError, match="reliability_score"):
        registration(reliability_score=score)


@pytest.mark.parametrize(
    "fields",
    [frozenset(), frozenset({""}), frozenset({"open", " "})],
)
def test_empty_or_blank_supported_fields_are_rejected(fields: frozenset[str]) -> None:
    with pytest.raises(ValueError, match="supported_fields"):
        registration(supported_fields=fields)


@pytest.mark.parametrize("priority", [-1, 1.5, True])
def test_invalid_priority_is_rejected(priority: object) -> None:
    with pytest.raises(ValueError, match="priority"):
        registration(priority=priority)


@pytest.mark.parametrize("sla", [-1, 1.5, True])
def test_invalid_sla_is_rejected(sla: object) -> None:
    with pytest.raises(ValueError, match="freshness_sla_days"):
        registration(freshness_sla_days=sla)


def test_complete_provider_quality_score() -> None:
    report = coverage_report(symbol_row("159915"), symbol_row("510300"))

    score = evaluate_provider_quality(
        report,
        registration(),
        ("510300", "159915"),
        date(2026, 8, 4),
    )

    assert score.provider_key == "fixture_dev"
    assert score.dataset is Dataset.ETF_DAILY_BARS
    assert score.coverage_ratio == Decimal("1")
    assert score.completeness_ratio == Decimal("1")
    assert score.freshness_days == 0
    assert score.freshness_status == "fresh"
    assert score.freshness_score == Decimal("1")
    assert score.quality_score == Decimal("1")
    assert score.missing_symbols == ()
    assert score.failed_symbols == ()


def test_missing_provider_is_a_failed_score() -> None:
    score = evaluate_provider_quality(
        coverage_report(provider_key=None),
        registration(reliability_score=Decimal("0.80")),
        ("510300", "159915"),
        date(2026, 8, 4),
    )

    assert score.coverage_ratio == Decimal("0")
    assert score.completeness_ratio == Decimal("0")
    assert score.freshness_days is None
    assert score.freshness_status == "failed"
    assert score.freshness_score == Decimal("0")
    assert score.quality_score == Decimal("0.1600")
    assert score.missing_symbols == ("159915", "510300")
    assert score.failed_symbols == ("159915", "510300")


def test_symbol_error_fails_coverage_but_not_field_completeness() -> None:
    error = CoverageError(
        provider_key="fixture_dev",
        symbol="510300",
        code="provider_error",
        message="failed",
    )
    score = evaluate_provider_quality(
        coverage_report(symbol_row("510300", errors=(error,))),
        registration(),
        ("510300",),
        date(2026, 8, 4),
    )

    assert score.coverage_ratio == Decimal("0")
    assert score.completeness_ratio == Decimal("1")
    assert score.freshness_status == "fresh"
    assert score.quality_score == Decimal("0.70")
    assert score.missing_symbols == ()
    assert score.failed_symbols == ("510300",)


@pytest.mark.parametrize(
    ("days", "expected_status", "expected_freshness_score", "expected_quality"),
    [
        (2, "warning", Decimal("0.5"), Decimal("0.90")),
        (3, "failed", Decimal("0"), Decimal("0.80")),
    ],
)
def test_stale_freshness_states(
    days: int,
    expected_status: str,
    expected_freshness_score: Decimal,
    expected_quality: Decimal,
) -> None:
    covered_date = date(2026, 8, 4)
    score = evaluate_provider_quality(
        coverage_report(
            symbol_row(
                "510300",
                covered_start=covered_date,
                covered_end=covered_date,
            )
        ),
        registration(freshness_sla_days=1),
        ("510300",),
        date(2026, 8, 4 + days),
    )

    assert score.freshness_days == days
    assert score.freshness_status == expected_status
    assert score.freshness_score == expected_freshness_score
    assert score.quality_score == expected_quality


@pytest.mark.parametrize(
    ("as_of_date", "expected_status", "expected_score"),
    [
        (date(2026, 8, 4), "fresh", Decimal("1")),
        (date(2026, 8, 5), "failed", Decimal("0")),
    ],
)
def test_zero_day_sla_requires_same_day_coverage(
    as_of_date: date,
    expected_status: str,
    expected_score: Decimal,
) -> None:
    score = evaluate_provider_quality(
        coverage_report(symbol_row("510300")),
        registration(freshness_sla_days=0),
        ("510300",),
        as_of_date,
    )

    assert score.freshness_status == expected_status
    assert score.freshness_score == expected_score


def test_repeated_evaluation_is_deterministic_and_sorted() -> None:
    report = coverage_report(symbol_row("510300"))
    policy = registration(reliability_score=Decimal("0.70"))
    arguments = (report, policy, ("510300", "159915"), date(2026, 8, 4))

    first = evaluate_provider_quality(*arguments)
    second = evaluate_provider_quality(*arguments)

    assert first == second
    assert first.coverage_ratio == Decimal("0.5")
    assert first.completeness_ratio == Decimal("0.5")
    assert first.quality_score == Decimal("0.64")
    assert first.missing_symbols == ("159915",)
    assert first.failed_symbols == ()


@pytest.mark.parametrize(
    "expected_symbols",
    [(), ("510300", "510300"), ("",), (" ",)],
)
def test_invalid_expected_symbols_are_rejected(
    expected_symbols: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="expected_symbols"):
        evaluate_provider_quality(
            coverage_report(),
            registration(),
            expected_symbols,
            date(2026, 8, 4),
        )


def test_invalid_as_of_date_is_rejected() -> None:
    with pytest.raises(ValueError, match="as_of_date"):
        evaluate_provider_quality(
            coverage_report(),
            registration(),
            ("510300",),
            datetime(2026, 8, 4),
        )


# --- Stage 4C fail-closed publishability gate ---------------------------


def test_decide_provider_publishability_complete_is_publishable() -> None:
    report = coverage_report(symbol_row("159915"), symbol_row("510300"))
    policy = registration()

    decision = decide_provider_publishability(
        report,
        policy,
        ("510300", "159915"),
        date(2026, 8, 4),
    )

    assert isinstance(decision, ProviderPublishDecision)
    assert decision.publishable is True
    assert decision.reasons == ()
    assert decision.provider_key == "fixture_dev"
    assert decision.dataset is Dataset.ETF_DAILY_BARS
    assert decision.coverage_ratio == Decimal("1")
    assert decision.completeness_ratio == Decimal("1")
    assert decision.freshness_status == "fresh"
    assert decision.failed_symbols == ()


def test_decide_provider_publishability_missing_provider_fails_closed() -> None:
    decision = decide_provider_publishability(
        coverage_report(provider_key=None),
        registration(reliability_score=Decimal("0.80")),
        ("510300", "159915"),
        date(2026, 8, 4),
    )

    assert decision.publishable is False
    assert decision.reasons == (
        DECISION_REASON_LOW_COVERAGE,
        DECISION_REASON_LOW_COMPLETENESS,
        DECISION_REASON_STALE_OR_FAILED_FRESHNESS,
        DECISION_REASON_FAILED_SYMBOLS,
    )
    assert decision.failed_symbols == ("159915", "510300")


def test_decide_provider_publishability_low_coverage_is_rejected() -> None:
    decision = decide_provider_publishability(
        coverage_report(symbol_row("510300")),
        registration(reliability_score=Decimal("0.70")),
        ("510300", "159915"),
        date(2026, 8, 4),
    )

    assert decision.publishable is False
    assert DECISION_REASON_LOW_COVERAGE in decision.reasons
    assert decision.coverage_ratio == Decimal("0.5")
    assert decision.completeness_ratio == Decimal("0.5")
    assert decision.freshness_status == "fresh"
    assert DECISION_REASON_LOW_COMPLETENESS in decision.reasons


def test_decide_provider_publishability_partial_completeness_is_rejected() -> None:
    partial_fields: tuple[str, ...] = ("close",)
    decision = decide_provider_publishability(
        coverage_report(symbol_row("510300", fields=partial_fields)),
        registration(),
        ("510300",),
        date(2026, 8, 4),
    )

    assert decision.publishable is False
    assert DECISION_REASON_LOW_COMPLETENESS in decision.reasons
    assert decision.completeness_ratio == Decimal("0")
    assert decision.freshness_status == "fresh"


def test_decide_provider_publishability_thresholds_are_independent() -> None:
    decision = decide_provider_publishability(
        coverage_report(symbol_row("510300")),
        registration(reliability_score=Decimal("0.70")),
        ("510300", "159915"),
        date(2026, 8, 4),
        min_completeness_ratio=Decimal("0.75"),
        min_coverage_ratio=Decimal("0.25"),
    )

    assert decision.publishable is False
    assert DECISION_REASON_LOW_COMPLETENESS in decision.reasons
    assert DECISION_REASON_LOW_COVERAGE not in decision.reasons


def test_decide_provider_publishability_warning_freshness_is_rejected() -> None:
    covered_date = date(2026, 8, 4)
    decision = decide_provider_publishability(
        coverage_report(
            symbol_row(
                "510300",
                covered_start=covered_date,
                covered_end=covered_date,
            )
        ),
        registration(freshness_sla_days=1),
        ("510300",),
        date(2026, 8, 6),
    )

    assert decision.publishable is False
    assert decision.reasons == (DECISION_REASON_STALE_OR_FAILED_FRESHNESS,)
    assert decision.freshness_status == "warning"
    assert decision.freshness_days == 2


def test_decide_provider_publishability_failed_freshness_is_rejected() -> None:
    covered_date = date(2026, 8, 4)
    decision = decide_provider_publishability(
        coverage_report(
            symbol_row(
                "510300",
                covered_start=covered_date,
                covered_end=covered_date,
            )
        ),
        registration(freshness_sla_days=1),
        ("510300",),
        date(2026, 8, 10),
    )

    assert decision.publishable is False
    assert decision.reasons == (DECISION_REASON_STALE_OR_FAILED_FRESHNESS,)
    assert decision.freshness_status == "failed"
    assert decision.freshness_days == 6


def test_decide_provider_publishability_symbol_error_yields_failed_symbols() -> None:
    error = CoverageError(
        provider_key="fixture_dev",
        symbol="510300",
        code="provider_error",
        message="failed",
    )
    decision = decide_provider_publishability(
        coverage_report(symbol_row("510300", errors=(error,))),
        registration(),
        ("510300",),
        date(2026, 8, 4),
    )

    assert decision.publishable is False
    assert DECISION_REASON_FAILED_SYMBOLS in decision.reasons
    assert decision.failed_symbols == ("510300",)
    assert decision.freshness_status == "fresh"


def test_decide_provider_publishability_custom_thresholds_relaxed() -> None:
    decision = decide_provider_publishability(
        coverage_report(symbol_row("510300")),
        registration(reliability_score=Decimal("0.70")),
        ("510300", "159915"),
        date(2026, 8, 4),
        min_coverage_ratio=Decimal("0.5"),
        min_completeness_ratio=Decimal("0.5"),
    )

    assert decision.publishable is True
    assert decision.reasons == ()
    assert decision.coverage_ratio == Decimal("0.5")
    assert decision.completeness_ratio == Decimal("0.5")


def test_decide_provider_publishability_thresholds_do_not_lower_freshness() -> None:
    covered_date = date(2026, 8, 4)
    decision = decide_provider_publishability(
        coverage_report(
            symbol_row(
                "510300",
                covered_start=covered_date,
                covered_end=covered_date,
            )
        ),
        registration(freshness_sla_days=1),
        ("510300",),
        date(2026, 8, 6),
        min_coverage_ratio=Decimal("0"),
        min_completeness_ratio=Decimal("0"),
    )

    assert decision.publishable is False
    assert decision.reasons == (DECISION_REASON_STALE_OR_FAILED_FRESHNESS,)


def test_decide_provider_publishability_defaults_are_perfect() -> None:
    assert Decimal("1") == DEFAULT_MIN_COVERAGE_RATIO
    assert Decimal("1") == DEFAULT_MIN_COMPLETENESS_RATIO


@pytest.mark.parametrize("threshold", [Decimal("-0.01"), Decimal("1.01"), Decimal("NaN")])
def test_decide_provider_publishability_invalid_thresholds_are_rejected(
    threshold: Decimal,
) -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        decide_provider_publishability(
            coverage_report(symbol_row("510300")),
            registration(),
            ("510300",),
            date(2026, 8, 4),
            min_coverage_ratio=threshold,
        )


@pytest.mark.parametrize("threshold", [0, 0.5, "0.5", True])
def test_decide_provider_publishability_threshold_must_be_decimal(
    threshold: object,
) -> None:
    with pytest.raises(ValueError, match="must be a Decimal"):
        decide_provider_publishability(
            coverage_report(symbol_row("510300")),
            registration(),
            ("510300",),
            date(2026, 8, 4),
            min_completeness_ratio=threshold,  # type: ignore[arg-type]
        )


def test_decision_from_score_rejects_non_score_input() -> None:
    with pytest.raises(ValueError, match="score must be a ProviderQualityScore"):
        decision_from_score(object())  # type: ignore[arg-type]


@pytest.mark.parametrize("threshold", [Decimal("-0.5"), Decimal("1.5"), Decimal("NaN")])
def test_decision_from_score_invalid_threshold_is_rejected(
    threshold: Decimal,
) -> None:
    score = evaluate_provider_quality(
        coverage_report(symbol_row("510300")),
        registration(),
        ("510300",),
        date(2026, 8, 4),
    )

    with pytest.raises(ValueError):
        decision_from_score(score, min_coverage_ratio=threshold)


def test_provider_publish_decision_is_immutable() -> None:
    decision = decide_provider_publishability(
        coverage_report(symbol_row("510300")),
        registration(),
        ("510300",),
        date(2026, 8, 4),
    )

    with pytest.raises(FrozenInstanceError):
        decision.publishable = False  # type: ignore[misc]


def test_decide_provider_publishability_is_deterministic() -> None:
    arguments = (
        coverage_report(symbol_row("510300")),
        registration(reliability_score=Decimal("0.70")),
        ("510300", "159915"),
        date(2026, 8, 4),
    )

    first = decide_provider_publishability(*arguments)
    second = decide_provider_publishability(*arguments)

    assert first == second
    assert first.reasons == second.reasons


def test_decision_from_score_is_deterministic_and_ordered() -> None:
    error = CoverageError(
        provider_key="fixture_dev",
        symbol="510300",
        code="provider_error",
        message="failed",
    )
    score = evaluate_provider_quality(
        coverage_report(symbol_row("510300", errors=(error,))),
        registration(),
        ("510300",),
        date(2026, 8, 4),
    )

    first = decision_from_score(score)
    second = decision_from_score(score)

    assert first == second
    assert first.reasons == second.reasons


def test_decide_provider_publishability_reasons_order_is_stable() -> None:
    error = CoverageError(
        provider_key="fixture_dev",
        symbol="510300",
        code="provider_error",
        message="failed",
    )
    decision = decide_provider_publishability(
        coverage_report(symbol_row("159915"), symbol_row("510300", errors=(error,))),
        registration(),
        ("510300", "159915"),
        date(2026, 8, 5),
    )

    assert decision.publishable is False
    assert decision.reasons == (
        DECISION_REASON_LOW_COVERAGE,
        DECISION_REASON_STALE_OR_FAILED_FRESHNESS,
        DECISION_REASON_FAILED_SYMBOLS,
    )
