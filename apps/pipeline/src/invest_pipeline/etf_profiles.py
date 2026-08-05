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

from invest_domain.etf_profile import (
    EtfProfile,
    FieldKey,
    ResolutionStatus,
    resolve_etf_profile_evidence,
)
from invest_domain.instruments.models import InstrumentId
from invest_domain.market_data.models import ProviderAttemptStatus
from invest_storage import (
    NewProviderAttempt,
    NewProviderBatch,
    NewProviderRequest,
)
from invest_storage.unit_of_work import SessionProvider, SqlAlchemyUnitOfWork
from sqlalchemy.orm import sessionmaker

from invest_pipeline.adapters.akshare.mapper import (
    AkshareProfileMappingResult,
    AkshareProfileRecord,
    map_etf_profile_to_field_evidence,
)
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

# Per-provider default confidence carried on every
# ``FieldEvidence`` row produced by the AkShare ETF Profile
# snapshot. The downstream resolver / consumer reads this score
# alongside ``quality_status`` so it must be a finite ``Decimal``
# in ``[0, 1]`` (the domain validator enforces the range).
_AKSHARE_EVIDENCE_CONFIDENCE = Decimal("0.9")
_AKSHARE_EVIDENCE_REVISION = 1


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

    ``evidence_rows`` counts the
    :class:`invest_domain.etf_profile.models.FieldEvidence` rows the
    slice persisted through ``uow.etf_profile_fields`` for the same
    AkShare profile snapshot. The count is the total number of
    :class:`FieldEvidence` rows the mapper emitted (so a
    fully-populated two-record snapshot yields ``6`` — three evidence
    rows per record). The repository's ``ON CONFLICT (content_hash)
    DO NOTHING`` keeps the count stable across re-runs of identical
    business content; a fresh provider / revision would surface as a
    different ``content_hash`` and a fresh row.
    """

    inserted: int
    skipped: int
    evidence_rows: int = 0

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
                "shares": format(record.shares, "f") if record.shares is not None else None,
            }
            for record in records
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _profile_from_resolution(*, instrument_id: UUID, resolution: Any) -> EtfProfile:
    """Project only resolved evidence into the canonical profile view."""

    def value_for(field_key: FieldKey) -> Any:
        field = resolution.fields.get(field_key)
        if field is None or field.status is not ResolutionStatus.RESOLVED:
            return None
        return field.value

    return EtfProfile(
        instrument_id=instrument_id,
        manager=value_for(FieldKey.MANAGER),
        benchmark_index=value_for(FieldKey.BENCHMARK_INDEX),
        category=value_for(FieldKey.CATEGORY),
        inception_date=value_for(FieldKey.INCEPTION_DATE),
        fund_type=value_for(FieldKey.FUND_TYPE),
        management_fee=value_for(FieldKey.MANAGEMENT_FEE),
        custody_fee=value_for(FieldKey.CUSTODY_FEE),
        aum=value_for(FieldKey.AUM),
        shares=value_for(FieldKey.SHARES),
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
        raise ValueError(f"profile records payload must be a dict, got {type(payload).__name__}")
    if payload.get("schema_version") != _RAW_RECORDS_SCHEMA_VERSION:
        raise ValueError(
            "unsupported profile records payload schema_version "
            f"{payload.get('schema_version')!r}; expected "
            f"{_RAW_RECORDS_SCHEMA_VERSION}"
        )
    raw_records = payload.get("records", [])
    if not isinstance(raw_records, list):
        raise ValueError(
            f"profile records payload 'records' must be a list, got {type(raw_records).__name__}"
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

        existing_attempts = uow.provider_attempts.list_by_request(stored_request.id, limit=1000)
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
                response_payload_sha256=batch.raw_payload_hash if batch is not None else "0" * 64,
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


def _sidecar_entry_to_profile_record(entry: dict[str, Any]) -> AkshareProfileRecord:
    """Reconstruct an :class:`AkshareProfileRecord` from a sidecar entry.

    The sidecar only carries the three verified fields
    (``fund_type`` / ``category`` / ``shares``) and the natural
    identifier pair (``symbol`` / ``exchange``). The reconstructed
    record feeds the existing PR-ETF-PROFILE-02 mapper
    (:func:`map_etf_profile_to_field_evidence`) so the slice
    reuses the same field-evidence vocabulary the mapper test suite
    pins. ``None`` for ``shares`` is preserved so the mapper can
    emit a :attr:`QualityStatus.MISSING` row on the
    :class:`FieldValueType.DECIMAL` slot.
    """

    shares_raw = entry.get("shares")
    shares_decimal: Decimal | None = None if shares_raw in (None, "") else Decimal(str(shares_raw))
    return AkshareProfileRecord(
        symbol=entry.get("symbol") or "",
        exchange=entry.get("exchange") or "",
        fund_type=entry.get("fund_type") or None,
        category=entry.get("category") or None,
        shares=shares_decimal,
    )


def _resolve_source_batch_id(
    uow: Any,
    *,
    attempt_id: UUID,
) -> UUID | None:
    """Return the latest ``raw.provider_batches.id`` for ``attempt_id``.

    The PR-ETF-PROFILE-01 ``FieldEvidenceSource`` carries a
    ``source_batch_id`` that pins each evidence row to the upstream
    audit batch. The slice resolves the batch from
    :meth:`invest_storage.repositories.SqlAlchemyProviderBatchRepository.list_by_attempt`
    and returns the most recent batch id (the storage layer orders
    batches by ``created_at DESC``). ``None`` is returned when the
    successful attempt produced no batch (a ``partial`` response) so
    the evidence row stays traceable to the attempt without a
    surrogate batch id.
    """

    batches = list(uow.provider_batches.list_by_attempt(attempt_id, limit=1))
    if not batches:
        return None
    return batches[0].id


def upsert_etf_profiles(
    session_factory: SessionProvider | sessionmaker[Any],
    *,
    provider_key: str = "akshare",
    dataset_key: str = _AKSHAKE_PROFILE_DATASET_KEY,
    request_key: str = _AKSHAKE_PROFILE_REQUEST_KEY,
    unit_of_work_factory: UnitOfWorkFactory = SqlAlchemyUnitOfWork,
) -> UpsertSummary:
    """Upsert standardized ETF profiles into ``core.etf_profiles`` and persist
    field-evidence rows into ``analytics.etf_profile_fields``.

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

    After the core ``core.etf_profiles`` upsert the slice
    additionally feeds the resolved records through the
    PR-ETF-PROFILE-02 mapper
    (:func:`invest_pipeline.adapters.akshare.mapper.map_etf_profile_to_field_evidence`)
    and persists the resulting
    :class:`invest_domain.etf_profile.models.FieldEvidence` rows
    through ``uow.etf_profile_fields``. The repository applies the
    idempotent ``ON CONFLICT (content_hash) DO NOTHING`` contract so
    a re-collect of identical business content keeps the audit
    table untouched while a different provider / revision (different
    ``content_hash``) lands as a coexisting row. The mapper carries
    the upstream ``source_batch_id`` (resolved from the latest
    ``raw.provider_batches`` row for the attempt), the attempt's
    ``finished_at`` as ``observed_at`` and the per-provider default
    ``confidence_score`` (0.9 for the AkShare ETF Profile snapshot).
    The mapper never emits ``AUM`` / ``MARKET_VALUE`` rows; only the
    three verified fields ``FUND_TYPE`` / ``CATEGORY`` / ``SHARES``
    ride on the evidence surface per the DC-2 conservative contract.

    Records that fail the ``(symbol, exchange) → core.instruments``
    lookup are skipped from both the core upsert and the field
    evidence pass so the field-evidence table never references an
    unknown instrument. Records missing ``symbol`` or ``exchange`` in
    the sidecar are likewise skipped.

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
        attempts = uow.provider_attempts.list_by_request(stored_request.id, limit=1000)
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
        evidence_records: list[AkshareProfileRecord] = []
        resolved_ids: dict[tuple[str, str], UUID] = {}
        for entry in records:
            symbol = entry.get("symbol")
            exchange = entry.get("exchange")
            if not symbol or not exchange:
                skipped += 1
                continue
            instrument = uow.instruments.get_by_business_key(exchange=exchange, symbol=symbol)
            if instrument is None or instrument.instrument_id is None:
                skipped += 1
                continue
            instrument_id_raw = instrument.instrument_id
            instrument_id_value = (
                instrument_id_raw.value
                if hasattr(instrument_id_raw, "value")
                else instrument_id_raw
            )
            evidence_records.append(_sidecar_entry_to_profile_record(entry))
            resolved_ids[(symbol, exchange)] = instrument_id_value
            inserted += 1

        evidence_rows = 0
        if evidence_records:
            profile_mapping = AkshareProfileMappingResult(
                records=tuple(evidence_records),
                warnings=(),
            )
            source_batch_id = _resolve_source_batch_id(uow, attempt_id=succeeded_attempt.id)
            observed_at = (
                succeeded_attempt.finished_at
                if succeeded_attempt.finished_at is not None
                else _now()
            )

            def _instrument_id_resolver(symbol: str, exchange: str) -> InstrumentId:
                key = (symbol, exchange)
                if key not in resolved_ids:
                    raise KeyError(f"no resolved instrument_id for ({symbol!r}, {exchange!r})")
                return InstrumentId(resolved_ids[key])

            evidence_mapping = map_etf_profile_to_field_evidence(
                profile_mapping,
                instrument_id_resolver=_instrument_id_resolver,
                source_batch_id=source_batch_id,
                observed_at=observed_at,
                confidence_score=_AKSHARE_EVIDENCE_CONFIDENCE,
                revision=_AKSHARE_EVIDENCE_REVISION,
            )
            for evidence in evidence_mapping.evidence:
                uow.etf_profile_fields.add(evidence)
                evidence_rows += 1

        for instrument_id in dict.fromkeys(resolved_ids.values()):
            evidence = uow.etf_profile_fields.get_by_instrument(instrument_id)
            resolution = resolve_etf_profile_evidence(evidence, instrument_id=instrument_id)
            uow.etf_profiles.upsert(
                _profile_from_resolution(instrument_id=instrument_id, resolution=resolution)
            )

        return UpsertSummary(
            inserted=inserted,
            skipped=skipped,
            evidence_rows=evidence_rows,
        )


PROFILE_RECORDS_SCHEMA_VERSION = _RAW_RECORDS_SCHEMA_VERSION
