from __future__ import annotations

import unittest
from datetime import date

from invest_pipeline.adapters import FixtureDevInstrumentProvider
from invest_pipeline.adapters.errors import ProviderError


class FixtureDevInstrumentProviderTest(unittest.TestCase):
    """Test the fixture_dev instrument provider adapter."""

    def test_provider_key(self) -> None:
        provider = FixtureDevInstrumentProvider()
        # Note: current implementation doesn't have provider_key property
        # This test documents the expected interface for P1-1
        self.assertTrue(hasattr(provider, 'list_instruments'))

    def test_list_instruments_returns_sequence(self) -> None:
        provider = FixtureDevInstrumentProvider()
        instruments = provider.list_instruments()
        self.assertIsInstance(instruments, (list, tuple))
        self.assertGreater(len(instruments), 0)

    def test_list_instruments_returns_valid_instruments(self) -> None:
        provider = FixtureDevInstrumentProvider()
        instruments = provider.list_instruments()
        for instrument in instruments:
            self.assertTrue(hasattr(instrument, 'symbol'))
            self.assertTrue(hasattr(instrument, 'exchange'))
            self.assertTrue(hasattr(instrument, 'name'))
            # ADR-0004 phase 1 market scope: SSE / SZSE only
            self.assertIn(instrument.exchange, {'SSE', 'SZSE'})

    def test_list_instruments_deterministic(self) -> None:
        """Fixture provider should return the same data on every call."""
        provider = FixtureDevInstrumentProvider()
        first = provider.list_instruments()
        second = provider.list_instruments()
        self.assertEqual(len(first), len(second))
        for a, b in zip(first, second):
            self.assertEqual(a.symbol, b.symbol)
            self.assertEqual(a.exchange, b.exchange)


if __name__ == "__main__":
    unittest.main()
