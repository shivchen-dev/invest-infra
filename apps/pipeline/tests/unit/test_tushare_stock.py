from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import uuid4

import httpx
import pytest
from invest_domain.instruments.models import InstrumentId, InstrumentType
from invest_pipeline.adapters.errors import (
    ProviderDataContractError,
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.adapters.tushare import StockTushareProvider, TushareSettings
from invest_pipeline.adapters.tushare.client import TushareClient
from invest_pipeline.adapters.tushare.mapper import map_stock_basic, map_stock_daily


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
        "ts_code": "000001.SZ",
        "start_date": "20260701",
        "end_date": "20260710",
    }


def test_stock_provider_maps_master_and_batch_daily_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["api_name"] == "stock_basic":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": ["ts_code", "name", "list_date", "list_status"],
                        "items": [["000001.SZ", "Ping An", "19910403", "L"]],
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "fields": [
                        "ts_code",
                        "trade_date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "pre_close",
                        "vol",
                        "amount",
                    ],
                    "items": [["000001.SZ", "20260710", 10, 11, 9, 10.5, 10.2, 100, 200]],
                },
            },
        )

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


def test_stock_client_by_trade_date_sends_only_trade_date_param() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": {"fields": [], "items": []}})

    client = TushareClient(
        TushareSettings(token="unit-secret"), transport=httpx.MockTransport(handler)
    )
    client.fetch_stock_daily_by_trade_date(trade_date=date(2026, 7, 10))
    client.close()
    assert seen["api_name"] == "daily"
    assert seen["params"] == {"trade_date": "20260710"}
    assert "ts_code" not in seen["params"]
    assert "start_date" not in seen["params"]
    assert "end_date" not in seen["params"]
    assert seen["fields"] == ("ts_code,trade_date,open,high,low,close,pre_close,vol,amount")


def test_stock_provider_by_trade_date_maps_rows_into_evidence_tuple() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["api_name"] == "daily"
        assert "ts_code" not in body["params"]
        assert body["params"] == {"trade_date": "20260710"}
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "fields": [
                        "ts_code",
                        "trade_date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "pre_close",
                        "vol",
                        "amount",
                    ],
                    "items": [
                        ["000001.SZ", "20260710", 10, 11, 9, 10.5, 10.2, 100, 200],
                        ["600000.SH", "20260710", 8, 9, 7.5, 8.5, 8.4, 150, 250],
                    ],
                },
            },
        )

    settings = TushareSettings(enabled=True, token="unit-secret")
    client = TushareClient(settings, transport=httpx.MockTransport(handler))
    provider = StockTushareProvider(settings, client=client)
    request, attempt, batch = provider.fetch_daily_bars_by_trade_date(date(2026, 7, 10))
    client.close()

    assert request.provider_key == "tushare"
    assert request.dataset_key == "stock_daily_bars_by_date"
    assert request.request_key == "daily-bars-by-date-2026-07-10"
    assert request.params == {"trade_date": "2026-07-10"}
    assert attempt.status.value == "succeeded"
    assert batch is not None
    trade_dates = {bar.trade_date for bar in batch.records}
    assert trade_dates == {date(2026, 7, 10)}
    symbols_by_id = {
        provider.symbol_and_exchange_for_instrument_id(bar.instrument_id) for bar in batch.records
    }
    assert symbols_by_id == {("000001", "SZSE"), ("600000", "SSE")}
    closes = sorted(float(bar.close) for bar in batch.records)
    assert closes == [8.5, 10.5]
    assert batch.raw_payload_hash
    assert batch.warnings == ()


def test_stock_client_by_trade_date_rejects_non_date() -> None:
    client = TushareClient(
        TushareSettings(token="unit-secret"),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, json={"code": 0, "data": {"fields": [], "items": []}}
            )
        ),
    )
    with pytest.raises(TypeError):
        client.fetch_stock_daily_by_trade_date(trade_date="20260710")  # type: ignore[arg-type]
    client.close()


def test_stock_basic_maps_bj_suffix_to_bjse_exchange() -> None:
    response = type(
        "Response",
        (),
        {
            "raw_payload": {
                "code": 0,
                "data": {
                    "fields": ["ts_code", "name", "list_date", "list_status"],
                    "items": [["830799.BJ", "某北交所股票", "20210812", "L"]],
                },
            }
        },
    )()
    instruments, warnings = map_stock_basic(response)
    assert warnings == ()
    assert len(instruments) == 1
    record = instruments[0]
    assert record.symbol == "830799"
    assert record.exchange == "BJSE"
    assert record.instrument_type is InstrumentType.STOCK
    assert record.provider_symbol_map["tushare"] == "830799.BJ"


def test_stock_basic_preserves_sh_sz_mappings_alongside_bj() -> None:
    response = type(
        "Response",
        (),
        {
            "raw_payload": {
                "code": 0,
                "data": {
                    "fields": ["ts_code", "name", "list_date", "list_status"],
                    "items": [
                        ["600000.SH", "上证A", "19901219", "L"],
                        ["000001.SZ", "平安银行", "19910403", "L"],
                        ["830799.BJ", "某北交所股票", "20210812", "L"],
                    ],
                },
            }
        },
    )()
    instruments, warnings = map_stock_basic(response)
    assert warnings == ()
    exchanges = sorted(record.exchange for record in instruments)
    assert exchanges == ["BJSE", "SSE", "SZSE"]


def test_stock_basic_rejects_unknown_exchange_suffix() -> None:
    response = type(
        "Response",
        (),
        {
            "raw_payload": {
                "code": 0,
                "data": {
                    "fields": ["ts_code", "name", "list_date", "list_status"],
                    "items": [["0700.HK", "Tencent", "20040616", "L"]],
                },
            }
        },
    )()
    with pytest.raises(ProviderDataContractError) as info:
        map_stock_basic(response)
    assert info.value.code == "UNSUPPORTED_EXCHANGE"
    assert "HK" in str(info.value)


def test_stock_daily_maps_bj_suffix_to_bjse_exchange() -> None:
    response = type(
        "Response",
        (),
        {
            "raw_payload": {
                "code": 0,
                "data": {
                    "fields": [
                        "ts_code",
                        "trade_date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "pre_close",
                        "vol",
                        "amount",
                    ],
                    "items": [["830799.BJ", "2026-07-10", 12, 13, 11, 12.5, 12.2, 300, 400]],
                },
            }
        },
    )()
    seen: dict[tuple[str, str], InstrumentId] = {}

    def resolver(symbol: str, exchange: str) -> InstrumentId:
        key = (symbol, exchange)
        if key not in seen:
            seen[key] = InstrumentId.generate()
        return seen[key]

    bars, warnings = map_stock_daily(
        response,
        source_batch_id=uuid4(),
        observed_at=datetime.now(UTC),
        instrument_id_resolver=resolver,
    )
    assert warnings == ()
    assert len(bars) == 1
    bar = bars[0]
    assert bar.trade_date == date(2026, 7, 10)
    assert bar.close == pytest.approx(12.5)
    assert ("830799", "BJSE") in seen
    assert seen[("830799", "BJSE")] == bar.instrument_id


def test_stock_daily_rejects_unknown_exchange_suffix() -> None:
    response = type(
        "Response",
        (),
        {
            "raw_payload": {
                "code": 0,
                "data": {
                    "fields": [
                        "ts_code",
                        "trade_date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "pre_close",
                        "vol",
                        "amount",
                    ],
                    "items": [["0700.HK", "2026-07-10", 12, 13, 11, 12.5, 12.2, 300, 400]],
                },
            }
        },
    )()
    with pytest.raises(ProviderDataContractError) as info:
        map_stock_daily(
            response,
            source_batch_id=uuid4(),
            observed_at=datetime.now(UTC),
            instrument_id_resolver=lambda _s, _e: InstrumentId.generate(),
        )
    assert info.value.code == "UNSUPPORTED_EXCHANGE"
    assert "HK" in str(info.value)
