"""BaoStock runtime adapter (Slice-1 of PR-08).

Three-layer evidence tuple
``(ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None)``
composing :class:`BaostockClient` and the field mapper. Public API
accepts bare ETF symbols (``510300``/``159901``) and owns the
conversion to provider-native (``sh.``/``sz.``).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

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
        return self._run(request, symbols, native_symbols, start_date, end_date)

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

    def _guard_enabled(self) -> None:
        if not self._settings.enabled:
            raise RealProviderRequiresExplicitEnablementError(
                f"BaoStock fetch_daily_bars requires BaostockSettings.enabled=True "
                f"({PROVIDER_KEY!r}); see DATA-SOURCE-MIGRATION-MATRIX.md §6 / Slice-1 "
                "(PR-08)"
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
