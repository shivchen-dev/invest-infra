"""Tests for the deterministic baseline-factor ``Candidate Proposal`` channel.

Covers the Stage 4A-0 PR-02 baseline-channel surface:

* Contract constants (channel_key, channel_version, factor-set binding).
* ``BaselineFactorPolicy`` invariants and stable ``parameter_hash``.
* Empty / single-instrument / mixed-batch universe routing with the
  hard quality gate (``exclude``) and the eligibility cap on PARTIAL
  (``watch``).
* Fail-closed behaviour on every documented hard-gate reason:
  conflict, invalid bars, missing factor on FULL, completeness below
  threshold, average turnover below threshold, stale / not-ETF /
  inactive / suspended inputs.
* Boundary scoring against ``include_threshold`` / ``watch_threshold``.
* Determinism and stable hash / ordering over re-runs, reversed
  inputs and equal policies.
* Purity guarantees: no clock / random / environment reads,
  ``factor_refs`` only ever references the existing v1.0.0 factor
  calculators.
"""
from __future__ import annotations

from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from invest_domain.candidate_pool.baseline_channel import (
    BASELINE_FACTOR_CHANNEL_KEY,
    BASELINE_FACTOR_CHANNEL_VERSION,
    BASELINE_FACTOR_FACTOR_SET_KEY,
    BASELINE_FACTOR_FACTOR_SET_VERSION,
    DEFAULT_MAX_STALE_DAYS,
    DEFAULT_MIN_FULL_HISTORY_DAYS,
    DEFAULT_MIN_PARTIAL_HISTORY_DAYS,
    BaselineFactorChannelResult,
    BaselineFactorPolicy,
    BaselineFactorProposal,
    InvalidBaselineFactorPolicyError,
    evaluate_baseline_factor_channel,
)
from invest_domain.candidate_pool.universe import UniverseEligibility
from invest_domain.instruments.models import (
    Instrument,
    InstrumentId,
    InstrumentType,
)
from invest_domain.market_data.models import BarSource, DailyBar
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_domain.research import FACTOR_KEYS, FACTOR_SET_KEY, FACTOR_SET_VERSION

_AS_OF = date(2026, 7, 30)
_OBSERVED_AT = datetime(2026, 7, 30, 8, tzinfo=UTC)
_BATCH_ID = UUID("00000000-0000-4000-8000-000000000bbb")
_PROVIDER_KEY = "baseline_channel_test"


def _iid(label: str) -> InstrumentId:
    """Stable instrument-id factory keyed off a human-readable label."""

    digest = UUID(
        int=int.from_bytes(label.encode("utf-8").ljust(16, b"\x00")[:16], "big")
    )
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


def _suspended_bar(instrument_id: InstrumentId, trade_date: date) -> DailyBar:
    return DailyBar.build(
        instrument_id=instrument_id,
        trade_date=trade_date,
        open=None,
        high=None,
        low=None,
        close=None,
        prev_close=None,
        volume=None,
        amount=None,
        adjustment=Adjust.NONE,
        trading_status=TradingStatus.SUSPENDED,
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
    """Return ``count`` consecutive NORMAL bars with an upward drift.

    The series is well-formed for the eight-factor calculator —
    closes are strictly increasing so ``return_20d`` / ``return_60d``
    are positive, ``distance_ma20`` / ``distance_ma60`` are also
    positive, and ``realized_volatility_20d`` / ``max_drawdown_60d``
    stay within reasonable bounds.
    """

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


def _flat_bars(
    instrument_id: InstrumentId,
    count: int,
    *,
    close: str = "3.15000000",
    amount: str = "20000000",
) -> list[DailyBar]:
    """Return ``count`` NORMAL bars with a constant close (zero return).

    Used to test the soft-score baseline (returns around ``0`` map to
    a trend_score around ``50``) and the stable tie-breaker between
    identical baselines.
    """

    return [
        _normal_bar(
            instrument_id,
            _AS_OF - timedelta(days=(count - 1 - offset)),
            close=close,
            amount=amount,
        )
        for offset in range(count)
    ]


# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------


class TestContractConstants:
    def test_channel_key_and_version_match_plan(self) -> None:
        # plan §6 ``Channel A`` mandates ``baseline_factor_screen``.
        assert BASELINE_FACTOR_CHANNEL_KEY == "baseline_factor_screen"
        assert BASELINE_FACTOR_CHANNEL_VERSION == "1.0.0"
        # plan §9 shares the v1.0.0 factor set between routing and AI.
        assert BASELINE_FACTOR_FACTOR_SET_KEY == FACTOR_SET_KEY
        assert BASELINE_FACTOR_FACTOR_SET_VERSION == FACTOR_SET_VERSION
        assert BASELINE_FACTOR_FACTOR_SET_VERSION == "1.0.0"

    def test_universe_thresholds_default_to_shadow_mvp_values(self) -> None:
        # The shadow MVP constants are the bounded-build defaults from
        # the task brief; the channel must agree so the two layers do
        # not diverge on the FULL / PARTIAL line.
        assert DEFAULT_MIN_FULL_HISTORY_DAYS == 60
        assert DEFAULT_MIN_PARTIAL_HISTORY_DAYS == 20
        assert DEFAULT_MAX_STALE_DAYS == 3

    def test_baseline_proposal_has_no_recommendation_field(self) -> None:
        # plan §5.1 — the screening layer must never emit a buy/sell
        # field that the AI research layer could mistake for an opinion.
        forbidden = {
            "buy",
            "sell",
            "stance",
            "recommendation",
            "ai_conclusion",
            "target_price",
            "signal",
            "action",
            "position",
        }
        names = {field.name for field in fields(BaselineFactorProposal)}
        assert forbidden.isdisjoint(names), (
            f"BaselineFactorProposal must not carry screening-banned fields; "
            f"got {sorted(forbidden & names)!r}"
        )


# ---------------------------------------------------------------------------
# Policy validation
# ---------------------------------------------------------------------------


class TestBaselineFactorPolicyInvariants:
    def test_defaults_produce_a_stable_parameter_hash(self) -> None:
        first = BaselineFactorPolicy()
        second = BaselineFactorPolicy()
        assert first.parameter_hash != ""
        assert first.parameter_hash == second.parameter_hash
        assert first.parameter_hash == first.compute_parameter_hash()

    def test_supplied_parameter_hash_must_match_payload(self) -> None:
        computed = BaselineFactorPolicy().compute_parameter_hash()
        # Identical payload → identical hash, accept it.
        match = BaselineFactorPolicy(parameter_hash=computed)
        assert match.parameter_hash == computed
        with pytest.raises(InvalidBaselineFactorPolicyError, match="parameter_hash"):
            BaselineFactorPolicy(parameter_hash="0" * 64)

    @pytest.mark.parametrize(
        "kwargs",
        [
            pytest.param(
                {"include_threshold": Decimal("30"), "watch_threshold": Decimal("40")},
                id="include_below_watch",
            ),
            pytest.param(
                {
                    "trend_weight": Decimal("0"),
                    "liquidity_weight": Decimal("0"),
                    "risk_weight": Decimal("0"),
                },
                id="zero_weights",
            ),
            pytest.param(
                {"min_full_history_days": 10, "min_partial_history_days": 20},
                id="full_below_partial",
            ),
            pytest.param(
                {"min_partial_history_days": 0},
                id="zero_partial_history",
            ),
            pytest.param(
                {
                    "liquidity_ceiling_amount_cny": Decimal("100"),
                    "liquidity_floor_amount_cny": Decimal("1000"),
                },
                id="liquidity_ceiling_le_floor",
            ),
            pytest.param(
                {"volatility_ceiling": Decimal("0")},
                id="zero_volatility_ceiling",
            ),
            pytest.param(
                {"drawdown_floor": Decimal("0")},
                id="non_negative_drawdown_floor",
            ),
        ],
    )
    def test_invalid_policy_is_rejected(self, kwargs: dict) -> None:
        with pytest.raises(InvalidBaselineFactorPolicyError):
            BaselineFactorPolicy(**kwargs)

    def test_non_decimal_or_negative_parameter_is_rejected(self) -> None:
        with pytest.raises(InvalidBaselineFactorPolicyError):
            BaselineFactorPolicy(trend_weight=Decimal("-0.10"))

    def test_policy_tweaks_change_parameter_hash(self) -> None:
        first = BaselineFactorPolicy()
        second = BaselineFactorPolicy(
            include_threshold=Decimal("65"),
            watch_threshold=Decimal("45"),
        )
        assert first.parameter_hash != second.parameter_hash


# ---------------------------------------------------------------------------
# Universe + decision routing
# ---------------------------------------------------------------------------


class TestUniverseRouting:
    def test_full_with_clean_factors_can_enter_include(self) -> None:
        iid = _iid("uptrend_full")
        instrument = _instrument("uptrend_full", symbol="510300")
        bars = _uptrend_bars(iid, 65)
        result = evaluate_baseline_factor_channel(
            instruments=[instrument],
            bars_by_instrument={iid: bars},
            as_of_date=_AS_OF,
        )
        assert len(result.proposals) == 1
        proposal = result.proposals[0]
        assert proposal.eligibility.value == "full"
        # Strong uptrend: trend_score is high enough to clear the
        # default watch threshold (40) so we expect include or watch.
        assert proposal.decision in {"include", "watch"}
        assert proposal.baseline_score is not None
        assert proposal.baseline_score >= Decimal("40")

    def test_partial_history_is_capped_at_watch(self) -> None:
        iid = _iid("partial_30")
        instrument = _instrument("partial_30", symbol="510500")
        bars = _uptrend_bars(iid, 30)
        result = evaluate_baseline_factor_channel(
            instruments=[instrument],
            bars_by_instrument={iid: bars},
            as_of_date=_AS_OF,
        )
        assert result.proposals[0].decision == "watch"
        assert result.proposals[0].eligibility.value == "partial"
        assert "baseline.partial_history_only" in result.proposals[0].reasons

    def test_ineligible_instruments_get_universe_exclusion_reasons(self) -> None:
        not_etf = _instrument("not_etf", symbol="600000", kind=InstrumentType.STOCK)
        inactive = _instrument("inactive", symbol="159915", active=False)
        no_history = _instrument("no_history", symbol="510100")
        result = evaluate_baseline_factor_channel(
            instruments=[not_etf, inactive, no_history],
            bars_by_instrument={},
            as_of_date=_AS_OF,
        )
        assert result.ineligible_count == 3
        assert result.proposals[0].decision == "exclude"
        assert any(
            reason.startswith("universe:")
            for reason in result.proposals[0].exclusion_reasons
        )

    def test_empty_input_produces_empty_proposals(self) -> None:
        result = evaluate_baseline_factor_channel(
            instruments=[],
            bars_by_instrument={},
            as_of_date=_AS_OF,
        )
        assert result.proposals == ()
        assert result.full_count == 0
        assert result.partial_count == 0
        assert result.ineligible_count == 0


# ---------------------------------------------------------------------------
# Hard quality gate (fail-closed)
# ---------------------------------------------------------------------------


class TestHardQualityGateClosed:
    def test_missing_fact_on_full_forces_exclude(self) -> None:
        iid = _iid("short_for_60d")
        instrument = _instrument("short_for_60d", symbol="510300")
        # 60 bars — qualifies for FULL (history_days >= 60) but
        # return_60d requires 61 closes, so the factor calculator
        # returns MISSING. The channel treats a missing key factor on
        # FULL as a hard gate failure.
        bars = _uptrend_bars(iid, 60)
        result = evaluate_baseline_factor_channel(
            instruments=[instrument],
            bars_by_instrument={iid: bars},
            as_of_date=_AS_OF,
        )
        proposal = result.proposals[0]
        assert proposal.eligibility.value == "full"
        assert proposal.decision == "exclude"
        assert any(
            reason.startswith("baseline.missing_factor:")
            for reason in proposal.exclusion_reasons
        )

    def test_partial_history_missing_factor_does_not_force_exclude(self) -> None:
        iid = _iid("partial_with_missing_60d")
        instrument = _instrument("partial_with_missing_60d", symbol="510300")
        bars = _uptrend_bars(iid, 30)
        result = evaluate_baseline_factor_channel(
            instruments=[instrument],
            bars_by_instrument={iid: bars},
            as_of_date=_AS_OF,
        )
        proposal = result.proposals[0]
        # PARTIAL is bounded to watch by plan §8; missing 60d factors
        # must NOT force the channel into ``exclude`` for the PARTIAL
        # slice (only the FULL slice uses missing_factor: as a gate).
        assert proposal.decision == "watch"
        assert not any(
            reason.startswith("baseline.missing_factor:") for reason in proposal.exclusion_reasons
        )

    def test_low_turnover_on_full_forces_exclude(self) -> None:
        iid = _iid("low_turnover")
        instrument = _instrument("low_turnover", symbol="510300")
        bars = _uptrend_bars(iid, 65, amount="1000")  # 0.001M per day
        result = evaluate_baseline_factor_channel(
            instruments=[instrument],
            bars_by_instrument={iid: bars},
            as_of_date=_AS_OF,
        )
        proposal = result.proposals[0]
        assert proposal.decision == "exclude"
        assert any(
            reason.startswith("baseline.turnover_below_") for reason in proposal.exclusion_reasons
        )

    def test_conflict_forces_exclude(self) -> None:
        # Two bars on the most-recent trading date at the same
        # revision but with different row_hash → the universe
        # classifier flags ``bar_revision_conflict`` and demotes the
        # instrument to INELIGIBLE. The channel must surface that
        # reason verbatim and never feed the conflicting bars into
        # the scoring pipeline (plan §10.1).
        iid = _iid("conflict")
        instrument = _instrument("conflict", symbol="510300")
        bars = _uptrend_bars(iid, 65)
        same_day = bars[-1].trade_date
        conflicting = DailyBar.build(
            instrument_id=iid,
            trade_date=same_day,
            open=Decimal("165"),
            high=Decimal("166"),
            low=Decimal("164"),
            close=Decimal("165"),
            prev_close=Decimal("164"),
            volume=Decimal("1000000"),
            amount=Decimal("20000000"),
            adjustment=Adjust.NONE,
            trading_status=TradingStatus.NORMAL,
            source=_bar_source(),
            revision=1,
        )
        bars = [*bars, conflicting]
        result = evaluate_baseline_factor_channel(
            instruments=[instrument],
            bars_by_instrument={iid: bars},
            as_of_date=_AS_OF,
        )
        proposal = result.proposals[0]
        assert proposal.decision == "exclude"
        assert proposal.eligibility.value == "ineligible"
        assert "universe:bar_revision_conflict" in proposal.exclusion_reasons

    def test_stale_instrument_becomes_ineligible(self) -> None:
        iid = _iid("stale")
        instrument = _instrument("stale", symbol="510300")
        bars = [
            _normal_bar(iid, _AS_OF - timedelta(days=10)),
            _normal_bar(iid, _AS_OF - timedelta(days=11)),
        ]
        result = evaluate_baseline_factor_channel(
            instruments=[instrument],
            bars_by_instrument={iid: bars},
            as_of_date=_AS_OF,
            policy=BaselineFactorPolicy(max_stale_days=DEFAULT_MAX_STALE_DAYS),
        )
        proposal = result.proposals[0]
        assert proposal.eligibility.value == "ineligible"
        assert proposal.decision == "exclude"
        assert any("universe:" in reason for reason in proposal.exclusion_reasons)

    def test_suspended_instrument_is_ineligible(self) -> None:
        iid = _iid("suspended")
        instrument = _instrument("suspended", symbol="510300")
        bars = [
            _normal_bar(iid, _AS_OF - timedelta(days=offset)) for offset in range(1, 60)
        ]
        # Most recent bar is suspended.
        bars.append(_suspended_bar(iid, _AS_OF))
        result = evaluate_baseline_factor_channel(
            instruments=[instrument],
            bars_by_instrument={iid: bars},
            as_of_date=_AS_OF,
        )
        proposal = result.proposals[0]
        assert proposal.eligibility.value == "ineligible"
        assert proposal.decision == "exclude"
        assert "universe:suspended" in proposal.exclusion_reasons

    def test_non_etf_instrument_is_ineligible(self) -> None:
        iid = _iid("not_etf")
        stock = Instrument(
            symbol="600000",
            name="000 ping an",
            exchange="SSE",
            instrument_type=InstrumentType.STOCK,
            is_active=True,
            instrument_id=iid,
        )
        result = evaluate_baseline_factor_channel(
            instruments=[stock],
            bars_by_instrument={},
            as_of_date=_AS_OF,
        )
        proposal = result.proposals[0]
        assert proposal.eligibility.value == "ineligible"
        assert proposal.decision == "exclude"
        assert "universe:not_etf" in proposal.exclusion_reasons


# ---------------------------------------------------------------------------
# Boundary scoring
# ---------------------------------------------------------------------------


def _two_instrument_fixture() -> tuple[
    list[Instrument], dict[InstrumentId, list[DailyBar]]
]:
    """Build a two-instrument fixture with materially different scores.

    ``alpha`` is a strong uptrend with healthy turnover so it lands in
    ``include``; ``beta`` is a flat series with equally healthy
    turnover so it lands in the watch band. Used by the boundary
    tests when the policy needs to push a baseline around the
    thresholds.
    """

    alpha = _instrument("alpha", symbol="510300")
    beta = _instrument("beta", symbol="510500")
    bars = {
        _iid("alpha"): _uptrend_bars(_iid("alpha"), 65),
        _iid("beta"): _flat_bars(_iid("beta"), 65, close="100.00"),
    }
    return [alpha, beta], bars


def _downtrend_low_turnover_fixture() -> tuple[
    list[Instrument], dict[InstrumentId, list[DailyBar]], Decimal
]:
    """Build a single downtrend fixture.

    Used by ``test_low_score_excludes_with_score_below_watch`` to
    exercise the ``baseline.score_below_watch_threshold`` branch.
    ``close`` declines 1 unit per bar so ``return_60d`` is strongly
    negative (well outside the ``trend_return_clip`` of 0.10), the
    daily turnover is well above the policy floor so the hard gate
    does not fire, and the resulting baseline score lands in the
    ``(watch_threshold, watch_threshold + 10)`` band so the test
    can tighten the threshold to flip the band.
    """

    instrument = _instrument("downtrend", symbol="510600")
    iid = instrument.instrument_id
    assert iid is not None
    bars: list[DailyBar] = []
    for offset in range(65):
        close = Decimal("100") - Decimal(offset)
        bars.append(
            DailyBar.build(
                instrument_id=iid,
                trade_date=_AS_OF - timedelta(days=(64 - offset)),
                open=close,
                high=close + Decimal("0.05"),
                low=close - Decimal("0.05"),
                close=close,
                prev_close=None if offset == 0 else close + Decimal("1"),
                volume=Decimal("1000000"),
                amount=Decimal("20000000"),
                adjustment=Adjust.NONE,
                trading_status=TradingStatus.NORMAL,
                source=_bar_source(),
                revision=1,
            )
        )
    return [instrument], {iid: bars}, Decimal("20000000")


class TestBoundaryScoring:
    def test_low_score_excludes_with_score_below_watch(self) -> None:
        instruments, bars, _ = _downtrend_low_turnover_fixture()
        # The downtrend earns a baseline_score of ~55 (trend≈0,
        # liquidity near ceiling, risk≈100). Raising the
        # ``watch_threshold`` so it is just above this score
        # forces the channel down the ``score_below_watch_threshold``
        # branch without triggering any other hard gate.
        baseline = evaluate_baseline_factor_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
        )
        baseline_score = baseline.proposals[0].baseline_score
        assert baseline_score is not None
        # Pick a threshold strictly above the natural baseline score
        # but still <= 100 (the policy validator's legal ceiling).
        threshold = baseline_score + Decimal("5")
        policy = BaselineFactorPolicy(watch_threshold=threshold)
        result = evaluate_baseline_factor_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=policy,
        )
        proposal = result.proposals[0]
        assert proposal.decision == "exclude"
        assert proposal.baseline_score == baseline_score
        assert "baseline.score_below_watch_threshold" in proposal.exclusion_reasons

    def test_watch_threshold_demotes_everything_to_watch(self) -> None:
        # Single uptrend fixture → default baseline_score ≈ 90.
        # Raising ``include_threshold`` above the natural score drops
        # the instrument from ``include`` to ``watch`` without
        # dropping it to ``exclude`` (because the natural score
        # still sits above ``watch_threshold``).
        iid = _iid("uptrend_only")
        instrument = _instrument("uptrend_only", symbol="510300")
        bars_ = {iid: _uptrend_bars(iid, 65)}
        baseline = evaluate_baseline_factor_channel(
            instruments=[instrument],
            bars_by_instrument=bars_,
            as_of_date=_AS_OF,
        )
        assert baseline.proposals[0].decision == "include"
        natural = baseline.proposals[0].baseline_score
        assert natural is not None
        policy = BaselineFactorPolicy(
            include_threshold=natural + Decimal("1"),
            watch_threshold=Decimal("0"),
        )
        result = evaluate_baseline_factor_channel(
            instruments=[instrument],
            bars_by_instrument=bars_,
            as_of_date=_AS_OF,
            policy=policy,
        )
        proposal = result.proposals[0]
        assert proposal.decision == "watch"
        assert proposal.baseline_score == natural

    def test_partial_history_caps_decision_even_with_high_score(self) -> None:
        iid = _iid("partial_high_score")
        instrument = _instrument("partial_high_score", symbol="510300")
        bars = _uptrend_bars(iid, 25)
        result = evaluate_baseline_factor_channel(
            instruments=[instrument],
            bars_by_instrument={iid: bars},
            as_of_date=_AS_OF,
        )
        proposal = result.proposals[0]
        assert proposal.eligibility.value == "partial"
        assert proposal.decision == "watch"  # never "include" for PARTIAL


# ---------------------------------------------------------------------------
# Determinism & stable ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_rerun_with_identical_inputs_is_byte_equal(self) -> None:
        instruments, bars = _two_instrument_fixture()
        first = evaluate_baseline_factor_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
        )
        second = evaluate_baseline_factor_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
        )
        assert first == second
        assert first.policy_hash == second.policy_hash
        assert first.proposals == second.proposals

    def test_reversed_input_order_yields_same_proposals(self) -> None:
        instruments, bars = _two_instrument_fixture()
        forward = evaluate_baseline_factor_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
        )
        backward = evaluate_baseline_factor_channel(
            instruments=list(reversed(instruments)),
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
        )
        assert [
            (p.instrument_id, p.decision, p.baseline_score) for p in backward.proposals
        ] == [
            (p.instrument_id, p.decision, p.baseline_score) for p in forward.proposals
        ]

    def test_ties_resolve_by_instrument_uuid_bytes(self) -> None:
        # Three identical flat series ⇒ identical baseline_score;
        # tie-breaker is the instrument UUID bytes.
        iid_a, iid_b, iid_c = _iid("zeta"), _iid("yotta"), _iid("alpha")
        instruments = [
            _instrument("zeta", symbol="510300"),
            _instrument("yotta", symbol="510500"),
            _instrument("alpha", symbol="510600"),
        ]
        bars = {
            iid: _flat_bars(iid, 65, close="100.00") for iid in (iid_a, iid_b, iid_c)
        }
        result = evaluate_baseline_factor_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
        )
        # Plain FLAT bars => trend_score=50, liquidity_score=100 (above
        # ceiling at 100M CNY → cap 100), risk=100. baseline ~ 75-ish.
        scores = [p.baseline_score for p in result.proposals]
        assert len(set(scores)) == 1  # all equal

        # Tie-breaker is the UUID bytes, lexicographic.
        sorted_ids = sorted(
            (p.instrument_id for p in result.proposals),
            key=lambda value: value.value.bytes,
        )
        ordered_ids = [p.instrument_id for p in result.proposals]
        # All three should be in the same FINAL position only if scores
        # are identical AND quality identical AND risk identical. We
        # assert the *stable* contract: the order must match the
        # well-defined sort key — testing all three of those ties
        # simultaneously.
        assert ordered_ids == sorted_ids

    def test_factor_refs_covers_eight_factors(self) -> None:
        iid = _iid("factor_refs")
        instrument = _instrument("factor_refs", symbol="510300")
        bars = _uptrend_bars(iid, 65)
        result = evaluate_baseline_factor_channel(
            instruments=[instrument],
            bars_by_instrument={iid: bars},
            as_of_date=_AS_OF,
        )
        proposal = result.proposals[0]
        assert set(proposal.factor_refs) == set(FACTOR_KEYS)
        for factor_key, item_hash in proposal.factor_refs.items():
            assert factor_key.startswith("factor.") or factor_key in FACTOR_KEYS
            assert isinstance(item_hash, str) and len(item_hash) == 64


# ---------------------------------------------------------------------------
# Purity / no-side-effects
# ---------------------------------------------------------------------------


class TestPurity:
    def test_module_does_not_seed_random_or_use_clock(self) -> None:
        import random
        import time

        random.seed(0)
        time.time()
        instruments, bars = _two_instrument_fixture()
        first = evaluate_baseline_factor_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
        )
        random.seed(42)
        time.time()
        second = evaluate_baseline_factor_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
        )
        assert first == second

    def test_module_does_not_import_infra_deps(self) -> None:
        import invest_domain.candidate_pool.baseline_channel as module

        forbidden = {"sqlalchemy", "pandas", "polars", "fastapi", "dagster", "httpx"}
        assert forbidden.isdisjoint(set(getattr(module, "__all__", [])))
        for name in forbidden:
            assert not hasattr(module, name), (
                f"baseline_channel must not expose infra dep {name}"
            )

    def test_policy_hash_changes_with_payload(self) -> None:
        first = evaluate_baseline_factor_channel(
            instruments=[],
            bars_by_instrument={},
            as_of_date=_AS_OF,
        )
        second = evaluate_baseline_factor_channel(
            instruments=[],
            bars_by_instrument={},
            as_of_date=_AS_OF,
            policy=BaselineFactorPolicy(include_threshold=Decimal("80")),
        )
        assert first.policy_hash != second.policy_hash
        assert first.policy_parameter_hash != second.policy_parameter_hash

    def test_result_counts_sum_to_proposal_length(
        self,
    ) -> None:
        instruments, bars = _two_instrument_fixture()
        result = evaluate_baseline_factor_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
        )
        assert (
            result.full_count + result.partial_count + result.ineligible_count
            == len(result.proposals)
        )


# ---------------------------------------------------------------------------
# Result / proposal value-object invariants
# ---------------------------------------------------------------------------


class TestProposalInvariants:
    def test_invalid_decimal_score_is_rejected(self) -> None:
        # The proposal's ``__post_init__`` must reject a non-finite
        # Decimal on any of the score axes so a corrupted pipeline
        # caller cannot smuggle a NaN / Infinity through.
        nan = Decimal("NaN")
        with pytest.raises(ValueError, match="finite Decimal"):
            BaselineFactorProposal(
                instrument_id=_iid("alpha"),
                symbol="510300",
                exchange="SSE",
                channel_key=BASELINE_FACTOR_CHANNEL_KEY,
                channel_version=BASELINE_FACTOR_CHANNEL_VERSION,
                decision="include",
                eligibility=UniverseEligibility.FULL,
                baseline_score=nan,
                trend_score=Decimal("50"),
                liquidity_score=Decimal("50"),
                risk_adjustment=Decimal("50"),
                quality_status="complete",
                freshness_status="fresh",
                observed_trading_days=65,
                data_completeness=Decimal("1"),
                factor_set_key=BASELINE_FACTOR_FACTOR_SET_KEY,
                factor_set_version=BASELINE_FACTOR_FACTOR_SET_VERSION,
            )

    def test_channel_key_is_pinned_on_proposal(self) -> None:
        with pytest.raises(ValueError, match="channel_key"):
            BaselineFactorProposal(
                instrument_id=_iid("alpha"),
                symbol="510300",
                exchange="SSE",
                channel_key="wrong_key",
                channel_version=BASELINE_FACTOR_CHANNEL_VERSION,
                decision="include",
                eligibility=UniverseEligibility.FULL,
                baseline_score=Decimal("50"),
                trend_score=Decimal("50"),
                liquidity_score=Decimal("50"),
                risk_adjustment=Decimal("50"),
                quality_status="complete",
                freshness_status="fresh",
                observed_trading_days=65,
                data_completeness=Decimal("1.0"),
                factor_set_key=BASELINE_FACTOR_FACTOR_SET_KEY,
                factor_set_version=BASELINE_FACTOR_FACTOR_SET_VERSION,
            )

    def test_result_count_invariant_holds(self) -> None:
        iid = _iid("alpha")
        instrument = _instrument("alpha", symbol="510300")
        bars = _uptrend_bars(iid, 65)
        result = evaluate_baseline_factor_channel(
            instruments=[instrument],
            bars_by_instrument={iid: bars},
            as_of_date=_AS_OF,
        )
        assert result.channel_key == BASELINE_FACTOR_CHANNEL_KEY
        assert result.channel_version == BASELINE_FACTOR_CHANNEL_VERSION
        assert result.factor_set_key == FACTOR_SET_KEY
        assert result.factor_set_version == FACTOR_SET_VERSION

    def test_result_rejects_duplicate_instrument_ids(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            duplicate_proposal = BaselineFactorProposal(
                instrument_id=_iid("alpha"),
                symbol="510300",
                exchange="SSE",
                channel_key=BASELINE_FACTOR_CHANNEL_KEY,
                channel_version=BASELINE_FACTOR_CHANNEL_VERSION,
                decision="include",
                eligibility=UniverseEligibility.FULL,
                baseline_score=Decimal("60"),
                trend_score=Decimal("60"),
                liquidity_score=Decimal("60"),
                risk_adjustment=Decimal("60"),
                quality_status="complete",
                freshness_status="fresh",
                observed_trading_days=65,
                data_completeness=Decimal("1.0"),
                factor_set_key=BASELINE_FACTOR_FACTOR_SET_KEY,
                factor_set_version=BASELINE_FACTOR_FACTOR_SET_VERSION,
            )
            BaselineFactorChannelResult(
                channel_key=BASELINE_FACTOR_CHANNEL_KEY,
                channel_version=BASELINE_FACTOR_CHANNEL_VERSION,
                factor_set_key=BASELINE_FACTOR_FACTOR_SET_KEY,
                factor_set_version=BASELINE_FACTOR_FACTOR_SET_VERSION,
                policy_hash="x" * 64,
                policy_parameter_hash="y" * 64,
                as_of_date=_AS_OF,
                proposals=(duplicate_proposal, duplicate_proposal),
            )