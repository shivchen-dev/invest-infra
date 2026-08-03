from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from invest_domain.instruments import InstrumentId

SCHEMA_VERSION = "1.0.0"
FACTOR_SET_KEY = "etf_market_state_daily"
FACTOR_SET_VERSION = "1.0.0"


class FreshnessStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    PARTIAL = "partial"
    FAILED = "failed"


class QualityStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    INVALID = "invalid"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class FactorSetMetadata:
    key: str = FACTOR_SET_KEY
    version: str = FACTOR_SET_VERSION

    def __post_init__(self) -> None:
        if self.key != FACTOR_SET_KEY or self.version != FACTOR_SET_VERSION:
            raise ValueError(f"factor set must be {FACTOR_SET_KEY}/{FACTOR_SET_VERSION}")


@dataclass(frozen=True, slots=True)
class CaseContext:
    instrument_id: InstrumentId
    as_of_date: date
    question: str
    horizon: str = "20-60d"
    case_id: str | UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise TypeError("CaseContext.instrument_id must be an InstrumentId")
        if not self.question.strip():
            raise ValueError("CaseContext.question must not be empty")
        if not self.horizon.strip():
            raise ValueError("CaseContext.horizon must not be empty")


@dataclass(frozen=True, slots=True)
class InstrumentSnapshot:
    instrument_id: InstrumentId
    symbol: str
    name: str
    exchange: str
    currency: str = "CNY"

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise TypeError("InstrumentSnapshot.instrument_id must be an InstrumentId")
        if any(not value.strip() for value in (self.symbol, self.name, self.exchange, self.currency)):
            raise ValueError("instrument snapshot strings must not be empty")


@dataclass(frozen=True, slots=True)
class CandidateContext:
    included: bool | None = None
    rank: int | None = None
    total_score: Decimal | None = None
    exclusion_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.rank is not None and self.rank < 1:
            raise ValueError("CandidateContext.rank must be >= 1")
        _require_finite(self.total_score, "CandidateContext.total_score")
        object.__setattr__(self, "exclusion_codes", tuple(sorted(set(self.exclusion_codes))))


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    latest_trade_date: date | None
    latest_close: Decimal | None
    currency: str
    observed_trading_days: int
    valid_price_days: int
    suspended_days: int = 0

    def __post_init__(self) -> None:
        _require_finite(self.latest_close, "MarketSnapshot.latest_close")
        if self.latest_close is not None and self.latest_close <= 0:
            raise ValueError("MarketSnapshot.latest_close must be > 0")
        if min(self.observed_trading_days, self.valid_price_days, self.suspended_days) < 0:
            raise ValueError("market snapshot day counts must be >= 0")
        if self.valid_price_days + self.suspended_days > self.observed_trading_days:
            raise ValueError("market snapshot day counts are inconsistent")
        if not self.currency.strip():
            raise ValueError("MarketSnapshot.currency must not be empty")


@dataclass(frozen=True, slots=True)
class FactorObservation:
    factor_key: str
    instrument_id: InstrumentId
    value: Decimal | None
    unit: str
    window: int
    observed_date: date
    quality_status: QualityStatus
    source_kind: str = "daily_bar"
    source_ref: str = "standardized_daily_bars"
    item_hash: str = ""
    evidence_id: str | None = None

    @property
    def evidence_key(self) -> str:
        return f"factor.{self.factor_key}"

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise TypeError("FactorObservation.instrument_id must be an InstrumentId")
        if not self.factor_key.strip() or not self.unit.strip():
            raise ValueError("factor key and unit must not be empty")
        if self.window <= 0:
            raise ValueError("FactorObservation.window must be > 0")
        _require_finite(self.value, f"FactorObservation[{self.factor_key}].value")
        from invest_domain.research.canonical import compute_item_hash

        computed = compute_item_hash(self)
        if self.item_hash and self.item_hash != computed:
            raise ValueError("FactorObservation.item_hash does not match its business content")
        object.__setattr__(self, "item_hash", computed)


@dataclass(frozen=True, slots=True)
class DataQuality:
    freshness_status: FreshnessStatus
    quality_status: QualityStatus
    target_trading_days: int
    observed_trading_days: int
    valid_price_days: int
    invalid_days: int = 0
    suspended_days: int = 0
    conflict_detected: bool = False

    def __post_init__(self) -> None:
        counts = (
            self.target_trading_days,
            self.observed_trading_days,
            self.valid_price_days,
            self.invalid_days,
            self.suspended_days,
        )
        if self.target_trading_days <= 0 or min(counts) < 0:
            raise ValueError("data-quality day counts are invalid")


@dataclass(frozen=True, slots=True)
class SourceReference:
    source_kind: str
    source_ref: str
    observed_date: date
    quality_status: QualityStatus = QualityStatus.COMPLETE
    revision: int | None = None

    def __post_init__(self) -> None:
        if not self.source_kind.strip() or not self.source_ref.strip():
            raise ValueError("source reference strings must not be empty")
        if self.revision is not None and self.revision < 1:
            raise ValueError("SourceReference.revision must be >= 1")


@dataclass(frozen=True, slots=True)
class EvidencePack:
    case: CaseContext
    instrument: InstrumentSnapshot
    market_snapshot: MarketSnapshot
    factors: tuple[FactorObservation, ...]
    data_quality: DataQuality
    candidate_context: CandidateContext | None = None
    missing_fields: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    source_refs: tuple[SourceReference, ...] = ()
    schema_version: str = SCHEMA_VERSION
    factor_set: FactorSetMetadata = field(default_factory=FactorSetMetadata)
    pack_hash: str = ""
    pack_id: UUID | None = None
    pipeline_run_id: UUID | None = None
    e2a_request_id: str | None = None
    e2a_session_id: str | None = None
    generated_at: datetime | None = None
    workspace_path: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
        if self.case.instrument_id != self.instrument.instrument_id:
            raise ValueError("case and instrument must identify the same instrument")
        factors = tuple(sorted(self.factors, key=lambda item: item.factor_key))
        from invest_domain.research.factor_set import FACTOR_KEYS

        if tuple(item.factor_key for item in factors) != tuple(sorted(FACTOR_KEYS)):
            raise ValueError("EvidencePack.factors must contain the complete v1.0.0 factor set")
        if len({item.factor_key for item in factors}) != len(factors):
            raise ValueError("factor keys must be unique")
        if any(item.instrument_id != self.instrument.instrument_id for item in factors):
            raise ValueError("all factors must identify the pack instrument")
        object.__setattr__(self, "factors", factors)
        object.__setattr__(self, "missing_fields", tuple(sorted(set(self.missing_fields))))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))
        object.__setattr__(
            self,
            "source_refs",
            tuple(
                sorted(
                    set(self.source_refs),
                    key=lambda item: (
                        item.source_kind,
                        item.source_ref,
                        item.observed_date,
                        item.revision or 0,
                        item.quality_status.value,
                    ),
                )
            ),
        )
        from invest_domain.research.canonical import compute_pack_hash, make_evidence_id

        computed = compute_pack_hash(self)
        if self.pack_hash and self.pack_hash != computed:
            raise ValueError("EvidencePack.pack_hash does not match its canonical content")
        object.__setattr__(self, "pack_hash", computed)
        identified = tuple(
            replace(item, evidence_id=make_evidence_id(computed, item)) for item in factors
        )
        for supplied, generated in zip(factors, identified, strict=True):
            if supplied.evidence_id is not None and supplied.evidence_id != generated.evidence_id:
                raise ValueError("FactorObservation.evidence_id is not derived from pack_hash")
        object.__setattr__(self, "factors", identified)


def _require_finite(value: Decimal | None, field_name: str) -> None:
    if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
        raise ValueError(f"{field_name} must be a finite Decimal or None")
