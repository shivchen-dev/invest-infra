"""Tests for the ``etf_profile`` bounded context.

The tests cover two contracts that share the same bounded context:

- Stage DC-2 ``EtfProfile`` (the canonical record per instrument);
- PR-ETF-PROFILE-01 ``FieldEvidence`` (one evidence row per
  instrument / field combination, plus the supporting
  :class:`FieldEvidenceSource`, :class:`FieldKey` and
  :class:`FieldValueType` vocabulary).

The ``EtfProfile`` cases pin:

- Every field accepts ``None`` (Provider unknown) and rejects fabricated
  defaults.
- ``instrument_id`` rejects non-UUIDs and the all-zero UUID.
- Optional text fields reject empty/whitespace strings.
- Fee rates are restricted to ``[0, 1)``.
- ``aum`` / ``shares`` are strictly positive when disclosed.
- ``inception_date`` rejects non-date values (future-date rejection
  is intentionally NOT enforced in the domain — providers may
  publish a forward-dated inception; storage layer is the right
  place for time-bound rules).

The ``FieldEvidence`` cases pin the Field Evidence Domain contract:

- ``instrument_id`` rejects non-UUIDs and the all-zero UUID.
- Runtime value type matches ``value_type`` (``TEXT`` ↔ ``str``,
  ``DECIMAL`` ↔ ``Decimal``, ``DATE`` ↔ ``date`` but not
  ``datetime``).
- ``TEXT`` values are stripped of surrounding whitespace; empty /
  whitespace-only values are rejected.
- ``DECIMAL`` values must be finite; ``bool`` is rejected.
- ``DATE`` values must be ``date``; ``datetime`` is rejected.
- ``QualityStatus.MISSING`` requires ``value`` is ``None``; other
  statuses may carry a value or ``None``.
- ``confidence_score`` is a finite ``Decimal`` in ``[0, 1]``.
- ``source.observed_at`` and ``created_at`` must be timezone-aware.
- ``content_hash`` is a deterministic 64-character lowercase hex
  digest derived from the business content; ``created_at`` is
  excluded from the digest; supplied hashes must match.
- ``FieldKey.AUM``, ``FieldKey.MARKET_VALUE`` and
  ``FieldKey.TURNOVER_VALUE`` are distinct members of the same
  enum and no constructor/helper converts one into another.
- The dataclass is ``frozen=True`` + ``slots=True``.

The repository round-trip and migration-chain tests live in
``tests/storage`` and ``tests/test_migration_chain.py`` respectively;
this file stays infrastructure-free so the domain contract can be
validated without spinning up SQLAlchemy or PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
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
    compute_field_evidence_hash,
)
from invest_domain.etf_profile.models import (
    FieldEvidence as DirectFieldEvidence,
)
from invest_domain.etf_profile.models import (
    FieldEvidenceSource as DirectFieldEvidenceSource,
)
from invest_domain.research import QualityStatus


def _instrument_id() -> UUID:
    return uuid4()


def _observed_at() -> datetime:
    return datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


def _source(**overrides: Any) -> FieldEvidenceSource:
    base: dict[str, Any] = {
        "provider_key": "akshare",
        "dataset_key": "etf_profile_snapshot",
        "observed_at": _observed_at(),
        "source_batch_id": uuid4(),
        "revision": 1,
    }
    base.update(overrides)
    return FieldEvidenceSource(**base)


def _evidence_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "instrument_id": _instrument_id(),
        "field_key": FieldKey.MANAGER,
        "value": "华夏基金",
        "value_type": FieldValueType.TEXT,
        "source": _source(),
        "quality_status": QualityStatus.COMPLETE,
        "confidence_score": Decimal("0.95"),
        "created_at": _observed_at(),
    }
    base.update(overrides)
    return base


def _build_evidence(**overrides: Any) -> FieldEvidence:
    return FieldEvidence(**_evidence_kwargs(**overrides))


class TestEtfProfileConstruction:
    def test_minimal_record_only_carries_instrument_id(self) -> None:
        iid = _instrument_id()
        profile = EtfProfile(instrument_id=iid)
        assert profile.instrument_id == iid
        assert profile.manager is None
        assert profile.benchmark_index is None
        assert profile.category is None
        assert profile.inception_date is None
        assert profile.fund_type is None
        assert profile.management_fee is None
        assert profile.custody_fee is None
        assert profile.aum is None
        assert profile.shares is None

    def test_fully_populated_record_is_constructed(self) -> None:
        iid = _instrument_id()
        profile = EtfProfile(
            instrument_id=iid,
            manager="华夏基金",
            benchmark_index="沪深300",
            category="Equity",
            inception_date=date(2013, 3, 25),
            fund_type="OpenEnd",
            management_fee=Decimal("0.0015"),
            custody_fee=Decimal("0.0010"),
            aum=Decimal("1234567890.00"),
            shares=Decimal("1000000000"),
        )
        assert profile.manager == "华夏基金"
        assert profile.benchmark_index == "沪深300"
        assert profile.category == "Equity"
        assert profile.inception_date == date(2013, 3, 25)
        assert profile.fund_type == "OpenEnd"
        assert profile.management_fee == Decimal("0.0015")
        assert profile.custody_fee == Decimal("0.0010")
        assert profile.aum == Decimal("1234567890.00")
        assert profile.shares == Decimal("1000000000")


class TestInstrumentIdValidation:
    def test_non_uuid_instrument_id_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="instrument_id"):
            EtfProfile(instrument_id="not-a-uuid")  # type: ignore[arg-type]

    def test_all_zero_instrument_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="all-zero"):
            EtfProfile(
                instrument_id=UUID("00000000-0000-0000-0000-000000000000")
            )

    def test_uuid_subclass_other_than_uuid_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            EtfProfile(instrument_id=123)  # type: ignore[arg-type]


class TestOptionalTextValidation:
    @pytest.mark.parametrize(
        "field_name",
        ["manager", "benchmark_index", "category", "fund_type"],
    )
    def test_empty_string_is_rejected(self, field_name: str) -> None:
        kwargs = {field_name: ""}
        with pytest.raises(ValueError, match=field_name):
            EtfProfile(instrument_id=_instrument_id(), **kwargs)

    @pytest.mark.parametrize(
        "field_name",
        ["manager", "benchmark_index", "category", "fund_type"],
    )
    def test_whitespace_string_is_rejected(self, field_name: str) -> None:
        kwargs = {field_name: "   "}
        with pytest.raises(ValueError, match=field_name):
            EtfProfile(instrument_id=_instrument_id(), **kwargs)

    @pytest.mark.parametrize(
        "field_name",
        ["manager", "benchmark_index", "category", "fund_type"],
    )
    def test_non_string_value_is_rejected(self, field_name: str) -> None:
        kwargs = {field_name: 123}  # type: ignore[arg-type]
        with pytest.raises(TypeError, match=field_name):
            EtfProfile(instrument_id=_instrument_id(), **kwargs)

    def test_text_field_strips_surrounding_whitespace(self) -> None:
        profile = EtfProfile(
            instrument_id=_instrument_id(),
            manager="  华夏基金  ",
        )
        assert profile.manager == "华夏基金"


class TestInceptionDateValidation:
    def test_date_value_is_preserved(self) -> None:
        profile = EtfProfile(
            instrument_id=_instrument_id(),
            inception_date=date(2013, 3, 25),
        )
        assert profile.inception_date == date(2013, 3, 25)

    def test_datetime_value_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="inception_date"):
            EtfProfile(
                instrument_id=_instrument_id(),
                inception_date=datetime(2013, 3, 25, tzinfo=UTC),  # type: ignore[arg-type]
            )

    def test_non_date_value_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="inception_date"):
            EtfProfile(
                instrument_id=_instrument_id(),
                inception_date="2013-03-25",  # type: ignore[arg-type]
            )


class TestFeeRateValidation:
    @pytest.mark.parametrize("field_name", ["management_fee", "custody_fee"])
    def test_zero_fee_rate_is_accepted(self, field_name: str) -> None:
        kwargs = {field_name: Decimal("0")}
        profile = EtfProfile(instrument_id=_instrument_id(), **kwargs)
        assert getattr(profile, field_name) == Decimal("0")

    @pytest.mark.parametrize("field_name", ["management_fee", "custody_fee"])
    def test_positive_fee_rate_is_accepted(self, field_name: str) -> None:
        kwargs = {field_name: Decimal("0.0015")}
        profile = EtfProfile(instrument_id=_instrument_id(), **kwargs)
        assert getattr(profile, field_name) == Decimal("0.0015")

    @pytest.mark.parametrize("field_name", ["management_fee", "custody_fee"])
    def test_negative_fee_rate_is_rejected(self, field_name: str) -> None:
        kwargs = {field_name: Decimal("-0.0001")}
        with pytest.raises(ValueError, match=field_name):
            EtfProfile(instrument_id=_instrument_id(), **kwargs)

    @pytest.mark.parametrize("field_name", ["management_fee", "custody_fee"])
    def test_fee_rate_at_one_is_rejected(self, field_name: str) -> None:
        kwargs = {field_name: Decimal("1")}
        with pytest.raises(ValueError, match=field_name):
            EtfProfile(instrument_id=_instrument_id(), **kwargs)

    @pytest.mark.parametrize("field_name", ["management_fee", "custody_fee"])
    def test_fee_rate_above_one_is_rejected(self, field_name: str) -> None:
        kwargs = {field_name: Decimal("1.5")}
        with pytest.raises(ValueError, match=field_name):
            EtfProfile(instrument_id=_instrument_id(), **kwargs)

    @pytest.mark.parametrize("field_name", ["management_fee", "custody_fee"])
    def test_non_finite_fee_rate_is_rejected(self, field_name: str) -> None:
        kwargs = {field_name: Decimal("Infinity")}
        with pytest.raises(ValueError, match="finite"):
            EtfProfile(instrument_id=_instrument_id(), **kwargs)

    @pytest.mark.parametrize("field_name", ["management_fee", "custody_fee"])
    def test_non_decimal_fee_rate_is_rejected(self, field_name: str) -> None:
        kwargs = {field_name: 0.0015}  # type: ignore[arg-type]
        with pytest.raises(TypeError, match=field_name):
            EtfProfile(instrument_id=_instrument_id(), **kwargs)


class TestAumAndSharesValidation:
    @pytest.mark.parametrize("field_name", ["aum", "shares"])
    def test_zero_value_is_rejected(self, field_name: str) -> None:
        kwargs = {field_name: Decimal("0")}
        with pytest.raises(ValueError, match="> 0"):
            EtfProfile(instrument_id=_instrument_id(), **kwargs)

    @pytest.mark.parametrize("field_name", ["aum", "shares"])
    def test_negative_value_is_rejected(self, field_name: str) -> None:
        kwargs = {field_name: Decimal("-1")}
        with pytest.raises(ValueError, match="> 0"):
            EtfProfile(instrument_id=_instrument_id(), **kwargs)

    @pytest.mark.parametrize("field_name", ["aum", "shares"])
    def test_non_finite_value_is_rejected(self, field_name: str) -> None:
        kwargs = {field_name: Decimal("NaN")}
        with pytest.raises(ValueError, match="finite"):
            EtfProfile(instrument_id=_instrument_id(), **kwargs)

    @pytest.mark.parametrize("field_name", ["aum", "shares"])
    def test_non_decimal_value_is_rejected(self, field_name: str) -> None:
        kwargs = {field_name: 1_000_000}  # type: ignore[arg-type]
        with pytest.raises(TypeError, match=field_name):
            EtfProfile(instrument_id=_instrument_id(), **kwargs)


class TestEtfProfileImmutability:
    def test_fields_cannot_be_mutated_after_construction(self) -> None:
        profile = EtfProfile(
            instrument_id=_instrument_id(),
            manager="华夏基金",
        )
        # The dataclass ``frozen=True`` guarantee: direct attribute
        # assignment must raise (Python's ``dataclasses.FrozenInstanceError``
        # is a subclass of :class:`AttributeError`).
        with pytest.raises(AttributeError):
            profile.manager = "其他基金"  # type: ignore[attr-defined]

    def test_slots_enforced(self) -> None:
        profile = EtfProfile(instrument_id=_instrument_id())
        assert not hasattr(profile, "__dict__")
        # ``slots=True`` rejects attributes that are not declared on the
        # dataclass. CPython surfaces that as ``AttributeError`` for
        # normal ``__slots__`` classes and ``TypeError`` from the
        # underlying ``object.__setattr__`` for dataclass-slot combos;
        # either is an acceptable violation, so accept both.
        with pytest.raises((AttributeError, TypeError)):
            profile.random_attr = "boom"  # type: ignore[attr-defined]  # noqa: E501


class TestEtfProfileEquality:
    def test_records_with_same_fields_are_equal(self) -> None:
        iid = _instrument_id()
        a = EtfProfile(instrument_id=iid, manager="华夏基金", management_fee=Decimal("0.0015"))
        b = EtfProfile(instrument_id=iid, manager="华夏基金", management_fee=Decimal("0.0015"))
        assert a == b

    def test_records_with_different_instrument_id_are_unequal(self) -> None:
        a = EtfProfile(instrument_id=_instrument_id(), manager="华夏基金")
        b = EtfProfile(instrument_id=_instrument_id(), manager="华夏基金")
        assert a != b

    def test_records_differing_only_on_one_nullable_field_are_unequal(self) -> None:
        iid = _instrument_id()
        a = EtfProfile(instrument_id=iid, manager="华夏基金")
        b = EtfProfile(instrument_id=iid, manager=None)
        assert a != b


class TestFieldValueTypeVocabulary:
    def test_text_decimal_and_date_are_members(self) -> None:
        assert FieldValueType.TEXT == "text"
        assert FieldValueType.DECIMAL == "decimal"
        assert FieldValueType.DATE == "date"

    def test_members_are_stable_strings(self) -> None:
        assert {member.value for member in FieldValueType} == {"text", "decimal", "date"}


class TestFieldKeyVocabulary:
    @pytest.mark.parametrize(
        "member_name,raw",
        [
            ("SYMBOL", "symbol"),
            ("NAME", "name"),
            ("EXCHANGE", "exchange"),
            ("STATUS", "status"),
            ("MANAGER", "manager"),
            ("BENCHMARK_INDEX", "benchmark_index"),
            ("CATEGORY", "category"),
            ("INCEPTION_DATE", "inception_date"),
            ("FUND_TYPE", "fund_type"),
            ("MANAGEMENT_FEE", "management_fee"),
            ("CUSTODY_FEE", "custody_fee"),
            ("AUM", "aum"),
            ("SHARES", "shares"),
            ("MARKET_VALUE", "market_value"),
            ("TURNOVER_VALUE", "turnover_value"),
        ],
    )
    def test_vocabulary_member(self, member_name: str, raw: str) -> None:
        member = getattr(FieldKey, member_name)
        assert member == raw
        assert isinstance(member, FieldKey)

    def test_aum_market_value_and_turnover_value_are_distinct(self) -> None:
        assert FieldKey.AUM != FieldKey.MARKET_VALUE
        assert FieldKey.AUM != FieldKey.TURNOVER_VALUE
        assert FieldKey.MARKET_VALUE != FieldKey.TURNOVER_VALUE
        assert FieldKey.AUM.value == "aum"
        assert FieldKey.MARKET_VALUE.value == "market_value"
        assert FieldKey.TURNOVER_VALUE.value == "turnover_value"

    def test_no_helper_converts_between_aum_market_value_and_turnover_value(
        self,
    ) -> None:
        members = (FieldKey.AUM, FieldKey.MARKET_VALUE, FieldKey.TURNOVER_VALUE)
        for source in members:
            for target in members:
                if source is target:
                    continue
                # The module deliberately exposes no constructor or
                # helper that rewrites one evidence-only key into
                # another; only an explicit membership equality must
                # hold. The vocabularies' raw string values are
                # different and there is no ``from_*`` helper.
                assert source.value != target.value
                assert source != target


class TestFieldEvidenceSourceValidation:
    def test_default_revision_is_one(self) -> None:
        source = FieldEvidenceSource(
            provider_key="akshare",
            dataset_key="etf_profile_snapshot",
            observed_at=_observed_at(),
        )
        assert source.revision == 1

    def test_optional_source_batch_id_defaults_to_none(self) -> None:
        source = FieldEvidenceSource(
            provider_key="akshare",
            dataset_key="etf_profile_snapshot",
            observed_at=_observed_at(),
        )
        assert source.source_batch_id is None

    def test_empty_provider_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="provider_key"):
            FieldEvidenceSource(
                provider_key="",
                dataset_key="etf_profile_snapshot",
                observed_at=_observed_at(),
            )

    def test_whitespace_provider_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="provider_key"):
            FieldEvidenceSource(
                provider_key="   ",
                dataset_key="etf_profile_snapshot",
                observed_at=_observed_at(),
            )

    def test_non_string_provider_key_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="provider_key"):
            FieldEvidenceSource(
                provider_key=123,  # type: ignore[arg-type]
                dataset_key="etf_profile_snapshot",
                observed_at=_observed_at(),
            )

    def test_empty_dataset_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="dataset_key"):
            FieldEvidenceSource(
                provider_key="akshare",
                dataset_key="",
                observed_at=_observed_at(),
            )

    def test_non_string_dataset_key_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="dataset_key"):
            FieldEvidenceSource(
                provider_key="akshare",
                dataset_key=123,  # type: ignore[arg-type]
                observed_at=_observed_at(),
            )

    def test_naive_observed_at_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            FieldEvidenceSource(
                provider_key="akshare",
                dataset_key="etf_profile_snapshot",
                observed_at=datetime(2026, 7, 31, 12, 0, 0),
            )

    def test_non_datetime_observed_at_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="observed_at"):
            FieldEvidenceSource(
                provider_key="akshare",
                dataset_key="etf_profile_snapshot",
                observed_at="2026-07-31T12:00:00Z",  # type: ignore[arg-type]
            )

    def test_revision_below_one_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="revision"):
            FieldEvidenceSource(
                provider_key="akshare",
                dataset_key="etf_profile_snapshot",
                observed_at=_observed_at(),
                revision=0,
            )

    def test_non_integer_revision_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="revision"):
            FieldEvidenceSource(
                provider_key="akshare",
                dataset_key="etf_profile_snapshot",
                observed_at=_observed_at(),
                revision=Decimal("1"),  # type: ignore[arg-type]
            )

    def test_bool_revision_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="revision"):
            FieldEvidenceSource(
                provider_key="akshare",
                dataset_key="etf_profile_snapshot",
                observed_at=_observed_at(),
                revision=True,  # type: ignore[arg-type]
            )

    def test_non_uuid_source_batch_id_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="source_batch_id"):
            FieldEvidenceSource(
                provider_key="akshare",
                dataset_key="etf_profile_snapshot",
                observed_at=_observed_at(),
                source_batch_id="not-a-uuid",  # type: ignore[arg-type]
            )


class TestFieldEvidenceConstruction:
    def test_minimal_record_carries_required_fields(self) -> None:
        evidence = _build_evidence(created_at=None)
        assert evidence.instrument_id is not None
        assert evidence.field_key is FieldKey.MANAGER
        assert evidence.value == "华夏基金"
        assert evidence.value_type is FieldValueType.TEXT
        assert evidence.source.provider_key == "akshare"
        assert evidence.quality_status is QualityStatus.COMPLETE
        assert evidence.confidence_score == Decimal("0.95")

    def test_text_value_strips_surrounding_whitespace(self) -> None:
        evidence = _build_evidence(value="  华夏基金  ", created_at=None)
        assert evidence.value == "华夏基金"

    def test_decimal_value_is_preserved(self) -> None:
        evidence = _build_evidence(
            field_key=FieldKey.AUM,
            value=Decimal("1234567890.00"),
            value_type=FieldValueType.DECIMAL,
            created_at=None,
        )
        assert evidence.value == Decimal("1234567890.00")

    def test_date_value_is_preserved(self) -> None:
        evidence = _build_evidence(
            field_key=FieldKey.INCEPTION_DATE,
            value=date(2013, 3, 25),
            value_type=FieldValueType.DATE,
            created_at=None,
        )
        assert evidence.value == date(2013, 3, 25)

    def test_none_value_is_allowed_for_non_missing_quality_status(self) -> None:
        evidence = _build_evidence(
            field_key=FieldKey.MANAGER,
            value=None,
            quality_status=QualityStatus.PARTIAL,
            created_at=None,
        )
        assert evidence.value is None

    def test_confidence_score_at_zero_and_one_is_accepted(self) -> None:
        for boundary in (Decimal("0"), Decimal("1")):
            evidence = _build_evidence(
                confidence_score=boundary, created_at=None
            )
            assert evidence.confidence_score == boundary

    def test_created_at_defaults_to_none(self) -> None:
        evidence = FieldEvidence(
            instrument_id=_instrument_id(),
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            value_type=FieldValueType.TEXT,
            source=_source(),
            quality_status=QualityStatus.COMPLETE,
            confidence_score=Decimal("0.95"),
        )
        assert evidence.created_at is None


class TestFieldEvidenceRuntimeValueTypeValidation:
    def test_text_value_with_non_str_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="TEXT"):
            FieldEvidence(
                **_evidence_kwargs(
                    field_key=FieldKey.MANAGER,
                    value=Decimal("1.0"),  # type: ignore[arg-type]
                    value_type=FieldValueType.TEXT,
                    created_at=None,
                )
            )

    def test_empty_text_value_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            FieldEvidence(
                **_evidence_kwargs(
                    field_key=FieldKey.MANAGER,
                    value="",
                    value_type=FieldValueType.TEXT,
                    created_at=None,
                )
            )

    def test_whitespace_text_value_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            FieldEvidence(
                **_evidence_kwargs(
                    field_key=FieldKey.MANAGER,
                    value="   ",
                    value_type=FieldValueType.TEXT,
                    created_at=None,
                )
            )

    def test_decimal_value_with_non_decimal_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="DECIMAL"):
            FieldEvidence(
                **_evidence_kwargs(
                    field_key=FieldKey.AUM,
                    value="12345",  # type: ignore[arg-type]
                    value_type=FieldValueType.DECIMAL,
                    created_at=None,
                )
            )

    def test_decimal_value_with_non_finite_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            FieldEvidence(
                **_evidence_kwargs(
                    field_key=FieldKey.AUM,
                    value=Decimal("Infinity"),
                    value_type=FieldValueType.DECIMAL,
                    created_at=None,
                )
            )

    def test_decimal_value_with_bool_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="DECIMAL"):
            FieldEvidence(
                **_evidence_kwargs(
                    field_key=FieldKey.AUM,
                    value=True,  # type: ignore[arg-type]
                    value_type=FieldValueType.DECIMAL,
                    created_at=None,
                )
            )

    def test_date_value_with_datetime_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="date"):
            FieldEvidence(
                **_evidence_kwargs(
                    field_key=FieldKey.INCEPTION_DATE,
                    value=datetime(2013, 3, 25, tzinfo=timezone.utc),  # type: ignore[arg-type]
                    value_type=FieldValueType.DATE,
                    created_at=None,
                )
            )

    def test_date_value_with_non_date_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="DATE"):
            FieldEvidence(
                **_evidence_kwargs(
                    field_key=FieldKey.INCEPTION_DATE,
                    value="2013-03-25",  # type: ignore[arg-type]
                    value_type=FieldValueType.DATE,
                    created_at=None,
                )
            )

    def test_text_value_with_datetime_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="TEXT"):
            FieldEvidence(
                **_evidence_kwargs(
                    field_key=FieldKey.MANAGER,
                    value=datetime(2026, 7, 31, tzinfo=timezone.utc),  # type: ignore[arg-type]
                    value_type=FieldValueType.TEXT,
                    created_at=None,
                )
            )


class TestFieldEvidenceQualitySemantics:
    def test_missing_quality_with_value_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="MISSING"):
            FieldEvidence(
                **_evidence_kwargs(
                    field_key=FieldKey.MANAGER,
                    value="华夏基金",
                    quality_status=QualityStatus.MISSING,
                    created_at=None,
                )
            )

    @pytest.mark.parametrize(
        "status",
        [
            QualityStatus.COMPLETE,
            QualityStatus.PARTIAL,
            QualityStatus.INVALID,
            QualityStatus.CONFLICT,
        ],
    )
    def test_non_missing_quality_accepts_value_or_none(
        self, status: QualityStatus
    ) -> None:
        with_value = _build_evidence(
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            quality_status=status,
            created_at=None,
        )
        assert with_value.quality_status is status
        assert with_value.value == "华夏基金"
        without_value = _build_evidence(
            field_key=FieldKey.MANAGER,
            value=None,
            quality_status=status,
            created_at=None,
        )
        assert without_value.value is None
        assert without_value.quality_status is status

    def test_missing_quality_accepts_none_value(self) -> None:
        evidence = _build_evidence(
            field_key=FieldKey.MANAGER,
            value=None,
            quality_status=QualityStatus.MISSING,
            created_at=None,
        )
        assert evidence.value is None
        assert evidence.quality_status is QualityStatus.MISSING


class TestFieldEvidenceInstrumentIdValidation:
    def test_all_zero_instrument_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="all-zero"):
            FieldEvidence(
                **_evidence_kwargs(
                    instrument_id=UUID("00000000-0000-0000-0000-000000000000"),
                    created_at=None,
                )
            )

    def test_non_uuid_instrument_id_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="instrument_id"):
            FieldEvidence(
                **_evidence_kwargs(
                    instrument_id="not-a-uuid",  # type: ignore[arg-type]
                    created_at=None,
                )
            )


class TestFieldEvidenceConfidenceValidation:
    @pytest.mark.parametrize(
        "bad",
        [Decimal("-0.01"), Decimal("1.01"), Decimal("10")],
    )
    def test_confidence_outside_zero_one_is_rejected(
        self, bad: Decimal
    ) -> None:
        with pytest.raises(ValueError, match="\\[0, 1\\]"):
            FieldEvidence(
                **_evidence_kwargs(confidence_score=bad, created_at=None)
            )

    def test_non_finite_confidence_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            FieldEvidence(
                **_evidence_kwargs(
                    confidence_score=Decimal("NaN"),
                    created_at=None,
                )
            )

    def test_non_decimal_confidence_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="confidence_score"):
            FieldEvidence(
                **_evidence_kwargs(
                    confidence_score=0.95,  # type: ignore[arg-type]
                    created_at=None,
                )
            )

    def test_bool_confidence_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="confidence_score"):
            FieldEvidence(
                **_evidence_kwargs(
                    confidence_score=True,  # type: ignore[arg-type]
                    created_at=None,
                )
            )


class TestFieldEvidenceCreatedAtValidation:
    def test_naive_created_at_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            FieldEvidence(
                **_evidence_kwargs(
                    created_at=datetime(2026, 7, 31, 12, 0, 0),
                )
            )

    def test_non_datetime_created_at_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="created_at"):
            FieldEvidence(
                **_evidence_kwargs(
                    created_at="2026-07-31T12:00:00Z",  # type: ignore[arg-type]
                )
            )


class TestFieldEvidenceContentHash:
    def test_content_hash_is_computed_when_not_supplied(self) -> None:
        evidence = _build_evidence()
        assert evidence.content_hash == compute_field_evidence_hash(evidence)

    def test_content_hash_length_is_64(self) -> None:
        evidence = _build_evidence()
        assert len(evidence.content_hash) == 64
        int(evidence.content_hash, 16)

    def test_content_hash_is_lowercase_hex(self) -> None:
        evidence = _build_evidence()
        assert evidence.content_hash == evidence.content_hash.lower()
        assert all(character in "0123456789abcdef" for character in evidence.content_hash)

    def test_content_hash_is_deterministic_for_identical_inputs(self) -> None:
        kwargs = _evidence_kwargs()
        first = FieldEvidence(**kwargs)
        second = FieldEvidence(**kwargs)
        assert first.content_hash == second.content_hash

    def test_supplied_matching_hash_is_accepted(self) -> None:
        fixed_source = _source()
        fixed_kwargs = _evidence_kwargs(source=fixed_source)
        expected = compute_field_evidence_hash(
            FieldEvidence(**fixed_kwargs)
        )
        evidence = FieldEvidence(**fixed_kwargs, content_hash=expected)
        assert evidence.content_hash == expected

    def test_supplied_mismatching_hash_is_rejected(self) -> None:
        bad_hash = "0" * 64
        with pytest.raises(ValueError, match="does not match"):
            FieldEvidence(
                **_evidence_kwargs(content_hash=bad_hash)
            )

    def test_supplied_hash_wrong_length_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="64"):
            FieldEvidence(
                **_evidence_kwargs(content_hash="abcd")
            )

    def test_supplied_non_hex_hash_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="hex"):
            FieldEvidence(
                **_evidence_kwargs(content_hash="z" * 64)
            )

    def test_supplied_uppercase_hash_is_rejected(self) -> None:
        fixed_source = _source()
        fixed_kwargs = _evidence_kwargs(source=fixed_source)
        expected = compute_field_evidence_hash(
            FieldEvidence(**fixed_kwargs)
        )
        with pytest.raises(ValueError, match="lowercase"):
            FieldEvidence(
                **_evidence_kwargs(
                    source=fixed_source, content_hash=expected.upper()
                )
            )

    def test_non_string_supplied_hash_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="content_hash"):
            FieldEvidence(
                **_evidence_kwargs(content_hash=12345)  # type: ignore[arg-type]
            )

    def test_hash_excludes_created_at(self) -> None:
        kwargs = _evidence_kwargs()
        kwargs["created_at"] = _observed_at()
        first = FieldEvidence(**kwargs)
        second = FieldEvidence(
            **_evidence_kwargs(
                instrument_id=first.instrument_id,
                field_key=first.field_key,
                value=first.value,
                value_type=first.value_type,
                source=first.source,
                quality_status=first.quality_status,
                confidence_score=first.confidence_score,
                created_at=_observed_at() + timedelta(hours=1),
            )
        )
        assert first.content_hash == second.content_hash

    def test_hash_is_sensitive_to_value(self) -> None:
        first = _build_evidence(value="华夏基金")
        second = _build_evidence(value="易方达基金")
        assert first.content_hash != second.content_hash

    def test_hash_is_sensitive_to_field_key(self) -> None:
        first = _build_evidence(field_key=FieldKey.MANAGER)
        second = _build_evidence(field_key=FieldKey.BENCHMARK_INDEX)
        assert first.content_hash != second.content_hash

    def test_hash_is_sensitive_to_value_type(self) -> None:
        first = _build_evidence(
            field_key=FieldKey.INCEPTION_DATE,
            value=date(2013, 3, 25),
            value_type=FieldValueType.DATE,
        )
        second = _build_evidence(
            field_key=FieldKey.INCEPTION_DATE,
            value=date(2014, 3, 25),
            value_type=FieldValueType.DATE,
        )
        assert first.content_hash != second.content_hash

    def test_hash_is_sensitive_to_quality_status(self) -> None:
        first = _build_evidence(quality_status=QualityStatus.COMPLETE)
        second = _build_evidence(quality_status=QualityStatus.PARTIAL)
        assert first.content_hash != second.content_hash

    def test_hash_is_sensitive_to_confidence_score(self) -> None:
        first = _build_evidence(confidence_score=Decimal("0.95"))
        second = _build_evidence(confidence_score=Decimal("0.90"))
        assert first.content_hash != second.content_hash

    def test_hash_is_sensitive_to_instrument_id(self) -> None:
        first = _build_evidence()
        second = _build_evidence(instrument_id=_instrument_id())
        assert first.content_hash != second.content_hash

    def test_hash_is_sensitive_to_source(self) -> None:
        first = _build_evidence(
            source=_source(provider_key="akshare", revision=1)
        )
        second = _build_evidence(
            source=_source(provider_key="eastmoney", revision=1)
        )
        assert first.content_hash != second.content_hash

    def test_hash_is_sensitive_to_source_revision(self) -> None:
        first = _build_evidence(source=_source(revision=1))
        second = _build_evidence(source=_source(revision=2))
        assert first.content_hash != second.content_hash

    def test_text_stripping_produces_same_hash(self) -> None:
        fixed_source = _source()
        fixed_instrument = _instrument_id()
        first = FieldEvidence(
            **_evidence_kwargs(
                instrument_id=fixed_instrument,
                source=fixed_source,
                value="华夏基金",
            )
        )
        second = FieldEvidence(
            **_evidence_kwargs(
                instrument_id=fixed_instrument,
                source=fixed_source,
                value="  华夏基金  ",
            )
        )
        assert first.content_hash == second.content_hash


class TestFieldEvidenceImmutability:
    def test_fields_cannot_be_mutated_after_construction(self) -> None:
        evidence = _build_evidence()
        with pytest.raises(AttributeError):
            evidence.value = "其他基金"  # type: ignore[attr-defined]

    def test_slots_enforced(self) -> None:
        evidence = _build_evidence()
        assert not hasattr(evidence, "__dict__")
        with pytest.raises((AttributeError, TypeError)):
            evidence.random_attr = "boom"  # type: ignore[attr-defined]  # noqa: E501

    def test_content_hash_is_set_after_construction(self) -> None:
        evidence = _build_evidence()
        # ``content_hash`` is computed in ``__post_init__``; reading it
        # after construction must always return the deterministic
        # digest.
        expected = compute_field_evidence_hash(evidence)
        assert evidence.content_hash == expected


class TestFieldEvidenceAumSeparation:
    def test_aum_market_value_and_turnover_value_observations_are_distinct(
        self,
    ) -> None:
        aum = _build_evidence(
            field_key=FieldKey.AUM,
            value=Decimal("1000000"),
            value_type=FieldValueType.DECIMAL,
            created_at=None,
        )
        market = _build_evidence(
            field_key=FieldKey.MARKET_VALUE,
            value=Decimal("1000000"),
            value_type=FieldValueType.DECIMAL,
            created_at=None,
        )
        turnover = _build_evidence(
            field_key=FieldKey.TURNOVER_VALUE,
            value=Decimal("1000000"),
            value_type=FieldValueType.DECIMAL,
            created_at=None,
        )
        assert aum.field_key is FieldKey.AUM
        assert market.field_key is FieldKey.MARKET_VALUE
        assert turnover.field_key is FieldKey.TURNOVER_VALUE
        # Identical numeric value but different field keys must
        # produce different evidence digests because the evidence
        # framework treats them as semantically distinct observations
        # (plan §6 — AUM is not a market value is not a turnover).
        assert aum.content_hash != market.content_hash
        assert aum.content_hash != turnover.content_hash
        assert market.content_hash != turnover.content_hash

    def test_aum_value_zero_is_accepted_as_provider_disclosure(self) -> None:
        # ``aum`` in :class:`EtfProfile` rejects ``Decimal('0')`` to
        # preserve the "strictly positive when supplied" contract, but
        # :class:`FieldEvidence` is the raw provider observation and
        # must accept any finite Decimal value (including zero) so the
        # Resolver can later decide whether zero is a meaningful
        # observation or should be promoted to ``QualityStatus.INVALID``.
        evidence = _build_evidence(
            field_key=FieldKey.AUM,
            value=Decimal("0"),
            value_type=FieldValueType.DECIMAL,
            quality_status=QualityStatus.INVALID,
            created_at=None,
        )
        assert evidence.value == Decimal("0")
        assert evidence.quality_status is QualityStatus.INVALID


class TestEtfProfilePackageReExport:
    def test_etf_profile_package_reexports_new_types(self) -> None:
        from invest_domain.etf_profile import (  # noqa: F401
            EtfProfile as ReExportedEtfProfile,
            FieldEvidence as ReExportedFieldEvidence,
            FieldEvidenceSource as ReExportedFieldEvidenceSource,
            FieldKey as ReExportedFieldKey,
            FieldValueType as ReExportedFieldValueType,
        )

        assert ReExportedEtfProfile is EtfProfile
        assert ReExportedFieldEvidence is DirectFieldEvidence
        assert ReExportedFieldEvidenceSource is DirectFieldEvidenceSource
        assert ReExportedFieldKey is FieldKey
        assert ReExportedFieldValueType is FieldValueType

    def test_invest_domain_package_reexports_new_types(self) -> None:
        from invest_domain import (  # noqa: F401
            FieldEvidence as DomainFieldEvidence,
            FieldEvidenceSource as DomainFieldEvidenceSource,
            FieldKey as DomainFieldKey,
            FieldValueType as DomainFieldValueType,
        )

        assert DomainFieldEvidence is DirectFieldEvidence
        assert DomainFieldEvidenceSource is DirectFieldEvidenceSource
        assert DomainFieldKey is FieldKey
        assert DomainFieldValueType is FieldValueType
