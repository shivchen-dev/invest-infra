"""Focused unit tests for the ``real_exposure_job`` Dagster registration.

The DC-3 slice ships exactly one dedicated manual job:

* it is registered as a module-level symbol on
  :mod:`invest_pipeline.definitions` with the name
  ``real_exposure_job``;
* the resolved job is materialised through :data:`invest_pipeline.definitions.defs`
  and is an asset job selecting **only** the new
  :func:`invest_pipeline.real_exposure_asset.real_exposure` asset;
* the ``personal_etf_daily_job`` selection remains scoped to the ETF
  daily slice — its asset set now includes the registered
  ``etf_akshare_daily_bars`` enrichment asset, but no
  ``real_exposure`` or stock-pipeline asset is added;
* no schedule and no sensor is wired up to ``real_exposure_job``; the
  job is manual-only so the opt-in flag is the single source of truth
  for real-network runs.
"""

from __future__ import annotations

import unittest

import dagster as dg
from invest_pipeline.definitions import defs, real_exposure_job
from invest_pipeline.real_exposure_asset import real_exposure


class RealExposureJobRegistrationTest(unittest.TestCase):
    """Module-level registration of ``real_exposure_job``."""

    def test_module_exposes_job_with_expected_name(self) -> None:
        self.assertEqual(real_exposure_job.name, "real_exposure_job")

    def test_definitions_resolves_job_under_expected_name(self) -> None:
        job_def = defs.resolve_job_def("real_exposure_job")
        self.assertIsInstance(job_def, dg.JobDefinition)
        self.assertEqual(job_def.name, "real_exposure_job")
        self.assertTrue(
            job_def.is_asset_job,
            "real_exposure_job must materialise assets, not ops",
        )

    def test_job_asset_module_exposes_real_exposure_asset(self) -> None:
        from invest_pipeline.real_exposure_asset import real_exposure as module_asset

        self.assertIs(module_asset, real_exposure)


class RealExposureJobSelectionTest(unittest.TestCase):
    """The job selects exactly the real-exposure asset and nothing else."""

    def test_selection_is_exactly_the_real_exposure_asset(self) -> None:
        job_def = defs.resolve_job_def("real_exposure_job")
        selected_keys = set(job_def.asset_layer.selected_asset_keys)
        self.assertEqual(selected_keys, {real_exposure.key})

    def test_selection_has_no_extra_assets(self) -> None:
        job_def = defs.resolve_job_def("real_exposure_job")
        self.assertEqual(
            len(job_def.asset_layer.selected_asset_keys),
            1,
            "real_exposure_job must select exactly one asset",
        )


class RealExposureJobNoScheduleTest(unittest.TestCase):
    """No schedule / sensor is wired up to the real-exposure job.

    The DC-3 contract is manual-only; an accidental schedule would let
    the opt-in asset materialise without an explicit operator launch.
    """

    def test_no_schedule_targets_real_exposure_job(self) -> None:
        schedule_job_names = [
            schedule.job_name
            for schedule in defs.schedules
        ]
        self.assertNotIn(
            "real_exposure_job",
            schedule_job_names,
            "real_exposure_job must never be triggered by a schedule; "
            f"found schedules targeting it: {schedule_job_names}",
        )

    def test_no_sensor_targets_real_exposure_job(self) -> None:
        sensors = defs.sensors or []
        sensor_job_names = [
            sensor.job_name
            for sensor in sensors
        ]
        self.assertNotIn(
            "real_exposure_job",
            sensor_job_names,
            "real_exposure_job must never be triggered by a sensor; "
            f"found sensors targeting it: {sensor_job_names}",
        )

    def test_definitions_exposes_no_sensor(self) -> None:
        sensors = defs.sensors or []
        self.assertEqual(
            list(sensors),
            [],
            "DC-3 slice must not add any sensor; the job is manual-only",
        )


class PersonalEtfDailyJobSelectionTest(unittest.TestCase):
    """The ``personal_etf_daily_job`` selection matches the registered ETF daily slice.

    The asset set mirrors what :mod:`invest_pipeline.definitions`
    registers (now including the ``etf_akshare_daily_bars`` enrichment
    asset); ``real_exposure`` and any stock-pipeline asset must still
    be absent so the manual job stays isolated from the daily ETF
    slice.
    """

    def test_personal_etf_daily_job_selection_matches_registered_set(self) -> None:
        from invest_pipeline.assets import (
            etf_akshare_daily_bars,
            etf_daily_bars,
            etf_daily_bars_raw,
            etf_input_snapshot,
            etf_instruments,
            etf_instruments_raw,
            personal_candidate_pool,
        )
        from invest_pipeline.definitions import personal_etf_daily_job

        job_def = defs.resolve_job_def("personal_etf_daily_job")
        expected_keys = {
            etf_instruments_raw.key,
            etf_instruments.key,
            etf_daily_bars_raw.key,
            etf_daily_bars.key,
            etf_akshare_daily_bars.key,
            etf_input_snapshot.key,
            personal_candidate_pool.key,
        }
        self.assertEqual(
            set(job_def.asset_layer.selected_asset_keys),
            expected_keys,
        )
        self.assertNotIn(
            real_exposure.key,
            job_def.asset_layer.selected_asset_keys,
            "real_exposure must not be added to personal_etf_daily_job",
        )
        self.assertEqual(personal_etf_daily_job.name, "personal_etf_daily_job")


if __name__ == "__main__":
    unittest.main()
