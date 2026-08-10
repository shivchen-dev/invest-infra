from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from invest_domain.research.models import FreshnessStatus, QualityStatus
from invest_domain.shared.canonical import canonical_sha256


@dataclass(frozen=True, slots=True)
class MarketObservation:
    observation_key: str
    value: Decimal | str | None
    unit: str
    observed_date: date
    source_kind: str
    source_ref: str
    quality_status: QualityStatus = QualityStatus.COMPLETE
    item_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.quality_status, QualityStatus):
            raise TypeError("quality_status must be a QualityStatus")
        if not self.observation_key.strip() or not self.unit.strip():
            raise ValueError("observation key and unit must not be empty")
        if not self.source_kind.strip() or not self.source_ref.strip():
            raise ValueError("observation source must not be empty")
        if isinstance(self.value, Decimal) and not self.value.is_finite():
            raise ValueError("observation value must be finite")
        computed = canonical_sha256(self.content_projection)
        if self.item_hash and self.item_hash != computed:
            raise ValueError("observation item_hash does not match content")
        object.__setattr__(self, "item_hash", computed)

    @property
    def content_projection(self) -> dict[str, Any]:
        return {
            "observation_key": self.observation_key,
            "value": self.value,
            "unit": self.unit,
            "observed_date": self.observed_date,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "quality_status": self.quality_status.value,
        }


@dataclass(frozen=True, slots=True)
class MarketObservationSnapshot:
    input_snapshot_id: UUID | str
    as_of_date: date
    observations: tuple[MarketObservation, ...]
    algorithm_version: str = "1.0.0"
    scope_type: str = "etf_universe"
    scope_key: str = "etf_active_universe_v1"
    quality_status: QualityStatus = QualityStatus.COMPLETE
    freshness_status: FreshnessStatus = FreshnessStatus.FRESH
    content_hash: str = ""
    snapshot_id: str = ""

    def __post_init__(self) -> None:
        if not str(self.input_snapshot_id).strip():
            raise ValueError("input_snapshot_id must not be empty")
        if not isinstance(self.quality_status, QualityStatus):
            raise TypeError("quality_status must be a QualityStatus")
        if not isinstance(self.freshness_status, FreshnessStatus):
            raise TypeError("freshness_status must be a FreshnessStatus")
        if (
            not self.algorithm_version.strip()
            or not self.scope_type.strip()
            or not self.scope_key.strip()
        ):
            raise ValueError("snapshot metadata must not be empty")
        ordered = tuple(sorted(self.observations, key=lambda item: item.observation_key))
        if len({item.observation_key for item in ordered}) != len(ordered):
            raise ValueError("observation keys must be unique")
        object.__setattr__(self, "observations", ordered)
        projection = self.content_projection
        computed = canonical_sha256(projection)
        if self.content_hash and self.content_hash != computed:
            raise ValueError("snapshot content_hash does not match content")
        object.__setattr__(self, "content_hash", computed)
        computed_id = f"mos:{computed[:32]}"
        if self.snapshot_id and self.snapshot_id != computed_id:
            raise ValueError("snapshot_id does not derive from content_hash")
        object.__setattr__(self, "snapshot_id", computed_id)

    @property
    def content_projection(self) -> dict[str, Any]:
        return {
            "scope_type": self.scope_type,
            "scope_key": self.scope_key,
            "as_of_date": self.as_of_date,
            "input_snapshot_id": str(self.input_snapshot_id),
            "algorithm_version": self.algorithm_version,
            "quality_status": self.quality_status.value,
            "freshness_status": self.freshness_status.value,
            "observations": [item.content_projection for item in self.observations],
        }
