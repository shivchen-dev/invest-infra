from __future__ import annotations

import unittest

from invest_pipeline.providers import (
    PROVIDER_KEY_RSSCAST,
    ProviderAdapterNotImplementedError,
    ProviderSettings,
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.providers.capabilities import ProviderCapability, ProviderRole
from invest_pipeline.providers.rsscast.declaration import RSSCAST_DECLARATION


class RsscastCapabilityTest(unittest.TestCase):
    def test_provider_key(self) -> None:
        self.assertEqual(RSSCAST_DECLARATION.provider_key, PROVIDER_KEY_RSSCAST)

    def test_role_is_research_only(self) -> None:
        self.assertEqual(RSSCAST_DECLARATION.role, ProviderRole.RESEARCH_ONLY)

    def test_does_not_declare_etf_capabilities(self) -> None:
        capabilities = RSSCAST_DECLARATION.capabilities
        self.assertNotIn(ProviderCapability.ETF_DAILY_BARS, capabilities)
        self.assertNotIn(ProviderCapability.ETF_INSTRUMENTS, capabilities)
        self.assertNotIn(ProviderCapability.ETF_TRADING_CALENDAR, capabilities)

    def test_declares_stock_and_index_quotes(self) -> None:
        capabilities = RSSCAST_DECLARATION.capabilities
        self.assertIn(ProviderCapability.STOCK_QUOTES, capabilities)
        self.assertIn(ProviderCapability.INDEX_QUOTES, capabilities)


class RsscastFactoryTest(unittest.TestCase):
    def test_factory_blocked_even_when_enabled(self) -> None:
        from invest_pipeline.providers import build_provider_from_settings

        settings = ProviderSettings.from_mapping(
            {
                "provider_key": PROVIDER_KEY_RSSCAST,
                "rsscast": {"enabled": True, "token": "demo"},
            }
        )
        with self.assertRaises(ProviderAdapterNotImplementedError):
            build_provider_from_settings(settings)

    def test_real_settings_have_redacted_env_prefix(self) -> None:
        self.assertEqual(RSSCAST_DECLARATION.env_prefix, "INVEST_PIPELINE_RSSCAST_")
        self.assertIn("INVEST_PIPELINE_RSSCAST_TOKEN", RSSCAST_DECLARATION.credential_env_vars)


class RsscastRegistryTest(unittest.TestCase):
    def test_registered_in_default_registry(self) -> None:
        from invest_pipeline.providers import DEFAULT_PROVIDER_REGISTRY

        self.assertIn(PROVIDER_KEY_RSSCAST, DEFAULT_PROVIDER_REGISTRY.keys())
        declaration = DEFAULT_PROVIDER_REGISTRY.declaration(PROVIDER_KEY_RSSCAST)
        self.assertEqual(declaration.role, ProviderRole.RESEARCH_ONLY)

    def test_has_capability_etf_daily_bars_is_false(self) -> None:
        from invest_pipeline.providers import DEFAULT_PROVIDER_REGISTRY

        self.assertFalse(
            DEFAULT_PROVIDER_REGISTRY.has_capability(
                PROVIDER_KEY_RSSCAST, ProviderCapability.ETF_DAILY_BARS
            )
        )


if __name__ == "__main__":
    unittest.main()
