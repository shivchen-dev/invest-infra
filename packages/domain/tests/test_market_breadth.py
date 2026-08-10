"""Focused unit tests for the Stage 4B Market Breadth builder.

The builder is a pure aggregator — the only persistence-free slice of
the Market Breadth feature — so the contract is verified entirely in
domain tests:

- hash / observation-id stability (mirror the Stage 4B Market
  Temperature contract tests);
- the three published ratios are clipped to ``[0, 1]`` and
  quantised to 8 decimal places;
- empty / partial / unknown / stale inputs fail closed through the
  shared ``MarketObservationSnapshot`` quality / freshness vocabulary;
- the input dataclass rejects malformed values;
- the snapshot pins the ``scope_type`` / ``scope_key`` to the
  frozen all-A-share universe contract.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from invest_domain.analytics.market_breadth import (
    ABOVE_MA20_RATIO,
    ADVANCING_RATIO,
    DECLINING_RATIO,
    TRADING_STATUS_NORMAL,
    TRADING_STATUS_SUSPENDED,
    TRADING_STATUS_UNKNOWN,
    MarketBreadthInput,
    build_market_breadth,
)
from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)
from invest_domain.research.models import FreshnessStatus, QualityStatus

AS_OF = date(2026, 8, 7)
INPUT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

# Five-instrument fixture: 2 advancing, 1 flat, 1 declining, 1 suspended.
# Above-MA20: instruments with close >= ma20 are 0, 1, 2 (three out of
# four tradable; instrument 3 has close=9 < ma20=10).
INSTRUMENTS = tuple(UUID(f"00000000-0000-4000-8000-00000000000{i}") for i in range(1, 6))


def _input(
    instrument_id: UUID,
    *,
    close: str,
    prev_close: str,
    ma20: str,
    trading_status: str = TRADING_STATUS_NORMAL,
    observed_date: date = AS_OF,
) -> MarketBreadthInput:
    return MarketBreadthInput(
        instrument_id=instrument_id,
        close=Decimal(close),
        prev_close=Decimal(prev_close),
        ma20=Decimal(ma20),
        observed_date=observed_date,
        trading_status=trading_status,
    )


def _complete_universe() -> tuple[MarketBreadthInput, ...]:
    return (
        _input(INSTRUMENTS[0], close="11", prev_close="10", ma20="10"),
        _input(INSTRUMENTS[1], close="12", prev_close="10", ma20="11"),
        _input(INSTRUMENTS[2], close="10", prev_close="10", ma20="10"),
        _input(INSTRUMENTS[3], close="9", prev_close="10", ma20="10"),
        _input(
            INSTRUMENTS[4],
            close="10",
            prev_close="10",
            ma20="10",
            trading_status=TRADING_STATUS_SUSPENDED,
        ),
    )


def test_snapshot_hash_and_observation_ids_are_stable_and_order_independent():
    first = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=_complete_universe(),
        as_of_date=AS_OF,
    )
    second = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=tuple(reversed(_complete_universe())),
        as_of_date=AS_OF,
    )
    assert first == second
    assert first.content_hash == second.content_hash
    first_hashes = {item.observation_key: item.item_hash for item in first.observations}
    second_hashes = {item.observation_key: item.item_hash for item in second.observations}
    assert first_hashes == second_hashes
    assert first.snapshot_id == second.snapshot_id
    assert first.snapshot_id == f"mos:{first.content_hash[:32]}"
    assert first.quality_status is QualityStatus.COMPLETE
    assert first.freshness_status is FreshnessStatus.FRESH


def test_snapshot_metadata_is_pinned_to_ashare_universe_contract():
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=_complete_universe(),
        as_of_date=AS_OF,
    )
    assert snapshot.scope_type == "ashare_universe"
    assert snapshot.scope_key == "ashare_active_universe_v1"
    assert snapshot.algorithm_version == "1.0.0"
    assert snapshot.input_snapshot_id == INPUT_ID
    assert snapshot.as_of_date == AS_OF
    assert {item.observation_key for item in snapshot.observations} == {
        ADVANCING_RATIO,
        DECLINING_RATIO,
        ABOVE_MA20_RATIO,
    }
    for item in snapshot.observations:
        assert item.unit == "ratio"
        assert item.source_kind == "analytics"
        assert item.source_ref == "market_breadth:1.0.0"


def test_ratios_match_documented_predicates_for_complete_universe():
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=_complete_universe(),
        as_of_date=AS_OF,
    )
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    # Tradable universe: instruments 0, 1, 2, 3 (instrument 4 is suspended).
    # 2 advancing (0, 1) out of 4 tradable -> 0.5
    # 1 declining (3) out of 4 tradable -> 0.25
    # 3 above-or-equal-ma20 (0, 1, 2) out of 4 tradable -> 0.75
    #   (instrument 3: close=9, ma20=10, so close < ma20)
    assert by_key[ADVANCING_RATIO] == Decimal("0.50000000")
    assert by_key[DECLINING_RATIO] == Decimal("0.25000000")
    assert by_key[ABOVE_MA20_RATIO] == Decimal("0.75000000")


def test_ratios_are_clipped_to_zero_one_and_quantised_to_eight_decimals():
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=(_input(INSTRUMENTS[0], close="99", prev_close="1", ma20="1"),),
        as_of_date=AS_OF,
    )
    for item in snapshot.observations:
        if isinstance(item.value, Decimal):
            assert Decimal("0") <= item.value <= Decimal("1")
            # 8 decimal places, ROUND_HALF_EVEN
            assert -item.value.as_tuple().exponent <= 8


def test_empty_input_fails_closed_with_invalid_failed_snapshot():
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=(),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.INVALID
    assert snapshot.freshness_status is FreshnessStatus.FAILED
    assert all(item.value is None for item in snapshot.observations)
    assert {item.observation_key for item in snapshot.observations} == {
        ADVANCING_RATIO,
        DECLINING_RATIO,
        ABOVE_MA20_RATIO,
    }


def test_stale_input_fails_closed_with_invalid_stale_snapshot():
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="10",
                prev_close="9",
                ma20="9",
                observed_date=date(2026, 8, 6),
            ),
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.INVALID
    assert snapshot.freshness_status is FreshnessStatus.STALE
    assert all(item.value is None for item in snapshot.observations)


def test_unknown_status_promotes_snapshot_to_partial_fresh():
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(INSTRUMENTS[0], close="10", prev_close="9", ma20="9"),
            _input(
                INSTRUMENTS[1],
                close="10",
                prev_close="9",
                ma20="9",
                trading_status=TRADING_STATUS_UNKNOWN,
            ),
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.PARTIAL
    assert snapshot.freshness_status is FreshnessStatus.FRESH
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    # Only INSTRUMENTS[0] is tradable; both ratios become 1.0 / 1.0.
    assert by_key[ADVANCING_RATIO] == Decimal("1.00000000")
    assert by_key[DECLINING_RATIO] == Decimal("0.00000000")
    assert by_key[ABOVE_MA20_RATIO] == Decimal("1.00000000")


def test_all_suspended_universe_publishes_zero_ratios_without_failing():
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="10",
                prev_close="9",
                ma20="9",
                trading_status=TRADING_STATUS_SUSPENDED,
            ),
            _input(
                INSTRUMENTS[1],
                close="10",
                prev_close="9",
                ma20="9",
                trading_status=TRADING_STATUS_SUSPENDED,
            ),
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.COMPLETE
    assert snapshot.freshness_status is FreshnessStatus.FRESH
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    assert by_key[ADVANCING_RATIO] == Decimal("0.00000000")
    assert by_key[DECLINING_RATIO] == Decimal("0.00000000")
    assert by_key[ABOVE_MA20_RATIO] == Decimal("0.00000000")


def test_above_ma20_uses_ge_predicate_so_equal_is_counted():
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=(_input(INSTRUMENTS[0], close="10", prev_close="10", ma20="10"),),
        as_of_date=AS_OF,
    )
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    assert by_key[ADVANCING_RATIO] == Decimal("0.00000000")
    assert by_key[DECLINING_RATIO] == Decimal("0.00000000")
    assert by_key[ABOVE_MA20_RATIO] == Decimal("1.00000000")


def test_market_breadth_input_rejects_malformed_values():
    base_kwargs = {
        "instrument_id": INSTRUMENTS[0],
        "close": Decimal("10"),
        "prev_close": Decimal("9"),
        "ma20": Decimal("9"),
        "observed_date": AS_OF,
    }
    with pytest.raises(ValueError):
        MarketBreadthInput(**{**base_kwargs, "close": Decimal("0")})
    with pytest.raises(ValueError):
        MarketBreadthInput(**{**base_kwargs, "prev_close": Decimal("-1")})
    with pytest.raises(ValueError):
        MarketBreadthInput(**{**base_kwargs, "ma20": Decimal("NaN")})
    with pytest.raises(ValueError):
        MarketBreadthInput(**{**base_kwargs, "trading_status": "halted"})


def test_build_market_breadth_rejects_empty_input_snapshot_id():
    with pytest.raises(ValueError):
        build_market_breadth(
            input_snapshot_id="", instruments=_complete_universe(), as_of_date=AS_OF
        )


def test_build_market_breadth_rejects_non_date_as_of_date():
    with pytest.raises(TypeError):
        build_market_breadth(
            input_snapshot_id=INPUT_ID,
            instruments=_complete_universe(),
            as_of_date="2026-08-07",  # type: ignore[arg-type]
        )


def test_output_observation_keys_and_unit_are_pinned():
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=_complete_universe(),
        as_of_date=AS_OF,
    )
    # Observation iteration is sorted by key by the parent dataclass; the
    # first observation must be the alphabetically smallest key.
    assert snapshot.observations[0].observation_key == ABOVE_MA20_RATIO
    assert snapshot.observations[1].observation_key == ADVANCING_RATIO
    assert snapshot.observations[2].observation_key == DECLINING_RATIO


def test_snapshot_and_observation_are_immutable_and_validate_inputs():
    with pytest.raises((TypeError, ValueError)):
        MarketObservation(
            observation_key="",
            value=Decimal("1"),
            unit="ratio",
            observed_date=AS_OF,
            source_kind="analytics",
            source_ref="market_breadth:1.0.0",
        )
    snapshot = MarketObservationSnapshot(
        input_snapshot_id=INPUT_ID,
        as_of_date=AS_OF,
        observations=(),
        algorithm_version="1.0.0",
    )
    with pytest.raises((AttributeError, TypeError)):
        snapshot.algorithm_version = "2.0.0"


def test_unknown_below_ma20_treated_as_partial_with_correct_denominator():
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(INSTRUMENTS[0], close="11", prev_close="10", ma20="10"),
            _input(INSTRUMENTS[1], close="9", prev_close="10", ma20="10"),
            _input(
                INSTRUMENTS[2],
                close="9",
                prev_close="9",
                ma20="9",
                trading_status=TRADING_STATUS_UNKNOWN,
            ),
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.PARTIAL
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    # Denominator excludes the unknown instrument -> 2 tradable.
    # Instrument 0: 11>10 (advancing), 11>=10 (above ma20)
    # Instrument 1: 9<10 (declining), 9<10 (below ma20)
    assert by_key[ADVANCING_RATIO] == Decimal("0.50000000")
    assert by_key[DECLINING_RATIO] == Decimal("0.50000000")
    assert by_key[ABOVE_MA20_RATIO] == Decimal("0.50000000")
