"""Unit tests for :class:`invest_pipeline.adapters.akshare.adapter.AkshareInstrumentProvider`.

Coverage focus (PR-02 / NAV / calendar):

- The provider_key is the literal ``"akshare"``.
- The default ``AkshareSettings.enabled=False`` gate raises
  :class:`RealProviderRequiresExplicitEnablementError` for the
  ``fetch_instruments``, ``fetch_daily_bars``, ``fetch_nav`` and
  ``fetch_trading_calendar`` methods.
- Construction does not perform any network I/O and does not import
  the optional ``akshare`` SDK at all — only the lazily-resolving
  :class:`AkshareClient` opens the SDK on first call.
- A real ``akshare`` SDK import failure (no module installed) is
  translated by the client into
  :class:`ProviderUnavailableError` carrying ``provider_key="akshare"``
  with an install hint.
- Happy-path success: a stub ``akshare`` module injected via the
  client's ``module=`` kwarg produces a non-empty
  :class:`ProviderBatch[Instrument]` /
  :class:`ProviderBatch[DailyBar]` /
  :class:`ProviderBatch[AkshareNavRecord]` /
  :class:`ProviderBatch[AkshareCalendarRecord]`.
- Malformed rows downgrade to batch warnings rather than failing
  the request — the request stays successful and the surviving
  ``ProviderBatch`` carries the partial payload.
- NAV is **never** coerced into OHLCV — the NAV batch carries
  :class:`AkshareNavRecord` only (plan §5 Task 2).
- Deterministic request keys: identical arguments yield identical
  request_key strings.
- Per-symbol failure short-circuits to a single failed
  :class:`ProviderAttempt` carrying the typed classification.
- The factory's :func:`invest_pipeline.provider_factory.build_provider`
  rejects ``provider_key="akshare"`` with
  :class:`RealProviderRequiresExplicitEnablementError` when
  ``enabled=False`` and accepts the adapter when ``enabled=True``.
"""

from __future__ import annotations

import unittest
from collections.abc import Callable
from datetime import UTC, date, datetime
from types import ModuleType, SimpleNamespace
from typing import Any

from invest_domain.instruments.models import InstrumentId
from invest_domain.market_data.models import (
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderFailureStage,
    ProviderRequest,
)
from invest_pipeline.adapters.akshare.adapter import AkshareInstrumentProvider
from invest_pipeline.adapters.akshare.client import AkshareClient
from invest_pipeline.adapters.akshare.config import AkshareSettings
from invest_pipeline.adapters.akshare.mapper import (
    AkshareCalendarRecord,
    AkshareNavRecord,
)
from invest_pipeline.adapters.errors import (
    ProviderBadResponseError,
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.config import Settings
from invest_pipeline.provider_factory import KNOWN_PROVIDER_KEYS, build_provider


def _fixed_clock() -> Callable[[], datetime]:
    counter = {"now": 0}

    def _now() -> datetime:
        counter["now"] += 1
        return datetime(2026, 7, 30, 8, 0, 0, tzinfo=UTC)

    return _now


def _enabled_settings(**overrides: Any) -> AkshareSettings:
    """Return a fully-populated settings object with ``enabled=True``.

    Mirrors the Cifang test idiom of mutating the public ``enabled``
    flag post-construction via :func:`object.__setattr__` so the lock
    on ``adjust`` is preserved.
    """

    settings = AkshareSettings(**overrides)
    object.__setattr__(settings, "enabled", True)
    return settings


class AkshareProviderKeyTest(unittest.TestCase):
    def test_provider_key_is_akshare(self) -> None:
        provider = AkshareInstrumentProvider()
        self.assertEqual(provider.provider_key, "akshare")


class AkshareDisabledGateTest(unittest.TestCase):
    """Default ``enabled=False`` keeps the adapter inert."""

    def test_fetch_instruments_raises_real_provider_error(self) -> None:
        provider = AkshareInstrumentProvider()
        with self.assertRaises(RealProviderRequiresExplicitEnablementError) as ctx:
            provider.fetch_instruments(date(2026, 7, 30))
        message = str(ctx.exception)
        self.assertIn("akshare", message)
        self.assertIn("PR-02", message)
        self.assertIn("DATA-SOURCE-MIGRATION-MATRIX", message)

    def test_fetch_daily_bars_raises_real_provider_error(self) -> None:
        provider = AkshareInstrumentProvider()
        with self.assertRaises(RealProviderRequiresExplicitEnablementError) as ctx:
            provider.fetch_daily_bars(
                symbols=["510300"],
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 30),
            )
        self.assertIn("akshare", str(ctx.exception))

    def test_empty_symbols_still_raises_real_provider_error(self) -> None:
        # An empty symbol list should not bypass the enabled gate —
        # the gate runs before the empty-list shortcut.
        provider = AkshareInstrumentProvider()
        with self.assertRaises(RealProviderRequiresExplicitEnablementError):
            provider.fetch_daily_bars(
                symbols=[],
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 30),
            )

    def test_fetch_nav_raises_real_provider_error(self) -> None:
        provider = AkshareInstrumentProvider()
        with self.assertRaises(RealProviderRequiresExplicitEnablementError) as ctx:
            provider.fetch_nav("510300")
        self.assertIn("akshare", str(ctx.exception))
        self.assertIn("fetch_nav", str(ctx.exception))

    def test_fetch_trading_calendar_raises_real_provider_error(self) -> None:
        provider = AkshareInstrumentProvider()
        with self.assertRaises(RealProviderRequiresExplicitEnablementError) as ctx:
            provider.fetch_trading_calendar()
        self.assertIn("akshare", str(ctx.exception))
        self.assertIn("fetch_trading_calendar", str(ctx.exception))


class AkshareConstructionTest(unittest.TestCase):
    """Construction never performs any network I/O."""

    def test_construction_does_not_import_akshare(self) -> None:
        # The optional ``akshare`` SDK is resolved lazily by the
        # client, not at adapter construction time. A misconfigured
        # environment that lacks the SDK must not break
        # ``__init__``.
        provider = AkshareInstrumentProvider()
        self.assertEqual(provider.provider_key, "akshare")

    def test_construction_does_not_consult_client(self) -> None:
        # Patch ``fetch_fund_etf_fund_info_em`` and
        # ``fetch_fund_etf_hist_em`` to raise if either is called
        # during construction.
        from unittest.mock import patch

        sentinel = AssertionError("network call during construction")

        class _SentinelClient(AkshareClient):
            def fetch_fund_etf_fund_info_em(self) -> Any:
                raise sentinel

            def fetch_fund_etf_hist_em(self, **kwargs: Any) -> Any:
                raise sentinel

            def fetch_fund_etf_fund_daily_em(self, **kwargs: Any) -> Any:
                raise sentinel

            def fetch_tool_trade_date_hist_sina(self) -> Any:
                raise sentinel

        client = _SentinelClient(AkshareSettings())
        with (
            patch.object(
                AkshareClient,
                "fetch_fund_etf_fund_info_em",
                side_effect=sentinel,
            ),
            patch.object(
                AkshareClient,
                "fetch_fund_etf_hist_em",
                side_effect=sentinel,
            ),
            patch.object(
                AkshareClient,
                "fetch_fund_etf_fund_daily_em",
                side_effect=sentinel,
            ),
            patch.object(
                AkshareClient,
                "fetch_tool_trade_date_hist_sina",
                side_effect=sentinel,
            ),
        ):
            AkshareInstrumentProvider(client=client)
        # NoAssertionError means construction did not call any of the
        # fetch methods; the explicit ``_SentinelClient`` would also
        # raise if anything slipped through.


class AkshareLazyDependencyTest(unittest.TestCase):
    """Missing ``akshare`` SDK translates to a typed runtime error."""

    def test_missing_akshare_returns_failed_attempt_on_fetch(self) -> None:
        # The client uses a module_resolver that fails to import;
        # construction succeeds and the fetch returns the
        # ``(request, failed attempt, None)`` bundle whose
        # ``error_code`` / ``error_message`` prove the SDK was not
        # installed (matrix §10: lazy optional dependency). The
        # adapter catches the typed ``ProviderError`` so the call
        # site cannot leak a raw ``ImportError`` into domain code.
        def _missing_resolver() -> ModuleType:
            raise ModuleNotFoundError("akshare is not installed")

        client = AkshareClient(
            _enabled_settings(),
            module_resolver=_missing_resolver,
        )
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        request, attempt, batch = provider.fetch_instruments(date(2026, 7, 30))
        self.assertEqual(request.provider_key, "akshare")
        self.assertEqual(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_code, "ProviderUnavailableError")
        self.assertEqual(attempt.error_stage, ProviderFailureStage.HTTP)
        self.assertIsNone(batch)
        self.assertIn("pip install akshare", attempt.error_message)

    def test_missing_akshare_returns_failed_attempt_for_daily_bars(self) -> None:
        def _missing_resolver() -> ModuleType:
            raise ModuleNotFoundError("akshare is not installed")

        client = AkshareClient(
            _enabled_settings(),
            module_resolver=_missing_resolver,
        )
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        _, attempt, batch = provider.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 30),
        )
        self.assertEqual(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_code, "ProviderUnavailableError")
        self.assertIsNone(batch)


class AkshareSinaPriorityTest(unittest.TestCase):
    def _row(self, trade_date: str = "2026-07-30") -> dict[str, str]:
        return {
            "日期": trade_date,
            "开盘": "3.900",
            "收盘": "3.910",
            "最高": "3.920",
            "最低": "3.890",
            "成交量": "10000000",
        }

    def test_sina_success_does_not_call_eastmoney(self) -> None:
        calls = {"sina": 0, "em": 0}

        def _sina(**kwargs: Any) -> list[dict[str, str]]:
            calls["sina"] += 1
            return [self._row()]

        def _em(**kwargs: Any) -> list[dict[str, str]]:
            calls["em"] += 1
            return [self._row()]

        client = AkshareClient(
            _enabled_settings(),
            module=SimpleNamespace(
                fund_etf_hist_sina=_sina,
                fund_etf_hist_em=_em,
            ),
        )
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        _, _, batch = provider.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
        )
        assert batch is not None
        self.assertEqual(calls, {"sina": 1, "em": 0})
        self.assertEqual(batch.records[0].source.provider_key, "sina")

    def test_sina_failure_falls_back_to_eastmoney(self) -> None:
        calls = {"sina": 0, "em": 0}

        def _sina(**kwargs: Any) -> list[dict[str, str]]:
            calls["sina"] += 1
            raise RuntimeError("sina unavailable")

        def _em(**kwargs: Any) -> list[dict[str, str]]:
            calls["em"] += 1
            return [self._row()]

        client = AkshareClient(
            _enabled_settings(),
            module=SimpleNamespace(fund_etf_hist_sina=_sina, fund_etf_hist_em=_em),
        )
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        _, attempt, batch = provider.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
        )
        assert batch is not None
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(calls, {"sina": 1, "em": 1})
        self.assertEqual(batch.records[0].source.provider_key, "eastmoney")

    def test_sina_empty_falls_back_to_eastmoney(self) -> None:
        calls = {"sina": 0, "em": 0}
        def _sina(**kwargs: Any) -> list[dict[str, str]]:
            calls["sina"] += 1
            return []

        def _em(**kwargs: Any) -> list[dict[str, str]]:
            calls["em"] += 1
            return [self._row()]

        client = AkshareClient(
            _enabled_settings(),
            module=SimpleNamespace(
                fund_etf_hist_sina=_sina,
                fund_etf_hist_em=_em,
            ),
        )
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        _, _, batch = provider.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
        )
        assert batch is not None
        self.assertEqual(calls, {"sina": 1, "em": 1})


class AkshareMappingSuccessTest(unittest.TestCase):
    """End-to-end success path with an injected stub ``akshare`` module."""

    def test_fetch_instruments_returns_succeeded_batch(self) -> None:
        # The stub ``akshare`` module exposes the documented function
        # and returns a list-of-dicts (already normalised shape).
        stub_module = SimpleNamespace(
            fund_etf_fund_info_em=lambda: [
                {
                    "symbol": "510300",
                    "name": "沪深300ETF",
                    "exchange": "SH",
                    "list_date": "2012-05-04",
                    "status": "active",
                },
                {
                    "symbol": "159919",
                    "name": "嘉实沪深300ETF",
                    "exchange": "SZ",
                    "list_date": "2012-05-07",
                    "status": "active",
                },
            ],
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        request, attempt, batch = provider.fetch_instruments(date(2026, 7, 30))
        self._assert_success_shape(request, attempt, batch, expected_count=2)

    def test_fetch_daily_bars_returns_succeeded_batch(self) -> None:
        # The stub exposes ``fund_etf_hist_em`` and returns OHLCV rows.
        def _hist_em(**kwargs: Any) -> list[dict[str, Any]]:
            symbol = kwargs["symbol"]
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
            ] if symbol == "510300" else []

        stub_module = SimpleNamespace(fund_etf_hist_em=_hist_em)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        request, attempt, batch = provider.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
        )
        self._assert_success_shape(request, attempt, batch, expected_count=1)
        self.assertTrue(all(bar.trade_date == date(2026, 7, 30) for bar in batch.records))

    def test_fetch_daily_bars_fans_out_across_symbols(self) -> None:
        # When more than one symbol is supplied the adapter calls
        # ``fund_etf_hist_em`` once per symbol and aggregates the
        # resulting bars into a single ``ProviderBatch``. The stub
        # module returns two rows per symbol so the aggregate carries
        # all of them.
        def _hist_em(**kwargs: Any) -> list[dict[str, Any]]:
            kwargs["symbol"]  # sanity: the adapter passes the symbol
            return [
                {
                    "trade_date": "2026-07-30",
                    "open": "3.900",
                    "close": "3.910",
                    "high": "3.920",
                    "low": "3.890",
                    "volume": "10000000",
                },
                {
                    "trade_date": "2026-07-29",
                    "open": "3.870",
                    "close": "3.895",
                    "high": "3.900",
                    "low": "3.860",
                    "volume": "9000000",
                },
            ]

        stub_module = SimpleNamespace(fund_etf_hist_em=_hist_em)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        _, _, batch = provider.fetch_daily_bars(
            symbols=["510300", "510500"],
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 30),
        )
        assert batch is not None
        self.assertEqual(len(batch.records), 4)
        # A multi-symbol request carries the documented fan-out
        # warning so operators can spot the per-call partition.
        self.assertTrue(
            any("fans out" in warning for warning in batch.warnings),
            f"expected fan-out warning, got {batch.warnings!r}",
        )

    def test_fetch_daily_bars_empty_symbols_returns_succeeded_empty_batch(self) -> None:
        # An empty ``symbols`` list is a no-op — the adapter returns
        # a successful empty batch with a deterministic hash instead
        # of raising, mirroring the Cifang pattern.
        stub_module = SimpleNamespace(
            fund_etf_hist_em=lambda **kwargs: [],
            fund_etf_fund_info_em=lambda: [],
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        request, attempt, batch = provider.fetch_daily_bars(
            symbols=[],
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 30),
        )
        assert batch is not None
        self.assertEqual(batch.records, ())
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(batch.status, ProviderBatchStatus.SUCCEEDED)
        self.assertEqual(request.provider_key, "akshare")

    def test_request_key_is_deterministic(self) -> None:
        # Identical arguments must yield identical ``request_key``
        # values so the application service can detect
        # idempotent re-collects.
        stub_module = SimpleNamespace(fund_etf_fund_info_em=lambda: [])
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        first_request, _, _ = provider.fetch_instruments(date(2026, 7, 30))
        second_request, _, _ = provider.fetch_instruments(date(2026, 7, 30))
        self.assertEqual(first_request.request_key, second_request.request_key)
        self.assertEqual(
            first_request.request_key,
            "instruments-2026-07-30",
        )

    def test_daily_bars_request_key_is_deterministic(self) -> None:
        stub_module = SimpleNamespace(fund_etf_hist_em=lambda **kwargs: [])
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        first_request, _, _ = provider.fetch_daily_bars(
            symbols=["510300", "510500"],
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 30),
        )
        second_request, _, _ = provider.fetch_daily_bars(
            symbols=["510300", "510500"],
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 30),
        )
        self.assertEqual(first_request.request_key, second_request.request_key)
        self.assertEqual(
            first_request.request_key,
            "daily-bars-2026-07-23-2026-07-30-510300-510500",
        )

    def _assert_success_shape(
        self,
        request: ProviderRequest,
        attempt: ProviderAttempt,
        batch: ProviderBatch | None,
        *,
        expected_count: int,
    ) -> None:
        self.assertEqual(request.provider_key, "akshare")
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual(batch.status, ProviderBatchStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), expected_count)
        self.assertEqual(len(batch.raw_payload_hash), 64)


class AkshareNavSuccessTest(unittest.TestCase):
    """End-to-end NAV success path with an injected stub ``akshare`` module."""

    def test_fetch_nav_returns_succeeded_batch(self) -> None:
        # The stub exposes ``fund_etf_fund_daily_em`` and returns
        # NAV rows; the adapter must stamp a successful batch
        # carrying :class:`AkshareNavRecord` records (never
        # :class:`DailyBar`) and the dedicated ``dataset_key``.
        stub_module = SimpleNamespace(
            fund_etf_fund_daily_em=lambda **kwargs: [
                {
                    "trade_date": "2026-07-30",
                    "unit_nav": "1.234",
                    "accumulated_nav": "1.567",
                    "daily_growth_rate": "0.5",
                },
                {
                    "trade_date": "2026-07-29",
                    "unit_nav": "1.230",
                    "accumulated_nav": "1.560",
                    "daily_growth_rate": "0.2",
                },
            ],
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        request, attempt, batch = provider.fetch_nav("510300")
        self.assertEqual(request.dataset_key, "etf_nav")
        self.assertEqual(request.request_key, "nav-510300")
        self.assertEqual(request.params, {"symbol": "510300"})
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        assert batch is not None
        self.assertEqual(batch.status, ProviderBatchStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), 2)
        self.assertEqual(len(batch.warnings), 0)
        self.assertEqual(len(batch.raw_payload_hash), 64)
        # Every record must be the dedicated NAV record type — the
        # adapter must never coerce NAV into a :class:`DailyBar`.
        for record in batch.records:
            self.assertIsInstance(record, AkshareNavRecord)
            self.assertEqual(record.symbol, "510300")

    def test_fetch_nav_empty_payload_returns_empty_batch(self) -> None:
        stub_module = SimpleNamespace(
            fund_etf_fund_daily_em=lambda **kwargs: []
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        request, attempt, batch = provider.fetch_nav("510300")
        assert batch is not None
        self.assertEqual(batch.records, ())
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(batch.status, ProviderBatchStatus.SUCCEEDED)
        self.assertEqual(request.provider_key, "akshare")

    def test_fetch_nav_missing_sdk_returns_failed_attempt(self) -> None:
        def _missing_resolver() -> ModuleType:
            raise ModuleNotFoundError("akshare is not installed")

        client = AkshareClient(
            _enabled_settings(),
            module_resolver=_missing_resolver,
        )
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        request, attempt, batch = provider.fetch_nav("510300")
        self.assertEqual(request.dataset_key, "etf_nav")
        self.assertEqual(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_code, "ProviderUnavailableError")
        self.assertIn("pip install akshare", attempt.error_message)
        self.assertIsNone(batch)

    def test_fetch_nav_invalid_symbol_raises_value_error(self) -> None:
        # The adapter validates ``symbol`` before consulting the
        # client so a bad input never reaches the SDK.
        provider = AkshareInstrumentProvider(settings=_enabled_settings())
        with self.assertRaises(ValueError):
            provider.fetch_nav("")
        with self.assertRaises(ValueError):
            provider.fetch_nav("   ")

    def test_fetch_nav_does_not_coerce_to_ohlcv(self) -> None:
        # A stub payload that *contains* OHLCV-shaped fields must
        # still come out as ``AkshareNavRecord`` only — the mapper
        # never reads OHLCV aliases for the NAV surface.
        stub_module = SimpleNamespace(
            fund_etf_fund_daily_em=lambda **kwargs: [
                {
                    "trade_date": "2026-07-30",
                    "unit_nav": "1.234",
                    "open": "1.234",
                    "high": "1.300",
                    "low": "1.200",
                    "close": "1.250",
                    "volume": "1000000",
                },
            ],
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        _, _, batch = provider.fetch_nav("510300")
        assert batch is not None
        self.assertEqual(len(batch.records), 1)
        record = batch.records[0]
        self.assertIsInstance(record, AkshareNavRecord)
        # OHLCV-shaped fields must not leak onto the NAV record.
        self.assertFalse(hasattr(record, "open"))
        self.assertFalse(hasattr(record, "high"))
        self.assertFalse(hasattr(record, "low"))
        self.assertFalse(hasattr(record, "close"))
        self.assertFalse(hasattr(record, "volume"))
        self.assertFalse(hasattr(record, "amount"))

    def test_fetch_nav_request_key_is_deterministic(self) -> None:
        stub_module = SimpleNamespace(
            fund_etf_fund_daily_em=lambda **kwargs: []
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        first, _, _ = provider.fetch_nav("510300")
        second, _, _ = provider.fetch_nav("510300")
        self.assertEqual(first.request_key, second.request_key)
        self.assertEqual(first.request_key, "nav-510300")


class AkshareCalendarSuccessTest(unittest.TestCase):
    """End-to-end trading-calendar success path with an injected stub module."""

    def test_fetch_trading_calendar_returns_succeeded_batch(self) -> None:
        # The stub exposes ``tool_trade_date_hist_sina`` and returns
        # a date-only payload; the adapter must stamp a successful
        # batch carrying :class:`AkshareCalendarRecord` entries.
        stub_module = SimpleNamespace(
            tool_trade_date_hist_sina=lambda: [
                {"trade_date": "2026-07-29"},
                {"trade_date": "2026-07-30"},
            ],
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        request, attempt, batch = provider.fetch_trading_calendar()
        self.assertEqual(request.dataset_key, "trading_calendar")
        self.assertEqual(request.request_key, "trading-calendar")
        self.assertEqual(request.params, {})
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        assert batch is not None
        self.assertEqual(batch.status, ProviderBatchStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), 2)
        self.assertEqual(len(batch.warnings), 0)
        self.assertEqual(len(batch.raw_payload_hash), 64)
        for entry in batch.records:
            self.assertIsInstance(entry, AkshareCalendarRecord)

    def test_fetch_trading_calendar_empty_payload_returns_empty_batch(self) -> None:
        stub_module = SimpleNamespace(
            tool_trade_date_hist_sina=lambda: []
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        _, _, batch = provider.fetch_trading_calendar()
        assert batch is not None
        self.assertEqual(batch.records, ())
        self.assertEqual(batch.status, ProviderBatchStatus.SUCCEEDED)

    def test_fetch_trading_calendar_missing_sdk_returns_failed_attempt(
        self,
    ) -> None:
        def _missing_resolver() -> ModuleType:
            raise ModuleNotFoundError("akshare is not installed")

        client = AkshareClient(
            _enabled_settings(),
            module_resolver=_missing_resolver,
        )
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        request, attempt, batch = provider.fetch_trading_calendar()
        self.assertEqual(request.dataset_key, "trading_calendar")
        self.assertEqual(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_code, "ProviderUnavailableError")
        self.assertIsNone(batch)

    def test_fetch_trading_calendar_request_key_is_deterministic(self) -> None:
        stub_module = SimpleNamespace(
            tool_trade_date_hist_sina=lambda: []
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        first, _, _ = provider.fetch_trading_calendar()
        second, _, _ = provider.fetch_trading_calendar()
        self.assertEqual(first.request_key, second.request_key)
        self.assertEqual(first.request_key, "trading-calendar")


class AkshareMalformedRowsTest(unittest.TestCase):
    """Malformed rows downgrade to warnings, not failure."""

    def test_malformed_master_row_raises_contract_failure(self) -> None:
        # A row missing ``symbol`` is a contract violation that the
        # mapper surfaces as :class:`ProviderDataContractError`. The
        # adapter translates the failure into a single failed
        # attempt with no batch.
        stub_module = SimpleNamespace(
            fund_etf_fund_info_em=lambda: [
                {"name": "ETF-A"},
            ],
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        request, attempt, batch = provider.fetch_instruments(date(2026, 7, 30))
        self.assertEqual(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_code, "ProviderDataContractError")
        self.assertEqual(attempt.error_stage, ProviderFailureStage.CONTRACT)
        self.assertIsNone(batch)
        self.assertEqual(request.provider_key, "akshare")

    def test_malformed_daily_row_downgrades_to_warning(self) -> None:
        # A row missing ``high`` is a row-level downgrade — the
        # batch stays successful and the surviving rows are kept.
        def _hist_em(**kwargs: Any) -> list[dict[str, Any]]:
            return [
                {
                    "trade_date": "2026-07-30",
                    "open": "3.900",
                    "close": "3.910",
                    # high missing -> row-level skip
                    "low": "3.890",
                    "volume": "10000000",
                },
                {
                    "trade_date": "2026-07-29",
                    "open": "3.870",
                    "close": "3.895",
                    "high": "3.900",
                    "low": "3.860",
                    "volume": "9000000",
                },
            ]

        stub_module = SimpleNamespace(fund_etf_hist_em=_hist_em)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        _, attempt, batch = provider.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 30),
        )
        assert batch is not None
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), 1)
        self.assertEqual(len(batch.warnings), 1)
        self.assertIn("missing required OHLC", batch.warnings[0])

    def test_per_symbol_failure_short_circuits_attempt(self) -> None:
        # A Provider-level exception on the second symbol short-
        # circuits the remaining symbols and produces a single
        # failed attempt with no batch.
        def _hist_em(**kwargs: Any) -> list[dict[str, Any]]:
            symbol = kwargs["symbol"]
            if symbol == "510500":
                raise ProviderBadResponseError(
                    "akshare",
                    "fund_etf_hist_em() raised ValueError: bad",
                )
            return [
                {
                    "trade_date": "2026-07-30",
                    "open": "3.900",
                    "close": "3.910",
                    "high": "3.920",
                    "low": "3.890",
                    "volume": "10000000",
                },
            ]

        stub_module = SimpleNamespace(fund_etf_hist_em=_hist_em)
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        _, attempt, batch = provider.fetch_daily_bars(
            symbols=["510300", "510500"],
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 30),
        )
        self.assertEqual(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_stage, ProviderFailureStage.DECODE)
        self.assertEqual(attempt.error_code, "ProviderBadResponseError")
        self.assertIn("510500", attempt.error_message)
        self.assertIsNone(batch)


class AkshareSymbolResolutionTest(unittest.TestCase):
    """``symbol_for_instrument_id`` round-trips placeholder UUIDs."""

    def test_symbol_for_instrument_id_returns_resolved_symbol(self) -> None:
        stub_module = SimpleNamespace(
            fund_etf_hist_em=lambda **kwargs: [
                {
                    "trade_date": "2026-07-30",
                    "open": "3.900",
                    "close": "3.910",
                    "high": "3.920",
                    "low": "3.890",
                    "volume": "10000000",
                },
            ],
        )
        client = AkshareClient(_enabled_settings(), module=stub_module)
        provider = AkshareInstrumentProvider(
            settings=_enabled_settings(), client=client
        )
        _, _, batch = provider.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
        )
        assert batch is not None
        bar = batch.records[0]
        resolved = provider.symbol_for_instrument_id(bar.instrument_id)
        self.assertEqual(resolved, "510300")

    def test_symbol_for_instrument_id_returns_none_for_unknown(self) -> None:
        provider = AkshareInstrumentProvider(settings=_enabled_settings())
        # An unseeded UUID must resolve to None so the application
        # service surfaces a hard error rather than silently picking
        # the first cached symbol.
        self.assertIsNone(
            provider.symbol_for_instrument_id(InstrumentId.generate())
        )


class AkshareFactoryIntegrationTest(unittest.TestCase):
    """The factory extension behind the explicit ``enabled=true`` gate."""

    def test_known_provider_keys_include_akshare(self) -> None:
        self.assertIn("akshare", KNOWN_PROVIDER_KEYS)

    def test_factory_rejects_akshare_when_disabled(self) -> None:
        # Default ``enabled=False`` keeps the factory rejected path
        # open so a misconfigured environment cannot silently hit
        # AkShare's upstream.
        settings = Settings(provider_key="akshare")
        akshare = AkshareSettings()  # enabled=False
        with self.assertRaises(RealProviderRequiresExplicitEnablementError) as ctx:
            build_provider(settings, akshare_settings=akshare)
        message = str(ctx.exception)
        self.assertIn("akshare", message)
        self.assertIn("INVEST_PIPELINE_AKSHARE_ENABLED", message)
        self.assertIn("DATA-SOURCE-MIGRATION-MATRIX", message)

    def test_factory_rejects_unknown_provider_key(self) -> None:
        # The factory continues to surface ``UnknownProviderError``
        # for keys outside the supported set; the new branch is
        # strictly opt-in.
        settings = Settings(provider_key="rsscast")
        with self.assertRaises(KeyError) as ctx:
            build_provider(settings)
        self.assertEqual(ctx.exception.args[0], "rsscast")

    def test_factory_still_rejects_unknown_provider_even_with_akshare_enabled(
        self,
    ) -> None:
        settings = Settings(provider_key="some-future-provider")
        with self.assertRaises(KeyError):
            build_provider(settings, akshare_settings=_enabled_settings())

    def test_factory_returns_adapter_when_akshare_enabled(self) -> None:
        # When the explicit gate is satisfied the factory must hand
        # back the real adapter rather than falling back to the
        # fixture provider.
        settings = Settings(provider_key="akshare")
        adapter = build_provider(
            settings,
            akshare_settings=_enabled_settings(),
        )
        self.assertIsInstance(adapter, AkshareInstrumentProvider)
        self.assertEqual(adapter.provider_key, "akshare")


if __name__ == "__main__":
    unittest.main()
