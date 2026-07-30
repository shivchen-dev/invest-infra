from __future__ import annotations

import unittest

from invest_domain.instruments import Instrument, InstrumentType


class InstrumentTest(unittest.TestCase):
    def test_valid_instrument(self) -> None:
        item = Instrument("510300", "沪深300ETF", "SSE", InstrumentType.ETF)
        self.assertEqual(item.symbol, "510300")

    def test_empty_symbol_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Instrument("", "沪深300ETF", "SSE", InstrumentType.ETF)


if __name__ == "__main__":
    unittest.main()
