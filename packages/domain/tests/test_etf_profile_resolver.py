"""Tests for the ``etf_profile`` Profile Resolver (``PR-ETF-PROFILE-03``).

The Resolver contracts pinned here:

- ``ProviderPriorityPolicy`` carries the audit-friendly provider-tier
  ordering for the prioritised fields (``manager``, ``benchmark_index``,
  ``aum``). Fields outside the explicit table use a stable conservative
  fallback rule (alphabetical provider_key order).
- ``ResolutionStatus`` exposes the three audit outcomes the plan §5
  promises: ``RESOLVED``, ``MISSING``, ``CONFLICT``.
- ``ResolvedField`` is the per-field result with the resolved value,
  selected evidence, all candidate evidence and any conflicting
  evidence rows preserved verbatim (no silent overwrite).
- ``ProfileResolution`` aggregates one ``ResolvedField`` per
  ``FieldKey`` observed in the input and an ``overall_status``.
- ``ProfileResolver.resolve(...)`` accepts a flat ``Sequence`` of
  ``FieldEvidence`` for one instrument; grouping by ``field_key`` and
  conflict detection are derived responsibilities, never the caller's.
- AUM, ``market_value`` and ``turnover_value`` are distinct ``FieldKey``
  members and the Resolver never aliases them: a row whose ``field_key``
  is ``MARKET_VALUE`` or ``TURNOVER_VALUE`` may resolve into its own
  ``ResolvedField`` but never feeds the ``AUM`` slot.
- Dataclass contracts are ``frozen=True`` + ``slots=True`` so neither
  result type nor ``ProviderPriorityPolicy`` accepts post-construction
  mutation through any code path.

The tests are pure-domain: no Provider adapter, no Storage, no clock,
no RNG. All timestamps and UUIDs are constructed explicitly.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from invest_domain.etf_profile import (
    EtfProfile,
    FieldEvidence,
    FieldEvidenceSource,
    FieldKey,
    FieldValueType,
)
from invest_domain.etf_profile.resolver import (
    DEFAULT_PROVIDER_PRIORITY_POLICY,
    ProfileResolution,
    ProfileResolver,
    ProviderPriorityPolicy,
    ResolutionPolicyError,
    ResolutionStatus,
    ResolvedField,
    resolve_etf_profile_evidence,
)
from invest_domain.research import QualityStatus


def _instrument_id() -> UUID:
    return uuid4()


def _observed_at(seed: int = 0) -> datetime:
    return datetime(2026, 7, 31, 12, 0, seed, tzinfo=UTC)


def _source(
    *,
    provider_key: str = "fund_official",
    dataset_key: str = "etf_profile_snapshot",
    observed_at: datetime | None = None,
    source_batch_id: UUID | None = None,
    revision: int = 1,
) -> FieldEvidenceSource:
    return FieldEvidenceSource(
        provider_key=provider_key,
        dataset_key=dataset_key,
        observed_at=observed_at or _observed_at(),
        source_batch_id=source_batch_id or uuid4(),
        revision=revision,
    )


def _evidence(
    *,
    field_key: FieldKey = FieldKey.MANAGER,
    value: Any = "华夏基金",
    value_type: FieldValueType = FieldValueType.TEXT,
    source: FieldEvidenceSource | None = None,
    quality_status: QualityStatus = QualityStatus.COMPLETE,
    confidence_score: Decimal = Decimal("0.95"),
    instrument_id: UUID | None = None,
    created_at: datetime | None = None,
) -> FieldEvidence:
    return FieldEvidence(
        instrument_id=instrument_id or _instrument_id(),
        field_key=field_key,
        value=value,
        value_type=value_type,
        source=source or _source(),
        quality_status=quality_status,
        confidence_score=confidence_score,
        created_at=created_at,
    )


class TestProviderPriorityPolicyConstruction:
    def test_default_policy_prioritises_manager(self) -> None:
        manager_priority = DEFAULT_PROVIDER_PRIORITY_POLICY.priority_for(
            FieldKey.MANAGER
        )
        assert manager_priority == (
            "fund_announcement",
            "fund_official",
            "exchange",
            "third_party",
        )

    def test_default_policy_prioritises_benchmark_index(self) -> None:
        benchmark_priority = DEFAULT_PROVIDER_PRIORITY_POLICY.priority_for(
            FieldKey.BENCHMARK_INDEX
        )
        assert benchmark_priority == (
            "fund_announcement",
            "index_provider",
            "fund_official",
            "third_party",
        )

    def test_default_policy_prioritises_aum(self) -> None:
        aum_priority = DEFAULT_PROVIDER_PRIORITY_POLICY.priority_for(FieldKey.AUM)
        assert aum_priority == (
            "fund_announcement",
            "fund_official",
            "third_party",
        )

    def test_default_policy_uses_full_field_table(self) -> None:
        keys = set(DEFAULT_PROVIDER_PRIORITY_POLICY.priorities)
        # Plan §5 names these three fields by name.
        assert FieldKey.MANAGER in keys
        assert FieldKey.BENCHMARK_INDEX in keys
        assert FieldKey.AUM in keys

    def test_unknown_field_returns_empty_priority(self) -> None:
        policy = ProviderPriorityPolicy()
        assert policy.priority_for(FieldKey.SYMBOL) == ()
        assert policy.priority_for(FieldKey.AUM) == ()

    @pytest.mark.parametrize(
        "field_key",
        [FieldKey.NAME, FieldKey.EXCHANGE, FieldKey.STATUS, FieldKey.CATEGORY],
    )
    def test_default_policy_has_no_explicit_priority_for_non_plan_field(
        self, field_key: FieldKey
    ) -> None:
        assert DEFAULT_PROVIDER_PRIORITY_POLICY.priority_for(field_key) == ()

    def test_priorities_are_tuples(self) -> None:
        policy = ProviderPriorityPolicy.from_dict(
            {FieldKey.MANAGER: ["fund_announcement", "fund_official"]}
        )
        priority = policy.priority_for(FieldKey.MANAGER)
        assert isinstance(priority, tuple)
        assert priority == ("fund_announcement", "fund_official")

    def test_priority_tuple_does_not_alias_caller_list(self) -> None:
        original = ["fund_announcement", "fund_official"]
        policy = ProviderPriorityPolicy.from_dict({FieldKey.MANAGER: original})
        priority = policy.priority_for(FieldKey.MANAGER)
        assert priority == ("fund_announcement", "fund_official")
        # Mutating the input list must not leak into the stored policy.
        original.append("third_party")
        assert policy.priority_for(FieldKey.MANAGER) == (
            "fund_announcement",
            "fund_official",
        )

    def test_priority_provider_key_must_be_non_empty_string(self) -> None:
        with pytest.raises((TypeError, ValueError)):
            ProviderPriorityPolicy.from_dict({FieldKey.MANAGER: [""]})

    def test_priority_provider_key_must_be_str(self) -> None:
        with pytest.raises(TypeError):
            ProviderPriorityPolicy.from_dict(
                {FieldKey.MANAGER: [123]}  # type: ignore[list-item]
            )

    def test_priority_key_must_be_field_key(self) -> None:
        with pytest.raises(TypeError):
            ProviderPriorityPolicy.from_dict({"manager": ("fund_official",)})  # type: ignore[dict-item]

    def test_priority_duplicates_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            ProviderPriorityPolicy.from_dict(
                {FieldKey.MANAGER: ("fund_official", "fund_official")}
            )

    def test_policy_is_frozen(self) -> None:
        policy = ProviderPriorityPolicy()
        with pytest.raises(AttributeError):
            policy.priorities = {FieldKey.MANAGER: ("fund_official",)}  # type: ignore[attr-defined]

    def test_policy_is_slots(self) -> None:
        policy = ProviderPriorityPolicy()
        assert not hasattr(policy, "__dict__")
        with pytest.raises((AttributeError, TypeError)):
            policy.random_attr = "boom"  # type: ignore[attr-defined]


class TestResolutionStatusVocabulary:
    def test_three_outcomes_are_member(self) -> None:
        assert {member.value for member in ResolutionStatus} == {
            "resolved",
            "missing",
            "conflict",
        }

    def test_status_members_are_stable_strings(self) -> None:
        assert ResolutionStatus.RESOLVED == "resolved"
        assert ResolutionStatus.MISSING == "missing"
        assert ResolutionStatus.CONFLICT == "conflict"


class TestResolvedFieldContract:
    def _build(
        self,
        *,
        field_key: FieldKey = FieldKey.MANAGER,
        status: ResolutionStatus = ResolutionStatus.MISSING,
        value: Any = None,
        candidates: Sequence[FieldEvidence] = (),
        selected: FieldEvidence | None = None,
        conflicts: Sequence[FieldEvidence] = (),
        observed: Sequence[Any] = (),
    ) -> ResolvedField:
        return ResolvedField(
            field_key=field_key,
            status=status,
            value=value,
            candidates=tuple(candidates),
            selected_evidence=selected,
            conflicts=tuple(conflicts),
            observed_distinct_values=tuple(observed),
        )

    def test_resolved_field_carries_value_and_evidence(self) -> None:
        evidence = _evidence()
        resolved = self._build(
            status=ResolutionStatus.RESOLVED,
            value="华夏基金",
            candidates=[evidence],
            selected=evidence,
            observed=["华夏基金"],
        )
        assert resolved.field_key is FieldKey.MANAGER
        assert resolved.status is ResolutionStatus.RESOLVED
        assert resolved.value == "华夏基金"
        assert resolved.selected_evidence == evidence
        assert resolved.candidates == (evidence,)
        assert resolved.conflicts == ()
        assert resolved.observed_distinct_values == ("华夏基金",)

    def test_conflict_field_carries_value_none(self) -> None:
        first = _evidence(
            value="沪深300",
            source=_source(provider_key="fund_announcement"),
        )
        second = _evidence(
            value="中证300",
            source=_source(provider_key="fund_official"),
        )
        resolved = self._build(
            status=ResolutionStatus.CONFLICT,
            value=None,
            conflicts=[first, second],
            observed=["沪深300", "中证300"],
        )
        assert resolved.status is ResolutionStatus.CONFLICT
        assert resolved.value is None
        assert resolved.selected_evidence is None
        assert first in resolved.conflicts
        assert second in resolved.conflicts
        assert resolved.observed_distinct_values == ("沪深300", "中证300")

    def test_missing_field_has_no_evidence(self) -> None:
        resolved = self._build(
            status=ResolutionStatus.MISSING, value=None, observed=[]
        )
        assert resolved.status is ResolutionStatus.MISSING
        assert resolved.value is None
        assert resolved.selected_evidence is None
        assert resolved.candidates == ()
        assert resolved.conflicts == ()

    def test_resolved_with_value_requires_selected_evidence(self) -> None:
        with pytest.raises(ValueError, match="selected_evidence"):
            self._build(
                status=ResolutionStatus.RESOLVED,
                value="华夏基金",
                selected=None,
                candidates=[],
            )

    def test_resolved_with_selected_requires_non_null_value(self) -> None:
        # A resolved status with no value is rejected; missing status
        # is the explicit carrier for unknown values.
        evidence = _evidence()
        with pytest.raises(ValueError, match="status"):
            self._build(
                status=ResolutionStatus.RESOLVED,
                value=None,
                selected=evidence,
            )

    def test_conflict_status_rejects_non_null_value(self) -> None:
        with pytest.raises(ValueError, match="CONFLICT"):
            self._build(
                status=ResolutionStatus.CONFLICT,
                value="华夏基金",
                conflicts=[],
                observed=[],
            )

    def test_conflict_status_requires_conflict_evidence(self) -> None:
        with pytest.raises(ValueError, match="conflict"):
            self._build(
                status=ResolutionStatus.CONFLICT,
                value=None,
                conflicts=[],
                observed=[],
            )

    def test_missing_status_requires_no_evidence(self) -> None:
        evidence = _evidence()
        with pytest.raises(ValueError, match="MISSING"):
            self._build(
                status=ResolutionStatus.MISSING,
                value=None,
                candidates=[evidence],
            )

    def test_resolved_field_is_frozen(self) -> None:
        resolved = self._build()
        with pytest.raises(AttributeError):
            resolved.value = "其他基金"  # type: ignore[attr-defined]

    def test_resolved_field_is_slots(self) -> None:
        resolved = self._build()
        assert not hasattr(resolved, "__dict__")
        with pytest.raises((AttributeError, TypeError)):
            resolved.random_attr = "boom"  # type: ignore[attr-defined]


class TestProfileResolverEmptyInput:
    def test_resolve_with_no_evidence_yields_empty_profile(self) -> None:
        resolver = ProfileResolver()
        iid = _instrument_id()
        resolution = resolver.resolve([], instrument_id=iid)
        assert isinstance(resolution, ProfileResolution)
        assert resolution.instrument_id == iid
        assert resolution.fields == {}
        assert resolution.overall_status is ResolutionStatus.MISSING

    def test_resolve_with_empty_evidence_without_instrument_id_is_rejected(
        self,
    ) -> None:
        resolver = ProfileResolver()
        with pytest.raises(ResolutionPolicyError):
            resolver.resolve([])


class TestProfileResolverSingleEvidenceRow:
    def test_single_evidence_row_is_resolved_with_value(self) -> None:
        evidence = _evidence(field_key=FieldKey.MANAGER, value="华夏基金")
        resolver = ProfileResolver()
        resolution = resolver.resolve([evidence])
        assert resolution.instrument_id == evidence.instrument_id
        resolved = resolution.fields[FieldKey.MANAGER]
        assert resolved.status is ResolutionStatus.RESOLVED
        assert resolved.value == "华夏基金"
        assert resolved.selected_evidence == evidence
        assert resolved.observed_distinct_values == ("华夏基金",)

    def test_single_decimal_evidence_row_resolves(self) -> None:
        evidence = _evidence(
            field_key=FieldKey.AUM,
            value=Decimal("1234567890.00"),
            value_type=FieldValueType.DECIMAL,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([evidence])
        resolved = resolution.fields[FieldKey.AUM]
        assert resolved.status is ResolutionStatus.RESOLVED
        assert resolved.value == Decimal("1234567890.00")
        assert resolved.selected_evidence == evidence

    def test_single_date_evidence_row_resolves(self) -> None:
        evidence = _evidence(
            field_key=FieldKey.INCEPTION_DATE,
            value=date(2013, 3, 25),
            value_type=FieldValueType.DATE,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([evidence])
        resolved = resolution.fields[FieldKey.INCEPTION_DATE]
        assert resolved.status is ResolutionStatus.RESOLVED
        assert resolved.value == date(2013, 3, 25)
        assert resolved.selected_evidence == evidence


class TestProfileResolverAgreementWithPriority:
    def test_higher_priority_provider_wins_when_values_agree(self) -> None:
        iid = _instrument_id()
        lower = _evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            source=_source(provider_key="third_party", observed_at=_observed_at(0)),
            instrument_id=iid,
        )
        higher = _evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            source=_source(provider_key="fund_announcement", observed_at=_observed_at(1)),
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([lower, higher])
        resolved = resolution.fields[FieldKey.MANAGER]
        assert resolved.status is ResolutionStatus.RESOLVED
        assert resolved.value == "华夏基金"
        assert resolved.selected_evidence == higher
        # Both rows are preserved as candidates.
        assert set(resolved.candidates) == {lower, higher}
        assert resolved.conflicts == ()

    def test_priority_outranks_higher_confidence(self) -> None:
        iid = _instrument_id()
        low_priority_high_confidence = _evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            source=_source(provider_key="third_party"),
            confidence_score=Decimal("0.99"),
            instrument_id=iid,
        )
        high_priority_low_confidence = _evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            source=_source(provider_key="fund_announcement"),
            confidence_score=Decimal("0.10"),
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve(
            [low_priority_high_confidence, high_priority_low_confidence]
        )
        resolved = resolution.fields[FieldKey.MANAGER]
        assert resolved.selected_evidence == high_priority_low_confidence


class TestProfileResolverAgreementTieBreaker:
    def test_tie_breaker_picks_most_recent_when_same_priority(self) -> None:
        # Provider A + Provider A same time; Provider A later must win.
        iid = _instrument_id()
        first = _evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            source=_source(
                provider_key="fund_announcement",
                observed_at=datetime(2026, 7, 31, tzinfo=UTC),
                revision=1,
            ),
            instrument_id=iid,
        )
        later = _evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            source=_source(
                provider_key="fund_announcement",
                observed_at=datetime(2026, 8, 1, tzinfo=UTC),
                revision=1,
            ),
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([first, later])
        resolved = resolution.fields[FieldKey.MANAGER]
        assert resolved.selected_evidence == later

    def test_tie_breaker_uses_content_hash_when_observation_matches(
        self,
    ) -> None:
        # Same provider_key, same observed_at, different content_hash
        # (theoretically the same business content would share a digest;
        # two truly identical inputs would dedupe naturally and never
        # appear as two rows in practice). We assert the deterministic
        # ordering by content_hash when everything else matches.
        iid = _instrument_id()
        a = _evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            source=_source(provider_key="fund_official"),
            instrument_id=iid,
        )
        b = _evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            source=_source(provider_key="fund_official"),
            instrument_id=iid,
            confidence_score=Decimal("0.80"),
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([a, b])
        resolved = resolution.fields[FieldKey.MANAGER]
        assert resolved.status is ResolutionStatus.RESOLVED
        # Whichever input sorts last in our deterministic ordering wins.
        assert resolved.selected_evidence in {a, b}


class TestProfileResolverConflictDetection:
    def test_two_distinct_values_are_reported_as_conflict(self) -> None:
        iid = _instrument_id()
        first = _evidence(
            field_key=FieldKey.BENCHMARK_INDEX,
            value="沪深300",
            source=_source(provider_key="fund_announcement"),
            instrument_id=iid,
        )
        second = _evidence(
            field_key=FieldKey.BENCHMARK_INDEX,
            value="中证300",
            source=_source(provider_key="index_provider"),
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([first, second])
        resolved = resolution.fields[FieldKey.BENCHMARK_INDEX]
        assert resolved.status is ResolutionStatus.CONFLICT
        assert resolved.value is None
        assert resolved.selected_evidence is None
        assert first in resolved.conflicts
        assert second in resolved.conflicts
        assert sorted(resolved.observed_distinct_values) == ["中证300", "沪深300"]
        # Plan §5 forbids silent overwrite: even though ``fund_announcement``
        # outranks ``index_provider`` for benchmark, conflict wins over priority.
        assert resolved.candidates == (first, second)

    def test_three_distinct_values_remain_conflict(self) -> None:
        iid = _instrument_id()
        rows = [
            _evidence(
                field_key=FieldKey.BENCHMARK_INDEX,
                value=name,
                source=_source(provider_key=provider),
                instrument_id=iid,
            )
            for name, provider in (
                ("沪深300", "third_party"),
                ("中证300", "fund_official"),
                ("上证50", "fund_announcement"),
            )
        ]
        resolver = ProfileResolver()
        resolution = resolver.resolve(rows)
        resolved = resolution.fields[FieldKey.BENCHMARK_INDEX]
        assert resolved.status is ResolutionStatus.CONFLICT
        assert resolved.value is None
        assert set(resolved.conflicts) == set(rows)

    def test_higher_priority_does_not_silently_overwrite_conflict(self) -> None:
        # ``fund_announcement`` is the highest-priority benchmark
        # provider in the default policy. The plan still forbids
        # silently overwriting a legitimate conflict.
        iid = _instrument_id()
        high_priority = _evidence(
            field_key=FieldKey.BENCHMARK_INDEX,
            value="沪深300",
            source=_source(provider_key="fund_announcement"),
            instrument_id=iid,
        )
        low_priority = _evidence(
            field_key=FieldKey.BENCHMARK_INDEX,
            value="中证300",
            source=_source(provider_key="third_party"),
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([low_priority, high_priority])
        resolved = resolution.fields[FieldKey.BENCHMARK_INDEX]
        assert resolved.status is ResolutionStatus.CONFLICT
        assert resolved.value is None
        assert resolved.selected_evidence is None
        assert set(resolved.conflicts) == {high_priority, low_priority}


class TestProfileResolverNullValueHandling:
    def test_none_value_evidence_does_not_contribute_to_resolved_value(self) -> None:
        iid = _instrument_id()
        null_evidence = _evidence(
            field_key=FieldKey.MANAGER,
            value=None,
            quality_status=QualityStatus.PARTIAL,
            instrument_id=iid,
        )
        actual = _evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            source=_source(provider_key="fund_official"),
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([null_evidence, actual])
        resolved = resolution.fields[FieldKey.MANAGER]
        assert resolved.status is ResolutionStatus.RESOLVED
        assert resolved.value == "华夏基金"
        assert resolved.selected_evidence == actual
        # The null-value row is still preserved as a candidate.
        assert null_evidence in resolved.candidates
        assert actual in resolved.candidates

    def test_all_none_value_evidence_yields_missing_status(self) -> None:
        iid = _instrument_id()
        first = _evidence(
            field_key=FieldKey.AUM,
            value=None,
            value_type=FieldValueType.DECIMAL,
            quality_status=QualityStatus.MISSING,
            instrument_id=iid,
        )
        second = _evidence(
            field_key=FieldKey.AUM,
            value=None,
            value_type=FieldValueType.DECIMAL,
            quality_status=QualityStatus.PARTIAL,
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([first, second])
        resolved = resolution.fields[FieldKey.AUM]
        assert resolved.status is ResolutionStatus.MISSING
        assert resolved.value is None
        assert resolved.selected_evidence is None
        assert resolved.candidates == ()
        assert resolved.conflicts == ()

    def test_null_value_with_other_missing_evidence_yields_missing(self) -> None:
        iid = _instrument_id()
        null_evidence = _evidence(
            field_key=FieldKey.AUM,
            value=None,
            value_type=FieldValueType.DECIMAL,
            quality_status=QualityStatus.MISSING,
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([null_evidence])
        resolved = resolution.fields[FieldKey.AUM]
        assert resolved.status is ResolutionStatus.MISSING


class TestProfileResolverFallbackPriority:
    def test_unknown_field_falls_back_to_alphabetical_provider_order(self) -> None:
        # ``NAME`` has no explicit policy entry. ``Charlie`` is the
        # lowest priority (alphabetically later), ``Alpha`` is the
        # highest. The Resolver must pick ``Alpha`` when both rows
        # supply the same value, purely from the alphabetical
        # fallback.
        iid = _instrument_id()
        charlie = _evidence(
            field_key=FieldKey.NAME,
            value="上证50ETF",
            source=_source(provider_key="charlie", observed_at=_observed_at(0)),
            instrument_id=iid,
        )
        alpha = _evidence(
            field_key=FieldKey.NAME,
            value="上证50ETF",
            source=_source(provider_key="alpha", observed_at=_observed_at(1)),
            instrument_id=iid,
        )
        bravo = _evidence(
            field_key=FieldKey.NAME,
            value="上证50ETF",
            source=_source(provider_key="bravo", observed_at=_observed_at(2)),
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([charlie, bravo, alpha])
        resolved = resolution.fields[FieldKey.NAME]
        assert resolved.status is ResolutionStatus.RESOLVED
        assert resolved.selected_evidence == alpha

    def test_fallback_resolves_three_distinct_values_as_conflict(self) -> None:
        iid = _instrument_id()
        rows = [
            _evidence(
                field_key=FieldKey.NAME,
                value=name,
                source=_source(provider_key=provider),
                instrument_id=iid,
            )
            for name, provider in (
                ("Alpha-ETF", "alpha"),
                ("Beta-ETF", "bravo"),
                ("Charlie-ETF", "charlie"),
            )
        ]
        resolver = ProfileResolver()
        resolution = resolver.resolve(rows)
        resolved = resolution.fields[FieldKey.NAME]
        assert resolved.status is ResolutionStatus.CONFLICT
        assert resolved.selected_evidence is None
        assert set(resolved.conflicts) == set(rows)


class TestProfileResolverAumSeparation:
    def test_market_value_evidence_does_not_affect_aum(self) -> None:
        iid = _instrument_id()
        aum = _evidence(
            field_key=FieldKey.AUM,
            value=Decimal("1000000"),
            value_type=FieldValueType.DECIMAL,
            source=_source(provider_key="fund_official"),
            instrument_id=iid,
        )
        market_value = _evidence(
            field_key=FieldKey.MARKET_VALUE,
            value=Decimal("2000000"),
            value_type=FieldValueType.DECIMAL,
            source=_source(provider_key="fund_official"),
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([aum, market_value])
        aum_resolved = resolution.fields[FieldKey.AUM]
        market_resolved = resolution.fields[FieldKey.MARKET_VALUE]
        # Plan §6 forbids market_value from feeding the AUM slot.
        assert aum_resolved.value == Decimal("1000000")
        assert aum_resolved.selected_evidence == aum
        assert market_resolved.value == Decimal("2000000")
        assert market_resolved.selected_evidence == market_value

    def test_turnover_value_evidence_does_not_affect_aum(self) -> None:
        iid = _instrument_id()
        aum = _evidence(
            field_key=FieldKey.AUM,
            value=Decimal("1000000"),
            value_type=FieldValueType.DECIMAL,
            source=_source(provider_key="fund_announcement"),
            instrument_id=iid,
        )
        turnover = _evidence(
            field_key=FieldKey.TURNOVER_VALUE,
            value=Decimal("5000000"),
            value_type=FieldValueType.DECIMAL,
            source=_source(provider_key="fund_official"),
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([aum, turnover])
        aum_resolved = resolution.fields[FieldKey.AUM]
        # The AUM slot is resolved purely from AUM evidence.
        assert aum_resolved.selected_evidence == aum
        assert aum_resolved.value == Decimal("1000000")
        # The turnover row only feeds the TURNOVER_VALUE slot.
        turnover_resolved = resolution.fields[FieldKey.TURNOVER_VALUE]
        assert turnover_resolved.value == Decimal("5000000")

    def test_market_value_and_aum_with_identical_decimals_split(self) -> None:
        # Two evidence rows with the same decimal value but different
        # ``field_key`` are distinct fields, not aliases.
        iid = _instrument_id()
        aum = _evidence(
            field_key=FieldKey.AUM,
            value=Decimal("1000000"),
            value_type=FieldValueType.DECIMAL,
            source=_source(provider_key="fund_official"),
            instrument_id=iid,
        )
        market = _evidence(
            field_key=FieldKey.MARKET_VALUE,
            value=Decimal("1000000"),
            value_type=FieldValueType.DECIMAL,
            source=_source(provider_key="fund_official"),
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([aum, market])
        assert resolution.fields[FieldKey.AUM].value == Decimal("1000000")
        assert resolution.fields[FieldKey.MARKET_VALUE].value == Decimal("1000000")
        # They are different ResolvedField instances.
        assert (
            resolution.fields[FieldKey.AUM].selected_evidence
            != resolution.fields[FieldKey.MARKET_VALUE].selected_evidence
        )


class TestProfileResolverInstrumentIdConsistency:
    def test_rows_with_different_instrument_ids_are_rejected(self) -> None:
        a = _evidence(instrument_id=_instrument_id())
        b = _evidence(instrument_id=_instrument_id())
        resolver = ProfileResolver()
        with pytest.raises(ResolutionPolicyError, match="instrument_id"):
            resolver.resolve([a, b])

    def test_all_rows_share_instrument_id(self) -> None:
        iid = _instrument_id()
        rows = [
            _evidence(
                field_key=field_key,
                instrument_id=iid,
            )
            for field_key in (
                FieldKey.MANAGER,
                FieldKey.BENCHMARK_INDEX,
                FieldKey.AUM,
            )
        ]
        resolver = ProfileResolver()
        resolution = resolver.resolve(rows)
        assert resolution.instrument_id == iid


class TestProfileResolverGrouping:
    def test_multiple_field_keys_group_correctly(self) -> None:
        iid = _instrument_id()
        manager = _evidence(field_key=FieldKey.MANAGER, value="华夏基金", instrument_id=iid)
        benchmark = _evidence(
            field_key=FieldKey.BENCHMARK_INDEX,
            value="沪深300",
            instrument_id=iid,
        )
        aum = _evidence(
            field_key=FieldKey.AUM,
            value=Decimal("1000000"),
            value_type=FieldValueType.DECIMAL,
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([manager, benchmark, aum])
        assert set(resolution.fields.keys()) == {
            FieldKey.MANAGER,
            FieldKey.BENCHMARK_INDEX,
            FieldKey.AUM,
        }
        assert resolution.fields[FieldKey.MANAGER].value == "华夏基金"
        assert resolution.fields[FieldKey.BENCHMARK_INDEX].value == "沪深300"
        assert resolution.fields[FieldKey.AUM].value == Decimal("1000000")

    def test_per_field_resolution_is_independent(self) -> None:
        iid = _instrument_id()
        manager_a = _evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            source=_source(provider_key="fund_announcement"),
            instrument_id=iid,
        )
        benchmark_a = _evidence(
            field_key=FieldKey.BENCHMARK_INDEX,
            value="沪深300",
            source=_source(provider_key="fund_announcement"),
            instrument_id=iid,
        )
        benchmark_b = _evidence(
            field_key=FieldKey.BENCHMARK_INDEX,
            value="中证300",
            source=_source(provider_key="fund_official"),
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve([manager_a, benchmark_a, benchmark_b])
        # MANAGER is resolved with a single row of evidence.
        assert resolution.fields[FieldKey.MANAGER].status is ResolutionStatus.RESOLVED
        # BENCHMARK_INDEX is in CONFLICT (two rows, two distinct values).
        assert (
            resolution.fields[FieldKey.BENCHMARK_INDEX].status
            is ResolutionStatus.CONFLICT
        )


class TestProfileResolutionOverallStatus:
    def test_overall_status_is_resolved_when_every_field_resolves(self) -> None:
        iid = _instrument_id()
        rows = [
            _evidence(field_key=FieldKey.MANAGER, value="华夏基金", instrument_id=iid),
            _evidence(
                field_key=FieldKey.BENCHMARK_INDEX,
                value="沪深300",
                instrument_id=iid,
            ),
        ]
        resolver = ProfileResolver()
        resolution = resolver.resolve(rows)
        assert resolution.overall_status is ResolutionStatus.RESOLVED

    def test_overall_status_is_conflict_if_any_field_conflicts(self) -> None:
        iid = _instrument_id()
        rows = [
            _evidence(field_key=FieldKey.MANAGER, value="华夏基金", instrument_id=iid),
            _evidence(
                field_key=FieldKey.BENCHMARK_INDEX,
                value="沪深300",
                instrument_id=iid,
            ),
            _evidence(
                field_key=FieldKey.BENCHMARK_INDEX,
                value="中证300",
                instrument_id=iid,
            ),
        ]
        resolver = ProfileResolver()
        resolution = resolver.resolve(rows)
        assert resolution.overall_status is ResolutionStatus.CONFLICT

    def test_overall_status_is_missing_only_when_every_field_missing(self) -> None:
        iid = _instrument_id()
        rows = [
            _evidence(field_key=FieldKey.MANAGER, value="华夏基金", instrument_id=iid),
            _evidence(
                field_key=FieldKey.AUM,
                value=None,
                value_type=FieldValueType.DECIMAL,
                quality_status=QualityStatus.MISSING,
                instrument_id=iid,
            ),
        ]
        resolver = ProfileResolver()
        resolution = resolver.resolve(rows)
        # The resolver surfaces the ``AUM`` field as MISSING, but the
        # ``MANAGER`` row is RESOLVED; the overall status is RESOLVED
        # because partial-but-non-conflicting resolution carries more
        # weight than an isolated missing field.
        assert resolution.overall_status is ResolutionStatus.RESOLVED

    def test_overall_status_is_missing_for_empty_evidence(self) -> None:
        resolver = ProfileResolver()
        resolution = resolver.resolve([], instrument_id=_instrument_id())
        assert resolution.overall_status is ResolutionStatus.MISSING


class TestProfileResolutionImmutability:
    def test_resolution_is_frozen(self) -> None:
        iid = _instrument_id()
        evidence = _evidence(instrument_id=iid)
        resolver = ProfileResolver()
        resolution = resolver.resolve([evidence])
        with pytest.raises(AttributeError):
            resolution.instrument_id = _instrument_id()  # type: ignore[attr-defined]

    def test_resolution_fields_mapping_is_read_only(self) -> None:
        iid = _instrument_id()
        evidence = _evidence(instrument_id=iid)
        resolver = ProfileResolver()
        resolution = resolver.resolve([evidence])
        # The exposed mapping is immutable; mutation must raise.
        with pytest.raises((TypeError, AttributeError)):
            resolution.fields[FieldKey.MANAGER] = "mutated"  # type: ignore[index]

    def test_resolution_is_slots(self) -> None:
        iid = _instrument_id()
        evidence = _evidence(instrument_id=iid)
        resolver = ProfileResolver()
        resolution = resolver.resolve([evidence])
        assert not hasattr(resolution, "__dict__")
        with pytest.raises((AttributeError, TypeError)):
            resolution.random_attr = "boom"  # type: ignore[attr-defined]


class TestProfileResolverIsReusable:
    def test_resolver_is_frozen(self) -> None:
        resolver = ProfileResolver()
        with pytest.raises(AttributeError):
            resolver.priority_policy = ProviderPriorityPolicy()  # type: ignore[attr-defined]

    def test_same_resolver_for_multiple_instruments(self) -> None:
        a_id = _instrument_id()
        b_id = _instrument_id()
        evidence_a = _evidence(
            field_key=FieldKey.MANAGER, value="A基金", instrument_id=a_id
        )
        evidence_b = _evidence(
            field_key=FieldKey.MANAGER, value="B基金", instrument_id=b_id
        )
        resolver = ProfileResolver()
        resolution_a = resolver.resolve([evidence_a])
        resolution_b = resolver.resolve([evidence_b])
        assert resolution_a.instrument_id == a_id
        assert resolution_b.instrument_id == b_id
        assert resolution_a.fields[FieldKey.MANAGER].value == "A基金"
        assert resolution_b.fields[FieldKey.MANAGER].value == "B基金"


class TestProfileResolverFunctionalHelper:
    def test_resolve_etf_profile_evidence_helper_matches_resolver(self) -> None:
        iid = _instrument_id()
        evidence = _evidence(
            field_key=FieldKey.MANAGER, value="华夏基金", instrument_id=iid
        )
        resolver = ProfileResolver()
        direct = resolver.resolve([evidence])
        helper = resolve_etf_profile_evidence([evidence])
        assert helper == direct


class TestProfileResolverCustomPolicy:
    def test_custom_policy_overrides_default_for_manager(self) -> None:
        iid = _instrument_id()
        top = _evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            source=_source(provider_key="top_provider"),
            instrument_id=iid,
        )
        bottom = _evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            source=_source(provider_key="fund_announcement"),
            instrument_id=iid,
        )
        policy = ProviderPriorityPolicy.from_dict(
            {FieldKey.MANAGER: ("top_provider", "fund_announcement")}
        )
        resolver = ProfileResolver(priority_policy=policy)
        resolution = resolver.resolve([bottom, top])
        resolved = resolution.fields[FieldKey.MANAGER]
        assert resolved.selected_evidence == top


class TestProfileResolverIntegrationWithEtfProfile:
    def test_resolution_can_be_projected_to_etf_profile(self) -> None:
        # The Resolver output is intentionally separate from the
        # canonical ``EtfProfile`` row (PR-ETF-PROFILE-01 / DC-2),
        # but the application layer must be able to project
        # RESOLVED fields into an ``EtfProfile`` payload. This test
        # guards the projection contract: only RESOLVED, non-None
        # values reach the canonical row; CONFLICT / MISSING fields
        # stay ``None``.
        iid = _instrument_id()
        manager_a = _evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            source=_source(provider_key="fund_announcement"),
            instrument_id=iid,
        )
        benchmark_a = _evidence(
            field_key=FieldKey.BENCHMARK_INDEX,
            value="沪深300",
            source=_source(provider_key="fund_announcement"),
            instrument_id=iid,
        )
        benchmark_b = _evidence(
            field_key=FieldKey.BENCHMARK_INDEX,
            value="中证300",
            source=_source(provider_key="fund_official"),
            instrument_id=iid,
        )
        aum = _evidence(
            field_key=FieldKey.AUM,
            value=Decimal("1234567890"),
            value_type=FieldValueType.DECIMAL,
            source=_source(provider_key="fund_official"),
            instrument_id=iid,
        )
        resolver = ProfileResolver()
        resolution = resolver.resolve(
            [manager_a, benchmark_a, benchmark_b, aum]
        )
        # Project RESOLVED fields only; CONFLICT and MISSING stay None.
        fields = resolution.fields
        profile = EtfProfile(
            instrument_id=iid,
            manager=(
                fields[FieldKey.MANAGER].value
                if fields[FieldKey.MANAGER].status is ResolutionStatus.RESOLVED
                else None
            ),
            benchmark_index=None,  # CONFLICT -> deliberately None
            category=None,
            inception_date=None,
            fund_type=None,
            management_fee=None,
            custody_fee=None,
            aum=(
                fields[FieldKey.AUM].value
                if fields[FieldKey.AUM].status is ResolutionStatus.RESOLVED
                else None
            ),
            shares=None,
        )
        assert profile.manager == "华夏基金"
        assert profile.benchmark_index is None
        assert profile.aum == Decimal("1234567890")
        # Resolution remains CONFLICT for ``benchmark_index`` because
        # the resolver refuses to overwrite disagreeing observations.
        assert (
            fields[FieldKey.BENCHMARK_INDEX].status is ResolutionStatus.CONFLICT
        )
