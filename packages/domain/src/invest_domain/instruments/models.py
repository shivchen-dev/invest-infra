"""Domain model for the ``instruments`` bounded context.

The :class:`InstrumentId` wraps a UUID and is the stable internal identity
referenced by every downstream aggregate (``DailyBar``, ``CandidatePoolItem``,
``input_snapshot_rows``). The legacy ``(symbol, exchange)`` pair remains a
valid business key for Provider communication and human display, but is no
longer the database primary key (see M0-DECISIONS §6 / M0-CODING-BRIEF
Phase 1-C).

Backward compatibility:

- The positional 4-argument ``Instrument(symbol, name, exchange, instrument_type)``
  constructor signature is preserved; new fields are optional and have
  ``None`` defaults so existing callers (including ``MockInstrumentProvider``,
  ``SqlAlchemyInstrumentRepository`` and ``tests/test_domain.py``) continue
  to work unchanged.
- ``InvestDomain.instruments`` continues to re-export ``Instrument`` and
  ``InstrumentType`` from the original module location.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from invest_domain.instruments.values import InstrumentStatus
from invest_domain.shared.values import Currency, Exchange


class InstrumentType(StrEnum):
    ETF = "ETF"
    STOCK = "STOCK"
    INDEX = "INDEX"


_INSTRUMENT_ID_NONE = UUID("00000000-0000-0000-0000-000000000000")


@dataclass(frozen=True, slots=True)
class InstrumentId:
    """Stable internal identity for an instrument.

    The wrapped UUID is the storage-layer primary key (see M0-DECISIONS §6).
    The all-zero UUID is explicitly rejected to avoid accidental "no id"
    semantics. Parsing from string accepts both the canonical
    ``8-4-4-4-12`` hex form and the 32-digit no-hyphen form.
    """

    value: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.value, UUID):
            raise TypeError(
                f"InstrumentId.value must be a UUID instance, got {type(self.value).__name__}"
            )
        if self.value == _INSTRUMENT_ID_NONE:
            raise ValueError("InstrumentId must not be the all-zero UUID")

    @classmethod
    def generate(cls) -> "InstrumentId":
        """Return a new :class:`InstrumentId` carrying a fresh UUIDv4."""
        return cls(uuid4())

    @classmethod
    def from_string(cls, value: str) -> "InstrumentId":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("InstrumentId.from_string requires a non-empty string")
        try:
            parsed = UUID(value.strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid UUID literal for InstrumentId: {value!r}") from exc
        return cls(parsed)

    def __str__(self) -> str:
        return str(self.value)


def _validate_optional_exchange(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("exchange must not be empty")
    if not Exchange.__members__:
        return value
    if value not in Exchange.__members__:
        raise ValueError(
            f"exchange {value!r} is not in the ADR-0004 allow-list; allowed: {sorted(Exchange.__members__)}"
        )
    return value


@dataclass(frozen=True, slots=True)
class Instrument:
    """Domain representation of a listed instrument.

    Backward-compat fields: ``symbol``, ``name``, ``exchange``,
    ``instrument_type``, ``is_active``. New optional fields are
    appended after the legacy positional block and default to ``None``
    so existing call sites keep working.

    Identity: ``(symbol, exchange)`` is a stable business key for
    Provider communication; ``instrument_id`` is the stable internal
    primary key. The model must never identify an instrument by
    ``symbol`` alone (see M0-CODISIONS §6 / M0-CODING-BRIEF Phase 1-B).
    """

    symbol: str
    name: str
    exchange: str
    instrument_type: InstrumentType
    is_active: bool = True
    instrument_id: InstrumentId | None = None
    currency: Currency = Currency.CNY
    list_date: date | None = None
    delist_date: date | None = None
    status: InstrumentStatus = InstrumentStatus.ACTIVE
    underlying_index: str | None = None
    category: str | None = None
    provider_symbol_map: dict[str, str] = field(default_factory=dict)
    valid_from: date | None = None
    valid_to: date | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        _validate_optional_exchange(self.exchange)
        if self.list_date is not None and self.delist_date is not None:
            if self.delist_date < self.list_date:
                raise ValueError(
                    f"delist_date {self.delist_date.isoformat()} must be on or after "
                    f"list_date {self.list_date.isoformat()}"
                )
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_to < self.valid_from:
                raise ValueError(
                    f"valid_to {self.valid_to.isoformat()} must be on or after "
                    f"valid_from {self.valid_from.isoformat()}"
                )
        if self.status is InstrumentStatus.DELISTED and self.delist_date is None:
            raise ValueError("status=DELISTED requires a delist_date")
        if not isinstance(self.provider_symbol_map, dict):
            raise ValueError("provider_symbol_map must be a dict[str, str]")

    @property
    def business_key(self) -> tuple[str, str]:
        """Return the stable Provider-facing business key ``(exchange, symbol)``."""
        return (self.exchange, self.symbol)


__all__ = [
    "Instrument",
    "InstrumentId",
    "InstrumentStatus",
    "InstrumentType",
]


# Re-export the market_data enums that ``Instrument`` validates against so
# downstream modules can import the whole family from a single namespace
# when they only have ``Instrument`` in scope. Intentionally untyped to
# avoid an import cycle through ``invest_domain.market_data.__init__``.
_Any = Any
