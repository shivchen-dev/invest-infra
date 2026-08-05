from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from invest_domain.instruments.models import InstrumentId
from invest_pipeline.adapters.tushare import TushareSettings
from invest_pipeline.adapters.tushare.client import TushareClient
from invest_pipeline.adapters.tushare.mapper import map_fund_basic, map_fund_daily


def test_settings_redacts_token_and_uses_centralized_store() -> None:
    settings = TushareSettings(token="unit-secret")
    assert "unit-secret" not in repr(settings)
    assert settings.resolved_token() == "unit-secret"


def test_client_sends_tushare_v2_post_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": {"fields": [], "items": []}})

    client = TushareClient(
        TushareSettings(token="unit-secret"),
        transport=httpx.MockTransport(handler),
    )
    client.fetch_fund_basic()
    client.close()
    assert captured["api_name"] == "fund_basic"
    assert captured["token"] == "unit-secret"


def test_mappers_translate_etf_and_daily_bar_shapes() -> None:
    basic = type(
        "Response",
        (),
        {
            "raw_payload": {
                "code": 0,
                "data": {
                    "fields": ["ts_code", "name", "market"],
                    "items": [["510300.SH", "ETF", "E"]],
                },
            }
        },
    )()
    instruments, warnings = map_fund_basic(basic)
    assert not warnings and instruments[0].exchange == "SSE"

    daily = type(
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
                    "items": [["510300.SH", "2026-08-05", 1, 2, 0.5, 1.5, 1.4, 100, 200]],
                },
            }
        },
    )()
    bars, warnings = map_fund_daily(
        daily,
        source_batch_id=uuid4(),
        observed_at=datetime.now(UTC),
        instrument_id_resolver=lambda _s, _e: InstrumentId.generate(),
    )
    assert not warnings and bars[0].close == 1.5
