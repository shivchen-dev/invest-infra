"""Mock-based unit tests for the storage repositories.

These tests exercise :class:`SqlAlchemyInstrumentRepository` and
:class:`SqlAlchemyProviderBatchRepository` against a
:class:`unittest.mock.MagicMock` ``Session`` so they do not require a
live PostgreSQL connection, Testcontainers or any schema bootstrap.

Each test focuses on a single behaviour:

- The repository calls the expected ``Session`` API
  (``execute``, ``scalars``, ``get``, ``add``, ``flush``).
- ORM-to-domain mapping is applied for the read-side methods, so the
  returned domain dataclass carries the same field values as the mock
  row.
- Write paths return the right counts (number of rows actually
  upserted) and behave correctly on empty input.

The tests do not enforce SQLAlchemy 2.x statement construction in
detail: they only assert ``session.execute`` was called once per
``upsert_many`` sub-batch. That is sufficient to distinguish
``_upsert_by_id`` from ``_upsert_by_business_key``.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.instruments import (
    Instrument,
    InstrumentId,
    InstrumentStatus,
    InstrumentType,
)
from invest_domain.shared.values import Currency
from invest_storage.models import InstrumentRow, RawProviderBatchRow
from invest_storage.repositories import (
    NewProviderBatch,
    SqlAlchemyInstrumentRepository,
    SqlAlchemyProviderBatchRepository,
    StoredProviderBatch,
)


def _make_instrument(
    *,
    symbol: str = "510050",
    name: str = "SSE 50 ETF",
    exchange: str = "SSE",
    instrument_type: InstrumentType = InstrumentType.ETF,
    instrument_id: InstrumentId | None = None,
    is_active: bool = True,
    currency: Currency = Currency.CNY,
    status: InstrumentStatus = InstrumentStatus.ACTIVE,
) -> Instrument:
    """Build a minimal valid :class:`Instrument` for repository input."""

    return Instrument(
        symbol=symbol,
        name=name,
        exchange=exchange,
        instrument_type=instrument_type,
        is_active=is_active,
        instrument_id=instrument_id,
        currency=currency,
        status=status,
    )


def _make_instrument_row(
    *,
    row_id: UUID | None = None,
    symbol: str = "510050",
    name: str = "SSE 50 ETF",
    exchange: str = "SSE",
    instrument_type: str = "ETF",
    currency: str = "CNY",
    status: str = "active",
    is_active: bool = True,
    list_date: date | None = None,
    delist_date: date | None = None,
    underlying_index: str | None = None,
    category: str | None = None,
    provider_symbol_map: dict[str, Any] | None = None,
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> MagicMock:
    """Build a mock that looks like an :class:`InstrumentRow`.

    The repository's mapping helper only reads attributes (no methods),
    so a plain attribute-bearing mock is sufficient.
    """

    row = MagicMock(spec=InstrumentRow)
    row.id = row_id or uuid4()
    row.symbol = symbol
    row.name = name
    row.exchange = exchange
    row.instrument_type = instrument_type
    row.currency = currency
    row.list_date = list_date
    row.delist_date = delist_date
    row.status = status
    row.is_active = is_active
    row.underlying_index = underlying_index
    row.category = category
    row.provider_symbol_map = provider_symbol_map if provider_symbol_map is not None else {}
    row.valid_from = valid_from
    row.valid_to = valid_to
    return row


def _make_batch_row(
    *,
    row_id: UUID | None = None,
    provider_key: str = "tushare",
    dataset_key: str = "daily",
    request_key: str = "req-001",
    request_params: dict[str, Any] | None = None,
    requested_at: datetime | None = None,
    received_at: datetime | None = None,
    provider_request_id: str | None = None,
    status: str = "received",
    record_count: int | None = 10,
    raw_payload_json: Any | None = None,
    raw_payload_uri: str | None = None,
    payload_sha256: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    warnings: list[Any] | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> MagicMock:
    """Build a mock that looks like a :class:`RawProviderBatchRow`."""

    row = MagicMock(spec=RawProviderBatchRow)
    row.id = row_id or uuid4()
    row.provider_key = provider_key
    row.dataset_key = dataset_key
    row.request_key = request_key
    row.request_params = request_params if request_params is not None else {}
    row.requested_at = requested_at or datetime(2024, 1, 1, tzinfo=UTC)
    row.received_at = received_at
    row.provider_request_id = provider_request_id
    row.status = status
    row.record_count = record_count
    row.raw_payload_json = raw_payload_json
    row.raw_payload_uri = raw_payload_uri
    row.payload_sha256 = payload_sha256
    row.error_code = error_code
    row.error_message = error_message
    row.warnings = warnings if warnings is not None else []
    row.created_at = created_at or datetime(2024, 1, 1, tzinfo=UTC)
    row.updated_at = updated_at or datetime(2024, 1, 1, tzinfo=UTC)
    return row


class SqlAlchemyInstrumentRepositoryMockTests(unittest.TestCase):
    """Mock-based tests for :class:`SqlAlchemyInstrumentRepository`."""

    def setUp(self) -> None:
        self._session = MagicMock(name="Session")
        self._repo = SqlAlchemyInstrumentRepository(self._session)

    # ------------------------------------------------------------------
    # upsert_many
    # ------------------------------------------------------------------

    def test_upsert_many_with_empty_list_returns_zero_without_touching_session(self) -> None:
        result = self._repo.upsert_many([])
        self.assertEqual(result, 0)
        self._session.execute.assert_not_called()
        self._session.scalars.assert_not_called()

    def test_upsert_many_without_id_uses_business_key_path(self) -> None:
        first = _make_instrument(symbol="510050", name="SSE 50 ETF", instrument_id=None)
        second = _make_instrument(
            symbol="510300",
            name="CSI 300 ETF",
            exchange="SSE",
            instrument_id=None,
        )

        result = self._repo.upsert_many([first, second])

        self.assertEqual(result, 2)
        # business-key path uses a single INSERT ... ON CONFLICT statement
        self.assertEqual(self._session.execute.call_count, 1)
        # it must not have called get / scalars / add
        self._session.get.assert_not_called()
        self._session.scalars.assert_not_called()
        self._session.add.assert_not_called()
        self._session.flush.assert_not_called()

    def test_upsert_many_with_id_uses_id_path(self) -> None:
        explicit_id = InstrumentId.generate()
        instrument = _make_instrument(
            symbol="510300",
            name="CSI 300 ETF",
            instrument_id=explicit_id,
        )

        result = self._repo.upsert_many([instrument])

        self.assertEqual(result, 1)
        self.assertEqual(self._session.execute.call_count, 1)
        self._session.get.assert_not_called()
        self._session.add.assert_not_called()

    def test_upsert_many_mixed_input_runs_two_passes(self) -> None:
        explicit_id = InstrumentId.generate()
        no_id = _make_instrument(symbol="510050", name="Auto-id", instrument_id=None)
        with_id = _make_instrument(
            symbol="510300",
            name="Explicit-id",
            instrument_id=explicit_id,
        )

        result = self._repo.upsert_many([no_id, with_id])

        self.assertEqual(result, 2)
        # one INSERT ... ON CONFLICT for each sub-batch
        self.assertEqual(self._session.execute.call_count, 2)

    # ------------------------------------------------------------------
    # get_by_id
    # ------------------------------------------------------------------

    def test_get_by_id_returns_instrument_when_row_exists(self) -> None:
        row_id = uuid4()
        row = _make_instrument_row(
            row_id=row_id,
            symbol="510050",
            name="SSE 50 ETF",
            currency="CNY",
            status="active",
        )
        self._session.get.return_value = row

        result = self._repo.get_by_id(row_id)

        self._session.get.assert_called_once_with(InstrumentRow, row_id)
        self.assertIsNotNone(result)
        assert result is not None  # for type-checkers
        self.assertEqual(result.symbol, "510050")
        self.assertEqual(result.name, "SSE 50 ETF")
        self.assertEqual(result.exchange, "SSE")
        self.assertEqual(result.instrument_type, InstrumentType.ETF)
        self.assertEqual(result.currency, Currency.CNY)
        self.assertEqual(result.status, InstrumentStatus.ACTIVE)
        self.assertIsNotNone(result.instrument_id)
        self.assertEqual(result.instrument_id.value, row_id)
        self.assertTrue(result.is_active)

    def test_get_by_id_accepts_instrument_id_value_object(self) -> None:
        row_id = uuid4()
        instrument_id = InstrumentId(row_id)
        row = _make_instrument_row(row_id=row_id, symbol="510050")
        self._session.get.return_value = row

        result = self._repo.get_by_id(instrument_id)

        # repository unwraps InstrumentId.value before calling Session.get
        self._session.get.assert_called_once_with(InstrumentRow, row_id)
        self.assertIsNotNone(result)
        self.assertEqual(result.instrument_id.value, row_id)

    def test_get_by_id_returns_none_when_row_missing(self) -> None:
        missing = uuid4()
        self._session.get.return_value = None

        result = self._repo.get_by_id(missing)

        self._session.get.assert_called_once_with(InstrumentRow, missing)
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # get_by_business_key
    # ------------------------------------------------------------------

    def test_get_by_business_key_returns_instrument_for_active_row(self) -> None:
        row = _make_instrument_row(
            symbol="510050",
            exchange="SSE",
            name="SSE 50 ETF",
            is_active=True,
        )

        # Session.scalars(stmt).first() — return the row on first()
        scalars_mock = self._session.scalars.return_value
        scalars_mock.first.return_value = row

        result = self._repo.get_by_business_key(exchange="SSE", symbol="510050")

        self.assertEqual(self._session.scalars.call_count, 1)
        scalars_mock.first.assert_called_once_with()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.symbol, "510050")
        self.assertEqual(result.exchange, "SSE")
        self.assertTrue(result.is_active)

    def test_get_by_business_key_returns_none_when_no_match(self) -> None:
        scalars_mock = self._session.scalars.return_value
        scalars_mock.first.return_value = None

        result = self._repo.get_by_business_key(exchange="SSE", symbol="NOPE")

        scalars_mock.first.assert_called_once_with()
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # list_active
    # ------------------------------------------------------------------

    def test_list_active_returns_domain_objects_for_each_row(self) -> None:
        first = _make_instrument_row(symbol="510050", exchange="SSE")
        second = _make_instrument_row(symbol="510300", exchange="SSE")
        scalars_mock = self._session.scalars.return_value
        scalars_mock.all.return_value = [first, second]

        result = self._repo.list_active(limit=10, offset=0)

        self.assertEqual(self._session.scalars.call_count, 1)
        scalars_mock.all.assert_called_once_with()
        self.assertEqual(len(result), 2)
        self.assertEqual([item.symbol for item in result], ["510050", "510300"])
        # each returned item is an Instrument, not a raw row
        for item in result:
            self.assertIsInstance(item, Instrument)

    def test_list_active_with_empty_result_returns_empty_sequence(self) -> None:
        scalars_mock = self._session.scalars.return_value
        scalars_mock.all.return_value = []

        result = self._repo.list_active(limit=100, offset=0)

        self.assertEqual(list(result), [])

    # ------------------------------------------------------------------
    # count_active
    # ------------------------------------------------------------------

    def test_count_active_uses_scalars_all_and_returns_length(self) -> None:
        scalars_mock = self._session.scalars.return_value
        scalars_mock.all.return_value = [uuid4(), uuid4(), uuid4()]

        result = self._repo.count_active()

        self.assertEqual(self._session.scalars.call_count, 1)
        scalars_mock.all.assert_called_once_with()
        self.assertEqual(result, 3)


class SqlAlchemyProviderBatchRepositoryMockTests(unittest.TestCase):
    """Mock-based tests for :class:`SqlAlchemyProviderBatchRepository`."""

    def setUp(self) -> None:
        self._session = MagicMock(name="Session")
        self._repo = SqlAlchemyProviderBatchRepository(self._session)

    # ------------------------------------------------------------------
    # add
    # ------------------------------------------------------------------

    def test_add_returns_stored_batch_after_session_add_and_flush(self) -> None:
        batch = NewProviderBatch(
            provider_key="tushare",
            dataset_key="daily",
            request_key="req-001",
            requested_at=datetime(2024, 1, 1, tzinfo=UTC),
            status="requested",
            request_params={"symbol": "510050"},
        )

        result = self._repo.add(batch)

        self.assertIsInstance(result, StoredProviderBatch)
        # the row was attached to the session exactly once and flushed
        self.assertEqual(self._session.add.call_count, 1)
        self.assertEqual(self._session.flush.call_count, 1)
        # the row argument passed to session.add carries the input fields
        added_row = self._session.add.call_args[0][0]
        self.assertIsInstance(added_row, RawProviderBatchRow)
        self.assertEqual(added_row.provider_key, "tushare")
        self.assertEqual(added_row.dataset_key, "daily")
        self.assertEqual(added_row.request_key, "req-001")
        self.assertEqual(added_row.status, "requested")
        self.assertEqual(added_row.request_params, {"symbol": "510050"})
        # StoredProviderBatch mirrors the row's fields
        self.assertEqual(result.provider_key, "tushare")
        self.assertEqual(result.dataset_key, "daily")
        self.assertEqual(result.request_key, "req-001")
        self.assertEqual(result.status, "requested")
        self.assertEqual(result.request_params, {"symbol": "510050"})
        self.assertIsInstance(result.id, UUID)

    # ------------------------------------------------------------------
    # get_by_id
    # ------------------------------------------------------------------

    def test_get_by_id_returns_stored_batch_for_known_id(self) -> None:
        row_id = uuid4()
        row = _make_batch_row(row_id=row_id, provider_key="tushare", record_count=42)
        self._session.get.return_value = row

        result = self._repo.get_by_id(row_id)

        self._session.get.assert_called_once_with(RawProviderBatchRow, row_id)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.id, row_id)
        self.assertEqual(result.provider_key, "tushare")
        self.assertEqual(result.record_count, 42)
        self.assertEqual(result.status, "received")

    def test_get_by_id_returns_none_for_unknown_id(self) -> None:
        missing = uuid4()
        self._session.get.return_value = None

        result = self._repo.get_by_id(missing)

        self._session.get.assert_called_once_with(RawProviderBatchRow, missing)
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # get_by_request
    # ------------------------------------------------------------------

    def test_get_by_request_returns_stored_batch_for_known_triplet(self) -> None:
        row = _make_batch_row(
            provider_key="tushare",
            dataset_key="daily",
            request_key="req-xyz",
            record_count=7,
        )
        scalars_mock = self._session.scalars.return_value
        scalars_mock.first.return_value = row

        result = self._repo.get_by_request(
            provider_key="tushare",
            dataset_key="daily",
            request_key="req-xyz",
        )

        self.assertEqual(self._session.scalars.call_count, 1)
        scalars_mock.first.assert_called_once_with()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.provider_key, "tushare")
        self.assertEqual(result.dataset_key, "daily")
        self.assertEqual(result.request_key, "req-xyz")
        self.assertEqual(result.record_count, 7)

    def test_get_by_request_returns_none_for_unknown_triplet(self) -> None:
        scalars_mock = self._session.scalars.return_value
        scalars_mock.first.return_value = None

        result = self._repo.get_by_request(
            provider_key="tushare",
            dataset_key="daily",
            request_key="does-not-exist",
        )

        scalars_mock.first.assert_called_once_with()
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
