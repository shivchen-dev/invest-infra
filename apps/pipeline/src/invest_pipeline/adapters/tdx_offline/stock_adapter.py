"""TDX ``.day`` offline stock provider — Stage 4B Phase 5 (slice 1).

This module wires the offline reader spike
(:mod:`invest_pipeline.adapters.tdx_offline.reader`) into the V2
provider evidence-tuple contract for the A-share stock daily-bars
slice. It is intentionally narrow:

* The adapter is a **drop-in provider** for the existing
  :mod:`invest_pipeline.stock_daily_bars` service — it implements the
  same structural port (:class:`invest_pipeline.stock_daily_bars.
  _StockProviderPort` and :class:`_StockByTradeDateProviderPort`) the
  Tushare :class:`StockTushareProvider` already exposes. A future
  fallback orchestration can therefore call into the same
  :func:`write_stock_daily_bars_raw` /
  :func:`write_stock_daily_bars_raw_by_trade_date` helpers without
  any shape change at the application-service layer.
* The adapter translates one ``.day`` file per
  ``(symbol, market)`` pair into a stream of :class:`DailyBar` records
  via :func:`map_tdx_daily_bars`; prices and amount are kept as
  :class:`decimal.Decimal` so the binary-float representation TDX
  stores never leaks into the upstream ``DailyBar`` row hash.
* Missing or invalid ``.day`` files **fail closed** — a missing
  file or a non-32-multiple size surfaces as a
  :class:`ProviderAttemptStatus.FAILED` attempt with
  :class:`ProviderFailureStage.STORAGE` and a deterministic
  ``error_code`` (e.g. ``"tdx_file_missing"``). The application
  service can therefore treat the offline read like any other
  provider failure and surface the skipped-asset semantic.
* The provider **never** issues a network call. The whole point of
  the offline adapter is to be the deterministic
  ``Tushare → TDX offline`` fallback; failing open would defeat the
  contract.

Slice 1 deliberately does not wire the runtime fallback into the
``stock_daily_bars_raw`` Dagster asset. The provider, the settings,
and the catalog entry are landing in this slice; the asset-level
fallback orchestration is documented in
:mod:`invest_pipeline.adapters.tdx_offline` as a follow-up that
requires a symbol-enumeration contract (a future slice must decide
how the by-date asset learns which symbols to read from the offline
``vipdoc`` tree without relying on a successful Tushare run to
provide them).
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from invest_domain.instruments.models import InstrumentId
from invest_domain.market_data.models import (
    BarSource,
    DailyBar,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderFailureStage,
    ProviderRequest,
)
from invest_domain.market_data.values import Adjust, TradingStatus

from invest_pipeline.adapters.tdx_offline.config import TdxOfflineSettings
from invest_pipeline.adapters.tdx_offline.errors import (
    TdxFileMissingError,
    TdxInvalidDateError,
    TdxInvalidMarketError,
    TdxInvalidPathError,
    TdxInvalidSizeError,
    TdxInvalidSymbolError,
    TdxInvalidValueError,
    TdxOfflineError,
)
from invest_pipeline.adapters.tdx_offline.reader import (
    DATASET_KEY,
    PROVIDER_KEY,
    read_symbol,
)
from invest_pipeline.adapters.tdx_offline.records import TdxDailyBar

_DEFAULT_BY_DATE_REQUEST_KEY = "daily-bars-by-date-{trade_date}"
_PER_SYMBOL_REQUEST_KEY_TEMPLATE = "daily-bars-{start}-{end}-{symbols}"

_MARKET_SH = "sh"
_MARKET_SZ = "sz"
_MARKET_TO_EXCHANGE: dict[str, str] = {
    _MARKET_SH: "SSE",
    _MARKET_SZ: "SZSE",
}
_EXCHANGE_TO_MARKET: dict[str, str] = {value: key for key, value in _MARKET_TO_EXCHANGE.items()}

_TDX_FILE_MISSING_CODE = "tdx_file_missing"
_TDX_INVALID_SIZE_CODE = "tdx_invalid_size"
_TDX_INVALID_DATE_CODE = "tdx_invalid_date"
_TDX_INVALID_VALUE_CODE = "tdx_invalid_value"
_TDX_INVALID_PATH_CODE = "tdx_invalid_path"
_TDX_INVALID_SYMBOL_CODE = "tdx_invalid_symbol"
_TDX_INVALID_MARKET_CODE = "tdx_invalid_market"
_TDX_DISABLED_CODE = "tdx_disabled"
_TDX_NO_UNIVERSE_CODE = "tdx_no_universe"
_TDX_RECORD_CAP_CODE = "tdx_record_cap_exceeded"

_TDX_ERROR_CODE_BY_EXCEPTION: dict[type[TdxOfflineError], str] = {
    TdxFileMissingError: _TDX_FILE_MISSING_CODE,
    TdxInvalidSizeError: _TDX_INVALID_SIZE_CODE,
    TdxInvalidDateError: _TDX_INVALID_DATE_CODE,
    TdxInvalidValueError: _TDX_INVALID_VALUE_CODE,
    TdxInvalidPathError: _TDX_INVALID_PATH_CODE,
    TdxInvalidSymbolError: _TDX_INVALID_SYMBOL_CODE,
    TdxInvalidMarketError: _TDX_INVALID_MARKET_CODE,
}


def _resolve_market(symbol: str) -> str:
    """Return the TDX market code (``sh`` or ``sz``) for a six-digit symbol.

    Mirrors :meth:`TushareInstrumentProvider._native_code` so the
    sidecar exchange field stays aligned with the Tushare convention:
    symbols starting with ``5`` / ``6`` route to Shanghai, everything
    else to Shenzhen. Stock symbols that share the same exchange as
    ETFs (``5xxxxx`` / ``6xxxxx``) follow the same rule; the stock-only
    prefixes (``0xxxxx`` / ``3xxxxx``) all fall under the Shenzhen
    branch. The rule is deterministic and unit-testable without a
    network call.
    """

    if not isinstance(symbol, str) or not symbol.isdigit() or len(symbol) != 6:
        raise TdxInvalidSymbolError(f"Symbol must be six digits, got {symbol!r}")
    return _MARKET_SH if symbol.startswith(("5", "6")) else _MARKET_SZ


def _market_to_exchange(market: str) -> str:
    try:
        return _MARKET_TO_EXCHANGE[market]
    except KeyError as exc:
        raise TdxInvalidMarketError(
            f"Unsupported TDX market {market!r}; expected one of {sorted(_MARKET_TO_EXCHANGE)}"
        ) from exc


def _yyyymmdd_to_date(value: int) -> date:
    year = value // 10000
    month = (value // 100) % 100
    day = value % 100
    return date(year, month, day)


def _date_to_yyyymmdd(value: date) -> int:
    return value.year * 10000 + value.month * 100 + value.day


def _per_symbol_request_key(start_date: date, end_date: date, symbols: Sequence[str]) -> str:
    return _PER_SYMBOL_REQUEST_KEY_TEMPLATE.format(
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        symbols="-".join(sorted(symbols)),
    )


def _by_date_request_key(trade_date: date) -> str:
    return _DEFAULT_BY_DATE_REQUEST_KEY.format(trade_date=trade_date.isoformat())


def _bar_to_daily_bar(
    *,
    bar: TdxDailyBar,
    instrument_id: InstrumentId,
    provider_key: str,
    source_batch_id: UUID,
    observed_at: datetime,
) -> DailyBar:
    """Map one :class:`TdxDailyBar` to a :class:`DailyBar`.

    The TDX reader does not store a per-bar trading status; offline
    ``.day`` files only record the dates the upstream actually traded.
    Every mapped row is therefore stamped
    :class:`TradingStatus.NORMAL` — a missing bar in the offline
    file is a *no row*, not a ``SUSPENDED`` row, and is dropped at
    the reader layer (not here).
    """

    source = BarSource(
        provider_key=provider_key,
        source_batch_id=source_batch_id,
        observed_at=observed_at,
    )
    return DailyBar.build(
        instrument_id=instrument_id,
        trade_date=_yyyymmdd_to_date(bar.date),
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        prev_close=None,
        volume=Decimal_int_to_decimal(bar.volume),
        amount=bar.amount,
        adjustment=Adjust.NONE,
        trading_status=TradingStatus.NORMAL,
        source=source,
        revision=1,
    )


def Decimal_int_to_decimal(value: int) -> Any:
    """Convert an integer TDX ``volume`` to a :class:`decimal.Decimal`.

    The standalone helper exists so the dependency on
    :class:`decimal.Decimal` is local to the adapter (the helper is
    inline-imported from :func:`_bar_to_daily_bar`). The conversion is
    lossy-free: the integer volume is preserved exactly.
    """

    from decimal import Decimal

    return Decimal(value)


def _raw_payload_hash(payload: bytes) -> str:
    """Return the SHA-256 hex digest of a serialised offline payload.

    The hash is the offline counterpart of the
    ``raw_payload_hash`` the Tushare adapter computes over the HTTP
    response: it is content-only, deterministic, and exposes nothing
    about the operator's filesystem layout.
    """

    return sha256(payload).hexdigest()


def _build_raw_payload(
    *,
    bars_by_symbol: dict[tuple[str, str], tuple[TdxDailyBar, ...]],
    started_at: datetime,
    finished_at: datetime,
) -> bytes:
    """Build a deterministic binary payload for the offline evidence hash.

    The payload is **not** a wire format — it is a deterministic byte
    string the adapter hashes into :attr:`ProviderBatch.raw_payload_hash`.
    A stable, sorted serialisation guarantees two offline runs over
    the same files produce the same hash, mirroring the Tushare
    contract.
    """

    parts: list[bytes] = []
    parts.append(struct.pack("<QQ", int(started_at.timestamp()), int(finished_at.timestamp())))
    for symbol, market in sorted(bars_by_symbol):
        parts.append(symbol.encode("ascii"))
        parts.append(b"|")
        parts.append(market.encode("ascii"))
        parts.append(b"\n")
        for bar in bars_by_symbol[(symbol, market)]:
            parts.append(
                struct.pack(
                    "<I",
                    bar.date,
                )
            )
            parts.append(
                str(bar.open).encode("ascii")
                + b","
                + str(bar.high).encode("ascii")
                + b","
                + str(bar.low).encode("ascii")
                + b","
                + str(bar.close).encode("ascii")
                + b","
                + str(bar.amount).encode("ascii")
                + b","
                + str(bar.volume).encode("ascii")
                + b"\n"
            )
    return b"".join(parts)


class TdxOfflineStockProvider:
    """Drop-in TDX offline provider for the A-share stock daily-bars slice.

    The provider exposes the same structural port the Tushare
    :class:`StockTushareProvider` already implements, so the existing
    :func:`write_stock_daily_bars_raw` /
    :func:`write_stock_daily_bars_raw_by_trade_date` helpers can be
    driven by either source. The provider stamps
    :data:`PROVIDER_KEY` (``"tdx_offline"``) and
    :data:`DATASET_KEY` (``"stock_daily_bars"``) on every request
    so the persisted ``raw.provider_requests`` rows can be
    distinguished from the Tushare primary path by their logical
    key alone.

    The provider keeps an internal ``(symbol, exchange) → InstrumentId``
    placeholder cache so the application service can recover the
    audit :class:`BarSource` (and downstream ``core.instruments.id``
    resolution) via
    :meth:`symbol_and_exchange_for_instrument_id` — mirroring the
    Tushare adapter's reverse-lookup contract. The cache is scoped to
    one provider instance; the application service persists symbol and
    exchange in the sidecar and resolves the real instrument identity
    during upsert.
    """

    def __init__(
        self,
        settings: TdxOfflineSettings | None = None,
        *,
        symbols: Sequence[str] | None = None,
        clock: Any | None = None,
    ) -> None:
        self._settings = settings or TdxOfflineSettings()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ids: dict[tuple[str, str], InstrumentId] = {}
        for symbol in symbols or ():
            self._register_symbol(symbol)

    @property
    def provider_key(self) -> str:
        return PROVIDER_KEY

    @property
    def dataset_key(self) -> str:
        return DATASET_KEY

    def _register_symbol(self, symbol: str) -> None:
        market = _resolve_market(symbol)
        exchange = _market_to_exchange(market)
        self._ids.setdefault((symbol, exchange), InstrumentId.generate())

    def symbol_and_exchange_for_instrument_id(
        self, instrument_id: InstrumentId
    ) -> tuple[str, str] | None:
        for (symbol, exchange), value in self._ids.items():
            if value == instrument_id:
                return symbol, exchange
        return None

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None]:
        if not symbols:
            raise ValueError("symbols must not be empty")
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")

        request_id = uuid4()
        request = ProviderRequest(
            provider_key=PROVIDER_KEY,
            dataset_key=DATASET_KEY,
            request_key=_per_symbol_request_key(start_date, end_date, symbols),
            params={
                "symbols": list(symbols),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        return self._fetch(
            request=request,
            request_id=request_id,
            symbols=tuple(symbols),
            start_date=start_date,
            end_date=end_date,
        )

    def fetch_daily_bars_by_trade_date(
        self, trade_date: date
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None]:
        """Fetch every registered symbol's bar for ``trade_date`` from the offline root.

        The provider does **not** scan the operator's ``vipdoc`` tree
        to discover symbols: the universe must be supplied at
        construction time (or via :meth:`register_symbol`). When no
        symbols are registered the by-date path surfaces a
        :class:`ProviderAttemptStatus.FAILED` attempt with
        :attr:`error_code = "tdx_no_universe"` and an explanatory
        :attr:`error_message` so the operator can fix the upstream
        without us silently coercing the response.
        """

        if not self._ids:
            request = ProviderRequest(
                provider_key=PROVIDER_KEY,
                dataset_key=DATASET_KEY,
                request_key=_by_date_request_key(trade_date),
                params={"trade_date": trade_date.isoformat()},
            )
            attempt = self._fail_attempt(
                request_id=uuid4(),
                error_code=_TDX_NO_UNIVERSE_CODE,
                error_message=(
                    "TdxOfflineStockProvider.fetch_daily_bars_by_trade_date "
                    "requires a non-empty symbol universe; register the "
                    "caller's stock universe at construction time so the "
                    "adapter knows which .day files to read"
                ),
            )
            return request, attempt, None

        request_id = uuid4()
        request = ProviderRequest(
            provider_key=PROVIDER_KEY,
            dataset_key=DATASET_KEY,
            request_key=_by_date_request_key(trade_date),
            params={"trade_date": trade_date.isoformat()},
        )
        return self._fetch(
            request=request,
            request_id=request_id,
            symbols=tuple(sorted({symbol for symbol, _ in self._ids})),
            start_date=trade_date,
            end_date=trade_date,
        )

    def register_symbol(self, symbol: str) -> InstrumentId:
        """Register an additional symbol with the provider.

        Returns the freshly-allocated placeholder :class:`InstrumentId`
        so callers can correlate audit fields without re-asking the
        reverse lookup. Registering the same symbol twice is a no-op
        and returns the existing placeholder.
        """

        market = _resolve_market(symbol)
        exchange = _market_to_exchange(market)
        existing = self._ids.get((symbol, exchange))
        if existing is not None:
            return existing
        placeholder = InstrumentId.generate()
        self._ids[(symbol, exchange)] = placeholder
        return placeholder

    def _fetch(
        self,
        *,
        request: ProviderRequest,
        request_id: UUID,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None]:
        if not self._settings.enabled:
            attempt = self._fail_attempt(
                request_id=request_id,
                error_code=_TDX_DISABLED_CODE,
                error_message=(
                    "TdxOfflineStockProvider is disabled by default; "
                    "set INVEST_PIPELINE_TDX_OFFLINE_ENABLED=true "
                    "and the operator-managed data_root to read the offline .day files"
                ),
            )
            return request, attempt, None

        started_at = self._clock()
        bars_by_symbol: dict[tuple[str, str], tuple[TdxDailyBar, ...]] = {}
        first_error: tuple[str, str] | None = None

        for symbol in symbols:
            try:
                market = _resolve_market(symbol)
                bars = read_symbol(
                    self._settings.data_root,
                    market,
                    symbol,
                    start_date=_date_to_yyyymmdd(start_date),
                    end_date=_date_to_yyyymmdd(end_date),
                )
            except TdxOfflineError as exc:
                if first_error is None:
                    first_error = (
                        _TDX_ERROR_CODE_BY_EXCEPTION.get(type(exc), "tdx_unknown"),
                        str(exc),
                    )
                continue
            if not bars:
                continue
            if sum(len(records) for records in bars_by_symbol.values()) + len(bars) > (
                self._settings.record_cap
            ):
                finished_at = self._clock()
                attempt = self._fail_attempt(
                    request_id=request_id,
                    started_at=started_at,
                    finished_at=finished_at,
                    error_code=_TDX_RECORD_CAP_CODE,
                    error_message=(
                        f"offline read exceeds record_cap={self._settings.record_cap}; "
                        "raise TdxOfflineSettings.record_cap or narrow the symbol set"
                    ),
                )
                return request, attempt, None
            exchange = _market_to_exchange(market)
            bars_by_symbol[(symbol, exchange)] = bars
            self._ids.setdefault((symbol, exchange), InstrumentId.generate())

        finished_at = self._clock()

        if first_error is not None:
            error_code, error_message = first_error
            attempt = self._fail_attempt(
                request_id=request_id,
                started_at=started_at,
                finished_at=finished_at,
                error_code=error_code,
                error_message=error_message,
            )
            return request, attempt, None

        if not bars_by_symbol:
            return request, self._empty_attempt(request_id, started_at, finished_at), None

        batch_id = uuid4()
        records: list[DailyBar] = []
        for (symbol, exchange), bars in bars_by_symbol.items():
            placeholder = self._ids.setdefault((symbol, exchange), InstrumentId.generate())
            for bar in bars:
                records.append(
                    _bar_to_daily_bar(
                        bar=bar,
                        instrument_id=placeholder,
                        provider_key=PROVIDER_KEY,
                        source_batch_id=batch_id,
                        observed_at=finished_at,
                    )
                )

        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        attempt = ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
        raw_payload = _build_raw_payload(
            bars_by_symbol=bars_by_symbol,
            started_at=started_at,
            finished_at=finished_at,
        )
        batch = ProviderBatch[DailyBar](
            attempt_id=request_id,
            records=tuple(records),
            raw_payload_hash=_raw_payload_hash(raw_payload),
            warnings=(),
            status=ProviderBatchStatus.SUCCEEDED,
        )
        return request, attempt, batch

    def _empty_attempt(
        self, request_id: UUID, started_at: datetime, finished_at: datetime
    ) -> ProviderAttempt:
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        return ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    def _fail_attempt(
        self,
        *,
        request_id: UUID,
        error_code: str,
        error_message: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> ProviderAttempt:
        now = self._clock()
        begin = started_at or now
        end = finished_at or now
        duration_ms = max(0, int((end - begin).total_seconds() * 1000))
        return ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.FAILED,
            started_at=begin,
            finished_at=end,
            duration_ms=duration_ms,
            error_stage=ProviderFailureStage.STORAGE,
            error_code=error_code,
            error_message=error_message,
        )


__all__ = ["TdxOfflineStockProvider"]
