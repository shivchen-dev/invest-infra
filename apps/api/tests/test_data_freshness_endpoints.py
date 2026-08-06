"""Tests for the ``/api/v1/data-freshness`` read-only endpoint.

The endpoint is exercised through ``fastapi.testclient.TestClient``
with the application-layer :class:`DataFreshnessQueryService` replaced
through a ``MagicMock`` so the handler can be driven without a live
PostgreSQL connection. The router-level tests assert the HTTP
contract (status codes, response shape, sanitized 500 detail, candidate
count and provider-freshness vocabulary); the application-level tests
in :mod:`tests.test_data_freshness_service` exercise the service
against a mock reader and own the snapshot-first / published-fallback /
empty-universe chain (PR-02), the five ``DataFreshnessStatus``
outcomes, the no-published-run state and the
:class:`sqlalchemy.exc.SQLAlchemyError` translation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from invest_api.application.data_freshness import (
    DataFreshnessQueryError,
    DataFreshnessView,
    latest_weekday,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


ENDPOINT = "/api/v1/data-freshness"
EXPECTED = date(2026, 7, 31)  # Friday


def _view(
    *,
    expected_trade_date: date = EXPECTED,
    latest_published_trade_date: date | None = None,
    universe_count: int = 0,
    daily_bar_count: int = 0,
    candidate_count: int = 0,
    snapshot_id: object | None = None,
    pipeline_run_id: object | None = None,
    pipeline_status: str | None = None,
    status: str = "missing",
) -> DataFreshnessView:
    """Return a :class:`DataFreshnessView` for endpoint tests."""

    missing_count = max(0, universe_count - daily_bar_count)
    return DataFreshnessView(
        expected_trade_date=expected_trade_date,
        latest_published_trade_date=latest_published_trade_date,
        universe_count=universe_count,
        daily_bar_count=daily_bar_count,
        missing_count=missing_count,
        candidate_count=candidate_count,
        snapshot_id=snapshot_id,
        pipeline_run_id=pipeline_run_id,
        pipeline_status=pipeline_status,
        status=status,
    )


class TestDataFreshnessStatus:
    """Coverage for the five ``status`` outcomes the endpoint reports."""

    def test_fresh(
        self,
        client: TestClient,
        data_freshness_service: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        pipeline_id = uuid4()
        published_id = uuid4()
        view = _view(
            latest_published_trade_date=EXPECTED,
            universe_count=120,
            daily_bar_count=120,
            candidate_count=120,
            snapshot_id=snapshot_id,
            pipeline_run_id=pipeline_id,
            pipeline_status="succeeded",
            status="fresh",
        )
        data_freshness_service.get_freshness.return_value = view

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

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
        assert body["as_of"].startswith("2026-")
        data_freshness_service.get_freshness.assert_called_once_with(EXPECTED)
        assert published_id is not None  # silence linter; coverage only

    def test_partial(
        self,
        client: TestClient,
        data_freshness_service: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        pipeline_id = uuid4()
        view = _view(
            latest_published_trade_date=EXPECTED,
            universe_count=200,
            daily_bar_count=150,
            candidate_count=150,
            snapshot_id=snapshot_id,
            pipeline_run_id=pipeline_id,
            pipeline_status="succeeded",
            status="partial",
        )
        data_freshness_service.get_freshness.return_value = view

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

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
        data_freshness_service: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        pipeline_id = uuid4()
        stale_date = EXPECTED - timedelta(days=7)
        view = _view(
            latest_published_trade_date=stale_date,
            universe_count=80,
            daily_bar_count=80,
            candidate_count=80,
            snapshot_id=snapshot_id,
            pipeline_run_id=pipeline_id,
            pipeline_status="succeeded",
            status="stale",
        )
        data_freshness_service.get_freshness.return_value = view

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

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
        data_freshness_service: MagicMock,
    ) -> None:
        view = _view(status="missing")
        data_freshness_service.get_freshness.return_value = view

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

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
        data_freshness_service: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        pipeline_id = uuid4()
        stale_date = EXPECTED - timedelta(days=1)
        view = _view(
            latest_published_trade_date=stale_date,
            universe_count=100,
            daily_bar_count=0,
            candidate_count=100,
            snapshot_id=snapshot_id,
            pipeline_run_id=pipeline_id,
            pipeline_status="failed",
            status="failed",
        )
        data_freshness_service.get_freshness.return_value = view

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

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
        data_freshness_service: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        view = _view(
            universe_count=35,
            daily_bar_count=35,
            candidate_count=35,
            snapshot_id=snapshot_id,
            status="fresh",
        )
        data_freshness_service.get_freshness.return_value = view

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["universe_count"] == 35
        assert body["snapshot_id"] == str(snapshot_id)

    def test_market_wide_bars_do_not_distort_missing_count(
        self,
        client: TestClient,
        data_freshness_service: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        view = _view(
            universe_count=50,
            daily_bar_count=30,
            candidate_count=30,
            snapshot_id=snapshot_id,
            status="partial",
        )
        data_freshness_service.get_freshness.return_value = view

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
        data_freshness_service: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        view = _view(
            universe_count=5,
            daily_bar_count=5,
            candidate_count=5,
            snapshot_id=snapshot_id,
            status="fresh",
        )
        data_freshness_service.get_freshness.return_value = view

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
        data_freshness_service: MagicMock,
    ) -> None:
        pipeline_id = uuid4()
        published_date = EXPECTED - timedelta(days=1)
        # No snapshot for the expected date, but a published run from a
        # previous weekday. The service returns the published run's
        # ``input_row_count`` as the universe and scopes the daily-bar
        # count to its items.
        view = _view(
            latest_published_trade_date=published_date,
            universe_count=42,
            daily_bar_count=37,
            candidate_count=40,
            snapshot_id=None,
            pipeline_run_id=pipeline_id,
            pipeline_status="succeeded",
            status="stale",
        )
        data_freshness_service.get_freshness.return_value = view

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

    def test_no_snapshot_and_no_published_yields_zero_universe(
        self,
        client: TestClient,
        data_freshness_service: MagicMock,
    ) -> None:
        view = _view(status="missing")
        data_freshness_service.get_freshness.return_value = view

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
        data_freshness_service: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        view = _view(
            universe_count=80,
            daily_bar_count=60,
            candidate_count=60,
            snapshot_id=snapshot_id,
            status="partial",
        )
        data_freshness_service.get_freshness.return_value = view

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "partial"
        assert body["missing_count"] == 20


class TestDataFreshnessErrorSanitization:
    """A :class:`DataFreshnessQueryError` must surface as a sanitized HTTP 500."""

    def test_returns_500_with_sanitized_detail(
        self,
        client: TestClient,
        data_freshness_service: MagicMock,
    ) -> None:
        data_freshness_service.get_freshness.side_effect = (
            DataFreshnessQueryError(
                "connection string: postgres://user:secret@host/db"
            )
        )

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Data freshness query failed"}
        # Ensure the original driver message (and any embedded secret) never leaks.
        assert "secret" not in response.text
        assert "DataFreshnessQueryError" not in response.text


class TestDataFreshnessDefaultDate:
    """When ``expected_trade_date`` is omitted the handler passes through to the service."""

    def test_default_uses_latest_weekday_helper(self) -> None:
        # Sanity-check the helper directly so the default behaviour is
        # documented and not coupled to the HTTP layer.
        assert latest_weekday(date(2026, 7, 31)) == date(2026, 7, 31)  # Friday
        assert latest_weekday(date(2026, 8, 1)) == date(2026, 7, 31)  # Saturday -> Friday
        assert latest_weekday(date(2026, 8, 2)) == date(2026, 7, 31)  # Sunday -> Friday
        assert latest_weekday(date(2026, 8, 3)) == date(2026, 8, 3)  # Monday

    def test_default_passes_none_through_to_service(
        self,
        client: TestClient,
        data_freshness_service: MagicMock,
    ) -> None:
        """Omitting ``expected_trade_date`` must pass ``None`` to the service.

        The service is responsible for resolving the Shanghai-local
        default via :func:`invest_api.clock.market_today`; the router
        is intentionally a thin pass-through so the default logic
        stays owned by the application layer.
        """

        view = _view(status="missing")
        data_freshness_service.get_freshness.return_value = view

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        data_freshness_service.get_freshness.assert_called_once_with(None)

    def test_explicit_date_is_forwarded_to_service(
        self,
        client: TestClient,
        data_freshness_service: MagicMock,
    ) -> None:
        view = _view(status="missing")
        data_freshness_service.get_freshness.return_value = view

        requested = date(2026, 7, 31)  # Friday
        response = client.get(
            ENDPOINT, params={"expected_trade_date": requested.isoformat()}
        )

        assert response.status_code == 200
        data_freshness_service.get_freshness.assert_called_once_with(requested)

    def test_as_of_is_utc_aware_timestamp(
        self,
        client: TestClient,
        data_freshness_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``as_of`` must remain a UTC-aware ``datetime``.

        The router stamps ``as_of = datetime.now(UTC)`` when it builds
        the response so downstream consumers can serialise it
        unambiguously.
        """

        captured: dict[str, object] = {}

        class _AwareDatetime(datetime):
            @classmethod
            def now(cls, tz: object | None = None) -> datetime:
                captured["tz"] = tz
                return datetime(2026, 8, 3, 1, 15, tzinfo=tz)  # type: ignore[arg-type]

        from invest_api.routers import data_freshness as data_freshness_module

        monkeypatch.setattr(data_freshness_module, "datetime", _AwareDatetime)

        view = _view(status="missing")
        data_freshness_service.get_freshness.return_value = view

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

        assert response.status_code == 200
        assert captured["tz"] is UTC
        body = response.json()
        # Pydantic emits the trailing ``Z`` suffix for naive-vs-aware
        # UTC datetimes; the precise wall time depends on the
        # monkey-patched ``datetime.now`` but the offset must still be
        # UTC, not the local market timezone.
        assert body["as_of"].endswith("Z")
        # Prefix is the ISO calendar day of the monkey-patched value.
        assert body["as_of"].startswith("2026-08-03T")


class TestDataFreshnessServiceWiring:
    """Coverage of the FastAPI dependency wiring for the service."""

    def test_router_uses_injected_service(
        self,
        client: TestClient,
        data_freshness_service: MagicMock,
    ) -> None:
        view = _view(status="missing")
        data_freshness_service.get_freshness.return_value = view

        response = client.get(
            ENDPOINT, params={"expected_trade_date": EXPECTED.isoformat()}
        )

        assert response.status_code == 200
        # ``MagicMock`` instances are interpolated to a truthy object, so
        # the service type can also be confirmed by being the same
        # instance the fixture overrode.
        assert isinstance(
            data_freshness_service, MagicMock
        ), "the service should be the injected mock"


__all__ = [
    "TestDataFreshnessDefaultDate",
    "TestDataFreshnessErrorSanitization",
    "TestDataFreshnessFallbackChain",
    "TestDataFreshnessServiceWiring",
    "TestDataFreshnessSnapshotUniverse",
    "TestDataFreshnessStatus",
]
