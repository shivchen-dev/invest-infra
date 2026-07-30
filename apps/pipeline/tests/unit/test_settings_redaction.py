from __future__ import annotations

import unittest

from invest_pipeline.providers.akshare.adapter import AkshareEtfMarketDataProvider
from invest_pipeline.providers.akshare.config import AkshareAdapterConfig
from invest_pipeline.providers.cifang.adapter import CifangEtfMarketDataProvider
from invest_pipeline.providers.cifang.config import CifangAdapterConfig


_AKSHARE_TOKEN = "AKSHARE_TEST_TOKEN_DO_NOT_LOG"
_CIFANG_TOKEN = "CIFANG_TEST_TOKEN_DO_NOT_LOG"


class AkshareConfigRedactionTest(unittest.TestCase):
    def test_sanitized_dict_omits_token(self) -> None:
        config = AkshareAdapterConfig(
            token=_AKSHARE_TOKEN,
            base_url="https://example.invalid/akshare",
            timeout_seconds=10.0,
        )
        sanitized = config.sanitized_dict()
        self.assertNotIn("token", sanitized)
        self.assertNotIn(_AKSHARE_TOKEN, repr(sanitized))
        self.assertEqual(sanitized["base_url"], "https://example.invalid/akshare")

    def test_repr_does_not_leak_token(self) -> None:
        config = AkshareAdapterConfig(
            token=_AKSHARE_TOKEN,
            base_url="https://example.invalid/akshare",
            timeout_seconds=10.0,
        )
        self.assertNotIn(_AKSHARE_TOKEN, repr(config))

    def test_str_does_not_leak_token(self) -> None:
        config = AkshareAdapterConfig(
            token=_AKSHARE_TOKEN,
            base_url="https://example.invalid/akshare",
            timeout_seconds=10.0,
        )
        self.assertNotIn(_AKSHARE_TOKEN, str(config))

    def test_provider_repr_does_not_leak_token(self) -> None:
        provider = AkshareEtfMarketDataProvider(
            token=_AKSHARE_TOKEN,
            base_url="https://example.invalid/akshare",
            timeout_seconds=10.0,
        )
        self.assertNotIn(_AKSHARE_TOKEN, repr(provider))


class CifangConfigRedactionTest(unittest.TestCase):
    def test_sanitized_dict_omits_token(self) -> None:
        config = CifangAdapterConfig(
            token=_CIFANG_TOKEN,
            base_url="https://www.cifangquant.com/api",
            adjustment="none",
            timeout_seconds=10.0,
        )
        sanitized = config.sanitized_dict()
        self.assertNotIn("token", sanitized)
        self.assertNotIn(_CIFANG_TOKEN, repr(sanitized))
        self.assertEqual(sanitized["adjustment"], "none")

    def test_repr_does_not_leak_token(self) -> None:
        config = CifangAdapterConfig(
            token=_CIFANG_TOKEN,
            base_url="https://www.cifangquant.com/api",
            adjustment="none",
            timeout_seconds=10.0,
        )
        self.assertNotIn(_CIFANG_TOKEN, repr(config))

    def test_str_does_not_leak_token(self) -> None:
        config = CifangAdapterConfig(
            token=_CIFANG_TOKEN,
            base_url="https://www.cifangquant.com/api",
            adjustment="none",
            timeout_seconds=10.0,
        )
        self.assertNotIn(_CIFANG_TOKEN, str(config))

    def test_provider_repr_does_not_leak_token(self) -> None:
        provider = CifangEtfMarketDataProvider(
            token=_CIFANG_TOKEN,
            base_url="https://www.cifangquant.com/api",
            adjustment="none",
            timeout_seconds=10.0,
        )
        self.assertNotIn(_CIFANG_TOKEN, repr(provider))


class EnvExampleRedactionTest(unittest.TestCase):
    """The committed .env.example must be free of real credentials."""

    def test_env_example_token_values_are_placeholders(self) -> None:
        from pathlib import Path

        env_path = Path(__file__).resolve().parents[4] / ".env.example"
        contents = env_path.read_text(encoding="utf-8")
        # Real-looking tokens would not be a string of underscores prefixed by
        # __SET_VIA_PLATFORM_SECRET__. Allow that pattern explicitly.
        for token_var in (
            "INVEST_PIPELINE_AKSHARE_TOKEN",
            "INVEST_PIPELINE_CIFANG_TOKEN",
            "INVEST_PIPELINE_RSSCAST_TOKEN",
            "INVEST_PIPELINE_QUICKTINY_MCP_TOKEN",
        ):
            self.assertIn(token_var, contents)
            self.assertNotIn(
                "AKSHARE_TOKEN=akshare", contents
            )  # no real-looking archive string
            self.assertIn("__SET_VIA_PLATFORM_SECRET__", contents)


if __name__ == "__main__":
    unittest.main()
