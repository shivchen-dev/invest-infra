"""DC-3 atomic slice: real AkShare exposure collection + persistence.

* :func:`collect_and_persist_real_exposure` resolves the ETF by
  business key via a short lookup :class:`UnitOfWork` (never committed,
  no network while open), fetches CSIndex constituents and AkShare
  reported holdings, validates inputs and cross-section consistency,
  and persists profile / constituents / mapping / holdings inside a
  single persistence UoW commit.
* The mapping provenance is operator-controlled
  (``provider_key="operator_controlled"``,
  ``dataset_key="etf_index_mapping"``); ``mapping_effective_from`` and
  optional ``mapping_effective_to`` are caller-supplied so observation
  time is never substituted for the effective date.
* ``ProviderRequest`` / ``ProviderAttempt`` / ``ProviderBatch`` audit
  rows are out of scope; both :attr:`AkshareResponse.raw_payload_hash`
  values are returned so the next slice can stamp audit rows without
  conflating transactions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from invest_domain.exposure import (
    EtfIndexMapping,
    ExposureProvenance,
    IndexProfile,
)
from invest_domain.instruments import InstrumentId, InstrumentType
from invest_storage.unit_of_work import UnitOfWork

from invest_pipeline.adapters.akshare.client import AkshareResponse
from invest_pipeline.adapters.akshare.exposure_mapper import (
    CsindexExposureMapping,
    map_csindex_constituent_weights,
)
from invest_pipeline.adapters.akshare.holding_mapper import map_reported_etf_holdings


class RealExposureServiceError(ValueError):
    """Base class for application-layer real-exposure service errors."""


class InvalidSymbolError(RealExposureServiceError): ...


class InvalidExchangeError(RealExposureServiceError): ...


class InvalidIndexCodeError(RealExposureServiceError): ...


class InvalidMappingDateError(RealExposureServiceError): ...


class InvalidHoldingYearError(RealExposureServiceError): ...


class NaiveObservedAtError(RealExposureServiceError): ...


class InstrumentNotFoundError(RealExposureServiceError, LookupError): ...


class NonEtfInstrumentError(RealExposureServiceError): ...


class InstrumentIdMissingError(RealExposureServiceError): ...


class IndexCodeMismatchError(RealExposureServiceError): ...


class HoldingEtfIdMismatchError(RealExposureServiceError): ...


class InstrumentResolutionMismatchError(RealExposureServiceError): ...


@runtime_checkable
class RealExposureClientProtocol(Protocol):
    """Minimal client surface the slice requires for the two DC-3 fetches."""

    def fetch_index_stock_cons_weight_csindex(
        self, *, index_code: str
    ) -> AkshareResponse: ...

    def fetch_fund_portfolio_hold_em(
        self, *, etf_code: str, year: str
    ) -> AkshareResponse: ...


UnitOfWorkFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class RealExposurePersistResult:
    """Identifiers, hashes, and raw payload hashes returned to the caller.

    All identifiers and content hashes come from the storage layer after
    persistence; both ``*_raw_payload_hash`` fields come from the
    upstream :class:`AkshareResponse` so the next slice can stamp audit
    rows outside this transaction.
    """

    etf_id: UUID
    index_id: UUID
    profile_id: UUID
    profile_content_hash: str
    constituent_snapshot_id: UUID
    constituent_content_hash: str
    mapping_id: UUID
    mapping_content_hash: str
    holding_snapshot_id: UUID
    holding_content_hash: str
    constituents_raw_payload_hash: str
    holdings_raw_payload_hash: str


def _six_digit(value: object, field: str, error: type[RealExposureServiceError]) -> str:
    if not isinstance(value, str):
        raise error(f"{field} must be a string")
    stripped = value.strip()
    if len(stripped) != 6 or not stripped.isdigit():
        raise error(f"{field} must be a non-empty 6-digit numeric string")
    return stripped


def _non_empty_str(value: object, field: str, error: type[RealExposureServiceError]) -> str:
    if not isinstance(value, str):
        raise error(f"{field} must be a string")
    stripped = value.strip()
    if not stripped:
        raise error(f"{field} must be a non-empty string")
    return stripped


def _date_value(value: object, field: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise InvalidMappingDateError(f"{field} must be a date")
    return value


def _observed_at_value(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise NaiveObservedAtError("observed_at must be a timezone-aware datetime")
    return value


def _holding_year_value(value: object) -> str:
    if not isinstance(value, str):
        raise InvalidHoldingYearError("holding_year must be a string")
    stripped = value.strip()
    if stripped == "":
        return ""
    if len(stripped) != 4 or not stripped.isdigit():
        raise InvalidHoldingYearError("holding_year must be empty or exactly 4 digits")
    return stripped


def _revision_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RealExposureServiceError("revision must be a positive integer")
    return value


def _confidence_value(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise RealExposureServiceError("confidence must be a finite Decimal")
    if not Decimal("0") <= value <= Decimal("1"):
        raise RealExposureServiceError("confidence must be in [0, 1]")
    return value


def _source_batch_id_value(value: object) -> UUID | None:
    if value is None:
        return None
    if not isinstance(value, UUID) or value.int == 0:
        raise RealExposureServiceError("mapping_source_batch_id must be a non-zero UUID or None")
    return value


def _instrument_id_value(instrument_id: object) -> UUID | None:
    if instrument_id is None:
        return None
    if isinstance(instrument_id, InstrumentId):
        return instrument_id.value
    if isinstance(instrument_id, UUID):
        return instrument_id
    raise InstrumentIdMissingError(
        f"instrument_id must be a UUID or InstrumentId (got {type(instrument_id).__name__})"
    )


def _stored_id(stored: object) -> UUID:
    value = getattr(stored, "id", None)
    if hasattr(value, "value"):
        value = value.value
    if isinstance(value, UUID) and value.int != 0:
        return value
    raise RealExposureServiceError("repository returned a stored row without a valid id")


def _stored_hash(stored: object) -> str:
    value = getattr(stored, "content_hash", None)
    if isinstance(value, str) and value.strip():
        return value
    raise RealExposureServiceError("repository returned a stored row without a valid content_hash")


def _payload_hash(response: AkshareResponse) -> str:
    value = response.raw_payload_hash
    if isinstance(value, str) and value.strip():
        return value
    raise RealExposureServiceError("provider returned a response without a valid raw_payload_hash")


def collect_and_persist_real_exposure(
    *,
    client: RealExposureClientProtocol,
    etf_symbol: str,
    etf_exchange: str,
    index_code: str,
    mapping_effective_from: date,
    observed_at: datetime,
    uow_factory: UnitOfWorkFactory,
    holding_year: str = "",
    mapping_effective_to: date | None = None,
    revision: int = 1,
    confidence: Decimal = Decimal("1"),
    mapping_source_batch_id: UUID | None = None,
    id_factory: Callable[[], UUID] = uuid4,
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RealExposurePersistResult:
    """Collect real exposure data and persist it through a single commit.

    See module docstring for the slice contract.
    """
    symbol = _six_digit(etf_symbol, "etf_symbol", InvalidSymbolError)
    exchange = _non_empty_str(etf_exchange, "etf_exchange", InvalidExchangeError)
    index = _six_digit(index_code, "index_code", InvalidIndexCodeError)
    observed = _observed_at_value(observed_at).astimezone(UTC)
    year = _holding_year_value(holding_year)
    validated_revision = _revision_value(revision)
    validated_confidence = _confidence_value(confidence)
    validated_batch_id = _source_batch_id_value(mapping_source_batch_id)

    from_date = _date_value(mapping_effective_from, "mapping_effective_from")
    if mapping_effective_to is None:
        effective_to: date | None = None
    else:
        to_date = _date_value(mapping_effective_to, "mapping_effective_to")
        if to_date < from_date:
            raise InvalidMappingDateError(
                f"mapping_effective_to {to_date.isoformat()} must be on or after "
                f"mapping_effective_from {from_date.isoformat()}"
            )
        effective_to = to_date

    # Phase 1: lookup UoW. Resolve the ETF by business key. No network
    # while open and the transaction is rolled back before exit so the
    # SELECT-only transaction never reaches the WAL stream.
    lookup_uow = uow_factory()
    with lookup_uow:
        instrument = lookup_uow.instruments.get_by_business_key(
            exchange=exchange, symbol=symbol
        )
        if instrument is None:
            raise InstrumentNotFoundError(
                f"ETF instrument ({exchange!r}, {symbol!r}) not found"
            )
        if getattr(instrument, "instrument_type", None) is not InstrumentType.ETF:
            raise NonEtfInstrumentError(
                f"instrument ({exchange!r}, {symbol!r}) is not an ETF"
            )
        if getattr(instrument, "is_active", None) is not True:
            raise InstrumentResolutionMismatchError(
                f"instrument ({exchange!r}, {symbol!r}) is not active"
            )
        etf_id_value = _instrument_id_value(instrument.instrument_id)
        if etf_id_value is None:
            raise InstrumentIdMissingError(
                f"ETF instrument ({exchange!r}, {symbol!r}) has no stored UUID"
            )
        lookup_uow.rollback()

    # Phase 2: network. Both fetches happen OUTSIDE any UoW.
    constituents_response = client.fetch_index_stock_cons_weight_csindex(index_code=index)
    holdings_response = client.fetch_fund_portfolio_hold_em(etf_code=symbol, year=year)

    # Phase 3: map with shared explicit inputs.
    constituents_mapping: CsindexExposureMapping = map_csindex_constituent_weights(
        constituents_response,
        observed_at=observed,
        revision=validated_revision,
        confidence=validated_confidence,
        id_factory=id_factory,
        now_factory=now_factory,
    )
    holding_snapshot = map_reported_etf_holdings(
        holdings_response,
        etf_id=etf_id_value,
        observed_at=observed,
        revision=validated_revision,
        confidence=validated_confidence,
        id_factory=id_factory,
        now_factory=now_factory,
    )
    profile: IndexProfile = constituents_mapping.profile
    constituent_snapshot = constituents_mapping.constituent_snapshot

    if profile.index_code != index:
        raise IndexCodeMismatchError(
            f"mapped profile.index_code {profile.index_code!r} != requested {index!r}"
        )
    if holding_snapshot.etf_id != etf_id_value:
        raise HoldingEtfIdMismatchError(
            f"holding_snapshot.etf_id {holding_snapshot.etf_id!s} != resolved {etf_id_value!s}"
        )

    # Phase 4: persistence UoW. Re-resolve to fail closed on
    # disappearance / identity change; mint the stable index identity,
    # build the operator-controlled mapping, persist four rows in one
    # commit.
    persistence_uow = uow_factory()
    with persistence_uow:
        rechecked = persistence_uow.instruments.get_by_business_key(
            exchange=exchange, symbol=symbol
        )
        if rechecked is None:
            raise InstrumentNotFoundError(
                f"ETF ({exchange!r}, {symbol!r}) disappeared between phases"
            )
        if getattr(rechecked, "instrument_type", None) is not InstrumentType.ETF:
            raise NonEtfInstrumentError(
                f"instrument ({exchange!r}, {symbol!r}) is no longer an ETF"
            )
        if getattr(rechecked, "is_active", None) is not True:
            raise InstrumentResolutionMismatchError(
                f"instrument ({exchange!r}, {symbol!r}) is not active"
            )
        rechecked_id = _instrument_id_value(rechecked.instrument_id)
        if rechecked_id is None:
            raise InstrumentIdMissingError(
                f"instrument ({exchange!r}, {symbol!r}) has no stored UUID"
            )
        if rechecked_id != etf_id_value:
            raise InstrumentResolutionMismatchError(
                f"persistence UoW resolved {rechecked_id!s}, lookup {etf_id_value!s}"
            )

        identity = persistence_uow.index_identities.add(
            index_code=profile.index_code,
            index_name=profile.index_name,
            category=profile.category,
        )
        stable_index_id = _stored_id(identity)

        mapping = EtfIndexMapping(
            etf_id=etf_id_value,
            index_id=stable_index_id,
            effective_from=from_date,
            effective_to=effective_to,
            observed_at=observed,
            provenance=ExposureProvenance(
                provider_key="operator_controlled",
                dataset_key="etf_index_mapping",
                observed_at=observed,
                source_batch_id=validated_batch_id,
                revision=validated_revision,
                confidence=validated_confidence,
            ),
        )

        stored_profile = persistence_uow.index_profiles.add(profile, index_id=stable_index_id)
        stored_constituent = persistence_uow.index_constituent_snapshots.add(
            constituent_snapshot, index_id=stable_index_id
        )
        stored_mapping = persistence_uow.etf_index_mappings.add(mapping)
        stored_holding = persistence_uow.etf_holding_snapshots.add(holding_snapshot)
        result = RealExposurePersistResult(
            etf_id=etf_id_value,
            index_id=stable_index_id,
            profile_id=_stored_id(stored_profile),
            profile_content_hash=_stored_hash(stored_profile),
            constituent_snapshot_id=_stored_id(stored_constituent),
            constituent_content_hash=_stored_hash(stored_constituent),
            mapping_id=_stored_id(stored_mapping),
            mapping_content_hash=_stored_hash(stored_mapping),
            holding_snapshot_id=_stored_id(stored_holding),
            holding_content_hash=_stored_hash(stored_holding),
            constituents_raw_payload_hash=_payload_hash(constituents_response),
            holdings_raw_payload_hash=_payload_hash(holdings_response),
        )
        persistence_uow.commit()

    return result


__all__ = [
    "HoldingEtfIdMismatchError",
    "IndexCodeMismatchError",
    "InstrumentIdMissingError",
    "InstrumentNotFoundError",
    "InstrumentResolutionMismatchError",
    "InvalidExchangeError",
    "InvalidHoldingYearError",
    "InvalidIndexCodeError",
    "InvalidMappingDateError",
    "InvalidSymbolError",
    "NaiveObservedAtError",
    "NonEtfInstrumentError",
    "RealExposureClientProtocol",
    "RealExposurePersistResult",
    "RealExposureServiceError",
    "UnitOfWorkFactory",
    "collect_and_persist_real_exposure",
]
