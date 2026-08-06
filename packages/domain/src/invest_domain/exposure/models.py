"""Pure, immutable contracts for index and ETF exposure evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Callable, Iterable
from uuid import UUID, uuid4

from invest_domain.shared.canonical import content_hash


def _text(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a str")
    value = value.strip()
    if not value:
        raise ValueError(f"{field} must not be empty")
    return value


def _date(value: date, field: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{field} must be a date")
    return value


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError(f"{field} must be a UUID")
    if value.int == 0:
        raise ValueError(f"{field} must not be the all-zero UUID")
    return value


def _confidence(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("confidence must be a Decimal")
    if not value.is_finite():
        raise ValueError("confidence must be finite")
    if not Decimal("0") <= value <= Decimal("1"):
        raise ValueError("confidence must be in [0, 1]")
    return value


@dataclass(frozen=True, slots=True)
class ExposureProvenance:
    provider_key: str
    dataset_key: str
    observed_at: datetime
    source_batch_id: UUID | None = None
    revision: int = 1
    confidence: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_key", _text(self.provider_key, "provider_key"))
        object.__setattr__(self, "dataset_key", _text(self.dataset_key, "dataset_key"))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if self.source_batch_id is not None and not isinstance(self.source_batch_id, UUID):
            raise TypeError("source_batch_id must be a UUID or None")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool):
            raise TypeError("revision must be an integer")
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        object.__setattr__(self, "confidence", _confidence(self.confidence))


@dataclass(frozen=True, slots=True)
class IndexProfile:
    index_code: str
    index_name: str
    provenance: ExposureProvenance
    category: str | None = None
    as_of_date: date | None = None
    content_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "index_code", _text(self.index_code, "index_code"))
        object.__setattr__(self, "index_name", _text(self.index_name, "index_name"))
        if not isinstance(self.provenance, ExposureProvenance):
            raise ValueError("provenance must be an ExposureProvenance")
        if self.category is not None:
            object.__setattr__(self, "category", _text(self.category, "category"))
        if self.as_of_date is not None:
            object.__setattr__(self, "as_of_date", _date(self.as_of_date, "as_of_date"))
        object.__setattr__(self, "content_hash", _validated_hash(self.content_hash, _hash({"type": "index_profile", "index_code": self.index_code, "index_name": self.index_name, "category": self.category, "as_of_date": self.as_of_date, "provenance": _prov_payload(self.provenance)})))


@dataclass(frozen=True, slots=True)
class IndexConstituent:
    stock_code: str
    weight: Decimal
    industry: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", _text(self.stock_code, "stock_code"))
        object.__setattr__(self, "weight", _weight(self.weight))
        if self.industry is not None:
            object.__setattr__(self, "industry", _text(self.industry, "industry"))


@dataclass(frozen=True, slots=True)
class EtfHolding:
    stock_code: str
    weight: Decimal
    industry: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", _text(self.stock_code, "stock_code"))
        object.__setattr__(self, "weight", _weight(self.weight))
        if self.industry is not None:
            object.__setattr__(self, "industry", _text(self.industry, "industry"))


def _weight(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("weight must be a Decimal")
    if not value.is_finite():
        raise ValueError("weight must be finite")
    if not Decimal("0") <= value <= Decimal("1"):
        raise ValueError("weight must be in [0, 1]")
    return value


def _security_code_key(item: IndexConstituent | EtfHolding) -> tuple[bool, str]:
    """Sort Shanghai six-digit codes before other exchange prefixes."""
    return (not item.stock_code.startswith("6"), item.stock_code)


def _hash(payload: object) -> str:
    return content_hash(payload)


def _prov_payload(value: ExposureProvenance) -> dict[str, object]:
    return {"provider_key": value.provider_key, "dataset_key": value.dataset_key, "observed_at": value.observed_at, "source_batch_id": value.source_batch_id, "revision": value.revision, "confidence": value.confidence}


def _validated_hash(value: str, computed: str) -> str:
    if value:
        if not isinstance(value, str):
            raise TypeError("content_hash must be a str")
        if len(value) != 64:
            raise ValueError("content_hash must be 64 characters")
        if value != computed:
            raise ValueError("content_hash does not match business content")
    return computed


def _snapshot_hash(kind: str, identity: object, as_of_date: date, observed_at: datetime, entries: object, provenance: ExposureProvenance) -> str:
    return _hash({"type": kind, "identity": identity, "as_of_date": as_of_date, "observed_at": observed_at, "entries": entries, "provenance": _prov_payload(provenance)})


@dataclass(frozen=True, slots=True)
class IndexConstituentSnapshot:
    id: UUID
    index_code: str
    as_of_date: date
    observed_at: datetime
    constituents: tuple[IndexConstituent, ...]
    provenance: ExposureProvenance
    content_hash: str = ""
    created_at: datetime | None = None

    @classmethod
    def create(cls, *, index_code: str, as_of_date: date, observed_at: datetime, constituents: Iterable[IndexConstituent], provenance: ExposureProvenance, id_factory: Callable[[], UUID] = uuid4, now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)) -> "IndexConstituentSnapshot":
        values = tuple(constituents)
        if not values:
            raise ValueError("constituents must contain at least one item")
        if any(not isinstance(item, IndexConstituent) for item in values):
            raise TypeError("constituents must contain IndexConstituent instances")
        values = tuple(sorted(values, key=_security_code_key))
        if len({item.stock_code for item in values}) != len(values):
            raise ValueError("constituents contain duplicates")
        return cls(id_factory(), index_code, as_of_date, observed_at, values, provenance, created_at=now_factory())

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _uuid(self.id, "id")); object.__setattr__(self, "index_code", _text(self.index_code, "index_code")); object.__setattr__(self, "as_of_date", _date(self.as_of_date, "as_of_date")); object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if not isinstance(self.constituents, tuple): raise ValueError("constituents must be a tuple")
        if not self.constituents: raise ValueError("constituents must not be empty")
        if any(not isinstance(item, IndexConstituent) for item in self.constituents): raise TypeError("constituents must contain IndexConstituent instances")
        sorted_constituents = tuple(sorted(self.constituents, key=_security_code_key))
        if len({item.stock_code for item in sorted_constituents}) != len(sorted_constituents): raise ValueError("constituents contain duplicates")
        object.__setattr__(self, "constituents", sorted_constituents)
        if not isinstance(self.provenance, ExposureProvenance): raise TypeError("provenance must be an ExposureProvenance")
        created = self.created_at if self.created_at is not None else datetime.now(UTC)
        object.__setattr__(self, "created_at", _aware(created, "created_at"))
        computed = _snapshot_hash("index_constituents", self.index_code, self.as_of_date, self.observed_at, [(x.stock_code, x.weight, x.industry) for x in sorted_constituents], self.provenance)
        object.__setattr__(self, "content_hash", _validated_hash(self.content_hash, computed))


@dataclass(frozen=True, slots=True)
class EtfIndexMapping:
    etf_id: UUID
    index_id: UUID
    effective_from: date
    effective_to: date | None
    observed_at: datetime
    provenance: ExposureProvenance
    content_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "etf_id", _uuid(self.etf_id, "etf_id")); object.__setattr__(self, "index_id", _uuid(self.index_id, "index_id")); object.__setattr__(self, "effective_from", _date(self.effective_from, "effective_from")); object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if self.effective_to is not None:
            object.__setattr__(self, "effective_to", _date(self.effective_to, "effective_to"))
            if self.effective_to < self.effective_from: raise ValueError("effective_to must be on or after effective_from")
        if not isinstance(self.provenance, ExposureProvenance): raise TypeError("provenance must be an ExposureProvenance")
        computed = _hash({"type": "etf_index_mapping", "etf_id": self.etf_id, "index_id": self.index_id, "effective_from": self.effective_from, "effective_to": self.effective_to, "observed_at": self.observed_at, "provenance": _prov_payload(self.provenance)})
        object.__setattr__(self, "content_hash", _validated_hash(self.content_hash, computed))


@dataclass(frozen=True, slots=True)
class EtfHoldingSnapshot:
    id: UUID
    etf_id: UUID
    as_of_date: date
    observed_at: datetime
    holdings: tuple[EtfHolding, ...]
    provenance: ExposureProvenance
    content_hash: str = ""
    created_at: datetime | None = None

    @classmethod
    def create(cls, *, etf_id: UUID, as_of_date: date, observed_at: datetime, holdings: Iterable[EtfHolding], provenance: ExposureProvenance, id_factory: Callable[[], UUID] = uuid4, now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)) -> "EtfHoldingSnapshot":
        values = tuple(holdings)
        if not values: raise ValueError("holdings must contain at least one item")
        if any(not isinstance(item, EtfHolding) for item in values): raise TypeError("holdings must contain EtfHolding instances")
        values = tuple(sorted(values, key=_security_code_key))
        if len({item.stock_code for item in values}) != len(values): raise ValueError("holdings contain duplicates")
        return cls(id_factory(), etf_id, as_of_date, observed_at, values, provenance, created_at=now_factory())

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _uuid(self.id, "id")); object.__setattr__(self, "etf_id", _uuid(self.etf_id, "etf_id")); object.__setattr__(self, "as_of_date", _date(self.as_of_date, "as_of_date")); object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if not isinstance(self.holdings, tuple): raise ValueError("holdings must be a tuple")
        if not self.holdings: raise ValueError("holdings must not be empty")
        if any(not isinstance(item, EtfHolding) for item in self.holdings): raise TypeError("holdings must contain EtfHolding instances")
        sorted_holdings = tuple(sorted(self.holdings, key=_security_code_key))
        if len({item.stock_code for item in sorted_holdings}) != len(sorted_holdings): raise ValueError("holdings contain duplicates")
        object.__setattr__(self, "holdings", sorted_holdings)
        if not isinstance(self.provenance, ExposureProvenance): raise TypeError("provenance must be an ExposureProvenance")
        created = self.created_at if self.created_at is not None else datetime.now(UTC)
        object.__setattr__(self, "created_at", _aware(created, "created_at"))
        computed = _snapshot_hash("etf_holdings", self.etf_id, self.as_of_date, self.observed_at, [(x.stock_code, x.weight, x.industry) for x in sorted_holdings], self.provenance)
        object.__setattr__(self, "content_hash", _validated_hash(self.content_hash, computed))


__all__ = ["EtfHolding", "EtfHoldingSnapshot", "EtfIndexMapping", "ExposureProvenance", "IndexConstituent", "IndexConstituentSnapshot", "IndexProfile"]
