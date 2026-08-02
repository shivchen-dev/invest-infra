"""Focused unit tests for the ``personal_etf_daily_job`` Dagster asset job.

PR-4 increment 1: the job is registered alongside the asset
collection in :mod:`invest_pipeline.definitions` and selects exactly
the six PR-2 / PR-3 ETF and candidate-pool assets that make up the
personal ETF daily pipeline (excluding the ``seed_instruments``
admin asset). These tests guard three contracts:

* the job is exposed as a module-level symbol on
  :mod:`invest_pipeline.definitions` with the right name;
* the resolved job is registered in :data:`invest_pipeline.definitions.defs`
  under that same name and is materially an asset job;
* the asset selection of the resolved job contains exactly the six
  expected asset keys — no more, no fewer, and no inadvertent
  inclusion of ``seed_instruments``.
"""

from __future__ import annotations

import unittest

import dagster as dg
from invest_pipeline.assets import (
    etf_daily_bars,
    etf_daily_bars_raw,
    etf_input_snapshot,
    etf_instruments,
    etf_instruments_raw,
    personal_candidate_pool,
    seed_instruments,
)
from invest_pipeline.definitions import defs, personal_etf_daily_job

_EXPECTED_SELECTION: tuple[dg.AssetsDefinition, ...] = (
    etf_instruments_raw,
    etf_instruments,
    etf_daily_bars_raw,
    etf_daily_bars,
    etf_input_snapshot,
    personal_candidate_pool,
)


class PersonalEtfDailyJobRegistrationTest(unittest.TestCase):
    """Module-level registration of ``personal_etf_daily_job``."""

    def test_module_exposes_job_with_expected_name(self) -> None:
        self.assertEqual(personal_etf_daily_job.name, "personal_etf_daily_job")

    def test_definitions_resolves_job_under_expected_name(self) -> None:
        job_def = defs.resolve_job_def("personal_etf_daily_job")
        self.assertIsInstance(job_def, dg.JobDefinition)
        self.assertEqual(job_def.name, "personal_etf_daily_job")
        self.assertTrue(
            job_def.is_asset_job,
            "personal_etf_daily_job must materialise assets, not ops",
        )


class PersonalEtfDailyJobSelectionTest(unittest.TestCase):
    """Asset selection of the resolved ``personal_etf_daily_job``."""

    def test_selection_is_exactly_the_six_etf_and_pool_assets(self) -> None:
        job_def = defs.resolve_job_def("personal_etf_daily_job")
        selected_keys = set(job_def.asset_layer.selected_asset_keys)
        expected_keys = {asset.key for asset in _EXPECTED_SELECTION}
        self.assertEqual(selected_keys, expected_keys)

    def test_selection_excludes_seed_instruments(self) -> None:
        job_def = defs.resolve_job_def("personal_etf_daily_job")
        self.assertNotIn(
            seed_instruments.key,
            job_def.asset_layer.selected_asset_keys,
        )

    def test_selection_has_no_extra_or_missing_assets(self) -> None:
        job_def = defs.resolve_job_def("personal_etf_daily_job")
        self.assertEqual(
            len(job_def.asset_layer.selected_asset_keys),
            len(_EXPECTED_SELECTION),
        )


if __name__ == "__main__":
    unittest.main()