"""Unit tests for :mod:`invest_pipeline.candidate_routing.shadow`.

Covers every behaviour documented in the shadow MVP contract:

* FULL / PARTIAL / INELIGIBLE routing into snapshot / watch_only /
  dropped; INELIGIBLE never reaches the calculator or watch_only.
* No-FULL behaviour: ``snapshot`` and ``candidate_pool_result`` are
  both ``None`` (no invented empty snapshot).
* Deterministic universe ordering and content hash for equal logical
  inputs with pinned factories.
* Stale and non-ETF / inactive instruments stay INELIGIBLE and never
  reach the calculator.
* Calculator delegation: the default calculator is wired and a stub
  calculator can be injected.
* Pure call surface: the function never opens a session, never calls
  a provider, never reads a file and never imports Dagster / SQLAlchemy
  / provider modules.
"""

from __future__ import annotations

import inspect
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from invest_domain.candidate_pool.calculator import (
    DefaultMinimumCandidatePoolCalculator,
    MinimumCandidatePoolCalculator,
)
from invest_domain.candidate_pool.models import (
    CandidatePoolPolicy,
    CandidatePoolResult,
    EligibilityCriteria,
    LiquidityCriteria,
    PriceQualityCriteria,
    RiskCriteria,
    ScoreWeights,
    SelectionCriteria,
)
from invest_domain.candidate_pool.universe import UniverseEligibility
from invest_domain.input_snapshot.models import InputSnapshot
from invest_domain.instruments.models import Instrument, InstrumentId
from invest_domain.market_data.models import BarSource, DailyBar
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_pipeline.candidate_routing.shadow import (
    DEFAULT_MAX_STALE_DAYS,
    DEFAULT_MINIMUM_FULL_HISTORY_DAYS,
    DEFAULT_MINIMUM_PARTIAL_HISTORY_DAYS,
    InvalidUniverseThresholdsError,
    route_candidate_pool_shadow,
)

_AS_OF = date(2026, 7, 30)
_SNAPSHOT_DATE = _AS_OF
_OBSERVED_AT = datetime(2026, 7, 30, 8, 0, 0, tzinfo=UTC)
_BATCH_ID = UUID("00000000-0000-0000-0000-000000000777")
_PROVIDER_KEY = "shadow_test"


def _iid(label: str) -> InstrumentId:
    """Return a deterministic :class:`InstrumentId` derived from ``label``.

    Uses a stable per-label UUID so tests stay readable; the shadow
    MVP is required to be order-independent, so deterministic IDs
    make intent obvious in failure messages without hiding bugs.
    """

    digest = UUID(int=int.from_bytes(label.encode("utf-8").ljust(16, b"\x00")[:16], "big"))
    return InstrumentId(digest)


def _instrument(
    label: str,
    *,
    symbol: str | None = None,
    exchange: str = "SSE",
    kind: Any = None,
    active: bool = True,
) -> Instrument:
    """Build an ETF :class:`Instrument` with deterministic ``instrument_id``."""

    from invest_domain.instruments.models import InstrumentType

    return Instrument(
        symbol=symbol or label,
        name=f"{label} ETF",
        exchange=exchange,
        instrument_type=kind if kind is not None else InstrumentType.ETF,
        is_active=active,
        instrument_id=_iid(label),
    )


def _bar_source() -> BarSource:
    return BarSource(
        provider_key=_PROVIDER_KEY,
        source_batch_id=_BATCH_ID,
        observed_at=_OBSERVED_AT,
    )


def _bar(
    instrument_id: InstrumentId,
    trade_date: date,
    *,
    close: str = "3.15",
    volume: str = "100000",
    amount: str = "315000",
    status: TradingStatus = TradingStatus.NORMAL,
) -> DailyBar:
    """Build a :class:`DailyBar` that satisfies the domain invariants."""

    if status is TradingStatus.NORMAL:
        return DailyBar.build(
            instrument_id=instrument_id,
            trade_date=trade_date,
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            close=Decimal(close),
            prev_close=Decimal(close),
            volume=Decimal(volume),
            amount=Decimal(amount),
            adjustment=Adjust.NONE,
            trading_status=TradingStatus.NORMAL,
            source=_bar_source(),
            revision=1,
        )
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


def _bar_series(label: str, count: int) -> list[DailyBar]:
    """Return ``count`` consecutive NORMAL bars ending on ``_AS_OF``."""

    iid = _iid(label)
    return [
        _bar(iid, _AS_OF - timedelta(days=offset))
        for offset in range(count - 1, -1, -1)
    ]


def _policy() -> CandidatePoolPolicy:
    """Build a minimal :class:`CandidatePoolPolicy` for the minimum calculator."""

    return CandidatePoolPolicy(
        algorithm_key="shadow_mvp",
        algorithm_version="1",
        parameter_set_key="shadow_default_v1",
        eligibility=EligibilityCriteria(
            min_listing_days=0,
            min_volume=Decimal("0"),
            min_amount=Decimal("0"),
        ),
        liquidity=LiquidityCriteria(lookback_days=1, min_valid_days=1),
        price_quality=PriceQualityCriteria(
            lookback_days=1,
            max_missing_ratio=Decimal("0"),
            max_zero_volume_days=0,
        ),
        risk=RiskCriteria(volatility_lookback_days=1, drawdown_lookback_days=1),
        selection=SelectionCriteria(max_candidates=100),
        score_weights=ScoreWeights(
            weights={
                "liquidity": Decimal("0"),
                "stability": Decimal("0"),
                "data_quality": Decimal("0"),
                "listing_maturity": Decimal("0"),
            }
        ),
    )


def _id_factory() -> UUID:
    return UUID("11111111-1111-1111-1111-111111111111")


def _now_factory() -> datetime:
    return datetime(2026, 7, 30, 10, 0, 0, tzinfo=UTC)


def _build_mixed_inputs() -> tuple[list[Instrument], dict[InstrumentId, list[DailyBar]]]:
    """Three ETF instruments exercising the FULL / PARTIAL / INELIGIBLE branches.

    The function pins ``alpha`` to FULL (60 bars), ``beta`` to PARTIAL
    (30 bars, well above 20 but below 60) and ``gamma`` to INELIGIBLE
    (no bars at all, so no valid price). The thresholds default to
    60 / 20 / 3 so the boundary values are stable.
    """

    alpha = _instrument("alpha", symbol="510300")
    beta = _instrument("beta", symbol="510500")
    gamma = _instrument("gamma", symbol="159915")

    bars_by_instrument: dict[InstrumentId, list[DailyBar]] = {
        _iid("alpha"): _bar_series("alpha", 60),
        _iid("beta"): _bar_series("beta", 30),
    }
    return [alpha, beta, gamma], bars_by_instrument


class TestUniverseRouting:
    def test_full_partial_ineligible_are_routed_to_their_buckets(self) -> None:
        instruments, bars = _build_mixed_inputs()
        result = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        eligibilities = {
            candidate.instrument_id: candidate.eligibility for candidate in result.universe
        }
        assert eligibilities[_iid("alpha")] is UniverseEligibility.FULL
        assert eligibilities[_iid("beta")] is UniverseEligibility.PARTIAL
        assert eligibilities[_iid("gamma")] is UniverseEligibility.INELIGIBLE

        assert result.full_count == 1
        assert result.partial_count == 1
        assert result.ineligible_count == 1
        assert result.watch_only == (_iid("beta"),)
        assert result.snapshot is not None
        assert result.snapshot.row_count == 1
        assert result.candidate_pool_result is not None

    def test_universe_keeps_ineligible_away_from_calculator_and_watch_only(self) -> None:
        instruments, bars = _build_mixed_inputs()
        result = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert _iid("gamma") not in result.watch_only
        if result.candidate_pool_result is not None:
            calculator_ids = {item.instrument_id for item in result.candidate_pool_result.items}
            assert _iid("gamma") not in calculator_ids
            assert _iid("beta") not in calculator_ids

    def test_universe_is_ordered_by_instrument_id_string(self) -> None:
        instruments, bars = _build_mixed_inputs()
        result = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        ordered = [str(candidate.instrument_id) for candidate in result.universe]
        assert ordered == sorted(ordered)

    def test_input_sequence_order_does_not_change_routing(self) -> None:
        instruments, bars = _build_mixed_inputs()
        first = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )
        reversed_instruments = list(reversed(instruments))
        second = route_candidate_pool_shadow(
            instruments=reversed_instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert first.watch_only == second.watch_only
        assert first.universe == second.universe
        if first.snapshot is None or second.snapshot is None:
            assert first.snapshot == second.snapshot
        else:
            assert first.snapshot.instrument_ids == second.snapshot.instrument_ids
            assert first.snapshot.content_hash == second.snapshot.content_hash


class TestNoFullCandidates:
    def test_only_ineligible_returns_no_snapshot_and_no_result(self) -> None:
        gamma = _instrument("gamma", symbol="159915")
        result = route_candidate_pool_shadow(
            instruments=[gamma],
            bars_by_instrument={},
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert result.full_count == 0
        assert result.partial_count == 0
        assert result.ineligible_count == 1
        assert len(result.universe) == 1
        assert result.watch_only == ()
        assert result.snapshot is None
        assert result.candidate_pool_result is None

    def test_only_partial_returns_no_snapshot_but_watch_only(self) -> None:
        beta = _instrument("beta", symbol="510500")
        result = route_candidate_pool_shadow(
            instruments=[beta],
            bars_by_instrument={_iid("beta"): _bar_series("beta", 30)},
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert result.full_count == 0
        assert result.partial_count == 1
        assert result.ineligible_count == 0
        assert result.watch_only == (_iid("beta"),)
        assert result.snapshot is None
        assert result.candidate_pool_result is None


class TestDeterminism:
    def test_pinned_factories_yield_equal_content_hashes(self) -> None:
        instruments, bars = _build_mixed_inputs()
        first = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )
        second = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert first.content_hash == second.content_hash
        assert first.universe == second.universe
        assert first.watch_only == second.watch_only

    def test_content_hash_changes_when_universe_changes(self) -> None:
        instruments, bars = _build_mixed_inputs()
        first = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        alpha, beta, gamma = instruments
        without_gamma = [alpha, beta]
        second = route_candidate_pool_shadow(
            instruments=without_gamma,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert first.content_hash != second.content_hash

    def test_content_hash_changes_when_policy_changes(self) -> None:
        instruments, bars = _build_mixed_inputs()
        first = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        policy = _policy()
        tighter = CandidatePoolPolicy(
            algorithm_key=policy.algorithm_key,
            algorithm_version=policy.algorithm_version,
            parameter_set_key=policy.parameter_set_key,
            eligibility=EligibilityCriteria(
                min_listing_days=policy.eligibility.min_listing_days,
                min_volume=Decimal("0"),
                min_amount=Decimal("1"),
            ),
            liquidity=policy.liquidity,
            price_quality=policy.price_quality,
            risk=policy.risk,
            selection=policy.selection,
            score_weights=policy.score_weights,
        )
        second = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=tighter,
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert first.content_hash != second.content_hash

    def test_result_is_frozen(self) -> None:
        instruments, bars = _build_mixed_inputs()
        result = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        with pytest.raises((AttributeError, TypeError)):
            result.watch_only = ()  # type: ignore[misc]


class TestStaleAndIneligibleExclusion:
    def test_stale_instrument_is_ineligible_and_excluded(self) -> None:
        alpha = _instrument("alpha", symbol="510300")
        iid = _iid("alpha")
        stale_bar = _bar(iid, _AS_OF - timedelta(days=10))
        result = route_candidate_pool_shadow(
            instruments=[alpha],
            bars_by_instrument={iid: [stale_bar]},
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
            max_stale_days=DEFAULT_MAX_STALE_DAYS,
        )

        assert result.universe[0].eligibility is UniverseEligibility.INELIGIBLE
        assert "stale" in result.universe[0].reasons
        assert result.snapshot is None
        assert result.candidate_pool_result is None

    def test_non_etf_instrument_is_ineligible_and_excluded(self) -> None:
        from invest_domain.instruments.models import InstrumentType

        stock = _instrument("stock", symbol="600000", kind=InstrumentType.STOCK)
        result = route_candidate_pool_shadow(
            instruments=[stock],
            bars_by_instrument={},
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert result.universe[0].eligibility is UniverseEligibility.INELIGIBLE
        assert "not_etf" in result.universe[0].reasons
        assert result.snapshot is None
        assert result.candidate_pool_result is None

    def test_inactive_instrument_is_ineligible_and_excluded(self) -> None:
        inactive = _instrument("inactive", symbol="510000", active=False)
        result = route_candidate_pool_shadow(
            instruments=[inactive],
            bars_by_instrument={},
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert result.universe[0].eligibility is UniverseEligibility.INELIGIBLE
        assert "inactive" in result.universe[0].reasons
        assert result.snapshot is None
        assert result.candidate_pool_result is None


class TestCalculatorDelegation:
    def test_default_calculator_is_used_when_not_injected(self) -> None:
        instruments, bars = _build_mixed_inputs()
        result = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert result.candidate_pool_result is not None
        assert result.candidate_pool_result.policy is not None

    def test_injected_calculator_receives_full_snapshot_and_bars(self) -> None:
        instruments, bars = _build_mixed_inputs()
        captured: dict[str, Any] = {}

        class _RecordingCalculator:
            def calculate(
                self,
                snapshot: InputSnapshot,
                calculator_bars: list[DailyBar],
                policy: CandidatePoolPolicy,
            ) -> CandidatePoolResult:
                captured["snapshot"] = snapshot
                captured["bars"] = list(calculator_bars)
                captured["policy"] = policy
                return DefaultMinimumCandidatePoolCalculator().calculate(
                    snapshot, calculator_bars, policy
                )

        route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
            calculator=_RecordingCalculator(),
        )

        assert isinstance(captured["snapshot"], InputSnapshot)
        assert captured["snapshot"].row_count == 1
        assert tuple(captured["snapshot"].instrument_ids) == (_iid("alpha").value,)
        assert len(captured["bars"]) == 1
        assert all(isinstance(bar, DailyBar) for bar in captured["bars"])
        assert isinstance(captured["policy"], CandidatePoolPolicy)

    def test_calculator_is_a_minimum_protocol_implementation(self) -> None:
        instruments, bars = _build_mixed_inputs()
        calculator = DefaultMinimumCandidatePoolCalculator()
        result = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
            calculator=calculator,
        )

        assert result.candidate_pool_result is not None
        assert isinstance(calculator, MinimumCandidatePoolCalculator)


class TestPureCallSurface:
    def test_function_signature_exposes_required_keyword_arguments(self) -> None:
        signature = inspect.signature(route_candidate_pool_shadow)
        parameters = signature.parameters
        for name in (
            "instruments",
            "bars_by_instrument",
            "as_of_date",
            "policy",
            "id_factory",
            "now_factory",
            "calculator",
        ):
            assert name in parameters, f"missing required kwarg {name!r}"
        assert parameters["minimum_full_history_days"].default == DEFAULT_MINIMUM_FULL_HISTORY_DAYS
        assert (
            parameters["minimum_partial_history_days"].default
            == DEFAULT_MINIMUM_PARTIAL_HISTORY_DAYS
        )
        assert parameters["max_stale_days"].default == DEFAULT_MAX_STALE_DAYS

    def test_function_does_not_import_io_modules(self) -> None:
        import ast

        forbidden = {
            "invest_pipeline.candidate_pool_service",
            "invest_pipeline.assets",
            "invest_storage",
            "invest_pipeline.provider_factory",
            "invest_pipeline.provider_routing",
            "sqlalchemy",
            "dagster",
        }

        shadow_module = sys.modules.get("invest_pipeline.candidate_routing.shadow")
        assert shadow_module is not None
        source_path = inspect.getsourcefile(shadow_module)
        assert source_path is not None
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()

        tree = ast.parse(source)
        direct_imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    direct_imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                direct_imports.add(node.module)

        leaked = sorted(
            name
            for name in direct_imports
            for needle in forbidden
            if name == needle or name.startswith(f"{needle}.")
        )
        assert not leaked, (
            "invest_pipeline.candidate_routing.shadow must not directly import "
            f"forbidden I/O modules; found: {leaked!r}"
        )

    def test_function_does_not_open_files_or_sessions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[str] = []

        def _explode_open(*_args: Any, **_kwargs: Any) -> Any:
            opened.append("open")
            raise AssertionError("route_candidate_pool_shadow must not open files")

        monkeypatch.setattr("builtins.open", _explode_open, raising=False)
        route_candidate_pool_shadow(
            instruments=[],
            bars_by_instrument={},
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )
        assert opened == []

    def test_function_does_not_call_calculator_when_no_full_candidate(self) -> None:
        called = {"count": 0}

        class _CountingCalculator:
            def calculate(
                self,
                snapshot: InputSnapshot,
                bars: list[DailyBar],
                policy: CandidatePoolPolicy,
            ) -> CandidatePoolResult:
                called["count"] += 1
                raise AssertionError(
                    "calculator must not be invoked when no FULL candidate survives"
                )

        gamma = _instrument("gamma", symbol="159915")
        route_candidate_pool_shadow(
            instruments=[gamma],
            bars_by_instrument={},
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
            calculator=_CountingCalculator(),
        )

        assert called["count"] == 0


class TestThresholdValidation:
    def test_partial_threshold_must_be_at_least_one(self) -> None:
        with pytest.raises(InvalidUniverseThresholdsError):
            route_candidate_pool_shadow(
                instruments=[],
                bars_by_instrument={},
                as_of_date=_AS_OF,
                policy=_policy(),
                minimum_partial_history_days=0,
            )

    def test_full_threshold_must_be_at_least_partial(self) -> None:
        with pytest.raises(InvalidUniverseThresholdsError):
            route_candidate_pool_shadow(
                instruments=[],
                bars_by_instrument={},
                as_of_date=_AS_OF,
                policy=_policy(),
                minimum_full_history_days=10,
                minimum_partial_history_days=20,
            )

    def test_max_stale_days_must_be_non_negative(self) -> None:
        with pytest.raises(InvalidUniverseThresholdsError):
            route_candidate_pool_shadow(
                instruments=[],
                bars_by_instrument={},
                as_of_date=_AS_OF,
                policy=_policy(),
                max_stale_days=-1,
            )


class TestResultInvariants:
    def test_result_full_partial_ineligible_counts_sum_to_universe_length(self) -> None:
        instruments, bars = _build_mixed_inputs()
        result = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert result.full_count + result.partial_count + result.ineligible_count == len(
            result.universe
        )

    def test_watch_only_length_matches_partial_count(self) -> None:
        instruments, bars = _build_mixed_inputs()
        result = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert len(result.watch_only) == result.partial_count

    def test_snapshot_row_count_matches_full_count(self) -> None:
        instruments, bars = _build_mixed_inputs()
        result = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert result.snapshot is not None
        assert result.snapshot.row_count == result.full_count

    def test_snapshot_and_result_are_paired(self) -> None:
        instruments, bars = _build_mixed_inputs()
        result = route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )

        assert (result.snapshot is None) == (result.candidate_pool_result is None)


class TestInputImmutability:
    def test_input_instruments_sequence_is_not_mutated(self) -> None:
        instruments, bars = _build_mixed_inputs()
        snapshot = list(instruments)
        route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )
        assert list(instruments) == snapshot

    def test_input_bars_mapping_is_not_mutated(self) -> None:
        instruments, bars = _build_mixed_inputs()
        snapshot = {key: list(value) for key, value in bars.items()}
        route_candidate_pool_shadow(
            instruments=instruments,
            bars_by_instrument=bars,
            as_of_date=_AS_OF,
            policy=_policy(),
            id_factory=_id_factory,
            now_factory=_now_factory,
        )
        for key, value in bars.items():
            assert list(value) == snapshot[key]
