"""Tests for the ``etf_profile`` bounded context.

The tests cover the Stage DC-2 ``EtfProfile`` domain contract:

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

The repository round-trip and migration-chain tests live in
``tests/storage`` and ``tests/test_migration_chain.py`` respectively;
this file stays infrastructure-free so the domain contract can be
validated without spinning up SQLAlchemy or PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from invest_domain.etf_profile import EtfProfile


def _instrument_id() -> UUID:
    return uuid4()


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
