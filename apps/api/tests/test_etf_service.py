"""Tests for :class:`invest_api.application.etf.EtfQueryService`.

The endpoint tests in :mod:`tests.test_etf_endpoints` mock the
application service at the FastAPI boundary and verify the HTTP
contract. These tests bypass the HTTP layer: they construct the real
service against mock repositories so they can assert that the service
itself owns the active-instrument universe fetch with the bounded
``INSTRUMENT_UNIVERSE_FETCH_LIMIT`` page, the ``exchange`` /
``status`` filter, the post-filter ``total``, the limit / offset
pagination slice, the instrument existence pre-check for
``/api/v1/etf/daily-bars``, the latest-revision-per-day reduction
(ADR-0006 §6) and the
:class:`sqlalchemy.exc.SQLAlchemyError` translation to
:class:`EtfQueryError`.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from invest_api.application.etf import (
    INSTRUMENT_UNIVERSE_FETCH_LIMIT,
    DailyBarRecord,
    EtfQueryError,
    EtfQueryService,
)
from invest_domain.market_data.values import Adjust
from sqlalchemy.exc import OperationalError

from tests.conftest import make_daily_bar, make_instrument


def _build_service() -> tuple[EtfQueryService, MagicMock, MagicMock]:
    """Return a real service wired to two mock repositories."""

    instrument_repo = MagicMock(name="InstrumentReader")
    daily_bar_repo = MagicMock(name="DailyBarReader")
    service = EtfQueryService(
        instrument_repository=instrument_repo,
        daily_bar_repository=daily_bar_repo,
    )
    return service, instrument_repo, daily_bar_repo


def _bar(
    instrument_id,
    *,
    trade_date: date,
    revision: int = 1,
) -> DailyBarRecord:
    return make_daily_bar(
        instrument_id=instrument_id, trade_date=trade_date, revision=revision
    )


class TestListActiveInstruments:
    """Coverage for :meth:`EtfQueryService.list_active_instruments`."""

    def test_fetches_full_universe_with_bounded_page(self) -> None:
        service, instrument_repo, _ = _build_service()
        sse = make_instrument(symbol="510050", exchange="SSE")
        szse = make_instrument(symbol="159915", exchange="SZSE")
        instrument_repo.list_active.return_value = [sse, szse]

        view = service.list_active_instruments(limit=100, offset=0)

        assert view.items == (sse, szse)
        assert view.total == 2
        instrument_repo.list_active.assert_called_once_with(
            limit=INSTRUMENT_UNIVERSE_FETCH_LIMIT, offset=0
        )

    def test_returns_empty_view_when_no_active_instruments(self) -> None:
        service, instrument_repo, _ = _build_service()
        instrument_repo.list_active.return_value = []

        view = service.list_active_instruments(limit=100, offset=0)

        assert view.items == ()
        assert view.total == 0
        assert view.limit == 100
        assert view.offset == 0

    def test_filters_by_exchange(self) -> None:
        service, instrument_repo, _ = _build_service()
        sse = make_instrument(symbol="510050", exchange="SSE")
        szse = make_instrument(symbol="159915", exchange="SZSE")
        instrument_repo.list_active.return_value = [sse, szse]

        view = service.list_active_instruments(
            exchange="SSE", limit=100, offset=0
        )

        assert view.items == (sse,)
        assert view.total == 1

    def test_filters_by_status_value(self) -> None:
        service, instrument_repo, _ = _build_service()
        active = make_instrument(symbol="510050")
        delisted = make_instrument(
            symbol="159915",
            status=__import__(
                "invest_domain.instruments", fromlist=["InstrumentStatus"]
            ).InstrumentStatus.DELISTED,
        )
        instrument_repo.list_active.return_value = [active, delisted]

        view = service.list_active_instruments(
            status_="delisted", limit=100, offset=0
        )

        assert [item.symbol for item in view.items] == ["159915"]
        assert view.total == 1

    @pytest.mark.parametrize(
        "limit,offset",
        [(1, 0), (50, 25), (100, 9999)],
    )
    def test_pagination_slices_filtered_total(self, limit: int, offset: int) -> None:
        service, instrument_repo, _ = _build_service()
        all_instruments = [
            make_instrument(symbol=f"5100{i:02d}") for i in range(10)
        ]
        instrument_repo.list_active.return_value = all_instruments

        view = service.list_active_instruments(limit=limit, offset=offset)

        assert view.items == tuple(all_instruments[offset : offset + limit])
        assert view.total == 10
        assert view.limit == limit
        assert view.offset == offset

    def test_uses_post_filter_total_when_filter_narrows_result(self) -> None:
        service, instrument_repo, _ = _build_service()
        instrument_repo.list_active.return_value = [
            make_instrument(symbol=f"5100{i:02d}", exchange="SSE" if i % 2 else "SZSE")
            for i in range(6)
        ]

        view = service.list_active_instruments(
            exchange="SSE", limit=2, offset=0
        )

        assert view.total == 3
        assert len(view.items) == 2

    def test_translates_sqlalchemy_error(self) -> None:
        from sqlalchemy.exc import OperationalError

        service, instrument_repo, _ = _build_service()
        instrument_repo.list_active.side_effect = OperationalError(
            "SELECT instruments",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        with pytest.raises(EtfQueryError):
            service.list_active_instruments(limit=100, offset=0)


class TestListLatestDailyBars:
    """Coverage for :meth:`EtfQueryService.list_latest_daily_bars`."""

    def test_returns_page_for_resolved_instrument(self) -> None:
        service, instrument_repo, daily_bar_repo = _build_service()
        instrument_id = uuid4()
        instrument = make_instrument(instrument_id=instrument_id, symbol="510050")
        bar_v2 = _bar(instrument_id, trade_date=date(2026, 7, 30), revision=2)
        bar_day2 = _bar(instrument_id, trade_date=date(2026, 7, 31), revision=1)
        instrument_repo.get_by_id.return_value = instrument
        daily_bar_repo.list_by_instrument_and_range.return_value = [
            _bar(instrument_id, trade_date=date(2026, 7, 30), revision=1),
            bar_v2,
            bar_day2,
        ]

        view = service.list_latest_daily_bars(
            instrument_id=instrument_id,
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 31),
            limit=100,
            offset=0,
        )

        assert view is not None
        assert view.items == (bar_v2, bar_day2)
        assert view.total == 2
        assert view.limit == 100
        assert view.offset == 0

    def test_returns_none_when_instrument_missing(self) -> None:
        service, instrument_repo, daily_bar_repo = _build_service()
        instrument_id = uuid4()
        instrument_repo.get_by_id.return_value = None

        view = service.list_latest_daily_bars(
            instrument_id=instrument_id,
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 31),
            limit=100,
            offset=0,
        )

        assert view is None
        daily_bar_repo.list_by_instrument_and_range.assert_not_called()

    def test_passes_adjustment_none_to_repository(self) -> None:
        service, instrument_repo, daily_bar_repo = _build_service()
        instrument_id = uuid4()
        instrument_repo.get_by_id.return_value = make_instrument(
            instrument_id=instrument_id
        )
        daily_bar_repo.list_by_instrument_and_range.return_value = []

        service.list_latest_daily_bars(
            instrument_id=instrument_id,
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
            limit=100,
            offset=0,
        )

        daily_bar_repo.list_by_instrument_and_range.assert_called_once_with(
            instrument_id=instrument_id,
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
            adjustment=Adjust.NONE,
        )

    def test_repositories_invocation_signature(self) -> None:
        service, instrument_repo, daily_bar_repo = _build_service()
        instrument_id = uuid4()
        instrument_repo.get_by_id.return_value = make_instrument(
            instrument_id=instrument_id
        )
        daily_bar_repo.list_by_instrument_and_range.return_value = []

        service.list_latest_daily_bars(
            instrument_id=instrument_id,
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
            limit=100,
            offset=0,
        )

        instrument_repo.get_by_id.assert_called_once_with(instrument_id)
        daily_bar_repo.list_by_instrument_and_range.assert_called_once()

    @pytest.mark.parametrize(
        "limit,offset",
        [(1, 0), (10, 5), (100, 999)],
    )
    def test_paginates_latest_per_day_page(self, limit: int, offset: int) -> None:
        service, instrument_repo, daily_bar_repo = _build_service()
        instrument_id = uuid4()
        instrument_repo.get_by_id.return_value = make_instrument(
            instrument_id=instrument_id
        )
        all_bars = [
            _bar(
                instrument_id,
                trade_date=date(2026, 7, 30 - i),
                revision=1,
            )
            for i in range(20)
        ]
        daily_bar_repo.list_by_instrument_and_range.return_value = all_bars

        view = service.list_latest_daily_bars(
            instrument_id=instrument_id,
            start_date=date(2026, 7, 11),
            end_date=date(2026, 7, 30),
            limit=limit,
            offset=offset,
        )

        assert view is not None
        assert view.total == 20
        assert view.limit == limit
        assert view.offset == offset
        sorted_bars = tuple(
            sorted(all_bars, key=lambda bar: bar.trade_date)
        )
        assert view.items == sorted_bars[offset : offset + limit]




    def test_reduction_keeps_highest_revision_per_trade_date(self) -> None:
        service, instrument_repo, daily_bar_repo = _build_service()
        instrument_id = uuid4()
        instrument_repo.get_by_id.return_value = make_instrument(
            instrument_id=instrument_id
        )
        bar_v1_day1 = _bar(
            instrument_id, trade_date=date(2026, 7, 30), revision=1
        )
        bar_v2_day1 = _bar(
            instrument_id, trade_date=date(2026, 7, 30), revision=2
        )
        bar_v3_day1 = _bar(
            instrument_id, trade_date=date(2026, 7, 30), revision=3
        )
        bar_v1_day2 = _bar(
            instrument_id, trade_date=date(2026, 7, 31), revision=1
        )
        # Repository returns sorted by trade_date then revision ASC;
        # the service must keep the highest revision per day.
        daily_bar_repo.list_by_instrument_and_range.return_value = [
            bar_v1_day1,
            bar_v2_day1,
            bar_v3_day1,
            bar_v1_day2,
        ]

        view = service.list_latest_daily_bars(
            instrument_id=instrument_id,
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 31),
            limit=100,
            offset=0,
        )

        assert view is not None
        assert view.items == (bar_v3_day1, bar_v1_day2)
        assert view.total == 2

    def test_reduction_keeps_only_single_revision_when_no_dupes(self) -> None:
        service, instrument_repo, daily_bar_repo = _build_service()
        instrument_id = uuid4()
        instrument_repo.get_by_id.return_value = make_instrument(
            instrument_id=instrument_id
        )
        bar_a = _bar(
            instrument_id, trade_date=date(2026, 7, 30), revision=1
        )
        bar_b = _bar(
            instrument_id, trade_date=date(2026, 7, 31), revision=1
        )
        bar_c = _bar(
            instrument_id, trade_date=date(2026, 8, 1), revision=1
        )
        daily_bar_repo.list_by_instrument_and_range.return_value = [bar_a, bar_b, bar_c]

        view = service.list_latest_daily_bars(
            instrument_id=instrument_id,
            start_date=date(2026, 7, 30),
            end_date=date(2026, 8, 1),
            limit=100,
            offset=0,
        )

        assert view is not None
        assert view.items == (bar_a, bar_b, bar_c)
        assert view.total == 3

    def test_reduction_sorts_latest_by_date_ascending(self) -> None:
        service, instrument_repo, daily_bar_repo = _build_service()
        instrument_id = uuid4()
        instrument_repo.get_by_id.return_value = make_instrument(
            instrument_id=instrument_id
        )
        bar_late = _bar(
            instrument_id, trade_date=date(2026, 7, 31), revision=1
        )
        bar_early = _bar(
            instrument_id, trade_date=date(2026, 7, 29), revision=1
        )
        bar_mid = _bar(
            instrument_id, trade_date=date(2026, 7, 30), revision=1
        )
        # Repository returns them out of order; the service must re-sort
        # by trade_date ascending before emitting the page.
        daily_bar_repo.list_by_instrument_and_range.return_value = [
            bar_late,
            bar_early,
            bar_mid,
        ]

        view = service.list_latest_daily_bars(
            instrument_id=instrument_id,
            start_date=date(2026, 7, 29),
            end_date=date(2026, 7, 31),
            limit=100,
            offset=0,
        )

        assert view is not None
        assert [item.trade_date for item in view.items] == [
            date(2026, 7, 29),
            date(2026, 7, 30),
            date(2026, 7, 31),
        ]

    def test_empty_repository_response_yields_empty_page(self) -> None:
        service, instrument_repo, daily_bar_repo = _build_service()
        instrument_id = uuid4()
        instrument_repo.get_by_id.return_value = make_instrument(
            instrument_id=instrument_id
        )
        daily_bar_repo.list_by_instrument_and_range.return_value = []

        view = service.list_latest_daily_bars(
            instrument_id=instrument_id,
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 31),
            limit=100,
            offset=0,
        )

        assert view is not None
        assert view.items == ()
        assert view.total == 0

    def test_repository_value_error_on_inverted_range_propagates(self) -> None:
        """The repository's inverted-range ``ValueError`` is not wrapped.

        The HTTP layer keeps the inverted-range 400 mapping, but if a
        caller bypasses that check the repository's contract is still
        preserved.
        """

        service, instrument_repo, daily_bar_repo = _build_service()
        instrument_id = uuid4()
        instrument_repo.get_by_id.return_value = make_instrument(
            instrument_id=instrument_id
        )
        daily_bar_repo.list_by_instrument_and_range.side_effect = ValueError(
            "end_date 2026-07-29 must be on or after start_date 2026-07-30"
        )

        with pytest.raises(ValueError, match="must be on or after"):
            service.list_latest_daily_bars(
                instrument_id=instrument_id,
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 29),
                limit=100,
                offset=0,
            )

    def test_translates_sqlalchemy_error_on_instrument_lookup(self) -> None:
        service, instrument_repo, _ = _build_service()
        instrument_repo.get_by_id.side_effect = OperationalError(
            "SELECT instrument by id",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        with pytest.raises(EtfQueryError):
            service.list_latest_daily_bars(
                instrument_id=uuid4(),
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 31),
                limit=100,
                offset=0,
            )

    def test_translates_sqlalchemy_error_on_daily_bar_lookup(self) -> None:
        service, instrument_repo, daily_bar_repo = _build_service()
        instrument_id = uuid4()
        instrument_repo.get_by_id.return_value = make_instrument(
            instrument_id=instrument_id
        )
        daily_bar_repo.list_by_instrument_and_range.side_effect = OperationalError(
            "SELECT daily bars",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        with pytest.raises(EtfQueryError):
            service.list_latest_daily_bars(
                instrument_id=instrument_id,
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 31),
                limit=100,
                offset=0,
            )

    def test_does_not_call_daily_bar_repo_when_instrument_missing(self) -> None:
        """The instrument pre-check short-circuits before daily-bar lookup."""

        service, instrument_repo, daily_bar_repo = _build_service()
        instrument_repo.get_by_id.return_value = None

        service.list_latest_daily_bars(
            instrument_id=uuid4(),
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 31),
            limit=100,
            offset=0,
        )

        daily_bar_repo.list_by_instrument_and_range.assert_not_called()


class TestEtfQueryError:
    """Coverage for the application exception type."""

    def test_is_runtime_error_subclass(self) -> None:
        assert issubclass(EtfQueryError, RuntimeError)

    def test_chains_original_sqlalchemy_cause(self) -> None:
        service, instrument_repo, _ = _build_service()
        original = OperationalError(
            "SELECT instruments",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )
        instrument_repo.list_active.side_effect = original

        with pytest.raises(EtfQueryError) as exc_info:
            service.list_active_instruments(limit=100, offset=0)

        assert exc_info.value.__cause__ is original


__all__ = [
    "TestEtfQueryError",
    "TestListActiveInstruments",
    "TestListLatestDailyBars",
]
