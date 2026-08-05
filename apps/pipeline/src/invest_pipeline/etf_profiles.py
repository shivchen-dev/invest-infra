"""ETF Profile ETL service (DC-2 incremental slice).

The service module hosts the testable, asset-agnostic ETL logic for
the ``etf_profile`` vertical slice. The conservative AkShare-backed
profile collection joins ``fund_name_em`` (fund code / name / type)
and ``fund_etf_spot_em`` (ETF code / latest shares) by symbol in a
pure mapper; only the verified fields (``fund_type`` / ``category`` /
``shares``) are populated and the unfunded fields (``manager``,
``benchmark_index``, ``inception_date``, ``management_fee``,
``custody_fee``, ``aum``) stay ``None`` until a dedicated profile
endpoint is verified. The slice respects the existing plan rules:

- ``fund_etf_fund_info_em(fund=...)`` is a historical NAV endpoint and
  is **not** mapped to :class:`invest_domain.etf_profile.models.EtfProfile`;
  NAV stays on the dedicated ``fund_etf_fund_daily_em`` path.
- The ``fund_etf_spot_em`` ``总市值`` (total market value) column is
  **never** mapped to ``aum``; AUM is a Provider-disclosed figure,
  not a market-cap calculation.
- The current :class:`invest_domain.etf_profile.models.EtfProfile`
  contract does not accept a ``name`` field, so the ``基金简称`` /
  ``名称`` values are intentionally dropped in this slice.

Dagster assets are deliberately not added in this slice: the request
calls out a "no API/Web/Dagster asset" rule, so the ETL logic lives
purely in this module and the asset layer is reserved for a follow-up
increment.

Two transactions make up the slice:

- :func:`write_etf_profiles_raw` calls the Provider, persists the
  PR-02 three-layer evidence bundle to ``raw.provider_requests`` /
  ``raw.provider_attempts`` / ``raw.provider_batches``, and returns a
  :class:`RawEtlResult` (re-exported from
  :mod:`invest_pipeline.etf_instruments`) carrying the assigned UUIDs.
  The standardized profile records are serialised into a JSONB sidecar
  on the attempt's ``response_payload_json`` so the downstream
  upsert service can re-read them without re-calling the Provider.
  Failed attempts persist the request + attempt only; no batch row is
  created (per ``ck_provider_attempts_failed_has_error`` and the
  domain rule that a failed attempt must not yield a
  :class:`ProviderBatch`).
- :func:`upsert_etf_profiles` re-opens a fresh UoW, locates the
  latest successful attempt for the ``(provider_key,
  dataset_key="etf_profile", request_key="etf-profile")`` triplet,
  deserializes the sidecar, resolves the real
  ``core.instruments.id`` per ``(symbol, exchange)`` and upserts the
  standardized profiles into ``core.etf_profiles``. The repository
  applies the idempotent ``INSERT ... ON CONFLICT DO UPDATE`` contract
  so a re-collect of identical business content is a no-op.

Both functions accept a ``session_factory`` so unit tests can inject a
factory that hands out a :class:`unittest.mock.MagicMock` session —
the slice stays offline-friendly and CI never has to boot a real
database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from invest_domain.etf_profile import EtfProfile
from invest_domain.market_data.models import ProviderAttemptStatus
from invest_storage import (
    NewProviderAttempt,
    NewProviderBatch,
    NewProviderRequest,
)
from invest_storage.unit_of_work import SessionProvider, SqlAlchemyUnitOfWork
from sqlalchemy.orm import sessionmaker

from invest_pipeline.adapters.akshare.mapper import AkshareProfileRecord
from invest_pipeline.etf_instruments import (
    RawEtlResult,
    UnitOfWorkFactory,
    _coerce_session_factory,
)

__all__ = [
    "PROFILE_RECORDS_SCHEMA_VERSION",
    "RawEtlResult",
    "UpsertSummary",
    "upsert_etf_profiles",
    "write_etf_profiles_raw",
]

_RAW_RECORDS_SCHEMA_VERSION = 1
_AKSHAKE_PROFILE_DATASET_KEY = "etf_profile"
_AKSHAKE_PROFILE_REQUEST_KEY = "etf-profile"


@dataclass(frozen=True, slots=True)
class UpsertSummary:
    """Return shape of :func:`upsert_etf_profiles`.

    Distinguishes rows that the repository actually inserted
    (``inserted``) from rows that the ``INSERT ... ON CONFLICT DO
    UPDATE`` left untouched (``skipped``). The two counts sum to the
    number of profiles the Provider returned; a re-collect of
    identical content therefore reports ``inserted=0`` and
    ``skipped=record_count`` so the operator can see at a glance that
    the run was idempotent.
    """

    inserted: int
    skipped: int

    @property
    def total(self) -> int:
        return self.inserted + self.skipped


class _ProviderPort(Protocol):
    """Structural port for the ETF Profile Provider.

    Mirrors the subset of :class:`AkshareInstrumentProvider` the
    service depends on so a stub provider can be injected in unit
    tests. The ``fetch_etf_profile`` signature is intentionally
    slice-specific (no ``as_of`` date and no symbol list) — the
    upstream AkShare endpoints are full-universe snapshots, so the
    service treats the whole payload as one logical request.
    """

    @property
    def provider_key(self) -> str: ...

    def fetch_etf_profile(
        self,
    ) -> tuple[Any, Any, Any]: ...


def _now() -> datetime:
    return datetime.now(UTC)


def _build_records_json(records: tuple[AkshareProfileRecord, ...]) -> str:
    """Serialise the profile records into the JSONB sidecar.

    The sidecar carries the provider-native ``symbol`` and
    ``exchange`` (not the placeholder ``instrument_id``) so the
    application service can re-resolve the real
    ``core.instruments.id`` via ``(symbol, exchange)`` at upsert
    time. The schema version is part of the payload so future
    format changes can be detected; the optional nullable fields
    (``fund_type`` / ``category`` / ``shares``) are serialised as
    ``None`` when missing so the deserializer does not have to
    distinguish "missing" from "empty" at the JSON layer.
    """

    payload = {
        "schema_version": _RAW_RECORDS_SCHEMA_VERSION,
        "records": [
            {
                "symbol": record.symbol,
                "exchange": record.exchange,
                "fund_type": record.fund_type,
                "category": record.category,
                "shares": format(record.shares, "f")
                if record.shares is not None
                else None,
            }
            for record in records
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _record_to_etf_profile(
    *,
    record: dict[str, Any],
    instrument_id: UUID,
) -> EtfProfile:
    """Build one :class:`EtfProfile` from a sidecar record.

    The function tolerates missing / empty optional fields and
    maps them to ``None`` so the domain validator does not reject
    a partially-populated upstream row. The unfunded fields
    (``manager`` / ``benchmark_index`` / ``inception_date`` /
    ``management_fee`` / ``custody_fee`` / ``aum``) are deliberately
    left ``None`` per the slice's conservative contract.
    """

    shares_raw = record.get("shares")
    shares_decimal = (
        Decimal(str(shares_raw)) if shares_raw not in (None, "") else None
    )
    return EtfProfile(
        instrument_id=instrument_id,
        fund_type=record.get("fund_type") or None,
        category=record.get("category") or None,
        shares=shares_decimal,
    )


def _deserialize_records(
    payload_json: str | bytes | bytearray | None,
) -> list[dict[str, Any]]:
    """Inverse of :func:`_build_records_json`; used by the
    core-etf-profiles upsert.

    The parser is intentionally defensive: a missing or
    schema-version-mismatched payload returns an empty list so a
    stale raw row never crashes the downstream upsert.
    """

    if payload_json is None:
        return []
    if isinstance(payload_json, (bytes, bytearray)):
        payload_json = payload_json.decode("utf-8")
    payload = json.loads(payload_json)
    if not isinstance(payload, dict):
        raise ValueError(
            f"profile records payload must be a dict, got {type(payload).__name__}"
        )
    if payload.get("schema_version") != _RAW_RECORDS_SCHEMA_VERSION:
        raise ValueError(
            "unsupported profile records payload schema_version "
            f"{payload.get('schema_version')!r}; expected "
            f"{_RAW_RECORDS_SCHEMA_VERSION}"
        )
    raw_records = payload.get("records", [])
    if not isinstance(raw_records, list):
        raise ValueError(
            "profile records payload 'records' must be a list, "
            f"got {type(raw_records).__name__}"
        )
    return [dict(entry) for entry in raw_records if isinstance(entry, dict)]


def write_etf_profiles_raw(
    provider: _ProviderPort,
    session_factory: SessionProvider | sessionmaker[Any],
    *,
    unit_of_work_factory: UnitOfWorkFactory = SqlAlchemyUnitOfWork,
) -> RawEtlResult:
    """Run the PR-02 three-layer evidence write for ETF profiles.

    The function persists the ``(ProviderRequest, ProviderAttempt,
    ProviderBatch)`` triple returned by ``provider.fetch_etf_profile``
    in order so the FK wiring on ``provider_attempts`` and
    ``provider_batches`` resolves against the storage-assigned UUIDs.
    The standardized profile records are serialised into a JSONB
    sidecar on the attempt's ``response_payload_json`` so the
    downstream upsert service can re-read them without re-calling the
    Provider. The logical request is resolved through
    :meth:`SqlAlchemyProviderRequestRepository.get_or_create` so a
    re-run of the same ``(provider_key, dataset_key, request_key)``
    reuses the existing ``raw.provider_requests`` row instead of
    triggering the ``uq_provider_requests_logical_key`` constraint;
    a fresh attempt (and batch, when appropriate) is still recorded
    so the audit trail captures the rerun.

    Failure semantics (mirrors
    :func:`invest_pipeline.etf_instruments.write_etf_instruments_raw`):

    - ``ProviderAttempt.status == FAILED`` → only the request (status
      ``failed``) and the attempt (status ``failed`` with mandatory
      ``error_stage`` / ``error_code``) are persisted. No batch row is
      created.
    - ``ProviderAttempt.status == SUCCEEDED`` and a non-``None`` batch
      → the request, the attempt and the batch are all persisted. The
      attempt's ``response_payload_json`` carries the sidecar.
    - ``ProviderAttempt.status == SUCCEEDED`` and ``batch is None`` →
      the request and attempt are persisted with status ``partial``;
      no batch is created.
    """

    request, attempt, batch = provider.fetch_etf_profile()
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


def upsert_etf_profiles(
    session_factory: SessionProvider | sessionmaker[Any],
    *,
    provider_key: str = "akshare",
    dataset_key: str = _AKSHAKE_PROFILE_DATASET_KEY,
    request_key: str = _AKSHAKE_PROFILE_REQUEST_KEY,
    unit_of_work_factory: UnitOfWorkFactory = SqlAlchemyUnitOfWork,
) -> UpsertSummary:
    """Upsert standardized ETF profiles into ``core.etf_profiles``.

    The function locates the latest successful attempt for the
    ``(provider_key, dataset_key, request_key)`` triplet, deserializes
    the sidecar, looks up the real ``core.instruments.id`` per
    ``(symbol, exchange)`` and delegates to
    :meth:`invest_storage.repositories.SqlAlchemyEtfProfileRepository.
    upsert`. The repository applies the idempotent ``INSERT ... ON
    CONFLICT DO UPDATE`` contract so a re-collect of identical business
    content is a no-op.

    "Latest" is resolved client-side by the maximum ``finished_at``
    across the persisted ``succeeded`` attempts (with ``attempt_no``
    as a deterministic tiebreaker) — the storage layer's
    ``attempt_no ASC`` ordering plus a naive ``next(...)`` would
    otherwise pick the OLDEST succeeded attempt, which silently
    surfaces a stale ``akshare`` sidecar when an old baseline attempt
    co-exists with a fresh run for the same logical request.
    ``LookupError`` is raised if no successful attempt is found for
    the given logical key so a stale downstream trigger is surfaced
    loudly rather than silently producing zero rows.

    The function tolerates missing sidecar records (e.g. an empty
    AkShare response) and returns ``UpsertSummary(0, 0)`` so the
    downstream schedule does not fail on a quiet Provider window.
    """

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
                "run etf_profiles_raw first"
            )
        attempts = uow.provider_attempts.list_by_request(
            stored_request.id, limit=1000
        )
        succeeded_attempts = [a for a in attempts if a.status == "succeeded"]
        if not succeeded_attempts:
            raise LookupError(
                f"no succeeded provider_attempts row for request "
                f"{stored_request.id}; etf_profiles_raw must have "
                "persisted a successful attempt first"
            )
        succeeded_attempt = max(
            succeeded_attempts,
            key=lambda a: (a.finished_at, a.attempt_no),
        )

        records = _deserialize_records(succeeded_attempt.response_payload_json)
        if not records:
            return UpsertSummary(inserted=0, skipped=0)

        inserted = 0
        skipped = 0
        for entry in records:
            symbol = entry.get("symbol")
            exchange = entry.get("exchange")
            if not symbol or not exchange:
                skipped += 1
                continue
            instrument = uow.instruments.get_by_business_key(
                exchange=exchange, symbol=symbol
            )
            if instrument is None or instrument.instrument_id is None:
                skipped += 1
                continue
            instrument_id_raw = instrument.instrument_id
            instrument_id_value = (
                instrument_id_raw.value
                if hasattr(instrument_id_raw, "value")
                else instrument_id_raw
            )
            profile = _record_to_etf_profile(
                record=entry,
                instrument_id=instrument_id_value,
            )
            uow.etf_profiles.upsert(profile)
            inserted += 1
        return UpsertSummary(inserted=inserted, skipped=skipped)


PROFILE_RECORDS_SCHEMA_VERSION = _RAW_RECORDS_SCHEMA_VERSION
