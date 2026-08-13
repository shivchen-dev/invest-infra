"""Characterization tests for the Provider–Engine–Event Phase 1 seam.

These tests intentionally describe the current public runtime/catalog
contracts.  They do not add a registry, make network calls, or open a
database connection.
"""

from __future__ import annotations

import unittest

from invest_pipeline.adapters.errors import (
    RealProviderRequiresExplicitEnablementError,
    UnknownProviderError,
)
from invest_pipeline.adapters.tushare import StockTushareProvider, TushareSettings
from invest_pipeline.config import Settings
from invest_pipeline.provider_catalog import (
    TDX_OFFLINE,
    TUSHARE,
    ProviderCapability,
    iter_provider_declarations,
    runtime_supported_provider_keys,
)
from invest_pipeline.provider_factory import KNOWN_PROVIDER_KEYS, build_stock_provider
from invest_pipeline.provider_routing.datasets import Dataset
from invest_pipeline.provider_routing.selection import (
    NoEligibleProviderError,
    select_providers,
)


class ProviderRuntimeRegistryCharacterizationTest(unittest.TestCase):
    """Freeze the currently observable catalog/factory/routing behavior."""

    def test_characterization_catalog_is_runtime_key_authority(self) -> None:
        self.assertEqual(KNOWN_PROVIDER_KEYS, runtime_supported_provider_keys())
        self.assertEqual(
            set(KNOWN_PROVIDER_KEYS),
            {
                declaration.provider_key
                for declaration in iter_provider_declarations()
                if declaration.has_runtime_factory_adapter
            },
        )
        self.assertNotIn(TDX_OFFLINE.provider_key, runtime_supported_provider_keys())

    def test_characterization_stock_daily_capability_is_declared_but_dataset_is_not_registered(
        self,
    ) -> None:
        stock_daily_declarations = tuple(
            declaration.provider_key
            for declaration in iter_provider_declarations()
            if ProviderCapability.STOCK_DAILY_BARS in declaration.capabilities
        )

        self.assertEqual(stock_daily_declarations, ("hithink", "tdx_offline", "tushare"))
        with self.assertRaises(AttributeError):
            _ = Dataset.STOCK_DAILY_BARS  # type: ignore[attr-defined]

    def test_characterization_selection_is_sorted_and_stable_for_enabled_only_false(
        self,
    ) -> None:
        declarations = tuple(iter_provider_declarations())

        first = select_providers(declarations, Dataset.ETF_DAILY_BARS, enabled_only=False)
        second = select_providers(declarations, Dataset.ETF_DAILY_BARS, enabled_only=False)

        self.assertEqual(
            tuple(declaration.provider_key for declaration in first),
            ("cifangquant", "fixture_dev", "tushare"),
        )
        self.assertEqual(first, second)

    def test_characterization_selection_honors_default_enablement(self) -> None:
        selected = select_providers(
            tuple(iter_provider_declarations()),
            Dataset.ETF_DAILY_BARS,
        )

        self.assertEqual(
            tuple(declaration.provider_key for declaration in selected),
            ("fixture_dev",),
        )

    def test_characterization_selection_reports_no_stock_candidate(self) -> None:
        with self.assertRaises(NoEligibleProviderError) as context:
            select_providers(
                tuple(iter_provider_declarations()),
                Dataset.STOCK_PRICE_LIMITS,
                enabled_only=False,
            )

        self.assertEqual(context.exception.args[0], Dataset.STOCK_PRICE_LIMITS.value)

    def test_characterization_stock_factory_returns_explicit_tushare_provider(self) -> None:
        provider = build_stock_provider(
            Settings(provider_key=TUSHARE.provider_key),
            tushare_settings=TushareSettings(enabled=True, token="unit-test-token"),
        )

        self.assertIsInstance(provider, StockTushareProvider)
        self.assertEqual(provider.provider_key, TUSHARE.provider_key)

    def test_characterization_stock_factory_requires_explicit_enablement(self) -> None:
        with self.assertRaises(RealProviderRequiresExplicitEnablementError):
            build_stock_provider(
                Settings(provider_key=TUSHARE.provider_key),
                tushare_settings=TushareSettings(token="unit-test-token"),
            )

    def test_characterization_stock_factory_rejects_unknown_provider(self) -> None:
        with self.assertRaises(UnknownProviderError) as context:
            build_stock_provider(Settings(provider_key="unknown-characterization-key"))

        self.assertEqual(context.exception.args[0], "unknown-characterization-key")


if __name__ == "__main__":
    unittest.main()
