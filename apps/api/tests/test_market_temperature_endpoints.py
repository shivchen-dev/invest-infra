from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

from fastapi.testclient import TestClient
from invest_api.application.market_temperature import MarketTemperatureQueryError
from invest_api.dependencies import get_market_temperature_query_service
from invest_api.main import app
from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)


def _snapshot() -> MarketObservationSnapshot:
    return MarketObservationSnapshot(
        input_snapshot_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        as_of_date=date(2026, 8, 7),
        observations=(
            MarketObservation(
                observation_key="market_temperature_score",
                value=Decimal("0.75"),
                unit="ratio",
                observed_date=date(2026, 8, 7),
                source_kind="computed",
                source_ref="calc:market_temperature",
            ),
        ),
    )


def _client(service: MagicMock) -> TestClient:
    app.dependency_overrides[get_market_temperature_query_service] = lambda: service
    return TestClient(app)


def test_latest_market_temperature_serializes_public_snapshot() -> None:
    service = MagicMock()
    service.get_latest.return_value = _snapshot()
    client = _client(service)
    try:
        response = client.get("/api/v1/market-temperature/latest")
        assert response.status_code == 200
        body = response.json()
        assert body["snapshot_id"] == _snapshot().snapshot_id
        assert body["content_hash"] == _snapshot().content_hash
        assert body["observations"][0]["observation_key"] == "market_temperature_score"
        assert body["observations"][0]["value"] == "0.75"
        assert "workspace_path" not in response.text
        assert "api_key" not in response.text
    finally:
        app.dependency_overrides.pop(get_market_temperature_query_service, None)


def test_latest_market_temperature_returns_404_when_empty() -> None:
    service = MagicMock()
    service.get_latest.return_value = None
    client = _client(service)
    try:
        response = client.get("/api/v1/market-temperature/latest")
        assert response.status_code == 404
        assert response.json() == {"detail": "Market temperature snapshot not found"}
    finally:
        app.dependency_overrides.pop(get_market_temperature_query_service, None)


def test_latest_market_temperature_sanitizes_query_error() -> None:
    service = MagicMock()
    service.get_latest.side_effect = MarketTemperatureQueryError("postgres password")
    client = _client(service)
    try:
        response = client.get("/api/v1/market-temperature/latest")
        assert response.status_code == 500
        assert response.json() == {"detail": "Market temperature query failed"}
        assert "postgres" not in response.text
    finally:
        app.dependency_overrides.pop(get_market_temperature_query_service, None)


def test_market_temperature_openapi_is_read_only_and_declared() -> None:
    path = app.openapi()["paths"]["/api/v1/market-temperature/latest"]
    assert set(path) == {"get"}
    assert path["get"]["responses"]["200"]["content"]["application/json"]
