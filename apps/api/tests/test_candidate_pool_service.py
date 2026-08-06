"""Tests for :class:`invest_api.application.candidate_pool.CandidatePoolQueryService`.

The endpoint tests in :mod:`tests.test_candidate_pool_endpoints` mock
the application service at the FastAPI boundary and verify the HTTP
contract. These tests bypass the HTTP layer: they construct the real
service against mock repositories so they can assert that the service
itself owns the ``PUBLISHED`` filter, the input-snapshot lookup, the
predecessor selection, the included-only set diff, the
:class:`sqlalchemy.exc.SQLAlchemyError` translation to
:class:`CandidatePoolQueryError`, and the missing-snapshot signal that
the router maps to a sanitized ``500``.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from invest_api.application.candidate_pool import (
    LATEST_LOOKBACK_LIMIT,
    CandidatePoolDiffView,
    CandidatePoolQueryError,
    CandidatePoolQueryService,
    CandidatePoolSnapshotMissingError,
    LatestCandidatePoolView,
)
from invest_domain.candidate_pool.models import (
    CandidatePoolStatus,
)
from invest_domain.instruments.models import InstrumentId

from tests.conftest import (
    make_candidate_pool_run,
    make_input_snapshot,
    make_instrument,
    make_pool_item,
)


def _build_service() -> tuple[
    CandidatePoolQueryService,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    """Return a real service wired to four mock repositories."""

    run_repository = MagicMock(name="CandidatePoolRunReader")
    item_repository = MagicMock(name="CandidatePoolItemReader")
    snapshot_repository = MagicMock(name="InputSnapshotReader")
    instrument_repository = MagicMock(name="InstrumentReader")
    service = CandidatePoolQueryService(
        run_repository=run_repository,
        item_repository=item_repository,
        snapshot_repository=snapshot_repository,
        instrument_repository=instrument_repository,
    )
    return service, run_repository, item_repository, snapshot_repository, instrument_repository


class TestGetLatest:
    """Coverage for :meth:`CandidatePoolQueryService.get_latest`."""

    def test_returns_view_for_latest_published_run(self) -> None:
        (
            service,
            run_repository,
            item_repository,
            snapshot_repository,
            instrument_repository,
        ) = _build_service()
        snapshot = make_input_snapshot(snapshot_date=date(2026, 7, 31))
        run = make_candidate_pool_run(input_snapshot_id=snapshot.id)
        instrument_id = uuid4()
        included_item = make_pool_item(instrument_id=instrument_id, rank=1)
        instrument = make_instrument(
            instrument_id=InstrumentId(instrument_id),
            symbol="510300",
            name="HS300 ETF",
            exchange="SSE",
        )
        run_repository.list_by_status.return_value = [run]
        snapshot_repository.list_by_date.return_value = [snapshot]
        item_repository.list_by_run_id.return_value = [included_item]
        instrument_repository.get_many_by_ids.return_value = {instrument_id: instrument}

        result = service.get_latest()

        assert isinstance(result, LatestCandidatePoolView)
        assert result.run is run
        assert result.snapshot is snapshot
        assert result.items == (included_item,)
        assert result.instruments_by_id == {instrument_id: instrument}
        run_repository.list_by_status.assert_called_once_with(
            CandidatePoolStatus.PUBLISHED, limit=1, offset=0
        )
        snapshot_repository.list_by_date.assert_called_once_with(run.trade_date)
        item_repository.list_by_run_id.assert_called_once_with(run.id)
        instrument_repository.get_many_by_ids.assert_called_once()

    def test_returns_none_when_no_published_run_exists(self) -> None:
        (
            service,
            run_repository,
            _item_repository,
            _snapshot_repository,
            _instrument_repository,
        ) = _build_service()
        run_repository.list_by_status.return_value = []

        assert service.get_latest() is None
        run_repository.list_by_status.assert_called_once_with(
            CandidatePoolStatus.PUBLISHED, limit=1, offset=0
        )

    def test_raises_snapshot_missing_when_snapshot_cannot_be_located(self) -> None:
        (
            service,
            run_repository,
            _item_repository,
            snapshot_repository,
            _instrument_repository,
        ) = _build_service()
        run = make_candidate_pool_run()
        run_repository.list_by_status.return_value = [run]
        snapshot_repository.list_by_date.return_value = []

        with pytest.raises(CandidatePoolSnapshotMissingError) as exc_info:
            service.get_latest()

        assert exc_info.value.run_id == run.id
        assert exc_info.value.snapshot_id == run.input_snapshot_id

    def test_translates_sqlalchemy_error_on_run_lookup(self) -> None:
        from sqlalchemy.exc import OperationalError

        (
            service,
            run_repository,
            _item_repository,
            _snapshot_repository,
            _instrument_repository,
        ) = _build_service()
        run_repository.list_by_status.side_effect = OperationalError(
            "SELECT candidate pool runs",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        with pytest.raises(CandidatePoolQueryError):
            service.get_latest()

    def test_translates_sqlalchemy_error_on_snapshot_lookup(self) -> None:
        from sqlalchemy.exc import OperationalError

        (
            service,
            run_repository,
            _item_repository,
            snapshot_repository,
            _instrument_repository,
        ) = _build_service()
        run = make_candidate_pool_run()
        run_repository.list_by_status.return_value = [run]
        snapshot_repository.list_by_date.side_effect = OperationalError(
            "SELECT input snapshots",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        with pytest.raises(CandidatePoolQueryError):
            service.get_latest()

    def test_translates_sqlalchemy_error_on_item_lookup(self) -> None:
        from sqlalchemy.exc import OperationalError

        (
            service,
            run_repository,
            item_repository,
            snapshot_repository,
            _instrument_repository,
        ) = _build_service()
        snapshot = make_input_snapshot(snapshot_date=__import__("datetime").date(2026, 7, 31))
        run = make_candidate_pool_run(input_snapshot_id=snapshot.id)
        run_repository.list_by_status.return_value = [run]
        snapshot_repository.list_by_date.return_value = [snapshot]
        item_repository.list_by_run_id.side_effect = OperationalError(
            "SELECT candidate pool items",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        with pytest.raises(CandidatePoolQueryError):
            service.get_latest()

    def test_translates_sqlalchemy_error_on_instrument_lookup(self) -> None:
        from sqlalchemy.exc import OperationalError

        (
            service,
            run_repository,
            item_repository,
            snapshot_repository,
            instrument_repository,
        ) = _build_service()
        snapshot = make_input_snapshot(snapshot_date=__import__("datetime").date(2026, 7, 31))
        run = make_candidate_pool_run(input_snapshot_id=snapshot.id)
        instrument_id = uuid4()
        included_item = make_pool_item(instrument_id=instrument_id, rank=1)
        run_repository.list_by_status.return_value = [run]
        snapshot_repository.list_by_date.return_value = [snapshot]
        item_repository.list_by_run_id.return_value = [included_item]
        instrument_repository.get_many_by_ids.side_effect = OperationalError(
            "SELECT instruments",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        with pytest.raises(CandidatePoolQueryError):
            service.get_latest()


class TestGetLatestDiff:
    """Coverage for :meth:`CandidatePoolQueryService.get_latest_diff`."""

    def test_returns_none_when_no_published_run_exists(self) -> None:
        (
            service,
            run_repository,
            _item_repository,
            _snapshot_repository,
            _instrument_repository,
        ) = _build_service()
        run_repository.list_by_status.return_value = []

        assert service.get_latest_diff() is None

    def test_returns_view_for_latest_published_run(self) -> None:
        (
            service,
            run_repository,
            item_repository,
            _snapshot_repository,
            instrument_repository,
        ) = _build_service()
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        retained = uuid4()
        added = uuid4()
        item_repository.list_by_run_id.side_effect = [
            [
                make_pool_item(instrument_id=retained, rank=1),
                make_pool_item(instrument_id=added, rank=2),
            ],
            [make_pool_item(instrument_id=retained, rank=1)],
        ]
        run_repository.list_by_status.side_effect = [
            [current],
            [current, previous],
        ]
        instrument_repository.get_many_by_ids.return_value = {}

        result = service.get_latest_diff()

        assert isinstance(result, CandidatePoolDiffView)
        assert result.trade_date == current.trade_date
        assert result.previous_trade_date == previous.trade_date
        added_entry = result.added[0]
        retained_entry = result.retained[0]
        assert added_entry.instrument_id == added
        assert retained_entry.instrument_id == retained
        assert result.removed == ()
        run_repository.list_by_status.assert_any_call(
            CandidatePoolStatus.PUBLISHED, limit=1, offset=0
        )
        run_repository.list_by_status.assert_any_call(
            CandidatePoolStatus.PUBLISHED, limit=LATEST_LOOKBACK_LIMIT, offset=0
        )

    def test_translates_sqlalchemy_error(self) -> None:
        from sqlalchemy.exc import OperationalError

        (
            service,
            run_repository,
            _item_repository,
            _snapshot_repository,
            _instrument_repository,
        ) = _build_service()
        run_repository.list_by_status.side_effect = OperationalError(
            "SELECT candidate pool runs",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        with pytest.raises(CandidatePoolQueryError):
            service.get_latest_diff()


class TestGetRunDiff:
    """Coverage for :meth:`CandidatePoolQueryService.get_run_diff`."""

    def test_returns_none_when_run_missing(self) -> None:
        (
            service,
            run_repository,
            _item_repository,
            _snapshot_repository,
            _instrument_repository,
        ) = _build_service()
        run_repository.get_by_id.return_value = None
        run_id = uuid4()

        assert service.get_run_diff(run_id) is None
        run_repository.get_by_id.assert_called_once_with(run_id)

    @pytest.mark.parametrize("status_value", ["calculated", "validated", "rejected"])
    def test_returns_none_for_non_published_run(self, status_value: str) -> None:
        (
            service,
            run_repository,
            _item_repository,
            _snapshot_repository,
            _instrument_repository,
        ) = _build_service()
        run = make_candidate_pool_run(status=CandidatePoolStatus(status_value))
        run_repository.get_by_id.return_value = run

        assert service.get_run_diff(run.id) is None

    def test_translates_sqlalchemy_error(self) -> None:
        from sqlalchemy.exc import OperationalError

        (
            service,
            run_repository,
            _item_repository,
            _snapshot_repository,
            _instrument_repository,
        ) = _build_service()
        run_repository.get_by_id.side_effect = OperationalError(
            "SELECT candidate pool run by id",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        with pytest.raises(CandidatePoolQueryError):
            service.get_run_diff(uuid4())


class TestIncludedOnlyDiff:
    """Coverage for the included-only membership diff invariant.

    The diff MUST reflect candidate-pool membership changes only: items
    with ``included=False`` are excluded from every bucket, even when
    they were included in a previous run.
    """

    def test_diff_excludes_excluded_items_from_all_buckets(self) -> None:
        (
            service,
            run_repository,
            item_repository,
            _snapshot_repository,
            instrument_repository,
        ) = _build_service()
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        retained = uuid4()
        excluded_previous = uuid4()
        excluded_current = uuid4()

        run_repository.get_by_id.return_value = current
        run_repository.list_by_status.return_value = [current, previous]
        item_repository.list_by_run_id.side_effect = [
            [
                make_pool_item(instrument_id=retained, rank=1),
                make_pool_item(
                    instrument_id=excluded_current,
                    included=False,
                    rank=None,
                    total_score=None,
                ),
            ],
            [
                make_pool_item(instrument_id=retained, rank=1),
                make_pool_item(
                    instrument_id=excluded_previous,
                    included=False,
                    rank=None,
                    total_score=None,
                ),
            ],
        ]
        instrument_repository.get_many_by_ids.return_value = {}

        result = service.get_run_diff(current.id)

        assert isinstance(result, CandidatePoolDiffView)
        all_entry_ids = {
            entry.instrument_id
            for entry in (*result.added, *result.retained, *result.removed)
        }
        assert all_entry_ids == {retained}
        assert result.added == ()
        assert result.removed == ()

    def test_diff_orders_added_entries_by_symbol_then_id(self) -> None:
        (
            service,
            run_repository,
            item_repository,
            _snapshot_repository,
            instrument_repository,
        ) = _build_service()
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        first = uuid4()
        second = uuid4()
        third = uuid4()
        run_repository.get_by_id.return_value = current
        run_repository.list_by_status.return_value = [current]
        item_repository.list_by_run_id.return_value = [
            make_pool_item(instrument_id=first, rank=1),
            make_pool_item(instrument_id=second, rank=2),
            make_pool_item(instrument_id=third, rank=3),
        ]
        instrument_repository.get_many_by_ids.return_value = {
            first: make_instrument(
                instrument_id=InstrumentId(first),
                symbol="159915",
                name="ChiNext ETF",
                exchange="SZSE",
            ),
            second: make_instrument(
                instrument_id=InstrumentId(second),
                symbol="510300",
                name="HS300 ETF",
                exchange="SSE",
            ),
            third: make_instrument(
                instrument_id=InstrumentId(third),
                symbol="510500",
                name="SSE 500 ETF",
                exchange="SSE",
            ),
        }

        result = service.get_run_diff(current.id)

        assert [entry.symbol for entry in result.added] == ["159915", "510300", "510500"]

    def test_diff_with_no_previous_run_reports_all_included_as_added(self) -> None:
        (
            service,
            run_repository,
            item_repository,
            _snapshot_repository,
            instrument_repository,
        ) = _build_service()
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        first = uuid4()
        second = uuid4()
        run_repository.get_by_id.return_value = current
        run_repository.list_by_status.return_value = [current]
        item_repository.list_by_run_id.return_value = [
            make_pool_item(instrument_id=first, rank=1),
            make_pool_item(instrument_id=second, rank=2),
        ]
        instrument_repository.get_many_by_ids.return_value = {
            first: make_instrument(
                instrument_id=InstrumentId(first),
                symbol="510500",
                name="SSE 500 ETF",
                exchange="SSE",
            ),
            second: make_instrument(
                instrument_id=InstrumentId(second),
                symbol="510300",
                name="HS300 ETF",
                exchange="SSE",
            ),
        }

        result = service.get_run_diff(current.id)

        assert result.previous_trade_date is None
        assert {entry.instrument_id for entry in result.added} == {first, second}
        assert result.retained == ()
        assert result.removed == ()
        assert [entry.symbol for entry in result.added] == sorted(
            [entry.symbol for entry in result.added]
        )


class TestCandidatePoolQueryError:
    """Coverage for the application exception types."""

    def test_candidate_pool_query_error_is_runtime_error_subclass(self) -> None:
        assert issubclass(CandidatePoolQueryError, RuntimeError)

    def test_candidate_pool_query_error_chains_original_cause(self) -> None:
        from sqlalchemy.exc import OperationalError

        (
            service,
            run_repository,
            _item_repository,
            _snapshot_repository,
            _instrument_repository,
        ) = _build_service()
        original = OperationalError(
            "SELECT candidate pool runs",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )
        run_repository.list_by_status.side_effect = original

        with pytest.raises(CandidatePoolQueryError) as exc_info:
            service.get_latest()

        assert exc_info.value.__cause__ is original

    def test_snapshot_missing_error_carries_identifiers(self) -> None:
        snapshot_id = uuid4()
        run_id = uuid4()
        error = CandidatePoolSnapshotMissingError(snapshot_id=snapshot_id, run_id=run_id)
        assert error.snapshot_id == snapshot_id
        assert error.run_id == run_id
        assert str(error) == (
            f"input snapshot {snapshot_id} referenced by run {run_id} not found"
        )


__all__ = [
    "TestCandidatePoolQueryError",
    "TestGetLatest",
    "TestGetLatestDiff",
    "TestGetRunDiff",
    "TestIncludedOnlyDiff",
]