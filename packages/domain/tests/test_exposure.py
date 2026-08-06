"""Behavior tests for the Stage DC-3A ``exposure`` bounded context.

These tests pin the pure-domain contract for index profile, index
constituent snapshot, ETF↔index mapping and ETF holding snapshot. They
are intentionally production-code-free: every contract is exercised
through the public re-export surface and, where applicable, also
through the ``models`` module so the ``__post_init__`` invariant
checks are reached directly (the same pattern as
``test_etf_profile.py`` / ``test_input_snapshot.py``).

Coverage map:

- :class:`TestExposureProvenanceValidation` — the shared
  provider-provenance record rejects empty ``provider_key`` /
  ``dataset_key``, naive ``observed_at``, non-finite / out-of-range
  ``confidence`` and missing revision.
- :class:`TestIndexProfileValidation` — the canonical static record
  per ``index_code`` rejects empty / whitespace ``index_code`` /
  ``index_name`` and rejects empty :class:`ExposureProvenance`.
- :class:`TestIndexConstituentValidation` — index-constituent weights
  must be finite ``Decimal`` in ``[0, 1]``; non-Decimal / bool values
  are rejected.
- :class:`TestIndexConstituentSnapshotCreate` — the factory sorts
  constituents, rejects duplicates, populates a deterministic
  ``content_hash`` and is order-independent.
- :class:`TestIndexConstituentSnapshotValidation` — direct construction
  re-checks the same invariants and rejects supplied hashes that do
  not match the business content.
- :class:`TestEtfIndexMappingValidation` — the mapping carries
  ``effective_from`` / ``effective_to`` / ``observed_at`` /
  provenance and explicitly exposes no ``index_weight`` /
  ``constituent_weight`` slot.
- :class:`TestEtfHoldingValidation` — ETF holding weights are
  independently validated as finite ``Decimal`` in ``[0, 1]``.
- :class:`TestEtfHoldingSnapshotCreate` — the factory sorts holdings,
  rejects duplicates, populates a deterministic ``content_hash`` and
  is order-independent.
- :class:`TestExposureWeightIndependence` — an index constituent and
  an ETF holding carrying identical numeric weights but different
  identities never collapse into the same content hash and never
  share a slot in any class.
- :class:`TestExposureContentHashDeterminism` — both snapshot
  factories and the static records expose a 64-character lowercase
  hex digest that is stable for identical business content.
- :class:`TestExposurePackageReExport` — ``invest_domain.exposure``
  re-exports every public type so application code never imports
  from ``exposure.models`` directly.
- :class:`TestIndexProfileProvenanceRequiredContract` — the static
  annotation of ``IndexProfile.provenance`` resolves to exactly
  :class:`ExposureProvenance` (no ``Optional`` / ``NoneType`` wrapper).
- :class:`TestExposureProvenanceSourceBatchIdAffectsHash` —
  ``source_batch_id`` embedded in provenance feeds ``content_hash``
  for every contract: index profile, ETF↔index mapping, index
  constituent snapshot, ETF holding snapshot.
- :class:`TestExposureSnapshotDirectConstructionNormalization` —
  direct snapshot construction applies the same ``_security_code_key``
  sort as ``.create``; reordered input yields an identical hash.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from invest_domain.exposure import (
    EtfHolding,
    EtfHoldingSnapshot,
    EtfIndexMapping,
    ExposureProvenance,
    IndexConstituent,
    IndexConstituentSnapshot,
    IndexProfile,
)
from invest_domain.exposure.models import (
    EtfHolding as DirectEtfHolding,
)
from invest_domain.exposure.models import (
    EtfHoldingSnapshot as DirectEtfHoldingSnapshot,
)
from invest_domain.exposure.models import (
    EtfIndexMapping as DirectEtfIndexMapping,
)
from invest_domain.exposure.models import (
    ExposureProvenance as DirectExposureProvenance,
)
from invest_domain.exposure.models import (
    IndexConstituent as DirectIndexConstituent,
)
from invest_domain.exposure.models import (
    IndexConstituentSnapshot as DirectIndexConstituentSnapshot,
)
from invest_domain.exposure.models import (
    IndexProfile as DirectIndexProfile,
)


_CONTENT_HASH_HEX_LEN: int = 64

_ETF_ID_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_ETF_ID_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_INDEX_ID_A = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
_INDEX_ID_B = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")

_HSI_CODE = "HSI"
_HSI_NAME = "Hang Seng Index"
_HSI_CATEGORY = "Broad Market"

_SSE_50 = "000016"
_CSI_300 = "000300"

_OBSERVED_AT = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)
_EARLIER_OBSERVED_AT = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

_AS_OF_DATE = date(2026, 7, 31)
_EARLIER_AS_OF_DATE = date(2026, 7, 30)

_EFFECTIVE_FROM = date(2024, 1, 1)
_EFFECTIVE_TO = date(2026, 12, 31)
_NULL_EFFECTIVE_TO: None = None

_FIXED_SNAPSHOT_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
_FIXED_CREATED_AT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_FIXED_SOURCE_BATCH_ID = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
_ALT_SOURCE_BATCH_ID = UUID("f0f0f0f0-f0f0-4f0f-8f0f-f0f0f0f0f0f0")

_STOCK_A = "600519"
_STOCK_B = "601318"
_STOCK_C = "000858"
_STOCK_D = "300750"


def _fixed_snapshot_id_factory() -> UUID:
    return _FIXED_SNAPSHOT_ID


def _fixed_now_factory() -> datetime:
    return _FIXED_CREATED_AT


def _provenance(**overrides: Any) -> ExposureProvenance:
    base: dict[str, Any] = {
        "provider_key": "akshare",
        "dataset_key": "index_constituent_snapshot",
        "observed_at": _OBSERVED_AT,
        "source_batch_id": _FIXED_SOURCE_BATCH_ID,
        "revision": 1,
        "confidence": Decimal("0.95"),
    }
    base.update(overrides)
    return ExposureProvenance(**base)


def _index_constituent(
    stock_code: str = _STOCK_A,
    weight: Decimal = Decimal("0.10"),
    *,
    industry: str | None = "白酒",
) -> IndexConstituent:
    return IndexConstituent(
        stock_code=stock_code, weight=weight, industry=industry
    )


def _etf_holding(
    stock_code: str = _STOCK_A,
    weight: Decimal = Decimal("0.10"),
    *,
    industry: str | None = "白酒",
) -> EtfHolding:
    return EtfHolding(
        stock_code=stock_code, weight=weight, industry=industry
    )


def _index_profile_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "index_code": _HSI_CODE,
        "index_name": _HSI_NAME,
        "category": _HSI_CATEGORY,
        "provenance": _provenance(),
    }
    base.update(overrides)
    return base


def _index_constituent_snapshot_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": _FIXED_SNAPSHOT_ID,
        "index_code": _HSI_CODE,
        "as_of_date": _AS_OF_DATE,
        "observed_at": _OBSERVED_AT,
        "constituents": (
            _index_constituent(_STOCK_A, Decimal("0.10")),
            _index_constituent(_STOCK_B, Decimal("0.05")),
        ),
        "provenance": _provenance(),
        "content_hash": "",
        "created_at": _FIXED_CREATED_AT,
    }
    base.update(overrides)
    return base


def _etf_holding_snapshot_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": _FIXED_SNAPSHOT_ID,
        "etf_id": _ETF_ID_A,
        "as_of_date": _AS_OF_DATE,
        "observed_at": _OBSERVED_AT,
        "holdings": (
            _etf_holding(_STOCK_A, Decimal("0.10")),
            _etf_holding(_STOCK_B, Decimal("0.05")),
        ),
        "provenance": _provenance(),
        "content_hash": "",
        "created_at": _FIXED_CREATED_AT,
    }
    base.update(overrides)
    return base


def _etf_index_mapping_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "etf_id": _ETF_ID_A,
        "index_id": _INDEX_ID_A,
        "effective_from": _EFFECTIVE_FROM,
        "effective_to": _EFFECTIVE_TO,
        "observed_at": _OBSERVED_AT,
        "provenance": _provenance(),
        "content_hash": "",
    }
    base.update(overrides)
    return base


class TestExposureProvenanceValidation:
    def test_default_revision_is_one(self) -> None:
        provenance = ExposureProvenance(
            provider_key="akshare",
            dataset_key="index_constituent_snapshot",
            observed_at=_OBSERVED_AT,
            confidence=Decimal("0.5"),
        )
        assert provenance.revision == 1

    def test_default_source_batch_id_is_none(self) -> None:
        provenance = ExposureProvenance(
            provider_key="akshare",
            dataset_key="index_constituent_snapshot",
            observed_at=_OBSERVED_AT,
            confidence=Decimal("0.5"),
        )
        assert provenance.source_batch_id is None

    def test_empty_provider_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="provider_key"):
            ExposureProvenance(
                provider_key="",
                dataset_key="index_constituent_snapshot",
                observed_at=_OBSERVED_AT,
                confidence=Decimal("0.5"),
            )

    def test_whitespace_provider_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="provider_key"):
            ExposureProvenance(
                provider_key="   ",
                dataset_key="index_constituent_snapshot",
                observed_at=_OBSERVED_AT,
                confidence=Decimal("0.5"),
            )

    def test_non_string_provider_key_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="provider_key"):
            ExposureProvenance(  # type: ignore[arg-type]
                provider_key=123,
                dataset_key="index_constituent_snapshot",
                observed_at=_OBSERVED_AT,
                confidence=Decimal("0.5"),
            )

    def test_empty_dataset_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="dataset_key"):
            ExposureProvenance(
                provider_key="akshare",
                dataset_key="",
                observed_at=_OBSERVED_AT,
                confidence=Decimal("0.5"),
            )

    def test_non_string_dataset_key_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="dataset_key"):
            ExposureProvenance(  # type: ignore[arg-type]
                provider_key="akshare",
                dataset_key=123,
                observed_at=_OBSERVED_AT,
                confidence=Decimal("0.5"),
            )

    def test_naive_observed_at_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            ExposureProvenance(
                provider_key="akshare",
                dataset_key="index_constituent_snapshot",
                observed_at=datetime(2026, 7, 31, 12, 0, 0),
                confidence=Decimal("0.5"),
            )

    def test_non_datetime_observed_at_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="observed_at"):
            ExposureProvenance(  # type: ignore[arg-type]
                provider_key="akshare",
                dataset_key="index_constituent_snapshot",
                observed_at="2026-07-31T12:00:00Z",
                confidence=Decimal("0.5"),
            )

    def test_revision_below_one_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="revision"):
            ExposureProvenance(
                provider_key="akshare",
                dataset_key="index_constituent_snapshot",
                observed_at=_OBSERVED_AT,
                confidence=Decimal("0.5"),
                revision=0,
            )

    def test_non_integer_revision_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="revision"):
            ExposureProvenance(  # type: ignore[arg-type]
                provider_key="akshare",
                dataset_key="index_constituent_snapshot",
                observed_at=_OBSERVED_AT,
                confidence=Decimal("0.5"),
                revision=Decimal("1"),
            )

    def test_bool_revision_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="revision"):
            ExposureProvenance(  # type: ignore[arg-type]
                provider_key="akshare",
                dataset_key="index_constituent_snapshot",
                observed_at=_OBSERVED_AT,
                confidence=Decimal("0.5"),
                revision=True,
            )

    def test_non_uuid_source_batch_id_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="source_batch_id"):
            ExposureProvenance(  # type: ignore[arg-type]
                provider_key="akshare",
                dataset_key="index_constituent_snapshot",
                observed_at=_OBSERVED_AT,
                source_batch_id="not-a-uuid",
                confidence=Decimal("0.5"),
            )

    @pytest.mark.parametrize(
        "bad",
        [Decimal("-0.01"), Decimal("1.01"), Decimal("10")],
    )
    def test_confidence_outside_zero_one_is_rejected(
        self, bad: Decimal
    ) -> None:
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            ExposureProvenance(
                provider_key="akshare",
                dataset_key="index_constituent_snapshot",
                observed_at=_OBSERVED_AT,
                confidence=bad,
            )

    def test_non_finite_confidence_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            ExposureProvenance(
                provider_key="akshare",
                dataset_key="index_constituent_snapshot",
                observed_at=_OBSERVED_AT,
                confidence=Decimal("NaN"),
            )

    def test_non_decimal_confidence_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="confidence"):
            ExposureProvenance(  # type: ignore[arg-type]
                provider_key="akshare",
                dataset_key="index_constituent_snapshot",
                observed_at=_OBSERVED_AT,
                confidence=0.95,
            )

    def test_bool_confidence_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="confidence"):
            ExposureProvenance(  # type: ignore[arg-type]
                provider_key="akshare",
                dataset_key="index_constituent_snapshot",
                observed_at=_OBSERVED_AT,
                confidence=True,
            )

    def test_provenance_is_required_for_index_profile(self) -> None:
        with pytest.raises((TypeError, ValueError)):
            IndexProfile(  # type: ignore[call-arg]
                index_code=_HSI_CODE,
                index_name=_HSI_NAME,
                category=_HSI_CATEGORY,
            )

    def test_empty_provenance_is_rejected_by_index_profile(self) -> None:
        with pytest.raises(ValueError):
            IndexProfile(**_index_profile_kwargs(provenance=None))


class TestIndexProfileValidation:
    def test_minimal_record_only_carries_required_fields(self) -> None:
        profile = IndexProfile(
            index_code=_HSI_CODE,
            index_name=_HSI_NAME,
            provenance=_provenance(),
        )
        assert profile.index_code == _HSI_CODE
        assert profile.index_name == _HSI_NAME
        assert profile.category is None
        assert isinstance(profile.provenance, ExposureProvenance)
        assert profile.content_hash

    def test_fully_populated_record_is_constructed(self) -> None:
        profile = IndexProfile(
            index_code=_HSI_CODE,
            index_name=_HSI_NAME,
            category=_HSI_CATEGORY,
            provenance=_provenance(),
        )
        assert profile.category == _HSI_CATEGORY

    @pytest.mark.parametrize(
        "field_name", ["index_code", "index_name", "category"]
    )
    def test_empty_string_is_rejected(self, field_name: str) -> None:
        kwargs = _index_profile_kwargs()
        kwargs[field_name] = ""
        with pytest.raises(ValueError, match=field_name):
            IndexProfile(**kwargs)

    @pytest.mark.parametrize(
        "field_name", ["index_code", "index_name", "category"]
    )
    def test_whitespace_string_is_rejected(self, field_name: str) -> None:
        kwargs = _index_profile_kwargs()
        kwargs[field_name] = "   "
        with pytest.raises(ValueError, match=field_name):
            IndexProfile(**kwargs)

    @pytest.mark.parametrize(
        "field_name", ["index_code", "index_name", "category"]
    )
    def test_non_string_value_is_rejected(self, field_name: str) -> None:
        kwargs = _index_profile_kwargs()
        kwargs[field_name] = 123  # type: ignore[arg-type]
        with pytest.raises(TypeError, match=field_name):
            IndexProfile(**kwargs)

    def test_text_field_strips_surrounding_whitespace(self) -> None:
        profile = IndexProfile(
            index_code="  HSI  ",
            index_name="  Hang Seng Index  ",
            provenance=_provenance(),
        )
        assert profile.index_code == "HSI"
        assert profile.index_name == "Hang Seng Index"

    def test_profile_has_no_weight_or_holding_slot(self) -> None:
        profile = IndexProfile(**_index_profile_kwargs())
        forbidden = (
            "weight",
            "constituents",
            "holdings",
            "index_weight",
            "etf_weight",
            "stock_code",
        )
        for attribute in forbidden:
            assert not hasattr(profile, attribute), (
                f"IndexProfile must not expose a {attribute!r} attribute "
                "(weights live on constituent / holding snapshots)"
            )

    def test_profile_fields_cannot_be_mutated_after_construction(self) -> None:
        profile = IndexProfile(**_index_profile_kwargs())
        with pytest.raises(AttributeError):
            profile.index_name = "Other Index"  # type: ignore[attr-defined]

    def test_profile_slots_enforced(self) -> None:
        profile = IndexProfile(**_index_profile_kwargs())
        assert not hasattr(profile, "__dict__")
        with pytest.raises((AttributeError, TypeError)):
            profile.random_attr = "boom"  # type: ignore[attr-defined]


class TestIndexProfileContentHash:
    def test_content_hash_is_computed_when_not_supplied(self) -> None:
        profile = IndexProfile(**_index_profile_kwargs())
        assert profile.content_hash
        assert len(profile.content_hash) == _CONTENT_HASH_HEX_LEN
        int(profile.content_hash, 16)

    def test_content_hash_is_lowercase_hex(self) -> None:
        profile = IndexProfile(**_index_profile_kwargs())
        assert profile.content_hash == profile.content_hash.lower()
        assert all(
            character in "0123456789abcdef" for character in profile.content_hash
        )

    def test_content_hash_is_deterministic_for_identical_inputs(self) -> None:
        first = IndexProfile(**_index_profile_kwargs())
        second = IndexProfile(**_index_profile_kwargs())
        assert first.content_hash == second.content_hash

    def test_distinct_index_codes_produce_distinct_hashes(self) -> None:
        first = IndexProfile(**_index_profile_kwargs(index_code="HSI"))
        second = IndexProfile(**_index_profile_kwargs(index_code="HSCEI"))
        assert first.content_hash != second.content_hash

    def test_distinct_categories_produce_distinct_hashes(self) -> None:
        first = IndexProfile(**_index_profile_kwargs(category="Broad Market"))
        second = IndexProfile(**_index_profile_kwargs(category="Strategy"))
        assert first.content_hash != second.content_hash


class TestIndexConstituentValidation:
    def test_minimal_record_carries_required_fields(self) -> None:
        constituent = IndexConstituent(
            stock_code=_STOCK_A, weight=Decimal("0.10")
        )
        assert constituent.stock_code == _STOCK_A
        assert constituent.weight == Decimal("0.10")
        assert constituent.industry is None

    def test_industry_is_optional(self) -> None:
        constituent = IndexConstituent(
            stock_code=_STOCK_A, weight=Decimal("0.10"), industry="白酒"
        )
        assert constituent.industry == "白酒"

    def test_empty_stock_code_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="stock_code"):
            IndexConstituent(stock_code="", weight=Decimal("0.10"))

    def test_whitespace_stock_code_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="stock_code"):
            IndexConstituent(stock_code="   ", weight=Decimal("0.10"))

    def test_non_string_stock_code_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="stock_code"):
            IndexConstituent(  # type: ignore[call-arg]
                stock_code=123, weight=Decimal("0.10")
            )

    def test_empty_industry_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="industry"):
            IndexConstituent(
                stock_code=_STOCK_A,
                weight=Decimal("0.10"),
                industry="",
            )

    def test_whitespace_industry_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="industry"):
            IndexConstituent(
                stock_code=_STOCK_A,
                weight=Decimal("0.10"),
                industry="   ",
            )

    @pytest.mark.parametrize(
        "weight",
        [Decimal("0"), Decimal("0.5"), Decimal("1")],
    )
    def test_weight_at_boundaries_is_accepted(self, weight: Decimal) -> None:
        constituent = IndexConstituent(stock_code=_STOCK_A, weight=weight)
        assert constituent.weight == weight

    @pytest.mark.parametrize(
        "bad_weight",
        [Decimal("-0.01"), Decimal("1.01"), Decimal("100")],
    )
    def test_weight_outside_zero_one_is_rejected(
        self, bad_weight: Decimal
    ) -> None:
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            IndexConstituent(stock_code=_STOCK_A, weight=bad_weight)

    def test_non_finite_weight_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            IndexConstituent(
                stock_code=_STOCK_A, weight=Decimal("Infinity")
            )

    def test_non_decimal_weight_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="weight"):
            IndexConstituent(  # type: ignore[arg-type]
                stock_code=_STOCK_A, weight=0.10
            )

    def test_bool_weight_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="weight"):
            IndexConstituent(  # type: ignore[arg-type]
                stock_code=_STOCK_A, weight=True
            )

    def test_industry_strips_surrounding_whitespace(self) -> None:
        constituent = IndexConstituent(
            stock_code=_STOCK_A,
            weight=Decimal("0.10"),
            industry="  白酒  ",
        )
        assert constituent.industry == "白酒"


class TestIndexConstituentSnapshotCreate:
    def test_create_sorts_constituents_by_stock_code(self) -> None:
        snapshot = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                _index_constituent(_STOCK_C, Decimal("0.20")),
                _index_constituent(_STOCK_A, Decimal("0.10")),
                _index_constituent(_STOCK_D, Decimal("0.05")),
                _index_constituent(_STOCK_B, Decimal("0.30")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.index_code == _HSI_CODE
        assert snapshot.as_of_date == _AS_OF_DATE
        assert [c.stock_code for c in snapshot.constituents] == [
            _STOCK_A,
            _STOCK_B,
            _STOCK_C,
            _STOCK_D,
        ]

    def test_create_is_order_independent(self) -> None:
        forward = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                _index_constituent(_STOCK_A, Decimal("0.10")),
                _index_constituent(_STOCK_B, Decimal("0.20")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        reverse = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                _index_constituent(_STOCK_B, Decimal("0.20")),
                _index_constituent(_STOCK_A, Decimal("0.10")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        middle = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                _index_constituent(_STOCK_B, Decimal("0.20")),
                _index_constituent(_STOCK_A, Decimal("0.10")),
            ][::-1],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert forward.content_hash == reverse.content_hash == middle.content_hash
        assert forward.constituents == reverse.constituents == middle.constituents

    def test_create_uses_id_and_now_factories(self) -> None:
        snapshot = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[_index_constituent(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.id == _FIXED_SNAPSHOT_ID
        assert snapshot.created_at == _FIXED_CREATED_AT

    def test_create_sets_constituent_count(self) -> None:
        snapshot = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                _index_constituent(_STOCK_A, Decimal("0.10")),
                _index_constituent(_STOCK_B, Decimal("0.20")),
                _index_constituent(_STOCK_C, Decimal("0.30")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert len(snapshot.constituents) == 3

    def test_create_computes_deterministic_content_hash(self) -> None:
        snapshot = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                _index_constituent(_STOCK_B, Decimal("0.20")),
                _index_constituent(_STOCK_A, Decimal("0.10")),
                _index_constituent(_STOCK_D, Decimal("0.30")),
                _index_constituent(_STOCK_C, Decimal("0.05")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.content_hash == IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                _index_constituent(_STOCK_A, Decimal("0.10")),
                _index_constituent(_STOCK_C, Decimal("0.05")),
                _index_constituent(_STOCK_D, Decimal("0.30")),
                _index_constituent(_STOCK_B, Decimal("0.20")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        ).content_hash

    def test_create_content_hash_length_is_64(self) -> None:
        snapshot = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[_index_constituent(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert len(snapshot.content_hash) == _CONTENT_HASH_HEX_LEN
        int(snapshot.content_hash, 16)

    def test_create_distinct_inputs_produce_distinct_hashes(self) -> None:
        first = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                _index_constituent(_STOCK_A, Decimal("0.10")),
                _index_constituent(_STOCK_B, Decimal("0.20")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        second = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                _index_constituent(_STOCK_A, Decimal("0.10")),
                _index_constituent(_STOCK_C, Decimal("0.20")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        third = IndexConstituentSnapshot.create(
            index_code="HSCEI",
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                _index_constituent(_STOCK_A, Decimal("0.10")),
                _index_constituent(_STOCK_B, Decimal("0.20")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert first.content_hash != second.content_hash
        assert first.content_hash != third.content_hash
        assert second.content_hash != third.content_hash

    def test_create_accepts_generator_input(self) -> None:
        snapshot = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=(
                _index_constituent(code, Decimal("0.10"))
                for code in (_STOCK_C, _STOCK_A, _STOCK_B)
            ),
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert [c.stock_code for c in snapshot.constituents] == [
            _STOCK_A,
            _STOCK_B,
            _STOCK_C,
        ]

    def test_create_rejects_empty_constituents(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            IndexConstituentSnapshot.create(
                index_code=_HSI_CODE,
                as_of_date=_AS_OF_DATE,
                observed_at=_OBSERVED_AT,
                constituents=[],
                provenance=_provenance(),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_duplicate_stock_codes(self) -> None:
        with pytest.raises(ValueError, match="duplicates"):
            IndexConstituentSnapshot.create(
                index_code=_HSI_CODE,
                as_of_date=_AS_OF_DATE,
                observed_at=_OBSERVED_AT,
                constituents=[
                    _index_constituent(_STOCK_A, Decimal("0.10")),
                    _index_constituent(_STOCK_B, Decimal("0.20")),
                    _index_constituent(_STOCK_A, Decimal("0.30")),
                ],
                provenance=_provenance(),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_invalid_weight_in_entry(self) -> None:
        with pytest.raises((TypeError, ValueError)):
            IndexConstituentSnapshot.create(
                index_code=_HSI_CODE,
                as_of_date=_AS_OF_DATE,
                observed_at=_OBSERVED_AT,
                constituents=[
                    _index_constituent(_STOCK_A, Decimal("0.10")),
                    IndexConstituent(
                        stock_code=_STOCK_B, weight=Decimal("1.5")
                    ),
                ],
                provenance=_provenance(),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_empty_index_code(self) -> None:
        with pytest.raises(ValueError, match="index_code"):
            IndexConstituentSnapshot.create(
                index_code="",
                as_of_date=_AS_OF_DATE,
                observed_at=_OBSERVED_AT,
                constituents=[_index_constituent(_STOCK_A, Decimal("0.10"))],
                provenance=_provenance(),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_whitespace_index_code(self) -> None:
        with pytest.raises(ValueError, match="index_code"):
            IndexConstituentSnapshot.create(
                index_code="   ",
                as_of_date=_AS_OF_DATE,
                observed_at=_OBSERVED_AT,
                constituents=[_index_constituent(_STOCK_A, Decimal("0.10"))],
                provenance=_provenance(),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_invalid_as_of_date(self) -> None:
        with pytest.raises((TypeError, ValueError)):
            IndexConstituentSnapshot.create(
                index_code=_HSI_CODE,
                as_of_date="2026-07-31",  # type: ignore[arg-type]
                observed_at=_OBSERVED_AT,
                constituents=[_index_constituent(_STOCK_A, Decimal("0.10"))],
                provenance=_provenance(),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_naive_observed_at(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            IndexConstituentSnapshot.create(
                index_code=_HSI_CODE,
                as_of_date=_AS_OF_DATE,
                observed_at=datetime(2026, 7, 31, 12, 0, 0),
                constituents=[_index_constituent(_STOCK_A, Decimal("0.10"))],
                provenance=_provenance(),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_empty_provenance(self) -> None:
        with pytest.raises(ValueError):
            IndexConstituentSnapshot.create(
                index_code=_HSI_CODE,
                as_of_date=_AS_OF_DATE,
                observed_at=_OBSERVED_AT,
                constituents=[_index_constituent(_STOCK_A, Decimal("0.10"))],
                provenance=_provenance(provider_key=""),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_factory_defaults_match_expectations(self) -> None:
        snapshot = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[_index_constituent(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
        )
        assert isinstance(snapshot.id, UUID)
        assert snapshot.created_at.tzinfo is not None
        assert snapshot.created_at.utcoffset() == UTC.utcoffset(
            snapshot.created_at
        )
        assert snapshot.created_at <= datetime.now(timezone.utc)


class TestIndexConstituentSnapshotValidation:
    def test_direct_construction_accepts_valid_payload(self) -> None:
        snapshot = DirectIndexConstituentSnapshot(
            **_index_constituent_snapshot_kwargs()
        )
        assert snapshot.id == _FIXED_SNAPSHOT_ID
        assert snapshot.index_code == _HSI_CODE
        assert snapshot.as_of_date == _AS_OF_DATE
        assert snapshot.observed_at == _OBSERVED_AT
        assert len(snapshot.constituents) == 2

    def test_empty_constituents_is_rejected(self) -> None:
        kwargs = _index_constituent_snapshot_kwargs()
        kwargs["constituents"] = ()
        with pytest.raises(ValueError, match="must not be empty"):
            DirectIndexConstituentSnapshot(**kwargs)

    def test_duplicate_stock_codes_is_rejected(self) -> None:
        kwargs = _index_constituent_snapshot_kwargs()
        kwargs["constituents"] = (
            _index_constituent(_STOCK_A, Decimal("0.10")),
            _index_constituent(_STOCK_A, Decimal("0.20")),
        )
        with pytest.raises(ValueError, match="duplicates"):
            DirectIndexConstituentSnapshot(**kwargs)

    def test_non_tuple_constituents_is_rejected(self) -> None:
        kwargs = _index_constituent_snapshot_kwargs()
        kwargs["constituents"] = [  # type: ignore[assignment]
            _index_constituent(_STOCK_A, Decimal("0.10"))
        ]
        with pytest.raises(ValueError, match="must be a tuple"):
            DirectIndexConstituentSnapshot(**kwargs)

    def test_non_date_as_of_date_is_rejected(self) -> None:
        kwargs = _index_constituent_snapshot_kwargs()
        kwargs["as_of_date"] = "2026-07-31"  # type: ignore[assignment]
        with pytest.raises((TypeError, ValueError), match="as_of_date"):
            DirectIndexConstituentSnapshot(**kwargs)

    def test_naive_created_at_is_rejected(self) -> None:
        kwargs = _index_constituent_snapshot_kwargs()
        kwargs["created_at"] = datetime(2026, 8, 1, 0, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            DirectIndexConstituentSnapshot(**kwargs)

    def test_content_hash_wrong_length_is_rejected(self) -> None:
        kwargs = _index_constituent_snapshot_kwargs()
        kwargs["content_hash"] = "abcd"
        with pytest.raises(ValueError, match="64"):
            DirectIndexConstituentSnapshot(**kwargs)

    def test_content_hash_too_long_is_rejected(self) -> None:
        kwargs = _index_constituent_snapshot_kwargs()
        kwargs["content_hash"] = "a" * 65
        with pytest.raises(ValueError, match="64"):
            DirectIndexConstituentSnapshot(**kwargs)

    def test_non_string_content_hash_is_rejected(self) -> None:
        kwargs = _index_constituent_snapshot_kwargs()
        kwargs["content_hash"] = 12345  # type: ignore[assignment]
        with pytest.raises(TypeError, match="must be a str"):
            DirectIndexConstituentSnapshot(**kwargs)

    def test_supplied_mismatching_hash_is_rejected(self) -> None:
        kwargs = _index_constituent_snapshot_kwargs()
        kwargs["content_hash"] = "0" * _CONTENT_HASH_HEX_LEN
        with pytest.raises(ValueError, match="does not match"):
            DirectIndexConstituentSnapshot(**kwargs)


class TestEtfIndexMappingValidation:
    def test_minimal_record_carries_required_fields(self) -> None:
        mapping = EtfIndexMapping(
            etf_id=_ETF_ID_A,
            index_id=_INDEX_ID_A,
            effective_from=_EFFECTIVE_FROM,
            effective_to=_NULL_EFFECTIVE_TO,
            observed_at=_OBSERVED_AT,
            provenance=_provenance(),
        )
        assert mapping.etf_id == _ETF_ID_A
        assert mapping.index_id == _INDEX_ID_A
        assert mapping.effective_from == _EFFECTIVE_FROM
        assert mapping.effective_to is None
        assert mapping.observed_at == _OBSERVED_AT
        assert isinstance(mapping.provenance, ExposureProvenance)

    def test_fully_populated_record_is_constructed(self) -> None:
        mapping = EtfIndexMapping(
            etf_id=_ETF_ID_A,
            index_id=_INDEX_ID_A,
            effective_from=_EFFECTIVE_FROM,
            effective_to=_EFFECTIVE_TO,
            observed_at=_OBSERVED_AT,
            provenance=_provenance(),
        )
        assert mapping.effective_to == _EFFECTIVE_TO

    def test_mapping_explicitly_carries_effective_from_to(self) -> None:
        mapping = EtfIndexMapping(**_etf_index_mapping_kwargs())
        assert hasattr(mapping, "effective_from")
        assert hasattr(mapping, "effective_to")
        assert mapping.effective_from == _EFFECTIVE_FROM
        assert mapping.effective_to == _EFFECTIVE_TO

    def test_mapping_explicitly_carries_observed_at(self) -> None:
        mapping = EtfIndexMapping(**_etf_index_mapping_kwargs())
        assert mapping.observed_at == _OBSERVED_AT

    def test_mapping_explicitly_carries_provenance(self) -> None:
        mapping = EtfIndexMapping(**_etf_index_mapping_kwargs())
        assert isinstance(mapping.provenance, ExposureProvenance)
        assert mapping.provenance.provider_key == "akshare"

    def test_mapping_has_no_index_weight_slot(self) -> None:
        mapping = EtfIndexMapping(**_etf_index_mapping_kwargs())
        forbidden = (
            "index_weight",
            "constituent_weight",
            "weight",
            "weights",
            "constituents",
            "holdings",
            "stock_code",
            "as_of_date",
        )
        for attribute in forbidden:
            assert not hasattr(mapping, attribute), (
                f"EtfIndexMapping must not expose a {attribute!r} attribute "
                "(weights live on constituent / holding snapshots; "
                "EtfIndexMapping only records the validity window)"
            )

    def test_non_uuid_etf_id_is_rejected(self) -> None:
        with pytest.raises((TypeError, ValueError), match="etf_id"):
            EtfIndexMapping(  # type: ignore[arg-type]
                etf_id="not-a-uuid",
                index_id=_INDEX_ID_A,
                effective_from=_EFFECTIVE_FROM,
                effective_to=_EFFECTIVE_TO,
                observed_at=_OBSERVED_AT,
                provenance=_provenance(),
            )

    def test_non_uuid_index_id_is_rejected(self) -> None:
        with pytest.raises((TypeError, ValueError), match="index_id"):
            EtfIndexMapping(  # type: ignore[arg-type]
                etf_id=_ETF_ID_A,
                index_id="not-a-uuid",
                effective_from=_EFFECTIVE_FROM,
                effective_to=_EFFECTIVE_TO,
                observed_at=_OBSERVED_AT,
                provenance=_provenance(),
            )

    def test_non_date_effective_from_is_rejected(self) -> None:
        with pytest.raises((TypeError, ValueError), match="effective_from"):
            EtfIndexMapping(  # type: ignore[arg-type]
                etf_id=_ETF_ID_A,
                index_id=_INDEX_ID_A,
                effective_from="2024-01-01",
                effective_to=_EFFECTIVE_TO,
                observed_at=_OBSERVED_AT,
                provenance=_provenance(),
            )

    def test_effective_to_before_effective_from_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="effective_to"):
            EtfIndexMapping(
                etf_id=_ETF_ID_A,
                index_id=_INDEX_ID_A,
                effective_from=_EFFECTIVE_FROM,
                effective_to=date(2023, 1, 1),
                observed_at=_OBSERVED_AT,
                provenance=_provenance(),
            )

    def test_naive_observed_at_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            EtfIndexMapping(
                etf_id=_ETF_ID_A,
                index_id=_INDEX_ID_A,
                effective_from=_EFFECTIVE_FROM,
                effective_to=_EFFECTIVE_TO,
                observed_at=datetime(2026, 7, 31, 12, 0, 0),
                provenance=_provenance(),
            )

    def test_empty_provenance_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            EtfIndexMapping(
                etf_id=_ETF_ID_A,
                index_id=_INDEX_ID_A,
                effective_from=_EFFECTIVE_FROM,
                effective_to=_EFFECTIVE_TO,
                observed_at=_OBSERVED_AT,
                provenance=_provenance(provider_key=""),
            )

    def test_mapping_fields_cannot_be_mutated_after_construction(self) -> None:
        mapping = EtfIndexMapping(**_etf_index_mapping_kwargs())
        with pytest.raises(AttributeError):
            mapping.effective_to = None  # type: ignore[attr-defined]

    def test_mapping_slots_enforced(self) -> None:
        mapping = EtfIndexMapping(**_etf_index_mapping_kwargs())
        assert not hasattr(mapping, "__dict__")
        with pytest.raises((AttributeError, TypeError)):
            mapping.random_attr = "boom"  # type: ignore[attr-defined]

    def test_two_mappings_with_distinct_etfs_are_unequal(self) -> None:
        first = EtfIndexMapping(**_etf_index_mapping_kwargs())
        second = EtfIndexMapping(**_etf_index_mapping_kwargs(etf_id=_ETF_ID_B))
        assert first != second

    def test_two_mappings_with_distinct_indexes_are_unequal(self) -> None:
        first = EtfIndexMapping(**_etf_index_mapping_kwargs())
        second = EtfIndexMapping(**_etf_index_mapping_kwargs(index_id=_INDEX_ID_B))
        assert first != second


class TestEtfIndexMappingContentHash:
    def test_distinct_etfs_produce_distinct_hashes(self) -> None:
        first = EtfIndexMapping(**_etf_index_mapping_kwargs())
        second = EtfIndexMapping(**_etf_index_mapping_kwargs(etf_id=_ETF_ID_B))
        assert first.content_hash != second.content_hash

    def test_distinct_indexes_produce_distinct_hashes(self) -> None:
        first = EtfIndexMapping(**_etf_index_mapping_kwargs())
        second = EtfIndexMapping(**_etf_index_mapping_kwargs(index_id=_INDEX_ID_B))
        assert first.content_hash != second.content_hash

    def test_distinct_effective_windows_produce_distinct_hashes(self) -> None:
        first = EtfIndexMapping(**_etf_index_mapping_kwargs())
        second = EtfIndexMapping(
            **_etf_index_mapping_kwargs(effective_from=date(2025, 1, 1))
        )
        assert first.content_hash != second.content_hash

    def test_content_hash_is_lowercase_hex_64_chars(self) -> None:
        mapping = EtfIndexMapping(**_etf_index_mapping_kwargs())
        assert len(mapping.content_hash) == _CONTENT_HASH_HEX_LEN
        assert mapping.content_hash == mapping.content_hash.lower()
        int(mapping.content_hash, 16)


class TestEtfHoldingValidation:
    def test_minimal_record_carries_required_fields(self) -> None:
        holding = EtfHolding(stock_code=_STOCK_A, weight=Decimal("0.10"))
        assert holding.stock_code == _STOCK_A
        assert holding.weight == Decimal("0.10")
        assert holding.industry is None

    def test_industry_is_optional(self) -> None:
        holding = EtfHolding(
            stock_code=_STOCK_A, weight=Decimal("0.10"), industry="金融"
        )
        assert holding.industry == "金融"

    def test_empty_stock_code_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="stock_code"):
            EtfHolding(stock_code="", weight=Decimal("0.10"))

    def test_whitespace_stock_code_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="stock_code"):
            EtfHolding(stock_code="   ", weight=Decimal("0.10"))

    def test_non_string_stock_code_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="stock_code"):
            EtfHolding(  # type: ignore[call-arg]
                stock_code=123, weight=Decimal("0.10")
            )

    @pytest.mark.parametrize(
        "weight",
        [Decimal("0"), Decimal("0.5"), Decimal("1")],
    )
    def test_weight_at_boundaries_is_accepted(self, weight: Decimal) -> None:
        holding = EtfHolding(stock_code=_STOCK_A, weight=weight)
        assert holding.weight == weight

    @pytest.mark.parametrize(
        "bad_weight",
        [Decimal("-0.01"), Decimal("1.01"), Decimal("100")],
    )
    def test_weight_outside_zero_one_is_rejected(
        self, bad_weight: Decimal
    ) -> None:
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            EtfHolding(stock_code=_STOCK_A, weight=bad_weight)

    def test_non_finite_weight_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            EtfHolding(stock_code=_STOCK_A, weight=Decimal("Infinity"))

    def test_non_decimal_weight_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="weight"):
            EtfHolding(  # type: ignore[arg-type]
                stock_code=_STOCK_A, weight=0.10
            )

    def test_bool_weight_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="weight"):
            EtfHolding(  # type: ignore[arg-type]
                stock_code=_STOCK_A, weight=True
            )


class TestEtfHoldingSnapshotCreate:
    def test_create_sorts_holdings_by_stock_code(self) -> None:
        snapshot = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[
                _etf_holding(_STOCK_C, Decimal("0.20")),
                _etf_holding(_STOCK_A, Decimal("0.10")),
                _etf_holding(_STOCK_D, Decimal("0.05")),
                _etf_holding(_STOCK_B, Decimal("0.30")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert [h.stock_code for h in snapshot.holdings] == [
            _STOCK_A,
            _STOCK_B,
            _STOCK_C,
            _STOCK_D,
        ]

    def test_create_is_order_independent(self) -> None:
        forward = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[
                _etf_holding(_STOCK_A, Decimal("0.10")),
                _etf_holding(_STOCK_B, Decimal("0.20")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        reverse = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[
                _etf_holding(_STOCK_B, Decimal("0.20")),
                _etf_holding(_STOCK_A, Decimal("0.10")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        middle = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=(
                _etf_holding(_STOCK_B, Decimal("0.20")),
                _etf_holding(_STOCK_A, Decimal("0.10")),
            )[::-1],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert forward.content_hash == reverse.content_hash == middle.content_hash
        assert forward.holdings == reverse.holdings == middle.holdings

    def test_create_uses_id_and_now_factories(self) -> None:
        snapshot = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[_etf_holding(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.id == _FIXED_SNAPSHOT_ID
        assert snapshot.created_at == _FIXED_CREATED_AT

    def test_create_sets_holding_count(self) -> None:
        snapshot = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[
                _etf_holding(_STOCK_A, Decimal("0.10")),
                _etf_holding(_STOCK_B, Decimal("0.20")),
                _etf_holding(_STOCK_C, Decimal("0.30")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert len(snapshot.holdings) == 3

    def test_create_computes_deterministic_content_hash(self) -> None:
        snapshot = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[
                _etf_holding(_STOCK_B, Decimal("0.20")),
                _etf_holding(_STOCK_A, Decimal("0.10")),
                _etf_holding(_STOCK_D, Decimal("0.30")),
                _etf_holding(_STOCK_C, Decimal("0.05")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        other = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[
                _etf_holding(_STOCK_A, Decimal("0.10")),
                _etf_holding(_STOCK_C, Decimal("0.05")),
                _etf_holding(_STOCK_D, Decimal("0.30")),
                _etf_holding(_STOCK_B, Decimal("0.20")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.content_hash == other.content_hash

    def test_create_content_hash_length_is_64(self) -> None:
        snapshot = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[_etf_holding(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert len(snapshot.content_hash) == _CONTENT_HASH_HEX_LEN
        int(snapshot.content_hash, 16)

    def test_create_distinct_inputs_produce_distinct_hashes(self) -> None:
        first = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[
                _etf_holding(_STOCK_A, Decimal("0.10")),
                _etf_holding(_STOCK_B, Decimal("0.20")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        second = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[
                _etf_holding(_STOCK_A, Decimal("0.10")),
                _etf_holding(_STOCK_C, Decimal("0.20")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        third = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_B,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[
                _etf_holding(_STOCK_A, Decimal("0.10")),
                _etf_holding(_STOCK_B, Decimal("0.20")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert first.content_hash != second.content_hash
        assert first.content_hash != third.content_hash
        assert second.content_hash != third.content_hash

    def test_create_accepts_generator_input(self) -> None:
        snapshot = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=(
                _etf_holding(code, Decimal("0.10"))
                for code in (_STOCK_C, _STOCK_A, _STOCK_B)
            ),
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert [h.stock_code for h in snapshot.holdings] == [
            _STOCK_A,
            _STOCK_B,
            _STOCK_C,
        ]

    def test_create_rejects_empty_holdings(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            EtfHoldingSnapshot.create(
                etf_id=_ETF_ID_A,
                as_of_date=_AS_OF_DATE,
                observed_at=_OBSERVED_AT,
                holdings=[],
                provenance=_provenance(),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_duplicate_stock_codes(self) -> None:
        with pytest.raises(ValueError, match="duplicates"):
            EtfHoldingSnapshot.create(
                etf_id=_ETF_ID_A,
                as_of_date=_AS_OF_DATE,
                observed_at=_OBSERVED_AT,
                holdings=[
                    _etf_holding(_STOCK_A, Decimal("0.10")),
                    _etf_holding(_STOCK_B, Decimal("0.20")),
                    _etf_holding(_STOCK_A, Decimal("0.30")),
                ],
                provenance=_provenance(),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_invalid_weight_in_entry(self) -> None:
        with pytest.raises((TypeError, ValueError)):
            EtfHoldingSnapshot.create(
                etf_id=_ETF_ID_A,
                as_of_date=_AS_OF_DATE,
                observed_at=_OBSERVED_AT,
                holdings=[
                    _etf_holding(_STOCK_A, Decimal("0.10")),
                    EtfHolding(
                        stock_code=_STOCK_B, weight=Decimal("-0.10")
                    ),
                ],
                provenance=_provenance(),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_non_uuid_etf_id(self) -> None:
        with pytest.raises((TypeError, ValueError)):
            EtfHoldingSnapshot.create(
                etf_id="not-a-uuid",  # type: ignore[arg-type]
                as_of_date=_AS_OF_DATE,
                observed_at=_OBSERVED_AT,
                holdings=[_etf_holding(_STOCK_A, Decimal("0.10"))],
                provenance=_provenance(),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_invalid_as_of_date(self) -> None:
        with pytest.raises((TypeError, ValueError)):
            EtfHoldingSnapshot.create(
                etf_id=_ETF_ID_A,
                as_of_date="2026-07-31",  # type: ignore[arg-type]
                observed_at=_OBSERVED_AT,
                holdings=[_etf_holding(_STOCK_A, Decimal("0.10"))],
                provenance=_provenance(),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_naive_observed_at(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            EtfHoldingSnapshot.create(
                etf_id=_ETF_ID_A,
                as_of_date=_AS_OF_DATE,
                observed_at=datetime(2026, 7, 31, 12, 0, 0),
                holdings=[_etf_holding(_STOCK_A, Decimal("0.10"))],
                provenance=_provenance(),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_empty_provenance(self) -> None:
        with pytest.raises(ValueError):
            EtfHoldingSnapshot.create(
                etf_id=_ETF_ID_A,
                as_of_date=_AS_OF_DATE,
                observed_at=_OBSERVED_AT,
                holdings=[_etf_holding(_STOCK_A, Decimal("0.10"))],
                provenance=_provenance(dataset_key=""),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_factory_defaults_match_expectations(self) -> None:
        snapshot = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[_etf_holding(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
        )
        assert isinstance(snapshot.id, UUID)
        assert snapshot.created_at.tzinfo is not None
        assert snapshot.created_at.utcoffset() == UTC.utcoffset(
            snapshot.created_at
        )
        assert snapshot.created_at <= datetime.now(timezone.utc)


class TestEtfHoldingSnapshotValidation:
    def test_direct_construction_accepts_valid_payload(self) -> None:
        snapshot = DirectEtfHoldingSnapshot(**_etf_holding_snapshot_kwargs())
        assert snapshot.id == _FIXED_SNAPSHOT_ID
        assert snapshot.etf_id == _ETF_ID_A
        assert snapshot.as_of_date == _AS_OF_DATE
        assert snapshot.observed_at == _OBSERVED_AT
        assert len(snapshot.holdings) == 2

    def test_empty_holdings_is_rejected(self) -> None:
        kwargs = _etf_holding_snapshot_kwargs()
        kwargs["holdings"] = ()
        with pytest.raises(ValueError, match="must not be empty"):
            DirectEtfHoldingSnapshot(**kwargs)

    def test_duplicate_stock_codes_is_rejected(self) -> None:
        kwargs = _etf_holding_snapshot_kwargs()
        kwargs["holdings"] = (
            _etf_holding(_STOCK_A, Decimal("0.10")),
            _etf_holding(_STOCK_A, Decimal("0.20")),
        )
        with pytest.raises(ValueError, match="duplicates"):
            DirectEtfHoldingSnapshot(**kwargs)

    def test_non_tuple_holdings_is_rejected(self) -> None:
        kwargs = _etf_holding_snapshot_kwargs()
        kwargs["holdings"] = [  # type: ignore[assignment]
            _etf_holding(_STOCK_A, Decimal("0.10"))
        ]
        with pytest.raises(ValueError, match="must be a tuple"):
            DirectEtfHoldingSnapshot(**kwargs)

    def test_non_uuid_etf_id_is_rejected(self) -> None:
        kwargs = _etf_holding_snapshot_kwargs()
        kwargs["etf_id"] = "not-a-uuid"  # type: ignore[assignment]
        with pytest.raises((TypeError, ValueError), match="etf_id"):
            DirectEtfHoldingSnapshot(**kwargs)

    def test_non_date_as_of_date_is_rejected(self) -> None:
        kwargs = _etf_holding_snapshot_kwargs()
        kwargs["as_of_date"] = "2026-07-31"  # type: ignore[assignment]
        with pytest.raises((TypeError, ValueError), match="as_of_date"):
            DirectEtfHoldingSnapshot(**kwargs)

    def test_naive_created_at_is_rejected(self) -> None:
        kwargs = _etf_holding_snapshot_kwargs()
        kwargs["created_at"] = datetime(2026, 8, 1, 0, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            DirectEtfHoldingSnapshot(**kwargs)

    def test_content_hash_wrong_length_is_rejected(self) -> None:
        kwargs = _etf_holding_snapshot_kwargs()
        kwargs["content_hash"] = "abcd"
        with pytest.raises(ValueError, match="64"):
            DirectEtfHoldingSnapshot(**kwargs)

    def test_content_hash_too_long_is_rejected(self) -> None:
        kwargs = _etf_holding_snapshot_kwargs()
        kwargs["content_hash"] = "a" * 65
        with pytest.raises(ValueError, match="64"):
            DirectEtfHoldingSnapshot(**kwargs)

    def test_non_string_content_hash_is_rejected(self) -> None:
        kwargs = _etf_holding_snapshot_kwargs()
        kwargs["content_hash"] = 12345  # type: ignore[assignment]
        with pytest.raises(TypeError, match="must be a str"):
            DirectEtfHoldingSnapshot(**kwargs)

    def test_supplied_mismatching_hash_is_rejected(self) -> None:
        kwargs = _etf_holding_snapshot_kwargs()
        kwargs["content_hash"] = "0" * _CONTENT_HASH_HEX_LEN
        with pytest.raises(ValueError, match="does not match"):
            DirectEtfHoldingSnapshot(**kwargs)


class TestExposureWeightIndependence:
    def test_index_constituent_and_etf_holding_are_distinct_types(self) -> None:
        constituent = _index_constituent()
        holding = _etf_holding()
        assert isinstance(constituent, IndexConstituent)
        assert isinstance(holding, EtfHolding)
        assert not isinstance(constituent, EtfHolding)
        assert not isinstance(holding, IndexConstituent)
        assert type(constituent) is not type(holding)

    def test_identical_numeric_weights_produce_distinct_hashes(self) -> None:
        constituent_snapshot = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[_index_constituent(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        holding_snapshot = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[_etf_holding(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert (
            constituent_snapshot.content_hash != holding_snapshot.content_hash
        )

    def test_index_constituent_snapshot_has_no_etf_field(self) -> None:
        snapshot = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[_index_constituent(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert not hasattr(snapshot, "etf_id")
        assert not hasattr(snapshot, "holdings")

    def test_etf_holding_snapshot_has_no_index_field(self) -> None:
        snapshot = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[_etf_holding(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert not hasattr(snapshot, "index_code")
        assert not hasattr(snapshot, "constituents")

    def test_etf_index_mapping_excludes_weight_slots(self) -> None:
        mapping = EtfIndexMapping(**_etf_index_mapping_kwargs())
        forbidden = (
            "index_weight",
            "constituent_weight",
            "weight",
            "weights",
            "constituents",
            "holdings",
        )
        for attribute in forbidden:
            assert not hasattr(mapping, attribute), (
                f"EtfIndexMapping must not expose a {attribute!r} slot "
                "(the mapping records validity only)"
            )


class TestExposureContentHashDeterminism:
    def test_repeat_index_snapshot_create_produces_same_hash(self) -> None:
        first = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                _index_constituent(_STOCK_A, Decimal("0.10")),
                _index_constituent(_STOCK_B, Decimal("0.20")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        second = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                _index_constituent(_STOCK_B, Decimal("0.20")),
                _index_constituent(_STOCK_A, Decimal("0.10")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert first.content_hash == second.content_hash

    def test_repeat_etf_holding_snapshot_create_produces_same_hash(self) -> None:
        first = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[
                _etf_holding(_STOCK_A, Decimal("0.10")),
                _etf_holding(_STOCK_B, Decimal("0.20")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        second = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[
                _etf_holding(_STOCK_B, Decimal("0.20")),
                _etf_holding(_STOCK_A, Decimal("0.10")),
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert first.content_hash == second.content_hash

    def test_repeat_index_profile_create_produces_same_hash(self) -> None:
        first = IndexProfile(**_index_profile_kwargs())
        second = IndexProfile(**_index_profile_kwargs())
        assert first.content_hash == second.content_hash

    def test_repeat_etf_index_mapping_create_produces_same_hash(self) -> None:
        first = EtfIndexMapping(**_etf_index_mapping_kwargs())
        second = EtfIndexMapping(**_etf_index_mapping_kwargs())
        assert first.content_hash == second.content_hash

    def test_index_snapshot_hash_is_sensitive_to_weights(self) -> None:
        first = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[_index_constituent(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        second = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[_index_constituent(_STOCK_A, Decimal("0.20"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert first.content_hash != second.content_hash

    def test_etf_holding_snapshot_hash_is_sensitive_to_weights(self) -> None:
        first = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[_etf_holding(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        second = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[_etf_holding(_STOCK_A, Decimal("0.20"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert first.content_hash != second.content_hash

    def test_index_snapshot_hash_is_sensitive_to_as_of_date(self) -> None:
        first = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[_index_constituent(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        second = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_EARLIER_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[_index_constituent(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert first.content_hash != second.content_hash

    def test_etf_holding_snapshot_hash_is_sensitive_to_observed_at(self) -> None:
        first = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[_etf_holding(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        second = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_EARLIER_OBSERVED_AT,
            holdings=[_etf_holding(_STOCK_A, Decimal("0.10"))],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert first.content_hash != second.content_hash

    def test_index_snapshot_hash_is_sensitive_to_industry(self) -> None:
        first = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                IndexConstituent(
                    stock_code=_STOCK_A,
                    weight=Decimal("0.10"),
                    industry="白酒",
                )
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        second = IndexConstituentSnapshot.create(
            index_code=_HSI_CODE,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            constituents=[
                IndexConstituent(
                    stock_code=_STOCK_A,
                    weight=Decimal("0.10"),
                    industry="金融",
                )
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert first.content_hash != second.content_hash

    def test_etf_holding_snapshot_hash_is_sensitive_to_industry(self) -> None:
        first = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[
                EtfHolding(
                    stock_code=_STOCK_A,
                    weight=Decimal("0.10"),
                    industry="白酒",
                )
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        second = EtfHoldingSnapshot.create(
            etf_id=_ETF_ID_A,
            as_of_date=_AS_OF_DATE,
            observed_at=_OBSERVED_AT,
            holdings=[
                EtfHolding(
                    stock_code=_STOCK_A,
                    weight=Decimal("0.10"),
                    industry="金融",
                )
            ],
            provenance=_provenance(),
            id_factory=_fixed_snapshot_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert first.content_hash != second.content_hash


class TestExposurePackageReExport:
    def test_exposure_package_reexports_public_types(self) -> None:
        from invest_domain.exposure import (  # noqa: F401
            EtfHolding as ReExportedEtfHolding,
            EtfHoldingSnapshot as ReExportedEtfHoldingSnapshot,
            EtfIndexMapping as ReExportedEtfIndexMapping,
            ExposureProvenance as ReExportedExposureProvenance,
            IndexConstituent as ReExportedIndexConstituent,
            IndexConstituentSnapshot as ReExportedIndexConstituentSnapshot,
            IndexProfile as ReExportedIndexProfile,
        )

        assert ReExportedIndexProfile is DirectIndexProfile
        assert ReExportedIndexConstituent is DirectIndexConstituent
        assert ReExportedIndexConstituentSnapshot is DirectIndexConstituentSnapshot
        assert ReExportedEtfIndexMapping is DirectEtfIndexMapping
        assert ReExportedEtfHolding is DirectEtfHolding
        assert ReExportedEtfHoldingSnapshot is DirectEtfHoldingSnapshot
        assert ReExportedExposureProvenance is DirectExposureProvenance

    def test_invest_domain_package_reexposes_exposure_types(self) -> None:
        from invest_domain import (  # noqa: F401
            EtfHolding as DomainEtfHolding,
            EtfHoldingSnapshot as DomainEtfHoldingSnapshot,
            EtfIndexMapping as DomainEtfIndexMapping,
            ExposureProvenance as DomainExposureProvenance,
            IndexConstituent as DomainIndexConstituent,
            IndexConstituentSnapshot as DomainIndexConstituentSnapshot,
            IndexProfile as DomainIndexProfile,
        )

        assert DomainIndexProfile is DirectIndexProfile
        assert DomainIndexConstituent is DirectIndexConstituent
        assert DomainIndexConstituentSnapshot is DirectIndexConstituentSnapshot
        assert DomainEtfIndexMapping is DirectEtfIndexMapping
        assert DomainEtfHolding is DirectEtfHolding
        assert DomainEtfHoldingSnapshot is DirectEtfHoldingSnapshot
        assert DomainExposureProvenance is DirectExposureProvenance


class TestIndexProfileProvenanceRequiredContract:
    """IndexProfile.provenance is a bare, non-Optional ExposureProvenance annotation."""

    def test_provenance_annotation_is_exactly_exposure_provenance(self) -> None:
        from typing import get_type_hints

        assert (
            get_type_hints(DirectIndexProfile)["provenance"]
            is ExposureProvenance
        )


class TestExposureProvenanceSourceBatchIdAffectsHash:
    """source_batch_id embedded in provenance participates in content_hash for every contract."""

    def test_index_profile_hash_changes_with_source_batch_id(self) -> None:
        base = _index_profile_kwargs()
        alt = _index_profile_kwargs(
            provenance=_provenance(source_batch_id=_ALT_SOURCE_BATCH_ID)
        )
        assert (
            IndexProfile(**base).content_hash
            != IndexProfile(**alt).content_hash
        )

    def test_etf_index_mapping_hash_changes_with_source_batch_id(self) -> None:
        base = _etf_index_mapping_kwargs()
        alt = _etf_index_mapping_kwargs(
            provenance=_provenance(source_batch_id=_ALT_SOURCE_BATCH_ID)
        )
        assert (
            EtfIndexMapping(**base).content_hash
            != EtfIndexMapping(**alt).content_hash
        )

    def test_index_constituent_snapshot_hash_changes_with_source_batch_id(
        self,
    ) -> None:
        constituents = (
            _index_constituent(_STOCK_A, Decimal("0.10")),
            _index_constituent(_STOCK_B, Decimal("0.20")),
        )

        def make(source_batch_id):
            return IndexConstituentSnapshot.create(
                index_code=_HSI_CODE,
                as_of_date=_AS_OF_DATE,
                observed_at=_OBSERVED_AT,
                constituents=constituents,
                provenance=_provenance(source_batch_id=source_batch_id),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

        assert (
            make(_FIXED_SOURCE_BATCH_ID).content_hash
            != make(_ALT_SOURCE_BATCH_ID).content_hash
        )

    def test_etf_holding_snapshot_hash_changes_with_source_batch_id(
        self,
    ) -> None:
        holdings = (
            _etf_holding(_STOCK_A, Decimal("0.10")),
            _etf_holding(_STOCK_B, Decimal("0.20")),
        )

        def make(source_batch_id):
            return EtfHoldingSnapshot.create(
                etf_id=_ETF_ID_A,
                as_of_date=_AS_OF_DATE,
                observed_at=_OBSERVED_AT,
                holdings=holdings,
                provenance=_provenance(source_batch_id=source_batch_id),
                id_factory=_fixed_snapshot_id_factory,
                now_factory=_fixed_now_factory,
            )

        assert (
            make(_FIXED_SOURCE_BATCH_ID).content_hash
            != make(_ALT_SOURCE_BATCH_ID).content_hash
        )


class TestExposureSnapshotDirectConstructionNormalization:
    """Direct snapshot construction sorts entries; reordered input yields identical hash."""

    def test_index_constituent_snapshot_direct_is_order_independent(self) -> None:
        ordered = DirectIndexConstituentSnapshot(
            **_index_constituent_snapshot_kwargs(
                constituents=(
                    _index_constituent(_STOCK_A, Decimal("0.10")),
                    _index_constituent(_STOCK_B, Decimal("0.20")),
                    _index_constituent(_STOCK_C, Decimal("0.30")),
                    _index_constituent(_STOCK_D, Decimal("0.40")),
                )
            )
        )
        shuffled = DirectIndexConstituentSnapshot(
            **_index_constituent_snapshot_kwargs(
                constituents=tuple(reversed(ordered.constituents))
            )
        )
        assert ordered.constituents == shuffled.constituents
        assert ordered.content_hash == shuffled.content_hash

    def test_etf_holding_snapshot_direct_is_order_independent(self) -> None:
        ordered = DirectEtfHoldingSnapshot(
            **_etf_holding_snapshot_kwargs(
                holdings=(
                    _etf_holding(_STOCK_A, Decimal("0.10")),
                    _etf_holding(_STOCK_B, Decimal("0.20")),
                    _etf_holding(_STOCK_C, Decimal("0.30")),
                    _etf_holding(_STOCK_D, Decimal("0.40")),
                )
            )
        )
        shuffled = DirectEtfHoldingSnapshot(
            **_etf_holding_snapshot_kwargs(
                holdings=tuple(reversed(ordered.holdings))
            )
        )
        assert ordered.holdings == shuffled.holdings
        assert ordered.content_hash == shuffled.content_hash
