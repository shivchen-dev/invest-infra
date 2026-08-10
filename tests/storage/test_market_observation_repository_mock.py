from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)
from invest_storage import (
    MarketObservationRow,
    MarketObservationSnapshotRow,
    SqlAlchemyMarketObservationSnapshotRepository,
)
from sqlalchemy.orm import Session

_AS_OF = date(2026, 8, 7)
_CREATED_AT = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)
_INPUT_SNAPSHOT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _make_observations() -> tuple[MarketObservation, ...]:
    return (
        MarketObservation(
            observation_key="breadth",
            value=Decimal("0.5"),
            unit="ratio",
            observed_date=_AS_OF,
            source_kind="computed",
            source_ref="calc:market_temperature",
        ),
        MarketObservation(
            observation_key="label",
            value="warm",
            unit="text",
            observed_date=_AS_OF,
            source_kind="computed",
            source_ref="calc:market_temperature",
        ),
        MarketObservation(
            observation_key="note_missing",
            value=None,
            unit="text",
            observed_date=_AS_OF,
            source_kind="computed",
            source_ref="calc:market_temperature",
        ),
    )


def _make_snapshot() -> MarketObservationSnapshot:
    return MarketObservationSnapshot(
        input_snapshot_id=_INPUT_SNAPSHOT_ID,
        as_of_date=_AS_OF,
        observations=_make_observations(),
    )


def _make_parent_row(snapshot: MarketObservationSnapshot, row_id: UUID) -> MagicMock:
    row = MagicMock(spec=MarketObservationSnapshotRow)
    row.id = row_id
    row.snapshot_id = snapshot.snapshot_id
    row.input_snapshot_id = UUID(str(snapshot.input_snapshot_id))
    row.as_of_date = snapshot.as_of_date
    row.algorithm_version = snapshot.algorithm_version
    row.scope_type = snapshot.scope_type
    row.scope_key = snapshot.scope_key
    row.quality_status = snapshot.quality_status.value
    row.freshness_status = snapshot.freshness_status.value
    row.content_hash = snapshot.content_hash
    row.created_at = _CREATED_AT
    return row


def _make_child_row(observation: MarketObservation, snapshot_row_id: UUID) -> MagicMock:
    row = MagicMock(spec=MarketObservationRow)
    row.id = uuid4()
    row.snapshot_id = snapshot_row_id
    row.observation_key = observation.observation_key
    row.value_numeric = (
        observation.value if isinstance(observation.value, Decimal) else None
    )
    row.value_text = observation.value if isinstance(observation.value, str) else None
    row.unit = observation.unit
    row.observed_date = observation.observed_date
    row.source_kind = observation.source_kind
    row.source_ref = observation.source_ref
    row.quality_status = observation.quality_status.value
    row.item_hash = observation.item_hash
    row.created_at = _CREATED_AT
    return row


def _make_rows(
    snapshot: MarketObservationSnapshot,
) -> tuple[MagicMock, list[MagicMock]]:
    row_id = uuid4()
    parent = _make_parent_row(snapshot, row_id)
    children = [_make_child_row(item, row_id) for item in snapshot.observations]
    return parent, children


class MarketObservationSnapshotRepositoryMockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._session = MagicMock(spec=Session)
        self._repo = SqlAlchemyMarketObservationSnapshotRepository(self._session)

    def test_add_inserts_parent_and_children_and_returns_domain_model(self) -> None:
        snapshot = _make_snapshot()
        inserted_id = uuid4()
        self._session.execute.return_value.scalar_one_or_none.return_value = inserted_id

        result = self._repo.add(snapshot)

        # 1 parent insert + 1 insert per child observation.
        self.assertEqual(self._session.execute.call_count, 1 + len(snapshot.observations))
        parent_statement = self._session.execute.call_args_list[0].args[0]
        params = parent_statement.compile().params
        self.assertEqual(params["snapshot_id"], snapshot.snapshot_id)
        self.assertEqual(
            params["input_snapshot_id"], UUID(str(snapshot.input_snapshot_id))
        )
        self.assertEqual(params["as_of_date"], snapshot.as_of_date)
        self.assertEqual(params["algorithm_version"], snapshot.algorithm_version)
        self.assertEqual(params["scope_type"], snapshot.scope_type)
        self.assertEqual(params["scope_key"], snapshot.scope_key)
        self.assertEqual(params["quality_status"], snapshot.quality_status.value)
        self.assertEqual(params["freshness_status"], snapshot.freshness_status.value)
        self.assertEqual(params["content_hash"], snapshot.content_hash)
        for call, observation in zip(
            self._session.execute.call_args_list[1:],
            snapshot.observations,
            strict=True,
        ):
            child_params = call.args[0].compile().params
            self.assertEqual(child_params["snapshot_id"], inserted_id)
            self.assertEqual(
                child_params["observation_key"], observation.observation_key
            )
            self.assertEqual(child_params["item_hash"], observation.item_hash)
            self.assertEqual(child_params["unit"], observation.unit)
        self._session.flush.assert_called_once()
        self.assertEqual(result, snapshot)
        self._session.rollback.assert_not_called()

    def test_add_returns_existing_after_content_hash_conflict(self) -> None:
        snapshot = _make_snapshot()
        parent, children = _make_rows(snapshot)
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        self._session.scalars.return_value.first.return_value = parent
        self._session.scalars.return_value.all.return_value = children

        result = self._repo.add(snapshot)

        self.assertEqual(result, snapshot)
        # Only the parent insert attempt; children are not re-written.
        self._session.execute.assert_called_once()
        self._session.rollback.assert_not_called()

    def test_add_raises_if_conflicting_row_disappears(self) -> None:
        snapshot = _make_snapshot()
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        self._session.scalars.return_value.first.return_value = None

        with self.assertRaises(RuntimeError):
            self._repo.add(snapshot)

        self._session.rollback.assert_not_called()

    def test_get_by_id_maps_parent_and_children(self) -> None:
        snapshot = _make_snapshot()
        parent, children = _make_rows(snapshot)
        self._session.get.return_value = parent
        self._session.scalars.return_value.all.return_value = children

        result = self._repo.get_by_id(parent.id)

        self.assertEqual(result, snapshot)
        self._session.get.assert_called_once_with(
            MarketObservationSnapshotRow, parent.id
        )

    def test_get_by_id_returns_none(self) -> None:
        self._session.get.return_value = None

        result = self._repo.get_by_id(uuid4())

        self.assertIsNone(result)

    def test_get_by_content_hash_maps_row(self) -> None:
        snapshot = _make_snapshot()
        parent, children = _make_rows(snapshot)
        self._session.scalars.return_value.first.return_value = parent
        self._session.scalars.return_value.all.return_value = children

        result = self._repo.get_by_content_hash(snapshot.content_hash)

        self.assertEqual(result, snapshot)

    def test_get_by_content_hash_returns_none(self) -> None:
        self._session.scalars.return_value.first.return_value = None

        result = self._repo.get_by_content_hash("a" * 64)

        self.assertIsNone(result)

    def test_list_by_date_maps_all_rows(self) -> None:
        snapshot = _make_snapshot()
        parent, children = _make_rows(snapshot)
        parent_result = MagicMock()
        parent_result.all.return_value = [parent]
        children_result = MagicMock()
        children_result.all.return_value = children
        self._session.scalars.side_effect = [parent_result, children_result]

        result = self._repo.list_by_date(_AS_OF)

        self.assertEqual(result, [snapshot])

    def test_list_by_date_returns_empty_list(self) -> None:
        self._session.scalars.return_value.all.return_value = []

        result = self._repo.list_by_date(_AS_OF)

        self.assertEqual(result, [])

    def test_get_latest_for_scope_filters_by_scope_type_and_scope_key(self) -> None:
        snapshot = _make_snapshot()
        parent, children = _make_rows(snapshot)
        parent_result = MagicMock()
        parent_result.first.return_value = parent
        children_result = MagicMock()
        children_result.all.return_value = children
        self._session.scalars.side_effect = [parent_result, children_result]

        returned = self._repo.get_latest_for_scope(
            "ashare_universe", "ashare_active_universe_v1"
        )

        self.assertEqual(returned, snapshot)
        # Two scalars calls: one for the filtered parent lookup, one
        # for the eager child re-read inside _row_to_snapshot.
        self.assertEqual(self._session.scalars.call_count, 2)
        first_statement = self._session.scalars.call_args_list[0].args[0]
        compiled = first_statement.compile()
        params = compiled.params
        self.assertEqual(params["scope_type_1"], "ashare_universe")
        self.assertEqual(params["scope_key_1"], "ashare_active_universe_v1")
        # No as_of_date filter applied when caller passes None.
        self.assertNotIn("as_of_date_1", params)
        # Ordering is as_of_date DESC, created_at DESC, id DESC.
        compiled_sql = str(compiled)
        self.assertIn(
            "ORDER BY analytics.market_observation_snapshots.as_of_date DESC",
            compiled_sql,
        )
        self.assertIn(
            "analytics.market_observation_snapshots.created_at DESC",
            compiled_sql,
        )
        self.assertIn(
            "analytics.market_observation_snapshots.id DESC",
            compiled_sql,
        )

    def test_get_latest_for_scope_passes_as_of_date_through(self) -> None:
        snapshot = _make_snapshot()
        parent, children = _make_rows(snapshot)
        parent_result = MagicMock()
        parent_result.first.return_value = parent
        children_result = MagicMock()
        children_result.all.return_value = children
        self._session.scalars.side_effect = [parent_result, children_result]

        returned = self._repo.get_latest_for_scope(
            "ashare_universe",
            "ashare_active_universe_v1",
            as_of_date=_AS_OF,
        )

        self.assertEqual(returned, snapshot)
        first_statement = self._session.scalars.call_args_list[0].args[0]
        params = first_statement.compile().params
        self.assertEqual(params["as_of_date_1"], _AS_OF)

    def test_get_latest_for_scope_returns_none_when_no_row(self) -> None:
        result = MagicMock()
        result.first.return_value = None
        self._session.scalars.return_value = result

        returned = self._repo.get_latest_for_scope(
            "ashare_universe", "ashare_active_universe_v1"
        )

        self.assertIsNone(returned)


if __name__ == "__main__":
    unittest.main()
