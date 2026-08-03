"""Focused validation for the Stage 4A 65-day research-window fixture.

The Stage 4A implementation plan §8 commits a 65-trading-day OHLCV/amount
fixture for a single ETF so the 60-day research window defined in §11.1
(return_60d, distance_ma60, realized_volatility_20d, max_drawdown_60d,
avg_turnover_amount_20d, data_completeness_60d) is provably satisfiable
before any Evidence Pack code is written. This test pins the four
invariants that block the slice:

1. The fixture carries at least 65 rows for a single symbol.
2. The trade dates form a consecutive weekday chain (no missing trading
   days in the [first, last] window).
3. No trade date is in the future relative to the wall clock at test
   run time. The slice cannot use future-dated data because every
   factor in §11 is a backward-looking ratio of past closes.
4. Every row carries an ``amount`` value and obeys the OHLC invariants
   shared with the rest of the project: ``low <= open/close <= high``
   and all four prices are strictly positive.

The fixture is intentionally small and pure-stdlib so this test can run
without installing the pipeline or storage packages; it only needs
``pytest`` and the JSON file on disk. The fixture path is resolved
relative to the test file so the test is independent of the caller's
working directory.
"""

from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    .parent
    .parent
    .parent
    .parent
    / "tests"
    / "fixtures"
    / "research"
    / "etf_daily_bars_65d.json"
)

MIN_ROWS_FOR_SIXTY_DAY_WINDOW = 65
RESEARCH_SYMBOL = "510300"
REQUIRED_FIELDS = frozenset(
    {
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "prev_close",
        "volume",
        "amount",
        "trading_status",
    }
)


def _load_fixture() -> list[dict[str, object]]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise AssertionError(
            f"research fixture must be a JSON list, got {type(payload).__name__}"
        )
    return [dict(entry) for entry in payload]


def _trade_dates(rows: list[dict[str, object]]) -> list[date]:
    out: list[date] = []
    for row in rows:
        raw = row.get("trade_date")
        if not isinstance(raw, str):
            raise AssertionError(f"trade_date must be a string, got {raw!r}")
        out.append(date.fromisoformat(raw))
    return out


class ResearchFixtureShapeTest(unittest.TestCase):
    """The on-disk file has the JSON shape the rest of the project expects."""

    def test_fixture_path_exists(self) -> None:
        self.assertTrue(
            FIXTURE_PATH.exists(),
            f"missing Stage 4A research fixture at {FIXTURE_PATH}",
        )

    def test_fixture_is_a_list_of_records_with_required_fields(self) -> None:
        rows = _load_fixture()
        self.assertGreater(len(rows), 0, "fixture is empty")
        for index, row in enumerate(rows):
            missing = REQUIRED_FIELDS - set(row)
            self.assertFalse(
                missing,
                f"row {index} missing fields {sorted(missing)}",
            )

    def test_fixture_targets_a_single_symbol(self) -> None:
        rows = _load_fixture()
        symbols = {str(row["symbol"]) for row in rows}
        self.assertEqual(
            symbols,
            {RESEARCH_SYMBOL},
            f"Stage 4A §8.1 commits the 65-day window to {RESEARCH_SYMBOL!r}; "
            f"got {sorted(symbols)}",
        )


class ResearchFixtureWindowTest(unittest.TestCase):
    """The fixture must satisfy the 60-day research window defined in §11.1."""

    def test_fixture_has_at_least_65_rows(self) -> None:
        rows = _load_fixture()
        self.assertGreaterEqual(
            len(rows),
            MIN_ROWS_FOR_SIXTY_DAY_WINDOW,
            f"60-day research window needs >= {MIN_ROWS_FOR_SIXTY_DAY_WINDOW} "
            f"trading days, fixture has only {len(rows)}",
        )

    def test_dates_form_consecutive_weekday_chain(self) -> None:
        rows = _load_fixture()
        dates = _trade_dates(rows)
        if not dates:
            self.fail("fixture has no rows")
        first, last = dates[0], dates[-1]
        expected: list[date] = []
        cursor = first
        while cursor <= last:
            if cursor.weekday() < 5:
                expected.append(cursor)
            cursor += timedelta(days=1)
        self.assertEqual(
            dates,
            expected,
            "trade_date chain has a weekday gap; Stage 4A §8.1 requires "
            "consecutive trading days",
        )

    def test_first_date_strictly_before_last_date(self) -> None:
        rows = _load_fixture()
        dates = _trade_dates(rows)
        self.assertLess(
            dates[0],
            dates[-1],
            "first and last trade_date must be different to define a window",
        )

    def test_window_covers_at_least_60_calendar_days(self) -> None:
        """60 trading days span ~88 calendar days; sanity-check the span."""

        rows = _load_fixture()
        dates = _trade_dates(rows)
        span = (dates[-1] - dates[0]).days
        self.assertGreaterEqual(
            span,
            60,
            f"research window spans {span} calendar days; expected >= 60",
        )


class ResearchFixtureFutureDateGuardTest(unittest.TestCase):
    """The fixture must never carry a future-dated row (Stage 4A §8.1)."""

    def test_no_trade_date_in_the_future(self) -> None:
        rows = _load_fixture()
        today = date.today()
        future_rows = [
            (index, row["trade_date"])
            for index, row in enumerate(rows)
            if date.fromisoformat(str(row["trade_date"])) > today
        ]
        self.assertEqual(
            future_rows,
            [],
            "future-dated fixture rows are not allowed; the research window "
            f"can only consume data on or before today ({today.isoformat()}): "
            f"{future_rows[:5]}",
        )

    def test_latest_trade_date_is_not_in_the_future(self) -> None:
        rows = _load_fixture()
        latest = _trade_dates(rows)[-1]
        today = date.today()
        self.assertLessEqual(
            latest,
            today,
            f"latest trade_date {latest.isoformat()} is after today "
            f"({today.isoformat()}); the fixture is allowed to lag the wall "
            "clock but must never lead it",
        )


class ResearchFixtureBarInvariantsTest(unittest.TestCase):
    """Every row obeys the OHLC/amount invariants shared with fixture_dev."""

    def test_every_row_has_positive_prices_and_consistent_ohlc(self) -> None:
        for index, row in enumerate(_load_fixture()):
            o = Decimal(str(row["open"]))
            h = Decimal(str(row["high"]))
            low = Decimal(str(row["low"]))
            c = Decimal(str(row["close"]))
            self.assertGreater(o, 0, f"row {index}: non-positive open")
            self.assertGreater(h, 0, f"row {index}: non-positive high")
            self.assertGreater(low, 0, f"row {index}: non-positive low")
            self.assertGreater(c, 0, f"row {index}: non-positive close")
            self.assertGreaterEqual(
                h,
                max(o, c, low),
                f"row {index}: high {h} < max(open, close, low)={max(o, c, low)}",
            )
            self.assertLessEqual(
                low,
                min(o, c, h),
                f"row {index}: low {low} > min(open, close, high)={min(o, c, h)}",
            )

    def test_every_row_has_non_null_amount(self) -> None:
        """avg_turnover_amount_20d (§11) requires a usable amount field."""

        for index, row in enumerate(_load_fixture()):
            raw_amount = row["amount"]
            self.assertIsNotNone(
                raw_amount,
                f"row {index}: amount is required for avg_turnover_amount_20d",
            )
            amount = Decimal(str(raw_amount))
            self.assertGreater(
                amount,
                Decimal("0"),
                f"row {index}: amount must be positive, got {amount}",
            )

    def test_trading_status_is_normal_for_every_row(self) -> None:
        for index, row in enumerate(_load_fixture()):
            self.assertEqual(
                row["trading_status"],
                "normal",
                f"row {index}: trading_status must be 'normal' for the "
                "Stage 4A 65-day window",
            )


if __name__ == "__main__":
    unittest.main()