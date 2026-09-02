"""ETF master-data ETL service (PR-05).

The service module hosts the testable, asset-agnostic ETL logic for
the ``etf_instruments`` vertical slice. Dagster assets in
:mod:`invest_pipeline.assets` are thin wrappers that wire the
``FixtureDevInstrumentProvider`` and the configured
:class:`SqlAlchemyUnitOfWork` into these functions.

Two transactions make up the slice:

- :func:`write_etf_instruments_raw` calls the Provider, persists the
  PR-02 three-layer evidence bundle to ``raw.provider_requests`` /
  ``raw.provider_attempts`` / ``raw.provider_batches``, and returns a
  :class:`RawEtlResult` carrying the assigned UUIDs.
  Failed attempts persist the request + attempt only; no batch row is
  created (per ``ck_provider_attempts_failed_has_error`` and the
  domain rule that a failed attempt must not yield a
  :class:`ProviderBatch`).
- :func:`upsert_etf_instruments` re-opens a fresh UoW, locates the
  latest successful attempt for the (provider, dataset, request_key)
  triplet, deserializes the records from the attempt's
  ``response_payload_json`` sidecar, and upserts them into
  ``core.instruments``. Upsert is idempotent on the partial unique
  business key ``(symbol, exchange) WHERE delist_date IS NULL``.

Both functions accept a ``session_factory`` so unit tests can inject a
factory that hands out a :class:`unittest.mock.MagicMock` session —
the asset-level integration is verified via the test suite without
booting a real database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol
from uuid import UUID

from invest_domain.instruments import Instrument
from invest_domain.market_data.models import (
    ProviderAttemptStatus,
)
from invest_storage import (
    NewProviderAttempt,
    NewProviderBatch,
    NewProviderRequest,
)
from invest_storage.unit_of_work import SessionProvider, SqlAlchemyUnitOfWork
from sqlalchemy.orm import sessionmaker

from invest_pipeline.adapters.fixture_dev.adapter import deserialize_records

_RAW_RECORDS_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class RawEtlResult:
    """Return shape of :func:`write_etf_instruments_raw`.

    Carries the storage-assigned UUIDs plus the terminal status of the
    attempt so the asset metadata can surface whether the batch was
    actually persisted or the attempt failed before producing one.
    """

    request_id: UUID
    attempt_id: UUID
    batch_id: UUID | None
    request_status: str
    attempt_status: str
    record_count: int
    error_code: str | None = None
    provider_key: str | None = None


class _ProviderPort(Protocol):
    """Structural port for the ETF instrument Provider.

    Mirrors the subset of :class:`FixtureDevInstrumentProvider` the
    service depends on so a stub provider can be injected in unit
    tests.
    """

    @property
    def provider_key(self) -> str: ...

    def fetch_instruments(
        self, as_of: date
    ) -> tuple[
        Any, Any, Any
    ]: ...


UnitOfWorkFactory = Any


def _coerce_session_factory(
    session_factory: SessionProvider | sessionmaker[Any],
) -> sessionmaker[Any]:
    """Return a ``sessionmaker`` regardless of the caller-supplied shape.

    The public API accepts either a :class:`SessionProvider` callable
    or a SQLAlchemy ``sessionmaker``; both are accepted by
    :class:`SqlAlchemyUnitOfWork`, but the type checker is happier when
    we narrow to a single shape.
    """

    return session_factory  # type: ignore[return-value]


def _now() -> datetime:
    return datetime.now(UTC)


def _build_records_json(records: tuple[Instrument, ...]) -> str:
    """Serialize ``records`` to the JSONB sidecar the core asset reads back."""

    payload = {
        "schema_version": _RAW_RECORDS_SCHEMA_VERSION,
        "records": [
            {
                "symbol": item.symbol,
                "name": item.name,
                "exchange": item.exchange,
                "instrument_type": item.instrument_type.value,
                "currency": item.currency.value,
                "list_date": item.list_date.isoformat() if item.list_date else None,
                "delist_date": (
                    item.delist_date.isoformat() if item.delist_date else None
                ),
                "status": item.status.value,
                "underlying_index": item.underlying_index,
                "category": item.category,
            }
            for item in records
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def write_etf_instruments_raw(
    provider: _ProviderPort,
    session_factory: SessionProvider | sessionmaker[Any],
    *,
    as_of: date,
    unit_of_work_factory: UnitOfWorkFactory = SqlAlchemyUnitOfWork,
) -> RawEtlResult:
    """Run the PR-02 three-layer evidence write for ETF master data.

    The function persists the ``(ProviderRequest, ProviderAttempt,
    ProviderBatch)`` triple returned by ``provider.fetch_instruments``
    in order so the FK wiring on ``provider_attempts`` and
    ``provider_batches`` resolves against the storage-assigned UUIDs.
    The logical request is resolved through
    :meth:`SqlAlchemyProviderRequestRepository.get_or_create` so a
    re-run of the same ``(provider_key, dataset_key, request_key)``
    reuses the existing ``raw.provider_requests`` row instead of
    triggering the ``uq_provider_requests_logical_key`` constraint;
    a fresh attempt (and batch, when appropriate) is still recorded
    so the audit trail captures the rerun.

    Failure semantics:

    - ``ProviderAttempt.status == FAILED`` → only the request (status
      ``failed``) and the attempt (status ``failed`` with mandatory
      ``error_stage`` / ``error_code``) are persisted. No batch row is
      created, mirroring the domain contract that a failed attempt
      leaves no batch behind.
    - ``ProviderAttempt.status == SUCCEEDED`` and a non-``None`` batch
      → the request (status ``succeeded``), the attempt (status
      ``succeeded`` with ``response_payload_sha256`` and the records
      sidecar in ``response_payload_json``) and the batch are all
      persisted.
    - ``ProviderAttempt.status == SUCCEEDED`` and ``batch is None`` →
      the request and attempt are persisted with status ``partial``;
      no batch is created.
    """

    request, attempt, batch = provider.fetch_instruments(as_of)
    finished_at = attempt.finished_at or _now()

    factory = _coerce_session_factory(session_factory)
    with unit_of_work_factory(factory) as uow:
        stored_request = uow.provider_requests.get_or_create(
            NewProviderRequest(
                provider_key=request.provider_key,
                dataset_key=request.dataset_key,
                request_key=request.request_key,
                status="pending",
                request_params=dict(request.params),
            )
        )

        existing_attempts = uow.provider_attempts.list_by_request(
            stored_request.id, limit=1000
        )
        next_attempt_no = (
            max(a.attempt_no for a in existing_attempts) + 1
            if existing_attempts
            else attempt.attempt_number
        )

        if attempt.status is ProviderAttemptStatus.FAILED:
            stored_attempt = uow.provider_attempts.add(
                NewProviderAttempt(
                    provider_request_id=stored_request.id,
                    attempt_no=next_attempt_no,
                    started_at=attempt.started_at,
                    finished_at=finished_at,
                    status="failed",
                    error_stage=attempt.error_stage.value
                    if attempt.error_stage is not None
                    else "provider",
                    error_code=attempt.error_code or "unknown_error",
                    error_message=attempt.error_message,
                )
            )
            uow.provider_requests.mark_status(
                stored_request.id, status="failed", completed_at=finished_at
            )
            return RawEtlResult(
                request_id=stored_request.id,
                attempt_id=stored_attempt.id,
                batch_id=None,
                request_status="failed",
                attempt_status="failed",
                record_count=0,
            )

        response_payload_json = (
            _build_records_json(tuple(batch.records)) if batch is not None else None
        )
        stored_attempt = uow.provider_attempts.add(
            NewProviderAttempt(
                provider_request_id=stored_request.id,
                attempt_no=next_attempt_no,
                started_at=attempt.started_at,
                finished_at=finished_at,
                status="succeeded",
                response_payload_sha256=batch.raw_payload_hash
                if batch is not None
                else "0" * 64,
                response_payload_json=response_payload_json,
            )
        )

        stored_batch_id: UUID | None = None
        record_count = 0
        request_status = "succeeded"
        if batch is not None:
            stored_batch = uow.provider_batches.add(
                NewProviderBatch(
                    provider_request_id=stored_request.id,
                    provider_attempt_id=stored_attempt.id,
                    provider_key=request.provider_key,
                    dataset_key=request.dataset_key,
                    record_count=len(batch.records),
                    payload_sha256=batch.raw_payload_hash,
                    status=batch.status.value,
                    warnings=list(batch.warnings),
                )
            )
            stored_batch_id = stored_batch.id
            record_count = len(batch.records)
        else:
            request_status = "partial"

        uow.provider_requests.mark_status(
            stored_request.id,
            status=request_status,
            completed_at=finished_at,
        )
        return RawEtlResult(
            request_id=stored_request.id,
            attempt_id=stored_attempt.id,
            batch_id=stored_batch_id,
            request_status=request_status,
            attempt_status="succeeded",
            record_count=record_count,
        )


def upsert_etf_instruments(
    session_factory: SessionProvider | sessionmaker[Any],
    *,
    as_of: date,
    provider_key: str = "fixture_dev",
    dataset_key: str = "etf_instruments",
    unit_of_work_factory: UnitOfWorkFactory = SqlAlchemyUnitOfWork,
) -> int:
    """Upsert standardized ETF instruments into ``core.instruments``.

    The function locates the latest successful attempt for
    ``(provider_key, dataset_key="etf_instruments",
    request_key=instruments-{as_of})``, deserializes the records from
    the attempt's ``response_payload_json`` sidecar, and delegates to
    :meth:`SqlAlchemyInstrumentRepository.upsert_many`.

    ``dataset_key="etf_instruments"`` is the formal ``raw.*`` key the
    ETF instrument providers (fixture_dev, cifangquant, ...) must
    stamp on the persisted request. Sharing a single key across
    providers keeps the upstream :func:`etf_instruments_raw` write
    path and this downstream upsert path aligned on one logical
    dataset so real CifangQuant runs (e.g. the 862 master-data rows
    on the formal API) flow into ``core.instruments`` instead of
    silently being skipped by a stale ``"instruments"`` lookup.

    Returns the number of instruments passed to the repository (which
    is the number of standardized records the batch carried). Raises
    :class:`LookupError` if no successful attempt is found for the
    given logical key so a stale downstream trigger is surfaced loudly
    rather than silently producing zero rows.
    """

    request_key = f"instruments-{as_of.isoformat()}"
    factory = _coerce_session_factory(session_factory)
    with unit_of_work_factory(factory) as uow:
        stored_request = uow.provider_requests.get_by_logical_key(
            provider_key=provider_key,
            dataset_key=dataset_key,
            request_key=request_key,
        )
        if stored_request is None:
            raise LookupError(
                f"no provider_requests row for "
                f"({provider_key!r}, {dataset_key!r}, {request_key!r}); "
                "run etf_instruments_raw first"
            )
        attempts = uow.provider_attempts.list_by_request(
            stored_request.id, limit=10
        )
        succeeded_attempt = next(
            (a for a in attempts if a.status == "succeeded"), None
        )
        if succeeded_attempt is None:
            raise LookupError(
                f"no succeeded provider_attempts row for request {stored_request.id}; "
                "etf_instruments_raw must have persisted a successful attempt first"
            )
        records = deserialize_records(succeeded_attempt.response_payload_json)
        if not records:
            return 0
        return uow.instruments.upsert_many(records)


__all__ = [
    "RawEtlResult",
    "upsert_etf_instruments",
    "write_etf_instruments_raw",
]
