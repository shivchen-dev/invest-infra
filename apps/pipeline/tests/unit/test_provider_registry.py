from __future__ import annotations

import unittest

from invest_pipeline.providers import (
    DEFAULT_PROVIDER_REGISTRY,
    PROVIDER_KEY_AKSHARE,
    PROVIDER_KEY_CIFANG,
    PROVIDER_KEY_FIXTURE_DEV,
    PROVIDER_KEY_QUICKTINY_MCP,
    PROVIDER_KEY_RSSCAST,
    InvalidProviderCapabilityError,
    UnknownProviderError,
)
from invest_pipeline.providers.capabilities import (
    ProviderCapability,
    ProviderDeclaration,
    ProviderRole,
)


class DefaultRegistryCompositionTest(unittest.TestCase):
    def test_lists_all_archived_sources(self) -> None:
        keys = set(DEFAULT_PROVIDER_REGISTRY.keys())
        self.assertEqual(
            keys,
            {
                PROVIDER_KEY_AKSHARE,
                PROVIDER_KEY_CIFANG,
                PROVIDER_KEY_RSSCAST,
                PROVIDER_KEY_QUICKTINY_MCP,
                PROVIDER_KEY_FIXTURE_DEV,
            },
        )

    def test_each_declaration_carries_redacted_template(self) -> None:
        for key in (
            PROVIDER_KEY_AKSHARE,
            PROVIDER_KEY_CIFANG,
            PROVIDER_KEY_RSSCAST,
            PROVIDER_KEY_QUICKTINY_MCP,
            PROVIDER_KEY_FIXTURE_DEV,
        ):
            declaration = DEFAULT_PROVIDER_REGISTRY.declaration(key)
            self.assertIsInstance(declaration, ProviderDeclaration)
            self.assertEqual(declaration.provider_key, key)


class CapabilityMatrixTest(unittest.TestCase):
    def test_akshare_declares_etf_capabilities(self) -> None:
        caps = DEFAULT_PROVIDER_REGISTRY.capabilities_for(PROVIDER_KEY_AKSHARE)
        self.assertIn(ProviderCapability.ETF_INSTRUMENTS, caps)
        self.assertIn(ProviderCapability.ETF_DAILY_BARS, caps)
        self.assertIn(ProviderCapability.ETF_TRADING_CALENDAR, caps)

    def test_cifang_declares_etf_capabilities(self) -> None:
        caps = DEFAULT_PROVIDER_REGISTRY.capabilities_for(PROVIDER_KEY_CIFANG)
        self.assertIn(ProviderCapability.ETF_INSTRUMENTS, caps)
        self.assertIn(ProviderCapability.ETF_DAILY_BARS, caps)

    def test_cifang_adjustment_is_none(self) -> None:
        declaration = DEFAULT_PROVIDER_REGISTRY.declaration(PROVIDER_KEY_CIFANG)
        self.assertEqual(declaration.adjustment, "none")

    def test_rsscast_does_not_declare_etf_daily_bars(self) -> None:
        caps = DEFAULT_PROVIDER_REGISTRY.capabilities_for(PROVIDER_KEY_RSSCAST)
        self.assertNotIn(ProviderCapability.ETF_DAILY_BARS, caps)
        self.assertNotIn(ProviderCapability.ETF_INSTRUMENTS, caps)
        self.assertNotIn(ProviderCapability.ETF_TRADING_CALENDAR, caps)
        self.assertIn(ProviderCapability.STOCK_QUOTES, caps)
        self.assertIn(ProviderCapability.INDEX_QUOTES, caps)

    def test_quicktiny_mcp_does_not_declare_etf_daily_bars(self) -> None:
        caps = DEFAULT_PROVIDER_REGISTRY.capabilities_for(PROVIDER_KEY_QUICKTINY_MCP)
        self.assertNotIn(ProviderCapability.ETF_DAILY_BARS, caps)
        self.assertNotIn(ProviderCapability.ETF_INSTRUMENTS, caps)
        self.assertNotIn(ProviderCapability.STOCK_QUOTES, caps)
        self.assertIn(ProviderCapability.RESEARCH_REPORTS, caps)
        self.assertIn(ProviderCapability.MARKET_SNAPSHOT, caps)

    def test_fixture_dev_includes_core_capabilities(self) -> None:
        caps = DEFAULT_PROVIDER_REGISTRY.capabilities_for(PROVIDER_KEY_FIXTURE_DEV)
        self.assertIn(ProviderCapability.ETF_INSTRUMENTS, caps)
        self.assertIn(ProviderCapability.ETF_DAILY_BARS, caps)
        self.assertIn(ProviderCapability.ETF_TRADING_CALENDAR, caps)


class HasCapabilityTest(unittest.TestCase):
    def test_returns_true_for_declared(self) -> None:
        self.assertTrue(
            DEFAULT_PROVIDER_REGISTRY.has_capability(
                PROVIDER_KEY_AKSHARE, ProviderCapability.ETF_DAILY_BARS
            )
        )

    def test_returns_false_for_undeclared(self) -> None:
        self.assertFalse(
            DEFAULT_PROVIDER_REGISTRY.has_capability(
                PROVIDER_KEY_RSSCAST, ProviderCapability.ETF_DAILY_BARS
            )
        )

    def test_returns_false_for_unknown_provider(self) -> None:
        self.assertFalse(
            DEFAULT_PROVIDER_REGISTRY.has_capability(
                "ghost-provider", ProviderCapability.ETF_DAILY_BARS
            )
        )


class RequireCapabilityTest(unittest.TestCase):
    def test_returns_declaration_for_declared_capability(self) -> None:
        declaration = DEFAULT_PROVIDER_REGISTRY.require_capability(
            PROVIDER_KEY_AKSHARE, ProviderCapability.ETF_DAILY_BARS
        )
        self.assertEqual(declaration.provider_key, PROVIDER_KEY_AKSHARE)

    def test_raises_for_undeclared_capability(self) -> None:
        with self.assertRaises(InvalidProviderCapabilityError):
            DEFAULT_PROVIDER_REGISTRY.require_capability(
                PROVIDER_KEY_RSSCAST, ProviderCapability.ETF_DAILY_BARS
            )


class UnknownProviderTest(unittest.TestCase):
    def test_declaration_raises(self) -> None:
        with self.assertRaises(UnknownProviderError):
            DEFAULT_PROVIDER_REGISTRY.declaration("does_not_exist")

    def test_build_raises(self) -> None:
        with self.assertRaises(UnknownProviderError):
            DEFAULT_PROVIDER_REGISTRY.build("does_not_exist")


class RoleMatrixTest(unittest.TestCase):
    """Recorded recommendations are advisory only — see migration matrix §3."""

    def test_archived_roles_match_recommendation(self) -> None:
        cases = {
            PROVIDER_KEY_AKSHARE: ProviderRole.SECONDARY,
            PROVIDER_KEY_CIFANG: ProviderRole.SECONDARY,
            PROVIDER_KEY_RSSCAST: ProviderRole.RESEARCH_ONLY,
            PROVIDER_KEY_QUICKTINY_MCP: ProviderRole.RESEARCH_ONLY,
            PROVIDER_KEY_FIXTURE_DEV: ProviderRole.PRIMARY,
        }
        for key, role in cases.items():
            declaration = DEFAULT_PROVIDER_REGISTRY.declaration(key)
            self.assertEqual(
                declaration.role,
                role,
                f"{key!r} expected {role} got {declaration.role}",
            )


if __name__ == "__main__":
    unittest.main()
