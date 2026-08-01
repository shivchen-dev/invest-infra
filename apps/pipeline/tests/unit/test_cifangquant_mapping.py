"""Offline unit tests for the CifangQuant field mappers (ADR-0011).

The mappers are pure functions over a :class:`CifangResponse`; no
network, no httpx. The tests cover:

- ETF scope and ``SH`` / ``SZ`` → ``SSE`` / ``SZSE`` mapping.
- Nullable ``prev_close`` / ``amount`` (ADR-0005 §3 / ADR-0011 §2).
- Missing / partial / malformed rows downgrade to warnings.
- Non-``none`` adjustment responses are rejected outright.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid4

from invest_domain.instruments.models import Instrument, InstrumentId, InstrumentType
from invest_domain.market_data.models import DailyBar
from invest_domain.market_data.values import Adjust, Currency, TradingStatus
from invest_pipeline.adapters.cifang.client import CifangResponse
from invest_pipeline.adapters.cifang.mapper import (
    map_fund_hist_em,
    map_fund_list,
)
from invest_pipeline.adapters.errors import ProviderDataContractError


def _id(symbol: str, exchange: str) -> InstrumentId:
    """Per-row resolver; the (symbol, exchange) tuple is preserved so
    the mapper can be tested for routing."""

    return InstrumentId.generate()


def _resolver() -> callable:
    """Stable per-call resolver; the mapper only needs a placeholder id."""

    return _id


def _make_response(payload: object) -> CifangResponse:
    return CifangResponse(
        request_url="https://example.invalid/api/fund/list",
        request_params=(),
        raw_payload=payload,
        raw_payload_hash="0" * 64,
    )


def _observed_at() -> datetime:
    return datetime(2026, 7, 30, 8, 0, 0, tzinfo=UTC)


def _bar_source() -> callable:
    """Closure-free helper for the bar_source kwarg."""
    pass


# ----------------------------------------------------------------------
# ETF master-data mapping
# ----------------------------------------------------------------------


class MapFundListTest(unittest.TestCase):
    """Mapping rules for ``/api/fund/list``."""

    def test_maps_sh_and_sz_to_sse_szse(self) -> None:
        payload = [
            {
                "symbol": "510300",
                "name": "华泰柏瑞沪深300ETF",
                "exchange": "SH",
                "instrument_type": "ETF",
                "list_date": "2012-05-04",
            },
            {
                "symbol": "159919",
                "name": "嘉实沪深300ETF",
                "exchange": "SZ",
                "instrument_type": "ETF",
                "list_date": "2012-05-07",
            },
        ]
        result = map_fund_list(_make_response(payload))
        self.assertEqual(len(result.instruments), 2)
        self.assertEqual(result.instruments[0].exchange, "SSE")
        self.assertEqual(result.instruments[1].exchange, "SZSE")
        for instrument in result.instruments:
            assert isinstance(instrument, Instrument)
            self.assertEqual(instrument.instrument_type, InstrumentType.ETF)
            self.assertEqual(instrument.currency, Currency.CNY)

    def test_non_etf_rows_are_skipped_with_warning(self) -> None:
        payload = [
            {
                "symbol": "510300",
                "name": "ETF-A",
                "exchange": "SH",
                "instrument_type": "ETF",
            },
            {
                "symbol": "600000",
                "name": "STOCK-A",
                "exchange": "SH",
                "instrument_type": "STOCK",
            },
        ]
        result = map_fund_list(_make_response(payload))
        self.assertEqual(len(result.instruments), 1)
        self.assertEqual(result.instruments[0].symbol, "510300")
        self.assertTrue(
            any("STOCK" in w for w in result.warnings),
            f"expected non-ETF warning, got {result.warnings!r}",
        )

    def test_unsupported_exchange_raises(self) -> None:
        payload = [
            {
                "symbol": "510300",
                "name": "ETF-A",
                "exchange": "HK",
                "instrument_type": "ETF",
            },
        ]
        with self.assertRaises(ProviderDataContractError) as ctx:
            map_fund_list(_make_response(payload))
        self.assertIn("UNSUPPORTED_EXCHANGE", str(ctx.exception))

    def test_missing_required_fields_raise(self) -> None:
        with self.assertRaises(ProviderDataContractError):
            map_fund_list(_make_response({"not": "a list"}))
        with self.assertRaises(ProviderDataContractError):
            map_fund_list(_make_response([{"symbol": "510300"}]))

    def test_non_list_payload_raises(self) -> None:
        with self.assertRaises(ProviderDataContractError):
            map_fund_list(_make_response({"data": []}))


# ----------------------------------------------------------------------
# Daily-bars mapping
# ----------------------------------------------------------------------


class MapFundHistEmTest(unittest.TestCase):
    """Mapping rules for ``/api/fund/hist_em``."""

    def _row(
        self,
        *,
        symbol: str = "510300",
        exchange: str = "SH",
        trade_date: str = "2026-07-30",
        open: object = "3.10",
        high: object = "3.18",
        low: object = "3.08",
        close: object = "3.15",
        prev_close: object = "3.09",
        volume: object = "1000",
        amount: object = "3150000",
    ) -> dict[str, object]:
        return {
            "symbol": symbol,
            "exchange": exchange,
            "trade_date": trade_date,
            "open": open,
            "high": high,
            "low": low,
            "close": close,
            "prev_close": prev_close,
            "volume": volume,
            "amount": amount,
        }

    def _payload(self, rows: list[dict[str, object]]) -> dict[str, object]:
        return {"adjust": "none", "data": rows}

    def test_maps_normal_row_with_full_ohlc(self) -> None:
        row = self._row()
        result = map_fund_hist_em(
            _make_response(self._payload([row])),
            chunk_index=1,
            chunk_count=1,
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            instrument_id_resolver=_resolver(),
        )
        self.assertEqual(len(result.bars), 1)
        bar = result.bars[0]
        assert isinstance(bar, DailyBar)
        self.assertEqual(bar.trading_status, TradingStatus.NORMAL)
        self.assertEqual(bar.adjustment, Adjust.NONE)
        self.assertEqual(bar.open, _D("3.10"))
        self.assertEqual(bar.prev_close, _D("3.09"))
        self.assertEqual(bar.amount, _D("3150000"))

    def test_maps_sh_to_sse_and_sz_to_szse(self) -> None:
        rows = [
            self._row(symbol="510300", exchange="SH"),
            self._row(symbol="159919", exchange="SZ"),
        ]
        calls, resolver = resolver_calls_for_test()
        result = map_fund_hist_em(
            _make_response(self._payload(rows)),
            chunk_index=1,
            chunk_count=1,
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            instrument_id_resolver=resolver,
        )
        self.assertEqual(len(result.bars), 2)
        # The mapper routes the resolver lookup through SSE / SZSE
        # (ADR-0011 §2 / ADR-0004 §1) rather than the upstream ``SH`` /
        # ``SZ`` strings. ``calls`` is a list (insertion order); sort
        # it so the assertion stays stable against row re-ordering.
        self.assertEqual(
            sorted(calls),
            sorted([("510300", "SSE"), ("159919", "SZSE")]),
        )

    def test_allow_nullable_prev_close_and_amount(self) -> None:
        row = self._row(prev_close=None, amount=None)
        result = map_fund_hist_em(
            _make_response(self._payload([row])),
            chunk_index=1,
            chunk_count=1,
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            instrument_id_resolver=_resolver(),
        )
        self.assertEqual(len(result.bars), 1)
        bar = result.bars[0]
        assert isinstance(bar, DailyBar)
        self.assertIsNone(bar.prev_close)
        self.assertIsNone(bar.amount)

    def test_suspended_row_with_all_null_ohlcv(self) -> None:
        row = self._row(
            open=None, high=None, low=None, close=None,
            prev_close=None, volume=None, amount=None,
        )
        result = map_fund_hist_em(
            _make_response(self._payload([row])),
            chunk_index=1,
            chunk_count=1,
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            instrument_id_resolver=_resolver(),
        )
        self.assertEqual(len(result.bars), 1)
        bar = result.bars[0]
        assert isinstance(bar, DailyBar)
        self.assertEqual(bar.trading_status, TradingStatus.SUSPENDED)

    def test_invalid_ohlc_skips_row_with_warning(self) -> None:
        row = self._row(open="3.30", high="3.20")  # high < open
        result = map_fund_hist_em(
            _make_response(self._payload([row])),
            chunk_index=1,
            chunk_count=1,
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            instrument_id_resolver=_resolver(),
        )
        self.assertEqual(len(result.bars), 0)
        self.assertTrue(any("OHLC" in w for w in result.warnings))

    def test_non_none_adjustment_raises(self) -> None:
        payload = {"adjust": "qfq", "data": [self._row()]}
        with self.assertRaises(ProviderDataContractError) as ctx:
            map_fund_hist_em(
                _make_response(payload),
                chunk_index=1,
                chunk_count=1,
                source_batch_id=uuid4(),
                observed_at=_observed_at(),
                instrument_id_resolver=_resolver(),
            )
        self.assertIn("NON_NONE_ADJUSTMENT", str(ctx.exception))

    def test_non_dict_payload_raises(self) -> None:
        with self.assertRaises(ProviderDataContractError):
            map_fund_hist_em(
                _make_response([self._row()]),
                chunk_index=1,
                chunk_count=1,
                source_batch_id=uuid4(),
                observed_at=_observed_at(),
                instrument_id_resolver=_resolver(),
            )

    def test_unsupported_exchange_in_row_raises(self) -> None:
        row = self._row(exchange="BJ")  # Beijing is not in ADR-0004
        with self.assertRaises(ProviderDataContractError) as ctx:
            map_fund_hist_em(
                _make_response(self._payload([row])),
                chunk_index=1,
                chunk_count=1,
                source_batch_id=uuid4(),
                observed_at=_observed_at(),
                instrument_id_resolver=_resolver(),
            )
        self.assertIn("UNSUPPORTED_EXCHANGE", str(ctx.exception))


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _D(value: str):
    from decimal import Decimal

    return Decimal(value)


def bar_instrument_ids(bars: tuple[DailyBar, ...]) -> set[str]:
    """Return the set of instrument ids the mapper produced.

    Each call to :func:`_resolver` returns a fresh ``InstrumentId``;
    we can only inspect them via their string form. The mapper does
    not stamp the symbol on the bar (the application service does the
    ``symbol -> core.instruments.id`` re-mapping), so this helper
    exists only as a smoke check.
    """

    return {str(bar.instrument_id.value) for bar in bars}


def resolver_calls_for_test() -> tuple[list[tuple[str, str]], callable]:
    """Build a resolver that records its (symbol, exchange) calls.

    Returns ``(calls, resolver)``. Used by ``test_maps_sh_to_sse_and_sz_to_szse``
    to confirm the mapper routes SSE / SZSE correctly into the resolver.
    """

    calls: list[tuple[str, str]] = []

    def resolver(symbol: str, exchange: str) -> InstrumentId:
        calls.append((symbol, exchange))
        return InstrumentId.generate()

    return calls, resolver


if __name__ == "__main__":
    unittest.main()