"""Focused offline tests for the AkShare client DC-3 exposure methods.

The :mod:`invest_pipeline.adapters.akshare.client` module owns the
lazy import of the optional ``akshare`` SDK. This module covers the
three DC-3 atomic transport methods:

- :meth:`AkshareClient.fetch_index_stock_cons_weight_csindex` accepts a
  non-empty stripped 6-digit numeric ``index_code`` and routes through
  ``ak.index_stock_cons_weight_csindex(symbol=...)``.
- :meth:`AkshareClient.fetch_fund_overview_em` accepts a non-empty
  stripped 6-digit numeric ``etf_code`` and routes through
  ``ak.fund_overview_em(symbol=...)``.
- :meth:`AkshareClient.fetch_fund_portfolio_hold_em` accepts a
  non-empty stripped 6-digit ``etf_code`` and a ``year`` that is either
  empty string or exactly 4 digits; routes through
  ``ak.fund_portfolio_hold_em(symbol=..., date=...)``.

All three methods honour the existing typed-error contract:
``ProviderUnavailableError`` for missing SDK functions,
``ProviderBadResponseError`` for upstream exceptions, ``ValueError``
for bad input. All three methods normalise the pandas ``DataFrame``
returns to a list of plain ``dict`` records and stamp the canonical
SHA-256 response hash.

The tests inject a stub ``akshare`` module via the client's
``module=`` kwarg so CI never has the real SDK installed.
"""

from __future__ import annotations

import unittest
from types import ModuleType, SimpleNamespace
from typing import Any

from invest_pipeline.adapters.akshare.client import AkshareClient, AkshareResponse
from invest_pipeline.adapters.akshare.config import AkshareSettings
from invest_pipeline.adapters.errors import (
    ProviderBadResponseError,
    ProviderUnavailableError,
)


def _enabled_settings(**overrides: Any) -> AkshareSettings:
    """Return a settings object with ``enabled=True``."""
    settings = AkshareSettings(**overrides)
    object.__setattr__(settings, "enabled", True)
    return settings


# ----------------------------------------------------------------------
# fetch_index_stock_cons_weight_csindex
# ----------------------------------------------------------------------


class AkshareClientIndexConsWeightCsindexTest(unittest.TestCase):
    """:meth:`AkshareClient.fetch_index_stock_cons_weight_csindex` happy path."""

    def test_returns_normalised_records(self) -> None:
        stub_module = SimpleNamespace(
            index_stock_cons_weight_csindex=lambda **kwargs: [
                {
                    "日期": "2026-07-30",
                    "指数代码": "000300",
                    "指数名称": "沪深300",
                    "成分券代码": "600036",
                    "成分券名称": "招商银行",
                    "权重": "5.1234",
                },
            ]
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        response = client.fetch_index_stock_cons_weight_csindex(index_code="000300")
        assert isinstance(response, AkshareResponse)
        self.assertEqual(response.operation, "index_stock_cons_weight_csindex")
        self.assertEqual(len(response.raw_payload), 1)
        self.assertEqual(len(response.raw_payload_hash), 64)

    def test_passes_symbol_kwarg_stripped(self) -> None:
        captured: dict[str, Any] = {}

        def _capture(**kwargs: Any) -> list[dict[str, Any]]:
            captured.update(kwargs)
            return []

        stub_module = SimpleNamespace(index_stock_cons_weight_csindex=_capture)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        client.fetch_index_stock_cons_weight_csindex(index_code="  000300  ")
        self.assertEqual(captured, {"symbol": "000300"})

    def test_invalid_index_code_raises_value_error(self) -> None:
        stub_module = SimpleNamespace(index_stock_cons_weight_csindex=lambda **k: [])
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ValueError):
            client.fetch_index_stock_cons_weight_csindex(index_code="")
        with self.assertRaises(ValueError):
            client.fetch_index_stock_cons_weight_csindex(index_code="   ")
        with self.assertRaises(ValueError):
            client.fetch_index_stock_cons_weight_csindex(index_code="00030")
        with self.assertRaises(ValueError):
            client.fetch_index_stock_cons_weight_csindex(index_code="0003000")
        with self.assertRaises(ValueError):
            client.fetch_index_stock_cons_weight_csindex(index_code="000ABC")

    def test_missing_sdk_function_raises_unavailable(self) -> None:
        stub_module = SimpleNamespace(__version__="99.0.0")
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderUnavailableError) as ctx:
            client.fetch_index_stock_cons_weight_csindex(index_code="000300")
        self.assertIn("index_stock_cons_weight_csindex", str(ctx.exception))
        self.assertIn("99.0.0", str(ctx.exception))

    def test_upstream_exception_is_wrapped_as_bad_response(self) -> None:
        def _raise(**kwargs: Any) -> list[dict[str, Any]]:
            raise RuntimeError("upstream 503")

        stub_module = SimpleNamespace(index_stock_cons_weight_csindex=_raise)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderBadResponseError) as ctx:
            client.fetch_index_stock_cons_weight_csindex(index_code="000300")
        self.assertIn("RuntimeError", str(ctx.exception))
        self.assertIn("upstream 503", str(ctx.exception))

    def test_no_sdk_import_on_construction(self) -> None:
        import sys
        key = "akshare"
        was_loaded = key in sys.modules

        class _SilentResolver:
            def __call__(self) -> ModuleType:
                raise ModuleNotFoundError("not installed")

        AkshareClient(
            _enabled_settings(),
            module_resolver=_SilentResolver(),
        )
        self.assertEqual(key in sys.modules, was_loaded)


# ----------------------------------------------------------------------
# fetch_fund_overview_em
# ----------------------------------------------------------------------


class AkshareClientFundOverviewEmTest(unittest.TestCase):
    """:meth:`AkshareClient.fetch_fund_overview_em` happy path."""

    def test_returns_normalised_records(self) -> None:
        stub_module = SimpleNamespace(
            fund_overview_em=lambda **kwargs: [
                {
                    "基金代码": "510300",
                    "基金简称": "华泰柏瑞沪深300ETF",
                    "基金类型": "ETF",
                    "跟踪标的": "沪深300",
                },
            ]
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        response = client.fetch_fund_overview_em(etf_code="510300")
        assert isinstance(response, AkshareResponse)
        self.assertEqual(response.operation, "fund_overview_em")
        self.assertEqual(len(response.raw_payload), 1)
        self.assertEqual(len(response.raw_payload_hash), 64)

    def test_passes_symbol_kwarg_stripped(self) -> None:
        captured: dict[str, Any] = {}

        def _capture(**kwargs: Any) -> list[dict[str, Any]]:
            captured.update(kwargs)
            return []

        stub_module = SimpleNamespace(fund_overview_em=_capture)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        client.fetch_fund_overview_em(etf_code="  510300  ")
        self.assertEqual(captured, {"symbol": "510300"})

    def test_invalid_etf_code_raises_value_error(self) -> None:
        stub_module = SimpleNamespace(fund_overview_em=lambda **k: [])
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ValueError):
            client.fetch_fund_overview_em(etf_code="")
        with self.assertRaises(ValueError):
            client.fetch_fund_overview_em(etf_code="   ")
        with self.assertRaises(ValueError):
            client.fetch_fund_overview_em(etf_code="51030")
        with self.assertRaises(ValueError):
            client.fetch_fund_overview_em(etf_code="0510300")
        with self.assertRaises(ValueError):
            client.fetch_fund_overview_em(etf_code="51ABC0")

    def test_missing_sdk_function_raises_unavailable(self) -> None:
        stub_module = SimpleNamespace(__version__="99.0.0")
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderUnavailableError) as ctx:
            client.fetch_fund_overview_em(etf_code="510300")
        self.assertIn("fund_overview_em", str(ctx.exception))
        self.assertIn("99.0.0", str(ctx.exception))

    def test_upstream_exception_is_wrapped_as_bad_response(self) -> None:
        def _raise(**kwargs: Any) -> list[dict[str, Any]]:
            raise ValueError("network blip")

        stub_module = SimpleNamespace(fund_overview_em=_raise)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderBadResponseError) as ctx:
            client.fetch_fund_overview_em(etf_code="510300")
        self.assertIn("ValueError", str(ctx.exception))
        self.assertIn("network blip", str(ctx.exception))

    def test_hash_is_deterministic(self) -> None:
        stub_module = SimpleNamespace(
            fund_overview_em=lambda **kwargs: [{"基金代码": "510300"}]
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        r1 = client.fetch_fund_overview_em(etf_code="510300")
        r2 = client.fetch_fund_overview_em(etf_code="510300")
        self.assertEqual(r1.raw_payload_hash, r2.raw_payload_hash)


# ----------------------------------------------------------------------
# fetch_fund_portfolio_hold_em
# ----------------------------------------------------------------------


class AkshareClientFundPortfolioHoldEmTest(unittest.TestCase):
    """:meth:`AkshareClient.fetch_fund_portfolio_hold_em` happy path."""

    def test_returns_normalised_records(self) -> None:
        stub_module = SimpleNamespace(
            fund_portfolio_hold_em=lambda **kwargs: [
                {
                    "序号": "1",
                    "股票代码": "600036",
                    "股票名称": "招商银行",
                    "占净值比例": "5.12",
                    "持股数": "1000000",
                    "持仓市值": "50000000",
                    "季度": "2024年4季度",
                },
            ]
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        response = client.fetch_fund_portfolio_hold_em(etf_code="510300")
        assert isinstance(response, AkshareResponse)
        self.assertEqual(response.operation, "fund_portfolio_hold_em")
        self.assertEqual(len(response.raw_payload), 1)
        self.assertEqual(len(response.raw_payload_hash), 64)

    def test_passes_symbol_and_date_kwargs_stripped(self) -> None:
        captured: dict[str, Any] = {}

        def _capture(**kwargs: Any) -> list[dict[str, Any]]:
            captured.update(kwargs)
            return []

        stub_module = SimpleNamespace(fund_portfolio_hold_em=_capture)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        client.fetch_fund_portfolio_hold_em(etf_code="  510300  ", year="  2024  ")
        self.assertEqual(captured, {"symbol": "510300", "date": "2024"})

    def test_empty_year_passes_empty_string(self) -> None:
        captured: dict[str, Any] = {}

        def _capture(**kwargs: Any) -> list[dict[str, Any]]:
            captured.update(kwargs)
            return []

        stub_module = SimpleNamespace(fund_portfolio_hold_em=_capture)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        client.fetch_fund_portfolio_hold_em(etf_code="510300", year="")
        self.assertEqual(captured, {"symbol": "510300", "date": ""})

    def test_invalid_etf_code_raises_value_error(self) -> None:
        stub_module = SimpleNamespace(fund_portfolio_hold_em=lambda **k: [])
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ValueError):
            client.fetch_fund_portfolio_hold_em(etf_code="", year="")
        with self.assertRaises(ValueError):
            client.fetch_fund_portfolio_hold_em(etf_code="   ", year="")
        with self.assertRaises(ValueError):
            client.fetch_fund_portfolio_hold_em(etf_code="51030", year="")
        with self.assertRaises(ValueError):
            client.fetch_fund_portfolio_hold_em(etf_code="5103000", year="")
        with self.assertRaises(ValueError):
            client.fetch_fund_portfolio_hold_em(etf_code="51ABC0", year="")

    def test_invalid_year_raises_value_error(self) -> None:
        stub_module = SimpleNamespace(fund_portfolio_hold_em=lambda **k: [])
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ValueError):
            client.fetch_fund_portfolio_hold_em(etf_code="510300", year="202")
        with self.assertRaises(ValueError):
            client.fetch_fund_portfolio_hold_em(etf_code="510300", year="20245")
        with self.assertRaises(ValueError):
            client.fetch_fund_portfolio_hold_em(etf_code="510300", year="ABCD")
        with self.assertRaises(ValueError):
            client.fetch_fund_portfolio_hold_em(etf_code="510300", year=None)  # type: ignore[arg-type]

    def test_missing_sdk_function_raises_unavailable(self) -> None:
        stub_module = SimpleNamespace(__version__="99.0.0")
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderUnavailableError) as ctx:
            client.fetch_fund_portfolio_hold_em(etf_code="510300")
        self.assertIn("fund_portfolio_hold_em", str(ctx.exception))
        self.assertIn("99.0.0", str(ctx.exception))

    def test_upstream_exception_is_wrapped_as_bad_response(self) -> None:
        def _raise(**kwargs: Any) -> list[dict[str, Any]]:
            raise RuntimeError("upstream 503")

        stub_module = SimpleNamespace(fund_portfolio_hold_em=_raise)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderBadResponseError) as ctx:
            client.fetch_fund_portfolio_hold_em(etf_code="510300")
        self.assertIn("RuntimeError", str(ctx.exception))
        self.assertIn("upstream 503", str(ctx.exception))

    def test_hash_is_deterministic(self) -> None:
        stub_module = SimpleNamespace(
            fund_portfolio_hold_em=lambda **kwargs: [{"股票代码": "600036"}]
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        r1 = client.fetch_fund_portfolio_hold_em(etf_code="510300", year="")
        r2 = client.fetch_fund_portfolio_hold_em(etf_code="510300", year="")
        self.assertEqual(r1.raw_payload_hash, r2.raw_payload_hash)


if __name__ == "__main__":
    unittest.main()
