"""Focused offline tests for the AkShare client NAV / calendar methods.

The :mod:`invest_pipeline.adapters.akshare.client` module owns the
lazy import of the optional ``akshare`` SDK. The adapter tests in
``test_akshare_adapter.py`` already cover the master-data /
daily-bars client methods end-to-end. This module pins the new
NAV / trading-calendar client methods:

- :meth:`AkshareClient.fetch_fund_etf_fund_daily_em` accepts a
  six-digit ``symbol`` and routes through ``ak.fund_etf_fund_daily_em``.
- :meth:`AkshareClient.fetch_tool_trade_date_hist_sina` returns the
  read-only SSE / SZSE trading-calendar payload through
  ``ak.tool_trade_date_hist_sina``.
- Both methods honour the existing typed-error contract:
  ``ProviderUnavailableError`` for missing SDK functions,
  ``ProviderBadResponseError`` for upstream exceptions,
  ``ValueError`` for bad input.
- Both methods normalise the pandas ``DataFrame`` returns to a list
  of plain ``dict`` records so the rest of the adapter stack stays
  ``pandas``-free.
- Both methods stamp the existing canonical SHA-256 response hash
  on the returned :class:`AkshareResponse`.
- :meth:`AkshareClient.fetch_fund_etf_hist_em` retries transient
  ``OSError`` subclasses raised by the SDK call with deterministic
  ``1.0`` / ``2.0`` second exponential delays while never retrying
  non-``OSError`` exceptions or dataframe-normalisation failures; the
  constructor validates ``max_attempts >= 1`` and accepts an injected
  ``sleep`` callable.

The tests inject a stub ``akshare`` module via the client's
``module=`` kwarg so CI never has the real SDK installed.
"""

from __future__ import annotations

import unittest
from datetime import date
from types import ModuleType, SimpleNamespace
from typing import Any

from invest_pipeline.adapters.akshare.client import AkshareClient, AkshareResponse
from invest_pipeline.adapters.akshare.config import AkshareSettings
from invest_pipeline.adapters.errors import (
    ProviderBadResponseError,
    ProviderUnavailableError,
)


def _enabled_settings(**overrides: Any) -> AkshareSettings:
    """Return a settings object with ``enabled=True``.

    The Akshare ``adjust`` lock must remain in force so the post-
    construction mutation is the smallest change that flips the
    default-on gate.
    """

    settings = AkshareSettings(**overrides)
    object.__setattr__(settings, "enabled", True)
    return settings


class AkshareClientNavFetchTest(unittest.TestCase):
    """:meth:`AkshareClient.fetch_fund_etf_fund_daily_em` happy path."""

    def test_returns_normalised_records(self) -> None:
        # The stub returns a list-of-dicts (already-normalised shape).
        # The client passes through unchanged and stamps a hex hash.
        stub_module = SimpleNamespace(
            fund_etf_fund_daily_em=lambda **kwargs: [
                {
                    "净值日期": "2026-07-30",
                    "单位净值": "1.234",
                    "累计净值": "1.567",
                    "日增长率": "0.5",
                },
            ]
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        response = client.fetch_fund_etf_fund_daily_em(symbol="510300")
        assert isinstance(response, AkshareResponse)
        self.assertEqual(response.operation, "fund_etf_fund_daily_em")
        self.assertEqual(
            response.raw_payload,
            [
                {
                    "净值日期": "2026-07-30",
                    "单位净值": "1.234",
                    "累计净值": "1.567",
                    "日增长率": "0.5",
                },
            ],
        )
        self.assertEqual(len(response.raw_payload_hash), 64)

    def test_passes_symbol_kwarg_through(self) -> None:
        captured: dict[str, Any] = {}

        def _capture(**kwargs: Any) -> list[dict[str, Any]]:
            captured.update(kwargs)
            return []

        stub_module = SimpleNamespace(fund_etf_fund_daily_em=_capture)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        client.fetch_fund_etf_fund_daily_em(symbol="159919")
        self.assertEqual(captured, {"symbol": "159919"})

    def test_blank_symbol_raises_value_error(self) -> None:
        client = AkshareClient(_enabled_settings(), module=SimpleNamespace())
        with self.assertRaises(ValueError):
            client.fetch_fund_etf_fund_daily_em(symbol="")
        with self.assertRaises(ValueError):
            client.fetch_fund_etf_fund_daily_em(symbol="   ")

    def test_missing_sdk_function_raises_unavailable(self) -> None:
        # A stub that lacks ``fund_etf_fund_daily_em`` simulates an
        # SDK upgrade that renamed the function. The client must
        # raise the typed ``ProviderUnavailableError`` carrying the
        # install hint so the adapter surfaces a clean failure.
        stub_module = SimpleNamespace(__version__="99.0.0")
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderUnavailableError) as ctx:
            client.fetch_fund_etf_fund_daily_em(symbol="510300")
        message = str(ctx.exception)
        self.assertIn("fund_etf_fund_daily_em", message)
        self.assertIn("99.0.0", message)

    def test_upstream_exception_is_wrapped_as_bad_response(self) -> None:
        def _raise(**kwargs: Any) -> list[dict[str, Any]]:
            raise ValueError("network blip")

        stub_module = SimpleNamespace(fund_etf_fund_daily_em=_raise)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderBadResponseError) as ctx:
            client.fetch_fund_etf_fund_daily_em(symbol="510300")
        self.assertIn("ValueError", str(ctx.exception))
        self.assertIn("network blip", str(ctx.exception))


class AkshareClientCalendarFetchTest(unittest.TestCase):
    """:meth:`AkshareClient.fetch_tool_trade_date_hist_sina` happy path."""

    def test_returns_normalised_records(self) -> None:
        stub_module = SimpleNamespace(
            tool_trade_date_hist_sina=lambda: [
                {"trade_date": "2026-07-29"},
                {"trade_date": "2026-07-30"},
            ]
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        response = client.fetch_tool_trade_date_hist_sina()
        assert isinstance(response, AkshareResponse)
        self.assertEqual(response.operation, "tool_trade_date_hist_sina")
        self.assertEqual(len(response.raw_payload), 2)
        self.assertEqual(len(response.raw_payload_hash), 64)

    def test_missing_sdk_function_raises_unavailable(self) -> None:
        stub_module = SimpleNamespace(__version__="99.0.0")
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderUnavailableError) as ctx:
            client.fetch_tool_trade_date_hist_sina()
        self.assertIn("tool_trade_date_hist_sina", str(ctx.exception))

    def test_upstream_exception_is_wrapped_as_bad_response(self) -> None:
        def _raise() -> list[dict[str, Any]]:
            raise RuntimeError("upstream 503")

        stub_module = SimpleNamespace(tool_trade_date_hist_sina=_raise)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderBadResponseError) as ctx:
            client.fetch_tool_trade_date_hist_sina()
        self.assertIn("upstream 503", str(ctx.exception))


class AkshareClientSinaFetchTest(unittest.TestCase):
    def test_passes_market_prefixed_symbol_and_filters_range(self) -> None:
        captured: dict[str, Any] = {}

        def _capture(**kwargs: Any) -> list[dict[str, Any]]:
            captured.update(kwargs)
            return [
                {"日期": "2026-07-22", "收盘": "1"},
                {"日期": "2026-07-23", "收盘": "2"},
                {"日期": "2026-07-30", "收盘": "3"},
                {"日期": "2026-07-31", "收盘": "4"},
            ]

        client = AkshareClient(
            _enabled_settings(),
            module=SimpleNamespace(fund_etf_hist_sina=_capture),
        )
        response = client.fetch_fund_etf_hist_sina(
            symbol="510300",
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 30),
        )
        self.assertEqual(captured, {"symbol": "sh510300"})
        self.assertEqual(
            [row["日期"] for row in response.raw_payload],
            ["2026-07-23", "2026-07-30"],
        )

    def test_shenzhen_symbol_uses_sz_prefix(self) -> None:
        captured: dict[str, Any] = {}
        client = AkshareClient(
            _enabled_settings(),
            module=SimpleNamespace(
                fund_etf_hist_sina=lambda **kwargs: captured.update(kwargs) or []
            ),
        )
        client.fetch_fund_etf_hist_sina(
            symbol="159919",
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 30),
        )
        self.assertEqual(captured["symbol"], "sz159919")

    def test_upstream_failure_is_typed(self) -> None:
        client = AkshareClient(
            _enabled_settings(),
            module=SimpleNamespace(
                fund_etf_hist_sina=lambda **kwargs: (_ for _ in ()).throw(
                    RuntimeError("upstream 503")
                )
            ),
        )
        with self.assertRaises(ProviderBadResponseError) as ctx:
            client.fetch_fund_etf_hist_sina(
                symbol="510300",
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 30),
            )
        self.assertIn("upstream 503", str(ctx.exception))

    def test_missing_sdk_function_is_typed(self) -> None:
        client = AkshareClient(_enabled_settings(), module=SimpleNamespace())
        with self.assertRaises(ProviderUnavailableError):
            client.fetch_fund_etf_hist_sina(
                symbol="510300",
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 30),
            )


class AkshareClientModuleResolutionTest(unittest.TestCase):
    """The lazy ``module_resolver`` path is preserved for NAV / calendar."""

    def test_missing_akshare_sdk_translates_to_unavailable(self) -> None:
        def _missing() -> ModuleType:
            raise ModuleNotFoundError("akshare is not installed")

        client = AkshareClient(
            _enabled_settings(),
            module_resolver=_missing,
        )
        with self.assertRaises(ProviderUnavailableError) as ctx:
            client.fetch_fund_etf_fund_daily_em(symbol="510300")
        self.assertIn("pip install akshare", str(ctx.exception))
        with self.assertRaises(ProviderUnavailableError) as ctx:
            client.fetch_tool_trade_date_hist_sina()
        self.assertIn("pip install akshare", str(ctx.exception))


class AkshareClientFundNameEmFetchTest(unittest.TestCase):
    """:meth:`AkshareClient.fetch_fund_name_em` happy path."""

    def test_returns_normalised_records(self) -> None:
        # The stub returns a list-of-dicts (already-normalised shape).
        # The client passes through unchanged and stamps a hex hash.
        stub_module = SimpleNamespace(
            fund_name_em=lambda: [
                {"基金代码": "510300", "基金简称": "华泰柏瑞沪深300ETF", "基金类型": "ETF"},
                {"基金代码": "159919", "基金简称": "嘉实沪深300ETF", "基金类型": "ETF"},
            ]
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        response = client.fetch_fund_name_em()
        assert isinstance(response, AkshareResponse)
        self.assertEqual(response.operation, "fund_name_em")
        self.assertEqual(len(response.raw_payload), 2)
        self.assertEqual(len(response.raw_payload_hash), 64)

    def test_missing_sdk_function_raises_unavailable(self) -> None:
        # A stub that lacks ``fund_name_em`` simulates an SDK upgrade
        # that renamed the function. The client must raise the typed
        # ``ProviderUnavailableError`` carrying the install hint so
        # the adapter surfaces a clean failure.
        stub_module = SimpleNamespace(__version__="99.0.0")
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderUnavailableError) as ctx:
            client.fetch_fund_name_em()
        self.assertIn("fund_name_em", str(ctx.exception))
        self.assertIn("99.0.0", str(ctx.exception))

    def test_upstream_exception_is_wrapped_as_bad_response(self) -> None:
        def _raise() -> list[dict[str, Any]]:
            raise RuntimeError("upstream 503")

        stub_module = SimpleNamespace(fund_name_em=_raise)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderBadResponseError) as ctx:
            client.fetch_fund_name_em()
        self.assertIn("upstream 503", str(ctx.exception))


class AkshareClientFundEtfSpotEmFetchTest(unittest.TestCase):
    """:meth:`AkshareClient.fetch_fund_etf_spot_em` happy path."""

    def test_returns_normalised_records(self) -> None:
        stub_module = SimpleNamespace(
            fund_etf_spot_em=lambda: [
                {"代码": "510300", "名称": "华泰柏瑞沪深300ETF", "最新份额": "1000000000"},
                {"代码": "159919", "名称": "嘉实沪深300ETF", "最新份额": "500000000"},
            ]
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        response = client.fetch_fund_etf_spot_em()
        assert isinstance(response, AkshareResponse)
        self.assertEqual(response.operation, "fund_etf_spot_em")
        self.assertEqual(len(response.raw_payload), 2)
        self.assertEqual(len(response.raw_payload_hash), 64)

    def test_missing_sdk_function_raises_unavailable(self) -> None:
        stub_module = SimpleNamespace(__version__="99.0.0")
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderUnavailableError) as ctx:
            client.fetch_fund_etf_spot_em()
        self.assertIn("fund_etf_spot_em", str(ctx.exception))

    def test_upstream_exception_is_wrapped_as_bad_response(self) -> None:
        def _raise() -> list[dict[str, Any]]:
            raise RuntimeError("upstream 503")

        stub_module = SimpleNamespace(fund_etf_spot_em=_raise)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        with self.assertRaises(ProviderBadResponseError) as ctx:
            client.fetch_fund_etf_spot_em()
        self.assertIn("upstream 503", str(ctx.exception))


class AkshareClientFundEtfHistEmRetryTest(unittest.TestCase):
    """:meth:`AkshareClient.fetch_fund_etf_hist_em` bounded retry contract."""

    @staticmethod
    def _hist_em_payload() -> list[dict[str, Any]]:
        return [
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

    def test_oserror_then_success_retries_with_single_delay(self) -> None:
        calls = {"count": 0}
        sleep_calls: list[float] = []

        def _hist_em(**kwargs: Any) -> list[dict[str, Any]]:
            calls["count"] += 1
            if calls["count"] == 1:
                raise ConnectionError("transient connection reset")
            return self._hist_em_payload()

        def _sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        client = AkshareClient(
            _enabled_settings(),
            module=SimpleNamespace(fund_etf_hist_em=_hist_em),
            sleep=_sleep,
        )
        response = client.fetch_fund_etf_hist_em(
            symbol="510300",
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
        )
        self.assertEqual(calls["count"], 2)
        self.assertEqual(sleep_calls, [1.0])
        assert isinstance(response, AkshareResponse)
        self.assertEqual(response.operation, "fund_etf_hist_em")
        self.assertEqual(len(response.raw_payload), 1)
        self.assertEqual(len(response.raw_payload_hash), 64)

    def test_persistent_oserror_exhausts_three_attempts_then_raises(self) -> None:
        calls = {"count": 0}
        sleep_calls: list[float] = []

        def _hist_em(**kwargs: Any) -> list[dict[str, Any]]:
            calls["count"] += 1
            raise OSError("upstream unreachable")

        def _sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        client = AkshareClient(
            _enabled_settings(),
            module=SimpleNamespace(fund_etf_hist_em=_hist_em),
            sleep=_sleep,
        )
        with self.assertRaises(ProviderBadResponseError) as ctx:
            client.fetch_fund_etf_hist_em(
                symbol="510300",
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 30),
            )
        self.assertEqual(calls["count"], 3)
        self.assertEqual(sleep_calls, [1.0, 2.0])
        self.assertEqual(ctx.exception.provider_key, "akshare")
        self.assertIn("OSError", str(ctx.exception))
        self.assertIn("upstream unreachable", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, OSError)

    def test_max_attempts_four_extends_exponential_delays_before_exhaustion(self) -> None:
        # ``max_attempts=4`` keeps the ``1.0 * 2 ** (attempt - 1)``
        # schedule so the three retry sleeps land at
        # ``[1.0, 2.0, 4.0]`` before the final attempt raises.
        calls = {"count": 0}
        sleep_calls: list[float] = []

        def _hist_em(**kwargs: Any) -> list[dict[str, Any]]:
            calls["count"] += 1
            raise OSError("upstream unreachable")

        def _sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        client = AkshareClient(
            _enabled_settings(),
            module=SimpleNamespace(fund_etf_hist_em=_hist_em),
            sleep=_sleep,
            max_attempts=4,
        )
        with self.assertRaises(ProviderBadResponseError) as ctx:
            client.fetch_fund_etf_hist_em(
                symbol="510300",
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 30),
            )
        self.assertEqual(calls["count"], 4)
        self.assertEqual(sleep_calls, [1.0, 2.0, 4.0])
        self.assertEqual(ctx.exception.provider_key, "akshare")
        self.assertIn("OSError", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, OSError)

    def test_non_retryable_value_error_runs_once_without_sleep(self) -> None:
        calls = {"count": 0}
        sleep_calls: list[float] = []

        def _hist_em(**kwargs: Any) -> list[dict[str, Any]]:
            calls["count"] += 1
            raise ValueError("malformed upstream schema")

        def _sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        client = AkshareClient(
            _enabled_settings(),
            module=SimpleNamespace(fund_etf_hist_em=_hist_em),
            sleep=_sleep,
        )
        with self.assertRaises(ProviderBadResponseError) as ctx:
            client.fetch_fund_etf_hist_em(
                symbol="510300",
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 30),
            )
        self.assertEqual(calls["count"], 1)
        self.assertEqual(sleep_calls, [])
        self.assertIn("ValueError", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, ValueError)

    def test_dataframe_normalization_failure_does_not_retry(self) -> None:
        calls = {"count": 0}
        sleep_calls: list[float] = []

        def _hist_em(**kwargs: Any) -> list[dict[str, Any]]:
            calls["count"] += 1
            # Return a dataframe whose ``to_dict`` raises ``ValueError``
            # so the normaliser converts it into
            # ``ProviderBadResponseError``. The retry loop must not
            # re-invoke the SDK because the call itself succeeded.
            return _DataFrameRaisingOnToDict()

        def _sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        client = AkshareClient(
            _enabled_settings(),
            module=SimpleNamespace(fund_etf_hist_em=_hist_em),
            sleep=_sleep,
        )
        with self.assertRaises(ProviderBadResponseError) as ctx:
            client.fetch_fund_etf_hist_em(
                symbol="510300",
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 30),
            )
        self.assertEqual(calls["count"], 1)
        self.assertEqual(sleep_calls, [])
        self.assertIn("not a serialisable", str(ctx.exception))

    def test_invalid_max_attempts_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            AkshareClient(_enabled_settings(), max_attempts=0)
        self.assertIn("max_attempts", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            AkshareClient(_enabled_settings(), max_attempts=-1)
        self.assertIn("max_attempts", str(ctx.exception))


class _DataFrameRaisingOnToDict:
    """Stub dataframe whose ``to_dict`` raises ``ValueError``.

    The normaliser catches the ``ValueError`` raised here and converts
    it into :class:`ProviderBadResponseError`; the retry loop must
    leave the SDK call count at one because the call itself succeeded.
    """

    def to_dict(self, orient: str = "dict") -> list[dict[str, Any]]:
        raise ValueError(f"unsupported orient={orient!r}")


if __name__ == "__main__":
    unittest.main()
