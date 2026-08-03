"""Market clock for China-market business dates."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")


def market_today() -> date:
    """Return today's date in the market timezone."""

    return datetime.now(MARKET_TIMEZONE).date()


__all__ = ["MARKET_TIMEZONE", "market_today"]
