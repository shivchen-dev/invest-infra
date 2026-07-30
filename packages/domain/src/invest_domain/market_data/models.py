"""Pure domain models for the ``market_data`` bounded context.

The models in this module are deliberately infrastructure-free:

- No SQLAlchemy, Alembic, FastAPI, Dagster, httpx or Provider SDK imports.
- No environment access (``os.environ``) and no clock access.
- All Decimal / date / datetime / UUID handling goes through
  :mod:`invest_domain.shared.canonical` so that ``DailyBar.row_hash`` is
  deterministic across processes, platforms and Python versions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID

from invest_domain.instruments.models import InstrumentId
from invest_domain.market_data.values import Adjust, Currency, TradingStatus
from invest_domain.shared.canonical import (
    CANONICAL_HASH_SCHEMA_VERSION,
    content_hash,
)

T = TypeVar("T")


class ProviderBatchStatus(StrEnum):
    """Status of a Provider batch as reported by the Adapter.

    Mirrors the ADR-0003 ``raw.provider_batches.status`` vocabulary. The
    domain does not enforce retries; it only records the outcome so the
    application layer can decide what to do.
    """

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProviderBatch(Generic[T]):
    """A single Provider response bundle.

    The Adapter is responsible for filling every metadata field; the domain
    treats the batch as immutable evidence. ``raw_payload_hash`` is the
    hex SHA-256 of the original response bytes computed by the Adapter; the
    domain does not have access to the response itself.
    """

    provider_key: str
    dataset_key: str
    requested_at: datetime
    received_at: datetime
    records: Sequence[T]
    raw_payload_hash: str
    status: ProviderBatchStatus
    request_id: str | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider_key.strip():
            raise ValueError("ProviderBatch.provider_key must not be empty")
        if not self.dataset_key.strip():
            raise ValueError("ProviderBatch.dataset_key must not be empty")
        if self.requested_at.tzinfo is None:
            raise ValueError("ProviderBatch.requested_at must be timezone-aware")
        if self.received_at.tzinfo is None:
            raise ValueError("ProviderBatch.received_at must be timezone-aware")
        if self.received_at < self.requested_at:
            raise ValueError("ProviderBatch.received_at must be on or after requested_at")
        if not self.raw_payload_hash.strip():
            raise ValueError("ProviderBatch.raw_payload_hash must not be empty")
        if not isinstance(self.records, (list, tuple)):
            raise ValueError("ProviderBatch.records must be a Sequence")
        if not isinstance(self.warnings, tuple):
            raise ValueError("ProviderBatch.warnings must be a tuple[str, ...]")


@dataclass(frozen=True, slots=True)
class BarSource:
    """Audit metadata attached to a :class:`DailyBar` (NOT part of the row hash).

    Mirrors the columns ``source_provider`` / ``source_batch_id`` /
    ``observed_at`` from the plan §5.3 daily-bars schema. Per ADR-0005 §8
    these fields are audit-only and MUST NOT enter ``DailyBar.row_hash``;
    the row hash is a content-only digest that stays stable across source
    re-collects, batch re-IDs and observed-at refreshes.
    """

    provider_key: str
    source_batch_id: UUID
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.provider_key.strip():
            raise ValueError("BarSource.provider_key must not be empty")
        if not isinstance(self.source_batch_id, UUID):
            raise TypeError(
                f"BarSource.source_batch_id must be a UUID, got {type(self.source_batch_id).__name__}"
            )
        if self.observed_at.tzinfo is None:
            raise ValueError("BarSource.observed_at must be timezone-aware")


def bar_source_metadata_hash(source: BarSource) -> str:
    """Return a deterministic hash for the ``BarSource`` audit portion.

    This is a separate digest from ``DailyBar.row_hash``; it is used to
    correlate the audit trail across re-collects and MUST NOT be confused
    with the content hash.
    """

    return content_hash(
        {
            "provider_key": source.provider_key,
            "source_batch_id": source.source_batch_id,
            "observed_at": source.observed_at,
        }
    )


def _require_positive_decimal(value: Decimal, *, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(
            f"DailyBar.{field_name} must be a Decimal, got {type(value).__name__}"
        )
    if not value.is_finite():
        raise ValueError(f"DailyBar.{field_name} must be a finite Decimal")
    if value <= 0:
        raise ValueError(f"DailyBar.{field_name} must be > 0, got {value!s}")
    return value


def _require_non_negative_decimal_or_none(
    value: Decimal | None, *, field_name: str
) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise TypeError(
            f"DailyBar.{field_name} must be a Decimal or None, got {type(value).__name__}"
        )
    if not value.is_finite():
        raise ValueError(f"DailyBar.{field_name} must be a finite Decimal")
    if value < 0:
        raise ValueError(f"DailyBar.{field_name} must be >= 0, got {value!s}")
    return value


def _build_business_payload(self_like: "DailyBar") -> dict[str, object]:
    """Build the canonical payload that feeds ``DailyBar.row_hash``.

    Per ADR-0005 §8 the digest is strictly the standardized business
    content; it MUST include ``hash_schema_version``, ``instrument_id``,
    ``trade_date``, ``adjustment``, the normalized OHLC, ``prev_close``,
    ``volume``, ``amount``, ``trading_status`` and ``currency``; and it
    MUST NOT include ``revision``, ``source``, ``row_hash`` itself, or
    any audit/timestamp field.

    The ``self_like`` parameter keeps the helper unit-testable without
    importing the dataclass machinery here.
    """

    return {
        "adjustment": self_like.adjustment,
        "amount": self_like.amount,
        "close": self_like.close,
        "currency": self_like.currency,
        "hash_schema_version": self_like.hash_schema_version,
        "high": self_like.high,
        "instrument_id": self_like.instrument_id.value,
        "low": self_like.low,
        "open": self_like.open,
        "prev_close": self_like.prev_close,
        "trade_date": self_like.trade_date,
        "trading_status": self_like.trading_status,
        "volume": self_like.volume,
    }


@dataclass(frozen=True, slots=True)
class DailyBar:
    """One row of standardized daily OHLCV data.

    The first-phase contract follows ADR-0005 §3 / §6 / §8 strictly:

    - Storage primary key is ``(instrument_id, trade_date, adjustment, revision)``
      (ADR-0006). ``revision`` and the audit fields in :class:`BarSource`
      exist for the storage layer and revision model; they are NOT part of
      ``row_hash``.
    - The exchange is carried by the referenced :class:`Instrument`, not
      duplicated on the row.
    - ``nav`` / ``iopv`` / ``premium_rate`` are NOT part of the Phase 1
      contract (ADR-0005 §3 last paragraph); even if a Provider returns
      them, the domain refuses to carry them.
    - ``row_hash`` covers the business content only and is therefore
      stable across source re-collects and revision bumps.
    - ``row_hash`` defaults to ``None``; :meth:`__post_init__` fills it
      from :meth:`compute_row_hash`. Supplying a hash that does not match
      is a hard error.
    """

    instrument_id: InstrumentId
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    prev_close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    adjustment: Adjust
    trading_status: TradingStatus
    source: BarSource
    revision: int
    row_hash: str | None = None
    hash_schema_version: int = CANONICAL_HASH_SCHEMA_VERSION
    currency: Currency = Currency.CNY

    def __post_init__(self) -> None:
        if self.adjustment is not Adjust.NONE:
            raise ValueError(
                f"DailyBar.adjustment must be Adjust.NONE in production "
                f"(got {self.adjustment.value!r}); enabling non-none adjustments "
                f"requires an amendment to ADR-0005"
            )
        if not isinstance(self.instrument_id, InstrumentId):
            raise TypeError(
                "DailyBar.instrument_id must be an InstrumentId instance "
                f"(got {type(self.instrument_id).__name__})"
            )
        if self.revision < 1:
            raise ValueError(f"DailyBar.revision must be >= 1, got {self.revision}")
        if self.trading_status is TradingStatus.NORMAL:
            self._validate_normal_ohlcv()
        elif self.trading_status is TradingStatus.SUSPENDED:
            self._validate_suspended_ohlcv()
        else:
            raise ValueError(
                f"unknown TradingStatus {self.trading_status!r}; expected NORMAL or SUSPENDED"
            )
        if self.hash_schema_version != CANONICAL_HASH_SCHEMA_VERSION:
            raise ValueError(
                f"DailyBar.hash_schema_version {self.hash_schema_version} does not match the "
                f"current canonical version {CANONICAL_HASH_SCHEMA_VERSION}; mixed-version "
                f"rows are rejected at construction time"
            )
        computed = self.compute_row_hash()
        if self.row_hash is None:
            object.__setattr__(self, "row_hash", computed)
        elif not isinstance(self.row_hash, str) or not self.row_hash.strip():
            raise ValueError("DailyBar.row_hash must be a non-empty string when supplied")
        elif self.row_hash != computed:
            raise ValueError(
                "DailyBar.row_hash does not match the deterministic hash of the row payload"
            )

    def _validate_normal_ohlcv(self) -> None:
        o = _require_positive_decimal(self.open, field_name="open")
        h = _require_positive_decimal(self.high, field_name="high")
        l = _require_positive_decimal(self.low, field_name="low")
        c = _require_positive_decimal(self.close, field_name="close")
        _require_positive_decimal(self.prev_close, field_name="prev_close")
        if h < max(o, c, l):
            raise ValueError(
                f"high {h!s} must be >= max(open, close, low) = {max(o, c, l)!s}"
            )
        if l > min(o, c, h):
            raise ValueError(
                f"low {l!s} must be <= min(open, close, high) = {min(o, c, h)!s}"
            )
        _require_non_negative_decimal_or_none(self.volume, field_name="volume")
        _require_non_negative_decimal_or_none(self.amount, field_name="amount")

    def _validate_suspended_ohlcv(self) -> None:
        forbidden = (
            "open",
            "high",
            "low",
            "close",
            "prev_close",
            "volume",
            "amount",
        )
        for name in forbidden:
            if getattr(self, name) is not None:
                raise ValueError(
                    f"trading_status=SUSPENDED must not carry {name}={getattr(self, name)!s}; "
                    f"ADR-0005 forbids fabricating OHLCV for suspended sessions"
                )

    def compute_row_hash(self) -> str:
        """Return the deterministic business-content hash for this bar.

        Per ADR-0005 §8 the digest is the canonicalized business content
        only: ``hash_schema_version``, ``instrument_id``, ``trade_date``,
        ``adjustment``, the normalized OHLC, ``prev_close``, ``volume``,
        ``amount``, ``trading_status`` and ``currency``. Audit-only
        fields (``revision``, ``source``) and the ``row_hash`` itself
        are deliberately excluded so that the same business content
        produces the same hash across re-collects and revision bumps.
        """

        return content_hash(_build_business_payload(self))

    @classmethod
    def build(
        cls,
        *,
        instrument_id: InstrumentId,
        trade_date: date,
        open: Decimal | None,
        high: Decimal | None,
        low: Decimal | None,
        close: Decimal | None,
        prev_close: Decimal | None,
        volume: Decimal | None,
        amount: Decimal | None,
        adjustment: Adjust,
        trading_status: TradingStatus,
        source: BarSource,
        revision: int,
        currency: Currency = Currency.CNY,
    ) -> "DailyBar":
        """Build a :class:`DailyBar` and let :meth:`__post_init__` fill ``row_hash``.

        Leaves ``row_hash`` unset; :meth:`__post_init__` fills it from
        :meth:`compute_row_hash` so callers never have to compute the
        digest by hand. To assert that a precomputed hash matches the
        payload, pass it via the regular constructor instead.
        """
        return cls(
            instrument_id=instrument_id,
            trade_date=trade_date,
            open=open,
            high=high,
            low=low,
            close=close,
            prev_close=prev_close,
            volume=volume,
            amount=amount,
            adjustment=adjustment,
            trading_status=trading_status,
            source=source,
            revision=revision,
            row_hash=None,
            currency=currency,
        )


__all__ = [
    "BarSource",
    "DailyBar",
    "ProviderBatch",
    "ProviderBatchStatus",
    "bar_source_metadata_hash",
]
