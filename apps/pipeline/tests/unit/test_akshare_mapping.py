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
from decimal import Decimal
from typing import Any
from uuid import uuid4

from invest_domain.etf_profile.models import FieldEvidence
from invest_domain.instruments.models import Instrument, InstrumentId, InstrumentType
from invest_domain.market_data.models import DailyBar
from invest_domain.market_data.values import Adjust, Currency, TradingStatus
from invest_domain.research.models import QualityStatus
from invest_pipeline.adapters.akshare.client import AkshareResponse
from invest_pipeline.adapters.akshare.mapper import (
    AkshareCalendarRecord,
    AkshareNavRecord,
    AkshareProfileRecord,
    map_etf_profile_to_field_evidence,
    map_fund_etf_fund_daily_em,
    map_fund_etf_fund_info_em,
    map_fund_etf_hist_em,
    map_fund_etf_spot_em,
    map_fund_name_em,
    map_tool_trade_date_hist_sina,
    merge_etf_profile,
)
from invest_pipeline.adapters.errors import ProviderDataContractError


def _resolver() -> callable:
    """Stable per-row resolver; the mapper only needs a placeholder id."""

    return lambda _symbol, _exchange: InstrumentId.generate()


def _make_response(payload: list[dict[str, Any]], *, operation: str = "op") -> AkshareResponse:
    import hashlib
    import json

    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
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

    def test_native_date_trade_date_is_parsed(self) -> None:
        payload = [{
            "date": date(2026, 7, 30),
            "open": "3.900", "close": "3.910",
            "high": "3.920", "low": "3.890", "volume": "10000000",
        }]
        result = map_fund_etf_hist_em(
            _make_response(payload), symbol="510300", source_batch_id=uuid4(),
            observed_at=_observed_at(), instrument_id_resolver=_resolver(),
        )
        self.assertEqual(len(result.bars), 1)

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


# ----------------------------------------------------------------------
# ETF Profile mapper (DC-2 — conservative static metadata)
# ----------------------------------------------------------------------


class MapFundNameEmTest(unittest.TestCase):
    """Mapping rules for ``ak.fund_name_em()``."""

    def test_maps_chinese_aliases_to_fund_name_records(self) -> None:
        payload = [
            {
                "基金代码": "510300",
                "基金简称": "华泰柏瑞沪深300ETF",
                "基金类型": "ETF",
            },
            {
                "基金代码": "159919",
                "基金简称": "嘉实沪深300ETF",
                "基金类型": "ETF",
            },
        ]
        response = _make_response(payload, operation="fund_name_em")
        result = map_fund_name_em(response)
        self.assertEqual(result.warnings, ())
        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.records[0].symbol, "510300")
        self.assertEqual(result.records[0].fund_type, "ETF")
        self.assertEqual(result.records[0].category, "ETF")
        self.assertEqual(result.records[1].symbol, "159919")

    def test_maps_english_aliases_to_fund_name_records(self) -> None:
        payload = [
            {"symbol": "510300", "name": "ETF-A", "type": "ETF"},
        ]
        response = _make_response(payload)
        result = map_fund_name_em(response)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].symbol, "510300")
        self.assertEqual(result.records[0].fund_type, "ETF")
        self.assertEqual(result.records[0].category, "ETF")

    def test_non_etf_row_is_skipped_with_warning(self) -> None:
        # ``fund_name_em`` includes LOFs / closed-end funds / bond
        # funds. The mapper is ETF-only; non-ETF rows downgrade to a
        # warning so the downstream merge is bounded to confirmed ETFs.
        payload = [
            {"基金代码": "510300", "基金类型": "ETF"},
            {"基金代码": "163406", "基金类型": "LOF"},
            {"基金代码": "000001", "基金类型": "OpenEnd"},
        ]
        response = _make_response(payload)
        result = map_fund_name_em(response)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].symbol, "510300")
        self.assertEqual(len(result.warnings), 2)
        for warning in result.warnings:
            self.assertIn("not an ETF row", warning)

    def test_non_six_digit_symbol_is_skipped_with_warning(self) -> None:
        payload = [
            {"基金代码": "510300", "基金类型": "ETF"},
            {"基金代码": "ABC123", "基金类型": "ETF"},
            {"基金代码": "12345", "基金类型": "ETF"},
        ]
        response = _make_response(payload)
        result = map_fund_name_em(response)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].symbol, "510300")
        self.assertEqual(len(result.warnings), 2)

    def test_missing_symbol_downgrades_to_warning(self) -> None:
        payload = [
            {"基金简称": "ETF-A", "基金类型": "ETF"},
        ]
        response = _make_response(payload)
        result = map_fund_name_em(response)
        self.assertEqual(result.records, ())
        self.assertEqual(len(result.warnings), 1)

    def test_non_dict_row_downgrades_to_warning(self) -> None:
        payload = [["基金代码", "基金类型"]]
        response = _make_response(payload)
        result = map_fund_name_em(response)
        self.assertEqual(result.records, ())
        self.assertEqual(len(result.warnings), 1)


class MapFundEtfSpotEmTest(unittest.TestCase):
    """Mapping rules for ``ak.fund_etf_spot_em()``."""

    def test_maps_chinese_aliases_to_spot_records(self) -> None:
        payload = [
            {
                "代码": "510300",
                "名称": "华泰柏瑞沪深300ETF",
                "最新份额": "1000000000",
                "总市值": "1234567890.00",
            },
            {
                "代码": "159919",
                "名称": "嘉实沪深300ETF",
                "最新份额": "500000000",
                "总市值": "987654321.00",
            },
        ]
        response = _make_response(payload, operation="fund_etf_spot_em")
        result = map_fund_etf_spot_em(response)
        self.assertEqual(result.warnings, ())
        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.records[0].symbol, "510300")
        self.assertEqual(
            result.records[0].shares, Decimal("1000000000")
        )
        # The total market value column is intentionally NOT extracted
        # — verify it never appears on the sidecar record.
        self.assertFalse(
            hasattr(result.records[0], "total_market_value")
        )
        self.assertFalse(
            hasattr(result.records[0], "aum")
        )

    def test_maps_english_aliases_to_spot_records(self) -> None:
        payload = [
            {"symbol": "510300", "shares": "1000000000"},
        ]
        response = _make_response(payload)
        result = map_fund_etf_spot_em(response)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].symbol, "510300")
        self.assertEqual(result.records[0].shares, Decimal("1000000000"))

    def test_non_six_digit_symbol_is_skipped_with_warning(self) -> None:
        payload = [
            {"代码": "510300", "最新份额": "1000000000"},
            {"代码": "ABC123", "最新份额": "500000000"},
        ]
        response = _make_response(payload)
        result = map_fund_etf_spot_em(response)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].symbol, "510300")
        self.assertEqual(len(result.warnings), 1)

    def test_missing_symbol_downgrades_to_warning(self) -> None:
        payload = [{"最新份额": "1000000000"}]
        response = _make_response(payload)
        result = map_fund_etf_spot_em(response)
        self.assertEqual(result.records, ())
        self.assertEqual(len(result.warnings), 1)

    def test_non_numeric_shares_downgrades_to_warning(self) -> None:
        payload = [
            {"代码": "510300", "最新份额": "1000000000"},
            {"代码": "159919", "最新份额": "not-a-number"},
        ]
        response = _make_response(payload)
        result = map_fund_etf_spot_em(response)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].symbol, "510300")
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("159919", result.warnings[0])
        self.assertIn("non-decimal", result.warnings[0])

    def test_missing_shares_is_acceptable(self) -> None:
        # A row with no ``shares`` is acceptable: ``shares`` is an
        # optional field on the domain contract. The mapper yields
        # ``None`` so the application service can still upsert the
        # profile row with verified fields only.
        payload = [
            {"代码": "510300", "总市值": "1234567890.00"},
        ]
        response = _make_response(payload)
        result = map_fund_etf_spot_em(response)
        self.assertEqual(len(result.records), 1)
        self.assertIsNone(result.records[0].shares)

    def test_non_dict_row_downgrades_to_warning(self) -> None:
        payload = [["代码", "最新份额"]]
        response = _make_response(payload)
        result = map_fund_etf_spot_em(response)
        self.assertEqual(result.records, ())
        self.assertEqual(len(result.warnings), 1)


class MergeEtfProfileTest(unittest.TestCase):
    """Inner-join rules for the static ETF Profile merge."""

    def test_joins_on_symbol_and_populates_verified_fields(self) -> None:
        name_payload = [
            {
                "基金代码": "510300",
                "基金简称": "华泰柏瑞沪深300ETF",
                "基金类型": "ETF",
            },
            {
                "基金代码": "159919",
                "基金简称": "嘉实沪深300ETF",
                "基金类型": "ETF",
            },
        ]
        spot_payload = [
            {
                "代码": "510300",
                "名称": "华泰柏瑞沪深300ETF",
                "最新份额": "1000000000",
                "总市值": "1234567890.00",
            },
            {
                "代码": "159919",
                "名称": "嘉实沪深300ETF",
                "最新份额": "500000000",
                "总市值": "987654321.00",
            },
        ]
        name_mapping = map_fund_name_em(
            _make_response(name_payload, operation="fund_name_em")
        )
        spot_mapping = map_fund_etf_spot_em(
            _make_response(spot_payload, operation="fund_etf_spot_em")
        )
        result = merge_etf_profile(name_mapping, spot_mapping)
        self.assertEqual(result.warnings, ())
        self.assertEqual(len(result.records), 2)
        # The merge step sorts symbols deterministically so the
        # output order is independent from the input order.
        records_by_symbol = {entry.symbol: entry for entry in result.records}
        sse = records_by_symbol["510300"]
        self.assertEqual(sse.exchange, "SSE")
        self.assertEqual(sse.fund_type, "ETF")
        self.assertEqual(sse.category, "ETF")
        self.assertEqual(sse.shares, Decimal("1000000000"))
        szse = records_by_symbol["159919"]
        self.assertEqual(szse.exchange, "SZSE")
        self.assertEqual(szse.shares, Decimal("500000000"))

    def test_total_market_value_is_never_mapped_to_aum(self) -> None:
        # The total market value column from ``fund_etf_spot_em``
        # is intentionally NOT extracted by the spot mapper; the
        # merge step therefore cannot leak it onto the profile
        # record. Verify the dataclass surface stays minimal.
        name_payload = [
            {"基金代码": "510300", "基金类型": "ETF"},
        ]
        spot_payload = [
            {
                "代码": "510300",
                "最新份额": "1000000000",
                "总市值": "1234567890.00",
            },
        ]
        name_mapping = map_fund_name_em(
            _make_response(name_payload, operation="fund_name_em")
        )
        spot_mapping = map_fund_etf_spot_em(
            _make_response(spot_payload, operation="fund_etf_spot_em")
        )
        result = merge_etf_profile(name_mapping, spot_mapping)
        self.assertEqual(len(result.records), 1)
        record = result.records[0]
        # The EtfProfile contract does not include aum from this
        # slice; verify the dataclass surface does not even expose
        # ``total_market_value``.
        self.assertFalse(hasattr(record, "aum"))
        self.assertFalse(hasattr(record, "total_market_value"))
        self.assertFalse(hasattr(record, "manager"))

    def test_name_only_symbols_yield_warning(self) -> None:
        name_payload = [
            {"基金代码": "510300", "基金类型": "ETF"},
            {"基金代码": "159919", "基金类型": "ETF"},
        ]
        spot_payload = [
            {"代码": "510300", "最新份额": "1000000000"},
        ]
        name_mapping = map_fund_name_em(
            _make_response(name_payload, operation="fund_name_em")
        )
        spot_mapping = map_fund_etf_spot_em(
            _make_response(spot_payload, operation="fund_etf_spot_em")
        )
        result = merge_etf_profile(name_mapping, spot_mapping)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].symbol, "510300")
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("159919", result.warnings[0])
        self.assertIn("fund_etf_spot_em", result.warnings[0])

    def test_spot_only_symbols_yield_warning(self) -> None:
        name_payload = [
            {"基金代码": "510300", "基金类型": "ETF"},
        ]
        spot_payload = [
            {"代码": "510300", "最新份额": "1000000000"},
            {"代码": "159919", "最新份额": "500000000"},
        ]
        name_mapping = map_fund_name_em(
            _make_response(name_payload, operation="fund_name_em")
        )
        spot_mapping = map_fund_etf_spot_em(
            _make_response(spot_payload, operation="fund_etf_spot_em")
        )
        result = merge_etf_profile(name_mapping, spot_mapping)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].symbol, "510300")
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("159919", result.warnings[0])
        self.assertIn("fund_name_em", result.warnings[0])

    def test_empty_payloads_yield_empty_records(self) -> None:
        name_mapping = map_fund_name_em(
            _make_response([], operation="fund_name_em")
        )
        spot_mapping = map_fund_etf_spot_em(
            _make_response([], operation="fund_etf_spot_em")
        )
        result = merge_etf_profile(name_mapping, spot_mapping)
        self.assertEqual(result.records, ())
        self.assertEqual(result.warnings, ())

    def test_unfunded_fields_stay_none(self) -> None:
        # The conservative slice leaves the unfunded fields ``None``
        # on the merged record. Verify the dataclass surface does not
        # fabricate a value (the production domain contract does not
        # accept a name field in this slice).
        name_payload = [
            {"基金代码": "510300", "基金类型": "ETF"},
        ]
        spot_payload = [
            {"代码": "510300", "最新份额": "1000000000"},
        ]
        name_mapping = map_fund_name_em(
            _make_response(name_payload, operation="fund_name_em")
        )
        spot_mapping = map_fund_etf_spot_em(
            _make_response(spot_payload, operation="fund_etf_spot_em")
        )
        result = merge_etf_profile(name_mapping, spot_mapping)
        record = result.records[0]
        # Verify the dataclass surface does not expose unfunded
        # fields at all (they live on the EtfProfile domain contract,
        # not on the AkShare-shaped mapper record).
        self.assertFalse(hasattr(record, "manager"))
        self.assertFalse(hasattr(record, "benchmark_index"))
        self.assertFalse(hasattr(record, "inception_date"))
        self.assertFalse(hasattr(record, "management_fee"))
        self.assertFalse(hasattr(record, "custody_fee"))
        self.assertFalse(hasattr(record, "aum"))
        self.assertFalse(hasattr(record, "name"))


# ----------------------------------------------------------------------
# ETF Profile → FieldEvidence mapping (PR-ETF-PROFILE-02)
# ----------------------------------------------------------------------


class MapEtfProfileToFieldEvidenceTest(unittest.TestCase):
    """Mapping rules for :func:`map_etf_profile_to_field_evidence`.

    The PR-ETF-PROFILE-02 slice converts the merged
    :class:`AkshareProfileRecord` rows into domain
    :class:`FieldEvidence` rows. Three evidence rows per record, in
    stable order — ``FUND_TYPE`` (TEXT), ``CATEGORY`` (TEXT),
    ``SHARES`` (DECIMAL). The mapper never emits ``AUM`` /
    ``MARKET_VALUE`` keys so the trading-day market value of an ETF
    cannot be silently rewritten as its assets under management.
    """

    @staticmethod
    def _build_profile_mapping(
        records: list[AkshareProfileRecord],
    ) -> object:
        from invest_pipeline.adapters.akshare.mapper import (
            AkshareProfileMappingResult,
        )

        return AkshareProfileMappingResult(
            records=tuple(records), warnings=()
        )

    @staticmethod
    def _confident_resolver(
        mapping: dict[tuple[str, str], InstrumentId] | None = None,
    ) -> callable:
        """Stable per-row resolver; defaults to a fresh InstrumentId."""

        table: dict[tuple[str, str], InstrumentId] = mapping or {}

        def _resolve(symbol: str, exchange: str) -> InstrumentId:
            key = (symbol, exchange)
            if key in table:
                return table[key]
            return InstrumentId.generate()

        return _resolve

    def test_emits_three_field_evidence_rows_per_complete_record(
        self,
    ) -> None:
        # A fully-populated ``AkshareProfileRecord`` produces three
        # evidence rows. ``fund_type`` / ``category`` ride as TEXT;
        # ``shares`` rides as DECIMAL; everything else is untouched.
        from invest_domain.etf_profile.models import (
            FieldKey,
            FieldValueType,
        )

        record = AkshareProfileRecord(
            symbol="510300",
            exchange="SSE",
            fund_type="ETF",
            category="Equity",
            shares=Decimal("1000000000"),
        )
        profile_mapping = self._build_profile_mapping([record])
        result = map_etf_profile_to_field_evidence(
            profile_mapping,
            instrument_id_resolver=self._confident_resolver(),
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            confidence_score=Decimal("0.95"),
        )
        self.assertEqual(result.warnings, ())
        self.assertEqual(len(result.evidence), 3)
        for evidence in result.evidence:
            assert isinstance(evidence, FieldEvidence)
            self.assertEqual(
                evidence.quality_status, QualityStatus.COMPLETE
            )
            self.assertEqual(evidence.confidence_score, Decimal("0.95"))
        keys = [entry.field_key for entry in result.evidence]
        self.assertEqual(
            keys,
            [FieldKey.FUND_TYPE, FieldKey.CATEGORY, FieldKey.SHARES],
        )
        value_types = [entry.value_type for entry in result.evidence]
        self.assertEqual(
            value_types,
            [FieldValueType.TEXT, FieldValueType.TEXT, FieldValueType.DECIMAL],
        )
        self.assertEqual(result.evidence[0].value, "ETF")
        self.assertEqual(result.evidence[1].value, "Equity")
        self.assertEqual(result.evidence[2].value, Decimal("1000000000"))

    def test_missing_source_fields_use_quality_status_missing(
        self,
    ) -> None:
        # ``AkshareProfileRecord`` may legitimately carry ``None`` for
        # any of the three verified fields. The mapper must preserve
        # ``None`` as the carrier for ``unknown`` and flag the row
        # ``MISSING`` so downstream analytics can distinguish
        # ``unknown`` from a real zero / empty value.
        from invest_domain.etf_profile.models import (
            FieldKey,
            FieldValueType,
        )

        record = AkshareProfileRecord(
            symbol="510300",
            exchange="SSE",
            fund_type=None,
            category="Equity",
            shares=None,
        )
        profile_mapping = self._build_profile_mapping([record])
        result = map_etf_profile_to_field_evidence(
            profile_mapping,
            instrument_id_resolver=self._confident_resolver(),
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            confidence_score=Decimal("0.5"),
        )
        self.assertEqual(len(result.evidence), 3)
        # ``FUND_TYPE`` is missing.
        self.assertEqual(result.evidence[0].field_key, FieldKey.FUND_TYPE)
        self.assertIsNone(result.evidence[0].value)
        self.assertEqual(result.evidence[0].value_type, FieldValueType.TEXT)
        self.assertEqual(
            result.evidence[0].quality_status, QualityStatus.MISSING
        )
        # ``CATEGORY`` is complete.
        self.assertEqual(result.evidence[1].field_key, FieldKey.CATEGORY)
        self.assertEqual(result.evidence[1].value, "Equity")
        self.assertEqual(
            result.evidence[1].quality_status, QualityStatus.COMPLETE
        )
        # ``SHARES`` is missing.
        self.assertEqual(result.evidence[2].field_key, FieldKey.SHARES)
        self.assertIsNone(result.evidence[2].value)
        self.assertEqual(
            result.evidence[2].value_type, FieldValueType.DECIMAL
        )
        self.assertEqual(
            result.evidence[2].quality_status, QualityStatus.MISSING
        )

    def test_field_order_and_count_are_stable(self) -> None:
        # Two records ⇒ exactly six evidence rows. Order is record
        # order (i.e. ``merge_etf_profile`` already sorts symbols
        # deterministically) and within each record the order is
        # ``FUND_TYPE`` → ``CATEGORY`` → ``SHARES``.
        from invest_domain.etf_profile.models import FieldKey

        records = [
            AkshareProfileRecord(
                symbol="159919",
                exchange="SZSE",
                fund_type="ETF",
                category="Equity",
                shares=Decimal("500000000"),
            ),
            AkshareProfileRecord(
                symbol="510300",
                exchange="SSE",
                fund_type="ETF",
                category="Bond",
                shares=Decimal("1000000000"),
            ),
        ]
        profile_mapping = self._build_profile_mapping(records)
        result = map_etf_profile_to_field_evidence(
            profile_mapping,
            instrument_id_resolver=self._confident_resolver(),
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            confidence_score=Decimal("0.9"),
        )
        self.assertEqual(result.warnings, ())
        self.assertEqual(len(result.evidence), 6)
        keys = [entry.field_key for entry in result.evidence]
        self.assertEqual(
            keys,
            [
                FieldKey.FUND_TYPE,
                FieldKey.CATEGORY,
                FieldKey.SHARES,
                FieldKey.FUND_TYPE,
                FieldKey.CATEGORY,
                FieldKey.SHARES,
            ],
        )
        # Each record's three rows share a single resolved
        # ``instrument_id``; the two records resolve to distinct ids.
        first_record_ids = {entry.instrument_id for entry in result.evidence[:3]}
        second_record_ids = {
            entry.instrument_id for entry in result.evidence[3:]
        }
        self.assertEqual(
            len(first_record_ids), 1,
            "All three rows of the first record must share one instrument_id",
        )
        self.assertEqual(
            len(second_record_ids), 1,
            "All three rows of the second record must share one instrument_id",
        )
        self.assertNotEqual(
            first_record_ids, second_record_ids,
            "Distinct records must resolve to distinct instrument ids",
        )

    def test_source_provenance_is_carried_on_every_row(self) -> None:
        # The shared ``FieldEvidenceSource`` carries the batch audit
        # fields. Pin the propagation so a future refactor that drops
        # the kwargs surfaces immediately.
        from invest_domain.etf_profile.models import (
            FieldKey,
            FieldValueType,
        )

        batch_id = uuid4()
        observed = _observed_at()
        record = AkshareProfileRecord(
            symbol="510300",
            exchange="SSE",
            fund_type="ETF",
            category="Equity",
            shares=Decimal("1000000000"),
        )
        profile_mapping = self._build_profile_mapping([record])
        result = map_etf_profile_to_field_evidence(
            profile_mapping,
            instrument_id_resolver=self._confident_resolver(),
            source_batch_id=batch_id,
            observed_at=observed,
            confidence_score=Decimal("0.7"),
            revision=2,
        )
        self.assertEqual(len(result.evidence), 3)
        for evidence in result.evidence:
            self.assertEqual(evidence.source.provider_key, "akshare")
            self.assertEqual(evidence.source.dataset_key, "etf_profile")
            self.assertEqual(evidence.source.observed_at, observed)
            self.assertEqual(evidence.source.source_batch_id, batch_id)
            self.assertEqual(evidence.source.revision, 2)
        # Distinct value_types are also pinned: ``SHARES`` is the only
        # DECIMAL row, the rest are TEXT.
        self.assertEqual(
            [(entry.field_key, entry.value_type) for entry in result.evidence],
            [
                (FieldKey.FUND_TYPE, FieldValueType.TEXT),
                (FieldKey.CATEGORY, FieldValueType.TEXT),
                (FieldKey.SHARES, FieldValueType.DECIMAL),
            ],
        )

    def test_resolver_is_called_with_symbol_and_exchange(self) -> None:
        # The mapper must thread ``(symbol, exchange)`` from the
        # :class:`AkshareProfileRecord` into the resolver so the
        # application service can look up the placeholder table.
        seen: list[tuple[str, str]] = []

        def _resolver(symbol: str, exchange: str) -> InstrumentId:
            seen.append((symbol, exchange))
            return InstrumentId.generate()

        record = AkshareProfileRecord(
            symbol="159919",
            exchange="SZSE",
            fund_type="ETF",
            category="Equity",
            shares=Decimal("500000000"),
        )
        profile_mapping = self._build_profile_mapping([record])
        map_etf_profile_to_field_evidence(
            profile_mapping,
            instrument_id_resolver=_resolver,
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            confidence_score=Decimal("0.9"),
        )
        self.assertEqual(seen, [("159919", "SZSE")])

    def test_resolver_failure_for_one_record_downgrades_to_warning(
        self,
    ) -> None:
        # The upstream ``core.instruments`` row may be missing for a
        # partial symbol set. The mapper must downgrade the failing
        # record to a warning and continue processing the surviving
        # records so a single missing placeholder never blocks the
        # whole batch.
        good_id = InstrumentId.generate()

        def _resolver(symbol: str, exchange: str) -> InstrumentId:
            if symbol == "159919":
                raise KeyError(
                    f"no instrument row for ({symbol!r}, {exchange!r})"
                )
            return good_id

        records = [
            AkshareProfileRecord(
                symbol="159919",
                exchange="SZSE",
                fund_type="ETF",
                category="Equity",
                shares=Decimal("500000000"),
            ),
            AkshareProfileRecord(
                symbol="510300",
                exchange="SSE",
                fund_type="ETF",
                category="Equity",
                shares=Decimal("1000000000"),
            ),
        ]
        profile_mapping = self._build_profile_mapping(records)
        result = map_etf_profile_to_field_evidence(
            profile_mapping,
            instrument_id_resolver=_resolver,
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            confidence_score=Decimal("0.9"),
        )
        # Three rows for ``510300`` survive; ``159919`` is downgraded.
        self.assertEqual(len(result.evidence), 3)
        self.assertEqual(len(result.warnings), 1)
        warning = result.warnings[0]
        self.assertIn("159919", warning)
        self.assertIn("SZSE", warning)
        self.assertIn("KeyError", warning)
        for evidence in result.evidence:
            self.assertEqual(evidence.instrument_id, good_id.value)

    def test_aum_and_market_value_are_never_emitted(self) -> None:
        # The conservative slice never emits ``AUM`` or
        # ``MARKET_VALUE`` rows so the trading-day market value of an
        # ETF cannot be silently rewritten as its assets under
        # management. Pin the closed-set vocabulary at the mapper
        # boundary.
        from invest_domain.etf_profile.models import FieldKey

        record = AkshareProfileRecord(
            symbol="510300",
            exchange="SSE",
            fund_type="ETF",
            category="Equity",
            shares=Decimal("1000000000"),
        )
        profile_mapping = self._build_profile_mapping([record])
        result = map_etf_profile_to_field_evidence(
            profile_mapping,
            instrument_id_resolver=self._confident_resolver(),
            source_batch_id=uuid4(),
            observed_at=_observed_at(),
            confidence_score=Decimal("0.9"),
        )
        emitted_keys = {entry.field_key for entry in result.evidence}
        self.assertEqual(
            emitted_keys,
            {FieldKey.FUND_TYPE, FieldKey.CATEGORY, FieldKey.SHARES},
        )
        self.assertNotIn(FieldKey.AUM, emitted_keys)
        self.assertNotIn(FieldKey.MARKET_VALUE, emitted_keys)
        self.assertNotIn(FieldKey.TURNOVER_VALUE, emitted_keys)

    def test_content_hash_is_deterministic(self) -> None:
        # Two mapping passes over the same input with the same kwargs
        # must produce identical ``content_hash`` digests so the audit
        # chain can identify the same observation across replays. The
        # resolver must therefore return the same ``InstrumentId``
        # across both calls — a fresh ``uuid4`` per call would
        # intentionally invalidate the digest.
        record = AkshareProfileRecord(
            symbol="510300",
            exchange="SSE",
            fund_type="ETF",
            category="Equity",
            shares=Decimal("1000000000"),
        )
        batch_id = uuid4()
        observed = _observed_at()
        confidence = Decimal("0.95")
        stable_id = InstrumentId.generate()

        def _stable_resolver(symbol: str, exchange: str) -> InstrumentId:
            return stable_id

        first = map_etf_profile_to_field_evidence(
            self._build_profile_mapping([record]),
            instrument_id_resolver=_stable_resolver,
            source_batch_id=batch_id,
            observed_at=observed,
            confidence_score=confidence,
        )
        second = map_etf_profile_to_field_evidence(
            self._build_profile_mapping([record]),
            instrument_id_resolver=_stable_resolver,
            source_batch_id=batch_id,
            observed_at=observed,
            confidence_score=confidence,
        )
        self.assertEqual(
            [entry.content_hash for entry in first.evidence],
            [entry.content_hash for entry in second.evidence],
        )
        # Hashes are 64 lowercase hex characters — pin the contract.
        for entry in first.evidence:
            self.assertEqual(len(entry.content_hash), 64)
            int(entry.content_hash, 16)

    def test_naive_observed_at_propagates_validation_error(self) -> None:
        # The ``FieldEvidenceSource`` validator rejects a naive
        # ``observed_at`` so the canonical hash stays deterministic
        # across processes and time zones. The mapper must propagate
        # the validation error rather than silently fabricating a
        # timezone.
        record = AkshareProfileRecord(
            symbol="510300",
            exchange="SSE",
            fund_type="ETF",
            category="Equity",
            shares=Decimal("1000000000"),
        )
        profile_mapping = self._build_profile_mapping([record])
        with self.assertRaises(ValueError) as ctx:
            map_etf_profile_to_field_evidence(
                profile_mapping,
                instrument_id_resolver=self._confident_resolver(),
                source_batch_id=uuid4(),
                observed_at=datetime(2026, 7, 30, 8, 0, 0),
                confidence_score=Decimal("0.95"),
            )
        self.assertIn("timezone-aware", str(ctx.exception))

    def test_invalid_confidence_propagates_validation_error(self) -> None:
        # A ``confidence_score`` outside ``[0, 1]`` is a Provider
        # contract violation. The mapper must propagate the validation
        # error rather than silently fabricating a default.
        record = AkshareProfileRecord(
            symbol="510300",
            exchange="SSE",
            fund_type="ETF",
            category="Equity",
            shares=Decimal("1000000000"),
        )
        profile_mapping = self._build_profile_mapping([record])
        with self.assertRaises(ValueError) as ctx:
            map_etf_profile_to_field_evidence(
                profile_mapping,
                instrument_id_resolver=self._confident_resolver(),
                source_batch_id=uuid4(),
                observed_at=_observed_at(),
                confidence_score=Decimal("1.5"),
            )
        self.assertIn("confidence_score", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
