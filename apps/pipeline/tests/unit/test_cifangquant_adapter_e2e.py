"""End-to-end adapter tests for the CifangQuant instrument provider.

These tests exercise :class:`CifangQuantInstrumentProvider` with a real
:class:`CifangClient` wired to ``httpx.MockTransport``, a no-op sleep,
and a deterministic clock. The Provider must:

- Refuse any call while ``CifangSettings.enabled=False``.
- Return the existing three-layer evidence bundle on success.
- Return a failed attempt with no batch on classified errors.
- Chunk 50+ symbols into at most ``MAX_SYMBOLS_PER_REQUEST`` per call.
- Never place the API key in evidence payloads, error messages or
  request parameters.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from typing import Any

import httpx
from invest_domain.market_data.models import (
    ProviderAttemptStatus,
    ProviderBatchStatus,
    ProviderFailureStage,
)
from invest_pipeline.adapters.cifang.adapter import CifangQuantInstrumentProvider
from invest_pipeline.adapters.cifang.client import CifangClient
from invest_pipeline.adapters.cifang.config import CifangSettings
from invest_pipeline.adapters.errors import (
    RealProviderRequiresExplicitEnablementError,
)

_SECRET_TOKEN = "e2e-secret-token"


def _build_enabled_settings(api_key: str = "") -> CifangSettings:
    """Build an enabled settings instance."""

    settings = CifangSettings(api_key=api_key)
    object.__setattr__(settings, "enabled", True)
    return settings


def _build_provider(
    handler,
    *,
    api_key: str = "",
    clock_value: datetime | None = None,
) -> CifangQuantInstrumentProvider:
    """Build an adapter whose transport is the supplied MockTransport."""

    settings = _build_enabled_settings(api_key=api_key)
    transport = httpx.MockTransport(handler)
    client = CifangClient(settings, transport=transport, sleep=lambda _seconds: None)
    if clock_value is None:
        clock_value = datetime(2026, 7, 30, 8, 0, 0, tzinfo=UTC)
    return CifangQuantInstrumentProvider(
        settings=settings,
        client=client,
        clock=lambda: clock_value,
    )


def _ok_list_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json=[
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
        ],
    )


def _ok_hist_em_handler(request: httpx.Request) -> httpx.Response:
    symbol = request.url.params.get("symbol", "")
    rows = []
    for offset in range(3):
        rows.append(
            {
                "symbol": symbol.split(",")[0],
                "exchange": "SH",
                "trade_date": (
                    date(2026, 7, 28 + offset).isoformat()
                ),
                "open": "3.10",
                "high": "3.18",
                "low": "3.08",
                "close": "3.15",
                "prev_close": "3.09",
                "volume": "1000",
                "amount": "3150000",
            }
        )
    return httpx.Response(200, json={"adjust": "none", "data": rows})


# ----------------------------------------------------------------------
# Default-disabled gate
# ----------------------------------------------------------------------


class CifangQuantAdapterDisabledGateTest(unittest.TestCase):
    """The adapter must not touch the network while ``enabled=False``."""

    def test_fetch_instruments_raises_when_disabled(self) -> None:
        provider = CifangQuantInstrumentProvider()
        with self.assertRaises(RealProviderRequiresExplicitEnablementError):
            provider.fetch_instruments(date(2026, 7, 30))

    def test_fetch_daily_bars_raises_when_disabled(self) -> None:
        provider = CifangQuantInstrumentProvider()
        with self.assertRaises(RealProviderRequiresExplicitEnablementError):
            provider.fetch_daily_bars(
                symbols=["510300"],
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 30),
            )


# ----------------------------------------------------------------------
# fetch_instruments evidence bundle
# ----------------------------------------------------------------------


class CifangQuantAdapterFetchInstrumentsTest(unittest.TestCase):
    """Successful ``/api/fund/list`` evidence tuple."""

    def test_returns_three_layer_success_bundle(self) -> None:
        provider = _build_provider(_ok_list_handler)
        try:
            request, attempt, batch = provider.fetch_instruments(
                date(2026, 7, 30)
            )
        finally:
            provider.close()

        self.assertEqual(request.provider_key, "cifangquant")
        self.assertEqual(request.dataset_key, "etf_instruments")
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertIsNotNone(batch)
        self.assertEqual(batch.status, ProviderBatchStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), 2)
        # Records carry the canonical ``SSE`` / ``SZSE`` exchange.
        exchanges = {record.exchange for record in batch.records}
        self.assertEqual(exchanges, {"SSE", "SZSE"})
        # No secret in params (defence in depth).
        self.assertNotIn(_SECRET_TOKEN, str(request.params))

    def test_request_params_contain_no_secret(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return _ok_list_handler(request)

        provider = _build_provider(handler, api_key=_SECRET_TOKEN)
        try:
            request, _, _ = provider.fetch_instruments(date(2026, 7, 30))
        finally:
            provider.close()
        # The token is on the wire (header) but must NOT be in the URL
        # or in ``ProviderRequest.params`` (ADR-0010 §5 / §6).
        self.assertNotIn(_SECRET_TOKEN, captured["url"])
        self.assertNotIn(_SECRET_TOKEN, str(request.params))


# ----------------------------------------------------------------------
# fetch_daily_bars evidence bundle + 50-symbol chunking
# ----------------------------------------------------------------------


class CifangQuantAdapterFetchDailyBarsTest(unittest.TestCase):
    """Successful ``/api/fund/hist_em`` evidence tuple."""

    def test_returns_three_layer_success_bundle(self) -> None:
        provider = _build_provider(_ok_hist_em_handler)
        try:
            request, attempt, batch = provider.fetch_daily_bars(
                symbols=["510300"],
                start_date=date(2026, 7, 28),
                end_date=date(2026, 7, 30),
            )
        finally:
            provider.close()

        self.assertEqual(request.provider_key, "cifangquant")
        self.assertEqual(request.dataset_key, "etf_daily_bars")
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertIsNotNone(batch)
        self.assertEqual(len(batch.records), 3)

    def test_splits_at_50_symbols_into_two_chunks(self) -> None:
        chunk_calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            symbols = request.url.params.get("symbol", "")
            chunk_calls.append(len(symbols.split(",")))
            return httpx.Response(
                200,
                json={
                    "adjust": "none",
                    "data": [
                        {
                            "symbol": symbols.split(",")[0],
                            "exchange": "SH",
                            "trade_date": "2026-07-30",
                            "open": "3.10",
                            "high": "3.18",
                            "low": "3.08",
                            "close": "3.15",
                            "prev_close": "3.09",
                            "volume": "1000",
                            "amount": "3150000",
                        }
                    ],
                },
            )

        symbols = [f"5{index:05d}" for index in range(75)]
        provider = _build_provider(handler)
        try:
            _, _, batch = provider.fetch_daily_bars(
                symbols=symbols,
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 30),
            )
        finally:
            provider.close()

        # Exactly 2 chunks: 50 + 25 (the documented 50-symbol limit).
        self.assertEqual(chunk_calls, [50, 25])
        # Batch aggregated the chunked rows; the warning mentions the split.
        self.assertIsNotNone(batch)
        self.assertTrue(
            any("chunked" in w.lower() for w in batch.warnings),
            f"expected chunking warning, got {batch.warnings!r}",
        )

    def test_empty_symbols_returns_empty_batch_with_no_http_call(
        self,
    ) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return _ok_hist_em_handler(request)

        provider = _build_provider(handler)
        try:
            _, attempt, batch = provider.fetch_daily_bars(
                symbols=[],
                start_date=date(2026, 7, 28),
                end_date=date(2026, 7, 30),
            )
        finally:
            provider.close()

        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(calls, 0)  # no HTTP roundtrip for empty input
        self.assertIsNotNone(batch)
        self.assertEqual(len(batch.records), 0)


# ----------------------------------------------------------------------
# Error classification through the evidence bundle
# ----------------------------------------------------------------------


class CifangQuantAdapterFailureTest(unittest.TestCase):
    """The adapter must surface Provider failures as typed evidence."""

    def _assert_failure_shape(
        self,
        attempt,
        *,
        stage: ProviderFailureStage,
        code_substring: str,
    ) -> None:
        self.assertEqual(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_stage, stage)
        self.assertIsNotNone(attempt.error_code)
        self.assertIn(code_substring, attempt.error_code)
        self.assertIsNotNone(attempt.error_message)
        # ``ProviderAttempt.__post_init__`` enforces the invariants.

    def test_authentication_failure_classifies_as_authentication_stage(
        self,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        provider = _build_provider(handler, api_key=_SECRET_TOKEN)
        try:
            _, attempt, batch = provider.fetch_instruments(
                date(2026, 7, 30)
            )
        finally:
            provider.close()
        self._assert_failure_shape(
            attempt,
            stage=ProviderFailureStage.AUTHENTICATION,
            code_substring="Authentication",
        )
        self.assertIsNone(batch)

    def test_rate_limit_failure_classifies_as_rate_limit_stage(
        self,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limited"})

        provider = _build_provider(handler)
        try:
            _, attempt, batch = provider.fetch_instruments(
                date(2026, 7, 30)
            )
        finally:
            provider.close()
        self._assert_failure_shape(
            attempt,
            stage=ProviderFailureStage.RATE_LIMIT,
            code_substring="RateLimit",
        )
        self.assertIsNone(batch)

    def test_5xx_failure_classifies_as_http_stage(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "down"})

        provider = _build_provider(handler)
        try:
            _, attempt, batch = provider.fetch_instruments(
                date(2026, 7, 30)
            )
        finally:
            provider.close()
        self._assert_failure_shape(
            attempt,
            stage=ProviderFailureStage.HTTP,
            code_substring="Unavailable",
        )
        self.assertIsNone(batch)

    def test_contract_failure_classifies_as_contract_stage(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            # ``data`` is missing, the mapper raises a contract error.
            return httpx.Response(200, json={"adjust": "none"})

        provider = _build_provider(handler)
        try:
            _, attempt, batch = provider.fetch_daily_bars(
                symbols=["510300"],
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 30),
            )
        finally:
            provider.close()
        self._assert_failure_shape(
            attempt,
            stage=ProviderFailureStage.CONTRACT,
            code_substring="DataContract",
        )
        self.assertIsNone(batch)


# ----------------------------------------------------------------------
# Port-shape compliance
# ----------------------------------------------------------------------


class CifangQuantAdapterPortTest(unittest.TestCase):
    """The adapter must remain substitutable for ``FixtureDevInstrumentProvider``."""

    def test_adapter_satisfies_etf_market_data_provider_protocol(self) -> None:
        from invest_domain.market_data.ports import EtfMarketDataProvider

        provider: EtfMarketDataProvider = _build_provider(_ok_list_handler)
        try:
            self.assertEqual(provider.provider_key, "cifangquant")
            request, attempt, batch = provider.fetch_instruments(
                date(2026, 7, 30)
            )
        finally:
            provider.close()
        self.assertEqual(request.provider_key, "cifangquant")
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertIsNotNone(batch)

    def test_placeholder_instrument_ids_are_stable_per_symbol(
        self,
    ) -> None:
        """Same symbol across two ``fetch_daily_bars`` calls gets the
        same domain ``instrument_id`` so the application service can
        re-resolve it without surprises."""

        provider = _build_provider(_ok_hist_em_handler)
        try:
            _, _, batch_one = provider.fetch_daily_bars(
                symbols=["510300"],
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 30),
            )
            _, _, batch_two = provider.fetch_daily_bars(
                symbols=["510300"],
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 30),
            )
        finally:
            provider.close()
        self.assertIsNotNone(batch_one)
        self.assertIsNotNone(batch_two)
        ids_one = {bar.instrument_id for bar in batch_one.records}
        ids_two = {bar.instrument_id for bar in batch_two.records}
        self.assertEqual(len(ids_one), 1)
        self.assertEqual(ids_one, ids_two)


if __name__ == "__main__":
    unittest.main()