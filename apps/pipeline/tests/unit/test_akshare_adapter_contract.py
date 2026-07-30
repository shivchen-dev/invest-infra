from __future__ import annotations

import re
import unittest
from datetime import date

from invest_pipeline.providers import (
    PROVIDER_KEY_AKSHARE,
    AkshareEtfMarketDataProvider,
    ProviderAuthenticationError,
)
from invest_pipeline.providers.capabilities import ProviderCapability
from invest_pipeline.providers.errors import ProviderAdapterNotImplementedError


_AKSHARE_TOKEN = "AKSHARE_SANDBOX_TOKEN_NOT_USED_IN_V2"


class AkshareAdapterContractTest(unittest.TestCase):
    def test_provider_key_is_akshare(self) -> None:
        provider = AkshareEtfMarketDataProvider(
            token=_AKSHARE_TOKEN,
            base_url="https://example.invalid/akshare",
            timeout_seconds=10.0,
        )
        self.assertEqual(provider.provider_key, PROVIDER_KEY_AKSHARE)

    def test_adjustment_is_locked_to_none(self) -> None:
        provider = AkshareEtfMarketDataProvider(
            token=_AKSHARE_TOKEN,
            base_url="https://example.invalid/akshare",
            timeout_seconds=10.0,
        )
        self.assertEqual(provider.adjustment, "none")

    def test_constructed_capabilities_match_archive_facts(self) -> None:
        declaration = AkshareEtfMarketDataProvider.declaration
        self.assertIn(ProviderCapability.ETF_INSTRUMENTS, declaration.capabilities)
        self.assertIn(ProviderCapability.ETF_DAILY_BARS, declaration.capabilities)
        self.assertIn(ProviderCapability.ETF_TRADING_CALENDAR, declaration.capabilities)

    def test_fetch_instruments_raises_not_implemented(self) -> None:
        provider = AkshareEtfMarketDataProvider(
            token=_AKSHARE_TOKEN,
            base_url="https://example.invalid/akshare",
            timeout_seconds=10.0,
        )
        with self.assertRaises(ProviderAdapterNotImplementedError):
            provider.fetch_instruments(date(2026, 7, 30))

    def test_fetch_daily_bars_raises_not_implemented(self) -> None:
        provider = AkshareEtfMarketDataProvider(
            token=_AKSHARE_TOKEN,
            base_url="https://example.invalid/akshare",
            timeout_seconds=10.0,
        )
        with self.assertRaises(ProviderAdapterNotImplementedError):
            provider.fetch_daily_bars(
                symbols=("510300",),
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 30),
            )

    def test_fetch_trading_calendar_raises_not_implemented(self) -> None:
        provider = AkshareEtfMarketDataProvider(
            token=_AKSHARE_TOKEN,
            base_url="https://example.invalid/akshare",
            timeout_seconds=10.0,
        )
        with self.assertRaises(ProviderAdapterNotImplementedError):
            provider.fetch_trading_calendar(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 30),
            )

    def test_no_token_raises_authentication_error(self) -> None:
        with self.assertRaises(ProviderAuthenticationError):
            AkshareEtfMarketDataProvider(
                token="",
                base_url="https://example.invalid/akshare",
                timeout_seconds=10.0,
            )

    def test_token_does_not_appear_in_repr(self) -> None:
        provider = AkshareEtfMarketDataProvider(
            token=_AKSHARE_TOKEN,
            base_url="https://example.invalid/akshare",
            timeout_seconds=10.0,
        )
        self.assertNotIn(_AKSHARE_TOKEN, repr(provider))
        self.assertNotIn(_AKSHARE_TOKEN, str(provider.config))
        self.assertNotIn(_AKSHARE_TOKEN, repr(provider.config))
        # Sanitized dict must be free of any token.
        sanitized = provider.config.sanitized_dict()
        self.assertNotIn("token", sanitized)
        self.assertNotIn(_AKSHARE_TOKEN, repr(sanitized))

    def test_risk_warnings_are_recorded(self) -> None:
        declaration = AkshareEtfMarketDataProvider.declaration
        joined = " ".join(declaration.risk_warnings).lower()
        self.assertIn("rate-limit", joined)
        self.assertIn("sla", joined)


class AkshareCredentialRedactionTest(unittest.TestCase):
    def test_construction_without_token_does_not_echo_token(self) -> None:
        try:
            AkshareEtfMarketDataProvider(
                token="",
                base_url="https://example.invalid/akshare",
                timeout_seconds=10.0,
            )
        except ProviderAuthenticationError as exc:
            self.assertNotIn(_AKSHARE_TOKEN, str(exc))

    def test_not_implemented_message_does_not_echo_token(self) -> None:
        provider = AkshareEtfMarketDataProvider(
            token=_AKSHARE_TOKEN,
            base_url="https://example.invalid/akshare",
            timeout_seconds=10.0,
        )
        try:
            provider.fetch_instruments(date(2026, 7, 30))
        except ProviderAdapterNotImplementedError as exc:
            message = str(exc)
            self.assertNotIn(_AKSHARE_TOKEN, message)
            self.assertRegex(message, re.compile(r"O-1|ADR-0003", re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
