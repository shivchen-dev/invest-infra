"""Unit tests for the minimal provider runtime registry."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from invest_pipeline.adapters import (
    FixtureDevInstrumentProvider,
    ProviderAuthenticationError,
    RealProviderRequiresExplicitEnablementError,
    UnknownProviderError,
)
from invest_pipeline.adapters.cifang import CifangSettings
from invest_pipeline.adapters.tushare import StockTushareProvider, TushareSettings
from invest_pipeline.config import Settings
from invest_pipeline.provider_catalog import FIXTURE_DEV, TDX_OFFLINE, TUSHARE
from invest_pipeline.provider_runtime_registry import (
    ProviderRuntimeRegistry,
)


class ProviderRuntimeRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ProviderRuntimeRegistry()

    def test_resolves_fixture_etf(self) -> None:
        resolved = self.registry.resolve_etf(Settings(provider_key="fixture_dev"))

        self.assertIsInstance(resolved.provider, FixtureDevInstrumentProvider)
        self.assertEqual(resolved.provider_key, FIXTURE_DEV.provider_key)
        self.assertIs(resolved.declaration, FIXTURE_DEV)

    def test_resolves_tushare_stock_with_fictional_token(self) -> None:
        resolved = self.registry.resolve_stock(
            Settings(provider_key="tushare"),
            tushare_settings=TushareSettings(
                enabled=True,
                token="fictional-unit-test-token",
            ),
        )

        self.assertIsInstance(resolved.provider, StockTushareProvider)
        self.assertIs(resolved.declaration, TUSHARE)

    def test_unknown_etf_key_fails_closed(self) -> None:
        with self.assertRaises(KeyError):
            self.registry.resolve_etf(Settings(provider_key="unknown"))

    def test_catalog_only_etf_key_fails_closed(self) -> None:
        with self.assertRaises(UnknownProviderError):
            self.registry.resolve_etf(Settings(provider_key="tdx_offline"))

    def test_disabled_provider_fails_closed(self) -> None:
        with self.assertRaises(RealProviderRequiresExplicitEnablementError):
            self.registry.resolve_etf(
                Settings(provider_key="cifangquant"),
                cifang_settings=CifangSettings(enabled=False, api_key="fictional"),
            )

    def test_missing_credential_fails_closed(self) -> None:
        with (
            patch.object(TushareSettings, "resolved_token", return_value=""),
            self.assertRaises(ProviderAuthenticationError),
        ):
            self.registry.resolve_stock(
                Settings(provider_key="tushare"),
                tushare_settings=TushareSettings(enabled=True, token=""),
            )

    def test_resolved_provider_is_immutable(self) -> None:
        resolved = self.registry.resolve_etf(Settings(provider_key="fixture_dev"))

        with self.assertRaises((AttributeError, TypeError)):
            resolved.provider_key = "tushare"  # type: ignore[misc]

    def test_describe_reuses_catalog_declaration(self) -> None:
        self.assertIs(self.registry.describe("tdx_offline"), TDX_OFFLINE)

    def test_tdx_is_not_a_stock_runtime_provider(self) -> None:
        with self.assertRaises(UnknownProviderError):
            self.registry.resolve_stock(Settings(provider_key="tdx_offline"))


if __name__ == "__main__":
    unittest.main()
