"""Focused tests for the Stage 4A-0 PR-03 institutional-recommendation channel.

Every behaviour pinned by the task brief is covered here:

1. Contract constants (``channel_key`` / ``channel_version``).
2. ``InstitutionRecommendation`` / ``InstitutionRecommendationBatch``
   validation rules (tz-aware datetimes, ``valid_until > published_at``,
   confidence in ``[0, 1]``, scalar-only metadata, ``external_opinion``
   marker).
3. ``evaluate_institutional_recommendation_channel`` happy path:
   rating → normalised score mapping and decision selection.
4. Five rating boundaries (recommended / positive / neutral /
   negative / avoid).
5. Source-key whitelist fail-closed behaviour (missing whitelist AND
   disallowed source key).
6. Expiry semantics (``as_of_datetime > valid_until``).
7. Unknown-symbol and unknown-instrument semantics (warning, no
   proposal, counter increment).
8. Dedup + conflict semantics (identical content collapses silently;
   conflicting content emits a warning and excludes the whole key).
9. Universe eligibility gate (``build_etf_universe``):
   INELIGIBLE → ``exclude``; PARTIAL caps ``include`` at ``watch``.
10. Determinism — same input (including reversed input) yields the
    same ``input_hash`` / ``output_hash`` and the same proposal
    order; no clock / random / environment reads.
11. Empty input (no recommendations) → empty proposals.
12. Module purity — no FastAPI / SQLAlchemy / Dagster / httpx / pandas
    re-exported; no infra-dependency imports.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import fields as dc_fields
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from invest_domain.candidate_pool.institutional_channel import (
    EXTERNAL_OPINION_MARKER,
    INSTITUTIONAL_CHANNEL_KEY,
    INSTITUTIONAL_CHANNEL_VERSION,
    REASON_SUMMARY_MAX_LENGTH,
    RECOMMENDATION_LEVEL_SCORES,
    DisallowedInstitutionSourceKeyError,
    InstitutionalChannelError,
    InstitutionalDecision,
    InstitutionalRecommendationChannelResult,
    InstitutionalRecommendationProposal,
    InstitutionChannelResultInvariantError,
    InstitutionRecommendation,
    InstitutionRecommendationBatch,
    InvalidInstitutionRecommendationBatchError,
    InvalidInstitutionRecommendationError,
    RecommendationLevel,
    evaluate_institutional_recommendation_channel,
)
from invest_domain.instruments.models import (
    Instrument,
    InstrumentId,
    InstrumentType,
)
from invest_domain.market_data.models import BarSource, DailyBar
from invest_domain.market_data.values import Adjust, TradingStatus

_AS_OF_DATE = date(2026, 8, 5)
_AS_OF_DATETIME = datetime(2026, 8, 5, 9, 30, tzinfo=UTC)
_PUBLISHED_AT = datetime(2026, 8, 3, 8, 0, tzinfo=timezone(timedelta(hours=8)))
_VALID_UNTIL = datetime(2026, 8, 10, 23, 59, 59, tzinfo=timezone(timedelta(hours=8)))
_SOURCE_KEY = "institution_x"
_SOURCE_REF = "institution_x:report_20260803"
_OBSERVED_AT = datetime(2026, 8, 5, 8, tzinfo=UTC)
_BATCH_ID = UUID("00000000-0000-4000-8000-000000000ccc")


def _iid(label: str) -> InstrumentId:
    """Stable :class:`InstrumentId` factory keyed off a label."""

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
        provider_key="institutional_channel_test",
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
    bars: list[DailyBar] = []
    start = Decimal(start_close)
    step_decimal = Decimal(step)
    for offset in range(count):
        close = start + step_decimal * offset
        bars.append(
            DailyBar.build(
                instrument_id=instrument_id,
                trade_date=_AS_OF_DATE - timedelta(days=(count - 1 - offset)),
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


def _recommendation(
    *,
    symbol: str,
    level: RecommendationLevel | str = RecommendationLevel.RECOMMENDED,
    source_ref: str = _SOURCE_REF,
    confidence: Decimal | str = "0.8",
    reason: str = "宽基配置价值提升",
    original_score: Decimal | str | None = "4",
    original_scale: str | None = "1-5",
) -> InstitutionRecommendation:
    resolved_level = level if isinstance(level, RecommendationLevel) else RecommendationLevel(level)
    resolved_confidence = confidence if isinstance(confidence, Decimal) else Decimal(confidence)
    resolved_score = (
        original_score
        if isinstance(original_score, Decimal) or original_score is None
        else Decimal(original_score)
    )
    return InstitutionRecommendation(
        symbol=symbol,
        recommendation_level=resolved_level,
        source_ref=source_ref,
        confidence=resolved_confidence,
        reason_summary=reason,
        original_score=resolved_score,
        original_scale=original_scale,
    )


def _batch(
    recommendations: tuple[InstitutionRecommendation, ...],
    *,
    source_key: str = _SOURCE_KEY,
    published_at: datetime = _PUBLISHED_AT,
    valid_until: datetime = _VALID_UNTIL,
) -> InstitutionRecommendationBatch:
    return InstitutionRecommendationBatch(
        source_key=source_key,
        published_at=published_at,
        valid_until=valid_until,
        recommendations=recommendations,
    )


def _two_etf_fixture() -> tuple[
    list[Instrument], dict[InstrumentId, list[DailyBar]], dict[str, InstrumentId]
]:
    """Build a two-ETF fixture with FULL and PARTIAL universe entries."""

    full = _instrument("alpha", symbol="510300")
    partial = _instrument("beta", symbol="510500")
    bars = {
        _iid("alpha"): _uptrend_bars(_iid("alpha"), 65),
        _iid("beta"): _uptrend_bars(_iid("beta"), 30),
    }
    mapping = {"510300": full.instrument_id, "510500": partial.instrument_id}
    return [full, partial], bars, mapping


# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------


class TestContractConstants:
    def test_channel_key_and_version_match_plan(self) -> None:
        # plan §6 ``Channel B`` mandates ``institutional_recommendation``.
        assert INSTITUTIONAL_CHANNEL_KEY == "institutional_recommendation"
        assert INSTITUTIONAL_CHANNEL_VERSION == "1.0.0"

    def test_recommendation_level_scores_match_plan(self) -> None:
        # plan §11.3 fixed rating → normalised-score mapping.
        assert dict(RECOMMENDATION_LEVEL_SCORES) == {
            "recommended": Decimal("80"),
            "positive": Decimal("70"),
            "neutral": Decimal("50"),
            "negative": Decimal("20"),
            "avoid": Decimal("0"),
        }

    def test_recommendation_level_enum_values_match_plan(self) -> None:
        assert {level.value for level in RecommendationLevel} == {
            "recommended",
            "positive",
            "neutral",
            "negative",
            "avoid",
        }

    def test_external_opinion_marker_is_pinned(self) -> None:
        assert EXTERNAL_OPINION_MARKER == "external_opinion"

    def test_proposal_carries_no_buy_or_sell_field(self) -> None:
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
        names = {field.name for field in dc_fields(InstitutionalRecommendationProposal)}
        assert forbidden.isdisjoint(names), (
            f"InstitutionalRecommendationProposal must not carry screening-banned fields; "
            f"got {sorted(forbidden & names)!r}"
        )

    def test_decision_vocabulary_matches_plan(self) -> None:
        assert {decision.value for decision in InstitutionalDecision} == {
            "include",
            "watch",
            "exclude",
            "no_opinion",
        }


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestRecommendationValidation:
    def test_blank_symbol_is_rejected(self) -> None:
        with pytest.raises(InvalidInstitutionRecommendationError, match="symbol"):
            InstitutionRecommendation(
                symbol="   ",
                recommendation_level=RecommendationLevel.POSITIVE,
                source_ref="ref",
                confidence=Decimal("0.5"),
                reason_summary="reason",
            )

    def test_blank_source_ref_is_rejected(self) -> None:
        with pytest.raises(InvalidInstitutionRecommendationError, match="source_ref"):
            InstitutionRecommendation(
                symbol="510300",
                recommendation_level=RecommendationLevel.POSITIVE,
                source_ref="",
                confidence=Decimal("0.5"),
                reason_summary="reason",
            )

    def test_blank_reason_summary_is_rejected(self) -> None:
        with pytest.raises(InvalidInstitutionRecommendationError, match="reason_summary"):
            InstitutionRecommendation(
                symbol="510300",
                recommendation_level=RecommendationLevel.POSITIVE,
                source_ref="ref",
                confidence=Decimal("0.5"),
                reason_summary="",
            )

    def test_confidence_outside_unit_interval_is_rejected(self) -> None:
        with pytest.raises(InvalidInstitutionRecommendationError, match="confidence"):
            InstitutionRecommendation(
                symbol="510300",
                recommendation_level=RecommendationLevel.POSITIVE,
                source_ref="ref",
                confidence=Decimal("1.5"),
                reason_summary="reason",
            )
        with pytest.raises(InvalidInstitutionRecommendationError, match="confidence"):
            InstitutionRecommendation(
                symbol="510300",
                recommendation_level=RecommendationLevel.POSITIVE,
                source_ref="ref",
                confidence=Decimal("-0.1"),
                reason_summary="reason",
            )

    def test_non_finite_confidence_is_rejected(self) -> None:
        nan = Decimal("NaN")
        with pytest.raises(InvalidInstitutionRecommendationError, match="confidence"):
            InstitutionRecommendation(
                symbol="510300",
                recommendation_level=RecommendationLevel.POSITIVE,
                source_ref="ref",
                confidence=nan,  # type: ignore[arg-type]
                reason_summary="reason",
            )

    def test_unknown_recommendation_level_is_rejected(self) -> None:
        with pytest.raises(InvalidInstitutionRecommendationError, match="recommendation_level"):
            InstitutionRecommendation(
                symbol="510300",
                recommendation_level="very-good",  # type: ignore[arg-type]
                source_ref="ref",
                confidence=Decimal("0.5"),
                reason_summary="reason",
            )

    def test_invalid_original_score_is_rejected(self) -> None:
        with pytest.raises(InvalidInstitutionRecommendationError, match="original_score"):
            InstitutionRecommendation(
                symbol="510300",
                recommendation_level=RecommendationLevel.POSITIVE,
                source_ref="ref",
                confidence=Decimal("0.5"),
                reason_summary="reason",
                original_score=Decimal("NaN"),  # type: ignore[arg-type]
            )

    def test_blank_original_scale_is_rejected(self) -> None:
        with pytest.raises(InvalidInstitutionRecommendationError, match="original_scale"):
            InstitutionRecommendation(
                symbol="510300",
                recommendation_level=RecommendationLevel.POSITIVE,
                source_ref="ref",
                confidence=Decimal("0.5"),
                reason_summary="reason",
                original_score=Decimal("4"),
                original_scale="   ",
            )

    def test_reason_summary_length_cap_constant_is_pinned(self) -> None:
        # plan §11.4: only the bounded summary is persisted; pin the
        # concrete cap so audit readers can quote the contract.
        assert REASON_SUMMARY_MAX_LENGTH == 500

    def test_reason_summary_at_length_cap_is_accepted(self) -> None:
        # The cap is inclusive — exactly REASON_SUMMARY_MAX_LENGTH
        # characters is fine.
        rec = InstitutionRecommendation(
            symbol="510300",
            recommendation_level=RecommendationLevel.POSITIVE,
            source_ref="ref",
            confidence=Decimal("0.5"),
            reason_summary="x" * REASON_SUMMARY_MAX_LENGTH,
        )
        assert len(rec.reason_summary) == REASON_SUMMARY_MAX_LENGTH

    def test_reason_summary_over_length_cap_is_rejected(self) -> None:
        with pytest.raises(
            InvalidInstitutionRecommendationError,
            match=rf"reason_summary.*{REASON_SUMMARY_MAX_LENGTH}",
        ):
            InstitutionRecommendation(
                symbol="510300",
                recommendation_level=RecommendationLevel.POSITIVE,
                source_ref="ref",
                confidence=Decimal("0.5"),
                reason_summary="x" * (REASON_SUMMARY_MAX_LENGTH + 1),
            )


class TestBatchValidation:
    def test_blank_source_key_is_rejected(self) -> None:
        with pytest.raises(InvalidInstitutionRecommendationBatchError, match="source_key"):
            InstitutionRecommendationBatch(
                source_key="",
                published_at=_PUBLISHED_AT,
                valid_until=_VALID_UNTIL,
                recommendations=(),
            )

    def test_naive_published_at_is_rejected(self) -> None:
        with pytest.raises(InvalidInstitutionRecommendationBatchError, match="published_at"):
            InstitutionRecommendationBatch(
                source_key=_SOURCE_KEY,
                published_at=datetime(2026, 8, 3, 8, 0),  # naive
                valid_until=_VALID_UNTIL,
                recommendations=(),
            )

    def test_naive_valid_until_is_rejected(self) -> None:
        with pytest.raises(InvalidInstitutionRecommendationBatchError, match="valid_until"):
            InstitutionRecommendationBatch(
                source_key=_SOURCE_KEY,
                published_at=_PUBLISHED_AT,
                valid_until=datetime(2026, 8, 10, 23, 59, 59),  # naive
                recommendations=(),
            )

    def test_valid_until_not_strictly_after_published_at_is_rejected(self) -> None:
        with pytest.raises(InvalidInstitutionRecommendationBatchError, match="strictly after"):
            InstitutionRecommendationBatch(
                source_key=_SOURCE_KEY,
                published_at=_PUBLISHED_AT,
                valid_until=_PUBLISHED_AT,  # equal
                recommendations=(),
            )

    def test_invalid_recommendation_in_batch_is_rejected(self) -> None:
        # Bypass ``InstitutionRecommendation.__post_init__`` by passing a
        # non-recommendation object directly into the batch; this
        # exercises the batch-level containment check without relying on
        # the inner dataclass raising first.
        with pytest.raises(InvalidInstitutionRecommendationBatchError, match="recommendations"):
            InstitutionRecommendationBatch(
                source_key=_SOURCE_KEY,
                published_at=_PUBLISHED_AT,
                valid_until=_VALID_UNTIL,
                recommendations=("not-an-institution-recommendation",),  # type: ignore[arg-type]
            )

    def test_recommendations_must_be_tuple(self) -> None:
        with pytest.raises(InvalidInstitutionRecommendationBatchError, match="recommendations"):
            InstitutionRecommendationBatch(
                source_key=_SOURCE_KEY,
                published_at=_PUBLISHED_AT,
                valid_until=_VALID_UNTIL,
                recommendations=[_recommendation(symbol="510300")],  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Source whitelist (fail-closed)
# ---------------------------------------------------------------------------


class TestSourceWhitelist:
    def test_empty_whitelist_is_rejected(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        batch = _batch((_recommendation(symbol="510300"),))
        with pytest.raises(DisallowedInstitutionSourceKeyError, match="whitelist"):
            evaluate_institutional_recommendation_channel(
                instruments=instruments,
                bars_by_instrument=bars,
                batch=batch,
                allowed_source_keys=frozenset(),
                as_of_datetime=_AS_OF_DATETIME,
                symbol_to_instrument=mapping,
            )

    def test_disallowed_source_key_is_rejected(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        batch = _batch(
            (_recommendation(symbol="510300"),),
            source_key="rogue_institution",
        )
        with pytest.raises(DisallowedInstitutionSourceKeyError, match="not in"):
            evaluate_institutional_recommendation_channel(
                instruments=instruments,
                bars_by_instrument=bars,
                batch=batch,
                allowed_source_keys=frozenset({_SOURCE_KEY}),
                as_of_datetime=_AS_OF_DATETIME,
                symbol_to_instrument=mapping,
            )

    def test_non_set_whitelist_type_is_rejected(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        batch = _batch((_recommendation(symbol="510300"),))
        with pytest.raises(TypeError, match="set or frozenset"):
            evaluate_institutional_recommendation_channel(
                instruments=instruments,
                bars_by_instrument=bars,
                batch=batch,
                allowed_source_keys=[_SOURCE_KEY],  # type: ignore[arg-type]
                as_of_datetime=_AS_OF_DATETIME,
                symbol_to_instrument=mapping,
            )


# ---------------------------------------------------------------------------
# Happy path / rating boundary
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_recommended_rating_yields_include_for_full(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        batch = _batch((_recommendation(symbol="510300"),))
        result = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert len(result.proposals) == 1
        proposal = result.proposals[0]
        assert proposal.decision == "include"
        assert proposal.normalized_score == Decimal("80")
        assert proposal.confidence == Decimal("0.8")
        assert proposal.symbol == "510300"
        assert proposal.exchange == "SSE"
        assert proposal.channel_key == INSTITUTIONAL_CHANNEL_KEY
        assert proposal.channel_version == INSTITUTIONAL_CHANNEL_VERSION
        assert proposal.metadata[EXTERNAL_OPINION_MARKER] is True
        assert result.include_count == 1
        assert result.watch_count == 0
        assert result.exclude_count == 0
        assert result.no_opinion_count == 0

    def test_rating_score_mapping_is_exact(self) -> None:
        for level, score in RECOMMENDATION_LEVEL_SCORES.items():
            instrument = _instrument(level, symbol=level)
            iid = instrument.instrument_id
            assert iid is not None
            bars = {iid: _uptrend_bars(iid, 65)}
            mapping = {level: iid}
            batch = _batch((_recommendation(symbol=level, level=level),))
            result = evaluate_institutional_recommendation_channel(
                instruments=[instrument],
                bars_by_instrument=bars,
                batch=batch,
                allowed_source_keys=frozenset({_SOURCE_KEY}),
                as_of_datetime=_AS_OF_DATETIME,
                symbol_to_instrument=mapping,
            )
            assert len(result.proposals) == 1
            assert result.proposals[0].normalized_score == score


class TestRatingBoundary:
    def test_full_recommended_decision_is_include(self) -> None:
        instrument = _instrument("full_recommended", symbol="510300")
        iid = instrument.instrument_id
        bars = {iid: _uptrend_bars(iid, 65)}
        result = _evaluate_single(instrument, bars, "510300", RecommendationLevel.RECOMMENDED)
        assert result.proposals[0].decision == "include"

    def test_full_positive_decision_is_include(self) -> None:
        instrument = _instrument("full_positive", symbol="510300")
        iid = instrument.instrument_id
        bars = {iid: _uptrend_bars(iid, 65)}
        result = _evaluate_single(instrument, bars, "510300", RecommendationLevel.POSITIVE)
        assert result.proposals[0].decision == "include"

    def test_full_neutral_decision_is_watch(self) -> None:
        instrument = _instrument("full_neutral", symbol="510300")
        iid = instrument.instrument_id
        bars = {iid: _uptrend_bars(iid, 65)}
        result = _evaluate_single(instrument, bars, "510300", RecommendationLevel.NEUTRAL)
        assert result.proposals[0].decision == "watch"

    def test_full_negative_decision_is_exclude(self) -> None:
        instrument = _instrument("full_negative", symbol="510300")
        iid = instrument.instrument_id
        bars = {iid: _uptrend_bars(iid, 65)}
        result = _evaluate_single(instrument, bars, "510300", RecommendationLevel.NEGATIVE)
        assert result.proposals[0].decision == "exclude"
        assert result.proposals[0].normalized_score == Decimal("20")

    def test_full_avoid_decision_is_exclude(self) -> None:
        instrument = _instrument("full_avoid", symbol="510300")
        iid = instrument.instrument_id
        bars = {iid: _uptrend_bars(iid, 65)}
        result = _evaluate_single(instrument, bars, "510300", RecommendationLevel.AVOID)
        assert result.proposals[0].decision == "exclude"
        assert result.proposals[0].normalized_score == Decimal("0")


def _evaluate_single(
    instrument: Instrument,
    bars: dict[InstrumentId, list[DailyBar]],
    symbol: str,
    level: RecommendationLevel,
) -> InstitutionalRecommendationChannelResult:
    iid = instrument.instrument_id
    assert iid is not None
    mapping = {symbol: iid}
    batch = _batch((_recommendation(symbol=symbol, level=level),))
    return evaluate_institutional_recommendation_channel(
        instruments=[instrument],
        bars_by_instrument=bars,
        batch=batch,
        allowed_source_keys=frozenset({_SOURCE_KEY}),
        as_of_datetime=_AS_OF_DATETIME,
        symbol_to_instrument=mapping,
    )


# ---------------------------------------------------------------------------
# Expiry / time semantics
# ---------------------------------------------------------------------------


class TestExpiry:
    def test_as_of_after_valid_until_marks_expired(self) -> None:
        instrument = _instrument("expired_full", symbol="510300")
        iid = instrument.instrument_id
        bars = {iid: _uptrend_bars(iid, 65)}
        mapping = {"510300": iid}
        batch = _batch((_recommendation(symbol="510300"),))
        late = _VALID_UNTIL + timedelta(hours=1)
        result = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=late,
            symbol_to_instrument=mapping,
        )
        assert result.proposals == ()
        assert result.expired_count == 1
        assert any("institutional.expired" in warning for warning in result.warnings)

    def test_as_of_exactly_at_valid_until_is_still_valid(self) -> None:
        instrument = _instrument("on_expiry_full", symbol="510300")
        iid = instrument.instrument_id
        bars = {iid: _uptrend_bars(iid, 65)}
        mapping = {"510300": iid}
        batch = _batch((_recommendation(symbol="510300"),))
        result = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_VALID_UNTIL,
            symbol_to_instrument=mapping,
        )
        assert len(result.proposals) == 1
        assert result.expired_count == 0

    def test_naive_as_of_datetime_is_rejected(self) -> None:
        instrument = _instrument("naive_asof", symbol="510300")
        iid = instrument.instrument_id
        bars = {iid: _uptrend_bars(iid, 65)}
        mapping = {"510300": iid}
        batch = _batch((_recommendation(symbol="510300"),))
        with pytest.raises(
            InstitutionalChannelError, match="as_of_datetime must be timezone-aware"
        ):
            evaluate_institutional_recommendation_channel(
                instruments=[instrument],
                bars_by_instrument=bars,
                batch=batch,
                allowed_source_keys=frozenset({_SOURCE_KEY}),
                as_of_datetime=datetime(2026, 8, 5, 9, 30),  # naive
                symbol_to_instrument=mapping,
            )

    def test_mismatched_as_of_date_is_rejected(self) -> None:
        instrument = _instrument("mismatched_date", symbol="510300")
        iid = instrument.instrument_id
        bars = {iid: _uptrend_bars(iid, 65)}
        mapping = {"510300": iid}
        batch = _batch((_recommendation(symbol="510300"),))
        with pytest.raises(InvalidInstitutionRecommendationBatchError, match="as_of_date"):
            evaluate_institutional_recommendation_channel(
                instruments=[instrument],
                bars_by_instrument=bars,
                batch=batch,
                allowed_source_keys=frozenset({_SOURCE_KEY}),
                as_of_datetime=_AS_OF_DATETIME,
                as_of_date=date(2026, 8, 6),
                symbol_to_instrument=mapping,
            )


# ---------------------------------------------------------------------------
# Unknown symbol / universe gate
# ---------------------------------------------------------------------------


class TestUnknownSymbol:
    def test_unknown_symbol_emits_warning_without_proposal(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        batch = _batch(
            (
                _recommendation(symbol="999999", reason="未知标的"),
                _recommendation(symbol="510300"),
            )
        )
        result = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert len(result.proposals) == 1
        assert result.proposals[0].symbol == "510300"
        assert result.unknown_symbol_count == 1
        assert any("institutional.unknown_symbol:999999" in w for w in result.warnings)

    def test_symbol_in_mapping_but_not_in_universe_emits_warning(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        # Symbol maps to an InstrumentId that is NOT present in the
        # ``instruments`` sequence, so the universe classifier never
        # sees the underlying instrument. The channel must surface this
        # as a warning + counter increment without ever emitting a
        # proposal.
        ghost_id = _iid("ghost")
        ghost_mapping = {**mapping, "999999": ghost_id}
        batch = _batch((_recommendation(symbol="999999"),))
        result = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=ghost_mapping,
        )
        assert result.proposals == ()
        assert result.unknown_symbol_count == 1
        assert any("institutional.universe_missing:999999" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Dedup + conflict
# ---------------------------------------------------------------------------


class TestDedupAndConflict:
    def test_identical_content_collapses_silently(self) -> None:
        instrument = _instrument("dedup_full", symbol="510300")
        iid = instrument.instrument_id
        bars = {iid: _uptrend_bars(iid, 65)}
        mapping = {"510300": iid}
        rec_a = _recommendation(symbol="510300", level=RecommendationLevel.RECOMMENDED)
        rec_b = _recommendation(symbol="510300", level=RecommendationLevel.RECOMMENDED)
        batch = _batch((rec_a, rec_b))
        result = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert len(result.proposals) == 1
        assert result.conflict_count == 0
        assert result.unknown_symbol_count == 0

    def test_conflicting_content_is_excluded_with_warning(self) -> None:
        instrument = _instrument("conflict_full", symbol="510300")
        iid = instrument.instrument_id
        bars = {iid: _uptrend_bars(iid, 65)}
        mapping = {"510300": iid}
        rec_a = _recommendation(symbol="510300", level=RecommendationLevel.RECOMMENDED)
        rec_b = _recommendation(symbol="510300", level=RecommendationLevel.AVOID)
        batch = _batch((rec_a, rec_b))
        result = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert result.proposals == ()
        assert result.conflict_count == 1
        assert any("institutional.conflict" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Universe eligibility gate
# ---------------------------------------------------------------------------


class TestUniverseGate:
    def test_ineligible_instrument_forces_exclude_with_reasons(self) -> None:
        not_etf = _instrument("not_etf", symbol="510300", kind=InstrumentType.STOCK)
        batch = _batch((_recommendation(symbol="510300"),))
        result = evaluate_institutional_recommendation_channel(
            instruments=[not_etf],
            bars_by_instrument={},
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument={"510300": not_etf.instrument_id},
        )
        assert len(result.proposals) == 1
        proposal = result.proposals[0]
        assert proposal.decision == "exclude"
        assert any(
            reason.startswith("institutional.universe:not_etf") for reason in proposal.reasons
        )
        assert result.exclude_count == 1

    def test_suspended_instrument_is_ineligible(self) -> None:
        instrument = _instrument("suspended", symbol="510300")
        iid = instrument.instrument_id
        bars = [_normal_bar(iid, _AS_OF_DATE - timedelta(days=offset)) for offset in range(1, 60)]
        bars.append(_suspended_bar(iid, _AS_OF_DATE))
        batch = _batch((_recommendation(symbol="510300"),))
        result = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument={iid: bars},
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument={"510300": iid},
        )
        proposal = result.proposals[0]
        assert proposal.decision == "exclude"
        assert any(
            reason.startswith("institutional.universe:suspended") for reason in proposal.reasons
        )

    def test_no_valid_price_is_ineligible(self) -> None:
        instrument = _instrument("no_price", symbol="510300")
        iid = instrument.instrument_id
        batch = _batch((_recommendation(symbol="510300"),))
        result = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument={iid: []},
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument={"510300": iid},
        )
        proposal = result.proposals[0]
        assert proposal.decision == "exclude"
        assert any(
            reason.startswith("institutional.universe:no_valid_price")
            for reason in proposal.reasons
        )


# ---------------------------------------------------------------------------
# Partial cap
# ---------------------------------------------------------------------------


class TestPartialCap:
    def test_partial_history_caps_include_at_watch(self) -> None:
        instrument = _instrument("partial_rec", symbol="510300")
        iid = instrument.instrument_id
        bars = {iid: _uptrend_bars(iid, 30)}
        mapping = {"510300": iid}
        batch = _batch((_recommendation(symbol="510300", level=RecommendationLevel.RECOMMENDED),))
        result = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert len(result.proposals) == 1
        proposal = result.proposals[0]
        assert proposal.decision == "watch"
        assert proposal.normalized_score == Decimal("80")
        assert proposal.metadata["eligibility"] == "partial"
        assert "institutional.partial_history_capped_at_watch" in proposal.reasons
        assert result.watch_count == 1
        assert result.include_count == 0

    def test_partial_negative_rating_still_excludes(self) -> None:
        instrument = _instrument("partial_negative", symbol="510300")
        iid = instrument.instrument_id
        bars = {iid: _uptrend_bars(iid, 30)}
        mapping = {"510300": iid}
        batch = _batch((_recommendation(symbol="510300", level=RecommendationLevel.NEGATIVE),))
        result = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert result.proposals[0].decision == "exclude"


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


class TestEmptyInput:
    def test_empty_recommendations_yields_empty_proposals(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        batch = _batch(())
        result = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert result.proposals == ()
        assert result.warnings == ()
        assert result.include_count == 0
        assert result.watch_count == 0
        assert result.exclude_count == 0
        assert result.no_opinion_count == 0
        assert result.unknown_symbol_count == 0
        assert result.expired_count == 0
        assert result.conflict_count == 0
        assert len(result.input_hash) == 64
        assert len(result.output_hash) == 64

    def test_empty_instruments_yields_empty_proposals(self) -> None:
        batch = _batch((_recommendation(symbol="510300"),))
        result = evaluate_institutional_recommendation_channel(
            instruments=[],
            bars_by_instrument={},
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument={"510300": _iid("nothing")},
        )
        assert result.proposals == ()
        assert result.unknown_symbol_count == 1


# ---------------------------------------------------------------------------
# Determinism / stable hash & order
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_rerun_with_identical_inputs_is_byte_equal(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        batch = _batch(
            (
                _recommendation(symbol="510300", level=RecommendationLevel.RECOMMENDED),
                _recommendation(symbol="510500", level=RecommendationLevel.POSITIVE),
            )
        )
        first = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        second = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert first == second
        assert first.input_hash == second.input_hash
        assert first.output_hash == second.output_hash

    def test_reversed_input_order_yields_same_proposal_order_and_hashes(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        forward_batch = _batch(
            (
                _recommendation(symbol="510300", level=RecommendationLevel.POSITIVE),
                _recommendation(symbol="510500", level=RecommendationLevel.RECOMMENDED),
            )
        )
        backward_batch = _batch(tuple(reversed(forward_batch.recommendations)))
        forward = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=forward_batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        backward = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=backward_batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert forward.input_hash == backward.input_hash
        assert forward.output_hash == backward.output_hash
        assert [p.symbol for p in forward.proposals] == [p.symbol for p in backward.proposals]

    def test_proposals_sort_by_eligibility_then_decision_then_score(self) -> None:
        # Three ETFs: full/positive (include), partial/recommended (watch),
        # ineligible/avoid (exclude). Verify the ordering matches the
        # documented stable key.
        full = _instrument("full_p", symbol="510300")
        partial = _instrument("partial_r", symbol="510500")
        ineligible = _instrument("ineligible_a", symbol="510700", kind=InstrumentType.STOCK)
        bars = {
            full.instrument_id: _uptrend_bars(full.instrument_id, 65),
            partial.instrument_id: _uptrend_bars(partial.instrument_id, 30),
            ineligible.instrument_id: [],
        }
        mapping = {
            "510300": full.instrument_id,
            "510500": partial.instrument_id,
            "510700": ineligible.instrument_id,
        }
        batch = _batch(
            (
                _recommendation(symbol="510300", level=RecommendationLevel.POSITIVE),
                _recommendation(symbol="510500", level=RecommendationLevel.RECOMMENDED),
                _recommendation(symbol="510700", level=RecommendationLevel.AVOID),
            )
        )
        result = evaluate_institutional_recommendation_channel(
            instruments=[full, partial, ineligible],
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        symbols = [proposal.symbol for proposal in result.proposals]
        # Expect: FULL include first (510300), PARTIAL watch next (510500),
        # INELIGIBLE exclude last (510700).
        assert symbols == ["510300", "510500", "510700"]

    def test_module_does_not_seed_random_or_use_clock(self) -> None:
        import random
        import time

        random.seed(0)
        time.time()
        instruments, bars, mapping = _two_etf_fixture()
        batch = _batch(
            (
                _recommendation(symbol="510300"),
                _recommendation(symbol="510500", level=RecommendationLevel.POSITIVE),
            )
        )
        first = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        random.seed(42)
        time.time()
        second = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert first == second


# ---------------------------------------------------------------------------
# Input-hash coverage of the universe classifier
# ---------------------------------------------------------------------------


class TestInputHashUniverseFingerprint:
    """Regression tests for the input-hash ↔ universe coupling.

    ARC review of PR-03 caught that the previous ``_compute_input_hash``
    only covered the batch, the source-key whitelist and the
    symbol→instrument mapping. Without the universe fingerprint a
    change in ``bars_by_instrument`` that moves an instrument from
    ``FULL`` to ``PARTIAL`` / ``INELIGIBLE`` would leave
    ``input_hash`` byte-identical, violating the "channel input is
    auditable" guarantee in plan §15. These tests pin the new
    coverage so the regression cannot creep back in.
    """

    def test_full_to_ineligible_transition_changes_input_hash(self) -> None:
        # Build a single ETF that is FULL with rich history …
        instrument = _instrument("hash_full_to_ineligible", symbol="510300")
        iid = instrument.instrument_id
        assert iid is not None
        rich_bars = {iid: _uptrend_bars(iid, 65)}
        mapping = {"510300": iid}
        batch = _batch((_recommendation(symbol="510300"),))

        full_result = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument=rich_bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        full_proposal = full_result.proposals[0]
        assert full_proposal.decision == "include"
        assert full_proposal.metadata["eligibility"] == "full"

        # … and the same instrument with no bars at all (no_valid_price
        # → INELIGIBLE). Every other input is identical.
        ineligible_result = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument={iid: []},
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        ineligible_proposal = ineligible_result.proposals[0]
        assert ineligible_proposal.decision == "exclude"
        assert ineligible_proposal.metadata["eligibility"] == "ineligible"

        # The regression: input_hash must differ once the universe
        # verdict changes, even though the batch / mapping / source
        # key / as_of_datetime are byte-identical.
        assert full_result.input_hash != ineligible_result.input_hash

    def test_full_to_partial_transition_changes_input_hash(self) -> None:
        # Same setup as above but flip FULL → PARTIAL by feeding a
        # shorter history (between the partial and full thresholds).
        instrument = _instrument("hash_full_to_partial", symbol="510300")
        iid = instrument.instrument_id
        assert iid is not None
        rich_bars = {iid: _uptrend_bars(iid, 65)}
        partial_bars = {iid: _uptrend_bars(iid, 30)}
        mapping = {"510300": iid}
        batch = _batch((_recommendation(symbol="510300"),))

        full_result = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument=rich_bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        partial_result = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument=partial_bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert full_result.proposals[0].metadata["eligibility"] == "full"
        assert partial_result.proposals[0].metadata["eligibility"] == "partial"
        assert full_result.input_hash != partial_result.input_hash

    def test_input_hash_is_stable_when_only_universe_is_byte_equal(self) -> None:
        # Sanity — once the universe fingerprint is in the payload,
        # two runs with the same universe verdict and the same batch
        # must still produce identical input_hash bytes.
        instrument = _instrument("hash_stable", symbol="510300")
        iid = instrument.instrument_id
        assert iid is not None
        bars = {iid: _uptrend_bars(iid, 65)}
        mapping = {"510300": iid}
        batch = _batch((_recommendation(symbol="510300"),))

        a = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        b = evaluate_institutional_recommendation_channel(
            instruments=[instrument],
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert a.input_hash == b.input_hash


# ---------------------------------------------------------------------------
# Purity / no-side-effects
# ---------------------------------------------------------------------------


class TestPurity:
    def test_module_does_not_import_infra_deps(self) -> None:
        import invest_domain.candidate_pool.institutional_channel as module

        forbidden = {"sqlalchemy", "pandas", "polars", "fastapi", "dagster", "httpx"}
        assert forbidden.isdisjoint(set(getattr(module, "__all__", [])))
        for name in forbidden:
            assert not hasattr(module, name), (
                f"institutional_channel must not expose infra dep {name}"
            )

    def test_function_has_no_side_effects_on_inputs(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        rec = _recommendation(symbol="510300")
        batch = _batch((rec,))
        before_recs = batch.recommendations
        before_source_key = batch.source_key
        before_published_at = batch.published_at
        evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert batch.recommendations == before_recs
        assert batch.source_key == before_source_key
        assert batch.published_at == before_published_at

    def test_function_returns_new_value_each_call(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        batch = _batch((_recommendation(symbol="510300"),))
        result_a = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        result_b = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert result_a == result_b
        assert result_a is not result_b


# ---------------------------------------------------------------------------
# Result / proposal value-object invariants
# ---------------------------------------------------------------------------


class TestResultInvariants:
    def test_result_rejects_duplicate_instrument_ids(self) -> None:
        proposal = _proposal_for("alpha")
        with pytest.raises(InstitutionChannelResultInvariantError, match="duplicate"):
            InstitutionalRecommendationChannelResult(
                channel_key=INSTITUTIONAL_CHANNEL_KEY,
                channel_version=INSTITUTIONAL_CHANNEL_VERSION,
                source_key=_SOURCE_KEY,
                as_of_date=_AS_OF_DATE,
                as_of_datetime=_AS_OF_DATETIME,
                input_hash="a" * 64,
                output_hash="b" * 64,
                proposals=(proposal, proposal),
            )

    def test_proposal_requires_external_opinion_marker(self) -> None:
        with pytest.raises(InstitutionChannelResultInvariantError, match=EXTERNAL_OPINION_MARKER):
            InstitutionalRecommendationProposal(
                instrument_id=_iid("alpha"),
                symbol="510300",
                exchange="SSE",
                channel_key=INSTITUTIONAL_CHANNEL_KEY,
                channel_version=INSTITUTIONAL_CHANNEL_VERSION,
                decision="include",
                normalized_score=Decimal("80"),
                confidence=Decimal("0.8"),
                reasons=("institutional.rating:recommended",),
                evidence_refs=("ref",),
                published_at=_PUBLISHED_AT,
                valid_until=_VALID_UNTIL,
                # No external_opinion marker.
            )

    def test_proposal_rejects_invalid_decimal_score(self) -> None:
        with pytest.raises(InstitutionChannelResultInvariantError, match="normalized_score"):
            InstitutionalRecommendationProposal(
                instrument_id=_iid("alpha"),
                symbol="510300",
                exchange="SSE",
                channel_key=INSTITUTIONAL_CHANNEL_KEY,
                channel_version=INSTITUTIONAL_CHANNEL_VERSION,
                decision="include",
                normalized_score=Decimal("200"),
                confidence=Decimal("0.8"),
                reasons=("institutional.rating:recommended",),
                evidence_refs=("ref",),
                published_at=_PUBLISHED_AT,
                valid_until=_VALID_UNTIL,
            )

    def test_proposal_rejects_non_json_metadata_value(self) -> None:
        with pytest.raises(InstitutionChannelResultInvariantError, match="metadata"):
            # Tuples are not in the JSON-scalar allow-list.
            bad_metadata = {EXTERNAL_OPINION_MARKER: True, "bad": (1, 2, 3)}
            InstitutionalRecommendationProposal(
                instrument_id=_iid("alpha"),
                symbol="510300",
                exchange="SSE",
                channel_key=INSTITUTIONAL_CHANNEL_KEY,
                channel_version=INSTITUTIONAL_CHANNEL_VERSION,
                decision="include",
                normalized_score=Decimal("80"),
                confidence=Decimal("0.8"),
                reasons=("institutional.rating:recommended",),
                evidence_refs=("ref",),
                published_at=_PUBLISHED_AT,
                valid_until=_VALID_UNTIL,
                metadata=bad_metadata,  # type: ignore[arg-type]
            )

    def test_proposal_rejects_channel_key_mismatch(self) -> None:
        with pytest.raises(InstitutionChannelResultInvariantError, match="channel_key"):
            InstitutionalRecommendationProposal(
                instrument_id=_iid("alpha"),
                symbol="510300",
                exchange="SSE",
                channel_key="wrong_key",
                channel_version=INSTITUTIONAL_CHANNEL_VERSION,
                decision="include",
                normalized_score=Decimal("80"),
                confidence=Decimal("0.8"),
                reasons=("institutional.rating:recommended",),
                evidence_refs=("ref",),
                published_at=_PUBLISHED_AT,
                valid_until=_VALID_UNTIL,
            )


def _proposal_for(label: str) -> InstitutionalRecommendationProposal:
    return InstitutionalRecommendationProposal(
        instrument_id=_iid(label),
        symbol=label,
        exchange="SSE",
        channel_key=INSTITUTIONAL_CHANNEL_KEY,
        channel_version=INSTITUTIONAL_CHANNEL_VERSION,
        decision="include",
        normalized_score=Decimal("80"),
        confidence=Decimal("0.8"),
        reasons=("institutional.rating:recommended",),
        evidence_refs=("ref",),
        published_at=_PUBLISHED_AT,
        valid_until=_VALID_UNTIL,
        metadata={
            EXTERNAL_OPINION_MARKER: True,
            "channel_source_key": _SOURCE_KEY,
            "source_ref": _SOURCE_REF,
            "recommendation_level": "recommended",
            "eligibility": "full",
            "decision": "include",
            "original_score": Decimal("4"),
            "original_scale": "1-5",
            "reason_summary": "宽基配置价值提升",
        },
    )


# ---------------------------------------------------------------------------
# Coverage / shape
# ---------------------------------------------------------------------------


class TestProposalShape:
    def test_proposal_carries_audit_fields_and_marker(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        batch = _batch((_recommendation(symbol="510300", reason="宽基配置价值提升"),))
        result = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        proposal = result.proposals[0]
        assert proposal.symbol == "510300"
        assert proposal.exchange == "SSE"
        assert proposal.published_at == _PUBLISHED_AT
        assert proposal.valid_until == _VALID_UNTIL
        assert proposal.metadata["channel_source_key"] == _SOURCE_KEY
        assert proposal.metadata["recommendation_level"] == "recommended"
        assert proposal.metadata["reason_summary"] == "宽基配置价值提升"
        assert proposal.metadata["original_score"] == Decimal("4")
        assert proposal.metadata["original_scale"] == "1-5"
        assert proposal.metadata[EXTERNAL_OPINION_MARKER] is True
        # All evidence refs are non-empty strings.
        assert all(isinstance(ref, str) and ref for ref in proposal.evidence_refs)
        assert any(ref.startswith("institution.source_ref:") for ref in proposal.evidence_refs)
        assert any(ref.startswith("institution.source_key:") for ref in proposal.evidence_refs)

    def test_no_buy_sell_signal_field_in_any_proposal_metadata(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        batch = _batch(
            (
                _recommendation(symbol="510300", level=RecommendationLevel.POSITIVE),
                _recommendation(symbol="510500", level=RecommendationLevel.RECOMMENDED),
            )
        )
        result = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        forbidden_metadata_keys = {
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
        pattern = re.compile(r"^(buy|sell|stance|signal|action|position|target_price)$")
        for proposal in result.proposals:
            for key in proposal.metadata:
                assert key not in forbidden_metadata_keys
                assert not pattern.match(key)

    def test_decision_counters_sum_to_proposal_count(self) -> None:
        instruments, bars, mapping = _two_etf_fixture()
        batch = _batch(
            (
                _recommendation(symbol="510300", level=RecommendationLevel.POSITIVE),
                _recommendation(symbol="510500", level=RecommendationLevel.RECOMMENDED),
            )
        )
        result = evaluate_institutional_recommendation_channel(
            instruments=instruments,
            bars_by_instrument=bars,
            batch=batch,
            allowed_source_keys=frozenset({_SOURCE_KEY}),
            as_of_datetime=_AS_OF_DATETIME,
            symbol_to_instrument=mapping,
        )
        assert (
            result.include_count
            + result.watch_count
            + result.exclude_count
            + result.no_opinion_count
            == len(result.proposals)
        )


@pytest.fixture(autouse=True)
def _clear_lru_caches() -> Iterator[None]:
    """Defensive teardown — the channel module deliberately has no lru_cache,
    but we keep this fixture present so future contributors do not have
    to remember to re-seed determinism between tests."""

    yield
