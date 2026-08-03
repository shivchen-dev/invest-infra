"""Tests for ``invest_api.clock``.

The clock module is intentionally tiny but the bug it prevents is easy
to reintroduce silently: a server running in UTC can return Sunday's
date at 00:30 Beijing time on a Monday morning, which would make the
data-freshness banner point at the wrong trading day. These tests pin
the contract:

- :data:`MARKET_TIMEZONE` is fixed to ``Asia/Shanghai``.
- :func:`market_today` returns the date in that timezone, regardless of
  the host's UTC offset.
- Driving :func:`market_today` with a mocked ``datetime.now`` makes the
  roll-over decision auditable - tests never touch the built-in
  :meth:`date.today` class.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from invest_api import clock


class TestMarketTimezone:
    """Lock down the timezone choice so a refactor cannot silently change it."""

    def test_market_timezone_is_asia_shanghai(self) -> None:
        assert ZoneInfo("Asia/Shanghai") == clock.MARKET_TIMEZONE

    def test_market_timezone_key_matches(self) -> None:
        # The IANA key (not just equality) is what callers reason about
        # in logs and error messages; pin both forms.
        assert clock.MARKET_TIMEZONE.key == "Asia/Shanghai"


class TestMarketToday:
    """``market_today`` returns today's date in :data:`MARKET_TIMEZONE`."""

    def test_market_today_is_naive_date_instance(self) -> None:
        result = clock.market_today()
        assert isinstance(result, date)
        assert not isinstance(result, datetime)

    def test_market_today_tracks_asia_shanghai_calendar(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Force ``datetime.now`` so we can observe the timezone offset directly.

        The expectation is that ``datetime.now`` is called with
        ``MARKET_TIMEZONE`` as its ``tz`` argument - we assert the
        keyword rather than the return value because ``datetime.now``
        itself owns the wall-clock read.
        """

        captured: dict[str, object] = {}

        def _fake_now(tz: object | None = None) -> datetime:
            captured["tz"] = tz
            if tz is clock.MARKET_TIMEZONE:
                return datetime(2026, 8, 3, 0, 30, tzinfo=tz)
            return datetime(2026, 8, 2, 16, 30, tzinfo=tz)

        monkeypatch.setattr(clock, "datetime", type("D", (), {"now": staticmethod(_fake_now)}))

        assert clock.market_today() == date(2026, 8, 3)
        assert captured["tz"] == clock.MARKET_TIMEZONE

    def test_beijing_monday_early_morning_while_utc_is_sunday(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Beijing Monday 00:30 / UTC Sunday 16:30 still reports Monday.

        This is the regression the clock exists to prevent: without the
        explicit ``tz`` argument, ``datetime.now()`` on a UTC host
        would return Sunday and a downstream handler would look up the
        wrong trading day.
        """

        def _fake_now(tz: object | None = None) -> datetime:
            assert tz is clock.MARKET_TIMEZONE, (
                "market_today must read the Asia/Shanghai wall clock"
            )
            return datetime(2026, 8, 3, 0, 30, tzinfo=clock.MARKET_TIMEZONE)

        def _fake_now_utc() -> datetime:
            return datetime(2026, 8, 2, 16, 30, tzinfo=UTC)

        monkeypatch.setattr(clock, "datetime", type("D", (), {"now": staticmethod(_fake_now)}))

        assert clock.market_today() == date(2026, 8, 3)  # Monday in Shanghai
        # Sanity-check the simulated UTC instant - the local date in UTC
        # is still Sunday so a naive ``date.today()`` would have
        # returned 2026-08-02.
        assert _fake_now_utc().date() == date(2026, 8, 2)


__all__ = ["TestMarketTimezone", "TestMarketToday"]
