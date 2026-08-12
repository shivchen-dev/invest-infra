"""Focused unit tests for the Stage 4B Market Breadth builder.

The builder is a pure aggregator — the only persistence-free slice of
the Market Breadth feature — so the contract is verified entirely in
domain tests. The module exposes two algorithm versions:

* :func:`invest_domain.analytics.market_breadth.build_market_breadth`
  — the **v1** contract: three ratios
  (``advancing_ratio`` / ``declining_ratio`` /
  ``above_ma20_ratio``), default algorithm version ``"1.0.0"``. The
  v1 builder ignores the v2 input fields entirely so a v1 caller
  (the Stage 4B Market Breadth pipeline) that only supplies v1
  fields still gets ``COMPLETE / FRESH`` for a fully normal-trading
  universe.
* :func:`invest_domain.analytics.market_breadth.build_market_breadth_v2`
  — the **v2** contract: six ratios (the v1 trio plus
  ``above_ma60_ratio`` / ``new_high_ratio`` / ``new_low_ratio``),
  default algorithm version ``"2.0.0"``. The v2 builder publishes
  the affected v2 ratio as ``None`` and downgrades the snapshot to
  ``PARTIAL / FRESH`` whenever a normal-trading instrument is
  missing any v2 field.

The test file mirrors that split: ``test_v1_*`` functions pin the
v1 contract, ``test_v2_*`` functions pin the v2 contract,
``test_input_*`` functions pin the shared
:class:`MarketBreadthInput` dataclass, and
``test_observation_*`` functions pin the parent
:class:`MarketObservationSnapshot` / :class:`MarketObservation`
invariants both builders rely on. The two contracts are not
duplicated: every assertion belongs to exactly one version.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from invest_domain.analytics.market_breadth import (
    ABOVE_MA20_RATIO,
    ABOVE_MA60_RATIO,
    ADVANCING_RATIO,
    DECLINING_RATIO,
    NEW_HIGH_RATIO,
    NEW_LOW_RATIO,
    TRADING_STATUS_NORMAL,
    TRADING_STATUS_SUSPENDED,
    TRADING_STATUS_UNKNOWN,
    MarketBreadthInput,
    build_market_breadth,
    build_market_breadth_v2,
)
from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)
from invest_domain.research.models import FreshnessStatus, QualityStatus

AS_OF = date(2026, 8, 7)
INPUT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

V1_OUTPUT_KEYS = frozenset(
    {
        ADVANCING_RATIO,
        DECLINING_RATIO,
        ABOVE_MA20_RATIO,
    }
)
V2_OUTPUT_KEYS = frozenset(
    {
        ADVANCING_RATIO,
        DECLINING_RATIO,
        ABOVE_MA20_RATIO,
        ABOVE_MA60_RATIO,
        NEW_HIGH_RATIO,
        NEW_LOW_RATIO,
    }
)

# Five-instrument fixture (v2-complete). Tradable universe: 0, 1, 2, 3
# (instrument 4 is suspended).
# v1 ratios over 4 tradable:
#   advancing: 0, 1 -> 2/4 = 0.5
#   declining: 3     -> 1/4 = 0.25
#   above_ma20: 0, 1, 2 (close=11>=10, 12>=11, 10>=10) -> 3/4 = 0.75
# v2 ratios over 4 tradable:
#   above_ma60: 0, 1, 2 (11>=9, 12>=10, 10>=10) -> 3/4 = 0.75
#   new_high: 0, 1 -> 2/4 = 0.5
#   new_low: 3 -> 1/4 = 0.25
INSTRUMENTS = tuple(UUID(f"00000000-0000-4000-8000-00000000000{i}") for i in range(1, 6))


def _input(
    instrument_id: UUID,
    *,
    close: str,
    prev_close: str,
    ma20: str,
    trading_status: str = TRADING_STATUS_NORMAL,
    observed_date: date = AS_OF,
    ma60: str | None = None,
    is_new_high: bool | None = None,
    is_new_low: bool | None = None,
) -> MarketBreadthInput:
    return MarketBreadthInput(
        instrument_id=instrument_id,
        close=Decimal(close),
        prev_close=Decimal(prev_close),
        ma20=Decimal(ma20),
        observed_date=observed_date,
        trading_status=trading_status,
        ma60=Decimal(ma60) if ma60 is not None else None,
        is_new_high=is_new_high,
        is_new_low=is_new_low,
    )


def _v1_only_universe() -> tuple[MarketBreadthInput, ...]:
    return (
        _input(
            INSTRUMENTS[0],
            close="11",
            prev_close="10",
            ma20="10",
        ),
        _input(
            INSTRUMENTS[1],
            close="12",
            prev_close="10",
            ma20="11",
        ),
        _input(
            INSTRUMENTS[2],
            close="10",
            prev_close="10",
            ma20="10",
        ),
        _input(
            INSTRUMENTS[3],
            close="9",
            prev_close="10",
            ma20="10",
        ),
    )


def _v2_complete_universe() -> tuple[MarketBreadthInput, ...]:
    return (
        _input(
            INSTRUMENTS[0],
            close="11",
            prev_close="10",
            ma20="10",
            ma60="9",
            is_new_high=True,
            is_new_low=False,
        ),
        _input(
            INSTRUMENTS[1],
            close="12",
            prev_close="10",
            ma20="11",
            ma60="10",
            is_new_high=True,
            is_new_low=False,
        ),
        _input(
            INSTRUMENTS[2],
            close="10",
            prev_close="10",
            ma20="10",
            ma60="10",
            is_new_high=False,
            is_new_low=False,
        ),
        _input(
            INSTRUMENTS[3],
            close="9",
            prev_close="10",
            ma20="10",
            ma60="10",
            is_new_high=False,
            is_new_low=True,
        ),
        _input(
            INSTRUMENTS[4],
            close="10",
            prev_close="10",
            ma20="10",
            trading_status=TRADING_STATUS_SUSPENDED,
        ),
    )


# ---------------------------------------------------------------------------
# v1 builder
# ---------------------------------------------------------------------------


def test_v1_snapshot_hash_and_observation_ids_are_stable_and_order_independent() -> None:
    first = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=_v1_only_universe(),
        as_of_date=AS_OF,
    )
    second = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=tuple(reversed(_v1_only_universe())),
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


def test_v1_snapshot_metadata_is_pinned_to_ashare_universe_v1_contract() -> None:
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=_v1_only_universe(),
        as_of_date=AS_OF,
    )
    assert snapshot.scope_type == "ashare_universe"
    assert snapshot.scope_key == "ashare_active_universe_v1"
    assert snapshot.algorithm_version == "1.0.0"
    assert snapshot.input_snapshot_id == INPUT_ID
    assert snapshot.as_of_date == AS_OF
    assert {item.observation_key for item in snapshot.observations} == V1_OUTPUT_KEYS
    for item in snapshot.observations:
        assert item.unit == "ratio"
        assert item.source_kind == "analytics"
        assert item.source_ref == "market_breadth:1.0.0"


def test_v1_ratios_match_documented_predicates_for_complete_universe() -> None:
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=_v1_only_universe(),
        as_of_date=AS_OF,
    )
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    # Tradable universe: 4 instruments.
    # 2 advancing (0, 1) out of 4 -> 0.5
    # 1 declining (3) out of 4     -> 0.25
    # 3 above-or-equal-ma20 (0, 1, 2) out of 4 -> 0.75
    # (instrument 3: close=9, ma20=10, so close < ma20)
    assert by_key[ADVANCING_RATIO] == Decimal("0.50000000")
    assert by_key[DECLINING_RATIO] == Decimal("0.25000000")
    assert by_key[ABOVE_MA20_RATIO] == Decimal("0.75000000")


def test_v1_ratios_are_clipped_to_zero_one_and_quantised_to_eight_decimals() -> None:
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="99",
                prev_close="1",
                ma20="1",
            ),
        ),
        as_of_date=AS_OF,
    )
    for item in snapshot.observations:
        if isinstance(item.value, Decimal):
            assert Decimal("0") <= item.value <= Decimal("1")
            # 8 decimal places, ROUND_HALF_EVEN
            assert -item.value.as_tuple().exponent <= 8


def test_v1_default_algorithm_version_is_one() -> None:
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=_v1_only_universe(),
        as_of_date=AS_OF,
    )
    assert snapshot.algorithm_version == "1.0.0"
    for item in snapshot.observations:
        assert item.source_ref == "market_breadth:1.0.0"


def test_v1_empty_input_fails_closed_with_invalid_failed_snapshot() -> None:
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=(),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.INVALID
    assert snapshot.freshness_status is FreshnessStatus.FAILED
    assert all(item.value is None for item in snapshot.observations)
    assert {item.observation_key for item in snapshot.observations} == V1_OUTPUT_KEYS


def test_v1_stale_input_fails_closed_with_invalid_stale_snapshot() -> None:
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


def test_v1_unknown_status_promotes_snapshot_to_partial_fresh() -> None:
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="10",
                prev_close="9",
                ma20="9",
            ),
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
    # Only INSTRUMENTS[0] is tradable; v1 ratios reduce to 1.0 / 0.0.
    assert by_key[ADVANCING_RATIO] == Decimal("1.00000000")
    assert by_key[DECLINING_RATIO] == Decimal("0.00000000")
    assert by_key[ABOVE_MA20_RATIO] == Decimal("1.00000000")


def test_v1_all_suspended_universe_publishes_zero_ratios_without_failing() -> None:
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
    for key in V1_OUTPUT_KEYS:
        assert by_key[key] == Decimal("0.00000000"), key


def test_v1_above_ma20_uses_ge_predicate_so_equal_is_counted() -> None:
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="10",
                prev_close="10",
                ma20="10",
            ),
        ),
        as_of_date=AS_OF,
    )
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    assert by_key[ADVANCING_RATIO] == Decimal("0.00000000")
    assert by_key[DECLINING_RATIO] == Decimal("0.00000000")
    assert by_key[ABOVE_MA20_RATIO] == Decimal("1.00000000")


def test_v1_rejects_empty_input_snapshot_id() -> None:
    with pytest.raises(ValueError):
        build_market_breadth(
            input_snapshot_id="",
            instruments=_v1_only_universe(),
            as_of_date=AS_OF,
        )


def test_v1_rejects_non_date_as_of_date() -> None:
    with pytest.raises(TypeError):
        build_market_breadth(
            input_snapshot_id=INPUT_ID,
            instruments=_v1_only_universe(),
            as_of_date="2026-08-07",  # type: ignore[arg-type]
        )


def test_v1_output_observation_keys_and_unit_are_pinned() -> None:
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=_v1_only_universe(),
        as_of_date=AS_OF,
    )
    # Observation iteration is sorted by key by the parent dataclass;
    # the first observation must be the alphabetically smallest key —
    # ``above_ma20_ratio``.
    assert [item.observation_key for item in snapshot.observations] == sorted(
        V1_OUTPUT_KEYS
    )
    assert snapshot.observations[0].observation_key == ABOVE_MA20_RATIO


def test_v1_ignores_v2_input_fields() -> None:
    # v1 callers that happen to set the v2 input fields still get
    # the v1 contract: three ratios, ``COMPLETE / FRESH`` for a
    # fully normal-trading universe, algorithm version ``"1.0.0"``.
    # The v2 fields are accepted on the input (the dataclass
    # validates their types) but never reach the v1 output.
    snapshot = build_market_breadth(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="11",
                prev_close="10",
                ma20="10",
                ma60="9",
                is_new_high=True,
                is_new_low=False,
            ),
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.COMPLETE
    assert snapshot.algorithm_version == "1.0.0"
    assert {item.observation_key for item in snapshot.observations} == V1_OUTPUT_KEYS


# ---------------------------------------------------------------------------
# v2 builder
# ---------------------------------------------------------------------------


def test_v2_snapshot_hash_and_observation_ids_are_stable_and_order_independent() -> None:
    first = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=_v2_complete_universe(),
        as_of_date=AS_OF,
    )
    second = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=tuple(reversed(_v2_complete_universe())),
        as_of_date=AS_OF,
    )
    assert first == second
    assert first.content_hash == second.content_hash
    assert first.snapshot_id == second.snapshot_id
    assert first.snapshot_id == f"mos:{first.content_hash[:32]}"
    assert first.quality_status is QualityStatus.COMPLETE
    assert first.freshness_status is FreshnessStatus.FRESH


def test_v2_snapshot_metadata_is_pinned_to_ashare_universe_v2_contract() -> None:
    snapshot = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=_v2_complete_universe(),
        as_of_date=AS_OF,
    )
    assert snapshot.scope_type == "ashare_universe"
    assert snapshot.scope_key == "ashare_active_universe_v1"
    assert snapshot.algorithm_version == "2.0.0"
    assert snapshot.input_snapshot_id == INPUT_ID
    assert snapshot.as_of_date == AS_OF
    assert {item.observation_key for item in snapshot.observations} == V2_OUTPUT_KEYS
    for item in snapshot.observations:
        assert item.unit == "ratio"
        assert item.source_kind == "analytics"
        assert item.source_ref == "market_breadth:2.0.0"


def test_v2_ratios_match_documented_predicates_for_complete_universe() -> None:
    snapshot = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=_v2_complete_universe(),
        as_of_date=AS_OF,
    )
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    # Tradable universe: 4 instruments (instrument 4 suspended).
    # v1 ratios (over 4 tradable):
    #   advancing: 0, 1 -> 2/4 = 0.5
    #   declining: 3     -> 1/4 = 0.25
    #   above_ma20: 0, 1, 2 -> 3/4 = 0.75
    # v2 ratios (over 4 tradable):
    #   above_ma60: 0, 1, 2 -> 3/4 = 0.75
    #   new_high: 0, 1 -> 2/4 = 0.5
    #   new_low: 3 -> 1/4 = 0.25
    assert by_key[ADVANCING_RATIO] == Decimal("0.50000000")
    assert by_key[DECLINING_RATIO] == Decimal("0.25000000")
    assert by_key[ABOVE_MA20_RATIO] == Decimal("0.75000000")
    assert by_key[ABOVE_MA60_RATIO] == Decimal("0.75000000")
    assert by_key[NEW_HIGH_RATIO] == Decimal("0.50000000")
    assert by_key[NEW_LOW_RATIO] == Decimal("0.25000000")


def test_v2_ratios_are_clipped_to_zero_one_and_quantised_to_eight_decimals() -> None:
    snapshot = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="99",
                prev_close="1",
                ma20="1",
                ma60="1",
                is_new_high=True,
                is_new_low=False,
            ),
        ),
        as_of_date=AS_OF,
    )
    for item in snapshot.observations:
        if isinstance(item.value, Decimal):
            assert Decimal("0") <= item.value <= Decimal("1")
            assert -item.value.as_tuple().exponent <= 8


def test_v2_default_algorithm_version_is_two() -> None:
    snapshot = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=_v2_complete_universe(),
        as_of_date=AS_OF,
    )
    assert snapshot.algorithm_version == "2.0.0"
    for item in snapshot.observations:
        assert item.source_ref == "market_breadth:2.0.0"


def test_v2_empty_input_fails_closed_with_invalid_failed_snapshot() -> None:
    snapshot = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=(),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.INVALID
    assert snapshot.freshness_status is FreshnessStatus.FAILED
    assert all(item.value is None for item in snapshot.observations)
    assert {item.observation_key for item in snapshot.observations} == V2_OUTPUT_KEYS


def test_v2_stale_input_fails_closed_with_invalid_stale_snapshot() -> None:
    snapshot = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="10",
                prev_close="9",
                ma20="9",
                ma60="9",
                is_new_high=True,
                is_new_low=False,
                observed_date=date(2026, 8, 6),
            ),
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.INVALID
    assert snapshot.freshness_status is FreshnessStatus.STALE
    assert all(item.value is None for item in snapshot.observations)


def test_v2_unknown_status_promotes_snapshot_to_partial_fresh() -> None:
    snapshot = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="10",
                prev_close="9",
                ma20="9",
            ),
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
    # Only INSTRUMENTS[0] is tradable; v1 ratios reduce to 1.0 / 0.0
    # and the v2 ratios are None because the tradable instrument is
    # missing every v2 field.
    assert by_key[ADVANCING_RATIO] == Decimal("1.00000000")
    assert by_key[DECLINING_RATIO] == Decimal("0.00000000")
    assert by_key[ABOVE_MA20_RATIO] == Decimal("1.00000000")
    assert by_key[ABOVE_MA60_RATIO] is None
    assert by_key[NEW_HIGH_RATIO] is None
    assert by_key[NEW_LOW_RATIO] is None


def test_v2_all_suspended_universe_publishes_six_known_zeros() -> None:
    snapshot = build_market_breadth_v2(
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
    for key in V2_OUTPUT_KEYS:
        assert by_key[key] == Decimal("0.00000000"), key


def test_v2_all_suspended_with_v2_fields_still_publishes_six_known_zeros() -> None:
    # All-suspended denominator-zero branch must be agnostic to
    # whether the suspended instruments carry v2 fields — the
    # six-zero shape is the same.
    snapshot = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="10",
                prev_close="9",
                ma20="9",
                trading_status=TRADING_STATUS_SUSPENDED,
                ma60=Decimal("9"),
                is_new_high=True,
                is_new_low=False,
            ),
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.COMPLETE
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    for key in V2_OUTPUT_KEYS:
        assert by_key[key] == Decimal("0.00000000"), key


def test_v2_above_ma60_uses_ge_predicate_so_equal_is_counted() -> None:
    snapshot = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="10",
                prev_close="9",
                ma20="9",
                ma60="10",
                is_new_high=False,
                is_new_low=False,
            ),
        ),
        as_of_date=AS_OF,
    )
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    assert by_key[ABOVE_MA60_RATIO] == Decimal("1.00000000")


def test_v2_v1_only_partial_publishes_v1_ratios_and_none_v2_ratios() -> None:
    # A v1-only fixture handed to the v2 builder: the v1 ratios
    # are computed normally from the tradable universe; every v2
    # ratio is published as ``None``; the snapshot is
    # ``PARTIAL / FRESH`` because the v2 surface is incomplete.
    snapshot = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=_v1_only_universe(),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.PARTIAL
    assert snapshot.freshness_status is FreshnessStatus.FRESH
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    # 2 advancing (0, 1) out of 4 tradable -> 0.5
    # 1 declining (3) out of 4 tradable     -> 0.25
    # 3 above-ma20 (0, 1, 2) out of 4 tradable -> 0.75
    assert by_key[ADVANCING_RATIO] == Decimal("0.50000000")
    assert by_key[DECLINING_RATIO] == Decimal("0.25000000")
    assert by_key[ABOVE_MA20_RATIO] == Decimal("0.75000000")
    # v2 surface incomplete: every v2 ratio is None.
    assert by_key[ABOVE_MA60_RATIO] is None
    assert by_key[NEW_HIGH_RATIO] is None
    assert by_key[NEW_LOW_RATIO] is None


def test_v2_per_metric_completeness_is_independent() -> None:
    # Instrument 0 is v2-complete; instrument 1 is missing only
    # ``ma60``. The snapshot is ``PARTIAL / FRESH``;
    # ``above_ma60_ratio`` is ``None``; ``new_high_ratio`` and
    # ``new_low_ratio`` keep computing normally from the tradable
    # universe.
    snapshot = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="11",
                prev_close="10",
                ma20="10",
                ma60="9",
                is_new_high=True,
                is_new_low=True,
            ),
            _input(
                INSTRUMENTS[1],
                close="9",
                prev_close="10",
                ma20="10",
                is_new_high=False,
                is_new_low=False,
            ),
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.PARTIAL
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    assert by_key[ABOVE_MA60_RATIO] is None
    assert by_key[NEW_HIGH_RATIO] == Decimal("0.50000000")
    assert by_key[NEW_LOW_RATIO] == Decimal("0.50000000")


def test_v2_mixed_v2_missing_marks_only_affected_ratio_as_none() -> None:
    # Instrument 0 is v2-complete; instrument 1 is missing only
    # ``is_new_low``. ``above_ma60_ratio`` and ``new_high_ratio``
    # compute; ``new_low_ratio`` is None.
    snapshot = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="11",
                prev_close="10",
                ma20="10",
                ma60="9",
                is_new_high=True,
                is_new_low=False,
            ),
            _input(
                INSTRUMENTS[1],
                close="9",
                prev_close="10",
                ma20="10",
                ma60="10",
                is_new_high=False,
            ),
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.PARTIAL
    assert snapshot.freshness_status is FreshnessStatus.FRESH
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    assert by_key[ADVANCING_RATIO] == Decimal("0.50000000")
    assert by_key[DECLINING_RATIO] == Decimal("0.50000000")
    assert by_key[ABOVE_MA20_RATIO] == Decimal("0.50000000")
    assert by_key[ABOVE_MA60_RATIO] == Decimal("0.50000000")
    assert by_key[NEW_HIGH_RATIO] == Decimal("0.50000000")
    assert by_key[NEW_LOW_RATIO] is None


def test_v2_rejects_empty_input_snapshot_id() -> None:
    with pytest.raises(ValueError):
        build_market_breadth_v2(
            input_snapshot_id="",
            instruments=_v2_complete_universe(),
            as_of_date=AS_OF,
        )


def test_v2_rejects_non_date_as_of_date() -> None:
    with pytest.raises(TypeError):
        build_market_breadth_v2(
            input_snapshot_id=INPUT_ID,
            instruments=_v2_complete_universe(),
            as_of_date="2026-08-07",  # type: ignore[arg-type]
        )


def test_v2_output_observation_keys_and_unit_are_pinned() -> None:
    snapshot = build_market_breadth_v2(
        input_snapshot_id=INPUT_ID,
        instruments=_v2_complete_universe(),
        as_of_date=AS_OF,
    )
    # Observation iteration is sorted by key by the parent dataclass;
    # the first observation must be the alphabetically smallest key —
    # ``above_ma20_ratio``.
    assert [item.observation_key for item in snapshot.observations] == sorted(
        V2_OUTPUT_KEYS
    )
    assert snapshot.observations[0].observation_key == ABOVE_MA20_RATIO


# ---------------------------------------------------------------------------
# Shared input dataclass validation
# ---------------------------------------------------------------------------


def test_input_rejects_malformed_values() -> None:
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
        MarketBreadthInput(**{**base_kwargs, "ma60": Decimal("0")})
    with pytest.raises(ValueError):
        MarketBreadthInput(**{**base_kwargs, "ma60": Decimal("-1")})
    with pytest.raises(TypeError):
        MarketBreadthInput(**{**base_kwargs, "ma60": "10"})
    with pytest.raises(TypeError):
        MarketBreadthInput(**{**base_kwargs, "is_new_high": 1})
    with pytest.raises(TypeError):
        MarketBreadthInput(**{**base_kwargs, "is_new_low": 0})
    with pytest.raises(ValueError):
        MarketBreadthInput(**{**base_kwargs, "trading_status": "halted"})


# ---------------------------------------------------------------------------
# Parent snapshot / observation invariants
# ---------------------------------------------------------------------------


def test_observation_and_snapshot_are_immutable() -> None:
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
        snapshot.algorithm_version = "2.0.0"  # type: ignore[misc]
