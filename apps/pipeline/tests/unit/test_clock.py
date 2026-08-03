from __future__ import annotations

from datetime import UTC, datetime

from invest_pipeline import clock


def test_market_today_uses_asia_shanghai_at_utc_midnight_boundary(
    monkeypatch,
) -> None:
    class FakeDateTime:
        @classmethod
        def now(cls, tz):
            return datetime(2026, 8, 2, 16, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(clock, "datetime", FakeDateTime)

    assert clock.market_today().isoformat() == "2026-08-03"
