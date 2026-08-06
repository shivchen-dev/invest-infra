from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from invest_api.mcp_server import (
    ReadOnlyGateway,
    _json_safe,
    create_tool_server,
    get_candidate_pool_diff,
    get_etf_daily_bars,
    mcp,
)


class _Status(Enum):
    READY = "ready"


@dataclass(frozen=True)
class _Payload:
    identifier: UUID
    when: date
    timestamp: datetime
    amount: Decimal
    status: _Status


def _tool(server, name: str):
    return server._tool_manager.get_tool(name).fn


def test_registers_exactly_four_tools() -> None:
    assert [tool.name for tool in mcp._tool_manager.list_tools()] == [
        "get_data_freshness",
        "get_latest_candidate_pool",
        "get_candidate_pool_diff",
        "get_etf_daily_bars",
    ]


def test_serializes_nested_values_to_json_safe_values() -> None:
    identifier = uuid4()
    value = _Payload(
        identifier=identifier,
        when=date(2026, 8, 6),
        timestamp=datetime(2026, 8, 6, 12, 30),
        amount=Decimal("12.3400"),
        status=_Status.READY,
    )

    result = _json_safe({identifier: [value, Decimal("1.2")]})

    assert result == {
        str(identifier): [
            {
                "identifier": str(identifier),
                "when": "2026-08-06",
                "timestamp": "2026-08-06T12:30:00",
                "amount": "12.3400",
                "status": "ready",
            },
            "1.2",
        ]
    }


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: get_candidate_pool_diff("not-a-uuid"), "UUID"),
        (lambda: get_etf_daily_bars(str(uuid4()), "bad", "2026-08-06"), "ISO date"),
        (lambda: get_etf_daily_bars(str(uuid4()), "2026-08-07", "2026-08-06"), "on or after"),
        (lambda: get_etf_daily_bars(str(uuid4()), "2026-08-06", "2026-08-06", limit=0), "between"),
        (
            lambda: get_etf_daily_bars(str(uuid4()), "2026-08-06", "2026-08-06", limit=1001),
            "between",
        ),
        (
            lambda: get_etf_daily_bars(str(uuid4()), "2026-08-06", "2026-08-06", offset=-1),
            "non-negative",
        ),
    ],
)
def test_validates_tool_arguments(call, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        call()


def test_fake_services_receive_parsed_arguments_and_errors_are_safe() -> None:
    freshness = MagicMock()
    candidate_pool = MagicMock()
    etf = MagicMock()
    instrument_id = uuid4()
    candidate_pool.get_run_diff.side_effect = RuntimeError("postgres://user:secret@host/db")
    etf.list_latest_daily_bars.return_value = {"value": Decimal("2.50")}
    gateway = ReadOnlyGateway(
        data_freshness=freshness,
        candidate_pool=candidate_pool,
        etf=etf,
    )
    server = create_tool_server(gateway)

    assert _tool(server, "get_candidate_pool_diff")(str(instrument_id)) == {"error": "Query failed"}
    assert _tool(server, "get_etf_daily_bars")(
        str(instrument_id), "2026-08-01", "2026-08-06", 25, 3
    ) == {"value": "2.50"}
    etf.list_latest_daily_bars.assert_called_once_with(
        instrument_id=instrument_id,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 6),
        limit=25,
        offset=3,
    )
