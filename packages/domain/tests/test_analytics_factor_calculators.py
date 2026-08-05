"""Focused tests for the GOV-03 Analytics-owned factor-calculator seam.

This slice moves the deterministic
:func:`invest_domain.analytics.factor_calculators.calculate_market_state_factors`
calculator behind an Analytics-owned module while preserving every
existing import path and the byte-for-byte behaviour of the function.

Every assertion in this file pins one of the four invariants the
convergence must keep intact:

1. **Public surface parity** — the new module exposes exactly the
   symbols the prior :mod:`invest_domain.research.factor_calculators`
   module exposed (``FactorCalculationResult`` and
   ````calculate_market_state_factors````) and nothing else.
2. **Identity preservation** — every re-export path
   (``invest_domain.analytics.factor_calculators``,
   :mod:`invest_domain.research.factor_calculators` compat shim,
   :mod:`invest_domain.research` umbrella, top-level
   :mod:`invest_domain` umbrella) resolves to the same class object
   and the same function object. No re-implementation, no copy.
3. **Behavioural parity** — running the function with the same inputs
   returns a value-equal :class:`FactorCalculationResult` regardless of
   which import path was used to obtain the function. Window
   boundaries, empty inputs and exception messages are unchanged.
4. **Seam isolation** — the Analytics module does not re-define any
   Research-only type (e.g. ``EvidencePack``, ``CaseContext``,
   ``ContextPack``); it owns only the calculator and its result type.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

import invest_domain.analytics.factor_calculators as analytics_fc
import invest_domain.research.factor_calculators as compat_fc
from invest_domain import FactorCalculationResult as TopLevelResult
from invest_domain import calculate_market_state_factors as top_level_calc
from invest_domain.analytics.factor_calculators import (
    FactorCalculationResult,
    calculate_market_state_factors,
)
from invest_domain.instruments import InstrumentId
from invest_domain.market_data import Adjust, BarSource, DailyBar, TradingStatus
from invest_domain.research import (
    FACTOR_DEFINITIONS,
    FACTOR_KEYS,
    FactorCalculationResult as ResearchResult,
    QualityStatus,
    calculate_market_state_factors as research_calc,
)
from invest_domain.research.factor_calculators import (
    FactorCalculationResult as CompatResult,
    calculate_market_state_factors as compat_calc,
)


_INSTRUMENT_ID = InstrumentId(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
_OTHER_INSTRUMENT_ID = InstrumentId(UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))
_AS_OF = date(2026, 8, 5)
_SOURCE = BarSource(
    provider_key="analytics_seam_test",
    source_batch_id=UUID("00000000-0000-4000-8000-0000000000aa"),
    observed_at=datetime(2026, 8, 5, 8, tzinfo=timezone.utc),
)


def _bar(
    *,
    trade_date: date,
    close: str | None = "3.10",
    amount: str | None = "15000000",
    trading_status: TradingStatus = TradingStatus.NORMAL,
    revision: int = 1,
) -> DailyBar:
    close_decimal = None if close is None else Decimal(close)
    amount_decimal = None if amount is None else Decimal(amount)
    return DailyBar.build(
        instrument_id=_INSTRUMENT_ID,
        trade_date=trade_date,
        open=close_decimal,
        high=None if close_decimal is None else close_decimal + Decimal("0.01"),
        low=None if close_decimal is None else close_decimal - Decimal("0.01"),
        close=close_decimal,
        prev_close=None,
        volume=Decimal(1000),
        amount=amount_decimal,
        adjustment=Adjust.NONE,
        trading_status=trading_status,
        source=_SOURCE,
        revision=revision,
    )


def _conflicting_bar(
    *,
    trade_date: date,
    close: str,
    amount: str,
    revision: int,
) -> DailyBar:
    return DailyBar.build(
        instrument_id=_INSTRUMENT_ID,
        trade_date=trade_date,
        open=Decimal(close),
        high=Decimal(close) + Decimal("0.01"),
        low=Decimal(close) - Decimal("0.01"),
        close=Decimal(close),
        prev_close=None,
        volume=Decimal(1000),
        amount=Decimal(amount),
        adjustment=Adjust.NONE,
        trading_status=TradingStatus.NORMAL,
        source=_SOURCE,
        revision=revision,
    )


def _bars(count: int) -> tuple[DailyBar, ...]:
    start = _AS_OF - timedelta(days=count + 5)
    return tuple(
        _bar(
            trade_date=start + timedelta(days=index),
            close=f"{3 + index * 0.01:.4f}",
        )
        for index in range(count)
    )


# ---------------------------------------------------------------------------
# 1. Public surface parity
# ---------------------------------------------------------------------------


def test_analytics_module_exposes_only_the_two_expected_symbols() -> None:
    assert set(analytics_fc.__all__) == {
        "FactorCalculationResult",
        "calculate_market_state_factors",
    }


def test_compat_shim_exposes_only_the_two_expected_symbols() -> None:
    assert set(compat_fc.__all__) == {
        "FactorCalculationResult",
        "calculate_market_state_factors",
    }


def test_analytics_module_owns_no_research_only_types() -> None:
    forbidden_research_types = {
        "EvidencePack",
        "CaseContext",
        "InstrumentSnapshot",
        "CandidateContext",
        "SourceReference",
        "ResearchContextPack",
        "ContextItem",
    }
    exported = set(analytics_fc.__all__)
    assert exported.isdisjoint(forbidden_research_types), (
        "Analytics-owned seam leaked a Research-only type: "
        f"{exported & forbidden_research_types}"
    )
    module_globals = set(dir(analytics_fc))
    assert module_globals.isdisjoint(forbidden_research_types), (
        "Analytics-owned seam leaked a Research-only attribute: "
        f"{module_globals & forbidden_research_types}"
    )


# ---------------------------------------------------------------------------
# 2. Identity preservation across every re-export path
# ---------------------------------------------------------------------------


def test_factor_calculation_result_is_identical_across_import_paths() -> None:
    assert FactorCalculationResult is analytics_fc.FactorCalculationResult
    assert FactorCalculationResult is CompatResult
    assert FactorCalculationResult is ResearchResult
    assert FactorCalculationResult is TopLevelResult
    assert FactorCalculationResult.__module__ == "invest_domain.analytics.factor_calculators"


def test_calculator_is_identical_across_import_paths() -> None:
    assert calculate_market_state_factors is analytics_fc.calculate_market_state_factors
    assert calculate_market_state_factors is compat_calc
    assert calculate_market_state_factors is research_calc
    assert calculate_market_state_factors is top_level_calc
    assert calculate_market_state_factors.__module__ == "invest_domain.analytics.factor_calculators"


def test_research_umbrella_resolves_lazily_and_caches() -> None:
    from invest_domain import research as research_module

    first = research_module.FactorCalculationResult
    second = research_module.FactorCalculationResult
    assert first is FactorCalculationResult
    assert second is first
    assert "FactorCalculationResult" in vars(research_module)


def test_research_umbrella_attribute_error_for_unknown_name() -> None:
    from invest_domain import research as research_module

    with pytest.raises(AttributeError, match="has no attribute"):
        research_module.this_name_does_not_exist


# ---------------------------------------------------------------------------
# 3. Behavioural parity
# ---------------------------------------------------------------------------


def _value(result: FactorCalculationResult, factor_key: str) -> Decimal | None:
    for observation in result.factors:
        if observation.factor_key == factor_key:
            return observation.value
    raise AssertionError(factor_key)


def test_calculator_is_deterministic_with_65_bars() -> None:
    bars = _bars(65)
    first = calculate_market_state_factors(
        bars,
        as_of_date=_AS_OF,
        instrument_id=_INSTRUMENT_ID,
    )
    second = calculate_market_state_factors(
        bars,
        as_of_date=_AS_OF,
        instrument_id=_INSTRUMENT_ID,
    )
    assert first == second
    assert first.factors == second.factors
    assert first.market_snapshot == second.market_snapshot
    assert first.data_quality == second.data_quality
    assert first.warnings == second.warnings
    assert first.missing_fields == second.missing_fields


def test_calculator_via_compat_path_matches_direct_call() -> None:
    bars = _bars(65)
    direct = calculate_market_state_factors(
        bars, as_of_date=_AS_OF, instrument_id=_INSTRUMENT_ID
    )
    via_compat = compat_calc(bars, as_of_date=_AS_OF, instrument_id=_INSTRUMENT_ID)
    assert via_compat == direct
    assert [obs.item_hash for obs in via_compat.factors] == [
        obs.item_hash for obs in direct.factors
    ]


def test_calculator_via_research_umbrella_matches_direct_call() -> None:
    bars = _bars(65)
    direct = calculate_market_state_factors(
        bars, as_of_date=_AS_OF, instrument_id=_INSTRUMENT_ID
    )
    via_research = research_calc(
        bars, as_of_date=_AS_OF, instrument_id=_INSTRUMENT_ID
    )
    assert via_research == direct


def test_calculator_emits_every_v1_factor_key() -> None:
    bars = _bars(65)
    result = calculate_market_state_factors(
        bars, as_of_date=_AS_OF, instrument_id=_INSTRUMENT_ID
    )
    assert {item.factor_key for item in result.factors} == set(FACTOR_KEYS)
    assert {item.factor_key for item in result.factors} == {
        definition.key for definition in FACTOR_DEFINITIONS
    }


@pytest.mark.parametrize(
    "count, available, missing",
    [
        (19, (), ("distance_ma20", "avg_turnover_amount_20d", "return_20d", "realized_volatility_20d")),
        (20, ("distance_ma20", "avg_turnover_amount_20d"), ("return_20d", "realized_volatility_20d")),
        (21, ("distance_ma20", "avg_turnover_amount_20d", "return_20d", "realized_volatility_20d"), ()),
        (59, (), ("distance_ma60", "max_drawdown_60d", "return_60d")),
        (60, ("distance_ma60", "max_drawdown_60d"), ("return_60d",)),
        (61, ("distance_ma60", "max_drawdown_60d", "return_60d"), ()),
    ],
)
def test_window_boundary_factors_remain_none(
    count: int,
    available: tuple[str, ...],
    missing: tuple[str, ...],
) -> None:
    result = calculate_market_state_factors(
        _bars(count), as_of_date=_AS_OF, instrument_id=_INSTRUMENT_ID
    )
    for factor_key in available:
        assert _value(result, factor_key) is not None, factor_key
    for factor_key in missing:
        assert _value(result, factor_key) is None, factor_key


def test_empty_bars_yield_no_close_or_amount_dependent_factors() -> None:
    result = calculate_market_state_factors(
        (), as_of_date=_AS_OF, instrument_id=_INSTRUMENT_ID
    )
    assert len(result.factors) == len(FACTOR_KEYS)
    assert result.data_quality.observed_trading_days == 0
    assert result.data_quality.valid_price_days == 0
    assert result.market_snapshot.latest_trade_date is None
    assert result.market_snapshot.latest_close is None
    assert _value(result, "data_completeness_60d") == Decimal("0.00000000")
    for factor_key in (
        "return_20d",
        "return_60d",
        "distance_ma20",
        "distance_ma60",
        "realized_volatility_20d",
        "max_drawdown_60d",
        "avg_turnover_amount_20d",
    ):
        assert _value(result, factor_key) is None, factor_key


def test_inferred_instrument_id_when_omitted() -> None:
    bars = _bars(5)
    result = calculate_market_state_factors(bars, as_of_date=_AS_OF)
    assert all(item.instrument_id == _INSTRUMENT_ID for item in result.factors)


def test_mismatched_instrument_id_raises_value_error() -> None:
    bars = _bars(5)
    with pytest.raises(ValueError, match="instrument_id does not match"):
        calculate_market_state_factors(
            bars, as_of_date=_AS_OF, instrument_id=_OTHER_INSTRUMENT_ID
        )


def test_future_bars_are_rejected() -> None:
    bars = _bars(5)
    with pytest.raises(ValueError, match="future"):
        calculate_market_state_factors(
            bars, as_of_date=_AS_OF - timedelta(days=10), instrument_id=_INSTRUMENT_ID
        )


def test_conflicting_revisions_set_conflict_quality() -> None:
    trade_date = _AS_OF - timedelta(days=2)
    bars = (
        _conflicting_bar(
            trade_date=trade_date, close="3.10", amount="15000000", revision=2
        ),
        _conflicting_bar(
            trade_date=trade_date, close="3.50", amount="18000000", revision=2
        ),
    )
    result = calculate_market_state_factors(
        bars, as_of_date=trade_date, instrument_id=_INSTRUMENT_ID
    )
    assert result.data_quality.conflict_detected is True
    assert all(item.quality_status is QualityStatus.CONFLICT for item in result.factors)


def test_factor_observations_carry_deterministic_item_hash() -> None:
    bars = _bars(65)
    result = calculate_market_state_factors(
        bars, as_of_date=_AS_OF, instrument_id=_INSTRUMENT_ID
    )
    hashes = [item.item_hash for item in result.factors]
    assert len(hashes) == len(FACTOR_KEYS)
    assert len(set(hashes)) == len(hashes)
    rerun = calculate_market_state_factors(
        bars, as_of_date=_AS_OF, instrument_id=_INSTRUMENT_ID
    )
    assert [item.item_hash for item in rerun.factors] == hashes


def test_factor_values_are_quantised_to_eight_fractional_digits() -> None:
    bars = _bars(65)
    result = calculate_market_state_factors(
        bars, as_of_date=_AS_OF, instrument_id=_INSTRUMENT_ID
    )
    for item in result.factors:
        if item.value is None:
            continue
        assert item.value.as_tuple().exponent <= -8, item