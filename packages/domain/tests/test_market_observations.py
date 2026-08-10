from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)
from invest_domain.analytics.market_temperature import (
    LIQUIDITY_NORMALIZER_VERSION,
    LIQUIDITY_SCALE,
    REQUIRED_FACTOR_KEYS,
    build_market_temperature,
)
from invest_domain.instruments import InstrumentId
from invest_domain.research.models import FactorObservation, FreshnessStatus, QualityStatus

AS_OF = date(2026, 8, 7)
INPUT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
INSTRUMENTS = [
    InstrumentId(UUID("00000000-0000-4000-8000-000000000001")),
    InstrumentId(UUID("00000000-0000-4000-8000-000000000002")),
]
REQUIRED_KEYS = REQUIRED_FACTOR_KEYS


def factor(
    instrument_id,
    key,
    value,
    *,
    quality=QualityStatus.COMPLETE,
    observed_date=AS_OF,
    window=20,
):
    return FactorObservation(
        factor_key=key,
        instrument_id=instrument_id,
        value=None if value is None else Decimal(value),
        unit="ratio",
        window=window,
        observed_date=observed_date,
        quality_status=quality,
    )


def complete_observations(instruments=INSTRUMENTS, values_by_instrument=None):
    """Return the four REQUIRED factor observations per instrument.

    ``values_by_instrument`` is an optional mapping of ``instrument_id`` ->
    4-tuple of decimal strings. Falls back to a deterministic fixture so that
    hash-stability, clipping, and bound tests have a single known input.
    """
    defaults = {
        INSTRUMENTS[0]: ("0.2", "0.3", "0.4", "0.1"),
        INSTRUMENTS[1]: ("0.8", "0.7", "0.6", "0.9"),
    }
    if values_by_instrument is not None:
        defaults.update(values_by_instrument)
    return tuple(
        factor(instrument, key, value)
        for instrument in instruments
        for key, value in zip(REQUIRED_KEYS, defaults[instrument], strict=True)
    )


def test_required_factor_keys_are_frozen_and_match_spec():
    assert REQUIRED_KEYS == (
        "return_20d",
        "realized_volatility_20d",
        "avg_turnover_amount_20d",
        "max_drawdown_60d",
    )


def test_snapshot_hash_and_observation_ids_are_stable_and_order_independent():
    first = build_market_temperature(
        input_snapshot_id=INPUT_ID, factor_observations=complete_observations(), as_of_date=AS_OF
    )
    second = build_market_temperature(
        input_snapshot_id=INPUT_ID,
        factor_observations=tuple(reversed(complete_observations())),
        as_of_date=AS_OF,
    )
    assert first == second
    assert first.content_hash == second.content_hash
    first_hashes = [item.item_hash for item in first.observations]
    second_hashes = [item.item_hash for item in second.observations]
    assert first_hashes == second_hashes
    assert first.snapshot_id == second.snapshot_id
    assert first.snapshot_id == f"mos:{first.content_hash[:32]}"
    assert first.quality_status is QualityStatus.COMPLETE
    assert first.freshness_status is FreshnessStatus.FRESH


def test_values_are_clipped_to_zero_one():
    result = build_market_temperature(
        input_snapshot_id=INPUT_ID,
        factor_observations=tuple(
            factor(INSTRUMENTS[0], key, value)
            for key, value in (
                ("return_20d", "99"),
                ("realized_volatility_20d", "-99"),
                ("avg_turnover_amount_20d", "99"),
                ("max_drawdown_60d", "-99"),
            )
        ),
        as_of_date=AS_OF,
    )
    assert all(
        Decimal("0") <= item.value <= Decimal("1")
        for item in result.observations
        if isinstance(item.value, Decimal)
    )


def test_liquidity_normalization_uses_versioned_fixed_scale():
    fixture = {
        INSTRUMENTS[0]: ("0.5", "0.2", "50000000", "-0.1"),
        INSTRUMENTS[1]: ("0.5", "0.2", "150000000", "-0.1"),
    }
    result = build_market_temperature(
        input_snapshot_id=INPUT_ID,
        factor_observations=complete_observations(values_by_instrument=fixture),
        as_of_date=AS_OF,
    )
    by_key = {item.observation_key: item.value for item in result.observations}
    small = by_key["market_temperature_liquidity_score"]
    large = by_key["market_temperature_liquidity_score"]
    assert small is large
    assert isinstance(small, Decimal)
    assert Decimal("0") <= small <= Decimal("1")
    assert LIQUIDITY_NORMALIZER_VERSION == "1.0.0"
    assert Decimal("100000000") == LIQUIDITY_SCALE
    expected_small = (Decimal("50000000") / LIQUIDITY_SCALE).quantize(Decimal("0.00000001"))
    expected_large = min(
        Decimal(1),
        Decimal("150000000") / LIQUIDITY_SCALE,
    ).quantize(Decimal("0.00000001"))
    second = build_market_temperature(
        input_snapshot_id=INPUT_ID,
        factor_observations=complete_observations(
            values_by_instrument={
                INSTRUMENTS[0]: ("0.5", "0.2", "50000000", "-0.1"),
                INSTRUMENTS[1]: ("0.5", "0.2", "50000000", "-0.1"),
            }
        ),
        as_of_date=AS_OF,
    )
    assert second.observations[0].quality_status is QualityStatus.COMPLETE
    small_score = next(
        item.value
        for item in result.observations
        if item.observation_key == "market_temperature_liquidity_score"
    )
    clipped_small = next(
        item.value
        for item in second.observations
        if item.observation_key == "market_temperature_liquidity_score"
    )
    assert clipped_small == expected_small
    assert small_score == expected_large
    assert small_score > clipped_small


@pytest.mark.parametrize(
    "quality",
    [
        QualityStatus.PARTIAL,
        QualityStatus.MISSING,
        QualityStatus.INVALID,
        QualityStatus.CONFLICT,
    ],
)
def test_bad_input_fails_closed(quality):
    result = build_market_temperature(
        input_snapshot_id=INPUT_ID,
        factor_observations=(factor(INSTRUMENTS[0], "return_20d", "0.2", quality=quality),),
        as_of_date=AS_OF,
    )
    assert result.quality_status is QualityStatus.INVALID
    assert result.freshness_status is FreshnessStatus.FAILED
    assert all(item.value is None for item in result.observations)


def test_stale_input_fails_closed():
    result = build_market_temperature(
        input_snapshot_id=INPUT_ID,
        factor_observations=(
            factor(INSTRUMENTS[0], "return_20d", "0.2", observed_date=date(2026, 8, 6)),
        ),
        as_of_date=AS_OF,
    )
    assert result.quality_status is QualityStatus.INVALID
    assert result.freshness_status is FreshnessStatus.STALE


def test_missing_required_factor_fails_closed():
    observations = [
        factor(INSTRUMENTS[0], key, value)
        for key, value in zip(
            REQUIRED_KEYS,
            ("0.2", "0.3", "0.4", "0.1"),
            strict=True,
        )
        if key != "max_drawdown_60d"
    ]
    result = build_market_temperature(
        input_snapshot_id=INPUT_ID,
        factor_observations=tuple(observations),
        as_of_date=AS_OF,
    )
    assert result.quality_status is QualityStatus.INVALID
    assert result.freshness_status is FreshnessStatus.FAILED
    assert all(item.value is None for item in result.observations)


def test_extra_factor_key_fails_closed():
    observations = [
        factor(INSTRUMENTS[0], key, value)
        for key, value in zip(
            REQUIRED_KEYS,
            ("0.2", "0.3", "0.4", "0.1"),
            strict=True,
        )
    ] + [factor(INSTRUMENTS[0], "return_60d", "0.5", window=60)]
    result = build_market_temperature(
        input_snapshot_id=INPUT_ID,
        factor_observations=tuple(observations),
        as_of_date=AS_OF,
    )
    assert result.quality_status is QualityStatus.INVALID
    assert result.freshness_status is FreshnessStatus.FAILED
    assert all(item.value is None for item in result.observations)


def test_duplicate_factor_key_for_instrument_fails_closed():
    observations = [
        factor(INSTRUMENTS[0], "return_20d", "0.2"),
        factor(INSTRUMENTS[0], "return_20d", "0.7"),
        factor(INSTRUMENTS[0], "realized_volatility_20d", "0.3"),
        factor(INSTRUMENTS[0], "avg_turnover_amount_20d", "0.4"),
        factor(INSTRUMENTS[0], "max_drawdown_60d", "0.1"),
    ]
    result = build_market_temperature(
        input_snapshot_id=INPUT_ID,
        factor_observations=tuple(observations),
        as_of_date=AS_OF,
    )
    assert result.quality_status is QualityStatus.INVALID
    assert result.freshness_status is FreshnessStatus.FAILED
    assert all(item.value is None for item in result.observations)


def test_none_value_for_required_factor_fails_closed():
    observations = [
        factor(INSTRUMENTS[0], key, value)
        for key, value in zip(
            REQUIRED_KEYS,
            ("0.2", "0.3", None, "0.1"),
            strict=True,
        )
    ]
    result = build_market_temperature(
        input_snapshot_id=INPUT_ID,
        factor_observations=tuple(observations),
        as_of_date=AS_OF,
    )
    assert result.quality_status is QualityStatus.INVALID
    assert result.freshness_status is FreshnessStatus.FAILED
    assert all(item.value is None for item in result.observations)


def test_snapshot_and_observation_are_immutable_and_validate_inputs():
    with pytest.raises((TypeError, ValueError)):
        MarketObservation(
            observation_key="",
            value=Decimal("1"),
            unit="ratio",
            observed_date=AS_OF,
            source_kind="domain",
            source_ref="builder",
        )
    with pytest.raises(TypeError):
        MarketObservation(
            observation_key="market_temperature_score",
            value=Decimal("1"),
            unit="score",
            observed_date=AS_OF,
            source_kind="analytics",
            source_ref="market_temperature:1.0.0",
            quality_status="complete",
        )
    snapshot = MarketObservationSnapshot(
        input_snapshot_id=INPUT_ID, as_of_date=AS_OF, observations=(), algorithm_version="1.0.0"
    )
    with pytest.raises((AttributeError, TypeError)):
        snapshot.algorithm_version = "2.0.0"
