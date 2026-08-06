"""DC-3 atomic slice: standardized exposure payload to UnitOfWork persistence.

This module implements the smallest complete application-service slice for
persisting an already-standardized AKShare exposure bundle:

* Accept a raw AKShare exposure payload (the JSON-shaped Mapping produced by
  the adapter layer) plus a :data:`UnitOfWorkFactory`.
* Call :func:`map_standardized_payload <invest_pipeline.adapters.exposure.map_standardized_payload>`
  exactly once before opening the UoW.
* Validate cross-section consistency:
  ``profile.index_code == constituent_snapshot.index_code`` and
  ``mapping.etf_id == holding_snapshot.etf_id``.
* Validate the referenced ETF instrument exists via
  ``uow.instruments.get_by_id``.
* Obtain the canonical stable index identity via
  ``uow.index_identities.add(index_code, index_name, category)``.
* Rebuild :class:`EtfIndexMapping` using ``identity.id`` as ``index_id``
  (the payload ``index_id`` is explicitly ignored).
* Persist ``profile``, ``constituents``, rebuilt ``mapping``, and
  ``holdings`` in one :class:`UnitOfWork` transaction; commit exactly once.
* Return a frozen result dataclass with the stable ``index_id`` and
  persisted record identifiers / content hashes.
* Exceptions abort the transaction without a commit (idempotent re-runs
  work because the content-hash idempotency guard short-circuits re-inserts).

The slice is intentionally Dagster-free: no asset wiring, no network,
no CLI. Errors are typed application-domain exceptions, not raw
storage exceptions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from invest_domain.exposure import (
    EtfHoldingSnapshot,
    EtfIndexMapping,
    IndexConstituentSnapshot,
    IndexProfile,
)
from invest_storage.unit_of_work import UnitOfWork

from invest_pipeline.adapters.exposure import map_standardized_payload

__all__ = [
    "ExposurePersistResult",
    "ExposureServiceError",
    "EtfIdMismatchError",
    "IndexCodeMismatchError",
    "InstrumentNotFoundError",
    "persist_exposure",
    "UnitOfWorkFactory",
]


UnitOfWorkFactory = Callable[[], UnitOfWork]


class ExposureServiceError(ValueError):
    """Base class for application-layer exposure service errors."""


class IndexCodeMismatchError(ExposureServiceError):
    """Raised when ``profile.index_code != constituent_snapshot.index_code``."""


class EtfIdMismatchError(ExposureServiceError):
    """Raised when ``mapping.etf_id != holding_snapshot.etf_id``."""


class InstrumentNotFoundError(ExposureServiceError, LookupError):
    """Raised when the ETF instrument referenced by ``etf_id`` does not exist."""


@dataclass(frozen=True, slots=True)
class ExposurePersistResult:
    """Return shape of :func:`persist_exposure`.

    Frozen so callers can use instances as dict keys or set members for
    audit trails. All identifiers and content hashes are the canonical
    values produced by the storage layer after persistence.
    """

    index_id: UUID
    """Stable index identity UUID obtained from ``uow.index_identities.add``."""

    profile_id: UUID
    """Persisted ``core.index_profiles`` row identifier."""

    profile_content_hash: str
    """Content hash of the persisted index profile."""

    constituent_snapshot_id: UUID
    """Persisted ``core.index_constituent_snapshots`` row identifier."""

    constituent_content_hash: str
    """Content hash of the persisted constituent snapshot."""

    mapping_id: UUID
    """Persisted ``core.etf_index_mappings`` row identifier."""

    mapping_content_hash: str
    """Content hash of the persisted ETF-index mapping."""

    holding_snapshot_id: UUID
    """Persisted ``core.etf_holding_snapshots`` row identifier."""

    holding_content_hash: str
    """Content hash of the persisted ETF holding snapshot."""


def persist_exposure(
    raw_payload: Mapping[str, Any],
    uow_factory: UnitOfWorkFactory,
) -> ExposurePersistResult:
    """Persist an exposure bundle from the raw adapter payload.

    The ``raw_payload`` argument is the JSON-shaped Mapping received from
    the adapter layer. This function calls
    :func:`map_standardized_payload <invest_pipeline.adapters.exposure.map_standardized_payload>`
    exactly once to produce the four domain objects before opening the
    UnitOfWork.

    The mapped bundle dict has the following structure::

        {
            "index_profile": IndexProfile,
            "index_constituents": IndexConstituentSnapshot,
            "etf_index_mapping": EtfIndexMapping,
            "etf_holdings": EtfHoldingSnapshot,
        }

    The function performs these steps:

    1. Call ``map_standardized_payload`` on ``raw_payload``.
    2. Cross-section validation: ``profile.index_code`` must equal
       ``constituent_snapshot.index_code``; ``mapping.etf_id`` must equal
       ``holding_snapshot.etf_id``.  These checks happen BEFORE opening
       the UnitOfWork so the factory is never called on invalid input.
    3. Open UnitOfWork via ``uow_factory()``.
    4. ETF instrument existence check via ``uow.instruments.get_by_id``.
    5. Canonical index identity via ``uow.index_identities.add`` using
       ``profile.index_code``, ``profile.index_name``, and ``profile.category``.
       The returned ``identity.id`` replaces any payload-supplied ``index_id``.
    6. :class:`EtfIndexMapping` rebuilt with ``identity.id`` as ``index_id``.
    7. Persist: ``index_profiles``, ``index_constituent_snapshots``,
       rebuilt ``etf_index_mappings``, ``etf_holding_snapshots``.
    8. Commit exactly once on success; rollback on any exception.

    Content-hash idempotency guards mean re-runs with the same bundle are
    safe and return the same ``ExposurePersistResult``.
    """
    standardized: dict[str, Any] = map_standardized_payload(raw_payload)

    profile: IndexProfile = standardized["index_profile"]
    constituent_snapshot: IndexConstituentSnapshot = standardized["index_constituents"]
    mapping: EtfIndexMapping = standardized["etf_index_mapping"]
    holding_snapshot: EtfHoldingSnapshot = standardized["etf_holdings"]

    if profile.index_code != constituent_snapshot.index_code:
        raise IndexCodeMismatchError(
            f"profile.index_code {profile.index_code!r} does not match "
            f"constituent_snapshot.index_code {constituent_snapshot.index_code!r}"
        )

    if mapping.etf_id != holding_snapshot.etf_id:
        raise EtfIdMismatchError(
            f"mapping.etf_id {mapping.etf_id!s} does not match "
            f"holding_snapshot.etf_id {holding_snapshot.etf_id!s}"
        )

    with uow_factory() as uow:
        instrument = uow.instruments.get_by_id(mapping.etf_id)
        if instrument is None:
            raise InstrumentNotFoundError(
                f"ETF instrument {mapping.etf_id!s} not found in core.instruments"
            )

        identity: Any = uow.index_identities.add(
            index_code=profile.index_code,
            index_name=profile.index_name,
            category=profile.category,
        )

        rebuilt_mapping = EtfIndexMapping(
            etf_id=mapping.etf_id,
            index_id=identity.id,
            effective_from=mapping.effective_from,
            effective_to=mapping.effective_to,
            observed_at=mapping.observed_at,
            provenance=mapping.provenance,
        )

        stored_profile = uow.index_profiles.add(profile, index_id=identity.id)
        stored_constituent = uow.index_constituent_snapshots.add(
            constituent_snapshot, index_id=identity.id
        )
        stored_mapping = uow.etf_index_mappings.add(rebuilt_mapping)
        stored_holding = uow.etf_holding_snapshots.add(holding_snapshot)

        uow.commit()

    return ExposurePersistResult(
        index_id=identity.id,
        profile_id=stored_profile.id,
        profile_content_hash=stored_profile.content_hash,
        constituent_snapshot_id=stored_constituent.id,
        constituent_content_hash=stored_constituent.content_hash,
        mapping_id=stored_mapping.id,
        mapping_content_hash=stored_mapping.content_hash,
        holding_snapshot_id=stored_holding.id,
        holding_content_hash=stored_holding.content_hash,
    )
