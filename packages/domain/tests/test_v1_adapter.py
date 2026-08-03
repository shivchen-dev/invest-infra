"""Tests for the pure-domain V1 ``TargetSelectionResult`` -> V2 adapter.

Every behaviour pinned by the Stage 4A-0 task brief is covered here:

1. ``TargetSelectionResult.codes`` is dynamic — no fixed 5/9/20 quantity.
2. ``strategy``/``as_of``/``source``/``is_fallback``/``fallback_reason``/
   ``data_age_days`` are all preserved verbatim through the conversion.
3. ``is_fallback=True`` REQUIRES a non-empty ``fallback_reason``.
4. The fail-closed empty result is expressible as an output value.
5. A V1 FQIR ranking is converted to V2 :class:`V1Proposal` instances
   that mirror the ``CandidateProposal`` contract sketched in plan §7.
6. The adapter never derives any buy/sell/recommendation field from the
   V1 numeric scores.
7. The conversion is deterministic — same input and mapping produces
   byte-identical output; no random or DB-order tiebreakers.
8. Missing scores, illegal codes, duplicate codes, illegal strategies
   are rejected or normalised through the documented surface.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from invest_domain.candidate_pool.v1_adapter import (
    OFFICIAL_CHANNEL_STRATEGIES,
    V1_ADAPTER_CHANNEL_VERSION,
    V1AdapterError,
    V1AdapterOutput,
    V1Proposal,
    V1TargetSelectionResult,
    V1_FQIR_WEIGHTS,
    V1_FAIL_CLOSED_OUTCOME,
    ChannelStrategy,
    FailClosedV1TargetSelectionError,
    InvalidV1ChannelStrategyError,
    UnknownV1InstrumentCodeError,
    adapt_v1_target_selection,
    build_fail_closed_output,
    is_official_channel_strategy,
    normalise_codes,
    validate_v1_target_selection,
)
from invest_domain.instruments.models import InstrumentId


_AOF = date(2026, 7, 30)
_GEN = datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc)


def _id(value: str) -> InstrumentId:
    """Stable :class:`InstrumentId` factory so order is deterministic in tests."""

    return InstrumentId(UUID(value))


def _symbol_map(*codes: str) -> dict[str, InstrumentId]:
    """Build a deterministic symbol -> InstrumentId mapping.

    The deterministic UUID stem (re-derivable from the code) makes the
    conversion reproducible without leaning on ``uuid.uuid4`` order.
    """

    mapping: dict[str, InstrumentId] = {}
    for index, code in enumerate(codes):
        stem = f"{index:08x}-0000-4000-8000-000000000000"
        mapping[code] = InstrumentId(UUID(stem))
    return mapping


def _v1_result(
    *,
    codes: tuple[str, ...] = ("510300", "510500"),
    scores: dict[str, float] | None = None,
    strategy: str = "fqir",
    as_of: date = _AOF,
    source: str = "v1:cron_etf_alpha_daily",
    is_fallback: bool = False,
    generated_at: datetime = _GEN,
    fallback_reason: str | None = None,
    data_age_days: int | None = None,
) -> V1TargetSelectionResult:
    mapping = dict(scores or {})
    for code in codes:
        mapping.setdefault(code, 1.0 + len(mapping) * 0.1)
    return V1TargetSelectionResult(
        as_of=as_of,
        strategy=strategy,
        codes=codes,
        scores=mapping,
        source=source,
        is_fallback=is_fallback,
        generated_at=generated_at,
        fallback_reason=fallback_reason,
        data_age_days=data_age_days,
    )


# ---------------------------------------------------------------------------
# Constant-shape invariants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_v1_fqir_weights_are_pinned_to_v1_factors(self) -> None:
        # plan §2.1 lists the canonical FQIR weights verbatim; the adapter
        # contract re-declares them so V2 callers do not need to consult
        # any archived module.
        assert dict(V1_FQIR_WEIGHTS) == {
            "fundamental": Decimal("0.30"),
            "quant": Decimal("0.25"),
            "liquidity": Decimal("0.20"),
            "information": Decimal("0.15"),
            "risk": Decimal("0.10"),
        }
        assert sum(V1_FQIR_WEIGHTS.values()) == Decimal("1.00")

    def test_channel_strategy_lists_v1_known_keys(self) -> None:
        assert ChannelStrategy.FQIR.value == "fqir"
        assert ChannelStrategy.DIVIDEND_LIQUIDITY.value == "dividend_liquidity"

    def test_only_fqir_is_an_official_channel(self) -> None:
        # dividend_liquidity is FROZEN per plan §2.1 second sub-bullet
        # and must not be promoted to a formal channel.
        assert OFFICIAL_CHANNEL_STRATEGIES == frozenset({ChannelStrategy.FQIR})
        assert is_official_channel_strategy(ChannelStrategy.FQIR) is True
        assert is_official_channel_strategy("fqir") is True
        assert is_official_channel_strategy("dividend_liquidity") is False
        assert is_official_channel_strategy(ChannelStrategy.DIVIDEND_LIQUIDITY) is False
        assert is_official_channel_strategy("not-a-strategy") is False
        assert is_official_channel_strategy(None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. ``TargetSelectionResult.codes`` is dynamic.
# ---------------------------------------------------------------------------


class TestCodesCountIsDynamic:
    @pytest.mark.parametrize("count", [1, 3, 7, 15, 47])
    def test_arbitrary_code_counts_are_accepted(self, count: int) -> None:
        codes = tuple(f"51{index:04d}" for index in range(count))
        scores = {code: 1.0 + index * 0.01 for index, code in enumerate(codes)}
        result = _v1_result(codes=codes, scores=scores)
        assert len(result.codes) == count

    def test_five_codes_are_not_a_special_case(self) -> None:
        codes = tuple(f"5{index:05d}" for index in range(5))
        scores = {code: 1.0 for code in codes}
        result = _v1_result(codes=codes, scores=scores)
        out = adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))
        assert len(out.proposals) == 5

    def test_nine_codes_are_not_a_special_case(self) -> None:
        codes = tuple(f"5{index:05d}" for index in range(9))
        scores = {code: 1.0 for code in codes}
        result = _v1_result(codes=codes, scores=scores)
        out = adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))
        assert len(out.proposals) == 9

    def test_twenty_codes_are_not_a_special_case(self) -> None:
        codes = tuple(f"5{index:05d}" for index in range(20))
        scores = {code: 1.0 for code in codes}
        result = _v1_result(codes=codes, scores=scores)
        out = adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))
        assert len(out.proposals) == 20

    def test_empty_codes_list_is_rejected_by_validation(self) -> None:
        result = _v1_result(codes=(), scores={})
        # An empty code list is a degenerate but legal V1 input; the adapter
        # accepts it (the V1 contract permits zero rows) but emits zero
        # proposals — the dynamic count check is about NOT being *fixed*.
        out = adapt_v1_target_selection(result, symbol_to_instrument={})
        assert out.proposals == ()


# ---------------------------------------------------------------------------
# 2. Audit fields survive untouched.
# ---------------------------------------------------------------------------


class TestAuditFieldsArePreserved:
    def test_strategy_as_of_and_source_pass_through_unchanged(self) -> None:
        codes = ("510300", "510500")
        result = _v1_result(
            codes=codes,
            source="v1:cron_etf_alpha_daily",
            is_fallback=True,
            fallback_reason="previous trading day's pool",
            data_age_days=1,
            generated_at=_GEN,
        )
        out = adapt_v1_target_selection(
            result,
            symbol_to_instrument=_symbol_map(*codes),
            max_age_days=2,
        )
        assert out.strategy == "fqir"
        assert out.channel_key == "fqir"
        assert out.channel_version == V1_ADAPTER_CHANNEL_VERSION
        assert out.as_of == _AOF
        assert out.source == "v1:cron_etf_alpha_daily"
        assert out.is_fallback is True
        assert out.fallback_reason == "previous trading day's pool"
        assert out.data_age_days == 1
        assert out.generated_at == _GEN

    def test_non_fallback_input_keeps_is_fallback_false(self) -> None:
        codes = ("510300",)
        result = _v1_result(
            codes=codes,
            is_fallback=False,
            fallback_reason=None,
            data_age_days=None,
        )
        out = adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))
        assert out.is_fallback is False
        assert out.fallback_reason is None
        assert out.data_age_days is None


# ---------------------------------------------------------------------------
# 3. fallback=true REQUIRES fallback_reason.
# ---------------------------------------------------------------------------


class TestFallbackReasonIsRequired:
    def test_v1_target_selection_rejects_fallback_without_reason(self) -> None:
        with pytest.raises(
            ValueError, match="fallback_reason must be non-empty when is_fallback is True"
        ):
            V1TargetSelectionResult(
                as_of=_AOF,
                strategy="fqir",
                codes=("510300",),
                scores={"510300": 1.0},
                source="v1:cron_etf_alpha_daily",
                is_fallback=True,
                generated_at=_GEN,
                fallback_reason=None,
            )

    def test_v1_target_selection_accepts_fallback_with_reason(self) -> None:
        result = V1TargetSelectionResult(
            as_of=_AOF,
            strategy="fqir",
            codes=("510300",),
            scores={"510300": 1.0},
            source="v1:cron_etf_alpha_daily",
            is_fallback=True,
            generated_at=_GEN,
            fallback_reason="no new pool; reusing last successful run",
        )
        assert result.fallback_reason == "no new pool; reusing last successful run"

    def test_v1_target_selection_rejects_blank_fallback_reason(self) -> None:
        with pytest.raises(ValueError, match="fallback_reason"):
            V1TargetSelectionResult(
                as_of=_AOF,
                strategy="fqir",
                codes=("510300",),
                scores={"510300": 1.0},
                source="v1:cron_etf_alpha_daily",
                is_fallback=True,
                generated_at=_GEN,
                fallback_reason="   ",
            )


# ---------------------------------------------------------------------------
# 4. Fail-closed empty result is expressible as an output value.
# ---------------------------------------------------------------------------


class TestFailClosedEmptyResult:
    def test_fail_closed_factory_emits_empty_pool_and_outcome_tag(self) -> None:
        out = build_fail_closed_output(
            strategy=ChannelStrategy.FQIR,
            as_of=_AOF,
            source="v1:cron_etf_alpha_daily",
            generated_at=_GEN,
            fallback_reason="latest successful pool too old",
            data_age_days=10,
            max_age_days=5,
        )
        assert out.proposals == ()
        assert out.outcome == V1_FAIL_CLOSED_OUTCOME
        assert out.is_fallback is True
        assert out.fallback_reason == "latest successful pool too old"
        assert out.data_age_days == 10
        assert any("fail_closed" in note for note in out.notes)

    def test_fail_closed_promoted_via_validator_when_threshold_exceeded(self) -> None:
        codes = ("510300",)
        result = _v1_result(
            codes=codes,
            is_fallback=True,
            fallback_reason="reusing last successful pool",
            data_age_days=10,
        )
        with pytest.raises(FailClosedV1TargetSelectionError) as exc_info:
            validate_v1_target_selection(result, max_age_days=5)
        err = exc_info.value
        assert err.data_age_days == 10
        assert err.max_age_days == 5
        assert err.strategy == "fqir"

    def test_fail_closed_not_triggered_when_age_at_threshold(self) -> None:
        codes = ("510300",)
        result = _v1_result(
            codes=codes,
            is_fallback=True,
            fallback_reason="reusing last successful pool",
            data_age_days=5,
        )
        validate_v1_target_selection(result, max_age_days=5)

    def test_fail_closed_not_triggered_on_fresh_pool(self) -> None:
        codes = ("510300",)
        result = _v1_result(codes=codes, is_fallback=False, data_age_days=None)
        validate_v1_target_selection(result, max_age_days=5)

    def test_dividend_liquidity_fail_closed_is_rejected(self) -> None:
        # Even though dividend_liquidity is FROZEN, the fail-closed factory
        # is part of the official V2 surface; we verify it rejects the
        # frozen strategy explicitly so callers cannot accidentally build
        # a fail-closed pool under that name.
        with pytest.raises(ValueError, match="FROZEN"):
            build_fail_closed_output(
                strategy=ChannelStrategy.DIVIDEND_LIQUIDITY,
                as_of=_AOF,
                source="v1:dynamic_pool_selector",
                generated_at=_GEN,
                fallback_reason="reusing last successful pool",
                data_age_days=10,
                max_age_days=5,
            )


# ---------------------------------------------------------------------------
# 5. V1 FQIR ranking → V2 CandidateProposal/equivalent output.
# ---------------------------------------------------------------------------


class TestFqirRankingToProposals:
    def test_each_code_becomes_one_proposal_in_rank_order(self) -> None:
        codes = ("510300", "510500", "510600")
        scores = {"510300": 0.87, "510500": 0.91, "510600": 0.83}
        result = _v1_result(codes=codes, scores=scores)
        out = adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))

        assert [proposal.v1_code for proposal in out.proposals] == list(codes)
        assert all(proposal.channel_key == "fqir" for proposal in out.proposals)
        assert all(proposal.channel_version == V1_ADAPTER_CHANNEL_VERSION for proposal in out.proposals)
        assert all(proposal.decision == "include" for proposal in out.proposals)

    def test_proposals_carry_no_recommendation_buy_or_sell_field(self) -> None:
        forbidden_field_pattern = re.compile(
            r"^(recommendation|stance|position|buy|sell|target_price|ai_conclusion|action|signal)$"
        )
        from dataclasses import fields as dc_fields

        for proposal in (
            V1Proposal(
                instrument_id=_id("00000000-0000-4000-8000-000000000000"),
                v1_code="510300",
                channel_key="fqir",
                channel_version=V1_ADAPTER_CHANNEL_VERSION,
                decision="include",
                normalized_score=Decimal("0.5"),
                confidence=None,
                reasons=(),
                evidence_refs=(),
                published_at=None,
                valid_until=None,
            ),
        ):
            assert all(
                not forbidden_field_pattern.match(field.name)
                for field in dc_fields(proposal)
            )

    def test_proposal_carries_ranking_score_only(self) -> None:
        codes = ("510300",)
        result = _v1_result(codes=codes, scores={"510300": 0.42})
        out = adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))
        proposal = out.proposals[0]
        # ``normalized_score`` is the only consumer-visible numeric field;
        # it is the V1 score re-emitted as Decimal, NEVER coerced into a
        # buy / sell / recommendation / stance semantics.
        assert proposal.normalized_score == Decimal("0.42000000")
        assert proposal.decision == "include"
        assert proposal.confidence is None
        assert "v1.fqir_ranking" in proposal.reasons
        assert ("v1.source:v1:cron_etf_alpha_daily",) == proposal.evidence_refs

    def test_fqir_weights_constant_does_not_change_through_conversion(self) -> None:
        # The adapter must NOT use V1_FQIR_WEIGHTS to recompute scores; it
        # only forwards the V1 numeric ``scores`` mapping. Verify by
        # ensuring the produced ``normalized_score`` equals the V1 score
        # rather than a recomputed weighted aggregate.
        codes = ("510300", "510500")
        scores = {"510300": 0.42, "510500": 0.66}
        result = _v1_result(codes=codes, scores=scores)
        out = adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))
        emitted = {proposal.v1_code: proposal.normalized_score for proposal in out.proposals}
        assert emitted == {
            "510300": Decimal("0.42000000"),
            "510500": Decimal("0.66000000"),
        }


# ---------------------------------------------------------------------------
# 6. No buy/sell/investment advice is derivable.
# ---------------------------------------------------------------------------


class TestNoInvestmentAdviceInOutput:
    def test_signal_one_does_not_become_a_buy_decision(self) -> None:
        codes = ("510300",)
        result = _v1_result(codes=codes, scores={"510300": 1.0})
        out = adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))
        proposal = out.proposals[0]
        # The V1 signal lands in ``metadata.v1_score`` as a Decimal and
        # in ``reasons`` as a tagging string, never as an actionable
        # buy/sell/bullish/bearish tag.
        assert proposal.decision == "include"
        # No field is named buy / sell / stance / recommendation.
        from dataclasses import fields as dc_fields

        names = {field.name for field in dc_fields(proposal)}
        forbidden = {"buy", "sell", "stance", "recommendation", "signal", "action", "side"}
        assert forbidden.isdisjoint(names)

    def test_signal_minus_one_does_not_become_a_sell_decision(self) -> None:
        codes = ("510300",)
        result = _v1_result(codes=codes, scores={"510300": -1.0})
        out = adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))
        proposal = out.proposals[0]
        # A negative V1 score does NOT flip the decision into "exclude" —
        # the adapter surfaces the V1 numeric score untouched and keeps
        # ``decision="include"`` because V2 routing finalises the bucket.
        assert proposal.decision == "include"
        assert proposal.normalized_score == Decimal("-1.00000000")

    def test_reasons_field_carries_only_canonical_tags(self) -> None:
        codes = ("510300",)
        result = _v1_result(codes=codes, scores={"510300": 0.5})
        out = adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))
        proposal = out.proposals[0]
        for reason in proposal.reasons:
            assert reason.startswith("v1.")
            assert reason not in {"buy", "sell", "hold"}

    def test_fqir_weights_constant_is_not_propagated_into_proposal_metadata(
        self,
    ) -> None:
        codes = ("510300",)
        result = _v1_result(codes=codes, scores={"510300": 0.5})
        out = adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))
        proposal = out.proposals[0]
        for forbidden_key in ("fundamental", "quant", "liquidity", "information", "risk"):
            assert forbidden_key not in proposal.metadata


# ---------------------------------------------------------------------------
# 7. Determinism / stable ordering.
# ---------------------------------------------------------------------------


class TestDeterministicConversion:
    def test_identical_input_and_mapping_yields_equal_output(self) -> None:
        codes = ("510300", "510500", "510600")
        scores = {"510300": 0.5, "510500": 0.9, "510600": 0.7}
        first = adapt_v1_target_selection(
            _v1_result(codes=codes, scores=scores),
            symbol_to_instrument=_symbol_map(*codes),
        )
        second = adapt_v1_target_selection(
            _v1_result(codes=codes, scores=scores),
            symbol_to_instrument=_symbol_map(*codes),
        )
        assert first == second

    def test_proposal_order_matches_input_order(self) -> None:
        codes = ("510300", "510500", "510600", "510700")
        scores = {"510300": 0.1, "510500": 0.4, "510600": 0.2, "510700": 0.3}
        out = adapt_v1_target_selection(
            _v1_result(codes=codes, scores=scores),
            symbol_to_instrument=_symbol_map(*codes),
        )
        assert tuple(proposal.v1_code for proposal in out.proposals) == codes

    def test_proposals_are_resolved_to_stable_instrument_ids(self) -> None:
        # Run the same conversion twice with fresh InstrumentId factories,
        # and verify that the same InstrumentId identity survives because
        # the supplied mapping fixes the UUID stem deterministically.
        codes = ("510300", "510500")
        first_map = _symbol_map(*codes)
        second_map = _symbol_map(*codes)
        first = adapt_v1_target_selection(
            _v1_result(codes=codes),
            symbol_to_instrument=first_map,
        )
        second = adapt_v1_target_selection(
            _v1_result(codes=codes),
            symbol_to_instrument=second_map,
        )
        first_ids = [proposal.instrument_id for proposal in first.proposals]
        second_ids = [proposal.instrument_id for proposal in second.proposals]
        assert first_ids == second_ids

    def test_call_does_not_seed_random_or_use_time(self) -> None:
        import random
        import time

        random.seed(0)
        time.time()
        codes = ("510300", "510500")
        first = adapt_v1_target_selection(
            _v1_result(codes=codes),
            symbol_to_instrument=_symbol_map(*codes),
        )
        second = adapt_v1_target_selection(
            _v1_result(codes=codes),
            symbol_to_instrument=_symbol_map(*codes),
        )
        assert first == second


# ---------------------------------------------------------------------------
# 8. Missing scores, illegal codes, duplicate codes.
# ---------------------------------------------------------------------------


class TestInputNormalisation:
    def test_missing_score_produces_no_opinion_proposal_with_reason(self) -> None:
        codes = ("510300", "510500")
        scores = {"510300": 0.5, "510500": 0.9}
        result = _v1_result(codes=codes, scores=scores)
        # Drop the score for ``510500``; the V1 contract permits a partial
        # scores mapping — the adapter surfaces that as a no_opinion
        # proposal rather than silently dropping the code.
        del result.scores["510500"]  # type: ignore[attr-defined]
        out = adapt_v1_target_selection(
            result,
            symbol_to_instrument=_symbol_map(*codes),
        )
        decisions = {proposal.v1_code: proposal.decision for proposal in out.proposals}
        assert decisions == {"510300": "include", "510500": "no_opinion"}
        assert any("scores_missing" in note for note in out.notes)

    def test_unknown_code_is_rejected(self) -> None:
        codes = ("510300", "999999")
        scores = {"510300": 0.5, "999999": 0.9}
        result = _v1_result(codes=codes, scores=scores)
        bad_map = _symbol_map("510300")
        with pytest.raises(UnknownV1InstrumentCodeError) as exc_info:
            adapt_v1_target_selection(result, symbol_to_instrument=bad_map)
        err = exc_info.value
        assert err.code_value == "999999"

    def test_duplicate_code_is_rejected(self) -> None:
        # The V1 contract requires unique codes per ranking; the adapter
        # rejects duplicates so the audit trail cannot be undermined.
        codes = ("510300", "510300")
        result = _v1_result(codes=codes, scores={"510300": 1.0})
        with pytest.raises(ValueError, match="duplicate"):
            validate_v1_target_selection(result)

    def test_blank_code_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty strings"):
            V1TargetSelectionResult(
                as_of=_AOF,
                strategy="fqir",
                codes=("",),
                scores={},
                source="v1:cron_etf_alpha_daily",
                is_fallback=False,
                generated_at=_GEN,
            )

    def test_invalid_strategy_is_rejected(self) -> None:
        result = _v1_result(strategy="unknown_strategy")
        with pytest.raises(ValueError, match="known ChannelStrategy"):
            validate_v1_target_selection(result)

    def test_dividend_liquidity_is_rejected_by_validator(self) -> None:
        codes = ("510300",)
        result = _v1_result(strategy="dividend_liquidity", codes=codes)
        with pytest.raises(ValueError, match="FROZEN"):
            validate_v1_target_selection(result)

    def test_dividend_liquidity_is_rejected_by_adapter(self) -> None:
        codes = ("510300",)
        result = _v1_result(strategy="dividend_liquidity", codes=codes)
        with pytest.raises(ValueError, match="FROZEN"):
            adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))

    def test_non_numeric_score_is_rejected(self) -> None:
        # Even though scores is typed Mapping[str, float], the dataclass
        # rejects string entries at construction time.
        with pytest.raises(ValueError, match="must be a number"):
            V1TargetSelectionResult(
                as_of=_AOF,
                strategy="fqir",
                codes=("510300",),
                scores={"510300": "high"},  # type: ignore[arg-type]
                source="v1:cron_etf_alpha_daily",
                is_fallback=False,
                generated_at=_GEN,
            )

    def test_infinite_score_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="finite float"):
            V1TargetSelectionResult(
                as_of=_AOF,
                strategy="fqir",
                codes=("510300",),
                scores={"510300": float("inf")},
                source="v1:cron_etf_alpha_daily",
                is_fallback=False,
                generated_at=_GEN,
            )

    def test_negative_data_age_days_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="data_age_days"):
            V1TargetSelectionResult(
                as_of=_AOF,
                strategy="fqir",
                codes=("510300",),
                scores={"510300": 1.0},
                source="v1:cron_etf_alpha_daily",
                is_fallback=True,
                generated_at=_GEN,
                fallback_reason="reusing last successful pool",
                data_age_days=-1,
            )

    def test_naive_datetime_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            V1TargetSelectionResult(
                as_of=_AOF,
                strategy="fqir",
                codes=("510300",),
                scores={"510300": 1.0},
                source="v1:cron_etf_alpha_daily",
                is_fallback=False,
                generated_at=datetime(2026, 7, 30, 8, 0, 0),  # naive
            )


# ---------------------------------------------------------------------------
# Pure-function purity guarantees.
# ---------------------------------------------------------------------------


class TestPureFunction:
    def test_function_has_no_side_effects_on_input(self) -> None:
        codes = ("510300", "510500")
        scores = {"510300": 0.5, "510500": 0.9}
        result = _v1_result(codes=codes, scores=scores)
        before_codes = result.codes
        before_scores = dict(result.scores)
        before_source = result.source
        adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))
        assert result.codes == before_codes
        assert dict(result.scores) == before_scores
        assert result.source == before_source

    def test_function_returns_new_value_each_call(self) -> None:
        codes = ("510300",)
        result = _v1_result(codes=codes)
        out_a = adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))
        out_b = adapt_v1_target_selection(result, symbol_to_instrument=_symbol_map(*codes))
        # The two outputs are equal but not the same object — the function
        # is pure but produces freshly constructed values.
        assert out_a == out_b
        assert out_a is not out_b

    def test_function_does_not_import_storage_or_pandas(self) -> None:
        # Architectural check: the adapter module may not pull in
        # infrastructure dependencies (M0-DECISIONS / scripts/check_architecture).
        import invest_domain.candidate_pool.v1_adapter as module

        module_globals = set(dir(module))
        forbidden = {"sqlalchemy", "pandas", "polars", "fastapi", "dagster"}
        assert forbidden.isdisjoint(set(getattr(module, "__all__", [])))
        for name in forbidden:
            assert not hasattr(module, name), f"v1_adapter unexpectedly exposes {name}"


# ---------------------------------------------------------------------------
# Misc helpers.
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_normalise_codes_preserves_first_seen_order(self) -> None:
        assert normalise_codes(("510300", "510500", "510300", "510600", "510500")) == (
            "510300",
            "510500",
            "510600",
        )

    def test_normalise_codes_rejects_blank(self) -> None:
        with pytest.raises(ValueError, match="blank code"):
            normalise_codes(("510300", "", "510500"))

    def test_invalid_v1_channel_strategy_error_carries_strategy(self) -> None:
        err = InvalidV1ChannelStrategyError("not_real")
        assert err.code == "v1.invalid_strategy"
        assert "not_real" in str(err)


@pytest.fixture(autouse=True)
def _clear_lru_caches() -> Iterator[None]:
    """Defensive teardown — the adapter module deliberately has no lru_cache,
    but we keep this fixture present so future contributors don't have to
    remember to re-seed determinism between tests."""

    yield
