"""TDX .day offline reader spike.

The reader is intentionally narrow:

* parses one 32-byte little-endian record per bar
* resolves a bar file from a root directory using the canonical
  ``vipdoc/{market}/lday/{market}{symbol}.day`` layout
* validates each record strictly and surfaces specific exceptions
* performs optional inclusive date filtering on ``YYYYMMDD`` integers
* returns parsed bars as :class:`~invest_pipeline.adapters.tdx_offline.records.TdxDailyBar`
  instances whose monetary fields are :class:`decimal.Decimal` values

The reader does not perform ETF-protocol parsing, adjustment, instrument
mapping or persistence; those responsibilities are intentionally left out of
this spike.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable
from datetime import date as _date
from decimal import Decimal
from pathlib import Path

from .errors import (
    TdxFileMissingError,
    TdxInvalidDateError,
    TdxInvalidMarketError,
    TdxInvalidPathError,
    TdxInvalidSizeError,
    TdxInvalidSymbolError,
    TdxInvalidValueError,
)
from .records import TdxDailyBar

PROVIDER_KEY = "tdx_offline"
DATASET_KEY = "stock_daily_bars"

RECORD_SIZE = 32
_RECORD_STRUCT = struct.Struct("<5IfI4x")
_MARKETS = frozenset({"sh", "sz"})


def _coerce_date_filter(value: int | _date | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, _date):
        return value.year * 10000 + value.month * 100 + value.day
    if isinstance(value, int):
        return value
    raise TdxInvalidDateError(
        f"Date filter must be an int YYYYMMDD or datetime.date, got {type(value).__name__}"
    )


def _validate_yyyymmdd(raw: int) -> int:
    if raw < 19700101 or raw > 29991231:
        raise TdxInvalidDateError(f"Date out of plausible range: {raw}")
    year = raw // 10000
    month = (raw // 100) % 100
    day = raw % 100
    if not 1 <= month <= 12:
        raise TdxInvalidDateError(f"Invalid month in date field: {raw}")
    if not 1 <= day <= 31:
        raise TdxInvalidDateError(f"Invalid day in date field: {raw}")
    try:
        _date(year, month, day)
    except ValueError as exc:
        raise TdxInvalidDateError(f"Invalid calendar date {raw}: {exc}") from exc
    return raw


def _price_from_uint(raw: int) -> Decimal:
    return Decimal(raw) / Decimal(100)


def _amount_from_float32(raw: float) -> Decimal:
    if math.isnan(raw):
        raise TdxInvalidValueError(f"Amount is NaN: {raw}")
    if math.isinf(raw):
        raise TdxInvalidValueError(f"Amount is non-finite: {raw}")
    if raw < 0:
        raise TdxInvalidValueError(f"Negative amount: {raw}")
    return Decimal(str(raw))


def _parse_record(buffer: bytes, offset: int) -> TdxDailyBar:
    try:
        date_raw, open_raw, high_raw, low_raw, close_raw, amount_raw, volume_raw = (
            _RECORD_STRUCT.unpack_from(buffer, offset)
        )
    except struct.error as exc:
        raise TdxInvalidSizeError(
            f"Record at offset {offset} cannot be unpacked: {exc}"
        ) from exc

    date_value = _validate_yyyymmdd(date_raw)
    open_d = _price_from_uint(open_raw)
    high_d = _price_from_uint(high_raw)
    low_d = _price_from_uint(low_raw)
    close_d = _price_from_uint(close_raw)
    amount_d = _amount_from_float32(amount_raw)
    if volume_raw < 0:
        raise TdxInvalidValueError(f"Negative volume at offset {offset}: {volume_raw}")

    return TdxDailyBar(
        date=date_value,
        open=open_d,
        high=high_d,
        low=low_d,
        close=close_d,
        amount=amount_d,
        volume=volume_raw,
    )


def _resolve_symbol_path(
    root: Path | str, market: str, symbol: str
) -> Path:
    if market not in _MARKETS:
        raise TdxInvalidMarketError(
            f"Unsupported market {market!r}; expected one of {sorted(_MARKETS)}"
        )
    if not (symbol.isdigit() and len(symbol) == 6):
        raise TdxInvalidSymbolError(
            f"Symbol must be six digits, got {symbol!r}"
        )
    return Path(root) / "vipdoc" / market / "lday" / f"{market}{symbol}.day"


def _apply_date_filters(
    bars: Iterable[TdxDailyBar],
    start: int | None,
    end: int | None,
) -> tuple[TdxDailyBar, ...]:
    if start is None and end is None:
        return tuple(bars)
    out: list[TdxDailyBar] = []
    for bar in bars:
        if start is not None and bar.date < start:
            continue
        if end is not None and bar.date > end:
            continue
        out.append(bar)
    return tuple(out)


def read_day_file(
    path: Path | str,
    *,
    start_date: int | _date | None = None,
    end_date: int | _date | None = None,
) -> tuple[TdxDailyBar, ...]:
    """Read a single ``.day`` file and return its parsed bars.

    The file must be a regular file whose size is a non-negative multiple of
    :data:`RECORD_SIZE` bytes. Empty files yield an empty tuple. Each record
    is validated strictly: bad dates or out-of-domain values raise
    :class:`~invest_pipeline.adapters.tdx_offline.errors.TdxInvalidDateError`
    or :class:`~invest_pipeline.adapters.tdx_offline.errors.TdxInvalidValueError`.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise TdxFileMissingError(f"TDX day file not found: {file_path}")
    if not file_path.is_file():
        raise TdxInvalidPathError(f"Path is not a regular file: {file_path}")

    size = file_path.stat().st_size
    if size == 0:
        return ()
    if size % RECORD_SIZE != 0:
        raise TdxInvalidSizeError(
            f"File size {size} bytes is not a multiple of {RECORD_SIZE}"
        )

    start = _coerce_date_filter(start_date)
    end = _coerce_date_filter(end_date)

    with file_path.open("rb") as fh:
        raw = fh.read()

    record_count = size // RECORD_SIZE
    bars = [
        _parse_record(raw, offset=i * RECORD_SIZE)
        for i in range(record_count)
    ]
    return _apply_date_filters(bars, start, end)


def read_symbol(
    root: Path | str,
    market: str,
    symbol: str,
    *,
    start_date: int | _date | None = None,
    end_date: int | _date | None = None,
) -> tuple[TdxDailyBar, ...]:
    """Resolve ``root/vipdoc/{market}/lday/{market}{symbol}.day`` and read it."""
    file_path = _resolve_symbol_path(root, market, symbol)
    return read_day_file(
        file_path, start_date=start_date, end_date=end_date
    )


__all__ = [
    "PROVIDER_KEY",
    "DATASET_KEY",
    "RECORD_SIZE",
    "read_day_file",
    "read_symbol",
]