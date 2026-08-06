from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import FastMCP

from invest_api.application.candidate_pool import CandidatePoolQueryService
from invest_api.application.data_freshness import DataFreshnessQueryService
from invest_api.application.etf import EtfQueryService
from invest_api.dependencies import (
    get_candidate_pool_query_service,
    get_data_freshness_query_service,
    get_db_session,
    get_etf_query_service,
)

_SAFE_ERROR = "Query failed"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_safe(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(_json_safe(key)): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            key: _json_safe(item) for key, item in vars(value).items() if not key.startswith("_")
        }
    return str(value)


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def _parse_uuid(value: str, name: str) -> UUID:
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a UUID") from exc


def _validate_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if offset < 0:
        raise ValueError("offset must be non-negative")


class ReadOnlyGateway:
    def __init__(
        self,
        *,
        data_freshness: DataFreshnessQueryService,
        candidate_pool: CandidatePoolQueryService,
        etf: EtfQueryService,
    ) -> None:
        self.data_freshness = data_freshness
        self.candidate_pool = candidate_pool
        self.etf = etf

    def get_data_freshness(self, expected_trade_date: date | None) -> Any:
        return self.data_freshness.get_freshness(expected_trade_date)

    def get_latest_candidate_pool(self) -> Any:
        return self.candidate_pool.get_latest()

    def get_candidate_pool_diff(self, run_id: UUID | None) -> Any:
        if run_id is None:
            return self.candidate_pool.get_latest_diff()
        return self.candidate_pool.get_run_diff(run_id)

    def get_etf_daily_bars(
        self,
        instrument_id: UUID,
        start_date: date,
        end_date: date,
        limit: int,
        offset: int,
    ) -> Any:
        return self.etf.list_latest_daily_bars(
            instrument_id=instrument_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )


@contextmanager
def _default_gateway() -> Iterator[ReadOnlyGateway]:
    session_iterator = get_db_session()
    session = next(session_iterator)
    try:
        yield ReadOnlyGateway(
            data_freshness=get_data_freshness_query_service(session),
            candidate_pool=get_candidate_pool_query_service(session),
            etf=get_etf_query_service(session),
        )
    finally:
        with suppress(StopIteration):
            next(session_iterator)


def _invoke(
    operation: Callable[[ReadOnlyGateway], Any], gateway: ReadOnlyGateway | None
) -> dict[str, Any] | list[Any] | Any:
    try:
        if gateway is not None:
            return _json_safe(operation(gateway))
        with _default_gateway() as database_gateway:
            return _json_safe(operation(database_gateway))
    except ValueError:
        raise
    except Exception:
        return {"error": _SAFE_ERROR}


mcp = FastMCP("invest-api")


@mcp.tool()
def get_data_freshness(expected_trade_date: str | None = None) -> Any:
    parsed = (
        None
        if expected_trade_date is None
        else _parse_date(expected_trade_date, "expected_trade_date")
    )
    return _invoke(lambda gateway: gateway.get_data_freshness(parsed), None)


@mcp.tool()
def get_latest_candidate_pool() -> Any:
    return _invoke(lambda gateway: gateway.get_latest_candidate_pool(), None)


@mcp.tool()
def get_candidate_pool_diff(run_id: str | None = None) -> Any:
    parsed = None if run_id is None else _parse_uuid(run_id, "run_id")
    return _invoke(lambda gateway: gateway.get_candidate_pool_diff(parsed), None)


@mcp.tool()
def get_etf_daily_bars(
    instrument_id: str,
    start_date: str,
    end_date: str,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    parsed_instrument_id = _parse_uuid(instrument_id, "instrument_id")
    parsed_start_date = _parse_date(start_date, "start_date")
    parsed_end_date = _parse_date(end_date, "end_date")
    _validate_page(limit, offset)
    if parsed_end_date < parsed_start_date:
        raise ValueError("end_date must be on or after start_date")
    return _invoke(
        lambda gateway: gateway.get_etf_daily_bars(
            parsed_instrument_id, parsed_start_date, parsed_end_date, limit, offset
        ),
        None,
    )


def create_tool_server(gateway: ReadOnlyGateway) -> FastMCP:
    server = FastMCP("invest-api")

    @server.tool(name="get_data_freshness")
    def injected_get_data_freshness(expected_trade_date: str | None = None) -> Any:
        parsed = (
            None
            if expected_trade_date is None
            else _parse_date(expected_trade_date, "expected_trade_date")
        )
        return _invoke(lambda service_gateway: service_gateway.get_data_freshness(parsed), gateway)

    @server.tool(name="get_latest_candidate_pool")
    def injected_get_latest_candidate_pool() -> Any:
        return _invoke(
            lambda service_gateway: service_gateway.get_latest_candidate_pool(),
            gateway,
        )

    @server.tool(name="get_candidate_pool_diff")
    def injected_get_candidate_pool_diff(run_id: str | None = None) -> Any:
        parsed = None if run_id is None else _parse_uuid(run_id, "run_id")
        return _invoke(
            lambda service_gateway: service_gateway.get_candidate_pool_diff(parsed),
            gateway,
        )

    @server.tool(name="get_etf_daily_bars")
    def injected_get_etf_daily_bars(
        instrument_id: str,
        start_date: str,
        end_date: str,
        limit: int = 100,
        offset: int = 0,
    ) -> Any:
        parsed_instrument_id = _parse_uuid(instrument_id, "instrument_id")
        parsed_start_date = _parse_date(start_date, "start_date")
        parsed_end_date = _parse_date(end_date, "end_date")
        _validate_page(limit, offset)
        if parsed_end_date < parsed_start_date:
            raise ValueError("end_date must be on or after start_date")
        return _invoke(
            lambda service_gateway: service_gateway.get_etf_daily_bars(
                parsed_instrument_id, parsed_start_date, parsed_end_date, limit, offset
            ),
            gateway,
        )

    return server


if __name__ == "__main__":
    mcp.run(transport="stdio")
