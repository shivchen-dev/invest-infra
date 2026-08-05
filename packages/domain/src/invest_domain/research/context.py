"""Immutable research context snapshots independent of ``EvidencePack``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from invest_domain.instruments import InstrumentId
from invest_domain.research.models import QualityStatus
from invest_domain.shared.canonical import canonical_json, canonical_sha256

CONTEXT_SCHEMA_VERSION = "0.1.0"


class ContextValueType(StrEnum):
    TEXT = "text"
    DECIMAL = "decimal"
    DATE = "date"
    JSON = "json"


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _value(value: Any, value_type: ContextValueType) -> Any:
    if value is None:
        return None
    if value_type is ContextValueType.TEXT:
        if not isinstance(value, str) or not value.strip():
            raise TypeError("text context values must be non-empty strings")
        return value.strip()
    if value_type is ContextValueType.DECIMAL:
        if not isinstance(value, Decimal) or not value.is_finite():
            raise TypeError("decimal context values must be finite Decimal instances")
        return value
    if value_type is ContextValueType.DATE:
        if isinstance(value, datetime) or not isinstance(value, date):
            raise TypeError("date context values must be date instances")
        return value
    if value_type is ContextValueType.JSON:
        canonical_json(value)
        return value
    raise ValueError(f"unsupported context value type: {value_type!r}")


@dataclass(frozen=True, slots=True)
class ContextItem:
    context_type: str
    key: str
    value: Any
    value_type: ContextValueType
    source_provider: str
    source_dataset: str
    observed_at: datetime
    source_batch_id: UUID | None = None
    source_revision: int = 1
    quality_status: QualityStatus = QualityStatus.COMPLETE
    confidence_score: Decimal = Decimal("1")
    evidence_refs: tuple[str, ...] = ()
    item_hash: str = ""

    def __post_init__(self) -> None:
        for name in ("context_type", "key", "source_provider", "source_dataset"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        if not isinstance(self.value_type, ContextValueType):
            raise TypeError("value_type must be ContextValueType")
        if not isinstance(self.quality_status, QualityStatus):
            raise TypeError("quality_status must be QualityStatus")
        object.__setattr__(self, "value", _value(self.value, self.value_type))
        _aware(self.observed_at, "observed_at")
        if self.source_batch_id is not None and not isinstance(self.source_batch_id, UUID):
            raise TypeError("source_batch_id must be UUID or None")
        if (
            not isinstance(self.source_revision, int)
            or isinstance(self.source_revision, bool)
            or self.source_revision < 1
        ):
            raise ValueError("source_revision must be >= 1")
        if not isinstance(self.confidence_score, Decimal) or not self.confidence_score.is_finite():
            raise TypeError("confidence_score must be a finite Decimal")
        if not Decimal("0") <= self.confidence_score <= Decimal("1"):
            raise ValueError("confidence_score must be between 0 and 1")
        refs = tuple(sorted(set(self.evidence_refs)))
        if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            raise ValueError("evidence_refs must contain non-empty strings")
        object.__setattr__(self, "evidence_refs", refs)
        computed = compute_context_item_hash(self)
        if self.item_hash and self.item_hash != computed:
            raise ValueError("item_hash does not match context item content")
        object.__setattr__(self, "item_hash", computed)


def context_item_projection(item: ContextItem) -> dict[str, Any]:
    return {
        "context_type": item.context_type,
        "key": item.key,
        "value": item.value,
        "value_type": item.value_type.value,
        "source_provider": item.source_provider,
        "source_dataset": item.source_dataset,
        "source_batch_id": item.source_batch_id,
        "source_revision": item.source_revision,
        "observed_at": item.observed_at,
        "quality_status": item.quality_status.value,
        "confidence_score": item.confidence_score,
        "evidence_refs": list(item.evidence_refs),
    }


def compute_context_item_hash(item: ContextItem) -> str:
    return canonical_sha256(context_item_projection(item))


@dataclass(frozen=True, slots=True)
class ResearchContextPack:
    instrument_id: InstrumentId
    items: tuple[ContextItem, ...] = ()
    schema_version: str = CONTEXT_SCHEMA_VERSION
    context_version: int = 1
    content_hash: str = ""
    created_at: datetime | None = None
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise TypeError("instrument_id must be InstrumentId")
        if self.schema_version != CONTEXT_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {CONTEXT_SCHEMA_VERSION}")
        if (
            not isinstance(self.context_version, int)
            or isinstance(self.context_version, bool)
            or self.context_version < 1
        ):
            raise ValueError("context_version must be >= 1")
        if self.created_at is not None:
            _aware(self.created_at, "created_at")
        if self.missing_reason is not None and not self.missing_reason.strip():
            raise ValueError("missing_reason must not be blank")
        if any(not isinstance(item, ContextItem) for item in self.items):
            raise TypeError("items must contain ContextItem instances")
        items = tuple(
            sorted(self.items, key=lambda item: (item.context_type, item.key, item.item_hash))
        )
        if len({item.item_hash for item in items}) != len(items):
            raise ValueError("context item hashes must be unique")
        object.__setattr__(self, "items", items)
        computed = compute_context_pack_hash(self)
        if self.content_hash and self.content_hash != computed:
            raise ValueError("content_hash does not match context pack content")
        object.__setattr__(self, "content_hash", computed)


def context_pack_projection(pack: ResearchContextPack) -> dict[str, Any]:
    return {
        "instrument_id": str(pack.instrument_id),
        "schema_version": pack.schema_version,
        "context_version": pack.context_version,
        "items": [context_item_projection(item) for item in pack.items],
        "missing_reason": pack.missing_reason,
    }


def compute_context_pack_hash(pack: ResearchContextPack) -> str:
    return canonical_sha256(context_pack_projection(pack))


def canonical_context_pack_json(pack: ResearchContextPack) -> str:
    return canonical_json(context_pack_projection(pack))


__all__ = [
    "CONTEXT_SCHEMA_VERSION",
    "ContextItem",
    "ContextValueType",
    "ResearchContextPack",
    "canonical_context_pack_json",
    "compute_context_item_hash",
    "compute_context_pack_hash",
    "context_item_projection",
    "context_pack_projection",
]
