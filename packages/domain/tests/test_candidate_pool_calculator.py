"""Tests for the PR-08 minimum candidate-pool calculator.

Covers:

- happy path (all instruments included, ranked by close * volume);
- each individual exclusion reason (``no_data``, ``suspended``,
  ``invalid_price``, ``low_volume``, ``low_amount``);
- mixed inputs where some instruments are included and others excluded;
- ranking correctness (descending by turnover, deterministic tiebreak);
- the strong consistency invariants from the task brief;
- boundary conditions (empty ``bars`` list, ``EligibilityCriteria``
  threshold validation, protocol conformance, type-rejection).

``invalid_price`` cannot be triggered through a real :class:`DailyBar`
because the model's ``__post_init__`` rejects NORMAL bars whose
``close`` is missing or non-positive; the test for that branch uses a
``MagicMock`` that quacks like a :class:`DailyBar` so the defensive
algorithm check is still exercised.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from invest_domain.candidate_pool.calculator import (
    DefaultMinimumCandidatePoolCalculator,
    MinimumCandidatePoolCalculator,
    _check_eligibility,
    _exclusion_reason,
    _latest_bar_per_instrument,
)
from invest_domain.candidate_pool.models import (
    CalculationContext,
    CandidatePoolItem,
    CandidatePoolPolicy,
    CandidatePoolResult,
    CandidatePoolSummary,
    EligibilityCriteria,
    ExclusionReason,
    LiquidityCriteria,
    PriceQualityCriteria,
    RiskCriteria,
    ScoreWeights,
    SelectionCriteria,
)
from invest_domain.candidate_pool.ports import CandidatePoolCalculator
from invest_domain.instruments.models import InstrumentId
from invest_domain.input_snapshot.models import InputSnapshot
from invest_domain.market_data.models import BarSource, DailyBar
from invest_domain.market_data.values import Adjust, TradingStatus

from .conftest import make_bar_source


_SNAPSHOT_DATE = date(2026, 7, 30)
_OBSERVED_AT = datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc)
_PROVIDER_KEY = "fixture_dev"


def _policy(
    *,
    min_volume: Decimal = Decimal("0"),
    min_amount: Decimal = Decimal("0"),
) -> CandidatePoolPolicy:
    return CandidatePoolPolicy(
        algorithm_key="etf_candidate_pool",
        algorithm_version="1.0.0",
        parameter_set_key="default",
        eligibility=EligibilityCriteria(
            min_listing_days=60,
            min_volume=min_volume,
            min_amount=min_amount,
        ),
        liquidity=LiquidityCriteria(lookback_days=20, min_valid_days=15),
        price_quality=PriceQualityCriteria(
            lookback_days=20,
            max_missing_ratio=Decimal("0.10"),
            max_zero_volume_days=3,
        ),
        risk=RiskCriteria(volatility_lookback_days=20, drawdown_lookback_days=60),
        selection=SelectionCriteria(max_candidates=100),
        score_weights=ScoreWeights(
            {
                "liquidity": Decimal("0.45"),
                "stability": Decimal("0.30"),
                "data_quality": Decimal("0.15"),
                "listing_maturity": Decimal("0.10"),
            }
        ),
    )


def _snapshot(instrument_ids: list[UUID]) -> InputSnapshot:
    return InputSnapshot.create(_SNAPSHOT_DATE, instrument_ids)


class _BarBuilder:
    """Build :class:`DailyBar` rows for calculator tests."""

    def __init__(self, source: BarSource) -> None:
        self._source = source

    def normal(
        self,
        *,
        instrument_id: InstrumentId,
        trade_date: date = _SNAPSHOT_DATE,
        close: str = "3.15",
        volume: str = "1000",
        amount: str = "3150000",
        open: str | None = None,
        high: str | None = None,
        low: str | None = None,
        prev_close: str | None = None,
    ) -> DailyBar:
        # When the caller does not pin OHLC we mirror the close across
        # open / high / low / prev_close so the OHLCV validator always
        # passes regardless of the chosen ``close``. Tests that need to
        # exercise a particular OHLC shape (e.g. low > close) override
        # the explicit fields.
        open_value = open if open is not None else close
        high_value = high if high is not None else close
        low_value = low if low is not None else close
        prev_close_value = prev_close if prev_close is not None else close
        return DailyBar.build(
            instrument_id=instrument_id,
            trade_date=trade_date,
            open=Decimal(open_value) if open_value is not None else None,
            high=Decimal(high_value) if high_value is not None else None,
            low=Decimal(low_value) if low_value is not None else None,
            close=Decimal(close) if close is not None else None,
            prev_close=Decimal(prev_close_value) if prev_close_value is not None else None,
            volume=Decimal(volume) if volume is not None else None,
            amount=Decimal(amount) if amount is not None else None,
            adjustment=Adjust.NONE,
            trading_status=TradingStatus.NORMAL,
            source=self._source,
            revision=1,
        )

    def suspended(
        self, *, instrument_id: InstrumentId, trade_date: date = _SNAPSHOT_DATE
    ) -> DailyBar:
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
            source=self._source,
            revision=1,
        )


@pytest.fixture
def bar_source() -> BarSource:
    return make_bar_source(provider_key=_PROVIDER_KEY, observed_at=_OBSERVED_AT)


@pytest.fixture
def builder(bar_source: BarSource) -> _BarBuilder:
    return _BarBuilder(bar_source)


@pytest.fixture
def calculator() -> DefaultMinimumCandidatePoolCalculator:
    return DefaultMinimumCandidatePoolCalculator()


@pytest.fixture
def instrument_ids() -> list[UUID]:
    return [uuid4(), uuid4(), uuid4()]


@pytest.fixture
def snapshot(instrument_ids: list[UUID]) -> InputSnapshot:
    return _snapshot(instrument_ids)


class TestProtocolConformance:
    def test_default_implements_protocol(
        self, calculator: DefaultMinimumCandidatePoolCalculator
    ) -> None:
        assert isinstance(calculator, MinimumCandidatePoolCalculator)

    def test_existing_protocol_is_separate(
        self, calculator: DefaultMinimumCandidatePoolCalculator
    ) -> None:
        # The PR-08 minimum Protocol deliberately differs from the M4
        # ``CandidatePoolCalculator`` Protocol (which takes histories
        # and a separate context). Confirm the runtime-checkable check
        # honours that boundary.
        assert not isinstance(calculator, CandidatePoolCalculator)


class TestHappyPath:
    def test_all_included_with_ranks(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
        instrument_ids: list[UUID],
    ) -> None:
        snapshot = _snapshot(instrument_ids)
        bars = [
            builder.normal(
                instrument_id=InstrumentId(uid),
                close="3.15",
                volume="1000",
                amount="3150000",
            )
            for uid in instrument_ids
        ]
        result = calculator.calculate(snapshot, bars, _policy())

        assert isinstance(result, CandidatePoolResult)
        assert len(result.items) == len(instrument_ids)
        assert result.summary.included_count == len(instrument_ids)
        assert result.summary.excluded_count == 0
        ranks = [item.rank for item in result.included_items]
        assert ranks == list(range(1, len(instrument_ids) + 1))
        for item in result.included_items:
            assert item.exclusion_reasons == ()


class TestExclusionReasons:
    def test_no_data_when_bar_missing(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        instrument_ids: list[UUID],
    ) -> None:
        snapshot = _snapshot(instrument_ids[:1])
        result = calculator.calculate(snapshot, [], _policy())

        assert len(result.items) == 1
        assert result.items[0].included is False
        assert result.items[0].exclusion_reasons[0].code == "no_data"
        assert result.summary.excluded_count == 1
        assert result.summary.included_count == 0

    def test_suspended_excludes_with_suspended_reason(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
        instrument_ids: list[UUID],
    ) -> None:
        uid = instrument_ids[0]
        snapshot = _snapshot([uid])
        bars = [builder.suspended(instrument_id=InstrumentId(uid))]
        result = calculator.calculate(snapshot, bars, _policy())

        item = result.items[0]
        assert item.included is False
        assert item.exclusion_reasons[0].code == "suspended"

    def test_invalid_price_check_is_exercised(self) -> None:
        # DailyBar.__post_init__ rejects NORMAL bars with close=None or
        # <= 0, so we drive the defensive check with a mock bar.
        mock_bar = MagicMock(spec=DailyBar)
        mock_bar.trading_status = TradingStatus.NORMAL
        mock_bar.close = None
        mock_bar.volume = Decimal("1000")
        mock_bar.amount = Decimal("1000")

        reason = _check_eligibility(
            mock_bar, min_volume=Decimal("0"), min_amount=Decimal("0")
        )

        assert reason is not None
        assert reason.code == "invalid_price"
        assert "close" in reason.message.lower()

    def test_invalid_price_check_fires_for_zero_close(self) -> None:
        mock_bar = MagicMock(spec=DailyBar)
        mock_bar.trading_status = TradingStatus.NORMAL
        mock_bar.close = Decimal("0")
        mock_bar.volume = Decimal("1000")
        mock_bar.amount = Decimal("1000")

        reason = _check_eligibility(
            mock_bar, min_volume=Decimal("0"), min_amount=Decimal("0")
        )
        assert reason is not None
        assert reason.code == "invalid_price"

    def test_low_volume_exclusion(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
        instrument_ids: list[UUID],
    ) -> None:
        uid = instrument_ids[0]
        snapshot = _snapshot([uid])
        bars = [
            builder.normal(
                instrument_id=InstrumentId(uid),
                volume="100",
                amount="10000",
            )
        ]
        policy = _policy(min_volume=Decimal("1000"), min_amount=Decimal("0"))
        result = calculator.calculate(snapshot, bars, policy)

        item = result.items[0]
        assert item.included is False
        assert item.exclusion_reasons[0].code == "low_volume"

    def test_low_amount_exclusion(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
        instrument_ids: list[UUID],
    ) -> None:
        uid = instrument_ids[0]
        snapshot = _snapshot([uid])
        bars = [
            builder.normal(
                instrument_id=InstrumentId(uid),
                volume="10000",
                amount="100",
            )
        ]
        policy = _policy(min_volume=Decimal("0"), min_amount=Decimal("10000"))
        result = calculator.calculate(snapshot, bars, policy)

        item = result.items[0]
        assert item.included is False
        assert item.exclusion_reasons[0].code == "low_amount"


class TestMixedUniverse:
    def test_mix_of_included_and_excluded(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
    ) -> None:
        ids = [uuid4() for _ in range(4)]
        snapshot = _snapshot(ids)

        good_close_volume_a = builder.normal(
            instrument_id=InstrumentId(ids[0]),
            close="10.00",
            volume="1000",
            amount="10000000",
        )
        good_close_volume_b = builder.normal(
            instrument_id=InstrumentId(ids[1]),
            close="5.00",
            volume="2000",
            amount="10000000",
        )
        suspended = builder.suspended(instrument_id=InstrumentId(ids[2]))
        # ids[3] has no bar at all -> no_data
        bars = [good_close_volume_a, good_close_volume_b, suspended]
        result = calculator.calculate(snapshot, bars, _policy())

        included = result.included_items
        excluded = result.excluded_items
        assert len(included) == 2
        assert len(excluded) == 2

        # Turnover: A = 10_000, B = 10_000 -> tie broken by UUID bytes.
        # A < B in UUID-bytes order for these random ids, so A ranks #1.
        # Tiebreak check: regardless of order, both ranks must be in 1..2.
        assert sorted(item.rank for item in included) == [1, 2]

        codes = {item.exclusion_reasons[0].code for item in excluded}
        assert codes == {"suspended", "no_data"}


class TestRanking:
    def test_ranks_descend_by_turnover(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
    ) -> None:
        ids = [uuid4() for _ in range(3)]
        snapshot = _snapshot(ids)
        bars = [
            builder.normal(
                instrument_id=InstrumentId(ids[0]),
                close="10.00",
                volume="100",
                amount="1000000",
            ),
            builder.normal(
                instrument_id=InstrumentId(ids[1]),
                close="5.00",
                volume="1000",
                amount="5000000",
            ),
            builder.normal(
                instrument_id=InstrumentId(ids[2]),
                close="2.00",
                volume="5000",
                amount="10000000",
            ),
        ]
        result = calculator.calculate(snapshot, bars, _policy())

        # Turnovers: ids[0]=1000, ids[1]=5000, ids[2]=10000.
        ranks = sorted(item.rank for item in result.included_items)
        assert ranks == [1, 2, 3]
        rank_by_uuid = {item.instrument_id.value: item.rank for item in result.included_items}
        assert rank_by_uuid[ids[2]] == 1
        assert rank_by_uuid[ids[1]] == 2
        assert rank_by_uuid[ids[0]] == 3

    def test_total_score_equals_turnover(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
    ) -> None:
        uid = uuid4()
        snapshot = _snapshot([uid])
        bars = [
            builder.normal(
                instrument_id=InstrumentId(uid),
                close="3.50",
                volume="2000",
                amount="7000000",
            )
        ]
        result = calculator.calculate(snapshot, bars, _policy())
        item = result.included_items[0]
        assert item.total_score == Decimal("3.50") * Decimal("2000")
        assert item.metrics["turnover"] == Decimal("3.50") * Decimal("2000")

    def test_ties_are_broken_by_uuid(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
    ) -> None:
        ids = sorted([uuid4() for _ in range(3)])
        snapshot = _snapshot(ids)
        bars = [
            builder.normal(
                instrument_id=InstrumentId(uid),
                close="1.00",
                volume="1000",
                amount="1000000",
            )
            for uid in ids
        ]
        result = calculator.calculate(snapshot, bars, _policy())
        ranks = [item.rank for item in result.included_items]
        assert ranks == [1, 2, 3]
        rank_by_uuid = {item.instrument_id.value: item.rank for item in result.included_items}
        # Lower UUID-bytes sorts first -> rank 1.
        assert rank_by_uuid[ids[0]] == 1
        assert rank_by_uuid[ids[1]] == 2
        assert rank_by_uuid[ids[2]] == 3

    def test_rank_is_deterministic_across_calls(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
    ) -> None:
        ids = [uuid4() for _ in range(3)]
        snapshot = _snapshot(ids)
        bars = [
            builder.normal(
                instrument_id=InstrumentId(uid),
                close="2.00",
                volume="500",
                amount="1000000",
            )
            for uid in ids
        ]
        first = calculator.calculate(snapshot, bars, _policy())
        second = calculator.calculate(snapshot, bars, _policy())
        assert first.summary.input_count == second.summary.input_count
        first_ranks = [item.rank for item in first.included_items]
        second_ranks = [item.rank for item in second.included_items]
        assert first_ranks == second_ranks


class TestConsistencyInvariants:
    def test_input_count_equals_included_plus_excluded(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
    ) -> None:
        ids = [uuid4() for _ in range(4)]
        snapshot = _snapshot(ids)
        bars = [
            builder.normal(instrument_id=InstrumentId(ids[0])),
            builder.normal(instrument_id=InstrumentId(ids[1]), volume="1", amount="1"),
            builder.suspended(instrument_id=InstrumentId(ids[2])),
        ]
        result = calculator.calculate(
            snapshot, bars, _policy(min_volume=Decimal("1000"), min_amount=Decimal("0"))
        )

        assert result.summary.input_count == 4
        assert (
            result.summary.included_count + result.summary.excluded_count
            == result.summary.input_count
        )
        assert len(result.items) == result.summary.input_count
        # Every instrument_id appears exactly once.
        seen = [item.instrument_id.value for item in result.items]
        assert sorted(seen) == sorted(ids)
        assert len(set(seen)) == len(ids)

    def test_included_ranks_are_unique_and_contiguous(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
    ) -> None:
        ids = [uuid4() for _ in range(5)]
        snapshot = _snapshot(ids)
        bars = [
            builder.normal(
                instrument_id=InstrumentId(uid),
                close="1.00",
                volume=str(100 * (idx + 1)),
                amount="1000000",
            )
            for idx, uid in enumerate(ids[:3])
        ]
        result = calculator.calculate(snapshot, bars, _policy())
        ranks = [item.rank for item in result.included_items]
        # ``included_items`` is filtered from ``items`` in snapshot order,
        # so we sort explicitly before comparing.
        sorted_ranks = sorted(ranks)
        assert len(set(sorted_ranks)) == len(sorted_ranks)
        assert sorted_ranks == list(range(1, len(sorted_ranks) + 1))

    def test_excluded_items_carry_a_reason(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
        instrument_ids: list[UUID],
    ) -> None:
        snapshot = _snapshot(instrument_ids)
        bars = [builder.suspended(instrument_id=InstrumentId(instrument_ids[0]))]
        result = calculator.calculate(snapshot, bars, _policy())
        for item in result.excluded_items:
            assert item.exclusion_reasons, "excluded items must carry a reason"
            assert all(reason.code and reason.message for reason in item.exclusion_reasons)

    def test_summary_counts_match_items(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
    ) -> None:
        ids = [uuid4() for _ in range(3)]
        snapshot = _snapshot(ids)
        bars = [
            builder.normal(instrument_id=InstrumentId(uid)) for uid in ids[:2]
        ]
        result = calculator.calculate(snapshot, bars, _policy())
        actual_included = sum(1 for item in result.items if item.included)
        actual_excluded = sum(1 for item in result.items if not item.included)
        assert result.summary.included_count == actual_included
        assert result.summary.excluded_count == actual_excluded


class TestBoundaryConditions:
    def test_empty_bars_excludes_all_with_no_data(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        instrument_ids: list[UUID],
    ) -> None:
        snapshot = _snapshot(instrument_ids)
        result = calculator.calculate(snapshot, [], _policy())
        assert result.summary.included_count == 0
        assert result.summary.excluded_count == len(instrument_ids)
        assert all(
            item.exclusion_reasons[0].code == "no_data"
            for item in result.excluded_items
        )

    def test_latest_bar_is_picked_when_multiple_present(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
        instrument_ids: list[UUID],
    ) -> None:
        uid = instrument_ids[0]
        snapshot = _snapshot([uid])
        bars = [
            builder.normal(
                instrument_id=InstrumentId(uid),
                trade_date=date(2026, 7, 29),
                close="1.00",
                volume="1",
                amount="1",
            ),
            builder.normal(
                instrument_id=InstrumentId(uid),
                trade_date=date(2026, 7, 30),
                close="2.00",
                volume="2000",
                amount="4000000",
            ),
            builder.normal(
                instrument_id=InstrumentId(uid),
                trade_date=date(2026, 7, 28),
                close="9.99",
                volume="9999",
                amount="99999999",
            ),
        ]
        result = calculator.calculate(snapshot, bars, _policy())
        item = result.included_items[0]
        # Latest bar is trade_date=2026-07-30 -> close=2.00, volume=2000.
        assert item.total_score == Decimal("2.00") * Decimal("2000")
        assert item.metrics["close"] == Decimal("2.00")

    def test_extra_bars_for_unknown_instruments_are_ignored(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        builder: _BarBuilder,
        instrument_ids: list[UUID],
    ) -> None:
        snapshot = _snapshot(instrument_ids[:1])
        bars = [
            builder.normal(instrument_id=InstrumentId(instrument_ids[0])),
            builder.normal(instrument_id=InstrumentId(uuid4())),  # not in snapshot
        ]
        result = calculator.calculate(snapshot, bars, _policy())
        assert result.summary.included_count == 1
        assert result.summary.excluded_count == 0
        assert result.summary.input_count == 1


class TestInputValidation:
    def test_rejects_non_input_snapshot(
        self, calculator: DefaultMinimumCandidatePoolCalculator
    ) -> None:
        snapshot = _snapshot([uuid4()])
        with pytest.raises(TypeError, match="snapshot"):
            calculator.calculate(  # type: ignore[arg-type]
                "not-a-snapshot",  # type: ignore[arg-type]
                [],
                _policy(),
            )

    def test_rejects_non_policy(
        self,
        calculator: DefaultMinimumCandidatePoolCalculator,
        instrument_ids: list[UUID],
    ) -> None:
        snapshot = _snapshot(instrument_ids)
        with pytest.raises(TypeError, match="policy"):
            calculator.calculate(snapshot, [], "not-a-policy")  # type: ignore[arg-type]

    def test_negative_min_volume_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="min_volume"):
            EligibilityCriteria(min_volume=Decimal("-1"))

    def test_negative_min_amount_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="min_amount"):
            EligibilityCriteria(min_amount=Decimal("-1"))

    def test_non_finite_min_volume_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="min_volume"):
            EligibilityCriteria(min_volume=Decimal("Infinity"))

    def test_non_decimal_min_volume_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="min_volume"):
            EligibilityCriteria(min_volume=1)  # type: ignore[arg-type]


class TestInternalHelpers:
    def test_exclusion_reason_messages_are_stable(self) -> None:
        # The codes / messages are part of the audit contract; a typo
        # here would silently break downstream tooling that groups on
        # ``code``.
        for code in ("no_data", "suspended", "invalid_price", "low_volume", "low_amount"):
            reason = _exclusion_reason(code)
            assert reason.code == code
            assert reason.message

    def test_latest_bar_per_instrument_returns_max_trade_date(
        self, builder: _BarBuilder
    ) -> None:
        iid = InstrumentId.generate()
        old = builder.normal(
            instrument_id=iid,
            trade_date=date(2026, 1, 1),
            close="1.00",
            volume="1",
            amount="1",
        )
        new = builder.normal(
            instrument_id=iid,
            trade_date=date(2026, 12, 31),
            close="9.00",
            volume="9",
            amount="81",
        )
        latest = _latest_bar_per_instrument([old, new])
        assert latest[iid] is new

    def test_latest_bar_per_instrument_handles_empty_input(self) -> None:
        assert _latest_bar_per_instrument([]) == {}