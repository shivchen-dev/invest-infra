from __future__ import annotations

import unittest
from datetime import date

from invest_pipeline.providers import FixtureDevEtfMarketDataProvider


class FixtureDevContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = FixtureDevEtfMarketDataProvider()

    def test_provider_key_is_stable(self) -> None:
        self.assertEqual(self.provider.provider_key, "fixture_dev")

    def test_adjustment_is_none(self) -> None:
        self.assertEqual(self.provider.adjustment, "none")

    def test_fetch_instruments_returns_envelope(self) -> None:
        batch = self.provider.fetch_instruments(date(2026, 7, 30))
        self.assertEqual(batch.provider_key, "fixture_dev")
        records = list(batch.records())
        self.assertGreater(len(records), 0)
        for record in records:
            self.assertTrue(hasattr(record, "symbol"))
            self.assertTrue(hasattr(record, "exchange"))

    def test_fetch_instruments_carries_warning(self) -> None:
        batch = self.provider.fetch_instruments(date(2026, 7, 30))
        self.assertTrue(any("dev/test" in warning for warning in batch.warnings))

    def test_fetch_daily_bars_returns_empty_with_warning(self) -> None:
        batch = self.provider.fetch_daily_bars(
            symbols=("510300", "510500"),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 30),
        )
        self.assertEqual(list(batch.records()), [])
        self.assertEqual(batch.provider_key, "fixture_dev")
        self.assertTrue(batch.warnings)

    def test_fetch_daily_bars_rejects_inverted_range(self) -> None:
        with self.assertRaises(ValueError):
            self.provider.fetch_daily_bars(
                symbols=(),
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 1),
            )

    def test_fetch_trading_calendar_returns_empty_with_warning(self) -> None:
        batch = self.provider.fetch_trading_calendar(
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 30),
        )
        self.assertEqual(list(batch.records()), [])
        self.assertTrue(batch.warnings)


if __name__ == "__main__":
    unittest.main()
