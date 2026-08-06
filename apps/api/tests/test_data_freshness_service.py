"""Tests for :class:`invest_api.application.data_freshness.DataFreshnessQueryService`.

The endpoint tests in :mod:`tests.test_data_freshness_endpoints` mock
the application service at the FastAPI boundary and verify the HTTP
contract. These tests bypass the HTTP layer: they construct the real
service against a mock reader so they can assert that the service
itself owns the snapshot-first / published-fallback / empty-universe
chain (PR-02), the ``expected_trade_date`` default (latest weekday
from :func:`invest_api.clock.market_today`), the five
:class:`DataFreshnessStatus` outcomes (``fresh``, ``partial``,
``stale``, ``missing``, ``failed``) and the
:class:`sqlalchemy.exc.SQLAlchemyError` translation to
:class:`DataFreshnessQueryError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from invest_api import clock as clock_module
from invest_api.application.data_freshness import (
    JOB_KEY,
    DataFreshnessQueryError,
    DataFreshnessQueryService,
    DataFreshnessView,
    InputSnapshotRow,
    PipelineRunRow,
    PublishedCandidatePoolRunRow,
    latest_weekday,
)
from sqlalchemy.exc import OperationalError


def _snapshot_row(
    *,
    id: object = None,
    instrument_ids: tuple[str, ...] = (),
    row_count: int = 0,
) -> InputSnapshotRow:
    """Return a duck-typed input-snapshot row for the mock reader."""

    return _SnapshotRow(id=id or uuid4(), instrument_ids=instrument_ids, row_count=row_count)


def _published_row(
    *,
    id: object = None,
    trade_date: date,
    input_row_count: int = 0,
) -> PublishedCandidatePoolRunRow:
    return _PublishedRow(
        id=id or uuid4(), trade_date=trade_date, input_row_count=input_row_count
    )


def _pipeline_row(*, id: object = None, status: str | None) -> PipelineRunRow:
    return _PipelineRow(id=id or uuid4(), status=status)


@dataclass(frozen=True, slots=True)
class _SnapshotRow:
    id: object
    instrument_ids: tuple[str, ...]
    row_count: int


@dataclass(frozen=True, slots=True)
class _PublishedRow:
    id: object
    trade_date: date
    input_row_count: int


@dataclass(frozen=True, slots=True)
class _PipelineRow:
    id: object
    status: str | None


def _build_service(
    reader: MagicMock,
) -> DataFreshnessQueryService:
    """Return a real service wired to the supplied mock reader."""

    return DataFreshnessQueryService(reader)


class TestLatestWeekdayHelper:
    """Sanity-check :func:`latest_weekday` directly."""

    def test_monday_passes_through(self) -> None:
        assert latest_weekday(date(2026, 8, 3)) == date(2026, 8, 3)

    def test_tuesday_passes_through(self) -> None:
        assert latest_weekday(date(2026, 8, 4)) == date(2026, 8, 4)

    def test_friday_passes_through(self) -> None:
        assert latest_weekday(date(2026, 7, 31)) == date(2026, 7, 31)

    def test_saturday_collapses_to_friday(self) -> None:
        assert latest_weekday(date(2026, 8, 1)) == date(2026, 7, 31)

    def test_sunday_collapses_to_friday(self) -> None:
        assert latest_weekday(date(2026, 8, 2)) == date(2026, 7, 31)


class TestDefaultDate:
    """The service defaults ``expected_trade_date`` to the market clock."""

    def test_uses_market_today_when_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Force the market clock helper to return a Shanghai Saturday so
        # the service should snap the default to the previous Friday.
        monkeypatch.setattr(clock_module, "market_today", lambda: date(2026, 8, 1))
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = None
        reader.get_latest_published_candidate_pool_run.return_value = None
        reader.count_daily_bars_for_snapshot.return_value = 0
        reader.count_daily_bars_for_published_run.return_value = 0
        reader.count_included_items_for_run.return_value = 0
        reader.get_latest_pipeline_run_for_partition.return_value = None
        service = _build_service(reader)

        view = service.get_freshness(None)

        # Saturday 2026-08-01 collapses to Friday 2026-07-31.
        assert view.expected_trade_date == date(2026, 7, 31)
        reader.get_snapshot_for_trade_date.assert_called_once_with(
            date(2026, 7, 31)
        )

    def test_keeps_explicit_date_verbatim(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(clock_module, "market_today", lambda: date(2026, 8, 2))
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = None
        reader.get_latest_published_candidate_pool_run.return_value = None
        reader.count_daily_bars_for_snapshot.return_value = 0
        reader.count_daily_bars_for_published_run.return_value = 0
        reader.count_included_items_for_run.return_value = 0
        reader.get_latest_pipeline_run_for_partition.return_value = None
        service = _build_service(reader)

        explicit = date(2026, 7, 31)
        view = service.get_freshness(explicit)

        assert view.expected_trade_date == explicit
        reader.get_snapshot_for_trade_date.assert_called_once_with(explicit)


class TestStatusStates:
    """Coverage for the five ``status`` outcomes the service derives."""

    def test_fresh_when_snapshot_full_and_pipeline_succeeded(self) -> None:
        snapshot_id = uuid4()
        published_id = uuid4()
        pipeline_id = uuid4()
        expected = date(2026, 7, 31)
        snapshot_ids = tuple(str(uuid4()) for _ in range(120))
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = _snapshot_row(
            id=snapshot_id, instrument_ids=snapshot_ids, row_count=120
        )
        reader.get_latest_published_candidate_pool_run.return_value = _published_row(
            id=published_id, trade_date=expected, input_row_count=120
        )
        reader.count_daily_bars_for_snapshot.return_value = 120
        reader.count_included_items_for_run.return_value = 120
        reader.get_latest_pipeline_run_for_partition.return_value = _pipeline_row(
            id=pipeline_id, status="succeeded"
        )
        service = _build_service(reader)

        view = service.get_freshness(expected)

        assert isinstance(view, DataFreshnessView)
        assert view.status == "fresh"
        assert view.expected_trade_date == expected
        assert view.latest_published_trade_date == expected
        assert view.universe_count == 120
        assert view.daily_bar_count == 120
        assert view.missing_count == 0
        assert view.candidate_count == 120
        assert view.snapshot_id == snapshot_id
        assert view.pipeline_run_id == pipeline_id
        assert view.pipeline_status == "succeeded"

        reader.count_daily_bars_for_snapshot.assert_called_once_with(
            expected, snapshot_ids
        )
        reader.count_daily_bars_for_published_run.assert_not_called()
        reader.count_included_items_for_run.assert_called_once_with(published_id)
        reader.get_latest_pipeline_run_for_partition.assert_called_once_with(
            job_key=JOB_KEY, partition_key=expected.isoformat()
        )

    def test_partial_when_snapshot_below_universe(self) -> None:
        snapshot_id = uuid4()
        published_id = uuid4()
        pipeline_id = uuid4()
        expected = date(2026, 7, 31)
        snapshot_ids = tuple(str(uuid4()) for _ in range(200))
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = _snapshot_row(
            id=snapshot_id, instrument_ids=snapshot_ids, row_count=200
        )
        reader.get_latest_published_candidate_pool_run.return_value = _published_row(
            id=published_id, trade_date=expected, input_row_count=150
        )
        reader.count_daily_bars_for_snapshot.return_value = 150
        reader.count_included_items_for_run.return_value = 150
        reader.get_latest_pipeline_run_for_partition.return_value = _pipeline_row(
            id=pipeline_id, status="succeeded"
        )
        service = _build_service(reader)

        view = service.get_freshness(expected)

        assert view.status == "partial"
        assert view.universe_count == 200
        assert view.daily_bar_count == 150
        assert view.missing_count == 50
        assert view.candidate_count == 150

    def test_stale_when_latest_published_is_before_expected(self) -> None:
        snapshot_id = uuid4()
        published_id = uuid4()
        pipeline_id = uuid4()
        expected = date(2026, 7, 31)
        snapshot_ids = tuple(str(uuid4()) for _ in range(80))
        stale_date = date(2026, 7, 24)
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = _snapshot_row(
            id=snapshot_id, instrument_ids=snapshot_ids, row_count=80
        )
        reader.get_latest_published_candidate_pool_run.return_value = _published_row(
            id=published_id, trade_date=stale_date, input_row_count=80
        )
        reader.count_daily_bars_for_snapshot.return_value = 80
        reader.count_included_items_for_run.return_value = 80
        reader.get_latest_pipeline_run_for_partition.return_value = _pipeline_row(
            id=pipeline_id, status="succeeded"
        )
        service = _build_service(reader)

        view = service.get_freshness(expected)

        assert view.status == "stale"
        assert view.latest_published_trade_date == stale_date

    def test_failed_when_pipeline_failed_and_no_same_day_published(self) -> None:
        snapshot_id = uuid4()
        published_id = uuid4()
        pipeline_id = uuid4()
        expected = date(2026, 7, 31)
        snapshot_ids = tuple(str(uuid4()) for _ in range(100))
        stale_date = date(2026, 7, 30)
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = _snapshot_row(
            id=snapshot_id, instrument_ids=snapshot_ids, row_count=100
        )
        reader.get_latest_published_candidate_pool_run.return_value = _published_row(
            id=published_id, trade_date=stale_date, input_row_count=100
        )
        reader.count_daily_bars_for_snapshot.return_value = 0
        reader.count_included_items_for_run.return_value = 100
        reader.get_latest_pipeline_run_for_partition.return_value = _pipeline_row(
            id=pipeline_id, status="failed"
        )
        service = _build_service(reader)

        view = service.get_freshness(expected)

        assert view.status == "failed"
        assert view.pipeline_status == "failed"
        assert view.missing_count == 100

    def test_failed_status_does_not_apply_when_same_day_published_exists(self) -> None:
        """A failed pipeline on a day that already published must not raise ``failed``.

        The state machine deliberately only flags ``failed`` when there
        is no same-day published run; a failed rerun after a
        successful publish should be reported as ``fresh`` (or
        ``partial``) instead.
        """

        snapshot_id = uuid4()
        published_id = uuid4()
        pipeline_id = uuid4()
        expected = date(2026, 7, 31)
        snapshot_ids = tuple(str(uuid4()) for _ in range(10))
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = _snapshot_row(
            id=snapshot_id, instrument_ids=snapshot_ids, row_count=10
        )
        reader.get_latest_published_candidate_pool_run.return_value = _published_row(
            id=published_id, trade_date=expected, input_row_count=10
        )
        reader.count_daily_bars_for_snapshot.return_value = 10
        reader.count_included_items_for_run.return_value = 10
        reader.get_latest_pipeline_run_for_partition.return_value = _pipeline_row(
            id=pipeline_id, status="failed"
        )
        service = _build_service(reader)

        view = service.get_freshness(expected)

        assert view.status == "fresh"

    def test_does_not_invoke_published_branch_when_pipeline_status_blank(self) -> None:
        """A pipeline row with no status string must still allow the published branch."""

        snapshot_id = uuid4()
        published_id = uuid4()
        pipeline_id = uuid4()
        expected = date(2026, 7, 31)
        snapshot_ids = tuple(str(uuid4()) for _ in range(50))
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = _snapshot_row(
            id=snapshot_id, instrument_ids=snapshot_ids, row_count=50
        )
        reader.get_latest_published_candidate_pool_run.return_value = _published_row(
            id=published_id, trade_date=expected, input_row_count=50
        )
        reader.count_daily_bars_for_snapshot.return_value = 50
        reader.count_included_items_for_run.return_value = 50
        reader.get_latest_pipeline_run_for_partition.return_value = _pipeline_row(
            id=pipeline_id, status=None
        )
        service = _build_service(reader)

        view = service.get_freshness(expected)

        assert view.status == "fresh"
        assert view.pipeline_status is None


class TestNoPublishedRun:
    """Coverage for the "no published run" state and the published-fallback path."""

    def test_missing_when_no_snapshot_and_no_published(self) -> None:
        expected = date(2026, 7, 31)
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = None
        reader.get_latest_published_candidate_pool_run.return_value = None
        reader.get_latest_pipeline_run_for_partition.return_value = None
        service = _build_service(reader)

        view = service.get_freshness(expected)

        assert view.status == "missing"
        assert view.expected_trade_date == expected
        assert view.latest_published_trade_date is None
        assert view.universe_count == 0
        assert view.daily_bar_count == 0
        assert view.missing_count == 0
        assert view.candidate_count == 0
        assert view.snapshot_id is None
        assert view.pipeline_run_id is None
        assert view.pipeline_status is None

        reader.count_daily_bars_for_snapshot.assert_not_called()
        reader.count_daily_bars_for_published_run.assert_not_called()
        reader.count_included_items_for_run.assert_not_called()

    def test_falls_back_to_published_input_row_count_when_no_snapshot(self) -> None:
        expected = date(2026, 7, 31)
        published_id = uuid4()
        pipeline_id = uuid4()
        published_date = date(2026, 7, 30)
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = None
        reader.get_latest_published_candidate_pool_run.return_value = _published_row(
            id=published_id, trade_date=published_date, input_row_count=42
        )
        reader.count_daily_bars_for_published_run.return_value = 37
        reader.count_included_items_for_run.return_value = 40
        reader.get_latest_pipeline_run_for_partition.return_value = _pipeline_row(
            id=pipeline_id, status="succeeded"
        )
        service = _build_service(reader)

        view = service.get_freshness(expected)

        # No snapshot -> the published run's ``input_row_count`` is the
        # personal universe; daily-bar count must be scoped to the
        # published run's items.
        assert view.snapshot_id is None
        assert view.universe_count == 42
        assert view.daily_bar_count == 37
        assert view.missing_count == 5
        assert view.candidate_count == 40
        assert view.latest_published_trade_date == published_date
        reader.count_daily_bars_for_published_run.assert_called_once_with(
            expected, published_id
        )
        reader.count_daily_bars_for_snapshot.assert_not_called()


class TestSqlAlchemyErrorBoundary:
    """Coverage for :class:`DataFreshnessQueryError` translation."""

    def test_translates_snapshot_lookup_error(self) -> None:
        expected = date(2026, 7, 31)
        reader = MagicMock(name="DataFreshnessReader")
        original = OperationalError(
            "SELECT snapshot",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )
        reader.get_snapshot_for_trade_date.side_effect = original

        with pytest.raises(DataFreshnessQueryError) as exc_info:
            _build_service(reader).get_freshness(expected)

        assert exc_info.value.__cause__ is original
        assert (
            str(exc_info.value)
            == "Data freshness query failed"
        )

    def test_translates_published_lookup_error(self) -> None:
        expected = date(2026, 7, 31)
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = None
        reader.get_latest_published_candidate_pool_run.side_effect = OperationalError(
            "SELECT candidate pool runs",
            {},
            Exception("boom"),
        )

        with pytest.raises(DataFreshnessQueryError):
            _build_service(reader).get_freshness(expected)

    def test_translates_daily_bar_lookup_error(self) -> None:
        expected = date(2026, 7, 31)
        snapshot_ids = tuple(str(uuid4()) for _ in range(5))
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = _snapshot_row(
            instrument_ids=snapshot_ids, row_count=5
        )
        reader.get_latest_published_candidate_pool_run.return_value = None
        reader.count_daily_bars_for_snapshot.side_effect = OperationalError(
            "SELECT daily bars",
            {},
            Exception("boom"),
        )

        with pytest.raises(DataFreshnessQueryError):
            _build_service(reader).get_freshness(expected)

    def test_translates_included_items_count_error(self) -> None:
        expected = date(2026, 7, 31)
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = None
        reader.get_latest_published_candidate_pool_run.return_value = _published_row(
            trade_date=expected, input_row_count=1
        )
        reader.count_daily_bars_for_published_run.return_value = 0
        reader.count_included_items_for_run.side_effect = OperationalError(
            "SELECT candidate pool items",
            {},
            Exception("boom"),
        )

        with pytest.raises(DataFreshnessQueryError):
            _build_service(reader).get_freshness(expected)

    def test_translates_pipeline_run_lookup_error(self) -> None:
        expected = date(2026, 7, 31)
        reader = MagicMock(name="DataFreshnessReader")
        reader.get_snapshot_for_trade_date.return_value = None
        reader.get_latest_published_candidate_pool_run.return_value = None
        reader.get_latest_pipeline_run_for_partition.side_effect = OperationalError(
            "SELECT pipeline runs",
            {},
            Exception("boom"),
        )

        with pytest.raises(DataFreshnessQueryError):
            _build_service(reader).get_freshness(expected)

    def test_query_error_is_runtime_error_subclass(self) -> None:
        assert issubclass(DataFreshnessQueryError, RuntimeError)


class TestProtocol:
    """Coverage that the reader Protocol accepts structurally-compatible mocks."""

    def test_accepts_structurally_compatible_reader(self) -> None:
        class _CompatibleReader:
            def get_snapshot_for_trade_date(self, trade_date):
                return None

            def get_latest_published_candidate_pool_run(self):
                return None

            def count_included_items_for_run(self, run_id):
                return 0

            def count_daily_bars_for_snapshot(self, trade_date, instrument_ids):
                return 0

            def count_daily_bars_for_published_run(self, trade_date, run_id):
                return 0

            def get_latest_pipeline_run_for_partition(self, *, job_key, partition_key):
                return None

        service = DataFreshnessQueryService(_CompatibleReader())  # type: ignore[arg-type]
        view = service.get_freshness(date(2026, 7, 31))
        assert view.status == "missing"


__all__ = [
    "TestDefaultDate",
    "TestLatestWeekdayHelper",
    "TestNoPublishedRun",
    "TestProtocol",
    "TestSqlAlchemyErrorBoundary",
    "TestStatusStates",
]
