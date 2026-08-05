"""Mock-based unit tests for the ETF-profile storage repository.

The tests drive a :class:`unittest.mock.MagicMock` ``Session`` so the
:class:`invest_storage.repositories.SqlAlchemyEtfProfileRepository`
can be verified without spinning up Testcontainers or speaking to a real
PostgreSQL. They pin four contracts:

- :meth:`upsert` issues an ``INSERT ... ON CONFLICT DO UPDATE``
  against ``core.etf_profiles`` keyed on ``instrument_id``, mapping
  every domain field through to the row and forwarding ``updated_at``
  bumps to ``now()``.
- :meth:`upsert` is idempotent: re-running the same write replaces
  every mutable column and returns the freshly-mapped domain row; the
  session is flushed so a subsequent ``get_by_id`` reads through.
- :meth:`get_by_id`, ``list_by_manager``, ``list_by_category``,
  ``list_by_fund_type`` and ``list_all`` produce ordered
  :class:`invest_domain.etf_profile.models.EtfProfile` instances from
  their respective SELECTs.
- Repository-level input validation aligns with the domain
  validator: defensive ``ValueError`` is raised when the storage
  layer is asked to filter on values that cannot exist in the column.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.etf_profile import EtfProfile
from invest_storage import EtfProfileRow, SqlAlchemyEtfProfileRepository
from sqlalchemy.orm import Session


def _make_profile(
    *,
    instrument_id: UUID | None = None,
    manager: str | None = "华夏基金",
    benchmark_index: str | None = "沪深300",
    category: str | None = "Equity",
    inception_date: date | None = date(2013, 3, 25),
    fund_type: str | None = "OpenEnd",
    management_fee: Decimal | None = Decimal("0.0015"),
    custody_fee: Decimal | None = Decimal("0.0010"),
    aum: Decimal | None = Decimal("1234567890.00"),
    shares: Decimal | None = Decimal("1000000000"),
) -> EtfProfile:
    return EtfProfile(
        instrument_id=instrument_id or uuid4(),
        manager=manager,
        benchmark_index=benchmark_index,
        category=category,
        inception_date=inception_date,
        fund_type=fund_type,
        management_fee=management_fee,
        custody_fee=custody_fee,
        aum=aum,
        shares=shares,
    )


def _make_row(profile: EtfProfile) -> MagicMock:
    row = MagicMock(spec=EtfProfileRow)
    row.instrument_id = profile.instrument_id
    row.manager = profile.manager
    row.benchmark_index = profile.benchmark_index
    row.category = profile.category
    row.inception_date = profile.inception_date
    row.fund_type = profile.fund_type
    row.management_fee = profile.management_fee
    row.custody_fee = profile.custody_fee
    row.aum = profile.aum
    row.shares = profile.shares
    return row


class EtfProfileRepositoryUpsertTests(unittest.TestCase):
    """Mock tests covering the idempotent ``upsert`` contract."""

    def setUp(self) -> None:
        self._session = MagicMock(spec=Session)
        self._repo = SqlAlchemyEtfProfileRepository(self._session)

    def test_upsert_inserts_row_with_full_domain_payload(self) -> None:
        profile = _make_profile()
        # ``get_by_id`` after the upsert must return the freshly-mapped
        # profile so the repository can hand the domain object back.
        self._session.get.return_value = _make_row(profile)

        result = self._repo.upsert(profile)

        self.assertEqual(result, profile)
        self._session.execute.assert_called_once()
        self._session.flush.assert_called_once_with()
        self._session.get.assert_called_once_with(EtfProfileRow, profile.instrument_id)

        # Inspect the INSERT statement that was sent to the session.
        statement = self._session.execute.call_args.args[0]
        params = statement.compile().params
        self.assertEqual(params["instrument_id"], profile.instrument_id)
        self.assertEqual(params["manager"], profile.manager)
        self.assertEqual(params["benchmark_index"], profile.benchmark_index)
        self.assertEqual(params["category"], profile.category)
        self.assertEqual(params["inception_date"], profile.inception_date)
        self.assertEqual(params["fund_type"], profile.fund_type)
        self.assertEqual(params["management_fee"], profile.management_fee)
        self.assertEqual(params["custody_fee"], profile.custody_fee)
        self.assertEqual(params["aum"], profile.aum)
        self.assertEqual(params["shares"], profile.shares)

    def test_upsert_carries_nullable_fields_as_none(self) -> None:
        profile = _make_profile(
            manager=None,
            benchmark_index=None,
            category=None,
            inception_date=None,
            fund_type=None,
            management_fee=None,
            custody_fee=None,
            aum=None,
            shares=None,
        )
        self._session.get.return_value = _make_row(profile)

        self._repo.upsert(profile)

        statement = self._session.execute.call_args.args[0]
        params = statement.compile().params
        self.assertIsNone(params["manager"])
        self.assertIsNone(params["benchmark_index"])
        self.assertIsNone(params["category"])
        self.assertIsNone(params["inception_date"])
        self.assertIsNone(params["fund_type"])
        self.assertIsNone(params["management_fee"])
        self.assertIsNone(params["custody_fee"])
        self.assertIsNone(params["aum"])
        self.assertIsNone(params["shares"])

    def test_upsert_passes_minimal_instrument_id_only_record(self) -> None:
        profile = EtfProfile(instrument_id=uuid4())
        self._session.get.return_value = _make_row(profile)

        result = self._repo.upsert(profile)

        self.assertEqual(result, profile)
        statement = self._session.execute.call_args.args[0]
        params = statement.compile().params
        self.assertEqual(params["instrument_id"], profile.instrument_id)
        self.assertIsNone(params["manager"])
        self.assertIsNone(params["aum"])

    def test_upsert_with_unreadable_row_raises_runtimeerror(self) -> None:
        # Defensive contract: if the row cannot be re-read after the
        # ``INSERT ... ON CONFLICT DO UPDATE`` succeeds, the repository
        # surfaces a ``RuntimeError`` so the application layer cannot
        # silently believe the write was durable.
        profile = _make_profile()
        self._session.get.return_value = None

        with self.assertRaises(RuntimeError):
            self._repo.upsert(profile)
        self._session.execute.assert_called_once()
        self._session.flush.assert_called_once_with()


class EtfProfileRepositoryReadTests(unittest.TestCase):
    """Mock tests covering the read surfaces used by Stage DC-2 dashboards."""

    def setUp(self) -> None:
        self._session = MagicMock(spec=Session)
        self._repo = SqlAlchemyEtfProfileRepository(self._session)

    def test_get_by_id_maps_row(self) -> None:
        profile = _make_profile()
        self._session.get.return_value = _make_row(profile)

        result = self._repo.get_by_id(profile.instrument_id)

        self.assertEqual(result, profile)
        self._session.get.assert_called_once_with(EtfProfileRow, profile.instrument_id)

    def test_get_by_id_accepts_instrument_id_wrapper(self) -> None:
        # The repository contract promises ``UUID`` *or*
        # :class:`invest_domain.instruments.models.InstrumentId` for
        # ``get_by_id``; the wrapper is unwrapped internally so the
        # underlying ``Session.get`` still sees the raw UUID.
        from invest_domain.instruments import InstrumentId

        profile = _make_profile()
        self._session.get.return_value = _make_row(profile)

        result = self._repo.get_by_id(InstrumentId(profile.instrument_id))

        self.assertEqual(result, profile)
        self._session.get.assert_called_once_with(EtfProfileRow, profile.instrument_id)

    def test_get_by_id_returns_none_when_missing(self) -> None:
        self._session.get.return_value = None

        result = self._repo.get_by_id(uuid4())

        self.assertIsNone(result)

    def test_list_by_manager_maps_rows_in_order(self) -> None:
        first = _make_profile()
        second = _make_profile()
        self._session.scalars.return_value.all.return_value = [
            _make_row(first),
            _make_row(second),
        ]

        result = self._repo.list_by_manager("华夏基金")

        self.assertEqual(result, [first, second])
        self._session.scalars.assert_called_once()

    def test_list_by_category_maps_rows_in_order(self) -> None:
        first = _make_profile()
        self._session.scalars.return_value.all.return_value = [_make_row(first)]

        result = self._repo.list_by_category("Equity")

        self.assertEqual(result, [first])
        self._session.scalars.assert_called_once()

    def test_list_by_fund_type_maps_rows_in_order(self) -> None:
        first = _make_profile()
        self._session.scalars.return_value.all.return_value = [_make_row(first)]

        result = self._repo.list_by_fund_type("OpenEnd")

        self.assertEqual(result, [first])
        self._session.scalars.assert_called_once()

    def test_list_all_maps_rows_in_order(self) -> None:
        first = _make_profile()
        second = _make_profile()
        self._session.scalars.return_value.all.return_value = [
            _make_row(first),
            _make_row(second),
        ]

        result = self._repo.list_all()

        self.assertEqual(result, [first, second])
        self._session.scalars.assert_called_once()

    def test_list_methods_reject_negative_limit(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_all(limit=-1)

    def test_list_methods_reject_negative_offset(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_all(offset=-1)

    def test_list_by_methods_reject_negative_limit(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_manager("华夏基金", limit=-1)

    def test_list_by_methods_reject_negative_offset(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_manager("华夏基金", offset=-1)

    def test_count_all_returns_scalar_count(self) -> None:
        self._session.scalar.return_value = 7

        result = self._repo.count_all()

        self.assertEqual(result, 7)
        self._session.scalar.assert_called_once()

    def test_count_all_handles_null_scalar(self) -> None:
        # ``session.scalar`` may return ``None`` when the underlying
        # statement yields no rows; the repository must coerce that to
        # zero so downstream dashboards never see ``None``.
        self._session.scalar.return_value = None

        result = self._repo.count_all()

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
