"""Focused unit tests for the Stage 4C Limit Sentiment builder.

The builder is a pure aggregator — the only persistence-free slice
of the Limit Sentiment feature — so the contract is verified
entirely in domain tests. The module exposes a single v1.0.0
algorithm:

* :func:`invest_domain.analytics.limit_sentiment.build_limit_sentiment`
  — three ratios (``limit_up_ratio`` / ``limit_down_ratio`` /
  ``limit_touch_unknown_ratio``), default algorithm version
  ``"1.0.0"``. Suspended rows are excluded from both denominators;
  ``unknown`` trading status or normal rows missing a limit price
  downgrade the snapshot to ``PARTIAL / FRESH`` and publish
  ``limit_touch_unknown_ratio`` as ``None`` so the operator can
  see the share of the universe that is currently excluded from
  the up/down counts.

The test file mirrors the
:mod:`invest_domain.analytics.market_breadth` layout:
``test_snapshot_*`` functions pin the snapshot-level invariants,
``test_complete_*`` functions pin the documented predicates on a
fully populated universe, ``test_fail_closed_*`` functions pin the
empty / stale / partial / missing-limit fail-closed branches,
``test_input_*`` functions pin the
:class:`LimitSentimentInput` dataclass, and
``test_observation_*`` functions pin the parent
:class:`MarketObservationSnapshot` / :class:`MarketObservation`
invariants the builder relies on.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from invest_domain.analytics.limit_sentiment import (
    LIMIT_DOWN_RATIO,
    LIMIT_TOUCH_UNKNOWN_RATIO,
    LIMIT_UP_RATIO,
    TRADING_STATUS_NORMAL,
    TRADING_STATUS_SUSPENDED,
    TRADING_STATUS_UNKNOWN,
    LimitSentimentInput,
    build_limit_sentiment,
)
from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)
from invest_domain.research.models import FreshnessStatus, QualityStatus

AS_OF = date(2026, 8, 7)
INPUT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")

OUTPUT_KEYS = frozenset(
    {LIMIT_UP_RATIO, LIMIT_DOWN_RATIO, LIMIT_TOUCH_UNKNOWN_RATIO}
)

# Five-instrument fixture: 4 normal + 1 suspended (instrument 4).
# close vs (limit_up_price, limit_down_price):
#   0 -> close=11 == limit_up_price=11 -> limit_up touch
#   1 -> close=12 == limit_up_price=12 -> limit_up touch
#   2 -> close=10 == limit_down_price=10 -> limit_down touch
#   3 -> close=10.5, limit_up=11, limit_down=10 -> no touch
#   4 -> suspended (excluded from both denominators)
# Tradable universe: 4 (0, 1, 2, 3)
# Participants: 4 (every normal row supplies both limit prices)
# limit_up count: 2 (0, 1)   -> 2/4 = 0.5
# limit_down count: 1 (2)    -> 1/4 = 0.25
# blind: 0                  -> 0/4 = 0.0
INSTRUMENTS = tuple(UUID(f"00000000-0000-4000-8000-00000000000{i}") for i in range(1, 6))


def _input(
    instrument_id: UUID,
    *,
    close: str,
    observed_date: date = AS_OF,
    limit_up_price: str | None = None,
    limit_down_price: str | None = None,
    trading_status: str = TRADING_STATUS_NORMAL,
) -> LimitSentimentInput:
    return LimitSentimentInput(
        instrument_id=instrument_id,
        close=Decimal(close),
        observed_date=observed_date,
        limit_up_price=Decimal(limit_up_price) if limit_up_price is not None else None,
        limit_down_price=(
            Decimal(limit_down_price) if limit_down_price is not None else None
        ),
        trading_status=trading_status,
    )


def _complete_universe() -> tuple[LimitSentimentInput, ...]:
    return (
        _input(INSTRUMENTS[0], close="11", limit_up_price="11", limit_down_price="10"),
        _input(INSTRUMENTS[1], close="12", limit_up_price="12", limit_down_price="11"),
        _input(INSTRUMENTS[2], close="10", limit_up_price="11", limit_down_price="10"),
        _input(INSTRUMENTS[3], close="10.5", limit_up_price="11", limit_down_price="10"),
        _input(
            INSTRUMENTS[4],
            close="11",
            limit_up_price="11",
            limit_down_price="10",
            trading_status=TRADING_STATUS_SUSPENDED,
        ),
    )


# ---------------------------------------------------------------------------
# Snapshot-level invariants
# ---------------------------------------------------------------------------


def test_snapshot_hash_and_observation_ids_are_stable_and_order_independent() -> None:
    first = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=_complete_universe(),
        as_of_date=AS_OF,
    )
    second = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=tuple(reversed(_complete_universe())),
        as_of_date=AS_OF,
    )
    assert first == second
    assert first.content_hash == second.content_hash
    assert first.snapshot_id == second.snapshot_id
    assert first.snapshot_id == f"mos:{first.content_hash[:32]}"
    first_hashes = {item.observation_key: item.item_hash for item in first.observations}
    second_hashes = {item.observation_key: item.item_hash for item in second.observations}
    assert first_hashes == second_hashes
    assert first.quality_status is QualityStatus.COMPLETE
    assert first.freshness_status is FreshnessStatus.FRESH


def test_snapshot_metadata_is_pinned_to_ashare_active_universe_v1_contract() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=_complete_universe(),
        as_of_date=AS_OF,
    )
    assert snapshot.scope_type == "ashare_universe"
    assert snapshot.scope_key == "ashare_active_universe_v1"
    assert snapshot.algorithm_version == "1.0.0"
    assert snapshot.input_snapshot_id == INPUT_ID
    assert snapshot.as_of_date == AS_OF
    assert {item.observation_key for item in snapshot.observations} == OUTPUT_KEYS
    for item in snapshot.observations:
        assert item.unit == "ratio"
        assert item.source_kind == "analytics"
        assert item.source_ref == "limit_sentiment:1.0.0"


def test_default_algorithm_version_is_one_zero_zero() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=_complete_universe(),
        as_of_date=AS_OF,
    )
    assert snapshot.algorithm_version == "1.0.0"
    for item in snapshot.observations:
        assert item.source_ref == "limit_sentiment:1.0.0"


def test_output_observation_keys_are_sorted_and_keys_are_unique() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=_complete_universe(),
        as_of_date=AS_OF,
    )
    assert [item.observation_key for item in snapshot.observations] == sorted(
        OUTPUT_KEYS
    )
    assert snapshot.observations[0].observation_key == LIMIT_DOWN_RATIO


# ---------------------------------------------------------------------------
# Complete universe — documented predicates
# ---------------------------------------------------------------------------


def test_complete_ratios_match_documented_predicates() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=_complete_universe(),
        as_of_date=AS_OF,
    )
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    # Tradable universe: 4 (instrument 4 suspended).
    # Participants: 4 (every normal row supplies both limits).
    # limit_up count: 2 (0, 1) -> 2/4 = 0.5
    # limit_down count: 1 (2)  -> 1/4 = 0.25
    # blind: 0                  -> 0/4 = 0.0
    assert by_key[LIMIT_UP_RATIO] == Decimal("0.50000000")
    assert by_key[LIMIT_DOWN_RATIO] == Decimal("0.25000000")
    assert by_key[LIMIT_TOUCH_UNKNOWN_RATIO] == Decimal("0.00000000")


def test_complete_ratios_are_quantised_to_eight_decimals() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(INSTRUMENTS[0], close="11", limit_up_price="11", limit_down_price="10"),
            _input(INSTRUMENTS[1], close="11", limit_up_price="11", limit_down_price="10"),
            _input(INSTRUMENTS[2], close="10", limit_up_price="11", limit_down_price="10"),
        ),
        as_of_date=AS_OF,
    )
    for item in snapshot.observations:
        if isinstance(item.value, Decimal):
            assert -item.value.as_tuple().exponent <= 8


def test_limit_touch_uses_equality_predicate_not_ge() -> None:
    # Close ABOVE limit_up_price is NOT a limit-up touch (equality only).
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(INSTRUMENTS[0], close="12", limit_up_price="11", limit_down_price="10"),
        ),
        as_of_date=AS_OF,
    )
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    assert by_key[LIMIT_UP_RATIO] == Decimal("0.00000000")
    assert by_key[LIMIT_DOWN_RATIO] == Decimal("0.00000000")


def test_equal_close_to_limit_down_counts_as_limit_down_touch() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(INSTRUMENTS[0], close="10", limit_up_price="11", limit_down_price="10"),
        ),
        as_of_date=AS_OF,
    )
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    assert by_key[LIMIT_DOWN_RATIO] == Decimal("1.00000000")


def test_suspended_rows_are_excluded_from_both_denominators() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="11",
                limit_up_price="11",
                limit_down_price="10",
                trading_status=TRADING_STATUS_SUSPENDED,
            ),
            _input(
                INSTRUMENTS[1],
                close="10",
                limit_up_price="11",
                limit_down_price="10",
                trading_status=TRADING_STATUS_SUSPENDED,
            ),
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.COMPLETE
    assert snapshot.freshness_status is FreshnessStatus.FRESH
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    # No tradable rows survive, so every ratio is zero (defensive).
    assert by_key[LIMIT_UP_RATIO] == Decimal("0.00000000")
    assert by_key[LIMIT_DOWN_RATIO] == Decimal("0.00000000")
    assert by_key[LIMIT_TOUCH_UNKNOWN_RATIO] == Decimal("0.00000000")


# ---------------------------------------------------------------------------
# Fail-closed: empty, stale, partial, missing-limit
# ---------------------------------------------------------------------------


def test_empty_input_fails_closed_with_invalid_failed_snapshot() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=(),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.INVALID
    assert snapshot.freshness_status is FreshnessStatus.FAILED
    assert all(item.value is None for item in snapshot.observations)
    assert {item.observation_key for item in snapshot.observations} == OUTPUT_KEYS


def test_stale_observed_date_fails_closed_with_invalid_stale_snapshot() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(
                INSTRUMENTS[0],
                close="11",
                limit_up_price="11",
                limit_down_price="10",
                observed_date=date(2026, 8, 6),
            ),
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.INVALID
    assert snapshot.freshness_status is FreshnessStatus.STALE
    assert all(item.value is None for item in snapshot.observations)


def test_unknown_trading_status_downgrades_to_partial_fresh_and_blinds_unknown_ratio() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(INSTRUMENTS[0], close="11", limit_up_price="11", limit_down_price="10"),
            _input(
                INSTRUMENTS[1],
                close="10",
                limit_up_price="11",
                limit_down_price="10",
                trading_status=TRADING_STATUS_UNKNOWN,
            ),
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.PARTIAL
    assert snapshot.freshness_status is FreshnessStatus.FRESH
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    # Participants: 1 (only INSTRUMENTS[0]); limit-up count: 1 -> 1/1 = 1.0
    assert by_key[LIMIT_UP_RATIO] == Decimal("1.00000000")
    assert by_key[LIMIT_DOWN_RATIO] == Decimal("0.00000000")
    # The unknown row contaminates the blind denominator, so the
    # fail-closed branch publishes the unknown ratio as None.
    assert by_key[LIMIT_TOUCH_UNKNOWN_RATIO] is None


def test_missing_limit_price_on_normal_row_downgrades_to_partial_fresh() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(INSTRUMENTS[0], close="11", limit_up_price="11", limit_down_price="10"),
            _input(INSTRUMENTS[1], close="10"),  # no limit prices supplied
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.PARTIAL
    assert snapshot.freshness_status is FreshnessStatus.FRESH
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    # Participants: 1; limit-up count: 1 -> 1/1 = 1.0
    assert by_key[LIMIT_UP_RATIO] == Decimal("1.00000000")
    assert by_key[LIMIT_DOWN_RATIO] == Decimal("0.00000000")
    assert by_key[LIMIT_TOUCH_UNKNOWN_RATIO] is None


def test_only_limit_down_supplied_on_normal_row_downgrades_to_partial_fresh() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(INSTRUMENTS[0], close="11", limit_up_price="11", limit_down_price="10"),
            _input(INSTRUMENTS[1], close="10", limit_down_price="10"),  # only limit_down
        ),
        as_of_date=AS_OF,
    )
    assert snapshot.quality_status is QualityStatus.PARTIAL
    assert by_key(snapshot)[LIMIT_TOUCH_UNKNOWN_RATIO] is None


def test_missing_limit_rows_are_not_silently_counted_as_limit_up() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(INSTRUMENTS[0], close="11", limit_up_price="11", limit_down_price="10"),
            _input(INSTRUMENTS[1], close="11"),  # close happens to be at the up limit
        ),
        as_of_date=AS_OF,
    )
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    # Participants: 1 (only INSTRUMENTS[0]); the missing-limit row is
    # NEVER folded into the limit-up count even though its close
    # matches a hypothetical upper limit.
    assert by_key[LIMIT_UP_RATIO] == Decimal("1.00000000")


def test_missing_limit_rows_are_not_silently_counted_as_limit_down() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=(
            _input(INSTRUMENTS[0], close="11", limit_up_price="11", limit_down_price="10"),
            _input(INSTRUMENTS[1], close="10"),  # close happens to be at the down limit
        ),
        as_of_date=AS_OF,
    )
    by_key = {item.observation_key: item.value for item in snapshot.observations}
    assert by_key[LIMIT_DOWN_RATIO] == Decimal("0.00000000")


# ---------------------------------------------------------------------------
# Determinism + validation guards
# ---------------------------------------------------------------------------


def test_deterministic_hash_is_stable_across_input_order() -> None:
    first = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=_complete_universe(),
        as_of_date=AS_OF,
    )
    second = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=_complete_universe(),
        as_of_date=AS_OF,
    )
    assert first.content_hash == second.content_hash
    assert first.snapshot_id == second.snapshot_id
    assert first.observations == second.observations


def test_rejects_empty_input_snapshot_id() -> None:
    with pytest.raises(ValueError):
        build_limit_sentiment(
            input_snapshot_id="",
            instruments=_complete_universe(),
            as_of_date=AS_OF,
        )


def test_rejects_non_date_as_of_date() -> None:
    with pytest.raises(TypeError):
        build_limit_sentiment(
            input_snapshot_id=INPUT_ID,
            instruments=_complete_universe(),
            as_of_date="2026-08-07",  # type: ignore[arg-type]
        )


def test_rejects_empty_algorithm_version() -> None:
    with pytest.raises(ValueError):
        build_limit_sentiment(
            input_snapshot_id=INPUT_ID,
            instruments=_complete_universe(),
            as_of_date=AS_OF,
            algorithm_version="",
        )


# ---------------------------------------------------------------------------
# Input dataclass guards
# ---------------------------------------------------------------------------


def test_input_rejects_empty_instrument_id() -> None:
    with pytest.raises(ValueError):
        LimitSentimentInput(
            instrument_id="",
            close=Decimal("11"),
            observed_date=AS_OF,
            limit_up_price=Decimal("11"),
            limit_down_price=Decimal("10"),
        )


def test_input_rejects_non_positive_close() -> None:
    with pytest.raises(ValueError):
        LimitSentimentInput(
            instrument_id=INSTRUMENTS[0],
            close=Decimal("0"),
            observed_date=AS_OF,
            limit_up_price=Decimal("11"),
            limit_down_price=Decimal("10"),
        )


def test_input_rejects_non_finite_close() -> None:
    with pytest.raises(ValueError):
        LimitSentimentInput(
            instrument_id=INSTRUMENTS[0],
            close=Decimal("NaN"),
            observed_date=AS_OF,
            limit_up_price=Decimal("11"),
            limit_down_price=Decimal("10"),
        )


def test_input_rejects_non_positive_limit_up_price() -> None:
    with pytest.raises(ValueError):
        LimitSentimentInput(
            instrument_id=INSTRUMENTS[0],
            close=Decimal("11"),
            observed_date=AS_OF,
            limit_up_price=Decimal("0"),
            limit_down_price=Decimal("10"),
        )


def test_input_rejects_non_positive_limit_down_price() -> None:
    with pytest.raises(ValueError):
        LimitSentimentInput(
            instrument_id=INSTRUMENTS[0],
            close=Decimal("11"),
            observed_date=AS_OF,
            limit_up_price=Decimal("11"),
            limit_down_price=Decimal("-1"),
        )


def test_input_rejects_invalid_trading_status() -> None:
    with pytest.raises(ValueError):
        LimitSentimentInput(
            instrument_id=INSTRUMENTS[0],
            close=Decimal("11"),
            observed_date=AS_OF,
            limit_up_price=Decimal("11"),
            limit_down_price=Decimal("10"),
            trading_status="halted",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def by_key(snapshot: MarketObservationSnapshot) -> dict[str, Decimal | None]:
    return {item.observation_key: item.value for item in snapshot.observations}


def test_parent_market_observation_invariants_are_respected() -> None:
    snapshot = build_limit_sentiment(
        input_snapshot_id=INPUT_ID,
        instruments=_complete_universe(),
        as_of_date=AS_OF,
    )
    for item in snapshot.observations:
        assert isinstance(item, MarketObservation)
        assert item.item_hash  # canonical_sha256 projection is non-empty
        assert item.observed_date == AS_OF
