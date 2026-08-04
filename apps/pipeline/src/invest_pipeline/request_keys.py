"""Deterministic bounded logical keys for persisted Provider requests."""

from collections.abc import Sequence
from datetime import date
from hashlib import sha256

_MAX_REQUEST_KEY_LENGTH = 128


def make_daily_bars_request_key(
    start_date: date,
    end_date: date,
    symbols: Sequence[str],
) -> str:
    """Return a deterministic daily-bars key that fits storage constraints.

    Short symbol lists retain the historical human-readable format. Longer
    lists keep the date range and use a digest of the ordered symbols; the
    complete symbol list remains in ``request_params``.
    """

    prefix = f"daily-bars-{start_date.isoformat()}-{end_date.isoformat()}-"
    readable = prefix + "-".join(symbols)
    if len(readable) <= _MAX_REQUEST_KEY_LENGTH:
        return readable
    digest = sha256(",".join(symbols).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}symbols-{digest}"


__all__ = ["make_daily_bars_request_key"]
