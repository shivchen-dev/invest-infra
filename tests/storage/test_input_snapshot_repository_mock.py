from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.input_snapshot import InputSnapshot
from invest_storage import InputSnapshotRepository, InputSnapshotRow
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


_SNAPSHOT_DATE = date(2026, 7, 31)
_CREATED_AT = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)


def _make_snapshot(*, snapshot_id: UUID | None = None) -> InputSnapshot:
    return InputSnapshot.create(
        _SNAPSHOT_DATE,
        [
            UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
            UUID("00000000-0000-0000-0000-000000000001"),
        ],
        id_factory=lambda: snapshot_id or uuid4(),
        now_factory=lambda: _CREATED_AT,
    )


def _make_row(snapshot: InputSnapshot) -> MagicMock:
    row = MagicMock(spec=InputSnapshotRow)
    row.id = snapshot.id
    row.snapshot_date = snapshot.snapshot_date
    row.instrument_ids = [str(value) for value in snapshot.instrument_ids]
    row.content_hash = snapshot.content_hash
    row.row_count = snapshot.row_count
    row.created_at = snapshot.created_at
    return row


class InputSnapshotRepositoryMockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._session = MagicMock(spec=Session)
        self._repo = InputSnapshotRepository(self._session)

    def test_add_inserts_json_compatible_row_and_returns_domain_model(self) -> None:
        snapshot = _make_snapshot()
        self._session.scalars.return_value.first.return_value = None

        result = self._repo.add(snapshot)

        self._session.add.assert_called_once()
        self._session.flush.assert_called_once_with()
        row = self._session.add.call_args.args[0]
        self.assertIsInstance(row, InputSnapshotRow)
        self.assertEqual(row.id, snapshot.id)
        self.assertEqual(row.snapshot_date, snapshot.snapshot_date)
        self.assertEqual(
            row.instrument_ids,
            [str(value) for value in snapshot.instrument_ids],
        )
        self.assertEqual(row.content_hash, snapshot.content_hash)
        self.assertEqual(row.row_count, snapshot.row_count)
        self.assertEqual(result, snapshot)

    def test_add_returns_existing_without_insert(self) -> None:
        snapshot = _make_snapshot()
        existing = _make_snapshot(snapshot_id=uuid4())
        self._session.scalars.return_value.first.return_value = _make_row(existing)

        result = self._repo.add(snapshot)

        self.assertEqual(result, existing)
        self._session.add.assert_not_called()
        self._session.flush.assert_not_called()

    def test_add_returns_existing_after_unique_conflict(self) -> None:
        snapshot = _make_snapshot()
        existing = _make_snapshot(snapshot_id=uuid4())
        self._session.scalars.return_value.first.side_effect = [
            None,
            _make_row(existing),
        ]
        self._session.flush.side_effect = IntegrityError(
            "INSERT",
            {},
            Exception("uq_input_snapshots_date_hash"),
        )

        result = self._repo.add(snapshot)

        self.assertEqual(result, existing)
        self._session.rollback.assert_called_once_with()
        self.assertEqual(self._session.scalars.call_count, 2)

    def test_get_by_date_and_hash_maps_row(self) -> None:
        snapshot = _make_snapshot()
        self._session.scalars.return_value.first.return_value = _make_row(snapshot)

        result = self._repo.get_by_date_and_hash(
            snapshot.snapshot_date,
            snapshot.content_hash,
        )

        self.assertEqual(result, snapshot)
        self._session.scalars.assert_called_once()

    def test_get_by_date_and_hash_returns_none(self) -> None:
        self._session.scalars.return_value.first.return_value = None

        result = self._repo.get_by_date_and_hash(_SNAPSHOT_DATE, "a" * 64)

        self.assertIsNone(result)

    def test_list_by_date_maps_all_rows(self) -> None:
        first = _make_snapshot()
        second = _make_snapshot(snapshot_id=uuid4())
        self._session.scalars.return_value.all.return_value = [
            _make_row(first),
            _make_row(second),
        ]

        result = self._repo.list_by_date(_SNAPSHOT_DATE)

        self.assertEqual(result, [first, second])
        self._session.scalars.return_value.all.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
