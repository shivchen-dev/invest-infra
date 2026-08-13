"""Golden consistency comparison between the ``tushare`` and
``tdx_offline`` providers.

This module pins the comparison contract for one canonical
``(tushare, tdx_offline)`` reconciliation shape used as the regression
artifact of the etf_daily_bars migration smoke tests. Three fixed
instruments are compared on a single trade date so the report shape
is fully deterministic and easy to eyeball.

Three scenarios are covered:

1. **Full agreement** — both providers return identical bars for all
   three instruments: ``matched_count=3``, no missing keys, no field
   mismatches.
2. **Asymmetric gap with a single-field disagreement** — TDX is
   missing one instrument AND has a different ``prev_close`` for
   another: exactly one ``prev_close`` mismatch on the right keys,
   with the correct missing key recorded on the TDX side and the
   provider names correctly propagated to the report.
3. **Idempotence** — running the same comparison twice on freshly
   constructed batches yields equal reports, proving the comparator
   has no non-deterministic ordering or side effects.

No network, no clock dependency, no shared state — everything is a
literal fixture.
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
    DailyBarKey,
    compare_daily_bar_batches,
)

TRADE_DATE = date(2026, 8, 12)

INSTRUMENT_ID_1 = UUID("11111111-1111-1111-1111-111111111111")
INSTRUMENT_ID_2 = UUID("22222222-2222-2222-2222-222222222222")
INSTRUMENT_ID_3 = UUID("33333333-3333-3333-3333-333333333333")

TUSHARE_PROVIDER_KEY = "tushare"
TDX_OFFLINE_PROVIDER_KEY = "tdx_offline"

_RAW_PAYLOAD_HASH = "0" * 64


def _make_bar(
    *,
    instrument_id: UUID,
    trade_date: date,
    provider_key: str,
    open_: str = "10.00",
    high: str = "11.00",
    low: str = "9.00",
    close: str = "10.50",
    prev_close: str = "9.50",
    volume: str = "1000",
    amount: str = "10000",
) -> DailyBar:
    return DailyBar.build(
        instrument_id=InstrumentId(instrument_id),
        trade_date=trade_date,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        prev_close=Decimal(prev_close),
        volume=Decimal(volume),
        amount=Decimal(amount),
        adjustment=Adjust.NONE,
        trading_status=TradingStatus.NORMAL,
        source=BarSource(
            provider_key=provider_key,
            source_batch_id=uuid4(),
            observed_at=datetime(2026, 8, 12, 0, 0, 0, tzinfo=UTC),
        ),
        revision=1,
    )


def _make_batch(bars: list[DailyBar], *, provider_key: str) -> ProviderBatch[DailyBar]:
    if not bars:
        raise AssertionError("_make_batch requires at least one bar")
    keys = {bar.source.provider_key for bar in bars}
    assert keys == {provider_key}, keys
    return ProviderBatch[DailyBar](
        attempt_id=uuid4(),
        records=tuple(bars),
        raw_payload_hash=_RAW_PAYLOAD_HASH,
        status=ProviderBatchStatus.SUCCEEDED,
    )


class TushareTdxOfflineConsistencyGoldenTest(unittest.TestCase):
    def test_identical_three_bars_yields_matched_count_three_no_mismatches(
        self,
    ) -> None:
        left_bars = [
            _make_bar(
                instrument_id=INSTRUMENT_ID_1,
                trade_date=TRADE_DATE,
                provider_key=TUSHARE_PROVIDER_KEY,
            ),
            _make_bar(
                instrument_id=INSTRUMENT_ID_2,
                trade_date=TRADE_DATE,
                provider_key=TUSHARE_PROVIDER_KEY,
            ),
            _make_bar(
                instrument_id=INSTRUMENT_ID_3,
                trade_date=TRADE_DATE,
                provider_key=TUSHARE_PROVIDER_KEY,
            ),
        ]
        right_bars = [
            _make_bar(
                instrument_id=INSTRUMENT_ID_1,
                trade_date=TRADE_DATE,
                provider_key=TDX_OFFLINE_PROVIDER_KEY,
            ),
            _make_bar(
                instrument_id=INSTRUMENT_ID_2,
                trade_date=TRADE_DATE,
                provider_key=TDX_OFFLINE_PROVIDER_KEY,
            ),
            _make_bar(
                instrument_id=INSTRUMENT_ID_3,
                trade_date=TRADE_DATE,
                provider_key=TDX_OFFLINE_PROVIDER_KEY,
            ),
        ]

        report = compare_daily_bar_batches(
            _make_batch(left_bars, provider_key=TUSHARE_PROVIDER_KEY),
            _make_batch(right_bars, provider_key=TDX_OFFLINE_PROVIDER_KEY),
        )

        self.assertEqual(report.left_provider, TUSHARE_PROVIDER_KEY)
        self.assertEqual(report.right_provider, TDX_OFFLINE_PROVIDER_KEY)
        self.assertEqual(report.matched_count, 3)
        self.assertEqual(report.missing_left, ())
        self.assertEqual(report.missing_right, ())
        self.assertEqual(report.mismatches, ())

    def test_tdx_missing_one_instrument_with_prev_close_mismatch_on_another(
        self,
    ) -> None:
        left_bars = [
            _make_bar(
                instrument_id=INSTRUMENT_ID_1,
                trade_date=TRADE_DATE,
                provider_key=TUSHARE_PROVIDER_KEY,
            ),
            _make_bar(
                instrument_id=INSTRUMENT_ID_2,
                trade_date=TRADE_DATE,
                provider_key=TUSHARE_PROVIDER_KEY,
            ),
            _make_bar(
                instrument_id=INSTRUMENT_ID_3,
                trade_date=TRADE_DATE,
                provider_key=TUSHARE_PROVIDER_KEY,
            ),
        ]
        right_bars = [
            _make_bar(
                instrument_id=INSTRUMENT_ID_1,
                trade_date=TRADE_DATE,
                provider_key=TDX_OFFLINE_PROVIDER_KEY,
            ),
            _make_bar(
                instrument_id=INSTRUMENT_ID_2,
                trade_date=TRADE_DATE,
                provider_key=TDX_OFFLINE_PROVIDER_KEY,
                prev_close="9.60",
            ),
        ]

        report = compare_daily_bar_batches(
            _make_batch(left_bars, provider_key=TUSHARE_PROVIDER_KEY),
            _make_batch(right_bars, provider_key=TDX_OFFLINE_PROVIDER_KEY),
        )

        self.assertEqual(report.left_provider, TUSHARE_PROVIDER_KEY)
        self.assertEqual(report.right_provider, TDX_OFFLINE_PROVIDER_KEY)
        self.assertEqual(report.matched_count, 2)
        self.assertEqual(
            report.missing_left,
            (
                DailyBarKey(
                    instrument_id=INSTRUMENT_ID_3,
                    trade_date=TRADE_DATE,
                    adjustment=Adjust.NONE.value,
                ),
            ),
        )
        self.assertEqual(report.missing_right, ())
        self.assertEqual(len(report.mismatches), 1)
        mismatch = report.mismatches[0]
        self.assertEqual(
            mismatch.key,
            DailyBarKey(
                instrument_id=INSTRUMENT_ID_2,
                trade_date=TRADE_DATE,
                adjustment=Adjust.NONE.value,
            ),
        )
        self.assertEqual(mismatch.field, "prev_close")
        self.assertEqual(mismatch.left_value, Decimal("9.50"))
        self.assertEqual(mismatch.right_value, Decimal("9.60"))

    def test_running_comparison_twice_yields_equal_report(self) -> None:
        left_bars = [
            _make_bar(
                instrument_id=INSTRUMENT_ID_1,
                trade_date=TRADE_DATE,
                provider_key=TUSHARE_PROVIDER_KEY,
            ),
            _make_bar(
                instrument_id=INSTRUMENT_ID_2,
                trade_date=TRADE_DATE,
                provider_key=TUSHARE_PROVIDER_KEY,
            ),
            _make_bar(
                instrument_id=INSTRUMENT_ID_3,
                trade_date=TRADE_DATE,
                provider_key=TUSHARE_PROVIDER_KEY,
            ),
        ]
        right_bars = [
            _make_bar(
                instrument_id=INSTRUMENT_ID_1,
                trade_date=TRADE_DATE,
                provider_key=TDX_OFFLINE_PROVIDER_KEY,
            ),
            _make_bar(
                instrument_id=INSTRUMENT_ID_2,
                trade_date=TRADE_DATE,
                provider_key=TDX_OFFLINE_PROVIDER_KEY,
                prev_close="9.60",
            ),
        ]

        first = compare_daily_bar_batches(
            _make_batch(left_bars, provider_key=TUSHARE_PROVIDER_KEY),
            _make_batch(right_bars, provider_key=TDX_OFFLINE_PROVIDER_KEY),
        )
        second = compare_daily_bar_batches(
            _make_batch(left_bars, provider_key=TUSHARE_PROVIDER_KEY),
            _make_batch(right_bars, provider_key=TDX_OFFLINE_PROVIDER_KEY),
        )

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
