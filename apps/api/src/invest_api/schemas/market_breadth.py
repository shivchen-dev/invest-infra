from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from invest_domain.analytics.market_observations import MarketObservationSnapshot
from pydantic import BaseModel


class MarketBreadthObservationResponse(BaseModel):
    observation_key: str
    value: Decimal | str | None
    unit: str
    observed_date: date
    source_kind: str
    source_ref: str
    quality_status: str
    item_hash: str


class MarketBreadthResponse(BaseModel):
    snapshot_id: str
    as_of_date: date
    input_snapshot_id: UUID | str
    algorithm_version: str
    scope_type: str
    scope_key: str
    quality_status: str
    freshness_status: str
    content_hash: str
    observations: list[MarketBreadthObservationResponse]

    @classmethod
    def from_domain(cls, snapshot: MarketObservationSnapshot) -> MarketBreadthResponse:
        return cls(
            snapshot_id=snapshot.snapshot_id,
            as_of_date=snapshot.as_of_date,
            input_snapshot_id=snapshot.input_snapshot_id,
            algorithm_version=snapshot.algorithm_version,
            scope_type=snapshot.scope_type,
            scope_key=snapshot.scope_key,
            quality_status=snapshot.quality_status.value,
            freshness_status=snapshot.freshness_status.value,
            content_hash=snapshot.content_hash,
            observations=[
                MarketBreadthObservationResponse(
                    observation_key=item.observation_key,
                    value=item.value,
                    unit=item.unit,
                    observed_date=item.observed_date,
                    source_kind=item.source_kind,
                    source_ref=item.source_ref,
                    quality_status=item.quality_status.value,
                    item_hash=item.item_hash,
                )
                for item in snapshot.observations
            ],
        )


__all__ = ["MarketBreadthObservationResponse", "MarketBreadthResponse"]