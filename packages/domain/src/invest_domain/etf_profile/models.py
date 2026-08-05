"""Pure domain model for the ``etf_profile`` bounded context.

The :class:`EtfProfile` value object is the Stage DC-2 contract: one
immutable record of an ETF's static metadata per underlying instrument
(``core.instruments.id``). The model is deliberately infrastructure-free:

- No SQLAlchemy, Alembic, FastAPI, Dagster, httpx or Provider SDK imports.
- No environment access (``os.environ``) and no clock access.
- No field defaults that would fabricate values when the Provider
  response omits them; ``None`` is the canonical ``unknown`` carrier.

Validation policy:

- ``instrument_id`` is the stable 1-1 primary key. It must be a non-zero
  UUID (the same invariant :class:`invest_domain.instruments.models.
  InstrumentId` enforces on :class:`Instrument.id`) so a stored profile
  row always points back at a known instrument.
- All textual fields (``manager``, ``benchmark_index``, ``category``,
  ``fund_type``) are optional and rejected as empty when supplied,
  matching the ``length(...) > 0`` database check constraints.
- ``inception_date`` is optional and stored as a calendar date. Provider
  publication timing is not imposed in the pure domain model; any
  freshness or as-of-date policy belongs to the collection/application
  layer.
- ``management_fee`` and ``custody_fee`` are optional percentage rates
  expressed as ``Decimal`` fractions in the inclusive range
  ``[0, 1)`` so ``0.0015`` correctly represents the contractual
  ``0.15 %`` management fee. The exclusive upper bound rejects the
  meaningless ``100 %``+ total-fee rows a buggy provider response
  could otherwise introduce.
- ``aum`` (assets under management, in fund currency) and ``shares``
  (units outstanding) are optional and must be strictly positive
  finite ``Decimal`` values when supplied. ``Decimal`` carries full
  precision through the storage layer; the application service never
  rounds them before they reach the database.

The same field set is reflected 1-1 in the ``core.etf_profiles``
SQLAlchemy model added in PR for DC-2 and in the
``20260804_0008_etf_profiles`` Alembic migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

_INSTRUMENT_ID_NONE = UUID("00000000-0000-0000-0000-000000000000")


def _require_optional_text(value: str | None, *, field_name: str) -> str | None:
    """Accept ``None`` or a non-empty ``str``; reject blank/whitespace strings."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(
            f"EtfProfile.{field_name} must be a str or None, got {type(value).__name__}"
        )
    stripped = value.strip()
    if not stripped:
        raise ValueError(
            f"EtfProfile.{field_name} must not be empty when supplied"
        )
    return stripped


def _require_optional_fee_rate(
    value: Decimal | None, *, field_name: str
) -> Decimal | None:
    """Accept ``None`` or a finite ``Decimal`` in ``[0, 1)``.

    The fund management fee is recorded as a fractional rate
    (``0.0015`` for a contractual ``0.15 %``). An upper bound of
    ``1`` excludes the meaningless ``100 %``+ total-fee rows a buggy
    provider response could otherwise introduce; a lower bound of
    ``0`` keeps a legitimate zero-fee fund fundable for promotional
    products that the candidate pool may need to inspect.

    A ``None`` value is the documented carrier for ``unknown`` /
    ``not disclosed`` and never triggers a default.
    """

    if value is None:
        return None
    if not isinstance(value, Decimal) or isinstance(value, bool):
        raise TypeError(
            f"EtfProfile.{field_name} must be a Decimal or None, "
            f"got {type(value).__name__}"
        )
    if not value.is_finite():
        raise ValueError(
            f"EtfProfile.{field_name} must be a finite Decimal, got {value!s}"
        )
    if value < 0:
        raise ValueError(
            f"EtfProfile.{field_name} must be >= 0, got {value!s}"
        )
    if value >= 1:
        raise ValueError(
            f"EtfProfile.{field_name} must be < 1 (exclusive), got {value!s}"
        )
    return value


def _require_optional_positive_decimal(
    value: Decimal | None, *, field_name: str
) -> Decimal | None:
    """Accept ``None`` or a finite, strictly-positive ``Decimal``.

    Used for ``aum`` and ``shares``: both represent physical quantities
    that are unambiguously positive when disclosed. A ``None`` value is
    the carrier for ``unknown`` / ``not disclosed`` and never triggers
    a default.
    """

    if value is None:
        return None
    if not isinstance(value, Decimal) or isinstance(value, bool):
        raise TypeError(
            f"EtfProfile.{field_name} must be a Decimal or None, "
            f"got {type(value).__name__}"
        )
    if not value.is_finite():
        raise ValueError(
            f"EtfProfile.{field_name} must be a finite Decimal, got {value!s}"
        )
    if value <= 0:
        raise ValueError(
            f"EtfProfile.{field_name} must be > 0, got {value!s}"
        )
    return value


def _require_instrument_uuid(value: Any, *, field_name: str) -> UUID:
    """Reject non-UUID or all-zero UUIDs.

    The instrument id is the 1-1 primary key of ``core.etf_profiles``
    and MUST always refer to a known row in ``core.instruments``. The
    all-zero UUID is explicitly rejected because it can only ever mean
    ``unknown`` here, which would silently break the foreign key
    constraint at insert time.
    """

    if not isinstance(value, UUID) or isinstance(value, bool):
        raise TypeError(
            f"EtfProfile.{field_name} must be a UUID, got {type(value).__name__}"
        )
    if value == _INSTRUMENT_ID_NONE:
        raise ValueError(
            f"EtfProfile.{field_name} must not be the all-zero UUID"
        )
    return value


@dataclass(frozen=True, slots=True)
class EtfProfile:
    """Immutable, pure-domain record of one ETF's static metadata.

    The field set mirrors the Stage DC-2 plan
    (``docs/plan/invest-infra-data-collection-enhancement-plan-v1.0.md``
    §"DC-2 ETF 基础研究数据 / ETF Profile") and the
    ``core.etf_profiles`` storage row introduced in the
    ``20260804_0008_etf_profiles`` Alembic migration. The natural key
    is ``instrument_id`` (one profile per listed instrument).

    Construction rules:

    - ``instrument_id`` (UUID, required) must be a non-zero UUID. It is
      the storage primary key and the foreign key to
      ``core.instruments.id``.
    - ``manager`` (str | None) — the fund manager's name as disclosed
      by the Provider; ``None`` when undisclosed. An empty or
      whitespace-only string is rejected.
    - ``benchmark_index`` (str | None) — the underlying benchmark
      identifier; ``None`` when undisclosed.
    - ``category`` (str | None) — the Provider's coarse
      classification (``Equity``, ``Bond``, ``Commodity`` ...);
      ``None`` when undisclosed.
    - ``inception_date`` (date | None) — the listing / inception date.
      ``None`` when undisclosed. It is validated as a calendar date;
      collection-time freshness policy is outside this value object.
    - ``fund_type`` (str | None) — the legal/open-end/closed-end
      taxonomy; ``None`` when undisclosed.
    - ``management_fee`` (Decimal | None) — annual management fee as a
      fractional rate (``0.0015`` = 0.15%); ``None`` when undisclosed.
      Inclusive lower bound ``0``, exclusive upper bound ``1``.
    - ``custody_fee`` (Decimal | None) — annual custody fee as a
      fractional rate. Same bounds as ``management_fee``.
    - ``aum`` (Decimal | None) — assets under management in fund
      currency; ``None`` when undisclosed. Strictly positive when
      supplied.
    - ``shares`` (Decimal | None) — units outstanding; ``None`` when
      undisclosed. Strictly positive when supplied.

    The dataclass is ``frozen=True`` + ``slots=True``; every assignment
    path passes through :meth:`__post_init__` so the validation cannot
    be bypassed via ``object.__setattr__``.
    """

    instrument_id: UUID
    manager: str | None = None
    benchmark_index: str | None = None
    category: str | None = None
    inception_date: date | None = None
    fund_type: str | None = None
    management_fee: Decimal | None = None
    custody_fee: Decimal | None = None
    aum: Decimal | None = None
    shares: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            _require_instrument_uuid(self.instrument_id, field_name="instrument_id"),
        )
        object.__setattr__(
            self, "manager", _require_optional_text(self.manager, field_name="manager")
        )
        object.__setattr__(
            self,
            "benchmark_index",
            _require_optional_text(self.benchmark_index, field_name="benchmark_index"),
        )
        object.__setattr__(
            self, "category", _require_optional_text(self.category, field_name="category")
        )
        object.__setattr__(
            self, "fund_type", _require_optional_text(self.fund_type, field_name="fund_type")
        )
        if self.inception_date is not None and (
            # ``datetime`` is a subclass of ``date``; explicitly reject
            # it so callers cannot smuggle in a timezone-aware timestamp
            # where the schema only stores a calendar date.
            isinstance(self.inception_date, datetime)
            or not isinstance(self.inception_date, date)
        ):
            raise TypeError(
                "EtfProfile.inception_date must be a date or None, "
                f"got {type(self.inception_date).__name__}"
            )
        object.__setattr__(
            self,
            "management_fee",
            _require_optional_fee_rate(
                self.management_fee, field_name="management_fee"
            ),
        )
        object.__setattr__(
            self,
            "custody_fee",
            _require_optional_fee_rate(self.custody_fee, field_name="custody_fee"),
        )
        object.__setattr__(
            self,
            "aum",
            _require_optional_positive_decimal(self.aum, field_name="aum"),
        )
        object.__setattr__(
            self,
            "shares",
            _require_optional_positive_decimal(self.shares, field_name="shares"),
        )


__all__ = ["EtfProfile"]
