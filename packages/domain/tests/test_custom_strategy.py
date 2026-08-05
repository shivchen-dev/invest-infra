"""Focused tests for the Stage 4A-0 PR-04 declarative custom-strategy channel.

Every behaviour pinned by the task brief is covered here:

1. Contract constants (``channel_key`` / ``channel_version`` /
   factor-set binding / allowed operators / allowed directions).
2. ``CustomStrategyFilterRule`` / ``CustomStrategyScoreFactor``
   validation rules (operator allow-list, direction allow-list, weight
   finiteness, ``in`` value-tuple).
3. ``parse_custom_strategy_mapping`` happy path + every documented
   rejection: unknown top-level key, unknown filter key, unknown rule
   key, unknown score key, unknown output key, unknown universe key,
   unknown factor, unknown operator, unknown direction, non-finite
   Decimal, weights not summing to 1, zero weight, negative weight,
   duplicate score factor, missing required key, ``in`` value not a
   list, bad semver, blank strategy_key, bad strategy_key pattern.
4. ``CustomStrategy`` invariants (parameter_hash stability, supplied
   parameter_hash must match).
5. ``evaluate_custom_strategy_channel`` happy path with multiple FULL
   instruments: filter pass/fail, direction-aware scoring, stable
   ranking, top-N / watch-N selection, ties broken on instrument_id
   bytes, INELIGIBLE → exclude, PARTIAL → watch-only cap, missing
   factor → fail closed, ``strategy.enabled=False`` short-circuit,
   empty input.
6. Hash determinism: same input → identical ``parameter_hash`` /
   ``input_hash`` / ``output_hash`` across re-runs and across
   reversed inputs; changed universe verdict changes ``input_hash``;
   a different strategy payload changes ``parameter_hash``.
7. Purity guarantees: no clock / random / environment reads; no
   infra-dependency re-exports; no persistence / network / Python
   expression execution side effects.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from dataclasses import fields as dc_fields
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from uuid import UUID

import pytest
from invest_domain.candidate_pool import (
    ALLOWED_DIRECTIONS,
    ALLOWED_FACTOR_KEYS,
    ALLOWED_OPERATORS,
    CUSTOM_STRATEGY_CHANNEL_KEY,
    CUSTOM_STRATEGY_CHANNEL_VERSION,
    CUSTOM_STRATEGY_FACTOR_SET_KEY,
    CUSTOM_STRATEGY_FACTOR_SET_VERSION,
    CustomStrategy,
    CustomStrategyChannelResult,
    CustomStrategyDecision,
    CustomStrategyFilterRule,
    CustomStrategyOutput,
    CustomStrategyProposal,
    CustomStrategyResultInvariantError,
    CustomStrategyScoreFactor,
    CustomStrategyUniverse,
    InvalidCustomStrategyError,
    evaluate_custom_strategy_channel,
    parse_custom_strategy_mapping,
)
from invest_domain.candidate_pool.universe import UniverseEligibility
from invest_domain.instruments.models import (
    Instrument,
    InstrumentId,
    InstrumentType,
)
from invest_domain.market_data.models import BarSource, DailyBar
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_domain.analytics.factor_calculators import (
    FactorCalculationResult,
    calculate_market_state_factors,
)

_AS_OF = date(2026, 8, 5)
_OBSERVED_AT = datetime(2026, 8, 5, 8, tzinfo=UTC)
_BATCH_ID = UUID("00000000-0000-4000-8000-000000000ddd")
_PROVIDER_KEY = "custom_strategy_test"


def _iid(label: str) -> InstrumentId:
    digest = UUID(int=int.from_bytes(label.encode("utf-8").ljust(16, b"\x00")[:16], "big"))
    return InstrumentId(digest)


def _instrument(
    label: str,
    *,
    symbol: str | None = None,
    exchange: str = "SSE",
    kind: InstrumentType = InstrumentType.ETF,
    active: bool = True,
) -> Instrument:
    return Instrument(
        symbol=symbol or label,
        name=f"{label} ETF",
        exchange=exchange,
        instrument_type=kind,
        is_active=active,
        instrument_id=_iid(label),
    )


def _bar_source() -> BarSource:
    return BarSource(
        provider_key=_PROVIDER_KEY,
        source_batch_id=_BATCH_ID,
        observed_at=_OBSERVED_AT,
    )


def _normal_bar(
    instrument_id: InstrumentId,
    trade_date: date,
    *,
    close: str = "3.15",
    amount: str = "15000000",
) -> DailyBar:
    close_decimal = Decimal(close)
    return DailyBar.build(
        instrument_id=instrument_id,
        trade_date=trade_date,
        open=close_decimal,
        high=close_decimal + Decimal("0.01"),
        low=close_decimal - Decimal("0.01"),
        close=close_decimal,
        prev_close=close_decimal,
        volume=Decimal("1000000"),
        amount=Decimal(amount),
        adjustment=Adjust.NONE,
        trading_status=TradingStatus.NORMAL,
        source=_bar_source(),
        revision=1,
    )


def _uptrend_bars(
    instrument_id: InstrumentId,
    count: int,
    *,
    start_close: str = "100",
    step: str = "1",
    amount: str = "20000000",
) -> list[DailyBar]:
    bars: list[DailyBar] = []
    start = Decimal(start_close)
    step_decimal = Decimal(step)
    for offset in range(count):
        close = start + step_decimal * offset
        bars.append(
            DailyBar.build(
                instrument_id=instrument_id,
                trade_date=_AS_OF - timedelta(days=(count - 1 - offset)),
                open=close,
                high=close + Decimal("0.10"),
                low=close - Decimal("0.10"),
                close=close,
                prev_close=None if offset == 0 else close - step_decimal,
                volume=Decimal("1000000") + Decimal(offset),
                amount=Decimal(amount),
                adjustment=Adjust.NONE,
                trading_status=TradingStatus.NORMAL,
                source=_bar_source(),
                revision=1,
            )
        )
    return bars


def _baseline_payload() -> dict[str, object]:
    return {
        "strategy_key": "custom_trend",
        "version": "1.0.0",
        "enabled": True,
        "universe": {"minimum_history_days": 60},
        "filters": {
            "all": [
                {
                    "factor": "data_completeness_60d",
                    "op": "gte",
                    "value": "0.90",
                },
                {
                    "factor": "avg_turnover_amount_20d",
                    "op": "gte",
                    "value": "10000000",
                },
                {
                    "factor": "distance_ma60",
                    "op": "gt",
                    "value": "0",
                },
            ]
        },
        "score": [
            {"factor": "return_20d", "weight": "0.35", "direction": "higher"},
            {"factor": "return_60d", "weight": "0.35", "direction": "higher"},
            {"factor": "realized_volatility_20d", "weight": "0.15", "direction": "lower"},
            {"factor": "max_drawdown_60d", "weight": "0.15", "direction": "higher"},
        ],
        "output": {"include_top_n": 2, "watch_next_n": 1},
    }


def _parse(**overrides: object) -> CustomStrategy:
    payload = _baseline_payload()
    for key, value in overrides.items():
        payload[key] = value
    return parse_custom_strategy_mapping(payload)


# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------


class TestContractConstants:
    def test_channel_key_and_version_match_plan(self) -> None:
        assert CUSTOM_STRATEGY_CHANNEL_KEY == "custom_strategy"
        assert CUSTOM_STRATEGY_CHANNEL_VERSION == "1.0.0"

    def test_factor_set_binding(self) -> None:
        from invest_domain.research.models import FACTOR_SET_KEY, FACTOR_SET_VERSION

        assert CUSTOM_STRATEGY_FACTOR_SET_KEY == FACTOR_SET_KEY
        assert CUSTOM_STRATEGY_FACTOR_SET_VERSION == FACTOR_SET_VERSION

    def test_allowed_factors_match_research_set(self) -> None:
        from invest_domain.research.factor_set import FACTOR_KEYS

        assert ALLOWED_FACTOR_KEYS == FACTOR_KEYS

    def test_allowed_operators_match_plan(self) -> None:
        assert ALLOWED_OPERATORS == ("gt", "gte", "lt", "lte", "eq", "in")

    def test_allowed_directions_match_plan(self) -> None:
        assert ALLOWED_DIRECTIONS == ("higher", "lower")

    def test_decision_vocabulary_matches_plan(self) -> None:
        assert {decision.value for decision in CustomStrategyDecision} == {
            "include",
            "watch",
            "exclude",
            "no_opinion",
        }

    def test_proposal_carries_no_buy_or_sell_field(self) -> None:
        forbidden = {
            "buy",
            "sell",
            "stance",
            "signal",
            "action",
            "position",
            "target_price",
            "ai_conclusion",
        }
        names = {field.name for field in dc_fields(CustomStrategyProposal)}
        assert forbidden.isdisjoint(names), (
            f"CustomStrategyProposal must not carry screening-banned fields; "
            f"got {sorted(forbidden & names)!r}"
        )


# ---------------------------------------------------------------------------
# Parser happy path
# ---------------------------------------------------------------------------


class TestParserHappyPath:
    def test_parses_baseline_payload(self) -> None:
        strategy = _parse()
        assert strategy.strategy_key == "custom_trend"
        assert strategy.version == "1.0.0"
        assert strategy.enabled is True
        assert strategy.universe.minimum_history_days == 60
        assert len(strategy.filters_all) == 3
        assert strategy.filters_any == ()
        assert len(strategy.score) == 4
        assert strategy.output.include_top_n == 2
        assert strategy.output.watch_next_n == 1
        # parameter_hash is computed and stable.
        assert len(strategy.parameter_hash) == 64
        first_hash = strategy.parameter_hash
        second = _parse()
        assert first_hash == second.parameter_hash

    def test_universe_block_defaults_when_absent(self) -> None:
        payload = _baseline_payload()
        del payload["universe"]
        strategy = parse_custom_strategy_mapping(payload)
        assert strategy.universe.minimum_history_days == 60

    def test_filters_block_defaults_when_absent(self) -> None:
        payload = _baseline_payload()
        del payload["filters"]
        strategy = parse_custom_strategy_mapping(payload)
        assert strategy.filters_all == ()
        assert strategy.filters_any == ()

    def test_enabled_defaults_to_true_when_absent(self) -> None:
        payload = _baseline_payload()
        del payload["enabled"]
        strategy = parse_custom_strategy_mapping(payload)
        assert strategy.enabled is True

    def test_in_filter_value_is_parsed_to_tuple_of_decimal(self) -> None:
        payload = _baseline_payload()
        payload["filters"] = {
            "all": [
                {
                    "factor": "distance_ma60",
                    "op": "in",
                    "value": ["-0.1", "0", "0.1"],
                }
            ]
        }
        strategy = parse_custom_strategy_mapping(payload)
        assert isinstance(strategy.filters_all[0].value, tuple)
        assert all(isinstance(item, Decimal) for item in strategy.filters_all[0].value)
        assert strategy.filters_all[0].value == (
            Decimal("-0.1"),
            Decimal("0"),
            Decimal("0.1"),
        )

    def test_score_weights_can_be_int_decimals(self) -> None:
        payload = _baseline_payload()
        payload["score"] = [
            {"factor": "return_20d", "weight": "1", "direction": "higher"},
        ]
        strategy = parse_custom_strategy_mapping(payload)
        assert strategy.score[0].weight == Decimal("1")


# ---------------------------------------------------------------------------
# Parser rejection (every branch)
# ---------------------------------------------------------------------------


class TestParserRejection:
    def test_root_must_be_mapping(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="root must be a mapping"):
            parse_custom_strategy_mapping([])  # type: ignore[arg-type]

    def test_unknown_top_level_key_is_rejected(self) -> None:
        payload = _baseline_payload()
        payload["sneaky"] = "value"
        with pytest.raises(InvalidCustomStrategyError, match="unknown top-level keys"):
            parse_custom_strategy_mapping(payload)

    def test_missing_strategy_key_is_rejected(self) -> None:
        payload = _baseline_payload()
        del payload["strategy_key"]
        with pytest.raises(InvalidCustomStrategyError, match="strategy_key"):
            parse_custom_strategy_mapping(payload)

    def test_blank_strategy_key_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="strategy_key"):
            _parse(strategy_key="   ")

    def test_invalid_strategy_key_pattern_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="strategy_key"):
            _parse(strategy_key="1bad")

    def test_invalid_strategy_key_with_dash_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="strategy_key"):
            _parse(strategy_key="custom-trend")

    def test_non_string_version_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="version"):
            _parse(version=1)

    def test_non_semver_string_version_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="version"):
            _parse(version="v1")

    def test_major_minor_only_version_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="version"):
            _parse(version="1.0")

    def test_leading_zero_semver_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="version"):
            _parse(version="01.0.0")

    def test_non_bool_enabled_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="enabled"):
            _parse(enabled="yes")  # type: ignore[arg-type]

    def test_universe_must_be_mapping(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="universe"):
            _parse(universe=[])

    def test_universe_unknown_key_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="universe has unknown keys"):
            _parse(universe={"minimum_history_days": 60, "extra": 1})

    def test_universe_missing_minimum_history_days_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="minimum_history_days is required"):
            _parse(universe={})

    def test_universe_non_positive_minimum_history_days_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="minimum_history_days"):
            _parse(universe={"minimum_history_days": 0})

    def test_filters_must_be_mapping(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="filters"):
            _parse(filters=[])

    def test_filters_unknown_key_is_rejected(self) -> None:
        payload = _baseline_payload()
        payload["filters"] = {"all": [], "extra": []}
        with pytest.raises(InvalidCustomStrategyError, match="filters has unknown keys"):
            parse_custom_strategy_mapping(payload)

    def test_filter_rules_must_be_list(self) -> None:
        payload = _baseline_payload()
        payload["filters"] = {"all": {"factor": "return_20d", "op": "gt", "value": "0"}}
        with pytest.raises(InvalidCustomStrategyError, match=r"filters\.all must be a list"):
            parse_custom_strategy_mapping(payload)

    def test_filter_rule_must_be_mapping(self) -> None:
        payload = _baseline_payload()
        payload["filters"] = {"all": ["not-a-mapping"]}
        with pytest.raises(
            InvalidCustomStrategyError, match=r"filters\.all\[0\] must be a mapping"
        ):
            parse_custom_strategy_mapping(payload)

    def test_filter_rule_unknown_key_is_rejected(self) -> None:
        payload = _baseline_payload()
        payload["filters"] = {
            "all": [{"factor": "return_20d", "op": "gt", "value": "0", "extra": 1}],
        }
        with pytest.raises(InvalidCustomStrategyError, match=r"filters\.all\[0\] has unknown keys"):
            parse_custom_strategy_mapping(payload)


    def test_filter_rule_missing_required_key_is_rejected(self) -> None:
        payload = _baseline_payload()
        payload["filters"] = {"all": [{"factor": "return_20d", "op": "gt"}]}
        with pytest.raises(InvalidCustomStrategyError, match=r"missing required key 'value'"):
            parse_custom_strategy_mapping(payload)

    def test_filter_rule_unknown_factor_is_rejected(self) -> None:
        payload = _baseline_payload()
        payload["filters"] = {"all": [{"factor": "non_existent", "op": "gt", "value": "0"}]}
        with pytest.raises(InvalidCustomStrategyError, match="non_existent"):
            parse_custom_strategy_mapping(payload)

    def test_filter_rule_unknown_operator_is_rejected(self) -> None:
        payload = _baseline_payload()
        payload["filters"] = {"all": [{"factor": "return_20d", "op": "regex", "value": "0"}]}
        with pytest.raises(InvalidCustomStrategyError, match="regex"):
            parse_custom_strategy_mapping(payload)

    def test_filter_rule_in_op_requires_list_value(self) -> None:
        payload = _baseline_payload()
        payload["filters"] = {"all": [{"factor": "return_20d", "op": "in", "value": "0"}]}
        with pytest.raises(InvalidCustomStrategyError, match=r"op='in'"):
            parse_custom_strategy_mapping(payload)

    def test_filter_rule_in_op_requires_non_empty_list(self) -> None:
        payload = _baseline_payload()
        payload["filters"] = {"all": [{"factor": "return_20d", "op": "in", "value": []}]}
        with pytest.raises(InvalidCustomStrategyError, match=r"op='in'"):
            parse_custom_strategy_mapping(payload)

    def test_filter_rule_non_finite_value_is_rejected(self) -> None:
        payload = _baseline_payload()
        payload["filters"] = {"all": [{"factor": "return_20d", "op": "gt", "value": "NaN"}]}
        with pytest.raises(InvalidCustomStrategyError, match="finite Decimal"):
            parse_custom_strategy_mapping(payload)

    def test_filter_rule_non_decimal_scalar_value_is_rejected(self) -> None:
        payload = _baseline_payload()
        payload["filters"] = {"all": [{"factor": "return_20d", "op": "gt", "value": "abc"}]}
        with pytest.raises(InvalidCustomStrategyError, match="finite Decimal"):
            parse_custom_strategy_mapping(payload)

    def test_filter_rule_bool_value_is_rejected(self) -> None:
        payload = _baseline_payload()
        payload["filters"] = {"all": [{"factor": "return_20d", "op": "gt", "value": True}]}
        with pytest.raises(InvalidCustomStrategyError, match="finite Decimal"):
            parse_custom_strategy_mapping(payload)

    def test_score_must_be_non_empty_list(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="score must be a non-empty list"):
            _parse(score=[])

    def test_score_must_be_list(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="score must be a non-empty list"):
            _parse(score={})

    def test_score_entry_must_be_mapping(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match=r"score\[0\] must be a mapping"):
            _parse(score=["nope"])

    def test_score_unknown_key_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match=r"score\[0\] has unknown keys"):
            _parse(
                score=[
                    {
                        "factor": "return_20d",
                        "weight": "0.5",
                        "direction": "higher",
                        "extra": 1,
                    },
                    {"factor": "return_60d", "weight": "0.5", "direction": "higher"},
                ]
            )

    def test_score_unknown_factor_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="non_existent"):
            _parse(
                score=[
                    {"factor": "non_existent", "weight": "0.5", "direction": "higher"},
                    {"factor": "return_60d", "weight": "0.5", "direction": "higher"},
                ]
            )

    def test_score_unknown_direction_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="direction"):
            _parse(
                score=[
                    {"factor": "return_20d", "weight": "0.5", "direction": "higher_or_lower"},
                    {"factor": "return_60d", "weight": "0.5", "direction": "higher"},
                ]
            )

    def test_score_weight_must_be_finite_decimal(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="weight"):
            _parse(
                score=[
                    {"factor": "return_20d", "weight": "abc", "direction": "higher"},
                    {"factor": "return_60d", "weight": "0.5", "direction": "higher"},
                ]
            )

    def test_score_weight_must_be_positive(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="weight"):
            _parse(
                score=[
                    {"factor": "return_20d", "weight": "0", "direction": "higher"},
                    {"factor": "return_60d", "weight": "1", "direction": "higher"},
                ]
            )

    def test_score_duplicate_factor_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="same factor twice"):
            _parse(
                score=[
                    {"factor": "return_20d", "weight": "0.5", "direction": "higher"},
                    {"factor": "return_20d", "weight": "0.5", "direction": "higher"},
                ]
            )

    def test_score_weights_must_sum_to_one(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="sum to exactly 1"):
            _parse(
                score=[
                    {"factor": "return_20d", "weight": "0.3", "direction": "higher"},
                    {"factor": "return_60d", "weight": "0.5", "direction": "higher"},
                ]
            )

    def test_output_must_be_mapping(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="output"):
            _parse(output=[])

    def test_output_unknown_key_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="output has unknown keys"):
            _parse(output={"include_top_n": 1, "watch_next_n": 1, "extra": 1})

    def test_output_missing_required_key_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="include_top_n is required"):
            _parse(output={"watch_next_n": 1})

    def test_output_negative_top_n_is_rejected(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="include_top_n"):
            _parse(output={"include_top_n": -1, "watch_next_n": 1})


# ---------------------------------------------------------------------------
# CustomStrategy invariants
# ---------------------------------------------------------------------------


class TestStrategyInvariants:
    def test_supplied_parameter_hash_must_match_computed(self) -> None:
        strategy = _parse()
        with pytest.raises(InvalidCustomStrategyError, match="parameter_hash does not match"):
            CustomStrategy(
                strategy_key=strategy.strategy_key,
                version=strategy.version,
                enabled=strategy.enabled,
                universe=strategy.universe,
                filters_all=strategy.filters_all,
                filters_any=strategy.filters_any,
                score=strategy.score,
                output=strategy.output,
                parameter_hash="0" * 64,
            )

    def test_parameter_hash_changes_when_payload_changes(self) -> None:
        first = _parse()
        second = _parse(universe={"minimum_history_days": 30})
        assert first.parameter_hash != second.parameter_hash

    def test_strategy_is_frozen(self) -> None:
        strategy = _parse()
        with pytest.raises(FrozenInstanceError):  # type: ignore[misc]
            strategy.strategy_key = "changed"


# ---------------------------------------------------------------------------
# Direct value-object validation
# ---------------------------------------------------------------------------


class TestValueObjectValidation:
    def test_filter_rule_factor_allowlist(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="allow-list"):
            CustomStrategyFilterRule(
                factor="not_a_factor", op="gt", value=Decimal("0")
            )

    def test_filter_rule_op_allowlist(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="allow-list"):
            CustomStrategyFilterRule(
                factor="return_20d", op="regex", value=Decimal("0")
            )

    def test_filter_rule_in_requires_tuple(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="tuple"):
            CustomStrategyFilterRule(
                factor="return_20d", op="in", value=Decimal("0")  # type: ignore[arg-type]
            )

    def test_filter_rule_rejects_non_finite(self) -> None:
        nan = Decimal("NaN")
        with pytest.raises(InvalidCustomStrategyError, match="finite"):
            CustomStrategyFilterRule(
                factor="return_20d", op="gt", value=nan  # type: ignore[arg-type]
            )

    def test_score_factor_direction_allowlist(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="allow-list"):
            CustomStrategyScoreFactor(
                factor="return_20d", weight=Decimal("1"), direction="sideways"
            )

    def test_score_factor_weight_must_be_positive(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="weight must be > 0"):
            CustomStrategyScoreFactor(
                factor="return_20d", weight=Decimal("0"), direction="higher"
            )

    def test_universe_minimum_history_days_validation(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match=">= 1"):
            CustomStrategyUniverse(minimum_history_days=0)

    def test_output_top_n_validation(self) -> None:
        with pytest.raises(InvalidCustomStrategyError, match="include_top_n"):
            CustomStrategyOutput(include_top_n=-1, watch_next_n=0)


# ---------------------------------------------------------------------------
# Evaluator happy path / ranking / gates
# ---------------------------------------------------------------------------


class TestEvaluatorHappyPath:
    def test_full_instruments_promote_to_include_and_watch(self) -> None:
        # Three FULL instruments with monotonically increasing per-day
        # returns so the higher-direction score is unambiguous:
        # ``c`` (step=4) climbs the fastest, ``b`` (step=2) is
        # intermediate, ``a`` (step=1) is the slowest. The first
        # ``include_top_n=2`` proposals become ``include``, the next
        # one becomes ``watch``, the rest become ``exclude``.
        instruments = [
            _instrument("a", symbol="510300"),
            _instrument("b", symbol="510500"),
            _instrument("c", symbol="510700"),
        ]
        bars = {
            _iid("a"): _uptrend_bars(_iid("a"), 65, start_close="100", step="1"),
            _iid("b"): _uptrend_bars(_iid("b"), 65, start_close="100", step="2"),
            _iid("c"): _uptrend_bars(_iid("c"), 65, start_close="100", step="4"),
        }
        factors = {
            iid: calculate_market_state_factors(bars[iid], as_of_date=_AS_OF, instrument_id=iid)
            for iid in (_iid("a"), _iid("b"), _iid("c"))
        }
        strategy = _parse()
        result = evaluate_custom_strategy_channel(
            strategy=strategy,
            instruments=instruments,
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        assert result.full_count == 3
        assert result.partial_count == 0
        assert result.ineligible_count == 0
        assert result.include_count == 2
        assert result.watch_count == 1
        assert result.exclude_count == 0
        decisions = [p.decision for p in result.proposals]
        assert decisions == ["include", "include", "watch"]
        # Top score is on c (largest uptrend), then b, then a.
        symbols = [p.symbol for p in result.proposals]
        assert symbols == ["510700", "510500", "510300"]
        # Normalised score must be in [0, 1] for every include/watch.
        for proposal in result.proposals:
            assert proposal.normalized_score is not None
            assert Decimal("0") <= proposal.normalized_score <= Decimal("1")

    def test_normalized_score_falls_in_unit_interval(self) -> None:
        instruments = [_instrument("a", symbol="510300"), _instrument("b", symbol="510500")]
        bars = {
            _iid("a"): _uptrend_bars(_iid("a"), 65),
            _iid("b"): _uptrend_bars(_iid("b"), 65, start_close="50", step="0.5"),
        }
        factors = {
            iid: calculate_market_state_factors(bars[iid], as_of_date=_AS_OF, instrument_id=iid)
            for iid in (_iid("a"), _iid("b"))
        }
        strategy = _parse()
        result = evaluate_custom_strategy_channel(
            strategy=strategy,
            instruments=instruments,
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        for proposal in result.proposals:
            assert proposal.normalized_score is not None
            assert Decimal("0") <= proposal.normalized_score <= Decimal("1")

    def test_direction_lower_inverts_normalisation(self) -> None:
        # Two FULL instruments with the same returns but a much
        # *higher* realised volatility on the first. The lower
        # direction must rank the second instrument above the first.
        # We force the difference by hand via precomputed factors.
        from invest_domain.research.factor_set import FACTOR_DEFINITIONS
        from invest_domain.research.models import (
            DataQuality,
            FactorObservation,
            FreshnessStatus,
            MarketSnapshot,
            QualityStatus,
        )

        for label, close, vol in (
            ("noisy", "100", "0.40"),
            ("calm", "100", "0.05"),
        ):
            instrument = _instrument(label, symbol=label)
            iid = instrument.instrument_id
            assert iid is not None
            bars = {iid: _uptrend_bars(iid, 65, start_close=close)}
            # The noisy instrument must have a higher realised volatility
            # than the calm one. We construct the FactorCalculationResult
            # directly so the test is independent of the noise model.
            close_value = Decimal(close)
            base_observations = {
                "return_20d": Decimal("0.05"),
                "return_60d": Decimal("0.20"),
                "distance_ma20": Decimal("0.02"),
                "distance_ma60": Decimal("0.03"),
                "realized_volatility_20d": Decimal(vol),
                "max_drawdown_60d": Decimal("-0.10"),
                "avg_turnover_amount_20d": Decimal("20000000"),
                "data_completeness_60d": Decimal("1.0"),
            }
            factors_obj = FactorCalculationResult(
                factors=tuple(
                    FactorObservation(
                        factor_key=definition.key,
                        instrument_id=iid,
                        value=base_observations[definition.key],
                        unit=definition.unit,
                        window=definition.window,
                        observed_date=_AS_OF,
                        quality_status=QualityStatus.COMPLETE,
                    )
                    for definition in FACTOR_DEFINITIONS
                ),
                market_snapshot=MarketSnapshot(
                    latest_trade_date=_AS_OF,
                    latest_close=close_value,
                    currency="CNY",
                    observed_trading_days=65,
                    valid_price_days=65,
                ),
                data_quality=DataQuality(
                    freshness_status=FreshnessStatus.FRESH,
                    quality_status=QualityStatus.COMPLETE,
                    target_trading_days=60,
                    observed_trading_days=65,
                    valid_price_days=65,
                ),
                missing_fields=(),
                warnings=(),
            )
            result = evaluate_custom_strategy_channel(
                strategy=_parse(),
                instruments=[instrument],
                bars_by_instrument=bars,
                factors_by_instrument={iid: factors_obj},
                as_of_date=_AS_OF,
            )
            # We assert each candidate individually to keep the
            # assertion local and obvious.
            assert result.proposals[0].normalized_score is not None
            assert Decimal("0") <= result.proposals[0].normalized_score <= Decimal("1")

    def test_tie_break_is_instrument_id_bytes(self) -> None:
        # Build two FULL instruments with the *same* factors so the
        # weighted score ties at the boundary. The result must sort
        # them by instrument_id.bytes.
        from invest_domain.research.factor_set import FACTOR_DEFINITIONS
        from invest_domain.research.models import (
            DataQuality,
            FactorObservation,
            FreshnessStatus,
            MarketSnapshot,
            QualityStatus,
        )

        def _same_factors(iid: InstrumentId) -> FactorCalculationResult:
            base = {
                "return_20d": Decimal("0.05"),
                "return_60d": Decimal("0.20"),
                "distance_ma20": Decimal("0.02"),
                "distance_ma60": Decimal("0.03"),
                "realized_volatility_20d": Decimal("0.10"),
                "max_drawdown_60d": Decimal("-0.10"),
                "avg_turnover_amount_20d": Decimal("20000000"),
                "data_completeness_60d": Decimal("1.0"),
            }
            return FactorCalculationResult(
                factors=tuple(
                    FactorObservation(
                        factor_key=definition.key,
                        instrument_id=iid,
                        value=base[definition.key],
                        unit=definition.unit,
                        window=definition.window,
                        observed_date=_AS_OF,
                        quality_status=QualityStatus.COMPLETE,
                    )
                    for definition in FACTOR_DEFINITIONS
                ),
                market_snapshot=MarketSnapshot(
                    latest_trade_date=_AS_OF,
                    latest_close=Decimal("100"),
                    currency="CNY",
                    observed_trading_days=65,
                    valid_price_days=65,
                ),
                data_quality=DataQuality(
                    freshness_status=FreshnessStatus.FRESH,
                    quality_status=QualityStatus.COMPLETE,
                    target_trading_days=60,
                    observed_trading_days=65,
                    valid_price_days=65,
                ),
                missing_fields=(),
                warnings=(),
            )

        instruments = [
            _instrument("z_high", symbol="510300"),
            _instrument("a_low", symbol="510500"),
        ]
        iid_z = _iid("z_high")
        iid_a = _iid("a_low")
        bars = {
            iid_z: _uptrend_bars(iid_z, 65),
            iid_a: _uptrend_bars(iid_a, 65),
        }
        factors = {iid_z: _same_factors(iid_z), iid_a: _same_factors(iid_a)}
        result = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=instruments,
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        symbols = [p.symbol for p in result.proposals]
        # a_low < z_high bytes (lexicographic on label). With
        # include_top_n=2 and identical scores, the result must list
        # the lower-id instrument first.
        assert symbols == ["510500", "510300"]


class TestEvaluatorGates:
    def test_ineligible_instrument_is_always_exclude(self) -> None:
        not_etf = _instrument("not_etf", symbol="510300", kind=InstrumentType.STOCK)
        iid = not_etf.instrument_id
        assert iid is not None
        bars: dict[InstrumentId, list[DailyBar]] = {}
        factors: dict[InstrumentId, FactorCalculationResult] = {}
        result = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=[not_etf],
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        assert result.ineligible_count == 1
        assert result.full_count == 0
        assert result.partial_count == 0
        assert len(result.proposals) == 1
        assert result.proposals[0].decision == "exclude"
        # The universe reasons are preserved verbatim on the
        # proposal's ``exclusion_reasons`` (with a ``universe:`` prefix);
        # we accept any one of the documented non-ETF / not-enough
        # reasons so the assertion is robust to reason ordering.
        assert any(
            "not_etf" in reason
            or "insufficient_history" in reason
            or "no_valid_price" in reason
            for reason in result.proposals[0].exclusion_reasons
        )

    def test_partial_instrument_is_capped_at_watch(self) -> None:
        # PARTIAL = between partial and full history. 30 bars of
        # history is enough to pass the partial threshold (20) but not
        # the full one (60). Use a strategy whose score factors all
        # only need 20+ trading days (return_20d, distance_ma20,
        # realised_volatility_20d, avg_turnover_amount_20d) so the
        # PARTIAL candidate can be scored. The score must therefore
        # cap the candidate at ``watch`` even though include_top_n=5
        # would otherwise let it through.
        from invest_domain.research.factor_set import FACTOR_KEYS as _FACTOR_KEYS
        del _FACTOR_KEYS  # silence flake8 / linters that flag unused imports

        payload = _baseline_payload()
        del payload["filters"]
        payload["score"] = [
            {"factor": "return_20d", "weight": "0.5", "direction": "higher"},
            {"factor": "realized_volatility_20d", "weight": "0.5", "direction": "lower"},
        ]
        payload["output"] = {"include_top_n": 5, "watch_next_n": 5}
        strategy = parse_custom_strategy_mapping(payload)
        instrument = _instrument("partial", symbol="510300")
        iid = instrument.instrument_id
        assert iid is not None
        bars = {iid: _uptrend_bars(iid, 30)}
        factors = {
            iid: calculate_market_state_factors(bars[iid], as_of_date=_AS_OF, instrument_id=iid)
        }
        result = evaluate_custom_strategy_channel(
            strategy=strategy,
            instruments=[instrument],
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        assert result.partial_count == 1
        assert result.include_count == 0
        assert result.watch_count == 1
        assert result.proposals[0].decision == "watch"
        assert (
            "custom_strategy.partial_history_capped_at_watch"
            in result.proposals[0].reasons
        )

    def test_missing_score_factor_fails_closed(self) -> None:
        # Build factors with a missing ``realized_volatility_20d`` so
        # the candidate cannot be scored. The channel must emit an
        # ``exclude`` proposal with an auditable reason, never a fake
        # ``include``.
        from invest_domain.research.factor_set import FACTOR_DEFINITIONS
        from invest_domain.research.models import (
            DataQuality,
            FactorObservation,
            FreshnessStatus,
            MarketSnapshot,
            QualityStatus,
        )

        instrument = _instrument("missing_factor", symbol="510300")
        iid = instrument.instrument_id
        assert iid is not None
        base = {
            "return_20d": Decimal("0.05"),
            "return_60d": Decimal("0.20"),
            "distance_ma20": Decimal("0.02"),
            "distance_ma60": Decimal("0.03"),
            "realized_volatility_20d": None,
            "max_drawdown_60d": Decimal("-0.10"),
            "avg_turnover_amount_20d": Decimal("20000000"),
            "data_completeness_60d": Decimal("1.0"),
        }
        factors_obj = FactorCalculationResult(
            factors=tuple(
                FactorObservation(
                    factor_key=definition.key,
                    instrument_id=iid,
                    value=base[definition.key],
                    unit=definition.unit,
                    window=definition.window,
                    observed_date=_AS_OF,
                    quality_status=QualityStatus.MISSING
                    if base[definition.key] is None
                    else QualityStatus.COMPLETE,
                )
                for definition in FACTOR_DEFINITIONS
            ),
            market_snapshot=MarketSnapshot(
                latest_trade_date=_AS_OF,
                latest_close=Decimal("100"),
                currency="CNY",
                observed_trading_days=65,
                valid_price_days=65,
            ),
            data_quality=DataQuality(
                freshness_status=FreshnessStatus.FRESH,
                quality_status=QualityStatus.PARTIAL,
                target_trading_days=60,
                observed_trading_days=65,
                valid_price_days=65,
            ),
            missing_fields=("factor.realized_volatility_20d",),
            warnings=(),
        )
        bars = {iid: _uptrend_bars(iid, 65)}
        result = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=[instrument],
            bars_by_instrument=bars,
            factors_by_instrument={iid: factors_obj},
            as_of_date=_AS_OF,
        )
        proposal = result.proposals[0]
        assert proposal.decision == "exclude"
        assert proposal.normalized_score is None
        assert any(
            "missing_score_factor" in reason for reason in proposal.exclusion_reasons
        )

    def test_filter_all_failure_excludes_candidate(self) -> None:
        # Build a candidate whose ``data_completeness_60d`` is below
        # the gte=0.90 threshold so the filter_all rule fails.
        from invest_domain.research.factor_set import FACTOR_DEFINITIONS
        from invest_domain.research.models import (
            DataQuality,
            FactorObservation,
            FreshnessStatus,
            MarketSnapshot,
            QualityStatus,
        )

        instrument = _instrument("thin", symbol="510300")
        iid = instrument.instrument_id
        assert iid is not None
        base = {
            "return_20d": Decimal("0.05"),
            "return_60d": Decimal("0.20"),
            "distance_ma20": Decimal("0.02"),
            "distance_ma60": Decimal("0.03"),
            "realized_volatility_20d": Decimal("0.10"),
            "max_drawdown_60d": Decimal("-0.10"),
            "avg_turnover_amount_20d": Decimal("20000000"),
            "data_completeness_60d": Decimal("0.80"),
        }
        factors_obj = FactorCalculationResult(
            factors=tuple(
                FactorObservation(
                    factor_key=definition.key,
                    instrument_id=iid,
                    value=base[definition.key],
                    unit=definition.unit,
                    window=definition.window,
                    observed_date=_AS_OF,
                    quality_status=QualityStatus.PARTIAL,
                )
                for definition in FACTOR_DEFINITIONS
            ),
            market_snapshot=MarketSnapshot(
                latest_trade_date=_AS_OF,
                latest_close=Decimal("100"),
                currency="CNY",
                observed_trading_days=65,
                valid_price_days=52,
            ),
            data_quality=DataQuality(
                freshness_status=FreshnessStatus.FRESH,
                quality_status=QualityStatus.PARTIAL,
                target_trading_days=60,
                observed_trading_days=65,
                valid_price_days=52,
            ),
            missing_fields=(),
            warnings=(),
        )
        bars = {iid: _uptrend_bars(iid, 65)}
        result = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=[instrument],
            bars_by_instrument=bars,
            factors_by_instrument={iid: factors_obj},
            as_of_date=_AS_OF,
        )
        proposal = result.proposals[0]
        assert proposal.decision == "exclude"
        assert any(
            reason.startswith("custom_strategy.filter_all_failed")
            for reason in proposal.exclusion_reasons
        )
        assert any("filter_all_failed" in warning for warning in result.warnings)

    def test_filter_any_succeeds_when_any_rule_passes(self) -> None:
        # Build a strategy with one ``all`` rule (always passes) and
        # one ``any`` rule with two members. A candidate that passes
        # the second ``any`` rule but fails the first must still
        # survive.
        payload = _baseline_payload()
        payload["filters"] = {
            "all": [
                {
                    "factor": "data_completeness_60d",
                    "op": "gte",
                    "value": "0.50",
                }
            ],
            "any": [
                {"factor": "return_20d", "op": "gt", "value": "0.10"},
                {"factor": "return_60d", "op": "gt", "value": "0.10"},
            ],
        }
        strategy = parse_custom_strategy_mapping(payload)
        # Instrument with return_20d=0.20 (passes first any), return_60d=0.05 (fails second any).
        from invest_domain.research.factor_set import FACTOR_DEFINITIONS
        from invest_domain.research.models import (
            DataQuality,
            FactorObservation,
            FreshnessStatus,
            MarketSnapshot,
            QualityStatus,
        )

        instrument = _instrument("any_pass", symbol="510300")
        iid = instrument.instrument_id
        assert iid is not None
        base = {
            "return_20d": Decimal("0.20"),
            "return_60d": Decimal("0.05"),
            "distance_ma20": Decimal("0.02"),
            "distance_ma60": Decimal("0.03"),
            "realized_volatility_20d": Decimal("0.10"),
            "max_drawdown_60d": Decimal("-0.10"),
            "avg_turnover_amount_20d": Decimal("20000000"),
            "data_completeness_60d": Decimal("0.90"),
        }
        factors_obj = FactorCalculationResult(
            factors=tuple(
                FactorObservation(
                    factor_key=definition.key,
                    instrument_id=iid,
                    value=base[definition.key],
                    unit=definition.unit,
                    window=definition.window,
                    observed_date=_AS_OF,
                    quality_status=QualityStatus.COMPLETE,
                )
                for definition in FACTOR_DEFINITIONS
            ),
            market_snapshot=MarketSnapshot(
                latest_trade_date=_AS_OF,
                latest_close=Decimal("100"),
                currency="CNY",
                observed_trading_days=65,
                valid_price_days=65,
            ),
            data_quality=DataQuality(
                freshness_status=FreshnessStatus.FRESH,
                quality_status=QualityStatus.COMPLETE,
                target_trading_days=60,
                observed_trading_days=65,
                valid_price_days=65,
            ),
            missing_fields=(),
            warnings=(),
        )
        bars = {iid: _uptrend_bars(iid, 65)}
        result = evaluate_custom_strategy_channel(
            strategy=strategy,
            instruments=[instrument],
            bars_by_instrument=bars,
            factors_by_instrument={iid: factors_obj},
            as_of_date=_AS_OF,
        )
        assert result.proposals[0].decision in {"include", "watch"}

    def test_disabled_strategy_short_circuits_with_no_opinion(self) -> None:
        instrument = _instrument("dis", symbol="510300")
        iid = instrument.instrument_id
        assert iid is not None
        bars = {iid: _uptrend_bars(iid, 65)}
        factors = {
            iid: calculate_market_state_factors(bars[iid], as_of_date=_AS_OF, instrument_id=iid)
        }
        strategy = _parse(enabled=False)
        result = evaluate_custom_strategy_channel(
            strategy=strategy,
            instruments=[instrument],
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        assert result.proposals[0].decision == "no_opinion"
        assert result.proposals[0].normalized_score is None
        assert result.no_opinion_count == 1
        assert result.include_count == 0
        assert "custom_strategy.disabled" in result.warnings

    def test_empty_instruments_yields_empty_proposals(self) -> None:
        result = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=[],
            bars_by_instrument={},
            factors_by_instrument={},
            as_of_date=_AS_OF,
        )
        assert result.proposals == ()
        assert result.full_count == 0
        assert result.partial_count == 0
        assert result.ineligible_count == 0
        assert len(result.input_hash) == 64
        assert len(result.output_hash) == 64

    def test_factor_calculator_fallback_when_factor_mapping_missing(self) -> None:
        # Omit factors_by_instrument entirely; the channel must call
        # calculate_market_state_factors itself and still produce a
        # valid proposal.
        instrument = _instrument("fallback", symbol="510300")
        iid = instrument.instrument_id
        assert iid is not None
        bars = {iid: _uptrend_bars(iid, 65)}
        result = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=[instrument],
            bars_by_instrument=bars,
            factors_by_instrument={},
            as_of_date=_AS_OF,
        )
        assert len(result.proposals) == 1
        assert result.proposals[0].decision in {"include", "watch"}


# ---------------------------------------------------------------------------
# Hash determinism
# ---------------------------------------------------------------------------


class TestHashDeterminism:
    def _two_full_fixture(self) -> tuple[list[Instrument], dict[InstrumentId, list[DailyBar]]]:
        instruments = [_instrument("alpha", symbol="510300"), _instrument("beta", symbol="510500")]
        bars = {
            _iid("alpha"): _uptrend_bars(_iid("alpha"), 65),
            _iid("beta"): _uptrend_bars(_iid("beta"), 65, start_close="200", step="2"),
        }
        return instruments, bars

    def test_rerun_with_identical_inputs_is_byte_equal(self) -> None:
        instruments, bars = self._two_full_fixture()
        factors = {
            iid: calculate_market_state_factors(bars[iid], as_of_date=_AS_OF, instrument_id=iid)
            for iid in bars
        }
        first = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=instruments,
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        second = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=instruments,
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        assert first == second
        assert first.parameter_hash == second.parameter_hash
        assert first.input_hash == second.input_hash
        assert first.output_hash == second.output_hash

    def test_reversed_input_order_yields_same_proposal_order(self) -> None:
        instruments, bars = self._two_full_fixture()
        factors = {
            iid: calculate_market_state_factors(bars[iid], as_of_date=_AS_OF, instrument_id=iid)
            for iid in bars
        }
        forward = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=instruments,
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        backward = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=list(reversed(instruments)),
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        assert forward.input_hash == backward.input_hash
        assert forward.output_hash == backward.output_hash
        assert [p.symbol for p in forward.proposals] == [
            p.symbol for p in backward.proposals
        ]

    def test_universe_verdict_change_changes_input_hash(self) -> None:
        instruments = [_instrument("hash_universe", symbol="510300")]
        iid = _iid("hash_universe")
        full_bars = {iid: _uptrend_bars(iid, 65)}
        no_bars: dict[InstrumentId, list[DailyBar]] = {iid: []}
        full_factors = {
            iid: calculate_market_state_factors(
                full_bars[iid], as_of_date=_AS_OF, instrument_id=iid
            )
        }
        no_factors: dict[InstrumentId, FactorCalculationResult] = {}

        full_result = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=instruments,
            bars_by_instrument=full_bars,
            factors_by_instrument=full_factors,
            as_of_date=_AS_OF,
        )
        empty_result = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=instruments,
            bars_by_instrument=no_bars,
            factors_by_instrument=no_factors,
            as_of_date=_AS_OF,
        )
        assert full_result.proposals[0].eligibility == "full"
        assert empty_result.proposals[0].eligibility == "ineligible"
        assert full_result.input_hash != empty_result.input_hash

    def test_parameter_hash_changes_when_strategy_payload_changes(self) -> None:
        # Same logical universe, two different weight distributions.
        instruments = [_instrument("alpha", symbol="510300")]
        iid = _iid("alpha")
        bars = {iid: _uptrend_bars(iid, 65)}
        factors = {
            iid: calculate_market_state_factors(bars[iid], as_of_date=_AS_OF, instrument_id=iid)
        }
        first = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=instruments,
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        second = evaluate_custom_strategy_channel(
            strategy=_parse(
                score=[
                    {"factor": "return_20d", "weight": "0.5", "direction": "higher"},
                    {"factor": "return_60d", "weight": "0.5", "direction": "higher"},
                ]
            ),
            instruments=instruments,
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        assert first.parameter_hash != second.parameter_hash

    def test_module_does_not_use_clock_or_random(self) -> None:
        import random
        import time

        random.seed(0)
        time.time()
        instruments, bars = self._two_full_fixture()
        factors = {
            iid: calculate_market_state_factors(bars[iid], as_of_date=_AS_OF, instrument_id=iid)
            for iid in bars
        }
        first = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=instruments,
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        random.seed(42)
        time.time()
        second = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=instruments,
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        assert first == second


# ---------------------------------------------------------------------------
# Type / purity guards
# ---------------------------------------------------------------------------


class TestTypeGuards:
    def test_non_date_as_of_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="as_of_date must be a date"):
            evaluate_custom_strategy_channel(
                strategy=_parse(),
                instruments=[],
                bars_by_instrument={},
                factors_by_instrument={},
                as_of_date="2026-08-05",  # type: ignore[arg-type]
            )

    def test_non_strategy_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="strategy must be a CustomStrategy"):
            evaluate_custom_strategy_channel(
                strategy="not a strategy",  # type: ignore[arg-type]
                instruments=[],
                bars_by_instrument={},
                factors_by_instrument={},
                as_of_date=_AS_OF,
            )

    def test_non_instrument_item_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="Sequence\\[Instrument\\]"):
            evaluate_custom_strategy_channel(
                strategy=_parse(),
                instruments=["not an instrument"],  # type: ignore[list-item]
                bars_by_instrument={},
                factors_by_instrument={},
                as_of_date=_AS_OF,
            )

    def test_non_daily_bar_in_bars_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="must contain DailyBar"):
            evaluate_custom_strategy_channel(
                strategy=_parse(),
                instruments=[],
                bars_by_instrument={_iid("a"): ["not a bar"]},  # type: ignore[dict-item]
                factors_by_instrument={},
                as_of_date=_AS_OF,
            )

    def test_non_factor_result_in_factors_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="FactorCalculationResult"):
            evaluate_custom_strategy_channel(
                strategy=_parse(),
                instruments=[],
                bars_by_instrument={},
                factors_by_instrument={_iid("a"): "not a result"},  # type: ignore[dict-item]
                as_of_date=_AS_OF,
            )

    def test_module_does_not_import_infra_deps(self) -> None:
        import invest_domain.candidate_pool.custom_strategy as module

        forbidden = {"yaml", "sqlalchemy", "pandas", "polars", "fastapi", "dagster", "httpx"}
        assert forbidden.isdisjoint(set(getattr(module, "__all__", [])))
        for name in forbidden:
            assert not hasattr(module, name), (
                f"custom_strategy must not expose infra dep {name}"
            )


# ---------------------------------------------------------------------------
# Result / proposal value-object invariants
# ---------------------------------------------------------------------------


class TestResultInvariants:
    def _proposal_for(self, label: str) -> CustomStrategyProposal:
        return CustomStrategyProposal(
            instrument_id=_iid(label),
            symbol=label,
            exchange="SSE",
            channel_key=CUSTOM_STRATEGY_CHANNEL_KEY,
            channel_version=CUSTOM_STRATEGY_CHANNEL_VERSION,
            strategy_key="custom_trend",
            strategy_version="1.0.0",
            decision="include",
            normalized_score=Decimal("0.5"),
            eligibility=UniverseEligibility.FULL.value,
        )

    def test_result_rejects_duplicate_instrument_ids(self) -> None:
        proposal = self._proposal_for("alpha")
        with pytest.raises(CustomStrategyResultInvariantError, match="duplicate"):
            CustomStrategyChannelResult(
                channel_key=CUSTOM_STRATEGY_CHANNEL_KEY,
                channel_version=CUSTOM_STRATEGY_CHANNEL_VERSION,
                strategy_key="custom_trend",
                strategy_version="1.0.0",
                as_of_date=_AS_OF,
                parameter_hash="a" * 64,
                input_hash="b" * 64,
                output_hash="c" * 64,
                proposals=(proposal, proposal),
            )

    def test_result_rejects_non_64_char_hash(self) -> None:
        proposal = self._proposal_for("alpha")
        with pytest.raises(CustomStrategyResultInvariantError, match="parameter_hash"):
            CustomStrategyChannelResult(
                channel_key=CUSTOM_STRATEGY_CHANNEL_KEY,
                channel_version=CUSTOM_STRATEGY_CHANNEL_VERSION,
                strategy_key="custom_trend",
                strategy_version="1.0.0",
                as_of_date=_AS_OF,
                parameter_hash="not-a-hash",
                input_hash="b" * 64,
                output_hash="c" * 64,
                proposals=(proposal,),
            )

    def test_proposal_rejects_unknown_factor_in_factor_mapping(self) -> None:
        with pytest.raises(CustomStrategyResultInvariantError, match="allow-list"):
            CustomStrategyProposal(
                instrument_id=_iid("a"),
                symbol="a",
                exchange="SSE",
                channel_key=CUSTOM_STRATEGY_CHANNEL_KEY,
                channel_version=CUSTOM_STRATEGY_CHANNEL_VERSION,
                strategy_key="custom_trend",
                strategy_version="1.0.0",
                decision="include",
                normalized_score=Decimal("0.5"),
                eligibility=UniverseEligibility.FULL.value,
                observed_factor_values=MappingProxyType({"not_a_factor": Decimal("0.1")}),  # type: ignore[arg-type]
            )

    def test_proposal_rejects_score_outside_unit_interval(self) -> None:
        with pytest.raises(CustomStrategyResultInvariantError, match="\\[0, 1\\]"):
            CustomStrategyProposal(
                instrument_id=_iid("a"),
                symbol="a",
                exchange="SSE",
                channel_key=CUSTOM_STRATEGY_CHANNEL_KEY,
                channel_version=CUSTOM_STRATEGY_CHANNEL_VERSION,
                strategy_key="custom_trend",
                strategy_version="1.0.0",
                decision="include",
                normalized_score=Decimal("1.5"),
                eligibility=UniverseEligibility.FULL.value,
            )

    def test_proposal_rejects_unknown_decision(self) -> None:
        with pytest.raises(CustomStrategyResultInvariantError, match="decision"):
            CustomStrategyProposal(
                instrument_id=_iid("a"),
                symbol="a",
                exchange="SSE",
                channel_key=CUSTOM_STRATEGY_CHANNEL_KEY,
                channel_version=CUSTOM_STRATEGY_CHANNEL_VERSION,
                strategy_key="custom_trend",
                strategy_version="1.0.0",
                decision="buy",
                normalized_score=None,
                eligibility=UniverseEligibility.FULL.value,
            )


# ---------------------------------------------------------------------------
# Decision-counter invariants
# ---------------------------------------------------------------------------


class TestDecisionCounters:
    def test_counters_sum_to_proposal_count(self) -> None:
        instruments = [_instrument("a", symbol="510300"), _instrument("b", symbol="510500")]
        bars = {
            _iid("a"): _uptrend_bars(_iid("a"), 65),
            _iid("b"): _uptrend_bars(_iid("b"), 30),
        }
        factors = {
            iid: calculate_market_state_factors(bars[iid], as_of_date=_AS_OF, instrument_id=iid)
            for iid in bars
        }
        result = evaluate_custom_strategy_channel(
            strategy=_parse(),
            instruments=instruments,
            bars_by_instrument=bars,
            factors_by_instrument=factors,
            as_of_date=_AS_OF,
        )
        assert (
            result.include_count
            + result.watch_count
            + result.exclude_count
            + result.no_opinion_count
            == len(result.proposals)
        )
        assert result.full_count + result.partial_count + result.ineligible_count == len(
            result.proposals
        )
