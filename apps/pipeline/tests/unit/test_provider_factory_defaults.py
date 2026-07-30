from __future__ import annotations

import unittest

from invest_pipeline.providers import (
    FIXTURE_DEV_PROVIDER_KEY,
    FixtureDevEtfMarketDataProvider,
    FixtureDevInstrumentProvider,
    ProviderAdapterNotImplementedError,
    ProviderAuthenticationError,
    ProviderSettings,
    RealProviderRequiresExplicitEnablementError,
    UnknownProviderError,
    build_provider_from_settings,
    default_provider_settings,
)


class DefaultSettingsTest(unittest.TestCase):
    def test_default_provider_key_is_fixture_dev(self) -> None:
        settings = default_provider_settings()
        self.assertEqual(settings.provider_key, FIXTURE_DEV_PROVIDER_KEY)

    def test_default_real_sources_disabled(self) -> None:
        settings = default_provider_settings()
        self.assertFalse(settings.akshare.enabled)
        self.assertFalse(settings.cifang.enabled)
        self.assertFalse(settings.rsscast.enabled)
        self.assertFalse(settings.quicktiny_mcp.enabled)

    def test_is_enabled_fixture_dev_is_true_even_when_disabled(self) -> None:
        settings = ProviderSettings(provider_key=FIXTURE_DEV_PROVIDER_KEY)
        self.assertTrue(settings.is_enabled(FIXTURE_DEV_PROVIDER_KEY))

    def test_is_enabled_unknown_key_raises(self) -> None:
        settings = default_provider_settings()
        with self.assertRaises(RealProviderRequiresExplicitEnablementError):
            settings.is_enabled("ghost-provider")


class FactoryDefaultsTest(unittest.TestCase):
    def test_default_build_yields_fixture_dev(self) -> None:
        settings = default_provider_settings()
        provider = build_provider_from_settings(settings)
        self.assertIsInstance(provider, FixtureDevEtfMarketDataProvider)
        self.assertEqual(provider.provider_key, FIXTURE_DEV_PROVIDER_KEY)

    def test_explicit_fixture_dev_key_builds_fixture(self) -> None:
        settings = ProviderSettings(provider_key=FIXTURE_DEV_PROVIDER_KEY)
        provider = build_provider_from_settings(settings)
        self.assertIsInstance(provider, FixtureDevEtfMarketDataProvider)

    def test_unknown_provider_raises(self) -> None:
        settings = ProviderSettings(provider_key="ghost-provider")
        with self.assertRaises(UnknownProviderError):
            build_provider_from_settings(settings)

    def test_akshare_blocked_by_default(self) -> None:
        settings = ProviderSettings(provider_key="akshare")
        with self.assertRaises(RealProviderRequiresExplicitEnablementError):
            build_provider_from_settings(settings)

    def test_cifang_blocked_by_default(self) -> None:
        settings = ProviderSettings(provider_key="cifang")
        with self.assertRaises(RealProviderRequiresExplicitEnablementError):
            build_provider_from_settings(settings)

    def test_akshare_with_explicit_enable_and_token_builds_adapter(self) -> None:
        settings = ProviderSettings.from_mapping(
            {
                "provider_key": "akshare",
                "akshare": {
                    "enabled": True,
                    "token": "demo-token",
                    "base_url": "https://example.invalid/akshare",
                },
            }
        )
        provider = build_provider_from_settings(settings)
        # The adapter class is a placeholder that has the correct provider_key
        self.assertEqual(provider.provider_key, "akshare")

    def test_cifang_with_qfq_adjustment_rejected_by_settings_layer(self) -> None:
        with self.assertRaises(ValueError):
            ProviderSettings.from_mapping(
                {
                    "provider_key": "cifang",
                    "cifang": {
                        "enabled": True,
                        "token": "demo-token",
                        "base_url": "https://www.cifangquant.com/api",
                        "adjustment": "qfq",
                    },
                }
            )

    def test_cifang_with_none_adjustment_builds_adapter(self) -> None:
        settings = ProviderSettings.from_mapping(
            {
                "provider_key": "cifang",
                "cifang": {
                    "enabled": True,
                    "token": "demo-token",
                    "base_url": "https://www.cifangquant.com/api",
                    "adjustment": "none",
                },
            }
        )
        provider = build_provider_from_settings(settings)
        self.assertEqual(provider.provider_key, "cifang")
        self.assertEqual(getattr(provider, "adjustment"), "none")


class ResearchOnlyProvidersTest(unittest.TestCase):
    def test_rsscast_blocked_at_factory(self) -> None:
        settings = ProviderSettings.from_mapping(
            {
                "provider_key": "rsscast",
                "rsscast": {"enabled": True, "token": "demo"},
            }
        )
        with self.assertRaises(ProviderAdapterNotImplementedError):
            build_provider_from_settings(settings)

    def test_quicktiny_mcp_blocked_at_factory(self) -> None:
        settings = ProviderSettings.from_mapping(
            {
                "provider_key": "quicktiny_mcp",
                "quicktiny_mcp": {"enabled": True, "token": "demo"},
            }
        )
        with self.assertRaises(ProviderAdapterNotImplementedError):
            build_provider_from_settings(settings)


class AuthenticationRequiredTest(unittest.TestCase):
    def test_akshare_without_token_raises_at_construction(self) -> None:
        settings = ProviderSettings.from_mapping(
            {
                "provider_key": "akshare",
                "akshare": {"enabled": True, "token": "", "base_url": "https://example.invalid"},
            }
        )
        with self.assertRaises(ProviderAuthenticationError):
            build_provider_from_settings(settings)

    def test_cifang_without_token_raises_at_construction(self) -> None:
        settings = ProviderSettings.from_mapping(
            {
                "provider_key": "cifang",
                "cifang": {
                    "enabled": True,
                    "token": "",
                    "base_url": "https://www.cifangquant.com/api",
                    "adjustment": "none",
                },
            }
        )
        with self.assertRaises(ProviderAuthenticationError):
            build_provider_from_settings(settings)


class InstrumentProviderShapeTest(unittest.TestCase):
    """Matches the Protocol in packages/domain/ports.py.InstrumentProvider."""

    def test_fixture_dev_instrument_provider_returns_records(self) -> None:
        provider = FixtureDevInstrumentProvider()
        instruments = list(provider.list_instruments())
        self.assertGreater(len(instruments), 0)
        exchanges = {item.exchange for item in instruments}
        # ADR-0004 phase 1 market scope: SSE / SZSE only.
        self.assertTrue(exchanges <= {"SSE", "SZSE"})


if __name__ == "__main__":
    unittest.main()
