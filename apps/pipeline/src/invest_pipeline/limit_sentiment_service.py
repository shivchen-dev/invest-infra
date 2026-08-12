from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from invest_domain.analytics.limit_sentiment import (
    LimitSentimentInput,
    build_limit_sentiment,
)
from invest_domain.analytics.market_observations import MarketObservationSnapshot
from invest_domain.input_snapshot import InputSnapshot
from invest_storage.unit_of_work import UnitOfWork

UnitOfWorkFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class LimitSentimentPublishResult:
    snapshot: MarketObservationSnapshot
    input_snapshot: InputSnapshot
    instrument_count: int


def calculate_and_publish_limit_sentiment(
    *,
    uow_factory: UnitOfWorkFactory,
    input_snapshot: InputSnapshot,
    inputs: Sequence[LimitSentimentInput],
    as_of: date,
) -> LimitSentimentPublishResult:
    if input_snapshot.snapshot_date != as_of:
        raise ValueError(
            f"as_of {as_of.isoformat()} does not match input_snapshot."
            f"snapshot_date {input_snapshot.snapshot_date.isoformat()}"
        )

    input_ids = [item.instrument_id for item in inputs]
    if len(input_ids) != len(set(input_ids)):
        raise ValueError("limit sentiment inputs must not contain duplicate instrument ids")
    expected_ids = set(input_snapshot.instrument_ids)
    actual_ids = set(input_ids)
    if actual_ids != expected_ids:
        raise ValueError(
            "limit sentiment input instrument ids do not match input snapshot universe"
        )

    snapshot = build_limit_sentiment(
        input_snapshot_id=input_snapshot.id,
        instruments=inputs,
        as_of_date=as_of,
    )
    with uow_factory() as uow:
        persisted = uow.market_observation_snapshots.add(snapshot)
        uow.commit()
    return LimitSentimentPublishResult(
        snapshot=persisted,
        input_snapshot=input_snapshot,
        instrument_count=len(inputs),
    )


__all__ = [
    "LimitSentimentPublishResult",
    "calculate_and_publish_limit_sentiment",
]
