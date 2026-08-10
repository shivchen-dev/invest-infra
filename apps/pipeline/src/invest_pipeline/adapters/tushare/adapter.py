"""Evidence-tuple adapter for Tushare ETF data."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import uuid4

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

from invest_pipeline.adapters.errors import (
    ProviderDataContractError,
    ProviderError,
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.adapters.tushare.client import TushareClient
from invest_pipeline.adapters.tushare.config import TushareSettings
from invest_pipeline.adapters.tushare.mapper import map_fund_basic, map_fund_daily
from invest_pipeline.request_keys import make_daily_bars_request_key

_KEY = "tushare"


class TushareInstrumentProvider:
    """Tushare adapter implementing V2's three-layer evidence contract."""

    def __init__(
        self,
        settings: TushareSettings | None = None,
        *,
        client: TushareClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings or TushareSettings()
        self._client = client or TushareClient(self._settings)
        self._owns_client = client is None
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ids: dict[tuple[str, str], InstrumentId] = {}

    @property
    def provider_key(self) -> str:
        return _KEY

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch_instruments(
        self, as_of: date
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[Instrument] | None]:
        request = ProviderRequest(
            _KEY,
            "etf_instruments",
            f"instruments-{as_of.isoformat()}",
            {"as_of": as_of.isoformat()},
            self._clock(),
        )
        return self._fetch(
            request,
            lambda: self._client.fetch_fund_basic(),
            lambda response, batch_id, observed: map_fund_basic(response),
        )

    def fetch_daily_bars(
        self, symbols: Sequence[str], start_date: date, end_date: date
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None]:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        request = ProviderRequest(
            _KEY,
            "etf_daily_bars",
            make_daily_bars_request_key(start_date, end_date, symbols),
            {
                "symbols": list(symbols),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            self._clock(),
        )

        def fetch_all():
            if not symbols:
                raise ValueError("symbols must not be empty")
            return [
                self._client.fetch_fund_daily(
                    ts_code=self._native_code(symbol),
                    start_date=start_date,
                    end_date=end_date,
                )
                for symbol in symbols
            ]

        def map_response(responses, batch_id, observed):
            bars: list[DailyBar] = []
            warnings: list[str] = []
            for response in responses:
                mapped, row_warnings = map_fund_daily(
                    response,
                    source_batch_id=batch_id,
                    observed_at=observed,
                    instrument_id_resolver=self._resolve_id,
                )
                bars.extend(mapped)
                warnings.extend(row_warnings)
            return tuple(bars), tuple(warnings)

        return self._fetch(
            request,
            fetch_all,
            map_response,
        )

    @staticmethod
    def _native_code(symbol: str) -> str:
        if "." in symbol:
            return symbol
        return f"{symbol}.SH" if symbol.startswith(("5", "6")) else f"{symbol}.SZ"

    def _resolve_id(self, symbol: str, exchange: str) -> InstrumentId:
        return self._ids.setdefault((symbol, exchange), InstrumentId.generate())

    def _fetch(self, request: ProviderRequest, fetch: Callable, mapper: Callable):
        request_id = uuid4()
        started = self._clock()
        if not self._settings.enabled:
            raise RealProviderRequiresExplicitEnablementError(
                "tushare provider requires TushareSettings.enabled=True "
                "(INVEST_PIPELINE_TUSHARE_ENABLED)"
            )
        try:
            response = fetch()
            batch_id = uuid4()
            mapped = mapper(response, batch_id, started)
            records, warnings = mapped
            finished = self._clock()
            attempt = ProviderAttempt(
                request_id,
                1,
                ProviderAttemptStatus.SUCCEEDED,
                started,
                finished,
                max(0, int((finished - started).total_seconds() * 1000)),
            )
            payload = (
                [item.raw_payload for item in response]
                if isinstance(response, list)
                else response.raw_payload
            )
            digest = sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                .encode()
            ).hexdigest()
            return (
                request,
                attempt,
                ProviderBatch(batch_id, records, digest, warnings, ProviderBatchStatus.SUCCEEDED),
            )
        except (ProviderError, ValueError) as exc:
            finished = self._clock()
            stage = (
                ProviderFailureStage.CONTRACT
                if isinstance(exc, (ProviderDataContractError, ValueError))
                else ProviderFailureStage.PROVIDER
            )
            attempt = ProviderAttempt(
                request_id,
                1,
                ProviderAttemptStatus.FAILED,
                started,
                finished,
                max(0, int((finished - started).total_seconds() * 1000)),
                stage,
                type(exc).__name__,
                str(exc),
            )
            return request, attempt, None

    def symbol_for_instrument_id(self, instrument_id: InstrumentId) -> str | None:
        for (symbol, _), value in self._ids.items():
            if value == instrument_id:
                return symbol
        return None

    def symbol_and_exchange_for_instrument_id(
        self, instrument_id: InstrumentId
    ) -> tuple[str, str] | None:
        """Return ``(symbol, exchange)`` whose placeholder UUID matches ``instrument_id``.

        Mirrors :meth:`symbol_for_instrument_id` but also surfaces the
        SSE / SZSE exchange the bar was fetched under so the daily-bars
        application service can resolve the real ``core.instruments.id``
        without inferring the exchange from the symbol prefix (stock
        symbols span more than one exchange prefix). Returns ``None``
        when the UUID was not generated by this adapter instance — that
        indicates a placeholder leak and the service surfaces it as a
        hard error rather than silently coercing the exchange.
        """

        for (symbol, exchange), value in self._ids.items():
            if value == instrument_id:
                return symbol, exchange
        return None


__all__ = ["TushareInstrumentProvider"]
