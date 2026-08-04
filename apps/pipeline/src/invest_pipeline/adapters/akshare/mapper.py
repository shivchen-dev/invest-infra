"""AkShare field mappers (PR-02, matrix §2 / §4 / ADR-0004 / ADR-0005 / NAV / calendar).

This module translates AkShare's pandas ``DataFrame`` payloads into the
domain :mod:`invest_domain.instruments.models.Instrument` and
:mod:`invest_domain.market_data.models.DailyBar` shapes plus the
read-only NAV and trading-calendar surfaces. It is deliberately
:mod:`pandas`-free — the client has already normalised the upstream
response to a list of plain ``dict`` records so the mapper can be
exercised against hermetic test fixtures.

Validation rules are taken from the Phase-1 contract documents:

- ETF scope — matrix §4.1, ADR-0004 §2. Non-ETF rows are skipped with
  a warning so a future AkShare broadening (e.g. LOFs) does not fail
  the whole batch.
- ``SH`` → ``SSE`` / ``SZ`` → ``SZSE`` — ADR-0004 §1 / matrix §4.1.
- Exchange inference from a six-digit ETF code prefix — matrix §4.1.
- Adjustment is locked to ``""`` (the AkShare ``none`` literal) —
  ADR-0005 §4; the client already validates this on the way in so the
  mapper trusts the setting without re-checking.
- NAV is **never** coerced into OHLCV — plan §5 Task 2 ("明确 NAV
  不映射为 OHLCV，不填充成交额"); NAV rows carry
  ``unit_nav`` / ``accumulated_nav`` / ``daily_growth_rate`` only and
  ride on a dedicated :class:`ProviderBatch` record type.

The mapper is implemented as four pure helpers (matching the existing
Cifang mappers in :mod:`invest_pipeline.adapters.cifang.mapper`):

- :func:`map_fund_etf_fund_info_em` for the ETF master-data endpoint.
- :func:`map_fund_etf_hist_em` for the per-symbol ETF daily-bars
  endpoint.
- :func:`map_fund_etf_fund_daily_em` for the per-symbol ETF NAV
  endpoint (read-only, never coerces to OHLCV).
- :func:`map_tool_trade_date_hist_sina` for the SSE / SZSE
  trading-calendar endpoint (read-only date-only surface).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from invest_domain.instruments.models import (
    Instrument,
    InstrumentId,
    InstrumentStatus,
    InstrumentType,
)
from invest_domain.market_data.models import BarSource, DailyBar
from invest_domain.market_data.values import Adjust, Currency, TradingStatus

from invest_pipeline.adapters.akshare.client import AkshareResponse
from invest_pipeline.adapters.errors import ProviderDataContractError

_PROVIDER_KEY = "akshare"

_EXCHANGE_MAP: dict[str, str] = {"SH": "SSE", "SZ": "SZSE"}
_ALLOWED_EXCHANGES = frozenset(_EXCHANGE_MAP.values())

_AKSHARE_SYMBOL_ALIASES = (
    "基金代码",
    "code",
    "symbol",
    "代码",
)
_AKSHARE_NAME_ALIASES = (
    "基金简称",
    "name",
    "名称",
)
_AKSHARE_EXCHANGE_ALIASES = (
    "交易所",
    "exchange",
    "市场",
    "市场代码",
)
_AKSHARE_LIST_DATE_ALIASES = (
    "上市日期",
    "成立日期",
    "list_date",
    "establish_date",
    "上市日",
)
_AKSHARE_DELIST_DATE_ALIASES = (
    "退市日期",
    "delist_date",
    "摘牌日",
)
_AKSHARE_STATUS_ALIASES = (
    "基金状态",
    "status",
    "状态",
)

_AKSHARE_DATE_ALIASES = (
    "日期",
    "trade_date",
    "date",
)
_AKSHARE_OPEN_ALIASES = ("开盘", "open", "今开")
_AKSHARE_CLOSE_ALIASES = ("收盘", "close", "今收")
_AKSHARE_HIGH_ALIASES = ("最高", "high")
_AKSHARE_LOW_ALIASES = ("最低", "low")
_AKSHARE_VOLUME_ALIASES = ("成交量", "volume")
_AKSHARE_AMOUNT_ALIASES = ("成交额", "amount")
_AKSHARE_PREV_CLOSE_ALIASES = ("昨收", "prev_close")

_AKSHARE_NAV_UNIT_ALIASES = (
    "单位净值",
    "unit_nav",
    "net_value",
    "净值",
)
_AKSHARE_NAV_ACCUMULATED_ALIASES = (
    "累计净值",
    "accumulated_nav",
    "累计单位净值",
)
_AKSHARE_NAV_DAILY_GROWTH_ALIASES = (
    "日增长率",
    "daily_growth_rate",
    "涨跌幅",
    "pct_change",
)
_AKSHARE_NAV_DATE_ALIASES = (
    "净值日期",
    "日期",
    "trade_date",
    "date",
)
_AKSHARE_CALENDAR_DATE_ALIASES = (
    "trade_date",
    "日期",
    "date",
)


@dataclass(frozen=True, slots=True)
class AkshareMappingResult:
    """Result of a master-data mapping pass.

    Carries the in-domain instruments plus a tuple of non-fatal
    warnings so the adapter can record them on the batch without
    raising.
    """

    instruments: tuple[Instrument, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AkshareDailyBarsMappingResult:
    """Result of a daily-bars mapping pass.

    Carries the resulting :class:`DailyBar` rows plus a tuple of
    non-fatal warnings. The mapper never raises on row-level issues;
    row-level failures downgrade to a warning so the upstream batch
    preserves the surviving rows.
    """

    bars: tuple[DailyBar, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AkshareNavRecord:
    """A single NAV row produced by ``ak.fund_etf_fund_daily_em()``.

    NAV rows are a strictly separate shape from :class:`DailyBar`
    per plan §5 Task 2 ("明确 NAV 不映射为 OHLCV，不填充成交额"). The
    mapper therefore builds this dataclass instead of a
    :class:`DailyBar` and the adapter packages the records into a
    :class:`ProviderBatch` carrying ``dataset_key="etf_nav"``. The
    fields are immutable and ``slots=True`` so a
    :class:`frozenset` of fields can feed the PR-05 coverage probe.
    """

    symbol: str
    trade_date: date
    unit_nav: Decimal | None
    accumulated_nav: Decimal | None
    daily_growth_rate: Decimal | None
    source_batch_id: UUID
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class AkshareNavMappingResult:
    """Result of a NAV mapping pass.

    Carries the resulting :class:`AkshareNavRecord` rows plus a tuple
    of non-fatal warnings. Row-level failures downgrade to a warning
    rather than failing the whole batch so a single malformed NAV
    row never blocks the surviving rows.
    """

    records: tuple[AkshareNavRecord, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AkshareCalendarRecord:
    """A single trading-calendar entry produced by ``ak.tool_trade_date_hist_sina()``.

    The calendar is a strictly read-only surface; the mapper only
    carries the date and the upstream-flag passthrough (e.g.
    ``is_open`` when present) so the adapter can stamp a
    :class:`ProviderBatch` with ``dataset_key="trading_calendar"``
    without coercing calendar rows into :class:`DailyBar` or
    :class:`Instrument`.
    """

    trade_date: date
    is_open: bool | None


@dataclass(frozen=True, slots=True)
class AkshareCalendarMappingResult:
    """Result of a trading-calendar mapping pass.

    Carries the resulting :class:`AkshareCalendarRecord` rows plus a
    tuple of non-fatal warnings. The mapping is intentionally
    shallow — the calendar carries no per-symbol content — so a
    malformed date row is the only recoverable failure mode.
    """

    records: tuple[AkshareCalendarRecord, ...]
    warnings: tuple[str, ...]


# ----------------------------------------------------------------------
# ETF master-data mapper
# ----------------------------------------------------------------------


def map_fund_etf_fund_info_em(
    response: AkshareResponse,
) -> AkshareMappingResult:
    """Translate ``ak.fund_etf_fund_info_em()`` rows into domain instruments.

    The mapper accepts the downstream dict-row shape produced by the
    client and applies:

    - The SSE / SZSE allow-list.
    - The ETF-only filter (``InstrumentType.ETF``); non-ETF rows are
      silently skipped with a warning so a future AkShare broadening
      does not fail the entire batch.
    - Field-alias resolution so both the documented Chinese column
      names (``基金代码`` / ``基金简称`` / ...) and English aliases
      (``code`` / ``symbol`` / ...) are honoured.

    Required fields:

    - ``symbol`` (six-digit string; mapped to ``symbol`` /
      ``exchange`` via the prefix rule or the explicit ``exchange``
      field).
    - ``name`` (non-empty string).

    Rows missing a required field raise
    :class:`ProviderDataContractError` so the upstream batch is
    rejected rather than silently returning an incomplete instrument
    set, mirroring the Cifang :func:`map_fund_list` policy.
    """

    warnings: list[str] = []
    instruments: list[Instrument] = []
    for index, entry in enumerate(response.raw_payload):
        if not isinstance(entry, dict):
            raise ProviderDataContractError(
                "MALFORMED_ETF_LIST_ROW",
                f"row {index} is not a JSON object",
                provider_key=_PROVIDER_KEY,
            )
        symbol = _alias_str(entry, _AKSHARE_SYMBOL_ALIASES)
        if symbol is None:
            raise ProviderDataContractError(
                "MISSING_REQUIRED_FIELD",
                f"row {index} missing symbol/code field "
                f"(tried {list(_AKSHARE_SYMBOL_ALIASES)})",
                provider_key=_PROVIDER_KEY,
            )
        name = _alias_str(entry, _AKSHARE_NAME_ALIASES)
        if name is None:
            raise ProviderDataContractError(
                "MISSING_REQUIRED_FIELD",
                f"row {index} ({symbol!r}) missing name field "
                f"(tried {list(_AKSHARE_NAME_ALIASES)})",
                provider_key=_PROVIDER_KEY,
            )
        raw_exchange = _alias_str(entry, _AKSHARE_EXCHANGE_ALIASES)
        exchange = _resolve_exchange(symbol=symbol, raw_exchange=raw_exchange)
        list_date_raw = _alias_value(entry, _AKSHARE_LIST_DATE_ALIASES)
        list_date_value = _coerce_optional_date(list_date_raw)
        delist_date_raw = _alias_value(entry, _AKSHARE_DELIST_DATE_ALIASES)
        delist_date_value = _coerce_optional_date(delist_date_raw)
        status_raw = _alias_str(entry, _AKSHARE_STATUS_ALIASES) or "active"
        try:
            status = InstrumentStatus(status_raw)
        except ValueError:
            status = InstrumentStatus.ACTIVE
        instruments.append(
            Instrument(
                symbol=symbol,
                name=name,
                exchange=exchange,
                instrument_type=InstrumentType.ETF,
                is_active=status is not InstrumentStatus.DELISTED,
                currency=Currency.CNY,
                list_date=list_date_value,
                delist_date=delist_date_value,
                status=status,
                provider_symbol_map={_PROVIDER_KEY: symbol},
            )
        )
    return AkshareMappingResult(
        instruments=tuple(instruments), warnings=tuple(warnings)
    )


# ----------------------------------------------------------------------
# Daily-bars mapper
# ----------------------------------------------------------------------


def map_fund_etf_hist_em(
    response: AkshareResponse,
    *,
    symbol: str,
    source_batch_id: UUID,
    observed_at: datetime,
    instrument_id_resolver: Callable[[str, str], InstrumentId],
    bar_source_key: str = _PROVIDER_KEY,
) -> AkshareDailyBarsMappingResult:
    """Translate ``ak.fund_etf_hist_em(...)`` rows into domain :class:`DailyBar`.

    The mapper accepts the dict-row shape produced by the client. Each
    row is translated using both the documented Chinese column names
    (``日期`` / ``开盘`` / ``收盘`` / ``最高`` / ``最低`` / ``成交量``
    / ``成交额``) and an English alias set; rows that miss required
    OHLC fields or fail the OHLC invariant downgrade to a warning so
    surviving rows still ship to the upstream batch.

    The instrument_id_resolver is the same seam used by the Cifang
    daily-bars mapper; the adapter wires this to its
    ``(symbol, exchange) -> InstrumentId`` placeholder table.
    """

    bar_source = BarSource(
        provider_key=bar_source_key,
        source_batch_id=source_batch_id,
        observed_at=observed_at,
    )
    exchange = _resolve_exchange(symbol=symbol, raw_exchange=None)
    bars: list[DailyBar] = []
    warnings: list[str] = []
    for index, entry in enumerate(response.raw_payload):
        if not isinstance(entry, dict):
            warnings.append(
                f"row {index} (symbol={symbol!r}) is not a JSON "
                f"object; skipped"
            )
            continue
        try:
            bar = _row_to_bar(
                entry,
                symbol=symbol,
                exchange=exchange,
                instrument_id_resolver=instrument_id_resolver,
                bar_source=bar_source,
            )
        except _SkippedRow as exc:
            warnings.append(
                f"row {index} (symbol={symbol!r}): {exc}"
            )
            continue
        bars.append(bar)
    return AkshareDailyBarsMappingResult(
        bars=tuple(bars), warnings=tuple(warnings)
    )


# ----------------------------------------------------------------------
# NAV mapper (no OHLCV coercion)
# ----------------------------------------------------------------------


def map_fund_etf_fund_daily_em(
    response: AkshareResponse,
    *,
    symbol: str,
    source_batch_id: UUID,
    observed_at: datetime,
) -> AkshareNavMappingResult:
    """Translate ``ak.fund_etf_fund_daily_em(...)`` rows into :class:`AkshareNavRecord`.

    Per plan §5 Task 2 ("明确 NAV 不映射为 OHLCV，不填充成交额") the NAV
    rows are **deliberately not** coerced into :class:`DailyBar`. The
    mapper therefore builds the local :class:`AkshareNavRecord`
    dataclass with ``unit_nav`` / ``accumulated_nav`` /
    ``daily_growth_rate`` only; ``open`` / ``high`` / ``low`` /
    ``close`` / ``volume`` / ``amount`` are never synthesised.

    Field alias resolution matches the existing mappers: both the
    documented Chinese column names (``单位净值`` / ``累计净值`` /
    ``日增长率`` / ``净值日期``) and the English aliases (``unit_nav``
    / ``accumulated_nav`` / ``daily_growth_rate`` / ``pct_change`` /
    ``trade_date``) are accepted. ``trade_date`` uses the same
    ``YYYY-MM-DD`` / ``YYYYMMDD`` flexibility as the daily-bars
    mapper. A row missing a required NAV field downgrades to a
    warning so the surviving rows still ship; a missing
    ``trade_date`` is also a recoverable warning because the upstream
    feed occasionally emits footer rows.
    """

    records: list[AkshareNavRecord] = []
    warnings: list[str] = []
    for index, entry in enumerate(response.raw_payload):
        if not isinstance(entry, dict):
            warnings.append(
                f"row {index} (symbol={symbol!r}) is not a JSON "
                "object; skipped"
            )
            continue
        trade_date_raw = _alias_str(entry, _AKSHARE_NAV_DATE_ALIASES)
        if trade_date_raw is None:
            warnings.append(
                f"row {index} (symbol={symbol!r}) missing "
                f"trade_date/date field; skipped"
            )
            continue
        try:
            trade_date_value = _coerce_trade_date(trade_date_raw)
        except _SkippedRow as exc:
            warnings.append(
                f"row {index} (symbol={symbol!r}): {exc}"
            )
            continue
        try:
            unit_nav_value = _optional_decimal(
                entry, _AKSHARE_NAV_UNIT_ALIASES
            )
            accumulated_nav_value = _optional_decimal(
                entry, _AKSHARE_NAV_ACCUMULATED_ALIASES
            )
            daily_growth_value = _optional_decimal(
                entry, _AKSHARE_NAV_DAILY_GROWTH_ALIASES
            )
        except _SkippedRow as exc:
            warnings.append(
                f"row {index} (symbol={symbol!r}): {exc}"
            )
            continue
        records.append(
            AkshareNavRecord(
                symbol=symbol,
                trade_date=trade_date_value,
                unit_nav=unit_nav_value,
                accumulated_nav=accumulated_nav_value,
                daily_growth_rate=daily_growth_value,
                source_batch_id=source_batch_id,
                observed_at=observed_at,
            )
        )
    return AkshareNavMappingResult(
        records=tuple(records), warnings=tuple(warnings)
    )


# ----------------------------------------------------------------------
# Trading-calendar mapper (read-only, date-only)
# ----------------------------------------------------------------------


def map_tool_trade_date_hist_sina(
    response: AkshareResponse,
) -> AkshareCalendarMappingResult:
    """Translate ``ak.tool_trade_date_hist_sina()`` rows into :class:`AkshareCalendarRecord`.

    The calendar is a **read-only** surface with no per-symbol
    content; the mapper therefore carries only the ``trade_date``
    plus an optional ``is_open`` flag passthrough. A row missing a
    parseable ``trade_date`` downgrades to a warning so the surviving
    dates still ship; a non-dict row is similarly recoverable. The
    mapper never raises on row-level issues so a single malformed
    footer row cannot block the whole calendar batch.
    """

    records: list[AkshareCalendarRecord] = []
    warnings: list[str] = []
    for index, entry in enumerate(response.raw_payload):
        if not isinstance(entry, dict):
            warnings.append(
                f"row {index} is not a JSON object; skipped"
            )
            continue
        trade_date_raw = _alias_str(entry, _AKSHARE_CALENDAR_DATE_ALIASES)
        if trade_date_raw is None:
            warnings.append(
                f"row {index} missing trade_date/date field; skipped"
            )
            continue
        try:
            trade_date_value = _coerce_trade_date(trade_date_raw)
        except _SkippedRow as exc:
            warnings.append(
                f"row {index}: {exc}"
            )
            continue
        is_open = _coerce_optional_bool(
            _alias_value(entry, ("is_open", "open", "is_trade_day"))
        )
        records.append(
            AkshareCalendarRecord(
                trade_date=trade_date_value,
                is_open=is_open,
            )
        )
    return AkshareCalendarMappingResult(
        records=tuple(records), warnings=tuple(warnings)
    )


# ----------------------------------------------------------------------
# Row-level helpers
# ----------------------------------------------------------------------


class _SkippedRow(ValueError):
    """Internal: a row is malformed at the field level but recoverable."""


def _row_to_bar(
    entry: dict[str, Any],
    *,
    symbol: str,
    exchange: str,
    instrument_id_resolver: Callable[[str, str], InstrumentId],
    bar_source: BarSource,
) -> DailyBar:
    """Build a single :class:`DailyBar` from a daily-bars row dict."""

    trade_date_raw = _alias_value(entry, _AKSHARE_DATE_ALIASES)
    if trade_date_raw is None:
        raise _SkippedRow(
            "missing trade_date/date field "
            f"(tried {list(_AKSHARE_DATE_ALIASES)})"
        )
    trade_date_value = _coerce_trade_date(trade_date_raw)

    open_raw = _alias_value(entry, _AKSHARE_OPEN_ALIASES)
    close_raw = _alias_value(entry, _AKSHARE_CLOSE_ALIASES)
    high_raw = _alias_value(entry, _AKSHARE_HIGH_ALIASES)
    low_raw = _alias_value(entry, _AKSHARE_LOW_ALIASES)
    prev_close_raw = _alias_value(entry, _AKSHARE_PREV_CLOSE_ALIASES)
    volume_raw = _alias_value(entry, _AKSHARE_VOLUME_ALIASES)
    amount_raw = _alias_value(entry, _AKSHARE_AMOUNT_ALIASES)

    all_none = all(
        value is None for value in (open_raw, close_raw, high_raw, low_raw)
    )
    if all_none and volume_raw is None and amount_raw is None:
        return DailyBar.build(
            instrument_id=instrument_id_resolver(symbol, exchange),
            trade_date=trade_date_value,
            open=None,
            high=None,
            low=None,
            close=None,
            prev_close=None,
            volume=None,
            amount=None,
            adjustment=Adjust.NONE,
            trading_status=TradingStatus.SUSPENDED,
            source=bar_source,
            revision=1,
        )

    if any(
        value is None
        for value in (open_raw, close_raw, high_raw, low_raw)
    ):
        raise _SkippedRow(
            "missing required OHLC field "
            f"(open={open_raw!r}, close={close_raw!r}, "
            f"high={high_raw!r}, low={low_raw!r})"
        )
    try:
        open_dec = _to_decimal(open_raw)
        high_dec = _to_decimal(high_raw)
        low_dec = _to_decimal(low_raw)
        close_dec = _to_decimal(close_raw)
        prev_close_dec = (
            _to_decimal(prev_close_raw)
            if prev_close_raw is not None
            else None
        )
        volume_dec = (
            _to_decimal(volume_raw)
            if volume_raw is not None
            else Decimal(0)
        )
        amount_dec = (
            _to_decimal(amount_raw)
            if amount_raw is not None
            else None
        )
    except (InvalidOperation, ValueError) as exc:
        raise _SkippedRow(
            f"non-decimal numeric field: {exc}"
        ) from exc

    if high_dec < max(open_dec, close_dec, low_dec):
        raise _SkippedRow(
            f"invalid OHLC: high={high_dec} < "
            f"max(open, close, low)={max(open_dec, close_dec, low_dec)}"
        )
    if low_dec > min(open_dec, close_dec, high_dec):
        raise _SkippedRow(
            f"invalid OHLC: low={low_dec} > "
            f"min(open, close, high)={min(open_dec, close_dec, high_dec)}"
        )

    return DailyBar.build(
        instrument_id=instrument_id_resolver(symbol, exchange),
        trade_date=trade_date_value,
        open=open_dec,
        high=high_dec,
        low=low_dec,
        close=close_dec,
        prev_close=prev_close_dec,
        volume=volume_dec,
        amount=amount_dec,
        adjustment=Adjust.NONE,
        trading_status=TradingStatus.NORMAL,
        source=bar_source,
        revision=1,
    )


def _resolve_exchange(*, symbol: str, raw_exchange: str | None) -> str:
    """Resolve the SSE / SZSE exchange for an ETF record.

    Prefers an explicit ``exchange`` field when present; otherwise
    infers from the documented six-digit ETF prefix rule. Raises
    :class:`ProviderDataContractError` when the resolved exchange is
    outside the ADR-0004 allow-list.
    """

    if raw_exchange is not None:
        candidate = _EXCHANGE_MAP.get(raw_exchange, raw_exchange)
    else:
        candidate = _exchange_for_etf_symbol(symbol)
    if candidate not in _ALLOWED_EXCHANGES:
        raise ProviderDataContractError(
            "UNSUPPORTED_EXCHANGE",
            f"symbol={symbol!r} raw_exchange={raw_exchange!r} resolved "
            f"to exchange={candidate!r}; outside the ADR-0004 "
            "SSE / SZSE allow-list",
            provider_key=_PROVIDER_KEY,
        )
    return candidate


def _exchange_for_etf_symbol(symbol: str) -> str:
    """Infer SSE / SZSE from the six-digit ETF prefix.

    The convention follows the official AkShare examples: codes
    starting with ``5`` or ``6`` live on the Shanghai exchange
    (``SSE``); codes starting with ``1`` or ``2`` live on the
    Shenzhen exchange (``SZSE``).
    """

    if not isinstance(symbol, str) or not symbol.strip():
        raise ProviderDataContractError(
            "MALFORMED_ETF_SYMBOL",
            "cannot infer SSE / SZSE exchange from an empty symbol",
            provider_key=_PROVIDER_KEY,
        )
    head = symbol.strip()[0]
    if head in {"5", "6"}:
        return "SSE"
    if head in {"1", "2"}:
        return "SZSE"
    raise ProviderDataContractError(
        "UNSUPPORTED_EXCHANGE",
        f"cannot infer SSE / SZSE exchange from symbol {symbol!r} "
        f"(expected leading digit in {{'1', '2', '5', '6'}})",
        provider_key=_PROVIDER_KEY,
    )


def _alias_str(entry: dict[str, Any], aliases: tuple[str, ...]) -> str | None:
    """Return the first non-empty string value among ``aliases``."""

    for key in aliases:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _alias_value(entry: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    """Return the first non-null / non-empty value among ``aliases``."""

    for key in aliases:
        if key not in entry:
            continue
        value = entry[key]
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        return value
    return None


def _coerce_optional_date(raw: Any) -> date | None:
    """Parse an optional date field. Returns ``None`` for empty values.

    Accepts ``datetime.date`` / ``datetime.datetime`` and the string
    forms ``"YYYY-MM-DD"`` (ADR-0005 / matrix §4.2) and ``"YYYYMMDD"``
    (AkShare's compact native form).
    """

    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        raise ProviderDataContractError(
            "MALFORMED_LIST_DATE",
            f"date field {raw!r} is neither ISO 'YYYY-MM-DD' nor compact 'YYYYMMDD'",
            provider_key=_PROVIDER_KEY,
        )
    raise ProviderDataContractError(
        "MALFORMED_LIST_DATE",
        f"date field has unexpected type {type(raw).__name__}",
        provider_key=_PROVIDER_KEY,
    )


def _coerce_trade_date(raw: str | date) -> date:
    """Parse a required trade-date string.

    Mirrors :func:`_coerce_optional_date` but is used for required
    fields: an empty / malformed value raises :class:`_SkippedRow` so
    the upstream row is dropped with a warning rather than failing the
    whole batch.
    """

    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = raw.strip()
    if not text:
        raise _SkippedRow("empty trade_date/date field")
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise _SkippedRow(
        f"invalid trade_date {raw!r}: expected ISO 'YYYY-MM-DD' or compact 'YYYYMMDD'"
    )


def _to_decimal(value: Any) -> Decimal:
    """Coerce a numeric / numeric-string field to ``Decimal``.

    Accepts ``Decimal`` / ``int`` / ``float`` / ``str`` and rejects
    non-finite floats so the upstream row surfaces a clean
    :class:`_SkippedRow` instead of a float-precision surprise.
    """

    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"non-finite float {value!r}")
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value.strip())
    raise ValueError(
        f"cannot convert {type(value).__name__} to Decimal"
    )


def _optional_decimal(
    entry: dict[str, Any], aliases: tuple[str, ...]
) -> Decimal | None:
    """Return the first decimal-coercible value among ``aliases``, or ``None``.

    Mirrors :func:`_alias_value` but routes through
    :func:`_to_decimal` so the NAV / calendar mapper can build
    ``Decimal`` columns without re-implementing alias resolution. A
    missing / empty value returns ``None``; a present-but-non-numeric
    value raises :class:`_SkippedRow` so the upstream row is dropped
    with a warning rather than failing the whole batch.
    """

    raw = _alias_value(entry, aliases)
    if raw is None:
        return None
    try:
        return _to_decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise _SkippedRow(
            f"non-decimal numeric field for aliases "
            f"{list(aliases)!r}: {exc}"
        ) from exc


def _coerce_optional_bool(raw: Any) -> bool | None:
    """Best-effort coercion of an upstream flag value to ``bool | None``.

    The trading-calendar feed occasionally surfaces a boolean ``is_open``
    flag; ``"1"`` / ``"0"`` / ``"true"`` / ``"false"`` and the
    ``int`` forms ``1`` / ``0`` are accepted. A missing / empty value
    returns ``None`` so the calendar mapper never fabricates a flag.
    """

    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str):
        text = raw.strip().lower()
        if not text:
            return None
        if text in {"1", "true", "t", "yes", "y", "open"}:
            return True
        if text in {"0", "false", "f", "no", "n", "closed", "close"}:
            return False
        return None
    return None


__all__ = [
    "AkshareCalendarMappingResult",
    "AkshareCalendarRecord",
    "AkshareDailyBarsMappingResult",
    "AkshareMappingResult",
    "AkshareNavMappingResult",
    "AkshareNavRecord",
    "map_fund_etf_fund_daily_em",
    "map_fund_etf_fund_info_em",
    "map_fund_etf_hist_em",
    "map_tool_trade_date_hist_sina",
]
