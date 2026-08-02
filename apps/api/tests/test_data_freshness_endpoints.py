"""Tests for the ``/api/v1/data-freshness`` read-only endpoint.

The endpoint runs raw ``text()`` queries through ``session.execute``,
so the test fixtures don't need a repository mock - they drive
``mock_session.execute`` directly. Each handler call issues a fixed
sequence of execute calls, so the tests populate
``mock_session.execute.side_effect`` with one ``MagicMock`` result per
query in order:

    1. active core.instruments count           -> ``.scalar_one()``
    2. latest published candidate-pool run    -> ``.first()`` (row or None)
    3. candidate_pool_items count (if any)    -> ``.scalar_one()``
    4. daily_bars distinct count               -> ``.scalar_one()``
    5. input_snapshots row for expected date  -> ``.first()`` (row or None)
    6. ops.pipeline_runs latest for partition -> ``.first()`` (row or None)
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
    universe_count: int,
    published: tuple | None,
    candidate_count: int,
    daily_bar_count: int,
    snapshot: tuple | None,
    pipeline: tuple | None,
) -> list[MagicMock]:
    results: list[MagicMock] = [_scalar(universe_count), _row(published)]
    if published is not None:
        results.append(_scalar(candidate_count))
    results.append(_scalar(daily_bar_count))
    results.append(_row(snapshot))
    results.append(_row(pipeline))
    return results


class TestDataFreshnessStatus:
    """Coverage for the five ``status`` outcomes the endpoint reports."""

    def test_fresh(
        self,
        client: TestClient,
        mock_session: MagicMock,
    ) -> None:
        run_id = uuid4()
        snapshot_id = uuid4()
        pipeline_id = uuid4()
        published = (run_id, EXPECTED, snapshot_id)
        mock_session.execute.side_effect = _build_results(
            universe_count=120,
            published=published,
            candidate_count=120,
            daily_bar_count=120,
            snapshot=(snapshot_id,),
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
        published = (uuid4(), EXPECTED, snapshot_id)
        mock_session.execute.side_effect = _build_results(
            universe_count=200,
            published=published,
            candidate_count=150,
            daily_bar_count=150,
            snapshot=(snapshot_id,),
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
        published = (uuid4(), stale_date, snapshot_id)
        mock_session.execute.side_effect = _build_results(
            universe_count=80,
            published=published,
            candidate_count=80,
            daily_bar_count=80,
            snapshot=(snapshot_id,),
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
            universe_count=50,
            published=None,
            candidate_count=0,
            daily_bar_count=0,
            snapshot=None,
            pipeline=None,
        )

        response = client.get(ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "missing"
        assert body["latest_published_trade_date"] is None
        assert body["universe_count"] == 50
        assert body["daily_bar_count"] == 0
        assert body["missing_count"] == 50
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
        published = (uuid4(), stale_date, snapshot_id)
        mock_session.execute.side_effect = _build_results(
            universe_count=100,
            published=published,
            candidate_count=100,
            daily_bar_count=0,
            snapshot=None,
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
        # First three queries succeed (no published => no items query), the
        # snapshot lookup blows up with a connection-level error.
        mock_session.execute.side_effect = [
            _scalar(10),
            _row(None),
            _scalar(0),
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
            universe_count=1,
            published=None,
            candidate_count=0,
            daily_bar_count=0,
            snapshot=None,
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
    "TestDataFreshnessStatus",
]
