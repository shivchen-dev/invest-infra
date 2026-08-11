"""Closed-set value types shared across bounded contexts.

These enumerations are intentionally restrictive:

- ``Adjust`` is frozen to ``NONE`` for production rows; ``QFQ``/``HFQ`` are
  reserved enum members (per ADR-0005) that domain code must reject when
  building ``DailyBar`` instances. Adopting a non-``NONE`` adjustment in
  production requires a new ADR.
- ``Exchange`` is restricted to ``SSE`` and ``SZSE`` for the ADR-0004
  ETF vertical slice. ``BJSE`` (Beijing Stock Exchange) is admitted for
  the Stage 4B A-share stock scope and remains out of scope for
  ADR-0004 (i.e. ETF mappers must still reject ``BJSE`` via their
  own allow-list — the domain enum only widens the canonical set).
  Any further exchange must be added by amending the relevant ADR
  and updating domain-level validation here.
- ``Currency`` is restricted to ``CNY`` for the Phase 1 ETF vertical slice.
- ``TradingStatus`` enumerates the only two trading-state values a stored
  ``DailyBar`` row may carry. Missing trading days are represented by the
  absence of a row, never by a row with status ``MISSING``.

This module is a leaf: it has zero internal-domain dependencies. Both
``instruments`` and ``market_data`` import from here, which keeps the
dependency graph acyclic.
"""

from __future__ import annotations

from enum import StrEnum


class Adjust(StrEnum):
    """Adjustment policy applied to a price series.

    Production code paths may only build rows with ``Adjust.NONE``. The
    ``QFQ`` and ``HFQ`` members exist for future extension and are
    explicitly rejected by :class:`invest_domain.market_data.models.DailyBar`.
    Adopting them in production requires ADR-0005 to be amended.
    """

    NONE = "none"
    QFQ = "qfq"
    HFQ = "hfq"

    @classmethod
    def production_only(cls) -> tuple["Adjust", ...]:
        return (cls.NONE,)


class TradingStatus(StrEnum):
    """Trading status of an instrument on a specific ``trade_date``.

    ``NORMAL`` rows carry complete OHLCV. ``SUSPENDED`` rows are
    explicitly marked and must not fabricate OHLC from prior closes
    (see ADR-0005). Missing data is represented by the absence of a row
    and is not encoded in this enum.
    """

    NORMAL = "normal"
    SUSPENDED = "suspended"


class Currency(StrEnum):
    """ISO-like currency codes accepted in Phase 1.

    Phase 1 covers only CNY-denominated ETFs on SSE / SZSE; ``USD``/``HKD``
    must not appear in production rows until ADR-0004 is amended.
    """

    CNY = "CNY"


class Exchange(StrEnum):
    """On-exchange identifiers accepted in Phase 1.

    Per ADR-0004, only ``SSE`` and ``SZSE`` are valid for the ETF
    vertical slice. ``BJSE`` is admitted for the Stage 4B A-share
    stock scope (Tushare ``.BJ`` ts_code suffix) and must not appear
    in ETF-only flows — ETF mappers enforce their own ADR-0004
    allow-list and reject ``BJSE`` explicitly. Adding a new exchange
    requires amending the relevant ADR and updating domain-level
    validation here.
    """

    SSE = "SSE"
    SZSE = "SZSE"
    BJSE = "BJSE"
