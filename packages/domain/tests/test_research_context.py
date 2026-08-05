from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from invest_domain.instruments import InstrumentId
from invest_domain.research import (
    ContextItem,
    ContextValueType,
    QualityStatus,
    ResearchContextPack,
    canonical_context_pack_json,
    compute_context_item_hash,
    compute_context_pack_hash,
)


def _item(**overrides: object) -> ContextItem:
    values: dict[str, object] = {
        "context_type": "etf_profile",
        "key": "category",
        "value": "Equity",
        "value_type": ContextValueType.TEXT,
        "source_provider": "akshare",
        "source_dataset": "etf_profile",
        "observed_at": datetime(2026, 8, 5, tzinfo=UTC),
        "confidence_score": Decimal("0.9"),
    }
    values.update(overrides)
    return ContextItem(**values)  # type: ignore[arg-type]


def test_context_item_hash_is_stable_and_excludes_supplied_hash() -> None:
    item = _item(evidence_refs=("b", "a"))
    assert item.item_hash == compute_context_item_hash(item)
    assert _item(evidence_refs=("a", "b")).item_hash == item.item_hash


def test_context_item_validates_typed_values_and_confidence() -> None:
    item = _item(value=Decimal("1.50"), value_type=ContextValueType.DECIMAL)
    assert item.value == Decimal("1.50")
    assert _item(value=date(2026, 8, 5), value_type=ContextValueType.DATE).value == date(2026, 8, 5)
    with pytest.raises(ValueError):
        _item(confidence_score=Decimal("1.01"))
    with pytest.raises(ValueError):
        _item(observed_at=datetime(2026, 8, 5))


def test_empty_context_pack_is_explicit_and_hashable() -> None:
    pack = ResearchContextPack(
        instrument_id=InstrumentId(uuid4()),
        missing_reason="profile_not_collected",
    )
    assert pack.items == ()
    assert len(pack.content_hash) == 64
    assert compute_context_pack_hash(pack) == pack.content_hash


def test_context_pack_sorts_items_and_changes_on_business_revision() -> None:
    instrument_id = InstrumentId(uuid4())
    first = ResearchContextPack(
        instrument_id=instrument_id,
        items=(_item(key="z"), _item(key="a")),
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
    )
    second = ResearchContextPack(
        instrument_id=instrument_id,
        items=tuple(reversed(first.items)),
        created_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    assert [item.key for item in first.items] == ["a", "z"]
    assert first.content_hash == second.content_hash
    revised = ResearchContextPack(
        instrument_id=instrument_id,
        items=first.items,
        context_version=2,
    )
    assert revised.content_hash != first.content_hash
    assert '"items"' in canonical_context_pack_json(first)


def test_missing_quality_can_carry_null_value() -> None:
    item = _item(value=None, quality_status=QualityStatus.MISSING)
    assert item.value is None
