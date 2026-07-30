from __future__ import annotations

import os
import unittest

from invest_pipeline.providers.capabilities import (
    ADJUSTMENT_NONE,
    ALLOWED_ADJUSTMENTS,
    PROVIDER_KEY_AKSHARE,
    PROVIDER_KEY_CIFANG,
    PROVIDER_KEY_FIXTURE_DEV,
    PROVIDER_KEY_QUICKTINY_MCP,
    PROVIDER_KEY_RSSCAST,
    ProviderCapability,
    ProviderDeclaration,
    ProviderRole,
    is_adjustment_allowed,
)


class ProviderCapabilityTest(unittest.TestCase):
    def test_expected_capability_keys_exist(self) -> None:
        keys = {cap.value for cap in ProviderCapability}
        self.assertIn("etf_instruments", keys)
        self.assertIn("etf_daily_bars", keys)
        self.assertIn("etf_trading_calendar", keys)
        self.assertIn("index_quotes", keys)
        self.assertIn("stock_quotes", keys)
        self.assertIn("research_reports", keys)
        self.assertIn("market_snapshot", keys)

    def test_provider_keys_are_stable(self) -> None:
        self.assertEqual(PROVIDER_KEY_AKSHARE, "akshare")
        self.assertEqual(PROVIDER_KEY_CIFANG, "cifang")
        self.assertEqual(PROVIDER_KEY_RSSCAST, "rsscast")
        self.assertEqual(PROVIDER_KEY_QUICKTINY_MCP, "quicktiny_mcp")
        self.assertEqual(PROVIDER_KEY_FIXTURE_DEV, "fixture_dev")

    def test_adjustment_only_allows_none(self) -> None:
        self.assertEqual(ADJUSTMENT_NONE, "none")
        self.assertEqual(ALLOWED_ADJUSTMENTS, frozenset({"none"}))
        self.assertTrue(is_adjustment_allowed("none"))
        self.assertFalse(is_adjustment_allowed("qfq"))
        self.assertFalse(is_adjustment_allowed("hfq"))
        self.assertFalse(is_adjustment_allowed(""))


class ProviderDeclarationTest(unittest.TestCase):
    def test_requires_at_least_one_capability(self) -> None:
        declaration = ProviderDeclaration(
            provider_key="placeholder",
            capabilities=frozenset({ProviderCapability.ETF_INSTRUMENTS}),
            role=ProviderRole.SECONDARY,
            requires_credentials=False,
            notes="placeholder",
        )
        self.assertEqual(declaration.provider_key, "placeholder")
        self.assertEqual(declaration.role, ProviderRole.SECONDARY)
        self.assertFalse(declaration.requires_credentials)

    def test_declaration_is_frozen(self) -> None:
        declaration = ProviderDeclaration(
            provider_key="placeholder",
            capabilities=frozenset({ProviderCapability.ETF_INSTRUMENTS}),
            role=ProviderRole.SECONDARY,
            requires_credentials=False,
            notes="placeholder",
        )
        with self.assertRaises(Exception):
            declaration.provider_key = "mutated"  # type: ignore[misc]


class EnvironmentConfigVariablesTest(unittest.TestCase):
    """Guard rail so default values stay redacted.

    These env var names are intentionally isolated here so we can add new
    ones in ``settings.py`` without accidentally leaking a real value into
    the test environment.
    """

    def test_no_real_token_in_environment(self) -> None:
        for name in (
            "INVEST_PIPELINE_AKSHARE_TOKEN",
            "INVEST_PIPELINE_CIFANG_TOKEN",
            "INVEST_PIPELINE_RSSCAST_TOKEN",
            "INVEST_PIPELINE_QUICKTINY_MCP_TOKEN",
        ):
            value = os.environ.get(name)
            self.assertIsNone(value, f"Unexpected env var {name!r} present")


if __name__ == "__main__":
    unittest.main()
