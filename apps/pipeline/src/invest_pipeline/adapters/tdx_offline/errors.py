"""Exception hierarchy for the TDX .day offline reader spike.

All exceptions inherit from :class:`TdxOfflineError` so callers can catch the
spike as a unit. The subclasses keep error attribution precise so that future
mapping into the broader pipeline error model can stay explicit.
"""

from __future__ import annotations


class TdxOfflineError(Exception):
    """Base class for all TDX offline reader failures."""


class TdxFileMissingError(TdxOfflineError):
    """Raised when the expected .day file does not exist on disk."""


class TdxInvalidPathError(TdxOfflineError):
    """Raised when a path exists but is not a regular file."""


class TdxInvalidSizeError(TdxOfflineError):
    """Raised when the file size is not a multiple of the 32-byte record size."""


class TdxInvalidDateError(TdxOfflineError):
    """Raised when a date field cannot be parsed as a valid YYYYMMDD date."""


class TdxInvalidValueError(TdxOfflineError):
    """Raised when OHLC, amount or volume is non-finite, negative or otherwise
    outside the acceptable domain for a daily bar."""


class TdxInvalidMarketError(TdxOfflineError):
    """Raised when the requested market code is not ``sh`` or ``sz``."""


class TdxInvalidSymbolError(TdxOfflineError):
    """Raised when the requested symbol is not a six-digit code."""


__all__ = [
    "TdxOfflineError",
    "TdxFileMissingError",
    "TdxInvalidPathError",
    "TdxInvalidSizeError",
    "TdxInvalidDateError",
    "TdxInvalidValueError",
    "TdxInvalidMarketError",
    "TdxInvalidSymbolError",
]