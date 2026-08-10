"""Tests for the ``/api/v1/market-breadth`` read-only endpoint.

The endpoint is exercised through ``fastapi.testclient.TestClient``
with the application-layer :class:`MarketBreadthQueryService` replaced
through a ``MagicMock`` so the handler can be driven without a live
PostgreSQL connection. The router-level tests assert the HTTP contract
(status codes, response shape, sanitized 500 detail, optional
``as_of_date`` query parameter and the OpenAPI declaration); the
application-level tests in :mod:`tests.test_market_breadth_service`
exercise the service against a mock reader and own the scope-pinning,
the ``as_of_date`` passthrough, the no-row state and the
:class:`sqlalchemy.exc.SQLAlchemyError` translation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import UUID

from invest_api.application.market_breadth import MarketBreadthQueryError
from invest_api.main import app
from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


ENDPOINT = "/api/v1/market-breadth/latest"


def _snapshot() -> MarketObservationSnapshot:
    return MarketObservationSnapshot(
        input_snapshot_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        as_of_date=date(2026, 8, 7),
        observations=(
            MarketObservation(
                observation_key="advancing_ratio",
                value=Decimal("0.6"),
                unit="ratio",
                observed_date=date(2026, 8, 7),
                source_kind="computed",
                source_ref="calc:market_breadth",
            ),
            MarketObservation(
                observation_key="declining_ratio",
                value=Decimal("0.3"),
                unit="ratio",
                observed_date=date(2026, 8, 7),
                source_kind="computed",
                source_ref="calc:market_breadth",
            ),
            MarketObservation(
                observation_key="above_ma20_ratio",
                value=Decimal("0.55"),
                unit="ratio",
                observed_date=date(2026, 8, 7),
                source_kind="computed",
                source_ref="calc:market_breadth",
            ),
        ),
    )


class TestMarketBreadthLatest:
    """Coverage for the happy-path serialization of a breadth snapshot."""

    def test_latest_serializes_read_only_snapshot(
        self,
        client: TestClient,
        market_breadth_service: MagicMock,
    ) -> None:
        snapshot = _snapshot()
        market_breadth_service.get_latest.return_value = snapshot

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["snapshot_id"] == snapshot.snapshot_id
        assert body["as_of_date"] == "2026-08-07"
        assert body["algorithm_version"] == snapshot.algorithm_version
        assert body["scope_type"] == snapshot.scope_type
        assert body["scope_key"] == snapshot.scope_key
        assert body["quality_status"] == snapshot.quality_status.value
        assert body["freshness_status"] == snapshot.freshness_status.value
        assert body["content_hash"] == snapshot.content_hash
        assert body["input_snapshot_id"] == str(snapshot.input_snapshot_id)
        assert [item["observation_key"] for item in body["observations"]] == [
            "above_ma20_ratio",
            "advancing_ratio",
            "declining_ratio",
        ]
        assert body["observations"][0]["value"] == "0.55"
        # Internal identifiers / paths / secrets must not leak.
        assert "workspace_path" not in response.text
        assert "api_key" not in response.text
        market_breadth_service.get_latest.assert_called_once_with(None)

    def test_latest_forwards_as_of_date_query(
        self,
        client: TestClient,
        market_breadth_service: MagicMock,
    ) -> None:
        market_breadth_service.get_latest.return_value = _snapshot()
        target = date(2026, 8, 7)

        response = client.get(ENDPOINT, params={"as_of_date": target.isoformat()})

        assert response.status_code == 200
        market_breadth_service.get_latest.assert_called_once_with(target)


class TestMarketBreadthMissing:
    """The router must surface an empty reader as a sanitized 404."""

    def test_returns_404_when_no_snapshot(
        self,
        client: TestClient,
        market_breadth_service: MagicMock,
    ) -> None:
        market_breadth_service.get_latest.return_value = None

        response = client.get(ENDPOINT)

        assert response.status_code == 404
        assert response.json() == {"detail": "Market breadth snapshot not found"}


class TestMarketBreadthInvalidDate:
    """FastAPI rejects a malformed ``as_of_date`` query parameter with 422."""

    def test_returns_422_for_unparseable_date(
        self,
        client: TestClient,
        market_breadth_service: MagicMock,
    ) -> None:
        response = client.get(ENDPOINT, params={"as_of_date": "not-a-date"})

        assert response.status_code == 422
        market_breadth_service.get_latest.assert_not_called()


class TestMarketBreadthQueryError:
    """A :class:`MarketBreadthQueryError` must surface as a sanitized HTTP 500."""

    def test_sanitizes_query_error(
        self,
        client: TestClient,
        market_breadth_service: MagicMock,
    ) -> None:
        market_breadth_service.get_latest.side_effect = MarketBreadthQueryError(
            "connection string: postgres://user:secret@host/db"
        )

        response = client.get(ENDPOINT)

        assert response.status_code == 500
        assert response.json() == {"detail": "Market breadth query failed"}
        assert "postgres" not in response.text
        assert "secret" not in response.text


class TestMarketBreadthOpenAPI:
    """The breadth surface is a single GET and declares no other operations."""

    def test_path_declares_only_get_and_response_shape(self) -> None:
        path = app.openapi()["paths"][ENDPOINT]

        assert set(path) == {"get"}
        responses = path["get"]["responses"]
        assert "200" in responses
        assert responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "MarketBreadthResponse"
        )


__all__ = [
    "TestMarketBreadthInvalidDate",
    "TestMarketBreadthLatest",
    "TestMarketBreadthMissing",
    "TestMarketBreadthOpenAPI",
    "TestMarketBreadthQueryError",
]