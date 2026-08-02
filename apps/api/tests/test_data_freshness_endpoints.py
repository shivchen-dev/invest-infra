"""Tests for the ``/api/v1/data-freshness`` read-only endpoint.

The endpoint runs raw ``text()`` queries through ``session.execute``,
so the test fixtures don't need a repository mock - they drive
``mock_session.execute.side_effect`` directly. Each handler call issues
a fixed sequence of execute calls, so the tests populate the side
effect with one ``MagicMock`` result per query in order:

    1. ``analytics.input_snapshots`` lookup for the expected date
       -> ``.first()`` (row of ``(id, instrument_ids, row_count)`` or
       ``None``)
    2. ``analytics.candidate_pool_runs`` latest published row
       -> ``.first()`` (row of ``(id, trade_date, input_row_count)`` or
       ``None``)
    3. ``analytics.candidate_pool_items`` count for the published run
       (only when the published row is non-null) -> ``.scalar_one()``
    4. ``core.daily_bars`` distinct count - the SQL depends on whether
       a snapshot was found, so the same single result covers both
       branches (snapshot path passes the membership list as an
       ``uuid[]``; fallback path uses a correlated ``IN`` sub-select
       against ``candidate_pool_items``) -> ``.scalar_one()``
    5. ``ops.pipeline_runs`` latest for the partition -> ``.first()``
       (row of ``(id, status)`` or ``None``)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from invest_api.routers import data_freshness as data_freshness_module
from invest_api.routers.data_freshness import latest_weekday
from sqlalchemy.exc import OperationalError

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


ENDPOINT = "/api/v1/data-freshness"
EXPECTED = date(2026, 7, 31)  # Friday


def _scalar(value: int) -> MagicMock:
    mock = MagicMock(name="ScalarResult")
    mock.scalar_one.return_value = value
    return mock


def _row(values: tuple | None) -> MagicMock:
    mock = MagicMock(name="RowResult")
    mock.first.return_value = values
    return mock


def _build_results(
    *,
    snapshot: tuple | None,
    published: tuple | None,
    candidate_count: int,
    daily_bar_count: int,
    pipeline: tuple | None,
) -> list[MagicMock]:
    """Build the ``session.execute.side_effect`` list for one handler call.

    The handler always queries the snapshot, then the latest published
    candidate-pool run, then (depending on which one resolved) a
    daily-bar count and the included-item count, then the pipeline run.
    The order below mirrors that sequence exactly so each call into
    ``session.execute`` consumes the correct mock.

    The snapshot tuple carries ``(id, instrument_ids, row_count)``;
    ``instrument_ids`` is the JSON-shaped list passed straight back to
    PostgreSQL through the ``uuid[]`` cast so tests can assert that the
    snapshot's instruments scope the daily-bar lookup. The published
    tuple carries ``(id, trade_date, input_row_count)`` to mirror the
    fallback path.
    """

    results: list[MagicMock] = [_row(snapshot), _row(published)]
    if snapshot is not None or published is not None:
        results.append(_scalar(daily_bar_count))
    if published is not None:
        results.append(_scalar(candidate_count))
    results.append(_row(pipeline))
    return results


class TestDataFreshnessStatus:
    """Coverage for the five ``status`` outcomes the endpoint reports."""

    def test_fresh(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        pipeline_id = uuid4()
        snapshot_ids = [str(uuid4()) for _ in range(120)]
        published = (uuid4(), EXPECTED, 120)
        mock_session.execute.side_effect = _build_results(
            snapshot=(snapshot_id, snapshot_ids, 120),
            published=published,
            candidate_count=120,
            daily_bar_count=120,
            pipeline=(pipeline_id, "succeeded"),
        )

        response = client.get(ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "fresh"
        assert body["universe_count"] == 120
        assert body["daily_bar_count"] == 120
        assert body["missing_count"] == 0
        assert body["candidate_count"] == 120
        assert body["latest_published_trade_date"] == EXPECTED.isoformat()
        assert body["snapshot_id"] == str(snapshot_id)
        assert body["pipeline_run_id"] == str(pipeline_id)
        assert body["pipeline_status"] == "succeeded"
        assert body["as_of"].startswith("2026-")  # ISO 8601 timestamp

    def test_partial(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        pipeline_id = uuid4()
        snapshot_ids = [str(uuid4()) for _ in range(200)]
        published = (uuid4(), EXPECTED, 150)
        mock_session.execute.side_effect = _build_results(
            snapshot=(snapshot_id, snapshot_ids, 200),
            published=published,
            candidate_count=150,
            daily_bar_count=150,
            pipeline=(pipeline_id, "succeeded"),
        )

        response = client.get(ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "partial"
        assert body["universe_count"] == 200
        assert body["daily_bar_count"] == 150
        assert body["missing_count"] == 50
        assert body["candidate_count"] == 150

    def test_stale(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        stale_date = EXPECTED - timedelta(days=7)
        snapshot_id = uuid4()
        pipeline_id = uuid4()
        snapshot_ids = [str(uuid4()) for _ in range(80)]
        published = (uuid4(), stale_date, 80)
        mock_session.execute.side_effect = _build_results(
            snapshot=(snapshot_id, snapshot_ids, 80),
            published=published,
            candidate_count=80,
            daily_bar_count=80,
            pipeline=(pipeline_id, "succeeded"),
        )

        response = client.get(ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "stale"
        assert body["latest_published_trade_date"] == stale_date.isoformat()
        assert body["daily_bar_count"] == 80
        assert body["missing_count"] == 0
        assert body["pipeline_status"] == "succeeded"

    def test_missing(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        mock_session.execute.side_effect = _build_results(
            snapshot=None,
            published=None,
            candidate_count=0,
            daily_bar_count=0,
            pipeline=None,
        )

        response = client.get(ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "missing"
        assert body["latest_published_trade_date"] is None
        assert body["universe_count"] == 0
        assert body["daily_bar_count"] == 0
        assert body["missing_count"] == 0
        assert body["candidate_count"] == 0
        assert body["snapshot_id"] is None
        assert body["pipeline_run_id"] is None
        assert body["pipeline_status"] is None

    def test_failed(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        stale_date = EXPECTED - timedelta(days=1)
        snapshot_id = uuid4()
        pipeline_id = uuid4()
        snapshot_ids = [str(uuid4()) for _ in range(100)]
        published = (uuid4(), stale_date, 100)
        mock_session.execute.side_effect = _build_results(
            snapshot=(snapshot_id, snapshot_ids, 100),
            published=published,
            candidate_count=100,
            daily_bar_count=0,
            pipeline=(pipeline_id, "failed"),
        )

        response = client.get(ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["latest_published_trade_date"] == stale_date.isoformat()
        assert body["pipeline_status"] == "failed"
        assert body["pipeline_run_id"] == str(pipeline_id)
        assert body["missing_count"] == 100


class TestDataFreshnessSnapshotUniverse:
    """Coverage for the snapshot-driven universe accounting (PR-02)."""

    def test_universe_count_uses_snapshot_row_count(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        snapshot_ids = [str(uuid4()) for _ in range(35)]
        published = (uuid4(), EXPECTED, 35)
        mock_session.execute.side_effect = _build_results(
            snapshot=(snapshot_id, snapshot_ids, 35),
            published=published,
            candidate_count=35,
            daily_bar_count=35,
            pipeline=(uuid4(), "succeeded"),
        )

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["universe_count"] == 35
        assert body["snapshot_id"] == str(snapshot_id)

    def test_snapshot_tie_breaker_prefers_latest_id(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        mock_session.execute.side_effect = _build_results(
            snapshot=(snapshot_id, [str(uuid4())], 1),
            published=(uuid4(), EXPECTED, 1),
            candidate_count=1,
            daily_bar_count=1,
            pipeline=(uuid4(), "succeeded"),
        )

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

        assert response.status_code == 200
        snapshot_query = str(mock_session.execute.call_args_list[0].args[0])
        assert "ORDER BY created_at DESC, id DESC" in snapshot_query

    def test_daily_bar_query_is_scoped_to_snapshot_instrument_ids(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        snapshot_ids = [str(uuid4()) for _ in range(10)]
        published = (uuid4(), EXPECTED, 10)
        mock_session.execute.side_effect = _build_results(
            snapshot=(snapshot_id, snapshot_ids, 10),
            published=published,
            candidate_count=10,
            daily_bar_count=7,
            pipeline=(uuid4(), "succeeded"),
        )

        response = client.get(ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()})

        assert response.status_code == 200
        # Locate the daily-bar query (the call that binds ``ids``); it
        # must carry the snapshot's instrument ids so the count is
        # scoped to the personal pool rather than every ETF in the
        # market.
        daily_bar_call = next(
            call
            for call in mock_session.execute.call_args_list
            if len(call.args) > 1 and "ids" in call.args[1]
        )
        bound_params = daily_bar_call.args[1]
        assert bound_params["trade_date"] == EXPECTED
        assert bound_params["ids"] == snapshot_ids

    def test_market_wide_bars_do_not_distort_missing_count(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        snapshot_ids = [str(uuid4()) for _ in range(50)]
        published = (uuid4(), EXPECTED, 30)
        mock_session.execute.side_effect = _build_results(
            snapshot=(snapshot_id, snapshot_ids, 50),
            published=published,
            candidate_count=30,
            daily_bar_count=30,
            pipeline=(uuid4(), "succeeded"),
        )

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

        assert response.status_code == 200
        body = response.json()
        # snapshot universe is 50 (covers the whole personal pool);
        # only 30 of them have a bar, so missing_count is 20 - it must
        # not be inflated by market-wide bars outside the snapshot.
        assert body["universe_count"] == 50
        assert body["daily_bar_count"] == 30
        assert body["missing_count"] == 20
        assert body["status"] == "partial"

    def test_snapshot_id_is_returned_when_snapshot_present(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        snapshot_ids = [str(uuid4()) for _ in range(5)]
        published = (uuid4(), EXPECTED, 5)
        mock_session.execute.side_effect = _build_results(
            snapshot=(snapshot_id, snapshot_ids, 5),
            published=published,
            candidate_count=5,
            daily_bar_count=5,
            pipeline=(uuid4(), "succeeded"),
        )

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

        body = response.json()
        assert body["snapshot_id"] == str(snapshot_id)


class TestDataFreshnessFallbackChain:
    """Coverage for the snapshot/published/empty fallback chain (PR-02)."""

    def test_no_snapshot_falls_back_to_published_input_row_count(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        pipeline_id = uuid4()
        # No snapshot for the expected date, but a published run from a
        # previous weekday. The handler must use ``input_row_count`` as
        # the universe and still scope the daily-bar lookup to the
        # published run's items.
        published = (uuid4(), EXPECTED - timedelta(days=1), 42)
        mock_session.execute.side_effect = _build_results(
            snapshot=None,
            published=published,
            candidate_count=40,
            daily_bar_count=37,
            pipeline=(pipeline_id, "succeeded"),
        )

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["snapshot_id"] is None
        assert body["universe_count"] == 42
        assert body["daily_bar_count"] == 37
        assert body["missing_count"] == 5
        assert body["candidate_count"] == 40

        # Locate the fallback daily-bar query (the one that binds
        # ``run_id`` to the published run). The correlated IN-sub-select
        # keeps the count scoped to the personal universe rather than
        # letting market-wide ETFs leak in.
        daily_bar_call = next(
            call
            for call in mock_session.execute.call_args_list
            if len(call.args) > 1 and "run_id" in call.args[1]
        )
        bound_params = daily_bar_call.args[1]
        assert bound_params["trade_date"] == EXPECTED
        assert bound_params["run_id"] == published[0]

    def test_no_snapshot_and_no_published_yields_zero_universe(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        mock_session.execute.side_effect = _build_results(
            snapshot=None,
            published=None,
            candidate_count=0,
            daily_bar_count=0,
            pipeline=None,
        )

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

        body = response.json()
        assert body["universe_count"] == 0
        assert body["daily_bar_count"] == 0
        assert body["missing_count"] == 0
        assert body["candidate_count"] == 0
        assert body["snapshot_id"] is None

    def test_partial_status_is_set_when_snapshot_misses_bars(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        snapshot_ids = [str(uuid4()) for _ in range(80)]
        published = (uuid4(), EXPECTED, 60)
        mock_session.execute.side_effect = _build_results(
            snapshot=(snapshot_id, snapshot_ids, 80),
            published=published,
            candidate_count=60,
            daily_bar_count=60,
            pipeline=(uuid4(), "succeeded"),
        )

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "partial"
        assert body["missing_count"] == 20


class TestDataFreshnessErrorSanitization:
    """A SQLAlchemy exception must surface as a sanitized HTTP 500."""

    def test_returns_500_with_sanitized_detail(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        mock_session.execute.side_effect = OperationalError(
            "SELECT 1",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        response = client.get(ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()})

        assert response.status_code == 500
        assert response.json() == {"detail": "Data freshness query failed"}
        # Ensure the original driver message (and any embedded secret) never leaks.
        assert "secret" not in response.text
        assert "OperationalError" not in response.text

    def test_returns_500_when_partition_key_query_fails(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        # The snapshot + published lookups succeed (the published row
        # is None so the candidate-count query is skipped), then the
        # daily-bar lookup blows up.
        mock_session.execute.side_effect = [
            _row(None),
            _row(None),
            OperationalError("SELECT", {}, Exception("boom")),
        ]

        response = client.get(ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()})

        assert response.status_code == 500
        assert response.json() == {"detail": "Data freshness query failed"}


class TestDataFreshnessDefaultDate:
    """When ``expected_trade_date`` is omitted the handler snaps to the latest weekday."""

    def test_default_uses_latest_weekday_helper(self) -> None:
        # Sanity-check the helper directly so the default behaviour is
        # documented and not coupled to the HTTP layer.
        assert latest_weekday(date(2026, 7, 31)) == date(2026, 7, 31)  # Friday
        assert latest_weekday(date(2026, 8, 1)) == date(2026, 7, 31)  # Saturday -> Friday
        assert latest_weekday(date(2026, 8, 2)) == date(2026, 7, 31)  # Sunday -> Friday
        assert latest_weekday(date(2026, 8, 3)) == date(2026, 8, 3)  # Monday

    def test_default_observed_via_partition_key(
        self,
        client: TestClient,
        mock_session: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Force "today" to be a Saturday so the handler should snap to the
        # previous Friday and query ops.pipeline_runs with that partition key.
        from datetime import date as _real_date

        class _FakeDate(_real_date):
            @classmethod
            def today(cls) -> _real_date:
                return _real_date(2026, 8, 1)  # Saturday

        monkeypatch.setattr(data_freshness_module, "date", _FakeDate)

        mock_session.execute.side_effect = _build_results(
            snapshot=None,
            published=None,
            candidate_count=0,
            daily_bar_count=0,
            pipeline=None,
        )

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        # Locate the execute call that targets ops.pipeline_runs (the last one
        # in the sequence) and confirm it bound partition_key to the Friday.
        last_call = mock_session.execute.call_args_list[-1]
        bound_params = last_call.kwargs.get("params") or last_call.args[1]
        assert bound_params["partition_key"] == date(2026, 7, 31).isoformat()
        assert bound_params["job_key"] == "personal_etf_daily_job"


__all__ = [
    "TestDataFreshnessDefaultDate",
    "TestDataFreshnessErrorSanitization",
    "TestDataFreshnessFallbackChain",
    "TestDataFreshnessSnapshotUniverse",
    "TestDataFreshnessStatus",
]