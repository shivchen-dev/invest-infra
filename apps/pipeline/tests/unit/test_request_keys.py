from datetime import date

from invest_pipeline.request_keys import make_daily_bars_request_key


def test_short_daily_bars_key_preserves_legacy_format() -> None:
    assert make_daily_bars_request_key(
        date(2026, 7, 23), date(2026, 7, 30), ("510300", "510500")
    ) == "daily-bars-2026-07-23-2026-07-30-510300-510500"


def test_long_daily_bars_key_is_bounded_and_deterministic() -> None:
    symbols = tuple(f"{index:06d}" for index in range(16))
    first = make_daily_bars_request_key(date(2026, 1, 1), date(2026, 8, 4), symbols)
    second = make_daily_bars_request_key(date(2026, 1, 1), date(2026, 8, 4), symbols)
    assert first == second
    assert len(first) <= 128
    assert first == "daily-bars-2026-01-01-2026-08-04-symbols-" + first.rsplit("-", 1)[-1]


def test_symbol_order_changes_long_key() -> None:
    symbols = tuple(f"{index:06d}" for index in range(16))
    reversed_symbols = tuple(reversed(symbols))
    first = make_daily_bars_request_key(date(2026, 1, 1), date(2026, 8, 4), symbols)
    second = make_daily_bars_request_key(
        date(2026, 1, 1), date(2026, 8, 4), reversed_symbols
    )
    assert first != second
