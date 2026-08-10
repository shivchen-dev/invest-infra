from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from invest_domain.instruments.models import InstrumentType
from invest_pipeline.adapters.errors import RealProviderRequiresExplicitEnablementError
from invest_pipeline.adapters.tushare import StockTushareProvider, TushareSettings
from invest_pipeline.adapters.tushare.client import TushareClient


def test_stock_client_uses_tushare_date_format() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": {"fields": [], "items": []}})

    client = TushareClient(
        TushareSettings(token="unit-secret"), transport=httpx.MockTransport(handler)
    )
    client.fetch_stock_daily(
        ts_code="000001.SZ", start_date=date(2026, 7, 1), end_date=date(2026, 7, 10)
    )
    client.close()
    assert seen["api_name"] == "daily"
    assert seen["params"] == {
        "ts_code": "000001.SZ", "start_date": "20260701", "end_date": "20260710"
    }


def test_stock_provider_maps_master_and_batch_daily_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["api_name"] == "stock_basic":
            return httpx.Response(200, json={"code": 0, "data": {
                "fields": ["ts_code", "name", "list_date", "list_status"],
                "items": [["000001.SZ", "Ping An", "19910403", "L"]],
            }})
        return httpx.Response(200, json={"code": 0, "data": {
            "fields": [
                "ts_code", "trade_date", "open", "high", "low", "close",
                "pre_close", "vol", "amount",
            ],
            "items": [["000001.SZ", "20260710", 10, 11, 9, 10.5, 10.2, 100, 200]],
        }})

    settings = TushareSettings(enabled=True, token="unit-secret")
    client = TushareClient(settings, transport=httpx.MockTransport(handler))
    provider = StockTushareProvider(settings, client=client)
    _, _, master = provider.fetch_instruments(date(2026, 7, 10))
    _, _, bars = provider.fetch_daily_bars(["000001.SZ"], date(2026, 7, 1), date(2026, 7, 10))
    assert master and master.records[0].instrument_type is InstrumentType.STOCK
    assert bars and bars.records[0].trade_date == date(2026, 7, 10)
    client.close()


def test_stock_provider_disabled_returns_failed_attempt() -> None:
    provider = StockTushareProvider(TushareSettings(token="unit-secret"))
    with pytest.raises(RealProviderRequiresExplicitEnablementError):
        provider.fetch_instruments(date(2026, 7, 10))
    provider.close()
