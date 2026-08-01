"""CifangQuant field mappers (ADR-0011, Phase 1 second increment).

This module translates raw provider payloads into the domain
:mod:`invest_domain.instruments.models.Instrument` and
:mod:`invest_domain.market_data.models.DailyBar` shapes. It is
deliberately httpx-free so the boundary between transport
(:mod:`client`) and domain validation stays clean. Every Provider
alias / type / range / exchange allow-list rule lives here so the
client stays a thin wire-format wrapper.

Validation rules are taken from the Phase 1 contract documents:

- ETF scope and ``adjustment=none`` — ADR-0005 §3 / §6.
- SSE / SZSE allow-list — ADR-0004 §1.
- Nullable ``amount`` / ``prev_close`` — ADR-0005 §3 + ADR-0011 §2.
- Exchange field mapping ``SH`` → ``SSE`` / ``SZ`` → ``SZSE`` — ADR-0011 §2.
- ETF filter — ADR-0004 §2 (only ``ETF`` instrument_type is accepted).
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

from invest_pipeline.adapters.cifang.client import CifangResponse
from invest_pipeline.adapters.errors import ProviderDataContractError

_PROVIDER_KEY = "cifangquant"
_EXCHANGE_MAP: dict[str, str] = {"SH": "SSE", "SZ": "SZSE"}
_ALLOWED_EXCHANGES = frozenset(_EXCHANGE_MAP.values())
_ADJUST_ALLOWED = frozenset({"none"})


@dataclass(frozen=True, slots=True)
class CifangMappingResult:
    """The mappers return value-and-issues pairs so the adapter can
    record non-fatal warnings on the batch without raising.
    """

    instruments: tuple[Instrument, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CifangDailyBarsMappingResult:
    """Result of a chunk mapper; carries warnings for non-fatal skips."""

    bars: tuple[DailyBar, ...]
    warnings: tuple[str, ...]


# ----------------------------------------------------------------------
# ETF master-data mapper
# ----------------------------------------------------------------------


def map_fund_list(
    response: CifangResponse,
) -> CifangMappingResult:
    """Translate a ``/api/fund/list`` payload into domain instruments.

    The Provider returns a JSON array of objects whose field names are
    documented in ADR-0011 §2; this helper applies the SSE / SZSE
    allow-list, the ETF filter and rejects anything that does not fit.
    Non-ETF rows are silently skipped with a warning so a future
    Provider broadening (e.g. adding LOFs) does not fail the whole
    batch.
    """

    payload = response.raw_payload
    if not isinstance(payload, list):
        raise ProviderDataContractError(
            "MALFORMED_LIST_PAYLOAD",
            "Cifang /api/fund/list must return a JSON array",
            provider_key=_PROVIDER_KEY,
        )

    instruments: list[Instrument] = []
    warnings: list[str] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise ProviderDataContractError(
                "MALFORMED_LIST_ROW",
                f"row {index} is not a JSON object",
                provider_key=_PROVIDER_KEY,
            )
        symbol = _require_str(entry, index, "symbol")
        name = _require_str(entry, index, "name")
        raw_exchange = _require_str(entry, index, "exchange")
        exchange = _EXCHANGE_MAP.get(raw_exchange)
        if exchange is None:
            raise ProviderDataContractError(
                "UNSUPPORTED_EXCHANGE",
                f"row {index} exchange={raw_exchange!r} is not in "
                f"{sorted(_EXCHANGE_MAP)} (ADR-0011 §2)",
                provider_key=_PROVIDER_KEY,
            )
        if exchange not in _ALLOWED_EXCHANGES:
            raise ProviderDataContractError(
                "UNSUPPORTED_EXCHANGE",
                f"row {index} exchange={exchange!r} is outside the "
                f"ADR-0004 SSE / SZSE allow-list",
                provider_key=_PROVIDER_KEY,
            )
        raw_type = _optional_str(entry, "instrument_type") or _optional_str(
            entry, "type"
        )
        if raw_type is None:
            raise ProviderDataContractError(
                "MISSING_INSTRUMENT_TYPE",
                f"row {index} ({symbol!r}) has no instrument_type",
                provider_key=_PROVIDER_KEY,
            )
        try:
            instrument_type = InstrumentType(raw_type)
        except ValueError as exc:
            warnings.append(
                f"row {index} ({symbol!r}) unknown instrument_type={raw_type!r}; "
                f"skipped ({exc})"
            )
            continue
        if instrument_type is not InstrumentType.ETF:
            warnings.append(
                f"row {index} ({symbol!r}) instrument_type={raw_type!r} is "
                f"not ETF; skipped (ADR-0004 §2)"
            )
            continue
        status_raw = _optional_str(entry, "status") or "active"
        try:
            status = InstrumentStatus(status_raw)
        except ValueError:
            status = InstrumentStatus.ACTIVE
        list_date_raw = _optional_str(entry, "list_date")
        delist_date_raw = _optional_str(entry, "delist_date")
        try:
            list_date_value = (
                date.fromisoformat(list_date_raw) if list_date_raw else None
            )
            delist_date_value = (
                date.fromisoformat(delist_date_raw) if delist_date_raw else None
            )
        except ValueError as exc:
            raise ProviderDataContractError(
                "MALFORMED_LIST_DATE",
                f"row {index} ({symbol!r}) has an invalid date: {exc}",
                provider_key=_PROVIDER_KEY,
            ) from exc
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
    return CifangMappingResult(
        instruments=tuple(instruments), warnings=tuple(warnings)
    )


# ----------------------------------------------------------------------
# Daily-bars mapper
# ----------------------------------------------------------------------


def map_fund_hist_em(
    response: CifangResponse,
    *,
    chunk_index: int,
    chunk_count: int,
    source_batch_id: UUID,
    observed_at: datetime,
    instrument_id_resolver: Callable[[str, str], InstrumentId],
) -> CifangDailyBarsMappingResult:
    """Translate a ``/api/fund/hist_em`` chunk into domain :class:`DailyBar` rows.

    The chunk's response is a JSON object whose ``data`` key is a list
    of records (dict- or list-shaped depending on the official schema).
    This mapper handles the documented dict-shaped row in ADR-0011 §2:

        ``{symbol, exchange, trade_date, open, close, high, low,
        volume, amount, prev_close}``

    ``source_batch_id`` / ``observed_at`` are stamped by the adapter on
    the way in so the mapper does not need its own clock. ``provider_key``
    is the constant ``"cifangquant"`` carried through
    :class:`BarSource`.

    ``instrument_id_resolver`` is injected by the adapter so the
    mapper does not depend on storage; the adapter resolves the
    placeholder ``InstrumentId`` (mirroring the fixture_dev pattern).

    Rows missing ``prev_close`` or ``amount`` are forwarded as ``None``
    (ADR-0011 §2 / ADR-0005 §3); no values are ever synthesised.
    """

    payload = response.raw_payload
    if not isinstance(payload, dict):
        raise ProviderDataContractError(
            "MALFORMED_HIST_PAYLOAD",
            "Cifang /api/fund/hist_em must return a JSON object",
            provider_key=_PROVIDER_KEY,
        )
    adjust = payload.get("adjust")
    if adjust not in _ADJUST_ALLOWED:
        raise ProviderDataContractError(
            "NON_NONE_ADJUSTMENT",
            f"Cifang /api/fund/hist_em returned adjust={adjust!r}; "
            f"only 'none' is accepted in Phase 1 (ADR-0005 §3)",
            provider_key=_PROVIDER_KEY,
        )
    raw_rows = payload.get("data")
    if raw_rows is None:
        raise ProviderDataContractError(
            "MISSING_DATA_KEY",
            "Cifang /api/fund/hist_em payload has no 'data' array",
            provider_key=_PROVIDER_KEY,
        )
    if not isinstance(raw_rows, list):
        raise ProviderDataContractError(
            "MALFORMED_HIST_ROWS",
            "Cifang /api/fund/hist_em 'data' must be a list",
            provider_key=_PROVIDER_KEY,
        )

    bar_source = BarSource(
        provider_key=_PROVIDER_KEY,
        source_batch_id=source_batch_id,
        observed_at=observed_at,
    )
    bars: list[DailyBar] = []
    warnings: list[str] = []
    for index, entry in enumerate(raw_rows):
        if not isinstance(entry, dict):
            warnings.append(
                f"chunk {chunk_index}/{chunk_count} row {index} is not a "
                f"JSON object; skipped"
            )
            continue
        raw_symbol = _optional_str(entry, "symbol") or _optional_str(entry, "code")
        if raw_symbol is None:
            warnings.append(
                f"chunk {chunk_index}/{chunk_count} row {index} has no "
                f"symbol; skipped"
            )
            continue
        raw_exchange = (
            _optional_str(entry, "exchange") or _optional_str(entry, "market")
        )
        if raw_exchange is None:
            warnings.append(
                f"chunk {chunk_index}/{chunk_count} row {index} ({raw_symbol!r}) "
                f"has no exchange; skipped"
            )
            continue
        exchange = _EXCHANGE_MAP.get(raw_exchange, raw_exchange)
        if exchange not in _ALLOWED_EXCHANGES:
            raise ProviderDataContractError(
                "UNSUPPORTED_EXCHANGE",
                f"chunk {chunk_index}/{chunk_count} row {index} exchange="
                f"{raw_exchange!r} is not in {sorted(_EXCHANGE_MAP)} "
                f"(ADR-0011 §2)",
                provider_key=_PROVIDER_KEY,
            )
        try:
            bar = _row_to_bar(
                entry,
                raw_symbol=raw_symbol,
                exchange=exchange,
                instrument_id_resolver=instrument_id_resolver,
                bar_source=bar_source,
            )
        except _SkippedRow as exc:
            warnings.append(
                f"chunk {chunk_index}/{chunk_count} row {index} "
                f"({raw_symbol!r}): {exc}"
            )
            continue
        bars.append(bar)
    return CifangDailyBarsMappingResult(bars=tuple(bars), warnings=tuple(warnings))


# ----------------------------------------------------------------------
# Row-level helpers
# ----------------------------------------------------------------------


class _SkippedRow(ValueError):
    """Internal: a row is malformed at the field level but recoverable."""


def _row_to_bar(
    entry: dict[str, Any],
    *,
    raw_symbol: str,
    exchange: str,
    instrument_id_resolver: Callable[[str, str], InstrumentId],
    bar_source: BarSource,
) -> DailyBar:
    """Build a single :class:`DailyBar` from a fund-hist-em row dict.

    ``instrument_id_resolver`` is called with ``(symbol, exchange)`` and
    must return an ``InstrumentId``; the adapter wires this to its
    placeholder table (mirrors the fixture_dev pattern).
    """

    trade_date_raw = _require_str(entry, -1, "trade_date", field_hint="row")
    try:
        trade_date_value = date.fromisoformat(trade_date_raw)
    except ValueError as exc:
        raise _SkippedRow(f"invalid trade_date {trade_date_raw!r}: {exc}") from exc

    open_raw = _optional_value(entry, "open")
    close_raw = _optional_value(entry, "close")
    high_raw = _optional_value(entry, "high")
    low_raw = _optional_value(entry, "low")
    prev_close_raw = _optional_value(entry, "prev_close")
    volume_raw = _optional_value(entry, "volume")
    amount_raw = _optional_value(entry, "amount")

    # SUSPENDED rows carry no OHLC; if every numeric is null we treat
    # the row as suspended. Any partial value triggers a normal row.
    all_none = all(
        value is None
        for value in (open_raw, close_raw, high_raw, low_raw)
    )
    if all_none and volume_raw is None and amount_raw is None:
        return DailyBar.build(
            instrument_id=instrument_id_resolver(raw_symbol, exchange),
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

    if any(value is None for value in (open_raw, close_raw, high_raw, low_raw)):
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
            _to_decimal(prev_close_raw) if prev_close_raw is not None else None
        )
        volume_dec = (
            _to_decimal(volume_raw) if volume_raw is not None else Decimal(0)
        )
        amount_dec = (
            _to_decimal(amount_raw) if amount_raw is not None else None
        )
    except (InvalidOperation, ValueError) as exc:
        raise _SkippedRow(f"non-decimal numeric field: {exc}") from exc

    # OHLC invariant: high >= max(open, close, low); low <= min(open, close, high).
    if high_dec < max(open_dec, close_dec, low_dec):
        raise _SkippedRow(
            f"invalid OHLC: high={high_dec} < max(open, close, low)="
            f"{max(open_dec, close_dec, low_dec)}"
        )
    if low_dec > min(open_dec, close_dec, high_dec):
        raise _SkippedRow(
            f"invalid OHLC: low={low_dec} > min(open, close, high)="
            f"{min(open_dec, close_dec, high_dec)}"
        )

    return DailyBar.build(
        instrument_id=instrument_id_resolver(raw_symbol, exchange),
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


def _require_str(
    entry: dict[str, Any],
    index: int,
    field: str,
    *,
    field_hint: str = "row",
) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ProviderDataContractError(
            "MISSING_REQUIRED_FIELD",
            f"{field_hint} {index} missing {field!r}",
            provider_key=_PROVIDER_KEY,
        )
    return value


def _optional_str(entry: dict[str, Any], field: str) -> str | None:
    value = entry.get(field)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _optional_value(entry: dict[str, Any], field: str) -> Any:
    value = entry.get(field)
    if value is None:
        return None
    if isinstance(value, str) and value == "":
        return None
    return value


def _to_decimal(value: Any) -> Decimal:
    """Coerce a numeric / numeric-string field to ``Decimal``.

    Accepts ``int``, ``float`` and ``str``; rejects ``None`` and any
    non-finite / non-numeric value with a typed exception so the caller
    can downgrade to a row warning.
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
        return Decimal(value)
    raise ValueError(f"cannot convert {type(value).__name__} to Decimal")


__all__ = [
    "CifangDailyBarsMappingResult",
    "CifangMappingResult",
    "map_fund_hist_em",
    "map_fund_list",
]