"""BaoStock runtime adapter (Slice-1 of PR-08).

Three-layer evidence tuple
``(ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None)``
composing :class:`BaostockClient` and the field mapper. Public API
accepts bare ETF symbols (``510300``/``159901``) and owns the
conversion to provider-native (``sh.``/``sz.``).
"""

from __future__ import annotations

import re
import uuid as _uuid
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
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

from invest_pipeline.adapters.baostock.client import BaostockClient
from invest_pipeline.adapters.baostock.config import BaostockSettings
from invest_pipeline.adapters.baostock.mapper import map_query_history_k_data_plus
from invest_pipeline.adapters.errors import (
    ProviderBadResponseError,
    ProviderDataContractError,
    ProviderError,
    ProviderUnavailableError,
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.request_keys import make_daily_bars_request_key

PROVIDER_KEY = "baostock"
DATASET_KEY = "etf_daily_bars"

_BARE_SYMBOL_RE = re.compile(r"^\d{6}$")
_BARE_TO_NATIVE_PREFIX = {"5": "sh.", "1": "sz."}
_NATIVE_PREFIX_TO_EXCHANGE = {"sh": "SSE", "sz": "SZSE"}

_ERROR_STAGE: dict[type[ProviderError], ProviderFailureStage] = {
    ProviderUnavailableError: ProviderFailureStage.HTTP,
    ProviderBadResponseError: ProviderFailureStage.DECODE,
    ProviderDataContractError: ProviderFailureStage.CONTRACT,
}


class BaostockEtfDailyBarsAdapter:
    """Evidence-tuple adapter wiring :class:`BaostockClient` to the domain port."""

    def __init__(
        self,
        settings: BaostockSettings | None = None,
        *,
        client: BaostockClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings or BaostockSettings()
        self._client = client or BaostockClient(self._settings)
        self._clock = clock or (lambda: datetime.now(UTC))
        # Placeholder ``InstrumentId`` cache seeded at fetch time. Keyed by
        # the deterministic UUID5 the mapper will mint for each
        # ``(native_symbol, exchange)`` pair; the value is the bare
        # six-digit symbol the caller originally requested, so the
        # application service can recover the Provider-facing business
        # key from a returned ``DailyBar.instrument_id`` without
        # re-running the SDK. Backwards-compatible: the mapper's UUID5
        # derivation is mirrored verbatim here so existing
        # ``raw_payload_hash`` / ``row_hash`` outputs are unaffected.
        self._placeholder_cache: dict[InstrumentId, str] = {}

    @property
    def provider_key(self) -> str:
        return PROVIDER_KEY

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: Any,
        end_date: Any,
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None]:
        if not symbols:
            raise ValueError("symbols must be a non-empty sequence")
        if end_date < start_date:
            raise ValueError(
                f"end_date {end_date.isoformat()} must be on or after "
                f"start_date {start_date.isoformat()}"
            )
        native_symbols = [_to_native(c) for c in symbols]
        bare_sorted = sorted(symbols)

        request = ProviderRequest(
            provider_key=PROVIDER_KEY,
            dataset_key=DATASET_KEY,
            request_key=make_daily_bars_request_key(start_date, end_date, bare_sorted),
            params={
                "symbols": list(symbols),
                "provider_native_symbols": native_symbols,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "adjustflag": self._settings.adjustflag,
            },
            created_at=self._now(),
        )
        self._guard_enabled()
        self._guard_window(start_date)
        return self._run(request, symbols, native_symbols, start_date, end_date)

    def symbol_for_instrument_id(self, instrument_id: InstrumentId) -> str | None:
        """Return the requested bare six-digit symbol for a fetched ``InstrumentId``.

        Mirrors :meth:`AkshareInstrumentProvider.symbol_for_instrument_id`
        so the application service can recover the Provider-facing
        business key from a returned ``DailyBar.instrument_id``. Returns
        ``None`` when ``instrument_id`` was not produced by this adapter
        instance — the application service surfaces that as a hard
        ``LookupError`` rather than silently coercing an audit field.
        """

        return self._placeholder_cache.get(instrument_id)

    # internal ------------------------------------------------------------

    def _run(
        self,
        request: ProviderRequest,
        bare_symbols: Sequence[str],
        native_symbols: list[str],
        start_date: Any,
        end_date: Any,
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None]:
        started_at = request.created_at
        attempt_id = uuid4()
        request_id = uuid4()
        try:
            response = self._client.fetch_etf_daily_bars(
                symbols=native_symbols, start_date=start_date, end_date=end_date,
            )
        except ProviderError as exc:
            return _failure(
                request, request_id, started_at, attempt_id, exc, self._now(),
            )

        finished_at = self._now()
        source = BarSource(
            provider_key=PROVIDER_KEY,
            source_batch_id=attempt_id,
            observed_at=finished_at,
        )
        try:
            mapping = map_query_history_k_data_plus(
                response, symbols=native_symbols, source=source,
            )
        except ProviderDataContractError as exc:
            return _failure(
                request, request_id, started_at, attempt_id, exc, finished_at,
            )

        # Seed the placeholder cache now that we know the SDK returned
        # at least one row per requested symbol (the client enforces the
        # EMPTY_SYMBOL_PAYLOAD / EMPTY_REQUIRED_PAYLOAD contract). The
        # mapper's UUID5 derivation is mirrored here so existing bar
        # hashes are unaffected.
        for bare, native in zip(bare_symbols, native_symbols, strict=True):
            self._track_placeholder(bare, native)

        attempt = ProviderAttempt(
            request_id=request_id, attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=started_at, finished_at=finished_at,
            duration_ms=_duration_ms(started_at, finished_at),
        )
        batch = ProviderBatch[DailyBar](
            attempt_id=attempt_id, records=mapping.bars,
            raw_payload_hash=response.raw_payload_hash,
            warnings=mapping.warnings,
            status=ProviderBatchStatus.SUCCEEDED,
        )
        return request, attempt, batch

    def _track_placeholder(self, bare_symbol: str, native_symbol: str) -> None:
        """Record the mapper-minted placeholder UUID for ``bare_symbol``."""

        exchange = _native_to_exchange(native_symbol)
        digest_seed = f"{PROVIDER_KEY}|{native_symbol}|{exchange}".encode()
        placeholder_id = InstrumentId(_uuid.uuid5(_uuid.NAMESPACE_DNS, digest_seed.hex()))
        self._placeholder_cache[placeholder_id] = bare_symbol

    def _guard_enabled(self) -> None:
        if not self._settings.enabled:
            raise RealProviderRequiresExplicitEnablementError(
                f"BaoStock fetch_daily_bars requires BaostockSettings.enabled=True "
                f"({PROVIDER_KEY!r}); see DATA-SOURCE-MIGRATION-MATRIX.md §6 / Slice-1 "
                "(PR-08)"
            )

    def _guard_window(self, start_date: Any) -> None:
        """Reject requests whose window exceeds ``settings.max_history_days``.

        Fail closed **before** SDK invocation so a misconfigured
        consumer never silently causes a slow historical backfill;
        ``WINDOW_OUT_OF_RANGE`` is the contract code the application
        service routes against. ``start_date`` is the user's date; the
        upper bound is the injected clock's calendar day so tests stay
        deterministic.
        """

        max_days = self._settings.max_history_days
        today = self._now().date()
        span_days = (today - start_date).days if isinstance(start_date, date) else None
        if span_days is None or span_days > max_days:
            start_iso = (
                start_date.isoformat()
                if hasattr(start_date, "isoformat") else repr(start_date)
            )
            raise ProviderDataContractError(
                "WINDOW_OUT_OF_RANGE",
                (
                    f"start_date {start_iso} is more than {max_days} days before "
                    f"the injected clock date {today.isoformat()} "
                    f"(span={span_days}d); BaostockSettings.max_history_days={max_days}"
                ),
                provider_key=PROVIDER_KEY,
            )

    def _now(self) -> datetime:
        return self._clock()


# module-level helpers --------------------------------------------------


def _to_native(code: str) -> str:
    """Convert bare 6-digit code to ``sh.``/``sz.`` form (fail-closed pre-SDK)."""
    if not isinstance(code, str) or not _BARE_SYMBOL_RE.match(code):
        raise ValueError(
            f"unsupported baostock symbol {code!r}; expected 6 digits"
        )
    prefix = _BARE_TO_NATIVE_PREFIX.get(code[:1])
    if prefix is None:
        raise ValueError(
            f"unsupported baostock symbol {code!r}; prefix {code[:1]!r} "
            f"is not SSE ('5') or SZSE ('1')"
        )
    return prefix + code


def _native_to_exchange(native_symbol: str) -> str:
    """Derive SSE/SZSE exchange from the native prefix (mirrors the mapper)."""
    prefix = native_symbol.split(".", 1)[0].lower()
    exchange = _NATIVE_PREFIX_TO_EXCHANGE.get(prefix)
    if exchange is None:
        raise ValueError(
            f"native baostock symbol {native_symbol!r} has no SSE/SZSE "
            f"prefix; expected 'sh.'/'sz.'"
        )
    return exchange


def _duration_ms(started: datetime, finished: datetime) -> int:
    return max(int((finished - started).total_seconds() * 1000), 0)


def _failure(
    request: ProviderRequest,
    request_id: UUID,
    started_at: datetime,
    attempt_id: UUID,
    error: ProviderError,
    finished_at: datetime,
) -> tuple[ProviderRequest, ProviderAttempt, None]:
    finished = finished_at
    attempt = ProviderAttempt(
        request_id=request_id, attempt_number=1,
        status=ProviderAttemptStatus.FAILED,
        started_at=started_at, finished_at=finished,
        duration_ms=_duration_ms(started_at, finished),
        error_stage=_ERROR_STAGE.get(type(error), ProviderFailureStage.PROVIDER),
        error_code=type(error).__name__,
        error_message=str(error),
    )
    return request, attempt, None


__all__ = ["BaostockEtfDailyBarsAdapter", "DATASET_KEY", "PROVIDER_KEY"]