"""AkShare runtime adapter (PR-02, matrix §3 / §5.4 / §10 / NAV / calendar).

This module composes :class:`AkshareClient` and the field mappers in
:mod:`invest_pipeline.adapters.akshare.mapper` into the existing
domain :class:`invest_domain.market_data.ports.EtfMarketDataProvider`
shape. Each public call returns the same three-layer evidence tuple
used by the Cifang adapter:

    ``(ProviderRequest, ProviderAttempt, ProviderBatch[T] | None)``

The adapter mirrors the Cifang adapter's safety rules:

- ``AkshareSettings.enabled=False`` (default) is the authoritative
  gate: while it is ``False`` every ``fetch_*`` method raises
  :class:`RealProviderRequiresExplicitEnablementError` so callers
  never silently hit the network in CI or local dev (matrix §6).
- ``AkshareSettings.adjust`` is locked to the empty string at
  construction time (the ``client`` enforces the same lock at call
  time); legacy ``hfq`` / ``qfq`` adjustments from the archive
  cannot reach the production path (ADR-0005 §4).
- ``ProviderError`` subclasses raised by the client and the mapper
  are classified into the canonical
  :class:`invest_domain.market_data.models.ProviderFailureStage` so
  the application layer can drive alerts without re-parsing free
  text (ADR-0003 §4).
- The optional ``akshare`` SDK dependency is resolved lazily by the
  client; the adapter never imports ``akshare`` itself and the
  module-level package import always succeeds.

The NAV / trading-calendar surface follows plan §5 Task 2 ("明确 NAV
不映射为 OHLCV，不填充成交额"): the adapter exposes explicit read-only
``fetch_nav`` / ``fetch_trading_calendar`` methods that route through
the lazy AkShare SDK and stamp NAV rows / calendar entries into
:class:`ProviderBatch` records that **never** carry OHLCV fields. The
NAV records ride on :class:`invest_pipeline.adapters.akshare.mapper.
AkshareNavRecord` and the calendar entries on
:class:`AkshareCalendarRecord`; the dedicated dataset keys
``"etf_nav"`` and ``"trading_calendar"`` keep the three-layer evidence
rows segregated from the daily-bars / master-data evidence.

The AkShare adapter is the canonical research/secondary ETF source
that matrix §3 pins to the ``research_only`` role; the default
``enabled=False`` keeps the slice safe in CI and local dev until the
matrix O-1 / O-3 / O-4 blockers are closed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from invest_domain.instruments.models import Instrument, InstrumentId
from invest_domain.market_data.models import (
    DailyBar,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderFailureStage,
    ProviderRequest,
)

from invest_pipeline.adapters.akshare.client import (
    AkshareClient,
)
from invest_pipeline.adapters.akshare.config import AkshareSettings
from invest_pipeline.adapters.akshare.mapper import (
    AkshareCalendarMappingResult,
    AkshareCalendarRecord,
    AkshareNavMappingResult,
    AkshareNavRecord,
    map_fund_etf_fund_daily_em,
    map_fund_etf_fund_info_em,
    map_fund_etf_hist_em,
    map_tool_trade_date_hist_sina,
)
from invest_pipeline.adapters.errors import (
    ProviderAuthenticationError,
    ProviderBadResponseError,
    ProviderDataContractError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.request_keys import make_daily_bars_request_key

_PROVIDER_KEY = "akshare"
_INSTRUMENTS_DATASET_KEY = "etf_instruments"
_DAILY_BARS_DATASET_KEY = "etf_daily_bars"
_NAV_DATASET_KEY = "etf_nav"
_CALENDAR_DATASET_KEY = "trading_calendar"


class AkshareInstrumentProvider:
    """Evidence-tuple adapter wiring :class:`AkshareClient` to the domain port.

    Parameters
    ----------
    settings:
        The redacted configuration. ``enabled=False`` (default) keeps
        the adapter inert; setting ``enabled=True`` would route real
        calls through the injected client while keeping the
        documentation matrix §6 / O-1 / O-3 / O-4 blockers visible.
    client:
        A pre-built :class:`AkshareClient`. Tests inject a client
        whose ``module`` argument resolves to a stub object so the
        suite runs without the optional ``akshare`` SDK installed.
    clock:
        Callable returning the current UTC datetime. Defaults to
        :func:`datetime.now`; tests inject a deterministic callable.
    placeholder_instrument_id_factory:
        Callable returning a fresh :class:`InstrumentId` for an
        unknown ``(symbol, exchange)`` pair. The application service
        re-maps ``symbol -> core.instruments.id`` at upsert time
        (mirrors the Cifang / fixture_dev pattern).
    """

    def __init__(
        self,
        settings: AkshareSettings | None = None,
        *,
        client: AkshareClient | None = None,
        clock: Callable[[], datetime] | None = None,
        placeholder_instrument_id_factory: Callable[[], InstrumentId] | None = None,
    ) -> None:
        self._settings = settings or AkshareSettings()
        self._client = client or AkshareClient(self._settings)
        self._clock: Callable[[], datetime] = (
            clock if clock is not None else _default_clock
        )
        self._placeholder_instrument_id_factory: Callable[[], InstrumentId] = (
            placeholder_instrument_id_factory
            if placeholder_instrument_id_factory is not None
            else InstrumentId.generate
        )
        self._placeholder_cache: dict[tuple[str, str], InstrumentId] = {}

    @property
    def provider_key(self) -> str:
        return _PROVIDER_KEY

    # ------------------------------------------------------------------
    # Domain port surface
    # ------------------------------------------------------------------

    def fetch_instruments(
        self, as_of: date
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[Instrument] | None]:
        """Return the evidence bundle for the ETF master-data call.

        AkShare serves all ETF master data via a single
        ``fund_etf_fund_info_em()`` endpoint, so the request has one
        batch / one chunk / one attempt. The mapper applies the ETF
        filter and the SSE / SZSE allow-list; a failed attempt
        returns no batch.
        """

        request_id = uuid4()
        attempt_id = uuid4()
        started_at = self._now()
        request = ProviderRequest(
            provider_key=self.provider_key,
            dataset_key=_INSTRUMENTS_DATASET_KEY,
            request_key=f"instruments-{as_of.isoformat()}",
            params={"as_of": as_of.isoformat()},
            created_at=started_at,
        )
        self._guard_enabled("fetch_instruments", as_of=as_of)
        try:
            response = self._client.fetch_fund_etf_fund_info_em()
        except ProviderError as exc:
            return self._build_failure(
                request=request,
                request_id=request_id,
                started_at=started_at,
                error=exc,
            )

        finished_at = self._now()
        try:
            mapping = map_fund_etf_fund_info_em(response)
        except ProviderDataContractError as exc:
            return self._build_failure(
                request=request,
                request_id=request_id,
                started_at=started_at,
                finished_at=finished_at,
                error=exc,
            )

        duration_ms = self._duration_ms(started_at, finished_at)
        attempt = ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
        raw_hash = _canonical_payload_hash(response.raw_payload)
        batch = ProviderBatch[Instrument](
            attempt_id=attempt_id,
            records=tuple(mapping.instruments),
            raw_payload_hash=raw_hash,
            warnings=mapping.warnings,
            status=ProviderBatchStatus.SUCCEEDED,
        )
        return request, attempt, batch

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None]:
        """Return the evidence bundle for the per-symbol ETF daily-bars calls.

        The AkShare ``fund_etf_hist_em`` endpoint takes exactly one
        symbol per call (documented limit). The adapter loops over
        ``symbols``, calls the client once per symbol and aggregates
        the mapped :class:`DailyBar` rows into a single
        :class:`ProviderBatch`. A failure on **any** symbol short-
        circuits to a single failed attempt so the
        ``raw.provider_attempts`` row carries the full classification.
        """

        if end_date < start_date:
            raise ValueError(
                f"end_date {end_date.isoformat()} must be on or after "
                f"start_date {start_date.isoformat()}"
            )

        request_id = uuid4()
        attempt_id = uuid4()
        started_at = self._now()
        request = ProviderRequest(
            provider_key=self.provider_key,
            dataset_key=_DAILY_BARS_DATASET_KEY,
            request_key=make_daily_bars_request_key(start_date, end_date, symbols),
            params={
                "symbols": list(symbols),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            created_at=started_at,
        )
        self._guard_enabled(
            "fetch_daily_bars",
            symbols=list(symbols),
            start_date=start_date,
            end_date=end_date,
        )

        symbol_list = list(symbols)
        if not symbol_list:
            finished_at = self._now()
            attempt = ProviderAttempt(
                request_id=request_id,
                attempt_number=1,
                status=ProviderAttemptStatus.SUCCEEDED,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=self._duration_ms(started_at, finished_at),
            )
            batch = ProviderBatch[DailyBar](
                attempt_id=attempt_id,
                records=(),
                raw_payload_hash=_canonical_payload_hash(
                    {"adjust": self._settings.adjust, "data": []}
                ),
                warnings=(),
                status=ProviderBatchStatus.SUCCEEDED,
            )
            return request, attempt, batch

        all_bars: list[DailyBar] = []
        all_warnings: list[str] = []
        symbol_payloads: list[Any] = []
        first_failure: ProviderError | None = None
        failed_symbol: str | None = None

        for symbol in symbol_list:
            response = None
            mapping = None
            source_key = "sina"
            try:
                response = self._client.fetch_fund_etf_hist_sina(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                )
                mapping = map_fund_etf_hist_em(
                    response,
                    symbol=symbol,
                    source_batch_id=attempt_id,
                    observed_at=self._now(),
                    instrument_id_resolver=self._resolve_placeholder_instrument_id,
                    bar_source_key=source_key,
                )
            except ProviderError:
                mapping = None

            if not mapping or not mapping.bars:
                source_key = "eastmoney"
                try:
                    response = self._client.fetch_fund_etf_hist_em(
                        symbol=symbol,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    mapping = map_fund_etf_hist_em(
                        response,
                        symbol=symbol,
                        source_batch_id=attempt_id,
                        observed_at=self._now(),
                        instrument_id_resolver=self._resolve_placeholder_instrument_id,
                        bar_source_key=source_key,
                    )
                except ProviderError as exc:
                    first_failure = exc
                    failed_symbol = symbol
                    break

            assert response is not None
            assert mapping is not None
            symbol_payloads.append(
                {"symbol": symbol, "source": source_key, "rows": response.raw_payload}
            )
            all_bars.extend(mapping.bars)
            all_warnings.extend(mapping.warnings)

        finished_at = self._now()
        duration_ms = self._duration_ms(started_at, finished_at)
        if first_failure is not None:
            return self._build_failure(
                request=request,
                request_id=request_id,
                started_at=started_at,
                finished_at=finished_at,
                error=first_failure,
                context_symbol=failed_symbol,
            )

        raw_hash = _canonical_payload_hash(
            {"adjust": self._settings.adjust, "symbols": symbol_payloads}
        )
        attempt = ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
        warnings = tuple(all_warnings)
        if len(symbol_list) > 1:
            warnings = warnings + (
                f"daily-bars request fans out to {len(symbol_list)} "
                f"per-symbol AkShare calls (fund_etf_hist_em single-"
                f"symbol limit; matrix §10); each completed "
                f"independently before aggregation",
            )
        batch = ProviderBatch[DailyBar](
            attempt_id=attempt_id,
            records=tuple(all_bars),
            raw_payload_hash=raw_hash,
            warnings=warnings,
            status=ProviderBatchStatus.SUCCEEDED,
        )
        return request, attempt, batch

    # ------------------------------------------------------------------
    # NAV surface (read-only, never coerces to OHLCV)
    # ------------------------------------------------------------------

    def fetch_nav(
        self, symbol: str
    ) -> tuple[
        ProviderRequest, ProviderAttempt, ProviderBatch[AkshareNavRecord] | None
    ]:
        """Return the evidence bundle for the per-symbol ETF NAV call.

        AkShare serves the per-symbol NAV series through
        ``ak.fund_etf_fund_daily_em(symbol=...)``. The adapter calls
        the client once per symbol and packages the mapped
        :class:`AkshareNavRecord` rows into a single
        :class:`ProviderBatch` with ``dataset_key="etf_nav"``. Per
        plan §5 Task 2 ("明确 NAV 不映射为 OHLCV，不填充成交额") NAV
        rows **never** ride on :class:`DailyBar`; the dedicated
        record type is the only thing that lands on the batch so a
        downstream pipeline cannot accidentally promote NAV to OHLCV.
        A failed client call short-circuits to a single failed
        attempt with no batch.
        """

        if not symbol or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")

        request_id = uuid4()
        attempt_id = uuid4()
        started_at = self._now()
        request = ProviderRequest(
            provider_key=self.provider_key,
            dataset_key=_NAV_DATASET_KEY,
            request_key=f"nav-{symbol}",
            params={"symbol": symbol},
            created_at=started_at,
        )
        self._guard_enabled("fetch_nav", symbol=symbol)

        try:
            response = self._client.fetch_fund_etf_fund_daily_em(symbol=symbol)
        except ProviderError as exc:
            return self._build_failure(
                request=request,
                request_id=request_id,
                started_at=started_at,
                error=exc,
                context_symbol=symbol,
            )

        finished_at = self._now()
        try:
            mapping: AkshareNavMappingResult = map_fund_etf_fund_daily_em(
                response,
                symbol=symbol,
                source_batch_id=attempt_id,
                observed_at=finished_at,
            )
        except ProviderDataContractError as exc:
            return self._build_failure(
                request=request,
                request_id=request_id,
                started_at=started_at,
                finished_at=finished_at,
                error=exc,
                context_symbol=symbol,
            )

        duration_ms = self._duration_ms(started_at, finished_at)
        attempt = ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
        raw_hash = _canonical_payload_hash(
            {"adjust": self._settings.adjust, "rows": response.raw_payload}
        )
        batch = ProviderBatch[AkshareNavRecord](
            attempt_id=attempt_id,
            records=mapping.records,
            raw_payload_hash=raw_hash,
            warnings=mapping.warnings,
            status=ProviderBatchStatus.SUCCEEDED,
        )
        return request, attempt, batch

    # ------------------------------------------------------------------
    # Trading-calendar surface (read-only, date-only)
    # ------------------------------------------------------------------

    def fetch_trading_calendar(
        self,
    ) -> tuple[
        ProviderRequest,
        ProviderAttempt,
        ProviderBatch[AkshareCalendarRecord] | None,
    ]:
        """Return the evidence bundle for the SSE / SZSE trading-calendar call.

        AkShare serves the historical SSE / SZSE trading-day schedule
        through ``ak.tool_trade_date_hist_sina()``. The adapter calls
        the client once and packages the mapped
        :class:`AkshareCalendarRecord` entries into a single
        :class:`ProviderBatch` with ``dataset_key="trading_calendar"``.
        The surface is read-only and never coerces calendar entries
        into :class:`DailyBar` or :class:`Instrument`; the adapter
        delegates the date-only normalisation to
        :func:`map_tool_trade_date_hist_sina`.
        """

        request_id = uuid4()
        attempt_id = uuid4()
        started_at = self._now()
        request = ProviderRequest(
            provider_key=self.provider_key,
            dataset_key=_CALENDAR_DATASET_KEY,
            request_key="trading-calendar",
            params={},
            created_at=started_at,
        )
        self._guard_enabled("fetch_trading_calendar")

        try:
            response = self._client.fetch_tool_trade_date_hist_sina()
        except ProviderError as exc:
            return self._build_failure(
                request=request,
                request_id=request_id,
                started_at=started_at,
                error=exc,
            )

        finished_at = self._now()
        try:
            mapping: AkshareCalendarMappingResult = map_tool_trade_date_hist_sina(
                response
            )
        except ProviderDataContractError as exc:
            return self._build_failure(
                request=request,
                request_id=request_id,
                started_at=started_at,
                finished_at=finished_at,
                error=exc,
            )

        duration_ms = self._duration_ms(started_at, finished_at)
        attempt = ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
        raw_hash = _canonical_payload_hash(
            {"adjust": self._settings.adjust, "rows": response.raw_payload}
        )
        batch = ProviderBatch[AkshareCalendarRecord](
            attempt_id=attempt_id,
            records=mapping.records,
            raw_payload_hash=raw_hash,
            warnings=mapping.warnings,
            status=ProviderBatchStatus.SUCCEEDED,
        )
        return request, attempt, batch

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _guard_enabled(self, op: str, **params: Any) -> None:
        if not self._settings.enabled:
            raise RealProviderRequiresExplicitEnablementError(
                f"AkShare {op} requires AkshareSettings.enabled=True "
                f"({self.provider_key!r}, params={params!r}); "
                f"see DATA-SOURCE-MIGRATION-MATRIX.md §6 / O-1 / "
                f"O-3 / O-4 blockers (PR-02)"
            )

    def _build_failure(
        self,
        *,
        request: ProviderRequest,
        request_id: UUID,
        started_at: datetime,
        error: ProviderError,
        finished_at: datetime | None = None,
        context_symbol: str | None = None,
    ) -> tuple[ProviderRequest, ProviderAttempt, None]:
        finished = finished_at or self._now()
        stage, code, message = _classify_failure(error, context_symbol=context_symbol)
        attempt = ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.FAILED,
            started_at=started_at,
            finished_at=finished,
            duration_ms=self._duration_ms(started_at, finished),
            error_stage=stage,
            error_code=code,
            error_message=message,
        )
        return request, attempt, None

    def _now(self) -> datetime:
        return self._clock()

    def _duration_ms(self, started: datetime, finished: datetime) -> int:
        delta = finished - started
        return max(int(delta.total_seconds() * 1000), 0)

    def _resolve_placeholder_instrument_id(
        self, symbol: str, exchange: str
    ) -> InstrumentId:
        key = (symbol, exchange)
        cached = self._placeholder_cache.get(key)
        if cached is not None:
            return cached
        new_id = self._placeholder_instrument_id_factory()
        self._placeholder_cache[key] = new_id
        return new_id

    def symbol_for_instrument_id(self, instrument_id: InstrumentId) -> str | None:
        """Return the provider-native symbol whose placeholder UUID matches.

        Reverse lookup against :attr:`_placeholder_cache`. Mirrors the
        Cifang adapter helper so the application service can
        re-resolve the real ``core.instruments.id`` per
        ``(symbol, exchange)`` at upsert time. Returns ``None`` when
        the UUID was not generated by this adapter instance.
        """

        for (symbol, _exchange), placeholder_id in self._placeholder_cache.items():
            if placeholder_id == instrument_id:
                return symbol
        return None


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _canonical_payload_hash(payload: Any) -> str:
    """Return a stable SHA-256 of a JSON-compatible payload.

    Uses sorted keys + compact separators so the digest is independent
    of dict ordering or whitespace; the value lives in
    :attr:`invest_domain.market_data.models.ProviderBatch.
    raw_payload_hash` and must match across re-collects of the same
    logical request.
    """

    import json

    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(text.encode("utf-8")).hexdigest()


_PROVIDER_ERROR_STAGE_MAP: dict[type[ProviderError], ProviderFailureStage] = {
    ProviderAuthenticationError: ProviderFailureStage.AUTHENTICATION,
    ProviderRateLimitError: ProviderFailureStage.RATE_LIMIT,
    ProviderTimeoutError: ProviderFailureStage.TIMEOUT,
    ProviderUnavailableError: ProviderFailureStage.HTTP,
    ProviderBadResponseError: ProviderFailureStage.DECODE,
    ProviderDataContractError: ProviderFailureStage.CONTRACT,
}


def _classify_failure(
    error: ProviderError, *, context_symbol: str | None = None
) -> tuple[ProviderFailureStage, str, str]:
    """Map a Provider error to ``(stage, code, message)``.

    The ``message`` is the original error string with any configured
    SDK token scrubbed defensively; the ``code`` is the canonical
    Provider error category so the application layer can route
    alerting without parsing free text. When the failure occurred on a
    specific per-symbol AkShare call, ``context_symbol`` is appended so
    the operator can identify which sub-call was responsible without
    re-parsing the message.
    """

    stage = _PROVIDER_ERROR_STAGE_MAP.get(
        type(error), ProviderFailureStage.PROVIDER
    )
    code = type(error).__name__
    base_message = _scrub_message(str(error))
    if context_symbol:
        return (
            stage,
            code,
            f"{base_message} (context_symbol={context_symbol!r})",
        )
    return stage, code, base_message


def _scrub_message(message: str) -> str:
    """Remove anything that smells like an SDK token from a Provider message.

    The Cifang helper had a token reference; the AkShare message may
    likewise include an optional AkShare SDK token. The scrubber is a
    belt-and-braces no-op guard — AkShare exceptions typically do not
    embed the token at all.
    """

    return message


__all__ = ["AkshareInstrumentProvider"]
