"""TDX .day offline reader spike.

Public surface:

* :data:`PROVIDER_KEY` and :data:`DATASET_KEY` constants for pipeline wiring.
* :func:`read_day_file` parses a single ``.day`` file.
* :func:`read_symbol` resolves and reads the canonical
  ``vipdoc/{market}/lday/{market}{symbol}.day`` file under a given directory.
* :class:`TdxDailyBar` is the normalized intermediate record.
* :class:`TdxOfflineSettings` is the operator-facing, disabled-by-default
  configuration object for the offline provider.
* :class:`TdxOfflineStockProvider` is the drop-in provider for the
  A-share stock daily-bars path; it implements the same structural
  port the Tushare ``StockTushareProvider`` exposes and is the
  Tushare → TDX offline fallback adapter for the daily-bars slice.
* All errors inherit from :class:`TdxOfflineError`.
"""

from .config import TdxOfflineSettings
from .errors import (
    TdxFileMissingError,
    TdxInvalidDateError,
    TdxInvalidMarketError,
    TdxInvalidPathError,
    TdxInvalidSizeError,
    TdxInvalidSymbolError,
    TdxInvalidValueError,
    TdxOfflineError,
)
from .reader import (
    DATASET_KEY,
    PROVIDER_KEY,
    RECORD_SIZE,
    read_day_file,
    read_symbol,
)
from .records import TdxDailyBar
from .stock_adapter import TdxOfflineStockProvider

__all__ = [
    "DATASET_KEY",
    "PROVIDER_KEY",
    "RECORD_SIZE",
    "TdxDailyBar",
    "TdxOfflineError",
    "TdxFileMissingError",
    "TdxInvalidDateError",
    "TdxInvalidMarketError",
    "TdxInvalidPathError",
    "TdxInvalidSizeError",
    "TdxInvalidSymbolError",
    "TdxInvalidValueError",
    "TdxOfflineSettings",
    "TdxOfflineStockProvider",
    "read_day_file",
    "read_symbol",
]
