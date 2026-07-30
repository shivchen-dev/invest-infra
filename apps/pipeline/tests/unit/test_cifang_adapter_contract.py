from __future__ import annotations

import unittest
from datetime import date

from invest_pipeline.providers import (
    PROVIDER_KEY_CIFANG,
    CifangEtfMarketDataProvider,
    ProviderAuthenticationError,
)
from invest_pipeline.providers.capabilities import ProviderCapability
from invest_pipeline.providers.errors import ProviderAdapterNotImplementedError

_CIFANG_TOKEN = "CIFANG_SANDBOX_TOKEN_NOT_USED_IN_V2"


class CifangAdapterContractTest(unittest.TestCase):
    def test_provider_key_is_cifang(self) -> None:
        provider = CifangEtfMarketDataProvider(
            token=_CIFANG_TOKEN,
            base_url="https://www.cifangquant.com/api",
            adjustment="none",
            timeout_seconds=10.0,
        )
        self.assertEqual(provider.provider_key, PROVIDER_KEY_CIFANG)

    def test_adjustment_is_locked_to_none(self) -> None:
        provider = CifangEtfMarketDataProvider(
            token=_CIFANG_TOKEN,
            base_url="https://www.cifangquant.com/api",
            adjustment="none",
            timeout_seconds=10.0,
        )
        self.assertEqual(provider.adjustment, "none")

    def test_qfq_adjustment_rejected_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            CifangEtfMarketDataProvider(
                token=_CIFANG_TOKEN,
                base_url="https://www.cifangquant.com/api",
                adjustment="qfq",
                timeout_seconds=10.0,
            )

    def test_hfq_adjustment_rejected_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            CifangEtfMarketDataProvider(
                token=_CIFANG_TOKEN,
                base_url="https://www.cifangquant.com/api",
                adjustment="hfq",
                timeout_seconds=10.0,
            )

    def test_declared_capabilities_match_archive_facts(self) -> None:
        declaration = CifangEtfMarketDataProvider.declaration
        self.assertIn(ProviderCapability.ETF_INSTRUMENTS, declaration.capabilities)
        self.assertIn(ProviderCapability.ETF_DAILY_BARS, declaration.capabilities)

    def test_fetch_instruments_raises_not_implemented(self) -> None:
        provider = CifangEtfMarketDataProvider(
            token=_CIFANG_TOKEN,
            base_url="https://www.cifangquant.com/api",
            adjustment="none",
            timeout_seconds=10.0,
        )
        with self.assertRaises(ProviderAdapterNotImplementedError):
            provider.fetch_instruments(date(2026, 7, 30))

    def test_fetch_daily_bars_raises_not_implemented(self) -> None:
        provider = CifangEtfMarketDataProvider(
            token=_CIFANG_TOKEN,
            base_url="https://www.cifangquant.com/api",
            adjustment="none",
            timeout_seconds=10.0,
        )
        with self.assertRaises(ProviderAdapterNotImplementedError):
            provider.fetch_daily_bars(
                symbols=("510300",),
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 30),
            )

    def test_no_token_raises_authentication_error(self) -> None:
        with self.assertRaises(ProviderAuthenticationError):
            CifangEtfMarketDataProvider(
                token="",
                base_url="https://www.cifangquant.com/api",
                adjustment="none",
                timeout_seconds=10.0,
            )

    def test_token_does_not_appear_in_repr(self) -> None:
        provider = CifangEtfMarketDataProvider(
            token=_CIFANG_TOKEN,
            base_url="https://www.cifangquant.com/api",
            adjustment="none",
            timeout_seconds=10.0,
        )
        self.assertNotIn(_CIFANG_TOKEN, repr(provider))
        self.assertNotIn(_CIFANG_TOKEN, str(provider.config))
        self.assertNotIn(_CIFANG_TOKEN, repr(provider.config))
        sanitized = provider.config.sanitized_dict()
        self.assertNotIn("token", sanitized)
        self.assertNotIn(_CIFANG_TOKEN, repr(sanitized))

    def test_qfq_warning_present(self) -> None:
        declaration = CifangEtfMarketDataProvider.declaration
        joined = " ".join((declaration.notes, *declaration.risk_warnings)).lower()
        self.assertIn("qfq", joined)


class CifangAdapterCredentialRedactionTest(unittest.TestCase):
    def test_construction_without_token_does_not_echo_token(self) -> None:
        try:
            CifangEtfMarketDataProvider(
                token="",
                base_url="https://www.cifangquant.com/api",
                adjustment="none",
                timeout_seconds=10.0,
            )
        except ProviderAuthenticationError as exc:
            self.assertNotIn(_CIFANG_TOKEN, str(exc))

    def test_not_implemented_message_does_not_echo_token(self) -> None:
        provider = CifangEtfMarketDataProvider(
            token=_CIFANG_TOKEN,
            base_url="https://www.cifangquant.com/api",
            adjustment="none",
            timeout_seconds=10.0,
        )
        try:
            provider.fetch_daily_bars(
                symbols=("510300",),
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 30),
            )
        except ProviderAdapterNotImplementedError as exc:
            message = str(exc)
            self.assertNotIn(_CIFANG_TOKEN, message)
            self.assertTrue(
                "qfq" not in message.lower() or "must not" in message.lower(),
                msg=f"unexpected message text: {message!r}",
            )


if __name__ == "__main__":
    unittest.main()
