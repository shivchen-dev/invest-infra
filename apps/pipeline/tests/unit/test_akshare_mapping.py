"""Unit tests for the AkShare field mappers (PR-02 / NAV / calendar).

The mappers are pure functions over an :class:`AkshareResponse`; no
network, no ``akshare``, no ``pandas``. The tests cover:

- Exchange alias resolution (``SH`` → ``SSE``, ``SZ`` → ``SZSE``)
  and exchange inference from six-digit ETF codes.
- Field aliases for the documented Chinese column names
  (``基金代码`` / ``基金简称`` / ``日期`` / ``开盘`` / ...) **and**
  English aliases (``symbol`` / ``name`` / ``trade_date`` / ...).
- ETF filter (``InstrumentType.ETF``).
- Nullable ``prev_close`` / ``amount`` (ADR-0005 §3).
- OHLC invariant: ``high >= max(open, close, low)`` and
  ``low <= min(open, close, high)``.
- Trade-date format flexibility (AkShare returns ``YYYY-MM-DD`` or
  ``YYYYMMDD`` interchangeably).
- Per-row downgrades: malformed rows produce warnings, not failures.
- NAV mapper: extracts ``unit_nav`` / ``accumulated_nav`` /
  ``daily_growth_rate`` only (never coerces to OHLCV per plan §5
  Task 2 "明确 NAV 不映射为 OHLCV，不填充成交额").
- Trading-calendar mapper: returns ``(trade_date, is_open)`` only —
  the surface is date-only by design.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from invest_domain.instruments.models import Instrument, InstrumentId, InstrumentType
from invest_domain.market_data.models import DailyBar
from invest_domain.market_data.values import Adjust, Currency, TradingStatus
from invest_pipeline.adapters.akshare.client import AkshareResponse
from invest_pipeline.adapters.akshare.mapper import (
    AkshareCalendarRecord,
    AkshareNavRecord,
    map_fund_etf_fund_daily_em,
    map_fund_etf_fund_info_em,
    map_fund_etf_hist_em,
    map_tool_trade_date_hist_sina,
)
from invest_pipeline.adapters.errors import ProviderDataContractError


def _resolver() -> callable:
    """Stable per-row resolver; the mapper only needs a placeholder id."""

    return lambda _symbol, _exchange: InstrumentId.generate()


def _make_response(payload: list[dict[str, Any]], *, operation: str = "op") -> AkshareResponse:
    import hashlib
    import json

    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return AkshareResponse(
        operation=operation,
        raw_payload=payload,
        raw_payload_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _observed_at() -> datetime:
    return datetime(2026, 7, 30, 8, 0, 0, tzinfo=UTC)


# ----------------------------------------------------------------------
# ETF master-data mapping
# ----------------------------------------------------------------------


class MapFundEtfFundInfoEmTest(unittest.TestCase):
    """Mapping rules for ``ak.fund_etf_fund_info_em()``."""

    def test_maps_chinese_aliases_to_domain_fields(self) -> None:
        # The real AkShare DataFrame uses Chinese column names. The
        # mapper should accept those names so a true AkShare response
        # passes through with no extra renaming.
        payload = [
            {
                "基金代码": "510300",
                "基金简称": "华泰柏瑞沪深300ETF",
            },
        ]
        response = _make_response(payload, operation="fund_etf_fund_info_em")
        result = map_fund_etf_fund_info_em(response)
        self.assertEqual(len(result.instruments), 1)
        instrument = result.instruments[0]
        assert isinstance(instrument, Instrument)
        self.assertEqual(instrument.symbol, "510300")
        self.assertEqual(instrument.name, "华泰柏瑞沪深300ETF")
        self.assertEqual(instrument.exchange, "SSE")
        self.assertEqual(instrument.instrument_type, InstrumentType.ETF)
        self.assertEqual(instrument.currency, Currency.CNY)
        self.assertEqual(instrument.provider_symbol_map, {"akshare": "510300"})

    def test_maps_english_aliases_to_domain_fields(self) -> None:
        payload = [
            {
                "symbol": "510300",
                "name": "ETF-A",
                "exchange": "SH",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_fund_info_em(response)
        self.assertEqual(len(result.instruments), 1)
        instrument = result.instruments[0]
        self.assertEqual(instrument.symbol, "510300")
        self.assertEqual(instrument.name, "ETF-A")
        self.assertEqual(instrument.exchange, "SSE")

    def test_maps_sz_alias_to_szse(self) -> None:
        payload = [
            {
                "symbol": "159919",
                "name": "嘉实沪深300ETF",
                "exchange": "SZ",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_fund_info_em(response)
        self.assertEqual(len(result.instruments), 1)
        self.assertEqual(result.instruments[0].exchange, "SZSE")

    def test_infers_exchange_from_symbol_when_missing(self) -> None:
        # When the upstream row omits ``exchange``, the mapper falls
        # back to the documented six-digit ETF prefix rule.
        payload = [
            {"symbol": "510300", "name": "ETF-510"},
            {"symbol": "159919", "name": "ETF-159"},
        ]
        response = _make_response(payload)
        result = map_fund_etf_fund_info_em(response)
        self.assertEqual(result.instruments[0].exchange, "SSE")
        self.assertEqual(result.instruments[1].exchange, "SZSE")

    def test_unknown_exchange_raises_contract_error(self) -> None:
        # The SSE / SZSE allow-list (ADR-0004 §1) is enforced even
        # when an explicit ``exchange`` field is supplied — out-of-
        # scope exchanges cannot silently reach the instrument table.
        payload = [
            {
                "symbol": "510300",
                "name": "ETF-A",
                "exchange": "BJSE",
            },
        ]
        response = _make_response(payload)
        with self.assertRaises(ProviderDataContractError) as ctx:
            map_fund_etf_fund_info_em(response)
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_EXCHANGE")
        self.assertIn("BJSE", str(ctx.exception))

    def test_cannot_infer_exchange_raises_contract_error(self) -> None:
        # A symbol that does not match the documented prefix set
        # cannot be silently dropped — the contract error surfaces
        # so the upstream batch can be rejected.
        payload = [
            {"symbol": "999999", "name": "ETF-999"},
        ]
        response = _make_response(payload)
        with self.assertRaises(ProviderDataContractError) as ctx:
            map_fund_etf_fund_info_em(response)
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_EXCHANGE")
        self.assertIn("999999", str(ctx.exception))

    def test_missing_symbol_raises_contract_error(self) -> None:
        payload = [
            {"name": "ETF-A"},
        ]
        response = _make_response(payload)
        with self.assertRaises(ProviderDataContractError) as ctx:
            map_fund_etf_fund_info_em(response)
        self.assertEqual(ctx.exception.code, "MISSING_REQUIRED_FIELD")

    def test_missing_name_raises_contract_error(self) -> None:
        payload = [
            {"symbol": "510300"},
        ]
        response = _make_response(payload)
        with self.assertRaises(ProviderDataContractError) as ctx:
            map_fund_etf_fund_info_em(response)
        self.assertEqual(ctx.exception.code, "MISSING_REQUIRED_FIELD")

    def test_list_date_iso_is_parsed(self) -> None:
        # AkShare may return either ``YYYY-MM-DD`` or ``YYYYMMDD``
        # forms for ``list_date``. The mapper accepts both.
        payload = [
            {
                "symbol": "510300",
                "name": "ETF-A",
                "list_date": "2012-05-04",
            },
            {
                "symbol": "510500",
                "name": "ETF-B",
                "list_date": "20130101",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_fund_info_em(response)
        self.assertEqual(result.instruments[0].list_date, date(2012, 5, 4))
        self.assertEqual(result.instruments[1].list_date, date(2013, 1, 1))

    def test_invalid_list_date_raises_contract_error(self) -> None:
        payload = [
            {
                "symbol": "510300",
                "name": "ETF-A",
                "list_date": "not-a-date",
            },
        ]
        response = _make_response(payload)
        with self.assertRaises(ProviderDataContractError) as ctx:
            map_fund_etf_fund_info_em(response)
        self.assertEqual(ctx.exception.code, "MALFORMED_LIST_DATE")

    def test_status_is_parsed_with_unknown_fallback_to_active(self) -> None:
        from invest_domain.instruments.values import InstrumentStatus

        payload = [
            {"symbol": "510300", "name": "ETF-A", "status": "active"},
            {
                "symbol": "510500",
                "name": "ETF-B",
                "status": "delisted",
                "delist_date": "2024-01-15",
            },
            {
                "symbol": "159919",
                "name": "ETF-C",
                "status": "some-future-status",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_fund_info_em(response)
        statuses = [instrument.status for instrument in result.instruments]
        self.assertEqual(
            statuses,
            [
                InstrumentStatus.ACTIVE,
                InstrumentStatus.DELISTED,
                InstrumentStatus.ACTIVE,
            ],
            "Unknown statuses should fall back to 'active' rather "
            "than failing the whole batch.",
        )

    def test_non_dict_entry_raises_contract_error(self) -> None:
        # A row that is not a JSON object is a contract violation,
        # not a recoverable skip — fail the batch with a typed error.
        payload = [["symbol", "name"], "510300"]
        response = _make_response(payload)
        with self.assertRaises(ProviderDataContractError) as ctx:
            map_fund_etf_fund_info_em(response)
        self.assertEqual(ctx.exception.code, "MALFORMED_ETF_LIST_ROW")


# ----------------------------------------------------------------------
# Daily-bars mapping
# ----------------------------------------------------------------------


class MapFundEtfHistEmTest(unittest.TestCase):
    """Mapping rules for ``ak.fund_etf_hist_em()``."""

    def test_maps_chinese_ohlcv_aliases_to_daily_bar(self) -> None:
        # Real AkShare ``fund_etf_hist_em`` returns Chinese column
        # names. The mapper should accept them and translate to a
        # domain :class:`DailyBar` with ``adjustment=Adjust.NONE`` /
        # ``trading_status=TradingStatus.NORMAL``.
        from decimal import Decimal

        payload = [
            {
                "日期": "2026-07-30",
                "开盘": "3.900",
                "收盘": "3.910",
                "最高": "3.920",
                "最低": "3.890",
                "成交量": "10000000",
                "成交额": "39100000",
            },
        ]
        response = _make_response(payload, operation="fund_etf_hist_em")
        result = map_fund_etf_hist_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            instrument_id_resolver=_resolver(),
        )
        self.assertEqual(len(result.bars), 1)
        self.assertEqual(len(result.warnings), 0)
        bar = result.bars[0]
        assert isinstance(bar, DailyBar)
        self.assertEqual(bar.trade_date, date(2026, 7, 30))
        self.assertEqual(bar.open, Decimal("3.900"))
        self.assertEqual(bar.high, Decimal("3.920"))
        self.assertEqual(bar.trading_status, TradingStatus.NORMAL)
        self.assertEqual(bar.adjustment, Adjust.NONE)
        self.assertIsNone(bar.prev_close)
        self.assertIsNotNone(bar.amount)

    def test_maps_english_ohlcv_aliases_to_daily_bar(self) -> None:
        payload = [
            {
                "trade_date": "2026-07-30",
                "open": "3.900",
                "close": "3.910",
                "high": "3.920",
                "low": "3.890",
                "volume": "10000000",
                "amount": "39100000",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_hist_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            instrument_id_resolver=_resolver(),
        )
        self.assertEqual(len(result.bars), 1)

    def test_suspended_row_is_mapped_to_suspended_status(self) -> None:
        # A row with all-null OHLC (and no volume / amount) is
        # treated as suspended, mirroring the Cifang mapper.
        payload = [
            {
                "日期": "2026-07-30",
                "开盘": None,
                "收盘": None,
                "最高": None,
                "最低": None,
                "成交量": None,
                "成交额": None,
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_hist_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            instrument_id_resolver=_resolver(),
        )
        self.assertEqual(len(result.bars), 1)
        self.assertEqual(result.bars[0].trading_status, TradingStatus.SUSPENDED)
        self.assertIsNone(result.bars[0].open)
        self.assertIsNone(result.bars[0].high)

    def test_invalid_ohlc_invariance_downgrades_to_warning(self) -> None:
        # ``high`` below ``max(open, close, low)`` is a row-level
        # problem — drop the row with a warning rather than failing
        # the whole batch.
        payload = [
            {
                "trade_date": "2026-07-30",
                "open": "4.000",
                "close": "3.910",
                "high": "3.850",
                "low": "3.890",
                "volume": "10000000",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_hist_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            instrument_id_resolver=_resolver(),
        )
        self.assertEqual(result.bars, ())
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("high=3.85", result.warnings[0])

    def test_missing_required_ohlc_downgrades_to_warning(self) -> None:
        # A row missing any of ``open`` / ``close`` / ``high`` /
        # ``low`` is a row-level problem — drop the row with a
        # warning rather than failing the batch.
        payload = [
            {
                "trade_date": "2026-07-30",
                "open": "3.900",
                "close": "3.910",
                "high": "3.920",
                # low missing
                "volume": "10000000",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_hist_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            instrument_id_resolver=_resolver(),
        )
        self.assertEqual(result.bars, ())
        self.assertEqual(len(result.warnings), 1)

    def test_non_dict_row_downgrades_to_warning(self) -> None:
        payload = [["trade_date", "open"]]
        response = _make_response(payload)
        result = map_fund_etf_hist_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            instrument_id_resolver=_resolver(),
        )
        self.assertEqual(result.bars, ())
        self.assertEqual(len(result.warnings), 1)

    def test_invalid_trade_date_format_downgrades_to_warning(self) -> None:
        payload = [
            {
                "trade_date": "30-07-2026",
                "open": "3.900",
                "close": "3.910",
                "high": "3.920",
                "low": "3.890",
                "volume": "10000000",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_hist_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            instrument_id_resolver=_resolver(),
        )
        self.assertEqual(result.bars, ())
        self.assertEqual(len(result.warnings), 1)

    def test_compact_yyyymmdd_trade_date_is_parsed(self) -> None:
        # AkShare returns ``YYYYMMDD`` natively for some symbols; the
        # mapper must accept the compact form so a real SDK response
        # does not produce row-level warnings.
        payload = [
            {
                "trade_date": "20260730",
                "open": "3.900",
                "close": "3.910",
                "high": "3.920",
                "low": "3.890",
                "volume": "10000000",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_hist_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            instrument_id_resolver=_resolver(),
        )
        self.assertEqual(len(result.bars), 1)
        self.assertEqual(result.bars[0].trade_date, date(2026, 7, 30))

    def test_unknown_symbol_exchange_raises_contract_error(self) -> None:
        # The mapper still raises the typed allow-list error when a
        # symbol prefix cannot be inferred to SSE / SZSE. Callers can
        # catch and downgrade to a batch-level rejection.
        payload = [
            {
                "trade_date": "2026-07-30",
                "open": "3.900",
                "close": "3.910",
                "high": "3.920",
                "low": "3.890",
                "volume": "10000000",
            },
        ]
        response = _make_response(payload)
        with self.assertRaises(ProviderDataContractError) as ctx:
            map_fund_etf_hist_em(
                response,
                symbol="999999",
                source_batch_id=uuid4(),
                observed_at=_observed_at(),
                instrument_id_resolver=_resolver(),
            )
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_EXCHANGE")


# ----------------------------------------------------------------------
# NAV mapper (no OHLCV coercion)
# ----------------------------------------------------------------------


class MapFundEtfFundDailyEmTest(unittest.TestCase):
    """Mapping rules for ``ak.fund_etf_fund_daily_em()``.

    The NAV mapper must build :class:`AkshareNavRecord` rows without
    ever populating OHLCV fields. The plan §5 Task 2 contract is
    pinned here so a future regression that pushes NAV into
    :class:`DailyBar` is caught at the mapper boundary.
    """

    def test_maps_chinese_aliases_to_nav_record(self) -> None:
        # Real AkShare ``fund_etf_fund_daily_em`` returns Chinese
        # column names. The mapper accepts them and translates to a
        # :class:`AkshareNavRecord` whose fields are ``unit_nav``,
        # ``accumulated_nav`` and ``daily_growth_rate`` only — never
        # OHLCV.
        from decimal import Decimal

        payload = [
            {
                "净值日期": "2026-07-30",
                "单位净值": "1.234",
                "累计净值": "1.567",
                "日增长率": "0.5",
            },
        ]
        response = _make_response(payload, operation="fund_etf_fund_daily_em")
        result = map_fund_etf_fund_daily_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
        )
        self.assertEqual(result.warnings, ())
        self.assertEqual(len(result.records), 1)
        record = result.records[0]
        assert isinstance(record, AkshareNavRecord)
        self.assertEqual(record.symbol, "510300")
        self.assertEqual(record.trade_date, date(2026, 7, 30))
        self.assertEqual(record.unit_nav, Decimal("1.234"))
        self.assertEqual(record.accumulated_nav, Decimal("1.567"))
        self.assertEqual(record.daily_growth_rate, Decimal("0.5"))
        # The NAV record must never expose OHLCV fields.
        self.assertFalse(hasattr(record, "open"))
        self.assertFalse(hasattr(record, "high"))
        self.assertFalse(hasattr(record, "low"))
        self.assertFalse(hasattr(record, "close"))
        self.assertFalse(hasattr(record, "volume"))
        self.assertFalse(hasattr(record, "amount"))

    def test_maps_english_aliases_to_nav_record(self) -> None:
        from decimal import Decimal

        payload = [
            {
                "trade_date": "2026-07-30",
                "unit_nav": "1.234",
                "accumulated_nav": "1.567",
                "daily_growth_rate": "0.5",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_fund_daily_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
        )
        self.assertEqual(len(result.records), 1)
        record = result.records[0]
        self.assertEqual(record.unit_nav, Decimal("1.234"))
        self.assertEqual(record.accumulated_nav, Decimal("1.567"))
        self.assertEqual(record.daily_growth_rate, Decimal("0.5"))

    def test_nullable_nav_fields_are_preserved(self) -> None:
        # NAV rows may legitimately omit any of ``unit_nav`` /
        # ``accumulated_nav`` / ``daily_growth_rate``; the mapper
        # must preserve the ``None`` so the upstream batch reports
        # the missing column rather than fabricating a value.
        payload = [
            {
                "trade_date": "2026-07-30",
                "unit_nav": None,
                "accumulated_nav": None,
                "daily_growth_rate": None,
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_fund_daily_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
        )
        record = result.records[0]
        self.assertIsNone(record.unit_nav)
        self.assertIsNone(record.accumulated_nav)
        self.assertIsNone(record.daily_growth_rate)

    def test_missing_trade_date_downgrades_to_warning(self) -> None:
        # A NAV row without ``trade_date`` cannot be promoted — the
        # mapper drops it with a warning and the surviving rows
        # still ship.
        payload = [
            {"unit_nav": "1.234"},
            {
                "trade_date": "2026-07-30",
                "unit_nav": "1.235",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_fund_daily_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
        )
        self.assertEqual(len(result.records), 1)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("trade_date", result.warnings[0])

    def test_invalid_trade_date_downgrades_to_warning(self) -> None:
        payload = [
            {
                "trade_date": "30-07-2026",
                "unit_nav": "1.234",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_fund_daily_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
        )
        self.assertEqual(result.records, ())
        self.assertEqual(len(result.warnings), 1)

    def test_non_decimal_nav_field_downgrades_to_warning(self) -> None:
        # A present-but-non-numeric NAV field is recoverable: the
        # mapper drops the row with a warning so the surviving rows
        # still ship on the upstream batch.
        payload = [
            {
                "trade_date": "2026-07-30",
                "unit_nav": "not-a-decimal",
            },
            {
                "trade_date": "2026-07-29",
                "unit_nav": "1.235",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_fund_daily_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
        )
        self.assertEqual(len(result.records), 1)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("non-decimal", result.warnings[0])

    def test_compact_yyyymmdd_trade_date_is_parsed(self) -> None:
        from decimal import Decimal

        payload = [
            {
                "trade_date": "20260730",
                "unit_nav": "1.234",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_fund_daily_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
        )
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].trade_date, date(2026, 7, 30))
        self.assertEqual(result.records[0].unit_nav, Decimal("1.234"))

    def test_non_dict_row_downgrades_to_warning(self) -> None:
        payload = [["trade_date", "unit_nav"]]
        response = _make_response(payload)
        result = map_fund_etf_fund_daily_em(
            response,
            symbol="510300",
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
        )
        self.assertEqual(result.records, ())
        self.assertEqual(len(result.warnings), 1)

    def test_records_carry_source_batch_id_and_observed_at(self) -> None:
        # The mapper does not own a clock — the adapter stamps the
        # audit fields on the way in. Pin the propagation here so a
        # future refactor that drops the kwargs surfaces immediately.
        batch_id = uuid4()
        observed = _observed_at()
        payload = [
            {
                "trade_date": "2026-07-30",
                "unit_nav": "1.234",
            },
        ]
        response = _make_response(payload)
        result = map_fund_etf_fund_daily_em(
            response,
            symbol="510300",
            source_batch_id=batch_id,
            observed_at=observed,
        )
        self.assertEqual(result.records[0].source_batch_id, batch_id)
        self.assertEqual(result.records[0].observed_at, observed)


# ----------------------------------------------------------------------
# Trading-calendar mapper (date-only)
# ----------------------------------------------------------------------


class MapToolTradeDateHistSinaTest(unittest.TestCase):
    """Mapping rules for ``ak.tool_trade_date_hist_sina()``.

    The trading-calendar mapper is date-only by design. The
    tests pin the shape so a future regression that injects
    per-symbol content or coerces calendar entries into
    :class:`DailyBar` is caught at the mapper boundary.
    """

    def test_maps_iso_trade_dates_to_calendar_records(self) -> None:
        payload = [
            {"trade_date": "2026-07-29"},
            {"trade_date": "2026-07-30"},
        ]
        response = _make_response(
            payload, operation="tool_trade_date_hist_sina"
        )
        result = map_tool_trade_date_hist_sina(response)
        self.assertEqual(result.warnings, ())
        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.records[0].trade_date, date(2026, 7, 29))
        self.assertEqual(result.records[1].trade_date, date(2026, 7, 30))
        # The calendar surface never carries a symbol; the records
        # expose ``is_open`` only.
        for entry in result.records:
            assert isinstance(entry, AkshareCalendarRecord)
            self.assertIsNone(entry.is_open)

    def test_maps_compact_trade_dates(self) -> None:
        payload = [{"trade_date": "20260730"}]
        response = _make_response(payload)
        result = map_tool_trade_date_hist_sina(response)
        self.assertEqual(result.records[0].trade_date, date(2026, 7, 30))

    def test_accepts_chinese_aliases(self) -> None:
        payload = [{"日期": "2026-07-30"}]
        response = _make_response(payload)
        result = map_tool_trade_date_hist_sina(response)
        self.assertEqual(result.records[0].trade_date, date(2026, 7, 30))

    def test_is_open_flag_is_parsed_when_present(self) -> None:
        payload = [
            {"trade_date": "2026-07-30", "is_open": True},
            {"trade_date": "2026-07-29", "is_open": 0},
            {"trade_date": "2026-07-28", "is_open": "1"},
        ]
        response = _make_response(payload)
        result = map_tool_trade_date_hist_sina(response)
        self.assertEqual(
            [entry.is_open for entry in result.records],
            [True, False, True],
        )

    def test_missing_trade_date_downgrades_to_warning(self) -> None:
        payload = [
            {"trade_date": "2026-07-30"},
            {"is_open": True},
        ]
        response = _make_response(payload)
        result = map_tool_trade_date_hist_sina(response)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("trade_date", result.warnings[0])

    def test_invalid_trade_date_downgrades_to_warning(self) -> None:
        payload = [{"trade_date": "30-07-2026"}]
        response = _make_response(payload)
        result = map_tool_trade_date_hist_sina(response)
        self.assertEqual(result.records, ())
        self.assertEqual(len(result.warnings), 1)

    def test_non_dict_row_downgrades_to_warning(self) -> None:
        payload = [["trade_date", "is_open"]]
        response = _make_response(payload)
        result = map_tool_trade_date_hist_sina(response)
        self.assertEqual(result.records, ())
        self.assertEqual(len(result.warnings), 1)


if __name__ == "__main__":
    unittest.main()
