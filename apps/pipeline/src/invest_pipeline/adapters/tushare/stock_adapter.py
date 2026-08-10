"""Tushare A-share stock provider; kept separate from the ETF provider."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from invest_domain.market_data.models import DailyBar, ProviderRequest

from invest_pipeline.adapters.tushare.adapter import TushareInstrumentProvider
from invest_pipeline.adapters.tushare.mapper import map_stock_basic, map_stock_daily


class StockTushareProvider(TushareInstrumentProvider):
    """Evidence-tuple provider for A-share master data and daily bars."""

    def fetch_instruments(self, as_of: date):
        request = ProviderRequest(
            "tushare", "stock_instruments", f"instruments-{as_of.isoformat()}",
            {"as_of": as_of.isoformat()}, self._clock()
        )
        return self._fetch(
            request, self._client.fetch_stock_basic,
            lambda response, batch_id, observed: map_stock_basic(response),
        )

    def fetch_daily_bars(self, symbols: Sequence[str], start_date: date, end_date: date):
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        request = ProviderRequest(
            "tushare", "stock_daily_bars", self._daily_key(start_date, end_date, symbols),
            {"symbols": list(symbols), "start_date": start_date.isoformat(),
             "end_date": end_date.isoformat()}, self._clock()
        )

        def fetch_all():
            if not symbols:
                raise ValueError("symbols must not be empty")
            return [
                self._client.fetch_stock_daily(
                    ts_code=self._native_code(symbol), start_date=start_date, end_date=end_date
                )
                for symbol in symbols
            ]

        def map_all(responses, batch_id, observed):
            bars: list[DailyBar] = []
            warnings: list[str] = []
            for response in responses:
                mapped, row_warnings = map_stock_daily(
                    response, source_batch_id=batch_id, observed_at=observed,
                    instrument_id_resolver=self._resolve_id,
                )
                bars.extend(mapped)
                warnings.extend(row_warnings)
            return tuple(bars), tuple(warnings)

        return self._fetch(request, fetch_all, map_all)

    @staticmethod
    def _daily_key(start_date: date, end_date: date, symbols: Sequence[str]) -> str:
        from invest_pipeline.request_keys import make_daily_bars_request_key
        return make_daily_bars_request_key(start_date, end_date, symbols)


__all__ = ["StockTushareProvider"]
