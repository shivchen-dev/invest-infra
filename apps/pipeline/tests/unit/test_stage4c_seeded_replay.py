from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from invest_domain.analytics.limit_sentiment import (
    LimitSentimentInput,
    build_limit_sentiment,
)
from invest_domain.input_snapshot import InputSnapshot
from invest_domain.instruments.models import InstrumentId
from invest_domain.market_data.models import BarSource, DailyBar
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_domain.research.models import FreshnessStatus, QualityStatus

TRADE_DATE = date(2026, 8, 12)
INSTRUMENT_IDS = (
    UUID("00000000-0000-4000-8000-000000000001"),
    UUID("00000000-0000-4000-8000-000000000002"),
)
SNAPSHOT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
SOURCE_BATCH_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _build_daily_bar(*, close: Decimal = Decimal("10.80")) -> DailyBar:
    return DailyBar.build(
        instrument_id=InstrumentId(INSTRUMENT_IDS[0]),
        trade_date=TRADE_DATE,
        open=Decimal("10.20"),
        high=Decimal("11.00"),
        low=Decimal("10.00"),
        close=close,
        prev_close=Decimal("10.10"),
        volume=Decimal("123456"),
        amount=Decimal("1333333.33"),
        adjustment=Adjust.NONE,
        trading_status=TradingStatus.NORMAL,
        source=BarSource(
            provider_key="seeded_replay",
            source_batch_id=SOURCE_BATCH_ID,
            observed_at=datetime(2026, 8, 12, 8, 0, tzinfo=UTC),
        ),
        revision=1,
    )


def _build_input_snapshot() -> InputSnapshot:
    return InputSnapshot.create(
        TRADE_DATE,
        INSTRUMENT_IDS[::-1],
        id_factory=lambda: SNAPSHOT_ID,
        now_factory=lambda: datetime(2026, 8, 12, 8, 30, tzinfo=UTC),
    )


def _build_limit_inputs() -> tuple[LimitSentimentInput, ...]:
    return (
        LimitSentimentInput(
            instrument_id=INSTRUMENT_IDS[0],
            close=Decimal("11.00"),
            observed_date=TRADE_DATE,
            limit_up_price=Decimal("11.00"),
            limit_down_price=Decimal("10.00"),
        ),
        LimitSentimentInput(
            instrument_id=INSTRUMENT_IDS[1],
            close=Decimal("9.00"),
            observed_date=TRADE_DATE,
            limit_up_price=Decimal("11.00"),
            limit_down_price=Decimal("9.00"),
        ),
    )


def test_stage4c_checkpoint_b_seeded_replay_daily_bar_hash_is_stable() -> None:
    first = _build_daily_bar()
    second = _build_daily_bar()
    changed = _build_daily_bar(close=Decimal("10.81"))

    assert first.row_hash == second.row_hash
    assert changed.row_hash != first.row_hash


def test_stage4c_checkpoint_b_seeded_replay_limit_sentiment_is_deterministic() -> None:
    first_input_snapshot = _build_input_snapshot()
    second_input_snapshot = _build_input_snapshot()
    inputs = _build_limit_inputs()
    first = build_limit_sentiment(
        input_snapshot_id=first_input_snapshot.id,
        instruments=inputs,
        as_of_date=TRADE_DATE,
    )
    second = build_limit_sentiment(
        input_snapshot_id=second_input_snapshot.id,
        instruments=tuple(reversed(inputs)),
        as_of_date=TRADE_DATE,
    )

    assert first_input_snapshot.id == second_input_snapshot.id == SNAPSHOT_ID
    assert first_input_snapshot.content_hash == second_input_snapshot.content_hash
    assert first.snapshot_id == second.snapshot_id
    assert first.content_hash == second.content_hash
    assert first.observations == second.observations
    assert [item.item_hash for item in first.observations] == [
        item.item_hash for item in second.observations
    ]
    assert first.quality_status is second.quality_status is QualityStatus.COMPLETE
    assert first.freshness_status is second.freshness_status is FreshnessStatus.FRESH
