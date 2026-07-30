from __future__ import annotations

import unittest

from invest_pipeline.providers import (
    PROVIDER_KEY_QUICKTINY_MCP,
    ProviderAdapterNotImplementedError,
    ProviderSettings,
)
from invest_pipeline.providers.capabilities import (
    ProviderCapability,
    ProviderRole,
)
from invest_pipeline.providers.quicktiny_mcp.declaration import QUICKTINY_MCP_DECLARATION


class QuicktinyMcpCapabilityTest(unittest.TestCase):
    def test_provider_key(self) -> None:
        self.assertEqual(QUICKTINY_MCP_DECLARATION.provider_key, PROVIDER_KEY_QUICKTINY_MCP)

    def test_role_is_research_only(self) -> None:
        self.assertEqual(QUICKTINY_MCP_DECLARATION.role, ProviderRole.RESEARCH_ONLY)

    def test_does_not_declare_any_etf_or_market_data_capability(self) -> None:
        capabilities = QUICKTINY_MCP_DECLARATION.capabilities
        self.assertNotIn(ProviderCapability.ETF_DAILY_BARS, capabilities)
        self.assertNotIn(ProviderCapability.ETF_INSTRUMENTS, capabilities)
        self.assertNotIn(ProviderCapability.ETF_TRADING_CALENDAR, capabilities)
        self.assertNotIn(ProviderCapability.STOCK_QUOTES, capabilities)
        self.assertNotIn(ProviderCapability.INDEX_QUOTES, capabilities)

    def test_declares_research_reports_and_market_snapshot_only(self) -> None:
        capabilities = QUICKTINY_MCP_DECLARATION.capabilities
        self.assertIn(ProviderCapability.RESEARCH_REPORTS, capabilities)
        self.assertIn(ProviderCapability.MARKET_SNAPSHOT, capabilities)
        # Capability set must contain exactly the two declared capabilities.
        self.assertEqual(
            capabilities,
            frozenset(
                {ProviderCapability.RESEARCH_REPORTS, ProviderCapability.MARKET_SNAPSHOT}
            ),
        )


class QuicktinyMcpFactoryTest(unittest.TestCase):
    def test_factory_blocked_even_when_enabled(self) -> None:
        from invest_pipeline.providers import build_provider_from_settings

        settings = ProviderSettings.from_mapping(
            {
                "provider_key": PROVIDER_KEY_QUICKTINY_MCP,
                "quicktiny_mcp": {"enabled": True, "token": "demo"},
            }
        )
        with self.assertRaises(ProviderAdapterNotImplementedError):
            build_provider_from_settings(settings)

    def test_real_settings_have_redacted_env_prefix(self) -> None:
        self.assertEqual(
            QUICKTINY_MCP_DECLARATION.env_prefix, "INVEST_PIPELINE_QUICKTINY_MCP_"
        )
        self.assertIn(
            "INVEST_PIPELINE_QUICKTINY_MCP_TOKEN",
            QUICKTINY_MCP_DECLARATION.credential_env_vars,
        )


class QuicktinyMcpRegistryTest(unittest.TestCase):
    def test_registered_in_default_registry(self) -> None:
        from invest_pipeline.providers import DEFAULT_PROVIDER_REGISTRY

        self.assertIn(PROVIDER_KEY_QUICKTINY_MCP, DEFAULT_PROVIDER_REGISTRY.keys())
        declaration = DEFAULT_PROVIDER_REGISTRY.declaration(PROVIDER_KEY_QUICKTINY_MCP)
        self.assertEqual(declaration.role, ProviderRole.RESEARCH_ONLY)

    def test_has_capability_etf_daily_bars_is_false(self) -> None:
        from invest_pipeline.providers import DEFAULT_PROVIDER_REGISTRY

        self.assertFalse(
            DEFAULT_PROVIDER_REGISTRY.has_capability(
                PROVIDER_KEY_QUICKTINY_MCP, ProviderCapability.ETF_DAILY_BARS
            )
        )


if __name__ == "__main__":
    unittest.main()
