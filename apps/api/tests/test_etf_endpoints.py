"""Mock-based tests for the read-only ETF endpoints.

The fixtures in :mod:`tests.conftest` patch each router's storage
repository classes with ``MagicMock`` instances so the handlers can
be exercised without spinning up PostgreSQL. Each test pins one
endpoint behaviour:

- happy path with realistic payloads
- query-parameter validation (limit/offset, exchange, status filter)
- date range validation
- dependency wiring (``get_db_session`` -> the patched repos)

Tests live under :mod:`tests.unit` style names but ``tests/`` because
``apps/api`` does not yet declare a ``unit`` package and these are the
contract tests for the routers.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

from invest_domain.instruments import InstrumentStatus

from tests.conftest import make_daily_bar, make_instrument

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
# GET /api/v1/etf/instruments
# ---------------------------------------------------------------------------


def test_list_etf_instruments_returns_active_set(
    client: TestClient,
    instrument_repo: MagicMock,
) -> None:
    """Happy path: the endpoint returns the active instrument list."""

    instrument_repo.list_active.return_value = [
        make_instrument(symbol="510050", exchange="SSE"),
        make_instrument(symbol="159915", exchange="SZSE"),
    ]

    response = client.get("/api/v1/etf/instruments")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert [item["symbol"] for item in body["items"]] == ["510050", "159915"]
    instrument_repo.list_active.assert_called_once_with(limit=1000, offset=0)


def test_list_etf_instruments_filters_by_exchange(
    client: TestClient,
    instrument_repo: MagicMock,
) -> None:
    """The endpoint filters on the ``exchange`` query parameter."""

    instrument_repo.list_active.return_value = [
        make_instrument(symbol="510050", exchange="SSE"),
        make_instrument(symbol="159915", exchange="SZSE"),
    ]

    response = client.get("/api/v1/etf/instruments?exchange=SSE")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["symbol"] for item in body["items"]] == ["510050"]
    assert [item["exchange"] for item in body["items"]] == ["SSE"]


def test_list_etf_instruments_filters_by_status(
    client: TestClient,
    instrument_repo: MagicMock,
) -> None:
    """The ``status`` query parameter narrows the response set."""

    instrument_repo.list_active.return_value = [
        make_instrument(symbol="510050"),
        make_instrument(symbol="159915", status=InstrumentStatus.DELISTED),
    ]

    response = client.get("/api/v1/etf/instruments?status=delisted")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["symbol"] for item in body["items"]] == ["159915"]


def test_list_etf_instruments_pagination(
    client: TestClient,
    instrument_repo: MagicMock,
) -> None:
    """The endpoint honours ``limit`` / ``offset``."""

    instrument_repo.list_active.return_value = [
        make_instrument(symbol=f"5100{i:02d}") for i in range(5)
    ]

    response = client.get("/api/v1/etf/instruments?limit=2&offset=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert [item["symbol"] for item in body["items"]] == ["510001", "510002"]


def test_list_etf_instruments_rejects_invalid_pagination(
    client: TestClient,
    instrument_repo: MagicMock,
) -> None:
    """``limit=0`` and ``offset<0`` are rejected by Pydantic query validation."""

    instrument_repo.list_active.return_value = []

    response = client.get("/api/v1/etf/instruments?limit=0")
    assert response.status_code == 422

    response = client.get("/api/v1/etf/instruments?offset=-1")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/etf/daily-bars
# ---------------------------------------------------------------------------


def test_list_etf_daily_bars_returns_latest_per_day(
    client: TestClient,
    instrument_repo: MagicMock,
    daily_bar_repo: MagicMock,
) -> None:
    """The endpoint collapses multiple revisions to the latest per trade date."""

    instrument_id = uuid4()
    instrument_repo.get_by_id.return_value = make_instrument(
        instrument_id=instrument_id, symbol="510050"
    )

    bar_v1 = make_daily_bar(
        instrument_id=instrument_id,
        trade_date=date(2026, 7, 30),
        revision=1,
    )
    bar_v2 = make_daily_bar(
        instrument_id=instrument_id,
        trade_date=date(2026, 7, 30),
        revision=2,
    )
    bar_v1_day2 = make_daily_bar(
        instrument_id=instrument_id,
        trade_date=date(2026, 7, 31),
        revision=1,
    )
    daily_bar_repo.list_by_instrument_and_range.return_value = [
        bar_v1,
        bar_v2,
        bar_v1_day2,
    ]

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
    daily_bar_repo.list_by_instrument_and_range.assert_called_once()


def test_list_etf_daily_bars_rejects_inverted_range(
    client: TestClient,
    instrument_repo: MagicMock,
    daily_bar_repo: MagicMock,
) -> None:
    """``end_date < start_date`` returns 400 with a descriptive detail."""

    instrument_id = uuid4()
    instrument_repo.get_by_id.return_value = make_instrument(
        instrument_id=instrument_id, symbol="510050"
    )

    response = client.get(
        "/api/v1/etf/daily-bars"
        f"?instrument_id={instrument_id}"
        "&start_date=2026-07-31&end_date=2026-07-30"
    )

    assert response.status_code == 400
    assert "must be on or after" in response.json()["detail"]


def test_list_etf_daily_bars_returns_404_for_unknown_instrument(
    client: TestClient,
    instrument_repo: MagicMock,
    daily_bar_repo: MagicMock,
) -> None:
    """Unknown ``instrument_id`` -> 404 with the instrument id in the detail."""

    instrument_id = uuid4()
    instrument_repo.get_by_id.return_value = None
    daily_bar_repo.list_by_instrument_and_range.return_value = []

    response = client.get(
        "/api/v1/etf/daily-bars"
        f"?instrument_id={instrument_id}"
        "&start_date=2026-07-30&end_date=2026-07-31"
    )

    assert response.status_code == 404
    assert str(instrument_id) in response.json()["detail"]


def test_list_etf_daily_bars_pagination(
    client: TestClient,
    instrument_repo: MagicMock,
    daily_bar_repo: MagicMock,
) -> None:
    """The endpoint honours ``limit`` / ``offset`` on the latest-per-day set."""

    instrument_id = uuid4()
    instrument_repo.get_by_id.return_value = make_instrument(
        instrument_id=instrument_id, symbol="510050"
    )

    daily_bar_repo.list_by_instrument_and_range.return_value = [
        make_daily_bar(
            instrument_id=instrument_id,
            trade_date=date(2026, 7, 30 - i),
            revision=1,
        )
        for i in range(5)
    ]

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
        "2026-07-28",
    ]


__all__ = [
    "test_list_etf_instruments_filters_by_exchange",
    "test_list_etf_instruments_filters_by_status",
    "test_list_etf_instruments_pagination",
    "test_list_etf_instruments_rejects_invalid_pagination",
    "test_list_etf_instruments_returns_active_set",
    "test_list_etf_daily_bars_pagination",
    "test_list_etf_daily_bars_rejects_inverted_range",
    "test_list_etf_daily_bars_returns_404_for_unknown_instrument",
    "test_list_etf_daily_bars_returns_latest_per_day",
]