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
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.instruments import (
    Instrument,
    InstrumentId,
    InstrumentStatus,
    InstrumentType,
)
from invest_domain.market_data.values import Adjust
from invest_domain.shared.values import Currency
from invest_storage.models import (
    DailyBarRow,
    InstrumentRow,
    RawProviderBatchRow,
    StockPriceLimitRow,
)
from invest_storage.repositories import (
    NewPriceLimit,
    NewProviderBatch,
    SqlAlchemyDailyBarRepository,
    SqlAlchemyInstrumentRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyStockPriceLimitRepository,
    StoredDailyBar,
    StoredPriceLimit,
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
    provider_request_id: UUID | None = None,
    provider_attempt_id: UUID | None = None,
    provider_key: str = "tushare",
    dataset_key: str = "daily",
    record_count: int = 10,
    payload_sha256: str | None = "a" * 64,
    warnings: list[Any] | None = None,
    status: str = "succeeded",
    created_at: datetime | None = None,
) -> MagicMock:
    """Build a mock that looks like a PR-02 :class:`RawProviderBatchRow`."""

    row = MagicMock(spec=RawProviderBatchRow)
    row.id = row_id or uuid4()
    row.provider_request_id = provider_request_id or uuid4()
    row.provider_attempt_id = provider_attempt_id or uuid4()
    row.provider_key = provider_key
    row.dataset_key = dataset_key
    row.record_count = record_count
    row.payload_sha256 = payload_sha256
    row.warnings = warnings if warnings is not None else []
    row.status = status
    row.created_at = created_at or datetime(2024, 1, 1, tzinfo=UTC)
    return row


def _make_daily_bar_row(
    *,
    instrument_id: UUID,
    trade_date: date,
    revision: int,
) -> MagicMock:
    row = MagicMock(spec=DailyBarRow)
    row.id = uuid4()
    row.instrument_id = instrument_id
    row.trade_date = trade_date
    row.open = Decimal("10")
    row.high = Decimal("11")
    row.low = Decimal("9")
    row.close = Decimal("10.5")
    row.prev_close = Decimal("10")
    row.volume = Decimal("100")
    row.amount = Decimal("1050")
    row.adjustment = Adjust.NONE.value
    row.trading_status = "normal"
    row.source_provider = "fixture_dev"
    row.source_batch_id = uuid4()
    row.observed_at = datetime(2024, 1, 3, tzinfo=UTC)
    row.revision = revision
    row.row_hash = str(revision) * 64
    row.created_at = datetime(2024, 1, 3, tzinfo=UTC)
    return row


def _make_stock_price_limit_row(
    *,
    instrument_id: UUID,
    trade_date: date,
    revision: int,
    row_hash: str = "0" * 64,
) -> MagicMock:
    row = MagicMock(spec=StockPriceLimitRow)
    row.id = uuid4()
    row.instrument_id = instrument_id
    row.trade_date = trade_date
    row.regime_id = "normal"
    row.limit_up_price = Decimal("11.50")
    row.limit_down_price = Decimal("9.50")
    row.status = "active"
    row.reference_price = Decimal("10.50")
    row.source_provider = "fixture_dev"
    row.source_batch_id = uuid4()
    row.observed_at = datetime(2024, 1, 3, tzinfo=UTC)
    row.revision = revision
    row.row_hash = row_hash
    row.created_at = datetime(2024, 1, 3, tzinfo=UTC)
    return row


class SqlAlchemyStockPriceLimitRepositoryMockTests(unittest.TestCase):
    """Focused coverage for :class:`SqlAlchemyStockPriceLimitRepository`.

    Verifies the row-hash idempotency contract of
    :meth:`SqlAlchemyStockPriceLimitRepository.upsert_many`: a
    re-collect with the same business content is a no-op while
    changed content advances the revision counter.
    """

    def setUp(self) -> None:
        self._session = MagicMock(name="Session")
        self._repo = SqlAlchemyStockPriceLimitRepository(self._session)

    def _stub_latest_and_max(
        self,
        *,
        existing: MagicMock | None,
        max_revision: int | None,
    ) -> None:
        """Configure ``session.execute`` for get_latest + _next_revision."""

        latest_result = MagicMock(name="get_latest_result")
        latest_result.scalar_one_or_none.return_value = existing
        max_result = MagicMock(name="max_revision_result")
        max_result.scalar.return_value = max_revision
        self._session.execute.side_effect = [latest_result, max_result]

    def test_upsert_many_skips_insert_when_row_hash_matches_latest(self) -> None:
        instrument_id = uuid4()
        trade_date = date(2024, 1, 3)
        existing = _make_stock_price_limit_row(
            instrument_id=instrument_id,
            trade_date=trade_date,
            revision=1,
        )
        self._stub_latest_and_max(existing=existing, max_revision=1)

        result = self._repo.upsert_many(
            [
                NewPriceLimit(
                    instrument_id=instrument_id,
                    trade_date=trade_date,
                    regime_id="normal",
                    limit_up_price=Decimal("11.50"),
                    limit_down_price=Decimal("9.50"),
                    status="active",
                    reference_price=Decimal("10.50"),
                    source_provider="fixture_dev",
                    source_batch_id=uuid4(),
                    observed_at=datetime(2024, 1, 3, tzinfo=UTC),
                    row_hash=existing.row_hash,
                ),
            ]
        )

        self.assertEqual(result, [])
        self._session.add.assert_not_called()
        self._session.flush.assert_not_called()

    def test_upsert_many_advances_revision_when_row_hash_changes(self) -> None:
        instrument_id = uuid4()
        trade_date = date(2024, 1, 3)
        existing = _make_stock_price_limit_row(
            instrument_id=instrument_id,
            trade_date=trade_date,
            revision=2,
            row_hash="a" * 64,
        )
        self._stub_latest_and_max(existing=existing, max_revision=2)

        result = self._repo.upsert_many(
            [
                NewPriceLimit(
                    instrument_id=instrument_id,
                    trade_date=trade_date,
                    regime_id="normal",
                    limit_up_price=Decimal("11.50"),
                    limit_down_price=Decimal("9.50"),
                    status="active",
                    reference_price=Decimal("10.50"),
                    source_provider="fixture_dev",
                    source_batch_id=uuid4(),
                    observed_at=datetime(2024, 1, 3, tzinfo=UTC),
                    row_hash="b" * 64,
                ),
            ]
        )

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], StoredPriceLimit)
        self.assertEqual(result[0].revision, 3)
        self.assertEqual(result[0].row_hash, "b" * 64)
        self._session.add.assert_called_once()
        self._session.flush.assert_called_once()


class SqlAlchemyDailyBarRepositoryMockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._session = MagicMock(name="Session")
        self._repo = SqlAlchemyDailyBarRepository(self._session)

    def test_list_latest_returns_empty_sequence(self) -> None:
        self._session.execute.return_value.scalars.return_value.all.return_value = []

        result = self._repo.list_latest_by_instrument_and_range(
            instrument_id=uuid4(),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            adjustment=Adjust.NONE,
        )

        self.assertEqual(result, [])

    def test_list_latest_rejects_reversed_range_without_querying(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be on or after"):
            self._repo.list_latest_by_instrument_and_range(
                instrument_id=uuid4(),
                start_date=date(2024, 2, 1),
                end_date=date(2024, 1, 31),
                adjustment=Adjust.NONE,
            )

        self._session.execute.assert_not_called()

    def test_list_latest_selects_max_revision_per_day_in_ascending_date_order(self) -> None:
        instrument_id = uuid4()
        rows = [
            _make_daily_bar_row(
                instrument_id=instrument_id,
                trade_date=date(2024, 1, 2),
                revision=3,
            ),
            _make_daily_bar_row(
                instrument_id=instrument_id,
                trade_date=date(2024, 1, 3),
                revision=2,
            ),
        ]
        self._session.execute.return_value.scalars.return_value.all.return_value = rows

        result = self._repo.list_latest_by_instrument_and_range(
            instrument_id=instrument_id,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            adjustment=Adjust.NONE,
        )

        self.assertEqual([item.revision for item in result], [3, 2])
        self.assertTrue(all(isinstance(item, StoredDailyBar) for item in result))
        statement = self._session.execute.call_args.args[0]
        sql = str(statement.compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("max(core.daily_bars.revision)", sql)
        self.assertIn("group by core.daily_bars.trade_date", sql)
        self.assertIn("order by core.daily_bars.trade_date asc", sql)

    def test_list_latest_accepts_uuid_and_instrument_id(self) -> None:
        raw_id = uuid4()
        self._session.execute.return_value.scalars.return_value.all.return_value = []

        for instrument_id in (raw_id, InstrumentId(raw_id)):
            self._repo.list_latest_by_instrument_and_range(
                instrument_id=instrument_id,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                adjustment=Adjust.NONE,
            )
            statement = self._session.execute.call_args.args[0]
            self.assertIn(raw_id, statement.compile().params.values())


class SqlAlchemyDailyBarRepositoryListLatestByInstrumentsMockTests(unittest.TestCase):
    """Focused coverage for the batch
    :meth:`SqlAlchemyDailyBarRepository.list_latest_by_instruments_and_range`.
    """

    def setUp(self) -> None:
        self._session = MagicMock(name="Session")
        self._repo = SqlAlchemyDailyBarRepository(self._session)

    def test_returns_empty_sequence_without_touching_session(self) -> None:
        for empty in ([], (), (uuid4(),)[:0]):
            result = self._repo.list_latest_by_instruments_and_range(
                instrument_ids=empty,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                adjustment=Adjust.NONE,
            )

            self.assertEqual(result, [])
            self.assertIsInstance(result, list)
            self._session.execute.assert_not_called()
            self._session.scalars.assert_not_called()

    def test_rejects_reversed_range_without_querying(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be on or after"):
            self._repo.list_latest_by_instruments_and_range(
                instrument_ids=[uuid4()],
                start_date=date(2024, 2, 1),
                end_date=date(2024, 1, 31),
                adjustment=Adjust.NONE,
            )

        self._session.execute.assert_not_called()

    def test_groups_by_instrument_and_trade_date_with_max_revision(self) -> None:
        first_id = uuid4()
        second_id = uuid4()
        rows = [
            _make_daily_bar_row(
                instrument_id=first_id,
                trade_date=date(2024, 1, 2),
                revision=3,
            ),
            _make_daily_bar_row(
                instrument_id=first_id,
                trade_date=date(2024, 1, 3),
                revision=2,
            ),
            _make_daily_bar_row(
                instrument_id=second_id,
                trade_date=date(2024, 1, 2),
                revision=5,
            ),
            _make_daily_bar_row(
                instrument_id=second_id,
                trade_date=date(2024, 1, 3),
                revision=4,
            ),
        ]
        self._session.execute.return_value.scalars.return_value.all.return_value = rows

        result = self._repo.list_latest_by_instruments_and_range(
            instrument_ids=[first_id, second_id],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            adjustment=Adjust.NONE,
        )

        self.assertEqual(
            [(item.instrument_id, item.revision) for item in result],
            [
                (first_id, 3),
                (first_id, 2),
                (second_id, 5),
                (second_id, 4),
            ],
        )
        self.assertTrue(all(isinstance(item, StoredDailyBar) for item in result))
        self.assertIsInstance(result, list)

        statement = self._session.execute.call_args.args[0]
        sql = str(statement.compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("max(core.daily_bars.revision)", sql)
        self.assertIn("group by core.daily_bars.instrument_id, core.daily_bars.trade_date", sql)
        self.assertIn("order by core.daily_bars.instrument_id asc", sql)
        self.assertIn("core.daily_bars.trade_date asc", sql)

    def test_filters_by_instrument_and_date_and_adjustment(self) -> None:
        self._session.execute.return_value.scalars.return_value.all.return_value = []
        instrument_id = uuid4()

        self._repo.list_latest_by_instruments_and_range(
            instrument_ids=[instrument_id],
            start_date=date(2024, 1, 5),
            end_date=date(2024, 2, 5),
            adjustment=Adjust.NONE,
        )

        statement = self._session.execute.call_args.args[0]
        sql = str(statement.compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("core.daily_bars.instrument_id", sql)
        self.assertIn("core.daily_bars.trade_date >=", sql)
        self.assertIn("core.daily_bars.trade_date <=", sql)
        self.assertIn("core.daily_bars.adjustment =", sql)
        self.assertIn("'none'", sql)
        self.assertIn("2024-01-05", sql)
        self.assertIn("2024-02-05", sql)

    def test_accepts_uuid_and_instrument_id_inputs(self) -> None:
        raw_id = uuid4()
        other_id = uuid4()
        self._session.execute.return_value.scalars.return_value.all.return_value = []

        for instrument_ids in (
            [raw_id, other_id],
            [InstrumentId(raw_id), InstrumentId(other_id)],
            [raw_id, InstrumentId(other_id)],
        ):
            self._session.execute.reset_mock()
            self._repo.list_latest_by_instruments_and_range(
                instrument_ids=instrument_ids,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                adjustment=Adjust.NONE,
            )
            statement = self._session.execute.call_args.args[0]
            flattened = []
            for value in statement.compile().params.values():
                if isinstance(value, list):
                    flattened.extend(value)
                else:
                    flattened.append(value)
            self.assertIn(raw_id, flattened)
            self.assertIn(other_id, flattened)

    def test_rejects_non_uuid_non_instrument_id_input(self) -> None:
        with self.assertRaisesRegex(TypeError, "UUID or InstrumentId"):
            self._repo.list_latest_by_instruments_and_range(
                instrument_ids=["not-a-uuid"],  # type: ignore[list-item]
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                adjustment=Adjust.NONE,
            )

        self._session.execute.assert_not_called()

    def test_dedupes_repeated_instrument_ids(self) -> None:
        instrument_id = uuid4()
        self._session.execute.return_value.scalars.return_value.all.return_value = []

        self._repo.list_latest_by_instruments_and_range(
            instrument_ids=[instrument_id, instrument_id, InstrumentId(instrument_id)],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            adjustment=Adjust.NONE,
        )

        statement = self._session.execute.call_args.args[0]
        # the IN clause appears twice in the SQL (subquery + outer WHERE);
        # after dedup each occurrence must contain exactly one UUID.
        in_clauses = [
            value
            for value in statement.compile().params.values()
            if isinstance(value, list)
        ]
        self.assertEqual(len(in_clauses), 2)
        for items in in_clauses:
            self.assertEqual(items, [instrument_id])


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
    """Mock-based tests for :class:`SqlAlchemyProviderBatchRepository`.

    PR-02 reshaped ``raw.provider_batches``: rows now carry
    ``provider_request_id`` and ``provider_attempt_id`` FKs plus a
    required ``payload_sha256`` digest. These tests cover the new
    surface (``add``, ``get_by_id``, ``list_by_attempt``,
    ``list_by_provider_dataset``).
    """

    def setUp(self) -> None:
        self._session = MagicMock(name="Session")
        self._repo = SqlAlchemyProviderBatchRepository(self._session)

    # ------------------------------------------------------------------
    # add
    # ------------------------------------------------------------------

    def test_add_returns_stored_batch_after_session_add_and_flush(self) -> None:
        request_id = uuid4()
        attempt_id = uuid4()
        batch = NewProviderBatch(
            provider_request_id=request_id,
            provider_attempt_id=attempt_id,
            provider_key="tushare",
            dataset_key="daily",
            record_count=10,
            payload_sha256="a" * 64,
            status="succeeded",
            warnings=["stale record skipped"],
        )

        result = self._repo.add(batch)

        self.assertIsInstance(result, StoredProviderBatch)
        # the row was attached to the session exactly once and flushed
        self.assertEqual(self._session.add.call_count, 1)
        self.assertEqual(self._session.flush.call_count, 1)
        # the row argument passed to session.add carries the input fields
        added_row = self._session.add.call_args[0][0]
        self.assertIsInstance(added_row, RawProviderBatchRow)
        self.assertEqual(added_row.provider_request_id, request_id)
        self.assertEqual(added_row.provider_attempt_id, attempt_id)
        self.assertEqual(added_row.provider_key, "tushare")
        self.assertEqual(added_row.dataset_key, "daily")
        self.assertEqual(added_row.record_count, 10)
        self.assertEqual(added_row.payload_sha256, "a" * 64)
        self.assertEqual(added_row.status, "succeeded")
        self.assertEqual(added_row.warnings, ["stale record skipped"])
        # StoredProviderBatch mirrors the row's fields
        self.assertEqual(result.provider_key, "tushare")
        self.assertEqual(result.dataset_key, "daily")
        self.assertEqual(result.record_count, 10)
        self.assertEqual(result.payload_sha256, "a" * 64)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.warnings, ["stale record skipped"])
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
        self.assertEqual(result.status, "succeeded")

    def test_get_by_id_returns_none_for_unknown_id(self) -> None:
        missing = uuid4()
        self._session.get.return_value = None

        result = self._repo.get_by_id(missing)

        self._session.get.assert_called_once_with(RawProviderBatchRow, missing)
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # list_by_attempt
    # ------------------------------------------------------------------

    def test_list_by_attempt_returns_stored_batches(self) -> None:
        attempt_id = uuid4()
        first = _make_batch_row(provider_attempt_id=attempt_id, record_count=10)
        second = _make_batch_row(provider_attempt_id=attempt_id, record_count=20)
        scalars_mock = self._session.scalars.return_value
        scalars_mock.all.return_value = [first, second]

        result = self._repo.list_by_attempt(attempt_id, limit=10, offset=0)

        self.assertEqual(self._session.scalars.call_count, 1)
        scalars_mock.all.assert_called_once_with()
        self.assertEqual(len(result), 2)
        for item in result:
            self.assertIsInstance(item, StoredProviderBatch)
            self.assertEqual(item.provider_attempt_id, attempt_id)


if __name__ == "__main__":
    unittest.main()
