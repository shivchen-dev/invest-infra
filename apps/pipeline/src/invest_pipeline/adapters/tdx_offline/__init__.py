"""TDX .day offline reader spike.

Public surface:

* :data:`PROVIDER_KEY` and :data:`DATASET_KEY` constants for pipeline wiring.
* :func:`read_day_file` parses a single ``.day`` file.
* :func:`read_symbol` resolves and reads the canonical
  ``vipdoc/{market}/lday/{market}{symbol}.day`` file under a given directory.
* :class:`TdxDailyBar` is the normalized intermediate record.
* All errors inherit from :class:`TdxOfflineError`.
"""

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

__all__ = [
    "PROVIDER_KEY",
    "DATASET_KEY",
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
    "read_day_file",
    "read_symbol",
]