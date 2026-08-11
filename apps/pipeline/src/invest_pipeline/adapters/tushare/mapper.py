"""Pure mappers from Tushare tabular responses to V2 domain rows."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from invest_domain.instruments.models import Instrument, InstrumentId, InstrumentType
from invest_domain.instruments.values import InstrumentStatus
from invest_domain.market_data.models import BarSource, DailyBar
from invest_domain.market_data.values import Adjust, Currency, TradingStatus

from invest_pipeline.adapters.errors import ProviderDataContractError
from invest_pipeline.adapters.tushare.client import TushareResponse

_PROVIDER_KEY = "tushare"


def _rows(response: TushareResponse) -> list[dict[str, Any]]:
    payload = response.raw_payload
    data = payload.get("data") if isinstance(payload, dict) else None
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("fields"), list)
        or not isinstance(data.get("items"), list)
    ):
        raise ProviderDataContractError(
            "MALFORMED_PAYLOAD",
            "Tushare data must contain fields/items",
            provider_key=_PROVIDER_KEY,
        )
    fields = data["fields"]
    return [
        dict(zip(fields, item, strict=False)) for item in data["items"] if isinstance(item, list)
    ]


def _decimal(value: Any, field: str, row: int) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise ProviderDataContractError(
            "MALFORMED_NUMBER", f"row {row} field {field} is invalid", provider_key=_PROVIDER_KEY
        ) from exc


def _trade_date(value: Any, row: int) -> date:
    try:
        text = str(value)
        return date.fromisoformat(text) if "-" in text else datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise ProviderDataContractError(
            "MALFORMED_DATE", f"row {row} trade_date is invalid", provider_key=_PROVIDER_KEY
        ) from exc


def _optional_date(row_data: dict[str, Any], field: str) -> date | None:
    value = row_data.get(field)
    if not value:
        return None
    text = str(value)
    return date.fromisoformat(text) if "-" in text else datetime.strptime(text, "%Y%m%d").date()


def _exchange(ts_code: str) -> tuple[str, str]:
    try:
        symbol, suffix = ts_code.rsplit(".", 1)
    except ValueError as exc:
        raise ProviderDataContractError(
            "MALFORMED_TS_CODE", f"invalid ts_code {ts_code!r}", provider_key=_PROVIDER_KEY
        ) from exc
    exchanges = {"SH": "SSE", "SZ": "SZSE", "BJ": "BJSE"}
    if suffix not in exchanges:
        raise ProviderDataContractError(
            "UNSUPPORTED_EXCHANGE",
            f"unsupported Tushare exchange {suffix!r}",
            provider_key=_PROVIDER_KEY,
        )
    return symbol, exchanges[suffix]


def map_fund_basic(response: TushareResponse) -> tuple[tuple[Instrument, ...], tuple[str, ...]]:
    records: list[Instrument] = []
    warnings: list[str] = []
    for index, row in enumerate(_rows(response)):
        if row.get("market") != "E":
            warnings.append(f"row {index} market={row.get('market')!r} skipped")
            continue
        ts_code, name = row.get("ts_code"), row.get("name")
        if not isinstance(ts_code, str) or not isinstance(name, str) or not name.strip():
            raise ProviderDataContractError(
                "MISSING_REQUIRED_FIELD",
                f"row {index} requires ts_code/name",
                provider_key=_PROVIDER_KEY,
            )
        symbol, exchange = _exchange(ts_code)

        list_date = _optional_date(row, "list_date")
        delist_date = _optional_date(row, "delist_date")
        status = InstrumentStatus.DELISTED if delist_date else InstrumentStatus.ACTIVE
        records.append(
            Instrument(
                symbol=symbol,
                name=name,
                exchange=exchange,
                instrument_type=InstrumentType.ETF,
                is_active=status is InstrumentStatus.ACTIVE,
                currency=Currency.CNY,
                list_date=list_date,
                delist_date=delist_date,
                status=status,
                provider_symbol_map={_PROVIDER_KEY: ts_code},
            )
        )
    return tuple(records), tuple(warnings)


def map_fund_daily(
    response: TushareResponse,
    *,
    source_batch_id: UUID,
    observed_at: datetime,
    instrument_id_resolver: Callable[[str, str], InstrumentId],
) -> tuple[tuple[DailyBar, ...], tuple[str, ...]]:
    records: list[DailyBar] = []
    warnings: list[str] = []
    source = BarSource(
        provider_key=_PROVIDER_KEY, source_batch_id=source_batch_id, observed_at=observed_at
    )
    for index, row in enumerate(_rows(response)):
        ts_code = row.get("ts_code")
        if not isinstance(ts_code, str):
            raise ProviderDataContractError(
                "MISSING_REQUIRED_FIELD",
                f"row {index} requires ts_code",
                provider_key=_PROVIDER_KEY,
            )
        symbol, exchange = _exchange(ts_code)
        values = {
            field: _decimal(row.get(field), field, index)
            for field in ("open", "high", "low", "close", "pre_close", "vol", "amount")
        }
        if any(values[field] is None for field in ("open", "high", "low", "close")):
            warnings.append(f"row {index} {ts_code} skipped: incomplete OHLC")
            continue
        records.append(
            DailyBar.build(
                instrument_id=instrument_id_resolver(symbol, exchange),
                trade_date=_trade_date(row.get("trade_date"), index),
                open=values["open"],
                high=values["high"],
                low=values["low"],
                close=values["close"],
                prev_close=values["pre_close"],
                volume=values["vol"],
                amount=values["amount"],
                adjustment=Adjust.NONE,
                trading_status=TradingStatus.NORMAL,
                source=source,
                revision=1,
            )
        )
    return tuple(records), tuple(warnings)


def map_stock_basic(response: TushareResponse) -> tuple[tuple[Instrument, ...], tuple[str, ...]]:
    records: list[Instrument] = []
    warnings: list[str] = []
    for index, row in enumerate(_rows(response)):
        ts_code, name = row.get("ts_code"), row.get("name")
        if not isinstance(ts_code, str) or not isinstance(name, str) or not name.strip():
            raise ProviderDataContractError(
                "MISSING_REQUIRED_FIELD", f"row {index} requires ts_code/name",
                provider_key=_PROVIDER_KEY,
            )
        symbol, exchange = _exchange(ts_code)
        list_date = _optional_date(row, "list_date")
        delist_date = _optional_date(row, "delist_date")
        status = (
            InstrumentStatus.DELISTED
            if delist_date or row.get("list_status") == "D"
            else InstrumentStatus.ACTIVE
        )
        records.append(Instrument(
            symbol=symbol, name=name, exchange=exchange, instrument_type=InstrumentType.STOCK,
            is_active=status is InstrumentStatus.ACTIVE, currency=Currency.CNY,
            list_date=list_date, delist_date=delist_date, status=status,
            provider_symbol_map={_PROVIDER_KEY: ts_code}, category=row.get("industry"),
        ))
    return tuple(records), tuple(warnings)


def map_stock_daily(
    response: TushareResponse, *, source_batch_id: UUID, observed_at: datetime,
    instrument_id_resolver: Callable[[str, str], InstrumentId],
) -> tuple[tuple[DailyBar, ...], tuple[str, ...]]:
    return map_fund_daily(response, source_batch_id=source_batch_id, observed_at=observed_at,
                          instrument_id_resolver=instrument_id_resolver)


__all__ = ["map_fund_basic", "map_fund_daily", "map_stock_basic", "map_stock_daily"]
