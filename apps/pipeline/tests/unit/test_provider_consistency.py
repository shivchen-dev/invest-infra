"""Unit tests for ``invest_pipeline.provider_consistency``.

Covers the validation contract (input types, mixed
provider/adjustment, duplicates, same-provider), the happy path of
fully matching batches, field-level disagreements on every compared
field, asymmetric missing keys, stable ordering across multiple
mismatches and missing keys, and exact numeric ``Decimal`` comparison
without tolerance (equivalent scales are equal; distinct values are not).
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from invest_domain.instruments.models import InstrumentId
from invest_domain.market_data.models import (
    BarSource,
    DailyBar,
    ProviderBatch,
    ProviderBatchStatus,
)
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_pipeline.provider_consistency import (
    COMPARED_FIELDS,
    DailyBarKey,
    FieldMismatch,
    ProviderConsistencyReport,
    compare_daily_bar_batches,
)

_RAW_PAYLOAD_HASH = "0" * 64


def _bar_source(provider_key: str) -> BarSource:
    return BarSource(
        provider_key=provider_key,
        source_batch_id=uuid4(),
        observed_at=datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC),
    )


def _instrument_id(seed: int) -> InstrumentId:
    return InstrumentId(UUID(int=seed))


def _bar(
    *,
    seed: int,
    trade_date: date,
    adjustment: Adjust = Adjust.NONE,
    provider_key: str = "fixture_dev",
    open_: str = "10.00",
    high: str = "11.00",
    low: str = "9.00",
    close: str = "10.50",
    prev_close: str | None = "9.50",
    volume: str | None = "1000",
    amount: str | None = "10000",
    trading_status: TradingStatus = TradingStatus.NORMAL,
) -> DailyBar:
    return DailyBar.build(
        instrument_id=_instrument_id(seed),
        trade_date=trade_date,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        prev_close=Decimal(prev_close) if prev_close is not None else None,
        volume=Decimal(volume) if volume is not None else None,
        amount=Decimal(amount) if amount is not None else None,
        adjustment=adjustment,
        trading_status=trading_status,
        source=_bar_source(provider_key),
        revision=1,
    )


def _batch(bars: list[DailyBar], *, provider_key: str) -> ProviderBatch[DailyBar]:
    if not bars:
        raise AssertionError("_batch requires at least one bar")
    keys = {bar.source.provider_key for bar in bars}
    assert keys == {provider_key}, keys
    return ProviderBatch[DailyBar](
        attempt_id=uuid4(),
        records=tuple(bars),
        raw_payload_hash=_RAW_PAYLOAD_HASH,
        status=ProviderBatchStatus.SUCCEEDED,
    )


class CompareDailyBarBatchesConsistentTest(unittest.TestCase):
    def test_identical_content_yields_no_mismatches(self) -> None:
        bars = [
            _bar(seed=1, trade_date=date(2024, 1, 2), provider_key="cifangquant"),
            _bar(seed=2, trade_date=date(2024, 1, 3), provider_key="cifangquant"),
            _bar(seed=3, trade_date=date(2024, 1, 4), provider_key="cifangquant"),
        ]
        left = _batch(bars, provider_key="cifangquant")
        right = _batch(
            [
                _bar(
                    seed=1,
                    trade_date=date(2024, 1, 2),
                    provider_key="fixture_dev",
                ),
                _bar(
                    seed=2,
                    trade_date=date(2024, 1, 3),
                    provider_key="fixture_dev",
                ),
                _bar(
                    seed=3,
                    trade_date=date(2024, 1, 4),
                    provider_key="fixture_dev",
                ),
            ],
            provider_key="fixture_dev",
        )

        report = compare_daily_bar_batches(left, right)

        self.assertEqual(
            report,
            ProviderConsistencyReport(
                left_provider="cifangquant",
                right_provider="fixture_dev",
                matched_count=3,
                missing_left=(),
                missing_right=(),
                mismatches=(),
            ),
        )


class CompareDailyBarBatchesFieldDifferencesTest(unittest.TestCase):
    def test_every_compared_field_can_differ(self) -> None:
        trade_date = date(2024, 2, 1)
        left_bar = _bar(
            seed=42,
            trade_date=trade_date,
            provider_key="cifangquant",
            open_="10.00",
            high="11.00",
            low="9.00",
            close="10.50",
            prev_close="9.50",
            volume="1000",
            amount="10000",
        )
        right_bar = _bar(
            seed=42,
            trade_date=trade_date,
            provider_key="fixture_dev",
            open_="10.10",
            high="11.20",
            low="8.90",
            close="10.60",
            prev_close="9.60",
            volume="1001",
            amount="10100",
        )

        left = _batch([left_bar], provider_key="cifangquant")
        right = _batch([right_bar], provider_key="fixture_dev")

        report = compare_daily_bar_batches(left, right)

        self.assertEqual(report.matched_count, 1)
        self.assertEqual(report.missing_left, ())
        self.assertEqual(report.missing_right, ())
        self.assertEqual(
            [mismatch.field for mismatch in report.mismatches],
            list(COMPARED_FIELDS),
        )
        expected_key = DailyBarKey(
            instrument_id=_instrument_id(42).value,
            trade_date=trade_date,
            adjustment=Adjust.NONE.value,
        )
        actual_values = {
            mismatch.field: (mismatch.left_value, mismatch.right_value)
            for mismatch in report.mismatches
        }
        self.assertEqual(
            actual_values,
            {
                "open": (Decimal("10.00"), Decimal("10.10")),
                "high": (Decimal("11.00"), Decimal("11.20")),
                "low": (Decimal("9.00"), Decimal("8.90")),
                "close": (Decimal("10.50"), Decimal("10.60")),
                "prev_close": (Decimal("9.50"), Decimal("9.60")),
                "volume": (Decimal("1000"), Decimal("1001")),
                "amount": (Decimal("10000"), Decimal("10100")),
            },
        )
        for mismatch in report.mismatches:
            self.assertEqual(mismatch.key, expected_key)
            self.assertIsInstance(mismatch, FieldMismatch)

    def test_decimal_equality_uses_exact_value_comparison(self) -> None:
        """Decimal comparison is preserved bit-for-bit in the report.

        Two ``Decimal`` instances that compare equal under ``Decimal('1.10') ==
        Decimal('1.1')`` MUST NOT produce a false mismatch (the equality
        contract must match the value, not the textual rendering), and
        two values whose Decimal difference is exactly one ``min_yu``
        unit MUST be reported as a real mismatch. This pins the
        implementation's ``!=`` semantics so a future ``float`` swap
        would break this test loud and early.
        """

        trade_date = date(2024, 2, 2)
        matching_left = _bar(
            seed=7,
            trade_date=trade_date,
            provider_key="cifangquant",
            open_="1.00",
            high="1.20",
            low="0.90",
            close="1.10",
        )
        matching_right = _bar(
            seed=7,
            trade_date=trade_date,
            provider_key="fixture_dev",
            open_="1.00",
            high="1.20",
            low="0.90",
            close="1.1",
        )
        match_report = compare_daily_bar_batches(
            _batch([matching_left], provider_key="cifangquant"),
            _batch([matching_right], provider_key="fixture_dev"),
        )
        self.assertEqual(match_report.matched_count, 1)
        self.assertEqual(match_report.mismatches, ())

        differing_left = _bar(
            seed=8,
            trade_date=trade_date,
            provider_key="cifangquant",
            open_="1.00",
            high="1.20",
            low="0.90",
            close=Decimal("1.10"),
        )
        differing_right = _bar(
            seed=8,
            trade_date=trade_date,
            provider_key="fixture_dev",
            open_="1.00",
            high="1.20",
            low="0.90",
            close=Decimal("1.11"),
        )
        self.assertNotEqual(Decimal("1.10"), Decimal("1.11"))
        mismatch_report = compare_daily_bar_batches(
            _batch([differing_left], provider_key="cifangquant"),
            _batch([differing_right], provider_key="fixture_dev"),
        )
        self.assertEqual(mismatch_report.matched_count, 1)
        self.assertEqual(len(mismatch_report.mismatches), 1)
        mismatch = mismatch_report.mismatches[0]
        self.assertEqual(mismatch.field, "close")
        self.assertEqual(mismatch.left_value, Decimal("1.10"))
        self.assertEqual(mismatch.right_value, Decimal("1.11"))

    def test_prev_close_none_on_both_sides_is_agreement(self) -> None:
        trade_date = date(2024, 2, 3)
        left_bar = _bar(
            seed=9,
            trade_date=trade_date,
            provider_key="cifangquant",
            prev_close=None,
        )
        right_bar = _bar(
            seed=9,
            trade_date=trade_date,
            provider_key="fixture_dev",
            prev_close=None,
        )

        report = compare_daily_bar_batches(
            _batch([left_bar], provider_key="cifangquant"),
            _batch([right_bar], provider_key="fixture_dev"),
        )

        self.assertEqual(report.mismatches, ())
        self.assertEqual(report.matched_count, 1)


class CompareDailyBarBatchesMissingKeysTest(unittest.TestCase):
    def test_asymmetric_missing_keys_are_reported_sorted(self) -> None:
        shared_date = date(2024, 3, 1)
        left_bars = [
            _bar(seed=1, trade_date=shared_date, provider_key="cifangquant"),
            _bar(seed=2, trade_date=shared_date, provider_key="cifangquant"),
        ]
        right_bars = [
            _bar(seed=2, trade_date=shared_date, provider_key="fixture_dev"),
            _bar(seed=3, trade_date=shared_date, provider_key="fixture_dev"),
        ]

        report = compare_daily_bar_batches(
            _batch(left_bars, provider_key="cifangquant"),
            _batch(right_bars, provider_key="fixture_dev"),
        )

        self.assertEqual(report.left_provider, "cifangquant")
        self.assertEqual(report.right_provider, "fixture_dev")
        self.assertEqual(report.matched_count, 1)
        self.assertEqual(
            report.missing_left,
            (
                DailyBarKey(
                    instrument_id=_instrument_id(1).value,
                    trade_date=shared_date,
                    adjustment=Adjust.NONE.value,
                ),
            ),
        )
        self.assertEqual(
            report.missing_right,
            (
                DailyBarKey(
                    instrument_id=_instrument_id(3).value,
                    trade_date=shared_date,
                    adjustment=Adjust.NONE.value,
                ),
            ),
        )


class CompareDailyBarBatchesDuplicateKeyTest(unittest.TestCase):
    def test_duplicate_key_in_left_raises_value_error(self) -> None:
        trade_date = date(2024, 4, 1)
        left_bars = [
            _bar(seed=1, trade_date=trade_date, provider_key="cifangquant"),
            _bar(seed=1, trade_date=trade_date, provider_key="cifangquant"),
        ]
        right_bars = [_bar(seed=1, trade_date=trade_date, provider_key="fixture_dev")]

        with self.assertRaises(ValueError) as ctx:
            compare_daily_bar_batches(
                _batch(left_bars, provider_key="cifangquant"),
                _batch(right_bars, provider_key="fixture_dev"),
            )
        self.assertIn("duplicate key", str(ctx.exception))
        self.assertIn("left", str(ctx.exception))

    def test_duplicate_key_in_right_raises_value_error(self) -> None:
        trade_date = date(2024, 4, 2)
        left_bars = [_bar(seed=1, trade_date=trade_date, provider_key="cifangquant")]
        right_bars = [
            _bar(seed=1, trade_date=trade_date, provider_key="fixture_dev"),
            _bar(seed=1, trade_date=trade_date, provider_key="fixture_dev"),
        ]

        with self.assertRaises(ValueError) as ctx:
            compare_daily_bar_batches(
                _batch(left_bars, provider_key="cifangquant"),
                _batch(right_bars, provider_key="fixture_dev"),
            )
        self.assertIn("duplicate key", str(ctx.exception))
        self.assertIn("right", str(ctx.exception))


class CompareDailyBarBatchesSameProviderTest(unittest.TestCase):
    def test_same_provider_key_on_both_sides_rejected(self) -> None:
        trade_date = date(2024, 5, 1)
        bar_a = _bar(seed=1, trade_date=trade_date, provider_key="fixture_dev")
        bar_b = _bar(seed=1, trade_date=trade_date, provider_key="fixture_dev")

        with self.assertRaises(ValueError) as ctx:
            compare_daily_bar_batches(
                _batch([bar_a], provider_key="fixture_dev"),
                _batch([bar_b], provider_key="fixture_dev"),
            )
        self.assertIn("different providers", str(ctx.exception))


class CompareDailyBarBatchesTypeValidationTest(unittest.TestCase):
    def test_non_provider_batch_left_raises_type_error(self) -> None:
        with self.assertRaises(TypeError) as ctx:
            compare_daily_bar_batches("not a batch", object())  # type: ignore[arg-type]
        self.assertIn("left", str(ctx.exception))
        self.assertIn("ProviderBatch", str(ctx.exception))

    def test_non_provider_batch_right_raises_type_error(self) -> None:
        bars = [_bar(seed=1, trade_date=date(2024, 6, 1), provider_key="cifangquant")]
        with self.assertRaises(TypeError) as ctx:
            compare_daily_bar_batches(
                _batch(bars, provider_key="cifangquant"),
                42,
            )
        self.assertIn("right", str(ctx.exception))

    def test_non_daily_bar_records_raise_type_error(self) -> None:
        right_bars = [
            _bar(seed=1, trade_date=date(2024, 6, 1), provider_key="fixture_dev")
        ]
        with self.assertRaises(TypeError) as ctx:
            compare_daily_bar_batches(
                ProviderBatch[DailyBar](
                    attempt_id=uuid4(),
                    records=("not-a-daily-bar",),
                    raw_payload_hash=_RAW_PAYLOAD_HASH,
                ),
                _batch(right_bars, provider_key="fixture_dev"),
            )
        self.assertIn("DailyBar", str(ctx.exception))


class CompareDailyBarBatchesIntraBatchConsistencyTest(unittest.TestCase):
    def test_mixed_provider_key_within_left_raises_value_error(self) -> None:
        trade_date = date(2024, 7, 1)
        left_bars = [
            _bar(seed=1, trade_date=trade_date, provider_key="cifangquant"),
            _bar(seed=2, trade_date=trade_date, provider_key="fixture_dev"),
        ]
        right_bars = [_bar(seed=1, trade_date=trade_date, provider_key="akshare")]

        with self.assertRaises(ValueError) as ctx:
            compare_daily_bar_batches(
                ProviderBatch[DailyBar](
                    attempt_id=uuid4(),
                    records=tuple(left_bars),
                    raw_payload_hash=_RAW_PAYLOAD_HASH,
                ),
                _batch(right_bars, provider_key="akshare"),
            )
        self.assertIn("single source.provider_key", str(ctx.exception))
        self.assertIn("left", str(ctx.exception))

    def test_uniform_adjustment_in_both_batches_is_carried_in_keys(self) -> None:
        trade_date = date(2024, 7, 2)
        left_bar = _bar(
            seed=1,
            trade_date=trade_date,
            provider_key="cifangquant",
        )
        right_bar = _bar(
            seed=1,
            trade_date=trade_date,
            provider_key="fixture_dev",
            open_="20.00",
            high="21.00",
            low="19.00",
            close="20.50",
        )

        report = compare_daily_bar_batches(
            _batch([left_bar], provider_key="cifangquant"),
            _batch([right_bar], provider_key="fixture_dev"),
        )

        self.assertEqual(report.matched_count, 1)
        self.assertEqual(len(report.mismatches), 4)
        self.assertTrue(
            all(mismatch.key.adjustment == Adjust.NONE.value for mismatch in report.mismatches)
        )
        self.assertTrue(
            all(mismatch.key.adjustment == "none" for mismatch in report.mismatches)
        )

    def test_empty_batch_raises_value_error(self) -> None:
        empty_left = ProviderBatch[DailyBar](
            attempt_id=uuid4(),
            records=(),
            raw_payload_hash=_RAW_PAYLOAD_HASH,
        )
        right_bars = [_bar(seed=1, trade_date=date(2024, 7, 3), provider_key="fixture_dev")]

        with self.assertRaises(ValueError) as ctx:
            compare_daily_bar_batches(
                empty_left,
                _batch(right_bars, provider_key="fixture_dev"),
            )
        self.assertIn("at least one DailyBar", str(ctx.exception))
        self.assertIn("left", str(ctx.exception))


class CompareDailyBarBatchesOrderingTest(unittest.TestCase):
    def test_mismatch_ordering_is_key_then_field(self) -> None:
        trade_date_one = date(2024, 8, 1)
        trade_date_two = date(2024, 8, 2)
        left_bars = [
            _bar(seed=2, trade_date=trade_date_two, provider_key="cifangquant"),
            _bar(seed=1, trade_date=trade_date_one, provider_key="cifangquant"),
        ]
        right_bars = [
            _bar(
                seed=1,
                trade_date=trade_date_one,
                provider_key="fixture_dev",
                open_="20.00",
                high="21.00",
                low="19.00",
                close="20.50",
            ),
            _bar(
                seed=2,
                trade_date=trade_date_two,
                provider_key="fixture_dev",
                open_="30.00",
                high="31.00",
                low="29.00",
                close="30.50",
            ),
        ]
        # The left batch keeps the original defaults (open=10, close=10.50,
        # high=11, low=9) so close/high/open vs the right side's much
        # larger values produce the expected mismatches.

        report = compare_daily_bar_batches(
            _batch(left_bars, provider_key="cifangquant"),
            _batch(right_bars, provider_key="fixture_dev"),
        )

        expected_key_one = DailyBarKey(
            instrument_id=_instrument_id(1).value,
            trade_date=trade_date_one,
            adjustment=Adjust.NONE.value,
        )
        expected_key_two = DailyBarKey(
            instrument_id=_instrument_id(2).value,
            trade_date=trade_date_two,
            adjustment=Adjust.NONE.value,
        )
        expected_order: tuple[tuple[DailyBarKey, str], ...] = (
            (expected_key_one, "open"),
            (expected_key_one, "high"),
            (expected_key_one, "low"),
            (expected_key_one, "close"),
            (expected_key_two, "open"),
            (expected_key_two, "high"),
            (expected_key_two, "low"),
            (expected_key_two, "close"),
        )
        self.assertEqual(
            tuple((m.key, m.field) for m in report.mismatches),
            expected_order,
        )

    def test_missing_keys_are_stably_sorted_across_dates(self) -> None:
        shared_dates = {
            1: date(2024, 9, 3),
            2: date(2024, 9, 2),
            3: date(2024, 9, 1),
        }
        left_bars = [
            _bar(seed=3, trade_date=shared_dates[3], provider_key="cifangquant"),
            _bar(seed=1, trade_date=shared_dates[1], provider_key="cifangquant"),
            _bar(seed=2, trade_date=shared_dates[2], provider_key="cifangquant"),
        ]
        right_bars = [
            _bar(seed=1, trade_date=shared_dates[1], provider_key="fixture_dev"),
            _bar(seed=3, trade_date=shared_dates[3], provider_key="fixture_dev"),
        ]

        report = compare_daily_bar_batches(
            _batch(left_bars, provider_key="cifangquant"),
            _batch(right_bars, provider_key="fixture_dev"),
        )

        expected_missing_left = (
            DailyBarKey(
                instrument_id=_instrument_id(2).value,
                trade_date=shared_dates[2],
                adjustment=Adjust.NONE.value,
            ),
        )
        self.assertEqual(report.matched_count, 2)
        self.assertEqual(report.missing_left, expected_missing_left)
        self.assertEqual(report.missing_right, ())
        self.assertEqual(report.mismatches, ())


if __name__ == "__main__":
    unittest.main()
