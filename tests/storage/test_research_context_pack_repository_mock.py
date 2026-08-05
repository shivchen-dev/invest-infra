from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

from invest_domain.instruments import InstrumentId
from invest_domain.research import (
    ContextItem,
    ContextValueType,
    QualityStatus,
    ResearchContextPack,
)
from invest_storage import (
    ResearchContextItemRow,
    ResearchContextPackRow,
    SqlAlchemyResearchContextPackRepository,
    SqlAlchemyUnitOfWork,
)
from sqlalchemy.orm import Session

OBSERVED_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def item(value: object, value_type: ContextValueType, key: str) -> ContextItem:
    return ContextItem(
        context_type="fundamental",
        key=key,
        value=value,
        value_type=value_type,
        source_provider="provider-a",
        source_dataset="context-v1",
        observed_at=OBSERVED_AT,
        source_batch_id=uuid4(),
        source_revision=2,
        quality_status=QualityStatus.COMPLETE,
        confidence_score=Decimal("0.9"),
        evidence_refs=("evidence:1",),
    )


def pack(*, instrument_id: InstrumentId | None = None, version: int = 1) -> ResearchContextPack:
    return ResearchContextPack(
        instrument_id=instrument_id or InstrumentId(uuid4()),
        context_version=version,
        items=(
            item("ready", ContextValueType.TEXT, "status"),
            item(Decimal("1.25"), ContextValueType.DECIMAL, "ratio"),
            item(date(2026, 8, 5), ContextValueType.DATE, "as_of"),
            item({"nested": True}, ContextValueType.JSON, "metadata"),
        ),
        missing_reason="none",
    )


def rows_for(value: ResearchContextPack, pack_id=None):
    pack_row = MagicMock(spec=ResearchContextPackRow)
    pack_row.id = pack_id or uuid4()
    pack_row.instrument_id = value.instrument_id.value
    pack_row.schema_version = value.schema_version
    pack_row.context_version = value.context_version
    pack_row.content_hash = value.content_hash
    pack_row.created_at = OBSERVED_AT
    pack_row.missing_reason = value.missing_reason
    item_rows = []
    for context_item in value.items:
        row = MagicMock(spec=ResearchContextItemRow)
        row.id = uuid4()
        row.pack_id = pack_row.id
        row.context_type = context_item.context_type
        row.key = context_item.key
        row.value_type = context_item.value_type.value
        row.value = (
            str(context_item.value)
            if context_item.value_type in (ContextValueType.DECIMAL, ContextValueType.DATE)
            else context_item.value
        )
        row.evidence_refs = list(context_item.evidence_refs)
        row.source_provider = context_item.source_provider
        row.source_dataset = context_item.source_dataset
        row.source_batch_id = context_item.source_batch_id
        row.source_revision = context_item.source_revision
        row.observed_at = context_item.observed_at
        row.quality_status = context_item.quality_status.value
        row.confidence_score = context_item.confidence_score
        row.item_hash = context_item.item_hash
        item_rows.append(row)
    return pack_row, item_rows


class ResearchContextPackRepositoryMockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(spec=Session)
        self.repo = SqlAlchemyResearchContextPackRepository(self.session)

    def assert_same_content(
        self, expected: ResearchContextPack, actual: ResearchContextPack
    ) -> None:
        self.assertEqual(actual.instrument_id, expected.instrument_id)
        self.assertEqual(actual.context_version, expected.context_version)
        self.assertEqual(actual.content_hash, expected.content_hash)
        self.assertEqual(actual.items, expected.items)
        self.assertEqual(actual.missing_reason, expected.missing_reason)

    def test_add_persists_items_and_same_hash_is_idempotent(self) -> None:
        value = pack()
        persisted_id = uuid4()
        self.session.execute.return_value.scalar_one_or_none.return_value = persisted_id
        self.assertEqual(self.repo.add(value), value)
        self.assertEqual(self.session.execute.call_count, 1 + len(value.items))
        self.session.execute.reset_mock()
        pack_row, item_rows = rows_for(value, persisted_id)
        self.session.scalars.return_value.first.return_value = pack_row
        self.session.scalars.return_value.all.return_value = item_rows
        self.assert_same_content(value, self.repo.upsert(value))
        self.session.execute.assert_not_called()

    def test_add_leaves_created_at_to_database_when_pack_does_not_provide_one(self) -> None:
        value = ResearchContextPack(
            instrument_id=InstrumentId(uuid4()),
            items=(item("ready", ContextValueType.TEXT, "status"),),
        )
        self.session.execute.return_value.scalar_one_or_none.return_value = uuid4()

        self.repo.add(value)

        statement = self.session.execute.call_args.args[0]
        self.assertNotIn("created_at", statement.compile().params)

    def test_distinct_versions_coexist_and_queries_map_domain(self) -> None:
        instrument_id = InstrumentId(uuid4())
        first = pack(instrument_id=instrument_id, version=1)
        second = pack(instrument_id=instrument_id, version=2)
        self.assertNotEqual(first.content_hash, second.content_hash)
        self.session.execute.return_value.scalar_one_or_none.side_effect = [uuid4(), uuid4()]
        self.assertEqual(self.repo.add(first), first)
        self.assertEqual(self.repo.add(second), second)
        first_row, first_items = rows_for(first)
        second_row, second_items = rows_for(second)
        self.session.scalars.return_value.first.return_value = first_row
        self.session.scalars.return_value.all.return_value = first_items
        self.assert_same_content(
            first, self.repo.get_by_instrument_and_version(instrument_id.value, 1)
        )
        self.session.scalars.return_value.all.return_value = [first_row, second_row]
        self.session.scalars.return_value.side_effect = None
        self.session.scalars.return_value.all.side_effect = [
            [first_row, second_row],
            first_items,
            second_items,
        ]
        result = self.repo.list_by_instrument(instrument_id.value)
        self.assertEqual([value.context_version for value in result], [1, 2])

    def test_item_and_provenance_round_trip(self) -> None:
        value = pack()
        pack_row, item_rows = rows_for(value)
        self.session.get.return_value = pack_row
        self.session.scalars.return_value.all.return_value = item_rows
        result = self.repo.get_by_id(pack_row.id)
        self.assert_same_content(value, result)
        self.assertEqual(result.items, value.items)

    def test_uow_exposes_cached_repository(self) -> None:
        session = MagicMock(spec=Session)
        uow = SqlAlchemyUnitOfWork(lambda: session)
        with uow:
            self.assertIs(uow.research_context_packs, uow.research_context_packs)
            self.assertIsInstance(
                uow.research_context_packs, SqlAlchemyResearchContextPackRepository
            )


if __name__ == "__main__":
    unittest.main()
