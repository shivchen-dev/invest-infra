"""Normalized intermediate record for the TDX .day offline reader spike.

The dataclass is intentionally minimal: it carries the values produced by a
strict parse of a single 32-byte record and does not depend on any
``InstrumentId`` or UUID-bearing type. Decimal is used for prices and amount
so the spike does not propagate binary-float artifacts into the broader
pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class TdxDailyBar:
    """A single parsed TDX daily bar.

    ``date`` is the integer ``YYYYMMDD`` as stored in the file. Prices and
    amount are :class:`decimal.Decimal` instances reconstructed from the
    on-disk integer or float32 representation. Volume is preserved as the
    unsigned 32-bit integer read from the file.
    """

    date: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    amount: Decimal
    volume: int


__all__ = ["TdxDailyBar"]