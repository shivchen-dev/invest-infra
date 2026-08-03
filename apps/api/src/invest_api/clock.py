"""Single source of truth for the API layer's "today".

All routers and services that need the current business date MUST go
through :func:`market_today` rather than calling :meth:`date.today` or
:meth:`datetime.now` directly. The market's local calendar is
``Asia/Shanghai`` (China A-share trading hours), so a server running in
UTC can otherwise miss the roll-over by up to eight hours and report
Sunday's data on a Monday morning.

Centralising the clock in one helper:

- keeps the timezone choice auditable (``MARKET_TIMEZONE`` is the only
  place the IANA name appears);
- lets tests pin "today" via :func:`monkeypatch.setattr` instead of
  monkey-patching the built-in :class:`date` class (which would leak
  into other modules);
- matches the domain rule that the trading day is the local
  ``Asia/Shanghai`` calendar (see ``packages/domain`` models).
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

MARKET_TIMEZONE: ZoneInfo = ZoneInfo("Asia/Shanghai")


def market_today() -> date:
    """Return today's date in :data:`MARKET_TIMEZONE`.

    Uses :func:`datetime.now` with an explicit ``tz`` so the result is
    deterministic regardless of the host clock's UTC offset; an
    unaware :meth:`date.today` would silently follow the host's local
    timezone and disagree with the market calendar.
    """

    return datetime.now(MARKET_TIMEZONE).date()


__all__ = ["MARKET_TIMEZONE", "market_today"]
