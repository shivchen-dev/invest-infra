"""Mock-based tests for the read-only ETF endpoints.

The fixtures in :mod:`tests.conftest` substitute the application
:class:`invest_api.application.etf.EtfQueryService` with a ``MagicMock``
through FastAPI's ``app.dependency_overrides`` so the handlers can be
exercised without spinning up PostgreSQL or instantiating the storage
repositories. Each test pins one endpoint behaviour:

- happy path with realistic payloads
- query-parameter validation (limit/offset, exchange, status filter)
- date range validation
- 404 mapping for unknown ``instrument_id``
- dependency wiring for both the ETF router and the legacy
  ``/v1/instruments`` router

Tests live under :mod:`tests.unit` style names but ``tests/`` because
``apps/api`` does not yet declare a ``unit`` package and these are the
contract tests for the routers. The application-level service tests in
:mod:`tests.test_etf_service` exercise the real service against mock
repositories and own the universe fetch, filter, pagination, latest
revision reduction and ``SQLAlchemyError`` translation assertions.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_api.application.etf import (
    DailyBarPageView,
    EtfQueryError,
    InstrumentPageView,
)
from invest_api.schemas import (
    InstrumentListResponse,
    InstrumentResponse,
    LegacyInstrumentListResponse,
    LegacyInstrumentResponse,
)
from invest_api.schemas.common import (
    InstrumentListResponse as CommonInstrumentListResponse,
)
from invest_api.schemas.common import (
    InstrumentResponse as CommonInstrumentResponse,
)
from invest_domain.instruments import InstrumentStatus

from tests.conftest import make_daily_bar, make_instrument

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_legacy_instruments_preserves_sparse_response(
    client: TestClient,
    etf_service: MagicMock,
) -> None:
    """The legacy ``/v1/instruments`` endpoint still returns the sparse shape."""

    view = InstrumentPageView(
        items=(make_instrument(),),
        total=1,
        limit=100,
        offset=0,
    )
    etf_service.list_active_instruments.return_value = view

    response = client.get("/v1/instruments")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "symbol": "510050",
                "name": "SSE 50 ETF",
                "exchange": "SSE",
                "instrument_type": "ETF",
                "is_active": True,
            }
        ],
        "limit": 100,
        "offset": 0,
    }
    etf_service.list_active_instruments.assert_called_once_with(
        limit=100, offset=0
    )


def test_instrument_schema_exports_share_one_definition() -> None:
    assert CommonInstrumentResponse is InstrumentResponse
    assert LegacyInstrumentResponse is InstrumentResponse
    assert CommonInstrumentListResponse is InstrumentListResponse
    assert LegacyInstrumentListResponse is InstrumentListResponse


# GET /api/v1/etf/instruments
# ---------------------------------------------------------------------------


def test_list_etf_instruments_returns_active_set(
    client: TestClient,
    etf_service: MagicMock,
) -> None:
    """Happy path: the endpoint returns the active instrument list."""

    sse = make_instrument(symbol="510050", exchange="SSE")
    szse = make_instrument(symbol="159915", exchange="SZSE")
    view = InstrumentPageView(items=(sse, szse), total=2, limit=100, offset=0)
    etf_service.list_active_instruments.return_value = view

    response = client.get("/api/v1/etf/instruments")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert [item["symbol"] for item in body["items"]] == ["510050", "159915"]
    assert set(body["items"][0]) == {
        "id",
        "symbol",
        "name",
        "exchange",
        "instrument_type",
        "currency",
        "status",
        "is_active",
        "list_date",
        "delist_date",
        "underlying_index",
        "category",
    }
    etf_service.list_active_instruments.assert_called_once_with(
        exchange=None, status_=None, limit=100, offset=0
    )


def test_list_etf_instruments_filters_by_exchange(
    client: TestClient,
    etf_service: MagicMock,
) -> None:
    """The endpoint forwards the ``exchange`` query parameter to the service."""

    sse = make_instrument(symbol="510050", exchange="SSE")
    view = InstrumentPageView(items=(sse,), total=1, limit=100, offset=0)
    etf_service.list_active_instruments.return_value = view

    response = client.get("/api/v1/etf/instruments?exchange=SSE")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["symbol"] for item in body["items"]] == ["510050"]
    assert [item["exchange"] for item in body["items"]] == ["SSE"]
    etf_service.list_active_instruments.assert_called_once_with(
        exchange="SSE", status_=None, limit=100, offset=0
    )


def test_list_etf_instruments_filters_by_status(
    client: TestClient,
    etf_service: MagicMock,
) -> None:
    """The ``status`` query parameter is forwarded to the service."""

    szse = make_instrument(
        symbol="159915",
        status=InstrumentStatus.DELISTED,
        exchange="SZSE",
    )
    view = InstrumentPageView(items=(szse,), total=1, limit=100, offset=0)
    etf_service.list_active_instruments.return_value = view

    response = client.get("/api/v1/etf/instruments?status=delisted")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["symbol"] for item in body["items"]] == ["159915"]
    etf_service.list_active_instruments.assert_called_once_with(
        exchange=None, status_="delisted", limit=100, offset=0
    )


def test_list_etf_instruments_pagination(
    client: TestClient,
    etf_service: MagicMock,
) -> None:
    """The endpoint forwards ``limit`` / ``offset`` to the service."""

    items = tuple(make_instrument(symbol=f"5100{i:02d}") for i in range(1, 3))
    view = InstrumentPageView(items=items, total=5, limit=2, offset=1)
    etf_service.list_active_instruments.return_value = view

    response = client.get("/api/v1/etf/instruments?limit=2&offset=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert [item["symbol"] for item in body["items"]] == ["510001", "510002"]
    etf_service.list_active_instruments.assert_called_once_with(
        exchange=None, status_=None, limit=2, offset=1
    )


def test_list_etf_instruments_rejects_invalid_pagination(
    client: TestClient,
    etf_service: MagicMock,
) -> None:
    """``limit=0`` and ``offset<0`` are rejected by Pydantic query validation."""

    response = client.get("/api/v1/etf/instruments?limit=0")
    assert response.status_code == 422

    response = client.get("/api/v1/etf/instruments?offset=-1")
    assert response.status_code == 422
    etf_service.list_active_instruments.assert_not_called()


def test_list_etf_instruments_surfaces_sanitized_500_on_query_error(
    client: TestClient,
    etf_service: MagicMock,
) -> None:
    """Repository ``SQLAlchemyError`` becomes a sanitized 500."""

    etf_service.list_active_instruments.side_effect = EtfQueryError(
        "connection string: postgres://user:secret@host/db"
    )

    response = client.get("/api/v1/etf/instruments")

    assert response.status_code == 500
    assert response.json() == {"detail": "ETF query failed"}
    assert "secret" not in response.text
    assert "EtfQueryError" not in response.text


# ---------------------------------------------------------------------------
# GET /api/v1/etf/daily-bars
# ---------------------------------------------------------------------------


def test_list_etf_daily_bars_returns_latest_per_day(
    client: TestClient,
    etf_service: MagicMock,
) -> None:
    """The endpoint surfaces the latest-per-day page returned by the service."""

    instrument_id = uuid4()
    etf_service.list_latest_daily_bars.return_value = DailyBarPageView(
        items=(
            make_daily_bar(
                instrument_id=instrument_id,
                trade_date=date(2026, 7, 30),
                revision=2,
            ),
            make_daily_bar(
                instrument_id=instrument_id,
                trade_date=date(2026, 7, 31),
                revision=1,
            ),
        ),
        total=2,
        limit=100,
        offset=0,
    )

    response = client.get(
        "/api/v1/etf/daily-bars"
        f"?instrument_id={instrument_id}"
        "&start_date=2026-07-30&end_date=2026-07-31"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["trade_date"] for item in body["items"]] == [
        "2026-07-30",
        "2026-07-31",
    ]
    assert [item["revision"] for item in body["items"]] == [2, 1]
    etf_service.list_latest_daily_bars.assert_called_once()
    call_kwargs = etf_service.list_latest_daily_bars.call_args.kwargs
    assert call_kwargs["instrument_id"] == instrument_id
    assert call_kwargs["start_date"] == date(2026, 7, 30)
    assert call_kwargs["end_date"] == date(2026, 7, 31)
    assert call_kwargs["limit"] == 100
    assert call_kwargs["offset"] == 0


def test_list_etf_daily_bars_rejects_inverted_range(
    client: TestClient,
    etf_service: MagicMock,
) -> None:
    """``end_date < start_date`` returns 400 with a descriptive detail."""

    instrument_id = uuid4()

    response = client.get(
        "/api/v1/etf/daily-bars"
        f"?instrument_id={instrument_id}"
        "&start_date=2026-07-31&end_date=2026-07-30"
    )

    assert response.status_code == 400
    assert "must be on or after" in response.json()["detail"]
    etf_service.list_latest_daily_bars.assert_not_called()


def test_list_etf_daily_bars_returns_404_for_unknown_instrument(
    client: TestClient,
    etf_service: MagicMock,
) -> None:
    """Service returning ``None`` -> 404 with the instrument id in the detail."""

    instrument_id = uuid4()
    etf_service.list_latest_daily_bars.return_value = None

    response = client.get(
        "/api/v1/etf/daily-bars"
        f"?instrument_id={instrument_id}"
        "&start_date=2026-07-30&end_date=2026-07-31"
    )

    assert response.status_code == 404
    assert str(instrument_id) in response.json()["detail"]


def test_list_etf_daily_bars_pagination(
    client: TestClient,
    etf_service: MagicMock,
) -> None:
    """The endpoint forwards ``limit`` / ``offset`` to the service."""

    instrument_id = uuid4()
    items = tuple(
        make_daily_bar(
            instrument_id=instrument_id,
            trade_date=date(2026, 7, 27 - i),
            revision=1,
        )
        for i in range(2)
    )
    etf_service.list_latest_daily_bars.return_value = DailyBarPageView(
        items=items, total=5, limit=2, offset=1
    )

    response = client.get(
        "/api/v1/etf/daily-bars"
        f"?instrument_id={instrument_id}"
        "&start_date=2026-07-26&end_date=2026-07-30&limit=2&offset=1"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert [item["trade_date"] for item in body["items"]] == [
        "2026-07-27",
        "2026-07-26",
    ]



    etf_service.list_latest_daily_bars.assert_called_once()
    call_kwargs = etf_service.list_latest_daily_bars.call_args.kwargs
    assert call_kwargs["limit"] == 2
    assert call_kwargs["offset"] == 1


def test_list_etf_daily_bars_surfaces_sanitized_500_on_query_error(
    client: TestClient,
    etf_service: MagicMock,
) -> None:
    """Repository ``SQLAlchemyError`` becomes a sanitized 500."""

    instrument_id: UUID = uuid4()
    etf_service.list_latest_daily_bars.side_effect = EtfQueryError(
        "connection string: postgres://user:secret@host/db"
    )

    response = client.get(
        "/api/v1/etf/daily-bars"
        f"?instrument_id={instrument_id}"
        "&start_date=2026-07-30&end_date=2026-07-31"
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "ETF query failed"}
    assert "secret" not in response.text
    assert "EtfQueryError" not in response.text


__all__ = [
    "test_instrument_schema_exports_share_one_definition",
    "test_legacy_instruments_preserves_sparse_response",
    "test_list_etf_instruments_filters_by_exchange",
    "test_list_etf_instruments_filters_by_status",
    "test_list_etf_instruments_pagination",
    "test_list_etf_instruments_rejects_invalid_pagination",
    "test_list_etf_instruments_returns_active_set",
    "test_list_etf_instruments_surfaces_sanitized_500_on_query_error",
    "test_list_etf_daily_bars_pagination",
    "test_list_etf_daily_bars_rejects_inverted_range",
    "test_list_etf_daily_bars_returns_404_for_unknown_instrument",
    "test_list_etf_daily_bars_returns_latest_per_day",
    "test_list_etf_daily_bars_surfaces_sanitized_500_on_query_error",
]
