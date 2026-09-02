"""BaoStock field mappers (Slice-1 of PR-08).

Pure, pandas-free mapper from the client's normalised dict-rows to
domain :class:`DailyBar` records. All field-level validation lives
here (date, finite numeric, OHLC invariants, exchange).
"""

from __future__ import annotations

import uuid as _uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from invest_domain.instruments.models import InstrumentId
from invest_domain.market_data.models import BarSource, DailyBar
from invest_domain.market_data.values import Adjust, Currency, TradingStatus

from invest_pipeline.adapters.baostock.client import BaostockResponse
from invest_pipeline.adapters.errors import ProviderDataContractError

_PROVIDER_KEY = "baostock"

_EXCHANGE_FROM_PREFIX = {"sh": "SSE", "sz": "SZSE"}

_NUMERIC_FIELDS = ("open", "high", "low", "close", "volume", "amount")


@dataclass(frozen=True, slots=True)
class BaostockDailyBarsMappingResult:
    bars: tuple[DailyBar, ...]
    warnings: tuple[str, ...]
    source_batch_id: UUID


def map_query_history_k_data_plus(
    response: BaostockResponse,
    *,
    symbols: Sequence[str],
    source: BarSource,
) -> BaostockDailyBarsMappingResult:
    warnings: list[str] = []
    bars: list[DailyBar] = []
    requested = tuple(sorted(set(symbols)))
    for index, entry in enumerate(response.raw_payload):
        if not isinstance(entry, dict):
            raise _contract("MALFORMED_HISTORY_ROW", f"row {index} not a dict", index=index)
        raw_code = entry.get("code")
        if not raw_code or not isinstance(raw_code, str):
            raise _contract(
                "MISSING_REQUIRED_FIELD", f"row {index} missing 'code'", index=index,
            )
        if requested and raw_code not in requested:
            warnings.append(
                f"row {index} code={raw_code!r} not in requested {list(requested)!r}"
            )
            continue
        bars.append(_row_to_bar(entry, index=index, source=source))
    return BaostockDailyBarsMappingResult(
        bars=tuple(bars), warnings=tuple(warnings), source_batch_id=source.source_batch_id,
    )


def _resolve_exchange(symbol: str) -> str:
    """SSE / SZSE allow-list. Anything outside raises UNSUPPORTED_EXCHANGE."""
    prefix, _, _ = symbol.partition(".")
    exchange = _EXCHANGE_FROM_PREFIX.get(prefix.lower())
    if exchange is None:
        raise _contract(
            "UNSUPPORTED_EXCHANGE",
            f"symbol={symbol!r} not SSE/SZSE (expected 'sh.'/'sz.')",
            index=-1,
        )
    return exchange


def _row_to_bar(entry: dict[str, Any], *, index: int, source: BarSource) -> DailyBar:
    raw_code = entry["code"]
    raw_date = entry.get("date")
    if not raw_date or not isinstance(raw_date, str):
        raise _contract("MISSING_REQUIRED_FIELD", f"row {index} missing 'date'", index=index)
    try:
        trade_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise _contract(
            "INVALID_DATE", f"row {index} invalid date {raw_date!r}", index=index,
        ) from exc

    decimals = {
        f: _parse_finite_decimal(entry, field=f, index=index, raw_code=raw_code)
        for f in _NUMERIC_FIELDS
    }
    open_ = decimals["open"]
    high = decimals["high"]
    low = decimals["low"]
    close = decimals["close"]
    volume = decimals["volume"]
    amount = decimals["amount"]

    # OHLC + non-negative volume/amount — data-quality safety.
    if not (high >= max(open_, close, low) and low <= min(open_, close, high)):
        raise _contract(
            "OHLC_INVARIANT",
            f"row {index} OHLC o={open_!s} h={high!s} l={low!s} c={close!s}",
            index=index,
        )
    if volume < 0 or amount < 0:
        raise _contract(
            "NEGATIVE_AMOUNT",
            f"row {index} vol={volume!s} amt={amount!s}",
            index=index,
        )

    exchange = _resolve_exchange(raw_code)
    return DailyBar.build(
        instrument_id=_instrument_id_for(raw_code, exchange),
        trade_date=trade_date,
        open=open_, high=high, low=low, close=close,
        prev_close=None, volume=volume, amount=amount,
        adjustment=Adjust.NONE,
        trading_status=TradingStatus.NORMAL,
        source=source,
        revision=1,
        currency=Currency.CNY,
    )


def _parse_finite_decimal(
    entry: dict[str, Any], *, field: str, index: int, raw_code: str,
) -> Decimal:
    """Parse ``entry[field]`` as a finite Decimal.

    ``Decimal("NaN")`` / ``Decimal("Infinity")`` parse through
    ``Decimal(str(raw))``; ``is_finite()`` is the only guard.
    """
    raw = entry.get(field)
    if raw is None or raw == "":
        raise _contract(
            "MISSING_REQUIRED_FIELD",
            f"row {index} missing numeric {field!r}", index=index,
        )
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise _contract(
            "INVALID_NUMERIC", f"row {index} {field!r}={raw!r}", index=index,
        ) from exc
    if not value.is_finite():
        raise _contract(
            "INVALID_NUMERIC", f"row {index} non-finite {field!r}={raw!r}", index=index,
        )
    return value


def _contract(code: str, msg: str, *, index: int) -> ProviderDataContractError:
    suffix = f" row={index}" if index >= 0 else ""
    return ProviderDataContractError(code, msg + suffix, provider_key=_PROVIDER_KEY)


def _instrument_id_for(symbol: str, exchange: str) -> InstrumentId:
    """Deterministic InstrumentId. Re-runs of the same (symbol, exchange) → same UUID."""
    digest_seed = f"{_PROVIDER_KEY}|{symbol}|{exchange}".encode()
    return InstrumentId(_uuid.uuid5(_uuid.NAMESPACE_DNS, digest_seed.hex()))


__all__ = ["BaostockDailyBarsMappingResult", "map_query_history_k_data_plus"]
