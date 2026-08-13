"""Integration tests for :mod:`invest_pipeline.limit_sentiment_service`.

Verifies the Stage 4C Limit Sentiment slice against a real Testcontainers
PostgreSQL:

* Idempotent re-publish: two consecutive
  :func:`calculate_and_publish_limit_sentiment` calls with identical
  inputs return the same ``snapshot_id`` / ``content_hash`` and only
  ever persist one parent snapshot row.
* Three observation ratios round-trip through
  ``market_observation_snapshots.get_by_content_hash`` as Decimal
  values (``limit_up_ratio`` = 0.5, ``limit_down_ratio`` = 0.0,
  ``limit_touch_unknown_ratio`` = 0.0).
* PARTIAL / FRESH downgrade when a normal row is missing both limit
  prices; ``limit_touch_unknown_ratio`` is persisted as ``None``.

Tests run against the disposable Testcontainers PostgreSQL; each test
is isolated via the truncation fixture in the parent conftest.py.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from invest_domain.analytics.limit_sentiment import (
    LIMIT_DOWN_RATIO,
    LIMIT_TOUCH_UNKNOWN_RATIO,
    LIMIT_UP_RATIO,
    LimitSentimentInput,
)
from invest_domain.input_snapshot import InputSnapshot
from invest_domain.research.models import FreshnessStatus, QualityStatus
from invest_pipeline.limit_sentiment_service import (
    calculate_and_publish_limit_sentiment,
)
from sqlalchemy import text

AS_OF = date(2026, 8, 12)
INSTRUMENT_A = UUID("00000000-0000-4000-8000-000000000001")
INSTRUMENT_B = UUID("00000000-0000-4000-8000-000000000002")
INSTRUMENT_C = UUID("00000000-0000-4000-8000-000000000003")


def _persist_input_snapshot(uow_factory, instrument_ids):
    snapshot = InputSnapshot.create(AS_OF, instrument_ids)
    with uow_factory() as uow:
        stored = uow.input_snapshot_repository.add(snapshot)
        uow.commit()
    return stored


def _observation(snapshot, key):
    return next(item for item in snapshot.observations if item.observation_key == key)


def test_complete_round_trip_persists_unique_snapshot(uow_factory, session_factory_fixture) -> None:
    snapshot = _persist_input_snapshot(uow_factory, instrument_ids=(INSTRUMENT_A, INSTRUMENT_B))
    limit_up_input = LimitSentimentInput(
        instrument_id=INSTRUMENT_A,
        close=Decimal("11"),
        observed_date=AS_OF,
        limit_up_price=Decimal("11"),
        limit_down_price=Decimal("10"),
    )
    normal_input = LimitSentimentInput(
        instrument_id=INSTRUMENT_B,
        close=Decimal("9"),
        observed_date=AS_OF,
        limit_up_price=Decimal("11"),
        limit_down_price=Decimal("10"),
    )

    first = calculate_and_publish_limit_sentiment(
        uow_factory=uow_factory,
        input_snapshot=snapshot,
        inputs=(limit_up_input, normal_input),
        as_of=AS_OF,
    )
    second = calculate_and_publish_limit_sentiment(
        uow_factory=uow_factory,
        input_snapshot=snapshot,
        inputs=(limit_up_input, normal_input),
        as_of=AS_OF,
    )

    assert second.snapshot.snapshot_id == first.snapshot.snapshot_id
    assert second.snapshot.content_hash == first.snapshot.content_hash
    assert first.snapshot.quality_status is QualityStatus.COMPLETE
    assert first.snapshot.freshness_status is FreshnessStatus.FRESH

    with uow_factory() as uow:
        reloaded = uow.market_observation_snapshots.get_by_content_hash(first.snapshot.content_hash)
    assert reloaded is not None
    values = {item.observation_key: item.value for item in reloaded.observations}
    assert values[LIMIT_UP_RATIO] == Decimal("0.5")
    assert values[LIMIT_DOWN_RATIO] == Decimal("0")
    assert values[LIMIT_TOUCH_UNKNOWN_RATIO] == Decimal("0")
    for value in values.values():
        assert isinstance(value, Decimal)

    with session_factory_fixture() as verify_session:
        parent_count = verify_session.execute(
            text(
                "SELECT COUNT(*) FROM analytics.market_observation_snapshots "
                "WHERE content_hash = :ch"
            ),
            {"ch": first.snapshot.content_hash},
        ).scalar_one()
    assert parent_count == 1


def test_partial_status_when_normal_row_missing_limits(uow_factory) -> None:
    snapshot = _persist_input_snapshot(uow_factory, instrument_ids=(INSTRUMENT_C,))
    missing_limits = LimitSentimentInput(
        instrument_id=INSTRUMENT_C,
        close=Decimal("9"),
        observed_date=AS_OF,
    )

    result = calculate_and_publish_limit_sentiment(
        uow_factory=uow_factory,
        input_snapshot=snapshot,
        inputs=(missing_limits,),
        as_of=AS_OF,
    )

    assert result.snapshot.quality_status is QualityStatus.PARTIAL
    assert result.snapshot.freshness_status is FreshnessStatus.FRESH
    with uow_factory() as uow:
        reloaded = uow.market_observation_snapshots.get_by_content_hash(
            result.snapshot.content_hash
        )
    assert reloaded is not None
    assert _observation(reloaded, LIMIT_TOUCH_UNKNOWN_RATIO).value is None


if __name__ == "__main__":
    import unittest

    unittest.main()
