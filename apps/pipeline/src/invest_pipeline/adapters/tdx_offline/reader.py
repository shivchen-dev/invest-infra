"""TDX .day offline reader spike.

The reader is intentionally narrow:

* parses one 32-byte little-endian record per bar
* resolves a bar file from a root directory using the canonical
  ``vipdoc/{market}/lday/{market}{symbol}.day`` layout for the three
  supported A-share markets: ``sh`` (Shanghai), ``sz`` (Shenzhen) and
  ``bj`` (Beijing)
* maps the TDX market code to the canonical exchange identifier the
  domain layer uses: ``sh -> SSE``, ``sz -> SZSE``, ``bj -> BJSE``
* validates each record strictly and surfaces specific exceptions
* performs optional inclusive date filtering on ``YYYYMMDD`` integers
* returns parsed bars as :class:`~invest_pipeline.adapters.tdx_offline.records.TdxDailyBar`
  instances whose monetary fields are :class:`decimal.Decimal` values
* enumerates the ``vipdoc/{sh,sz,bj}/lday`` tree for read-only symbol
  discovery so the by-date fallback can build its own universe without
  depending on a successful Tushare run

The reader does not perform ETF-protocol parsing, adjustment, instrument
mapping or persistence; those responsibilities are intentionally left out of
this spike.
"""

from __future__ import annotations

import math
import re
import struct
from collections.abc import Iterable, Mapping
from datetime import date as _date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

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

_MARKETS: frozenset[str] = frozenset({"sh", "sz", "bj"})

MARKET_TO_EXCHANGE: Mapping[str, str] = MappingProxyType(
    {
        "sh": "SSE",
        "sz": "SZSE",
        "bj": "BJSE",
    }
)

_LDAY_FILENAME_RE = re.compile(r"^(?P<market>sh|sz|bj)(?P<symbol>\d{6})\.day$")


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


def market_to_exchange(market: str) -> str:
    """Return the canonical exchange identifier for a TDX market code.

    The mapping is the single source of truth for the TDX ``sh`` / ``sz``
    / ``bj`` market codes → domain-layer ``SSE`` / ``SZSE`` / ``BJSE``
    exchange identifiers. Callers must use the canonical exchange string
    when stamping the persisted ``raw.provider_requests`` row so the
    upstream application service can route the offline evidence to the
    correct ``core.instruments`` / ``core.daily_bars`` partition.
    """

    try:
        return MARKET_TO_EXCHANGE[market]
    except KeyError as exc:
        raise TdxInvalidMarketError(
            f"Unsupported TDX market {market!r}; expected one of {sorted(_MARKETS)}"
        ) from exc


def enumerate_symbols(root: Path | str) -> tuple[tuple[str, str], ...]:
    """Enumerate the offline ``vipdoc`` tree for read-only symbol discovery.

    Scans every known market directory (``sh`` / ``sz`` / ``bj``) under
    ``root/vipdoc/{market}/lday`` and returns the regular files whose
    name matches the canonical ``<market><6digits>.day`` layout as a
    deterministic, sorted tuple of ``(market, symbol)`` pairs.

    The scan is **strict about the schema but lenient about filesystem
    noise**: directories that do not exist are silently skipped (so the
    helper degrades to a partial enumeration when an operator has only
    downloaded one or two markets), and files that do not match the
    canonical filename pattern — minute-line ``.lc1`` / ``.lc5`` files,
    ``index.*`` manifests, ``stockinfo`` snapshots — are silently
    dropped. The read-only helper never raises on an unrecognised
    filename; callers that want strict validation can pipe the result
    through :func:`read_symbol` which still enforces the same
    market and symbol checks as before.

    The result is sorted lexicographically by ``(market, symbol)`` so
    the by-date fallback can compare two enumerations byte-for-byte
    and the caller never has to sort the output themselves.
    """

    root_path = Path(root)
    if not root_path.exists():
        return ()
    if not root_path.is_dir():
        return ()

    pairs: list[tuple[str, str]] = []
    for market in sorted(_MARKETS):
        lday = root_path / "vipdoc" / market / "lday"
        if not lday.is_dir():
            continue
        for entry in lday.iterdir():
            if not entry.is_file():
                continue
            match = _LDAY_FILENAME_RE.match(entry.name)
            if match is None:
                continue
            discovered_market = match.group("market")
            if discovered_market != market:
                continue
            pairs.append((discovered_market, match.group("symbol")))
    pairs.sort()
    return tuple(pairs)


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
    "DATASET_KEY",
    "MARKET_TO_EXCHANGE",
    "PROVIDER_KEY",
    "RECORD_SIZE",
    "enumerate_symbols",
    "market_to_exchange",
    "read_day_file",
    "read_symbol",
]