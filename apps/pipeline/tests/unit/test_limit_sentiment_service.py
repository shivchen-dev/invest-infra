from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from invest_domain.analytics.limit_sentiment import LimitSentimentInput
from invest_domain.input_snapshot import InputSnapshot
from invest_domain.research.models import FreshnessStatus, QualityStatus
from invest_pipeline.limit_sentiment_service import (
    calculate_and_publish_limit_sentiment,
)

AS_OF = date(2026, 8, 12)
IDS = (
    UUID("00000000-0000-4000-8000-000000000001"),
    UUID("00000000-0000-4000-8000-000000000002"),
)


class _ObservationRepo:
    def __init__(self) -> None:
        self.added = []

    def add(self, snapshot):
        self.added.append(snapshot)
        return snapshot


class _Uow:
    def __init__(self) -> None:
        self.market_observation_snapshots = _ObservationRepo()
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


def _snapshot(*, snapshot_date: date = AS_OF) -> InputSnapshot:
    return InputSnapshot.create(
        snapshot_date,
        IDS,
        id_factory=lambda: UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        now_factory=lambda: datetime(2026, 8, 12, tzinfo=UTC),
    )


def _input(instrument_id: UUID, *, missing_limits: bool = False) -> LimitSentimentInput:
    return LimitSentimentInput(
        instrument_id=instrument_id,
        close=Decimal("11"),
        observed_date=AS_OF,
        limit_up_price=None if missing_limits else Decimal("11"),
        limit_down_price=None if missing_limits else Decimal("10"),
    )


def _run(inputs, *, snapshot=None):
    uow = _Uow()
    result = calculate_and_publish_limit_sentiment(
        uow_factory=lambda: uow,
        input_snapshot=snapshot or _snapshot(),
        inputs=inputs,
        as_of=AS_OF,
    )
    return result, uow


def test_persists_snapshot_commits_and_returns_result() -> None:
    result, uow = _run(tuple(_input(item_id) for item_id in IDS))

    assert result.instrument_count == 2
    assert result.snapshot is uow.market_observation_snapshots.added[0]
    assert uow.committed is True
    assert result.snapshot.quality_status is QualityStatus.COMPLETE


def test_rejects_snapshot_date_mismatch_before_opening_uow() -> None:
    with pytest.raises(ValueError, match="does not match"):
        _run(
            tuple(_input(item_id) for item_id in IDS),
            snapshot=_snapshot(snapshot_date=date(2026, 8, 11)),
        )


def test_rejects_duplicate_input_ids() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _run((_input(IDS[0]), _input(IDS[0])))


def test_rejects_universe_mismatch() -> None:
    with pytest.raises(ValueError, match="do not match"):
        _run((_input(IDS[0]), _input(UUID("00000000-0000-4000-8000-000000000003"))))


def test_persists_partial_domain_snapshot_without_upgrading_quality() -> None:
    result, uow = _run((_input(IDS[0]), _input(IDS[1], missing_limits=True)))

    assert len(uow.market_observation_snapshots.added) == 1
    assert result.snapshot.quality_status is QualityStatus.PARTIAL
    assert result.snapshot.freshness_status is FreshnessStatus.FRESH
