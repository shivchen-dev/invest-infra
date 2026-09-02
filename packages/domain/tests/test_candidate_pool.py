"""Tests for the ``candidate_pool`` bounded context."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from invest_domain.candidate_pool.fingerprint import compute_market_data_fingerprint
from invest_domain.candidate_pool.models import (
    LEGACY_MARKET_DATA_FINGERPRINT,
    CalculationContext,
    CandidatePoolItem,
    CandidatePoolPolicy,
    CandidatePoolResult,
    CandidatePoolRun,
    CandidatePoolStatus,
    CandidatePoolSummary,
    EligibilityCriteria,
    ExclusionReason,
    LiquidityCriteria,
    PriceQualityCriteria,
    RiskCriteria,
    RuleOutcome,
    RuleSeverity,
    ScoreWeights,
    SelectionCriteria,
)
from invest_domain.instruments.models import InstrumentId
from invest_domain.market_data.models import BarSource, DailyBar
from invest_domain.market_data.values import Adjust, TradingStatus

from .conftest import make_bar_source


def _default_policy() -> CandidatePoolPolicy:
    return CandidatePoolPolicy(
        algorithm_key="etf_candidate_pool",
        algorithm_version="1.0.0",
        parameter_set_key="default",
        eligibility=EligibilityCriteria(min_listing_days=60),
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


class TestScoreWeights:
    def test_valid_weights_are_accepted(self) -> None:
        sw = ScoreWeights(
            {
                "liquidity": Decimal("0.45"),
                "stability": Decimal("0.30"),
                "data_quality": Decimal("0.15"),
                "listing_maturity": Decimal("0.10"),
            }
        )
        assert sw.weights["liquidity"] == Decimal("0.45")

    def test_missing_required_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="missing required keys"):
            ScoreWeights({"liquidity": Decimal("0.5")})

    def test_unknown_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown keys"):
            ScoreWeights(
                {
                    "liquidity": Decimal("0.5"),
                    "stability": Decimal("0.3"),
                    "data_quality": Decimal("0.1"),
                    "listing_maturity": Decimal("0.1"),
                    "extra": Decimal("0.1"),
                }
            )

    def test_negative_weight_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            ScoreWeights(
                {
                    "liquidity": Decimal("-0.1"),
                    "stability": Decimal("0.5"),
                    "data_quality": Decimal("0.3"),
                    "listing_maturity": Decimal("0.3"),
                }
            )

    def test_non_decimal_weight_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ScoreWeights(
                {  # type: ignore[arg-type]
                    "liquidity": 0.5,
                    "stability": Decimal("0.3"),
                    "data_quality": Decimal("0.1"),
                    "listing_maturity": Decimal("0.1"),
                }
            )


class TestCriteria:
    def test_eligibility_default_exchanges(self) -> None:
        ec = EligibilityCriteria()
        assert ec.allowed_exchanges == ("SSE", "SZSE")
        assert ec.min_listing_days == 0

    def test_eligibility_negative_min_listing_days(self) -> None:
        with pytest.raises(ValueError, match="min_listing_days"):
            EligibilityCriteria(min_listing_days=-1)

    def test_liquidity_lookback_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="lookback_days"):
            LiquidityCriteria(lookback_days=0, min_valid_days=1)

    def test_liquidity_min_valid_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="min_valid_days"):
            LiquidityCriteria(lookback_days=10, min_valid_days=0)

    def test_liquidity_min_valid_cannot_exceed_lookback(self) -> None:
        with pytest.raises(ValueError, match="min_valid_days"):
            LiquidityCriteria(lookback_days=10, min_valid_days=20)

    def test_price_quality_ratio_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="max_missing_ratio"):
            PriceQualityCriteria(
                lookback_days=20,
                max_missing_ratio=Decimal("1.5"),
                max_zero_volume_days=3,
            )

    def test_price_quality_negative_zero_days(self) -> None:
        with pytest.raises(ValueError, match="max_zero_volume_days"):
            PriceQualityCriteria(
                lookback_days=20,
                max_missing_ratio=Decimal("0.1"),
                max_zero_volume_days=-1,
            )

    def test_selection_max_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_candidates"):
            SelectionCriteria(max_candidates=0)


class TestPolicy:
    def test_policy_auto_computes_parameter_hash(self) -> None:
        policy = _default_policy()
        assert len(policy.parameter_hash) == 64

    def test_policy_deterministic_hash(self) -> None:
        a = _default_policy()
        b = _default_policy()
        assert a.parameter_hash == b.parameter_hash

    def test_policy_different_algorithm_version_yields_different_hash(self) -> None:
        a = _default_policy()
        b = CandidatePoolPolicy(
            algorithm_key=a.algorithm_key,
            algorithm_version="1.0.1",
            parameter_set_key=a.parameter_set_key,
            eligibility=a.eligibility,
            liquidity=a.liquidity,
            price_quality=a.price_quality,
            risk=a.risk,
            selection=a.selection,
            score_weights=a.score_weights,
        )
        assert a.parameter_hash != b.parameter_hash

    def test_supplying_wrong_hash_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="parameter_hash"):
            CandidatePoolPolicy(
                algorithm_key="etf_candidate_pool",
                algorithm_version="1.0.0",
                parameter_set_key="default",
                eligibility=EligibilityCriteria(),
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
                parameter_hash="0" * 64,
            )

    def test_blank_algorithm_key_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            CandidatePoolPolicy(
                algorithm_key="",
                algorithm_version="1.0.0",
                parameter_set_key="default",
                eligibility=EligibilityCriteria(),
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


class TestStateMachine:
    def test_legal_transitions(self) -> None:
        run = CandidatePoolRun(
            id=uuid4(),
            trade_date=date(2026, 7, 30),
            algorithm_key="etf_candidate_pool",
            algorithm_version="1.0.0",
            parameter_set_key="default",
            parameter_hash=_default_policy().parameter_hash,
            input_snapshot_id=uuid4(),
            input_row_count=100,
            included_count=10,
            status=CandidatePoolStatus.CALCULATED,
            created_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
        )
        run = run.transition_to(CandidatePoolStatus.VALIDATED)
        run = run.transition_to(
            CandidatePoolStatus.PUBLISHED,
            at=datetime(2026, 7, 30, 9, 0, 0, tzinfo=timezone.utc),
        )
        assert run.status is CandidatePoolStatus.PUBLISHED
        assert run.published_at is not None

    def test_illegal_transition_calculated_to_published(self) -> None:
        run = CandidatePoolRun(
            id=uuid4(),
            trade_date=date(2026, 7, 30),
            algorithm_key="etf_candidate_pool",
            algorithm_version="1.0.0",
            parameter_set_key="default",
            parameter_hash=_default_policy().parameter_hash,
            input_snapshot_id=uuid4(),
            input_row_count=100,
            included_count=10,
            status=CandidatePoolStatus.CALCULATED,
            created_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
        )
        with pytest.raises(ValueError, match="illegal"):
            run.transition_to(CandidatePoolStatus.PUBLISHED)

    def test_illegal_transition_validated_to_rejected(self) -> None:
        run = CandidatePoolRun(
            id=uuid4(),
            trade_date=date(2026, 7, 30),
            algorithm_key="etf_candidate_pool",
            algorithm_version="1.0.0",
            parameter_set_key="default",
            parameter_hash=_default_policy().parameter_hash,
            input_snapshot_id=uuid4(),
            input_row_count=100,
            included_count=10,
            status=CandidatePoolStatus.CALCULATED,
            created_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
        )
        validated = run.transition_to(CandidatePoolStatus.VALIDATED)
        rejected = validated.transition_to(
            CandidatePoolStatus.REJECTED,
            at=datetime(2026, 7, 30, 9, 0, 0, tzinfo=timezone.utc),
            rejection_reason="quality errors",
        )
        assert rejected.status is CandidatePoolStatus.REJECTED
        assert rejected.rejection_reason == "quality errors"

    def test_terminal_state_cannot_transition(self) -> None:
        run = CandidatePoolRun(
            id=uuid4(),
            trade_date=date(2026, 7, 30),
            algorithm_key="etf_candidate_pool",
            algorithm_version="1.0.0",
            parameter_set_key="default",
            parameter_hash=_default_policy().parameter_hash,
            input_snapshot_id=uuid4(),
            input_row_count=100,
            included_count=10,
            status=CandidatePoolStatus.PUBLISHED,
            created_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
            published_at=datetime(2026, 7, 30, 9, 0, 0, tzinfo=timezone.utc),
        )
        with pytest.raises(ValueError, match="illegal"):
            run.transition_to(CandidatePoolStatus.REJECTED)

    def test_rejected_without_reason_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="rejection_reason"):
            CandidatePoolRun(
                id=uuid4(),
                trade_date=date(2026, 7, 30),
                algorithm_key="etf_candidate_pool",
                algorithm_version="1.0.0",
                parameter_set_key="default",
                parameter_hash=_default_policy().parameter_hash,
                input_snapshot_id=uuid4(),
                input_row_count=100,
                included_count=0,
                status=CandidatePoolStatus.REJECTED,
                created_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
            )

    def test_published_without_timestamp_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="published_at"):
            CandidatePoolRun(
                id=uuid4(),
                trade_date=date(2026, 7, 30),
                algorithm_key="etf_candidate_pool",
                algorithm_version="1.0.0",
                parameter_set_key="default",
                parameter_hash=_default_policy().parameter_hash,
                input_snapshot_id=uuid4(),
                input_row_count=100,
                included_count=10,
                status=CandidatePoolStatus.PUBLISHED,
                created_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
            )

    def test_naive_created_at_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            CandidatePoolRun(
                id=uuid4(),
                trade_date=date(2026, 7, 30),
                algorithm_key="etf_candidate_pool",
                algorithm_version="1.0.0",
                parameter_set_key="default",
                parameter_hash=_default_policy().parameter_hash,
                input_snapshot_id=uuid4(),
                input_row_count=100,
                included_count=10,
                status=CandidatePoolStatus.CALCULATED,
                created_at=datetime(2026, 7, 30, 8, 0, 0),  # naive
            )


class TestCalculationContext:
    def test_context_is_constructed(self) -> None:
        ctx = CalculationContext(
            trade_date=date(2026, 7, 30),
            as_of_utc=datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
            input_snapshot_id=uuid4(),
        )
        assert ctx.trade_date == date(2026, 7, 30)

    def test_naive_as_of_utc_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            CalculationContext(
                trade_date=date(2026, 7, 30),
                as_of_utc=datetime(2026, 7, 30, 8, 0, 0),
                input_snapshot_id=uuid4(),
            )

    def test_non_uuid_snapshot_id_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            CalculationContext(
                trade_date=date(2026, 7, 30),
                as_of_utc=datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
                input_snapshot_id="not-a-uuid",  # type: ignore[arg-type]
            )


class TestResultAndItem:
    def _items(self) -> tuple[CandidatePoolItem, CandidatePoolItem]:
        iid1 = InstrumentId.generate()
        iid2 = InstrumentId.generate()
        return (
            CandidatePoolItem(
                instrument_id=iid1,
                included=True,
                rank=1,
                total_score=Decimal("85.5"),
                metrics={"x": Decimal("1")},
            ),
            CandidatePoolItem(
                instrument_id=iid2,
                included=False,
                rank=None,
                total_score=None,
                exclusion_reasons=(ExclusionReason(code="liquidity", message="low"),),
            ),
        )

    def test_result_groups_included_and_excluded(self) -> None:
        policy = _default_policy()
        ctx = CalculationContext(
            trade_date=date(2026, 7, 30),
            as_of_utc=datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
            input_snapshot_id=uuid4(),
        )
        items = self._items()
        result = CandidatePoolResult(
            policy=policy,
            context=ctx,
            items=items,
            summary=CandidatePoolSummary(
                input_count=2,
                included_count=1,
                excluded_count=1,
                rule_error_count=0,
                rule_warn_count=1,
            ),
        )
        assert len(result.included_items) == 1
        assert len(result.excluded_items) == 1

    def test_duplicate_instrument_id_is_rejected(self) -> None:
        iid = InstrumentId.generate()
        item = CandidatePoolItem(
            instrument_id=iid,
            included=True,
            rank=1,
            total_score=Decimal("1"),
        )
        policy = _default_policy()
        ctx = CalculationContext(
            trade_date=date(2026, 7, 30),
            as_of_utc=datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
            input_snapshot_id=uuid4(),
        )
        with pytest.raises(ValueError, match="duplicate"):
            CandidatePoolResult(
                policy=policy,
                context=ctx,
                items=(item, item),
                summary=CandidatePoolSummary(
                    input_count=1,
                    included_count=1,
                    excluded_count=0,
                    rule_error_count=0,
                    rule_warn_count=0,
                ),
            )

    def test_included_item_must_have_rank(self) -> None:
        iid = InstrumentId.generate()
        with pytest.raises(ValueError, match="rank"):
            CandidatePoolItem(
                instrument_id=iid,
                included=True,
                rank=None,
                total_score=Decimal("1"),
            )

    def test_excluded_item_must_have_exclusion_reason(self) -> None:
        iid = InstrumentId.generate()
        with pytest.raises(ValueError, match="exclusion reason"):
            CandidatePoolItem(
                instrument_id=iid,
                included=False,
                rank=None,
                total_score=None,
            )

    def test_rule_outcome_rejects_non_decimal_threshold(self) -> None:
        with pytest.raises(TypeError):
            RuleOutcome(
                rule_key="x",
                passed=True,
                threshold=1,  # type: ignore[arg-type]
            )


class TestMarketDataFingerprint:
    def _make_bar(
        self,
        *,
        instrument_id: InstrumentId,
        trade_date: date,
        revision: int = 1,
        close: str = "3.15",
        volume: str = "1000",
        amount: str = "3150000",
        trading_status: TradingStatus = TradingStatus.NORMAL,
        source: BarSource | None = None,
    ) -> DailyBar:
        bar_source = source or make_bar_source()
        if trading_status is TradingStatus.SUSPENDED:
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
                trading_status=trading_status,
                source=bar_source,
                revision=revision,
            )
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
            trading_status=trading_status,
            source=bar_source,
            revision=revision,
        )

    def test_order_independence(self) -> None:
        a = self._make_bar(
            instrument_id=InstrumentId(uuid4()), trade_date=date(2026, 7, 30)
        )
        b = self._make_bar(
            instrument_id=InstrumentId(uuid4()), trade_date=date(2026, 7, 31)
        )
        assert compute_market_data_fingerprint([a, b]) == compute_market_data_fingerprint(
            [b, a]
        )

    def test_deterministic_identical_input(self) -> None:
        bar = self._make_bar(
            instrument_id=InstrumentId(uuid4()), trade_date=date(2026, 7, 30)
        )
        first = compute_market_data_fingerprint([bar])
        second = compute_market_data_fingerprint([bar])
        assert first == second
        assert len(first) == 64
        assert first == first.lower()

    def test_changed_revision_changes_fingerprint_with_same_row_hash(self) -> None:
        iid = InstrumentId(uuid4())
        shared_source = make_bar_source()
        revision_one = self._make_bar(
            instrument_id=iid,
            trade_date=date(2026, 7, 30),
            revision=1,
            source=shared_source,
        )
        revision_two = self._make_bar(
            instrument_id=iid,
            trade_date=date(2026, 7, 30),
            revision=2,
            source=shared_source,
        )
        assert revision_one.row_hash == revision_two.row_hash
        assert revision_one.revision != revision_two.revision
        assert compute_market_data_fingerprint(
            [revision_one]
        ) != compute_market_data_fingerprint([revision_two])

    def test_changed_row_content_changes_fingerprint(self) -> None:
        iid = InstrumentId(uuid4())
        first = self._make_bar(
            instrument_id=iid, trade_date=date(2026, 7, 30), close="3.15"
        )
        second = self._make_bar(
            instrument_id=iid, trade_date=date(2026, 7, 30), close="3.16"
        )
        assert first.row_hash != second.row_hash
        assert compute_market_data_fingerprint([first]) != compute_market_data_fingerprint(
            [second]
        )

    def test_empty_input_has_stable_fingerprint(self) -> None:
        assert compute_market_data_fingerprint([]) == compute_market_data_fingerprint(())

    def test_wrong_type_fails(self) -> None:
        with pytest.raises(TypeError, match="DailyBar"):
            compute_market_data_fingerprint(["not-a-bar"])  # type: ignore[list-item]

    def test_duplicate_identity_fails(self) -> None:
        iid = InstrumentId(uuid4())
        trade_date = date(2026, 7, 30)
        bar_a = self._make_bar(instrument_id=iid, trade_date=trade_date, revision=1)
        bar_b = self._make_bar(instrument_id=iid, trade_date=trade_date, revision=1)
        with pytest.raises(ValueError, match="duplicate"):
            compute_market_data_fingerprint([bar_a, bar_b])


class TestCandidatePoolRunMarketDataFingerprint:
    @staticmethod
    def _base_kwargs() -> dict[str, object]:
        return {
            "id": uuid4(),
            "trade_date": date(2026, 7, 30),
            "algorithm_key": "etf_candidate_pool",
            "algorithm_version": "1.0.0",
            "parameter_set_key": "default",
            "parameter_hash": _default_policy().parameter_hash,
            "input_snapshot_id": uuid4(),
            "input_row_count": 100,
            "included_count": 10,
            "status": CandidatePoolStatus.CALCULATED,
            "created_at": datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
        }

    def test_default_compatibility_uses_legacy_constant(self) -> None:
        run = CandidatePoolRun(**self._base_kwargs())
        assert run.market_data_fingerprint == LEGACY_MARKET_DATA_FINGERPRINT
        assert run.market_data_fingerprint == "0" * 64
        assert len(run.market_data_fingerprint) == 64

    def test_explicit_valid_fingerprint_is_accepted(self) -> None:
        digest = ("abcdef0123456789" * 4)
        assert len(digest) == 64
        run = CandidatePoolRun(**self._base_kwargs(), market_data_fingerprint=digest)
        assert run.market_data_fingerprint == digest

    def test_wrong_type_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="market_data_fingerprint"):
            CandidatePoolRun(**self._base_kwargs(), market_data_fingerprint=123)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("0" * 63, id="too-short"),
            pytest.param("0" * 65, id="too-long"),
            pytest.param("A" * 64, id="uppercase"),
            pytest.param("a" * 63 + "Z", id="mixed-case"),
            pytest.param("g" * 64, id="non-hex-letter"),
            pytest.param("0" * 63 + "!", id="non-hex-suffix"),
        ],
    )
    def test_invalid_fingerprints_are_rejected(self, value: str) -> None:
        with pytest.raises(ValueError, match="market_data_fingerprint"):
            CandidatePoolRun(**self._base_kwargs(), market_data_fingerprint=value)

    def test_transition_to_preserves_fingerprint(self) -> None:
        digest = "abcdef0123456789" * 4
        run = CandidatePoolRun(**self._base_kwargs(), market_data_fingerprint=digest)
        validated = run.transition_to(CandidatePoolStatus.VALIDATED)
        assert validated.market_data_fingerprint == digest
        published = validated.transition_to(
            CandidatePoolStatus.PUBLISHED,
            at=datetime(2026, 7, 30, 9, 0, 0, tzinfo=timezone.utc),
        )
        assert published.market_data_fingerprint == digest
