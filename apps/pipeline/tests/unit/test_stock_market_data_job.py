"""Focused unit tests for the ``stock_market_data_job`` Dagster asset job.

Stage 4B increment: the job is registered alongside the asset
collection in :mod:`invest_pipeline.definitions` and selects the
stock market-data assets that make up the dedicated A-share chain —
``stock_instruments_raw`` → ``stock_instruments`` →
``stock_daily_bars_raw`` → ``stock_daily_bars`` →
``stock_input_snapshot`` → ``market_breadth_snapshot`` — and nothing
else. ``personal_etf_daily_job`` now also selects the
``etf_akshare_daily_bars`` enrichment asset on top of the original
ETF daily slice, and the new job must still not overlap with it.

The tests guard four contracts:

* the job is exposed as a module-level symbol on
  :mod:`invest_pipeline.definitions` with the right name;
* the resolved job is registered in :data:`invest_pipeline.definitions.defs`
  under that same name and is materially an asset job;
* the asset selection of the resolved job contains exactly the six
  expected asset keys — no more, no fewer, and no inadvertent
  inclusion of any ETF asset or ``seed_instruments``;
* the six stock assets share a single ``DailyPartitionsDefinition``
  instance distinct from the ETF daily partition so the stock chain
  runs on its own schedule.
"""

from __future__ import annotations

import unittest

import dagster as dg
from invest_pipeline.assets import (
    etf_akshare_daily_bars,
    etf_daily_bars,
    etf_daily_bars_raw,
    etf_input_snapshot,
    etf_instruments,
    etf_instruments_raw,
    market_breadth_snapshot,
    personal_candidate_pool,
    seed_instruments,
    stock_daily_bars,
    stock_daily_bars_raw,
    stock_input_snapshot,
    stock_instruments,
    stock_instruments_raw,
)
from invest_pipeline.definitions import defs, stock_market_data_job

_EXPECTED_STOCK_SELECTION: tuple[dg.AssetsDefinition, ...] = (
    stock_instruments_raw,
    stock_instruments,
    stock_daily_bars_raw,
    stock_daily_bars,
    stock_input_snapshot,
    market_breadth_snapshot,
)


class StockMarketDataJobRegistrationTest(unittest.TestCase):
    """Module-level registration of ``stock_market_data_job``."""

    def test_module_exposes_job_with_expected_name(self) -> None:
        self.assertEqual(stock_market_data_job.name, "stock_market_data_job")

    def test_definitions_resolves_job_under_expected_name(self) -> None:
        job_def = defs.resolve_job_def("stock_market_data_job")
        self.assertIsInstance(job_def, dg.JobDefinition)
        self.assertEqual(job_def.name, "stock_market_data_job")
        self.assertTrue(
            job_def.is_asset_job,
            "stock_market_data_job must materialise assets, not ops",
        )


class StockMarketDataJobSelectionTest(unittest.TestCase):
    """Asset selection of the resolved ``stock_market_data_job``."""

    def test_selection_is_exactly_the_six_stock_assets(self) -> None:
        job_def = defs.resolve_job_def("stock_market_data_job")
        selected_keys = set(job_def.asset_layer.selected_asset_keys)
        expected_keys = {asset.key for asset in _EXPECTED_STOCK_SELECTION}
        self.assertEqual(selected_keys, expected_keys)

    def test_selection_has_no_extra_or_missing_assets(self) -> None:
        job_def = defs.resolve_job_def("stock_market_data_job")
        self.assertEqual(
            len(job_def.asset_layer.selected_asset_keys),
            len(_EXPECTED_STOCK_SELECTION),
        )

    def test_selection_excludes_seed_instruments(self) -> None:
        job_def = defs.resolve_job_def("stock_market_data_job")
        self.assertNotIn(
            seed_instruments.key,
            job_def.asset_layer.selected_asset_keys,
        )

    def test_selection_excludes_etf_pipeline_assets(self) -> None:
        job_def = defs.resolve_job_def("stock_market_data_job")
        etf_keys = {
            etf_instruments_raw.key,
            etf_instruments.key,
            etf_daily_bars_raw.key,
            etf_daily_bars.key,
            etf_input_snapshot.key,
            personal_candidate_pool.key,
        }
        selected = set(job_def.asset_layer.selected_asset_keys)
        self.assertTrue(
            etf_keys.isdisjoint(selected),
            "stock_market_data_job must not select any ETF pipeline asset",
        )

    def test_selection_includes_stock_input_snapshot_and_market_breadth(self) -> None:
        job_def = defs.resolve_job_def("stock_market_data_job")
        selected = set(job_def.asset_layer.selected_asset_keys)
        self.assertIn(stock_input_snapshot.key, selected)
        self.assertIn(market_breadth_snapshot.key, selected)


class StockMarketDataJobPartitionTest(unittest.TestCase):
    """The six stock assets share an independent daily partition definition."""

    def test_each_stock_asset_is_partitioned_with_daily_definition(self) -> None:
        for asset in _EXPECTED_STOCK_SELECTION:
            with self.subTest(asset=asset.key.to_user_string()):
                self.assertIsInstance(asset.partitions_def, dg.DailyPartitionsDefinition)

    def test_all_stock_assets_share_same_partitions_def_instance(self) -> None:
        first = stock_instruments_raw.partitions_def
        for asset in _EXPECTED_STOCK_SELECTION:
            with self.subTest(asset=asset.key.to_user_string()):
                self.assertIs(asset.partitions_def, first)

    def test_stock_partitions_def_is_distinct_from_etf_partitions_def(self) -> None:
        from invest_pipeline.assets import (
            _ETF_INPUT_SNAPSHOT_PARTITIONS,
            _STOCK_MARKET_DATA_PARTITIONS,
        )

        self.assertIsNot(
            _STOCK_MARKET_DATA_PARTITIONS,
            _ETF_INPUT_SNAPSHOT_PARTITIONS,
            "stock chain must use an independent daily partition definition",
        )


class StockMarketDataJobIsolationTest(unittest.TestCase):
    """The new job does not disturb the existing ETF job's selection.

    ``personal_etf_daily_job`` now also selects the
    ``etf_akshare_daily_bars`` enrichment asset, but ``real_exposure``
    and every stock-pipeline asset must still be absent so the
    dedicated chain stays isolated from the ETF daily slice.
    """

    def test_personal_etf_daily_job_selection_matches_registered_set(self) -> None:
        job_def = defs.resolve_job_def("personal_etf_daily_job")
        selected_keys = set(job_def.asset_layer.selected_asset_keys)
        etf_keys = {
            etf_instruments_raw.key,
            etf_instruments.key,
            etf_daily_bars_raw.key,
            etf_daily_bars.key,
            etf_akshare_daily_bars.key,
            etf_input_snapshot.key,
            personal_candidate_pool.key,
        }
        self.assertEqual(selected_keys, etf_keys)


if __name__ == "__main__":
    unittest.main()