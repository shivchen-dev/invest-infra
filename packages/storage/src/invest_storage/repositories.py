"""Repository implementations for the M1 Storage layer.

Each repository owns its ORM-to-domain mapping: callers always receive
domain objects, never SQLAlchemy ORM rows.

PR-02 introduced the three-layer evidence model in
``raw.provider_requests`` / ``raw.provider_attempts`` /
``raw.provider_batches`` (see ADR-0003 §6). The repositories in this
module cover:

- :class:`SqlAlchemyInstrumentRepository` — canonical
  ``core.instruments`` rows. The partial unique index on
  ``(symbol, exchange) WHERE delist_date IS NULL`` is the natural
  business-key upsert target.
- :class:`SqlAlchemyProviderRequestRepository` — one row per logical
  request, identified by ``(provider_key, dataset_key, request_key)``.
  :meth:`get_or_create` is the idempotent entry point used by the
  application service.
- :class:`SqlAlchemyProviderAttemptRepository` — one row per
  network/SDK attempt; carries lifecycle status and error metadata.
  :meth:`start` opens an attempt, :meth:`mark_succeeded` /
  :meth:`mark_failed` close it.
- :class:`SqlAlchemyProviderBatchRepository` — one row per
  successful/partial batch. Inserted only when the parent attempt
  succeeded or partially succeeded.
- :class:`SqlAlchemyPipelineRunRepository` — one row per execution of
  a pipeline job in ``ops.pipeline_runs``.
- :class:`SqlAlchemyCandidatePoolRunRepository` — one row per
  candidate-pool calculation in ``analytics.candidate_pool_runs``.
  Drives the legal state-machine transitions through
  :meth:`invest_domain.candidate_pool.models.CandidatePoolRun.transition_to`.
- :class:`SqlAlchemyCandidatePoolItemRepository` — per-instrument
  judgments belonging to a run, persisted in
  ``analytics.candidate_pool_items``.
- :class:`SqlAlchemyEvidencePackRepository` — Phase 2B persistence
  closure for ``analytics.research_evidence_packs``. Idempotent on
  ``content_hash``; the database ``research_case_id`` FK is the
  authoritative case link; no update / delete surface because packs
  are immutable.
- :class:`SqlAlchemyEtfProfileFieldRepository` — per-field evidence
  rows persisted in ``analytics.etf_profile_fields`` with the
  ``content_hash`` natural key as the idempotency contract.

Each domain-side dataclass is free of SQLAlchemy machinery, so
application / domain code can pass them around without importing the
storage layer.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)
from invest_domain.candidate_pool.models import (
    CandidatePoolItem,
    CandidatePoolRun,
    CandidatePoolStatus,
    ExclusionReason,
    RuleOutcome,
    RuleSeverity,
)
from invest_domain.etf_profile import (
    EtfProfile,
    FieldEvidence,
    FieldEvidenceSource,
    FieldKey,
    FieldValueType,
)
from invest_domain.exposure import (
    EtfHolding,
    EtfHoldingSnapshot,
    EtfIndexMapping,
    ExposureProvenance,
    IndexConstituent,
    IndexConstituentSnapshot,
    IndexProfile,
)
from invest_domain.input_snapshot import InputSnapshot
from invest_domain.instruments import (
    Instrument,
    InstrumentId,
    InstrumentStatus,
    InstrumentType,
)
from invest_domain.market_data.models import DailyBar
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_domain.pipeline import PipelineRun, PipelineRunStatus
from invest_domain.research import (
    ContextItem,
    ContextValueType,
    EvidencePack,
    QualityStatus,
    ResearchCase,
    ResearchCaseStatus,
    ResearchContextPack,
)
from invest_domain.research.evidence_bundle import (
    MarketSnapshotRef,
    ResearchEvidenceBundle,
)
from invest_domain.research.models import FreshnessStatus
from invest_domain.research.research_run import (
    ResearchResult,
    ResearchRun,
    ResearchRunStatus,
)
from invest_domain.shared.values import Currency
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from invest_storage.evidence_pack_codec import (
    coerce_optional_uuid,
    evidence_pack_to_payload,
    row_to_evidence_pack,
)
from invest_storage.models import (
    CandidatePoolItemRow,
    CandidatePoolRunRow,
    DailyBarRow,
    EtfHoldingRow,
    EtfHoldingSnapshotRow,
    EtfIndexMappingRow,
    EtfProfileFieldRow,
    EtfProfileRow,
    IndexConstituentRow,
    IndexConstituentSnapshotRow,
    IndexIdentityRow,
    IndexProfileRow,
    InputSnapshotRow,
    InstrumentRow,
    MarketObservationRow,
    MarketObservationSnapshotRow,
    PipelineRunRow,
    ProviderAttemptRow,
    ProviderRequestRow,
    RawProviderBatchRow,
    ResearchCaseRow,
    ResearchContextItemRow,
    ResearchContextPackRow,
    ResearchEvidenceBundleRow,
    ResearchEvidencePackRow,
    ResearchResultRow,
    ResearchRunRow,
)


@dataclass(frozen=True, slots=True)
class StoredProviderRequest:
    """Domain-side view of a persisted ``raw.provider_requests`` row."""

    id: UUID
    provider_key: str
    dataset_key: str
    request_key: str
    request_params: dict[str, Any] = field(default_factory=dict)
    requested_by_run_id: UUID | None = None
    status: str = "pending"
    created_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewProviderRequest:
    """Input shape for :meth:`SqlAlchemyProviderRequestRepository.add`."""

    provider_key: str
    dataset_key: str
    request_key: str
    status: str = "pending"
    request_params: dict[str, Any] = field(default_factory=dict)
    requested_by_run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class StoredProviderAttempt:
    """Domain-side view of a persisted ``raw.provider_attempts`` row."""

    id: UUID
    provider_request_id: UUID
    attempt_no: int
    provider_request_id_text: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str = "running"
    http_status: int | None = None
    error_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    response_payload_sha256: str | None = None
    response_payload_json: Any | None = None
    response_payload_uri: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewProviderAttempt:
    """Input shape for :meth:`SqlAlchemyProviderAttemptRepository.add`."""

    provider_request_id: UUID
    attempt_no: int
    started_at: datetime
    status: str = "running"
    provider_request_id_text: str | None = None
    finished_at: datetime | None = None
    http_status: int | None = None
    error_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    response_payload_sha256: str | None = None
    response_payload_json: Any | None = None
    response_payload_uri: str | None = None


@dataclass(frozen=True, slots=True)
class StoredProviderBatch:
    """Domain-side view of a persisted ``raw.provider_batches`` row."""

    id: UUID
    provider_request_id: UUID
    provider_attempt_id: UUID
    provider_key: str
    dataset_key: str
    record_count: int
    payload_sha256: str
    warnings: list[Any] = field(default_factory=list)
    status: str = "succeeded"
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewProviderBatch:
    """Input shape for :meth:`SqlAlchemyProviderBatchRepository.add`.

    ``provider_request_id`` and ``provider_attempt_id`` are mandatory FKs
    pointing to the parent request and attempt rows; the application
    service persists them in order (request → attempt → batch) and
    threads the assigned UUIDs through.
    """

    provider_request_id: UUID
    provider_attempt_id: UUID
    provider_key: str
    dataset_key: str
    record_count: int
    payload_sha256: str
    status: str = "succeeded"
    warnings: list[Any] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StoredDailyBar:
    """Domain-side view of a persisted ``core.daily_bars`` row.

    Carries every field the :class:`invest_domain.market_data.models.DailyBar`
    needs to be reconstructed, plus the storage-assigned ``id`` and
    server-generated ``created_at``. ``row_hash`` is the deterministic
    business-content digest the domain validated at construction time;
    callers that want a full :class:`DailyBar` instance should rebuild it
    through :meth:`DailyBar.build` so the domain invariants run again
    on the round-trip.
    """

    id: UUID
    instrument_id: UUID
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    prev_close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    adjustment: str
    trading_status: str
    source_provider: str
    source_batch_id: UUID | None
    observed_at: datetime
    revision: int
    row_hash: str
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewDailyBar:
    """Input shape for :meth:`SqlAlchemyDailyBarRepository.upsert_many`.

    The caller is responsible for validating the OHLCV business content
    through :class:`invest_domain.market_data.models.DailyBar` before
    handing the bar to the repository; this dataclass is the
    "transport" shape the application service uses. ``revision`` on
    the input is taken as ``1`` and the repository may bump it to
    ``latest + 1`` when the business content has actually changed (see
    ADR-0006 §3).
    """

    instrument_id: UUID
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
    source_provider: str
    source_batch_id: UUID | None
    observed_at: datetime
    row_hash: str


@dataclass(frozen=True, slots=True)
class NewEtfProfileField:
    """Input shape for :meth:`SqlAlchemyEtfProfileFieldRepository.add`.

    ``PR-ETF-PROFILE-04`` lifts the domain-side
    :class:`invest_domain.etf_profile.models.FieldEvidence` into a
    storage-aware transport dataclass so the application service can
    build one without depending on the SQLAlchemy ORM row. The
    ``content_hash`` field is the deterministic business-content digest
    computed by the domain dataclass; the repository treats it as the
    natural idempotency key so re-collects of the same observation are
    a no-op while a different provider / revision (different
    ``content_hash``) is stored as a coexisting row.

    The runtime value is stored in one of three discriminated columns
    depending on ``value_type``: ``TEXT`` ↔ ``field_value_text``,
    ``DECIMAL`` ↔ ``field_value_numeric``, ``DATE`` ↔
    ``field_value_date``. Callers MUST populate exactly the column
    matching ``value_type`` and leave the other two ``None``; the
    database CHECK constraints flag any mismatch.
    """

    instrument_id: UUID
    field_key: FieldKey
    value_type: FieldValueType
    field_value_text: str | None = None
    field_value_numeric: Decimal | None = None
    field_value_date: date | None = None
    source_provider: str = ""
    source_dataset: str = ""
    observed_at: datetime | None = None
    source_batch_id: UUID | None = None
    source_revision: int = 1
    quality_status: str = "complete"
    confidence_score: Decimal | None = None
    content_hash: str = ""


@dataclass(frozen=True, slots=True)
class StoredEtfProfileField:
    """Domain-side view of a persisted ``analytics.etf_profile_fields`` row.

    Returns the same :class:`FieldEvidence` shape the domain layer
    expects so callers can use the field-evidence vocabulary end to
    end without re-mapping column names. ``id`` is the storage-assigned
    UUID, ``created_at`` is the server-generated audit timestamp and
    the three value columns are collapsed into the single ``value``
    slot on ``FieldEvidence`` based on ``value_type``.
    """

    id: UUID
    instrument_id: UUID
    field_key: FieldKey
    value_type: FieldValueType
    field_value_text: str | None
    field_value_numeric: Decimal | None
    field_value_date: date | None
    source_provider: str
    source_dataset: str
    observed_at: datetime
    source_batch_id: UUID | None
    source_revision: int
    quality_status: str
    confidence_score: Decimal | None
    content_hash: str
    created_at: datetime | None = None


class SqlAlchemyInstrumentRepository:
    """CRUD + UUID upsert for the canonical ``core.instruments`` table.

    The repository is stateless apart from its session: callers obtain a
    fresh repository per UnitOfWork so the session lifetime is owned by
    the UoW (or by the caller of :func:`invest_storage.database.session_scope`).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, instruments: Sequence[Instrument]) -> int:
        """Insert or update a batch of instruments; returns the count.

        Instruments carrying an explicit ``instrument_id`` are upserted by
        primary key (so an explicit re-import can rewrite the row). The
        remainder are upserted by the partial unique business key
        ``(symbol, exchange) WHERE delist_date IS NULL`` - re-imports of
        an existing active instrument keep the original ``id``.
        """

        if not instruments:
            return 0

        with_id: list[Instrument] = []
        without_id: list[Instrument] = []
        for item in instruments:
            if item.instrument_id is None:
                without_id.append(item)
            else:
                with_id.append(item)

        total = 0
        if with_id:
            total += self._upsert_by_id(with_id)
        if without_id:
            total += self._upsert_by_business_key(without_id)
        return total

    def get_by_id(self, instrument_id: UUID | InstrumentId) -> Instrument | None:
        raw_id = instrument_id.value if isinstance(instrument_id, InstrumentId) else instrument_id
        row = self._session.get(InstrumentRow, raw_id)
        return _row_to_instrument(row) if row is not None else None

    def get_many_by_ids(
        self, instrument_ids: Sequence[UUID | InstrumentId]
    ) -> dict[UUID, Instrument]:
        """Bulk lookup instruments by ``instrument_id``.

        Returns a dict keyed by the raw ``UUID`` containing only the rows
        that were found; ``instrument_ids`` that are missing from
        ``core.instruments`` are silently omitted so the caller can
        degrade to ``None`` display fields instead of failing the whole
        read path. An empty ``instrument_ids`` yields an empty dict so
        the common "no items" path stays branch-free.
        """

        if not instrument_ids:
            return {}
        normalised: dict[UUID, None] = {}
        for value in instrument_ids:
            if isinstance(value, InstrumentId):
                normalised[value.value] = None
            elif isinstance(value, UUID):
                normalised[value] = None
            else:
                raise TypeError(
                    f"get_many_by_ids expects UUID or InstrumentId, got {type(value).__name__}"
                )
        rows = self._session.scalars(
            select(InstrumentRow).where(InstrumentRow.id.in_(normalised.keys()))
        ).all()
        return {row.id: _row_to_instrument(row) for row in rows}

    def get_by_business_key(self, *, exchange: str, symbol: str) -> Instrument | None:
        """Return the active instrument carrying the given business key.

        Uses the partial unique index on ``(symbol, exchange) WHERE
        delist_date IS NULL``; delisted rows are ignored. Returns
        ``None`` when no active row matches.
        """

        stmt = (
            select(InstrumentRow)
            .where(
                InstrumentRow.symbol == symbol,
                InstrumentRow.exchange == exchange,
                InstrumentRow.delist_date.is_(None),
            )
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_instrument(row) if row is not None else None

    def list_active(self, *, limit: int = 100, offset: int = 0) -> Sequence[Instrument]:
        rows = self._session.scalars(
            select(InstrumentRow)
            .where(InstrumentRow.is_active.is_(True))
            .order_by(InstrumentRow.exchange, InstrumentRow.symbol)
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_instrument(row) for row in rows]

    def count_active(self) -> int:
        stmt = select(InstrumentRow.id).where(InstrumentRow.is_active.is_(True))
        return len(self._session.scalars(stmt).all())

    def _upsert_by_id(self, instruments: Sequence[Instrument]) -> int:
        values = [
            {
                "id": item.instrument_id.value,  # type: ignore[union-attr]
                "symbol": item.symbol,
                "exchange": item.exchange,
                "name": item.name,
                "instrument_type": item.instrument_type.value,
                "currency": _currency_value(item.currency),
                "list_date": item.list_date,
                "delist_date": item.delist_date,
                "status": _status_value(item.status),
                "underlying_index": item.underlying_index,
                "category": item.category,
                "provider_symbol_map": _provider_symbol_map(item.provider_symbol_map),
                "valid_from": item.valid_from,
                "valid_to": item.valid_to,
                "is_active": item.is_active,
            }
            for item in instruments
        ]
        statement = insert(InstrumentRow).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[InstrumentRow.id],
            set_=_excluded_set(),
        )
        self._session.execute(statement)
        return len(values)

    def _upsert_by_business_key(self, instruments: Sequence[Instrument]) -> int:
        values = [
            {
                "id": uuid.uuid4(),
                "symbol": item.symbol,
                "exchange": item.exchange,
                "name": item.name,
                "instrument_type": item.instrument_type.value,
                "currency": _currency_value(item.currency),
                "list_date": item.list_date,
                "delist_date": item.delist_date,
                "status": _status_value(item.status),
                "underlying_index": item.underlying_index,
                "category": item.category,
                "provider_symbol_map": _provider_symbol_map(item.provider_symbol_map),
                "valid_from": item.valid_from,
                "valid_to": item.valid_to,
                "is_active": item.is_active,
            }
            for item in instruments
        ]
        statement = insert(InstrumentRow).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[InstrumentRow.symbol, InstrumentRow.exchange],
            index_where=InstrumentRow.delist_date.is_(None),
            set_=_excluded_set(),
        )
        self._session.execute(statement)
        return len(values)


class SqlAlchemyProviderRequestRepository:
    """Read/write access to ``raw.provider_requests``.

    A ``raw.provider_requests`` row is identified by the natural unique
    key ``(provider_key, dataset_key, request_key)``; the database
    enforces uniqueness. :meth:`get_or_create` is the idempotent entry
    point used by the application service when a logical request is
    re-issued: an existing row is returned untouched instead of raising
    :class:`sqlalchemy.exc.IntegrityError`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, request: NewProviderRequest) -> StoredProviderRequest:
        row = ProviderRequestRow(
            id=uuid.uuid4(),
            provider_key=request.provider_key,
            dataset_key=request.dataset_key,
            request_key=request.request_key,
            request_params=dict(request.request_params),
            requested_by_run_id=request.requested_by_run_id,
            status=request.status,
        )
        self._session.add(row)
        self._session.flush()
        return _row_to_stored_request(row)

    def get_by_id(self, request_id: UUID) -> StoredProviderRequest | None:
        row = self._session.get(ProviderRequestRow, request_id)
        return _row_to_stored_request(row) if row is not None else None

    def get_by_logical_key(
        self, *, provider_key: str, dataset_key: str, request_key: str
    ) -> StoredProviderRequest | None:
        stmt = (
            select(ProviderRequestRow)
            .where(
                ProviderRequestRow.provider_key == provider_key,
                ProviderRequestRow.dataset_key == dataset_key,
                ProviderRequestRow.request_key == request_key,
            )
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_stored_request(row) if row is not None else None

    def get_or_create(self, request: NewProviderRequest) -> StoredProviderRequest:
        existing = self.get_by_logical_key(
            provider_key=request.provider_key,
            dataset_key=request.dataset_key,
            request_key=request.request_key,
        )
        if existing is not None:
            return existing
        try:
            return self.add(request)
        except Exception:
            self._session.rollback()
            existing = self.get_by_logical_key(
                provider_key=request.provider_key,
                dataset_key=request.dataset_key,
                request_key=request.request_key,
            )
            if existing is not None:
                return existing
            raise

    def mark_status(
        self,
        request_id: UUID,
        *,
        status: str,
        completed_at: datetime | None = None,
    ) -> StoredProviderRequest:
        row = self._session.get(ProviderRequestRow, request_id)
        if row is None:
            raise LookupError(f"ProviderRequest {request_id!s} not found; cannot update status")
        row.status = status
        if completed_at is not None:
            row.completed_at = completed_at
        self._session.flush()
        return _row_to_stored_request(row)


class SqlAlchemyProviderAttemptRepository:
    """Read/write access to ``raw.provider_attempts``.

    The repository owns the lifecycle transitions for an attempt:
    :meth:`start` opens a new attempt in the ``running`` state,
    :meth:`mark_succeeded` / :meth:`mark_failed` close it. The database
    CHECK constraint ``ck_provider_attempts_succeeded_has_hash`` and
    ``ck_provider_attempts_failed_has_error`` enforce the contract that
    a successful attempt MUST carry a response SHA-256 and a failed
    attempt MUST carry ``error_stage`` and ``error_code``; the
    repository surfaces those violations via :class:`ValueError` /
    :class:`sqlalchemy.exc.IntegrityError`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, attempt: NewProviderAttempt) -> StoredProviderAttempt:
        row = ProviderAttemptRow(
            id=uuid.uuid4(),
            provider_request_id=attempt.provider_request_id,
            attempt_no=attempt.attempt_no,
            provider_request_id_text=attempt.provider_request_id_text,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            status=attempt.status,
            http_status=attempt.http_status,
            error_stage=attempt.error_stage,
            error_code=attempt.error_code,
            error_message=attempt.error_message,
            response_payload_sha256=attempt.response_payload_sha256,
            response_payload_json=attempt.response_payload_json,
            response_payload_uri=attempt.response_payload_uri,
        )
        self._session.add(row)
        self._session.flush()
        return _row_to_stored_attempt(row)

    def start(
        self,
        *,
        provider_request_id: UUID,
        attempt_no: int,
        started_at: datetime,
        provider_request_id_text: str | None = None,
    ) -> StoredProviderAttempt:
        """Open a new ``running`` attempt for the given request.

        Raises :class:`ValueError` if ``attempt_no < 1``; the database
        ``UNIQUE(provider_request_id, attempt_no)`` constraint will
        reject duplicate ``attempt_no`` values via
        :class:`sqlalchemy.exc.IntegrityError`.
        """

        if attempt_no < 1:
            raise ValueError(f"attempt_no must be >= 1, got {attempt_no}")
        return self.add(
            NewProviderAttempt(
                provider_request_id=provider_request_id,
                attempt_no=attempt_no,
                started_at=started_at,
                status="running",
                provider_request_id_text=provider_request_id_text,
            )
        )

    def mark_succeeded(
        self,
        attempt_id: UUID,
        *,
        finished_at: datetime,
        response_payload_sha256: str,
        response_payload_json: Any | None = None,
        response_payload_uri: str | None = None,
        http_status: int | None = None,
    ) -> StoredProviderAttempt:
        """Transition an attempt into the ``succeeded`` terminal state.

        ``response_payload_sha256`` is required by the database CHECK
        constraint. The repository raises :class:`ValueError` when the
        hash is empty so a meaningless record is never persisted.
        """

        if not response_payload_sha256 or not response_payload_sha256.strip():
            raise ValueError("mark_succeeded requires a non-empty response_payload_sha256")
        row = self._session.get(ProviderAttemptRow, attempt_id)
        if row is None:
            raise LookupError(f"ProviderAttempt {attempt_id!s} not found; cannot mark succeeded")
        row.status = "succeeded"
        row.finished_at = finished_at
        row.response_payload_sha256 = response_payload_sha256
        row.response_payload_json = response_payload_json
        row.response_payload_uri = response_payload_uri
        if http_status is not None:
            row.http_status = http_status
        self._session.flush()
        return _row_to_stored_attempt(row)

    def mark_failed(
        self,
        attempt_id: UUID,
        *,
        finished_at: datetime,
        error_stage: str,
        error_code: str,
        error_message: str | None = None,
        http_status: int | None = None,
    ) -> StoredProviderAttempt:
        """Transition an attempt into the ``failed`` terminal state.

        ``error_stage`` and ``error_code`` are required by the database
        CHECK constraint. The repository raises :class:`ValueError`
        when either is empty so a meaningless record is never persisted.
        """

        if not error_stage or not error_stage.strip():
            raise ValueError("mark_failed requires a non-empty error_stage")
        if not error_code or not error_code.strip():
            raise ValueError("mark_failed requires a non-empty error_code")
        row = self._session.get(ProviderAttemptRow, attempt_id)
        if row is None:
            raise LookupError(f"ProviderAttempt {attempt_id!s} not found; cannot mark failed")
        row.status = "failed"
        row.finished_at = finished_at
        row.error_stage = error_stage
        row.error_code = error_code
        row.error_message = error_message
        if http_status is not None:
            row.http_status = http_status
        self._session.flush()
        return _row_to_stored_attempt(row)

    def get_by_id(self, attempt_id: UUID) -> StoredProviderAttempt | None:
        row = self._session.get(ProviderAttemptRow, attempt_id)
        return _row_to_stored_attempt(row) if row is not None else None

    def list_by_request(
        self, request_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> Sequence[StoredProviderAttempt]:
        rows = self._session.scalars(
            select(ProviderAttemptRow)
            .where(ProviderAttemptRow.provider_request_id == request_id)
            .order_by(ProviderAttemptRow.attempt_no.asc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_stored_attempt(row) for row in rows]


class SqlAlchemyProviderBatchRepository:
    """Read/write access to ``raw.provider_batches``.

    Only successful/partial attempts produce a batch row. The repository
    does not enforce the ``status`` value set itself - the database
    CHECK constraint ``ck_provider_batches_status_valid`` rejects
    ``FAILED`` and any other out-of-vocabulary value. The FK constraints
    on ``provider_request_id`` and ``provider_attempt_id`` reject
    batches with missing parents via
    :class:`sqlalchemy.exc.IntegrityError`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, batch: NewProviderBatch) -> StoredProviderBatch:
        row = RawProviderBatchRow(
            id=uuid.uuid4(),
            provider_request_id=batch.provider_request_id,
            provider_attempt_id=batch.provider_attempt_id,
            provider_key=batch.provider_key,
            dataset_key=batch.dataset_key,
            record_count=batch.record_count,
            payload_sha256=batch.payload_sha256,
            warnings=list(batch.warnings),
            status=batch.status,
        )
        self._session.add(row)
        self._session.flush()
        return _row_to_stored_batch(row)

    def get_by_id(self, batch_id: UUID) -> StoredProviderBatch | None:
        row = self._session.get(RawProviderBatchRow, batch_id)
        return _row_to_stored_batch(row) if row is not None else None

    def list_by_attempt(
        self, attempt_id: UUID, *, limit: int = 10, offset: int = 0
    ) -> Sequence[StoredProviderBatch]:
        rows = self._session.scalars(
            select(RawProviderBatchRow)
            .where(RawProviderBatchRow.provider_attempt_id == attempt_id)
            .order_by(RawProviderBatchRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_stored_batch(row) for row in rows]

    def list_by_provider_dataset(
        self, *, provider_key: str, dataset_key: str, limit: int = 100, offset: int = 0
    ) -> Sequence[StoredProviderBatch]:
        rows = self._session.scalars(
            select(RawProviderBatchRow)
            .where(
                RawProviderBatchRow.provider_key == provider_key,
                RawProviderBatchRow.dataset_key == dataset_key,
            )
            .order_by(RawProviderBatchRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_stored_batch(row) for row in rows]


class SqlAlchemyDailyBarRepository:
    """Read/write access to ``core.daily_bars`` with ADR-0006 revision semantics.

    The repository owns the revision-allocation algorithm defined in
    ADR-0006 §3: a write only advances the revision when the incoming
    business content (as identified by ``row_hash``) differs from the
    latest persisted row for ``(instrument_id, trade_date, adjustment)``.
    Re-collects of the same business content are a no-op; the new
    ``raw.provider_batches`` row still records the audit trail but no
    additional ``core.daily_bars`` row is created.

    All write paths route through :meth:`upsert_many`; there is no
    single-row ``add`` so callers cannot accidentally bypass the
    row-hash comparison. The database-level ``UNIQUE (instrument_id,
    trade_date, adjustment, revision)`` constraint is the final
    concurrency guard, but the repository reads the latest revision
    inside the same UnitOfWork so the deterministic content comparison
    runs before the INSERT.

    A failed attempt does not produce a batch row, so the application
    service must NOT call :meth:`upsert_many` on the
    :class:`invest_domain.market_data.models.ProviderBatch` returned
    from a failed ``ProviderAttempt``. The pipeline asset enforces this
    by gating ``upsert_etf_daily_bars`` on the attempt status.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def _next_revision(
        self,
        *,
        instrument_id: UUID,
        trade_date: date,
        adjustment: Adjust,
    ) -> int:
        """Return the next ``revision`` number for the given logical key.

        The lookup is scoped to the current session so the read sees
        any rows added by :meth:`upsert_many` earlier in the same
        transaction (identity-map behaviour). Returns ``1`` when no
        row exists for the logical key.
        """

        current_max = self._session.execute(
            select(func.max(DailyBarRow.revision)).where(
                DailyBarRow.instrument_id == instrument_id,
                DailyBarRow.trade_date == trade_date,
                DailyBarRow.adjustment == adjustment.value,
            )
        ).scalar()
        return 1 if current_max is None else int(current_max) + 1

    def get_latest(
        self,
        *,
        instrument_id: UUID | InstrumentId,
        trade_date: date,
        adjustment: Adjust,
    ) -> StoredDailyBar | None:
        """Return the row with the highest ``revision`` for the logical key.

        Per ADR-0006 §6 this is the recommended read surface for new
        snapshot builders. The caller may also use
        :meth:`get_exact` to pin a specific revision for replay.
        """

        raw_id = instrument_id.value if isinstance(instrument_id, InstrumentId) else instrument_id
        row = self._session.execute(
            select(DailyBarRow)
            .where(
                DailyBarRow.instrument_id == raw_id,
                DailyBarRow.trade_date == trade_date,
                DailyBarRow.adjustment == adjustment.value,
            )
            .order_by(DailyBarRow.revision.desc())
            .limit(1)
        ).scalar_one_or_none()
        return _row_to_stored_daily_bar(row) if row is not None else None

    def get_exact(
        self,
        *,
        instrument_id: UUID | InstrumentId,
        trade_date: date,
        adjustment: Adjust,
        revision: int,
    ) -> StoredDailyBar | None:
        """Return the row at the exact ``revision`` for the logical key."""

        if revision < 1:
            raise ValueError(f"revision must be >= 1, got {revision}")
        raw_id = instrument_id.value if isinstance(instrument_id, InstrumentId) else instrument_id
        row = self._session.execute(
            select(DailyBarRow)
            .where(
                DailyBarRow.instrument_id == raw_id,
                DailyBarRow.trade_date == trade_date,
                DailyBarRow.adjustment == adjustment.value,
                DailyBarRow.revision == revision,
            )
            .limit(1)
        ).scalar_one_or_none()
        return _row_to_stored_daily_bar(row) if row is not None else None

    def list_by_instrument_and_range(
        self,
        *,
        instrument_id: UUID | InstrumentId,
        start_date: date,
        end_date: date,
        adjustment: Adjust,
    ) -> Sequence[StoredDailyBar]:
        """Return every revision of the bars in ``[start_date, end_date]``.

        The result includes all revisions of the matching
        ``(instrument_id, trade_date, adjustment)`` triplets, ordered
        by ``trade_date`` then ``revision`` ascending so the caller can
        group revisions in a single pass. :class:`Market` use cases
        that need "the latest revision per day" should feed the result
        through :meth:`get_latest` (per ADR-0006 §5); candidate-pool
        replay MUST NOT use this list directly.
        """

        if end_date < start_date:
            raise ValueError(
                f"end_date {end_date.isoformat()} must be on or after "
                f"start_date {start_date.isoformat()}"
            )
        raw_id = instrument_id.value if isinstance(instrument_id, InstrumentId) else instrument_id
        rows = (
            self._session.execute(
                select(DailyBarRow)
                .where(
                    DailyBarRow.instrument_id == raw_id,
                    DailyBarRow.trade_date >= start_date,
                    DailyBarRow.trade_date <= end_date,
                    DailyBarRow.adjustment == adjustment.value,
                )
                .order_by(
                    DailyBarRow.trade_date.asc(),
                    DailyBarRow.revision.asc(),
                )
            )
            .scalars()
            .all()
        )
        return [_row_to_stored_daily_bar(row) for row in rows]

    def list_latest_by_instrument_and_range(
        self,
        *,
        instrument_id: UUID | InstrumentId,
        start_date: date,
        end_date: date,
        adjustment: Adjust,
    ) -> Sequence[StoredDailyBar]:
        """Return the highest revision for each trade date in the inclusive range."""

        if end_date < start_date:
            raise ValueError(
                f"end_date {end_date.isoformat()} must be on or after "
                f"start_date {start_date.isoformat()}"
            )
        raw_id = instrument_id.value if isinstance(instrument_id, InstrumentId) else instrument_id
        latest_revisions = (
            select(
                DailyBarRow.trade_date.label("trade_date"),
                func.max(DailyBarRow.revision).label("revision"),
            )
            .where(
                DailyBarRow.instrument_id == raw_id,
                DailyBarRow.trade_date >= start_date,
                DailyBarRow.trade_date <= end_date,
                DailyBarRow.adjustment == adjustment.value,
            )
            .group_by(DailyBarRow.trade_date)
            .subquery()
        )
        rows = (
            self._session.execute(
                select(DailyBarRow)
                .join(
                    latest_revisions,
                    (DailyBarRow.trade_date == latest_revisions.c.trade_date)
                    & (DailyBarRow.revision == latest_revisions.c.revision),
                )
                .where(
                    DailyBarRow.instrument_id == raw_id,
                    DailyBarRow.adjustment == adjustment.value,
                )
                .order_by(DailyBarRow.trade_date.asc())
            )
            .scalars()
            .all()
        )
        return [_row_to_stored_daily_bar(row) for row in rows]

    def list_latest_by_instruments_and_range(
        self,
        *,
        instrument_ids: Sequence[UUID | InstrumentId],
        start_date: date,
        end_date: date,
        adjustment: Adjust,
    ) -> Sequence[StoredDailyBar]:
        """Return the highest revision per ``(instrument_id, trade_date)`` in range.

        Batch counterpart of :meth:`list_latest_by_instrument_and_range`. The
        ``[start_date, end_date]`` interval is inclusive on both ends. The
        result is ordered by ``instrument_id`` ascending then ``trade_date``
        ascending so the caller can chunk the output by instrument in a
        single pass without re-sorting.

        ``instrument_ids`` accepts both :class:`UUID` and
        :class:`invest_domain.instruments.InstrumentId`; duplicates are
        de-duplicated before the SQL is built so the ``IN`` clause stays
        small. An empty input sequence returns an empty sequence without
        touching the session - the common "no items" path stays
        branch-free in the caller.
        """

        if end_date < start_date:
            raise ValueError(
                f"end_date {end_date.isoformat()} must be on or after "
                f"start_date {start_date.isoformat()}"
            )
        if not instrument_ids:
            return []
        normalised: dict[UUID, None] = {}
        for value in instrument_ids:
            if isinstance(value, InstrumentId):
                normalised[value.value] = None
            elif isinstance(value, UUID):
                normalised[value] = None
            else:
                raise TypeError(
                    "list_latest_by_instruments_and_range expects UUID or "
                    f"InstrumentId, got {type(value).__name__}"
                )
        latest_revisions = (
            select(
                DailyBarRow.instrument_id.label("instrument_id"),
                DailyBarRow.trade_date.label("trade_date"),
                func.max(DailyBarRow.revision).label("revision"),
            )
            .where(
                DailyBarRow.instrument_id.in_(normalised.keys()),
                DailyBarRow.trade_date >= start_date,
                DailyBarRow.trade_date <= end_date,
                DailyBarRow.adjustment == adjustment.value,
            )
            .group_by(DailyBarRow.instrument_id, DailyBarRow.trade_date)
            .subquery()
        )
        rows = (
            self._session.execute(
                select(DailyBarRow)
                .join(
                    latest_revisions,
                    (DailyBarRow.instrument_id == latest_revisions.c.instrument_id)
                    & (DailyBarRow.trade_date == latest_revisions.c.trade_date)
                    & (DailyBarRow.revision == latest_revisions.c.revision),
                )
                .where(
                    DailyBarRow.instrument_id.in_(normalised.keys()),
                    DailyBarRow.adjustment == adjustment.value,
                )
                .order_by(
                    DailyBarRow.instrument_id.asc(),
                    DailyBarRow.trade_date.asc(),
                )
            )
            .scalars()
            .all()
        )
        return [_row_to_stored_daily_bar(row) for row in rows]

    def upsert_many(self, bars: Sequence[NewDailyBar | DailyBar]) -> list[StoredDailyBar]:
        """Persist ``bars`` into ``core.daily_bars`` under ADR-0006 revision rules.

        The algorithm follows ADR-0006 §3:

        - For each bar, look up the latest persisted row for the
          ``(instrument_id, trade_date, adjustment)`` logical key.
        - If no row exists, insert with ``revision = 1``.
        - If a row exists and its ``row_hash`` equals the incoming
          ``row_hash``, skip — the re-collect is a no-op at the core
          layer, only the ``raw.provider_batches`` audit row is added.
        - If a row exists and the hashes differ, insert with
          ``revision = latest + 1``.

        Returns the list of rows actually written (rows whose content
        matched the latest revision are NOT in the result). The order
        of the returned list mirrors the input order so callers can
        correlate ``upsert_many`` invocations with the original
        Provider batch.
        """

        if not bars:
            return []

        written: list[StoredDailyBar] = []
        for bar in bars:
            (instrument_id, trade_date, adjustment, payload) = _normalise_bar(bar)
            latest = self.get_latest(
                instrument_id=instrument_id,
                trade_date=trade_date,
                adjustment=adjustment,
            )
            if latest is not None and latest.row_hash == payload["row_hash"]:
                continue
            next_revision = self._next_revision(
                instrument_id=instrument_id,
                trade_date=trade_date,
                adjustment=adjustment,
            )
            row = DailyBarRow(
                id=uuid.uuid4(),
                instrument_id=instrument_id,
                trade_date=trade_date,
                open=payload["open"],
                high=payload["high"],
                low=payload["low"],
                close=payload["close"],
                prev_close=payload["prev_close"],
                volume=payload["volume"],
                amount=payload["amount"],
                adjustment=adjustment.value,
                trading_status=payload["trading_status"],
                source_provider=payload["source_provider"],
                source_batch_id=payload["source_batch_id"],
                observed_at=payload["observed_at"],
                revision=next_revision,
                row_hash=payload["row_hash"],
            )
            self._session.add(row)
            self._session.flush()
            written.append(_row_to_stored_daily_bar(row))
        return written


class SqlAlchemyResearchContextPackRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, pack: ResearchContextPack) -> ResearchContextPack:
        pack_values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "instrument_id": pack.instrument_id.value,
            "schema_version": pack.schema_version,
            "context_version": pack.context_version,
            "content_hash": pack.content_hash,
            "missing_reason": pack.missing_reason,
        }
        if pack.created_at is not None:
            pack_values["created_at"] = pack.created_at
        statement = (
            insert(ResearchContextPackRow)
            .values(**pack_values)
            .on_conflict_do_nothing(index_elements=[ResearchContextPackRow.content_hash])
            .returning(ResearchContextPackRow.id)
        )
        inserted_id = self._session.execute(statement).scalar_one_or_none()
        if inserted_id is None:
            existing = self._find_by_hash(pack.content_hash)
            if existing is None:
                raise RuntimeError("research context pack conflict row was not found")
            return existing
        self._session.flush()
        for item in pack.items:
            self._session.execute(
                insert(ResearchContextItemRow)
                .values(**_context_item_to_row(item, inserted_id))
                .on_conflict_do_nothing(constraint="uq_research_context_items_pack_item_hash")
            )
        self._session.flush()
        return pack

    def upsert(self, pack: ResearchContextPack) -> ResearchContextPack:
        existing = self._find_by_hash(pack.content_hash)
        return existing if existing is not None else self.add(pack)

    def get_by_id(self, pack_id: UUID) -> ResearchContextPack | None:
        row = self._session.get(ResearchContextPackRow, pack_id)
        return self._row_to_pack(row) if row is not None else None

    def get_by_instrument_and_version(
        self, instrument_id: UUID | InstrumentId, context_version: int
    ) -> ResearchContextPack | None:
        raw_id = instrument_id.value if isinstance(instrument_id, InstrumentId) else instrument_id
        row = self._session.scalars(
            select(ResearchContextPackRow)
            .where(
                ResearchContextPackRow.instrument_id == raw_id,
                ResearchContextPackRow.context_version == context_version,
            )
            .order_by(ResearchContextPackRow.created_at.desc())
            .limit(1)
        ).first()
        return self._row_to_pack(row) if row is not None else None

    def list_by_instrument(self, instrument_id: UUID | InstrumentId) -> list[ResearchContextPack]:
        raw_id = instrument_id.value if isinstance(instrument_id, InstrumentId) else instrument_id
        rows = self._session.scalars(
            select(ResearchContextPackRow)
            .where(ResearchContextPackRow.instrument_id == raw_id)
            .order_by(
                ResearchContextPackRow.context_version.asc(),
                ResearchContextPackRow.created_at.asc(),
            )
        ).all()
        return [self._row_to_pack(row) for row in rows]

    def _find_by_hash(self, content_hash: str) -> ResearchContextPack | None:
        row = self._session.scalars(
            select(ResearchContextPackRow)
            .where(ResearchContextPackRow.content_hash == content_hash)
            .limit(1)
        ).first()
        return self._row_to_pack(row) if row is not None else None

    def _row_to_pack(self, row: ResearchContextPackRow) -> ResearchContextPack:
        item_rows = self._session.scalars(
            select(ResearchContextItemRow)
            .where(ResearchContextItemRow.pack_id == row.id)
            .order_by(ResearchContextItemRow.context_type, ResearchContextItemRow.key)
        ).all()
        items = tuple(
            ContextItem(
                context_type=item.context_type,
                key=item.key,
                value=_context_value_from_json(item.value, item.value_type),
                value_type=ContextValueType(item.value_type),
                source_provider=item.source_provider,
                source_dataset=item.source_dataset,
                observed_at=item.observed_at,
                source_batch_id=item.source_batch_id,
                source_revision=item.source_revision,
                quality_status=QualityStatus(item.quality_status),
                confidence_score=_as_decimal(item.confidence_score) or Decimal("1"),
                evidence_refs=tuple(item.evidence_refs or ()),
                item_hash=item.item_hash,
            )
            for item in item_rows
        )
        return ResearchContextPack(
            instrument_id=InstrumentId(row.instrument_id),
            items=items,
            schema_version=row.schema_version,
            context_version=row.context_version,
            content_hash=row.content_hash,
            created_at=row.created_at,
            missing_reason=row.missing_reason,
        )


class SqlAlchemyResearchCaseRepository:
    """Persistence for :class:`ResearchCase` (ADR-0012, Phase 2A).

    Owns ``analytics.research_cases``. ``add`` is the only insert path;
    ``save_transition`` is a single ``UPDATE ... WHERE case_id = :id
    AND status = :previous_status`` compare-and-swap that raises
    :class:`ResearchCaseTransitionError` on ``rowcount != 1`` so the
    application layer cannot lose a concurrent transition.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, case: ResearchCase) -> ResearchCase:
        row = ResearchCaseRow(
            case_id=case.case_id,
            instrument_id=case.instrument_id.value,
            as_of_date=case.as_of_date,
            question=case.question,
            horizon=case.horizon,
            status=case.status.value,
            created_at=case.created_at,
            closed_at=case.closed_at,
            candidate_pool_run_id=case.candidate_pool_run_id,
        )
        self._session.add(row)
        self._session.flush()
        return _row_to_research_case(row)

    def get(self, case_id: UUID) -> ResearchCase | None:
        row = self._session.get(ResearchCaseRow, case_id)
        return _row_to_research_case(row) if row is not None else None

    def list_by_instrument(self, instrument_id: UUID | InstrumentId) -> list[ResearchCase]:
        raw_id = (
            instrument_id.value
            if isinstance(instrument_id, InstrumentId)
            else instrument_id
        )
        rows = self._session.scalars(
            select(ResearchCaseRow)
            .where(ResearchCaseRow.instrument_id == raw_id)
            .order_by(
                ResearchCaseRow.created_at.asc(),
                ResearchCaseRow.case_id.asc(),
            )
        ).all()
        return [_row_to_research_case(row) for row in rows]

    def save_transition(
        self,
        previous_status: ResearchCaseStatus,
        transitioned_case: ResearchCase,
    ) -> ResearchCase:
        result = self._session.execute(
            update(ResearchCaseRow)
            .where(
                ResearchCaseRow.case_id == transitioned_case.case_id,
                ResearchCaseRow.status == previous_status.value,
            )
            .values(
                status=transitioned_case.status.value,
                closed_at=transitioned_case.closed_at,
            )
        )
        if result.rowcount != 1:
            raise ResearchCaseTransitionError(
                f"ResearchCase {transitioned_case.case_id!s} save_transition "
                f"expected exactly 1 row to match case_id+status="
                f"{previous_status.value!r}, got {result.rowcount}; "
                "either the row is missing or the status changed concurrently"
            )
        self._session.flush()
        return _row_to_research_case(
            self._session.get(ResearchCaseRow, transitioned_case.case_id)
        )

    def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[ResearchCase]:
        if limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        rows = self._session.scalars(
            select(ResearchCaseRow)
            .order_by(
                ResearchCaseRow.created_at.desc(),
                ResearchCaseRow.case_id.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_research_case(row) for row in rows]

    def count_all(self) -> int:
        stmt = select(func.count(ResearchCaseRow.case_id))
        return int(self._session.scalar(stmt) or 0)


class ResearchCaseTransitionError(RuntimeError):
    """Raised when ``save_transition`` cannot apply a CAS update."""


def _row_to_research_case(row: ResearchCaseRow) -> ResearchCase:
    return ResearchCase(
        case_id=row.case_id,
        instrument_id=InstrumentId(row.instrument_id),
        as_of_date=row.as_of_date,
        question=row.question,
        horizon=row.horizon,
        status=ResearchCaseStatus(row.status),
        created_at=row.created_at,
        closed_at=row.closed_at,
        candidate_pool_run_id=row.candidate_pool_run_id,
    )


class SqlAlchemyResearchRunRepository:
    """Persistence for :class:`ResearchRun` (PR-5.5, lifecycle owner).

    Owns ``analytics.research_runs`` (migration for Slice 1). The
    repository exposes:

    - :meth:`add` / :meth:`get` for the trivial round-trip.
    - :meth:`list_by_case` with deterministic ordering
      (``created_at`` ascending, ``run_id`` ascending).
    - :meth:`save_transition` as the single ``UPDATE ... WHERE
      run_id = :id AND status = :previous_status`` compare-and-swap
      path that raises :class:`ResearchRunTransitionError` on
      ``rowcount != 1`` so a stale worker cannot overwrite a newer
      state.
    - :meth:`bind_external_identity` for the nullable
      ``external_request_id`` / ``external_session_id`` columns
      reserved for the later JiuwenSwarm adapter. The repository
      refuses blank values so the storage layer never persists a
      meaningless identity token.
    - :meth:`lookup_by_external_session_id` for the partial unique
      index that the adapter will need.

    The domain layer keeps the legal-transition graph in
    :meth:`ResearchRun._transition`; the repository only mirrors the
    resulting :class:`ResearchRun` into a CAS-aware UPDATE so a
    concurrent worker cannot silently rewrite a row that already
    moved to the next state.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, run: ResearchRun) -> ResearchRun:
        row = ResearchRunRow(
            run_id=run.run_id,
            case_id=run.case_id,
            evidence_pack_id=run.evidence_pack_id,
            runner_key=run.runner_key,
            playbook_key=run.playbook_key,
            status=run.status.value,
            attempt=run.attempt,
            started_at=run.started_at,
            finished_at=run.finished_at,
            error_summary=run.error_summary,
            external_request_id=None,
            external_session_id=None,
            evidence_bundle_id=run.evidence_bundle_id,
        )
        self._session.add(row)
        self._session.flush()
        return _row_to_research_run(row)

    def get(self, run_id: UUID) -> ResearchRun | None:
        row = self._session.get(ResearchRunRow, run_id)
        return _row_to_research_run(row) if row is not None else None

    def list_by_case(self, case_id: UUID) -> list[ResearchRun]:
        rows = self._session.scalars(
            select(ResearchRunRow)
            .where(ResearchRunRow.case_id == case_id)
            .order_by(
                ResearchRunRow.created_at.asc(),
                ResearchRunRow.run_id.asc(),
            )
        ).all()
        return [_row_to_research_run(row) for row in rows]

    def save_transition(
        self,
        previous_status: ResearchRunStatus,
        transitioned_run: ResearchRun,
    ) -> ResearchRun:
        row = self._session.get(ResearchRunRow, transitioned_run.run_id)
        if row is None:
            raise LookupError(
                f"ResearchRun {transitioned_run.run_id!s} not found; "
                "cannot apply save_transition"
            )
        result = self._session.execute(
            update(ResearchRunRow)
            .where(
                ResearchRunRow.run_id == transitioned_run.run_id,
                ResearchRunRow.status == previous_status.value,
            )
            .values(
                status=transitioned_run.status.value,
                started_at=transitioned_run.started_at,
                finished_at=transitioned_run.finished_at,
                error_summary=transitioned_run.error_summary,
                evidence_bundle_id=transitioned_run.evidence_bundle_id,
            )
        )
        if result.rowcount != 1:
            raise ResearchRunTransitionError(
                f"ResearchRun {transitioned_run.run_id!s} save_transition "
                f"expected exactly 1 row to match run_id+status="
                f"{previous_status.value!r}, got {result.rowcount}; "
                "either the row is missing or the status changed concurrently"
            )
        self._session.flush()
        refreshed = self._session.get(ResearchRunRow, transitioned_run.run_id)
        return _row_to_research_run(refreshed) if refreshed is not None else transitioned_run

    def bind_external_identity(
        self,
        run_id: UUID,
        *,
        external_request_id: str | None = None,
        external_session_id: str | None = None,
    ) -> ResearchRun:
        if external_request_id is None and external_session_id is None:
            raise ValueError(
                "bind_external_identity requires at least one of "
                "external_request_id or external_session_id to be provided"
            )
        if external_request_id is not None and not external_request_id.strip():
            raise ValueError(
                "bind_external_identity requires a non-blank external_request_id when provided"
            )
        if external_session_id is not None and not external_session_id.strip():
            raise ValueError(
                "bind_external_identity requires a non-blank external_session_id when provided"
            )
        request_id = external_request_id.strip() if external_request_id is not None else None
        session_id = external_session_id.strip() if external_session_id is not None else None
        values: dict[str, str | None] = {}
        if external_request_id is not None:
            values["external_request_id"] = request_id
        if external_session_id is not None:
            values["external_session_id"] = session_id
        row = self._session.get(ResearchRunRow, run_id)
        if row is None:
            raise LookupError(
                f"ResearchRun {run_id!s} not found; cannot bind external identity"
            )
        result = self._session.execute(
            update(ResearchRunRow)
            .where(ResearchRunRow.run_id == run_id)
            .values(**values)
        )
        if result.rowcount != 1:
            raise RuntimeError(
                f"ResearchRun {run_id!s} bind_external_identity expected "
                f"exactly 1 row to match, got {result.rowcount}"
            )
        self._session.flush()
        refreshed = self._session.get(ResearchRunRow, run_id)
        if refreshed is None:
            return _row_to_research_run(row)
        return _row_to_research_run(refreshed)

    def lookup_by_external_session_id(
        self, external_session_id: str
    ) -> ResearchRun | None:
        if not isinstance(external_session_id, str) or not external_session_id.strip():
            raise ValueError(
                "lookup_by_external_session_id requires a non-blank external_session_id"
            )
        row = self._session.scalars(
            select(ResearchRunRow)
            .where(ResearchRunRow.external_session_id == external_session_id.strip())
            .limit(1)
        ).first()
        return _row_to_research_run(row) if row is not None else None

    def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[ResearchRun]:
        if limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        rows = self._session.scalars(
            select(ResearchRunRow)
            .order_by(
                ResearchRunRow.created_at.desc(),
                ResearchRunRow.run_id.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_research_run(row) for row in rows]

    def count_all(self) -> int:
        stmt = select(func.count(ResearchRunRow.run_id))
        return int(self._session.scalar(stmt) or 0)


class ResearchRunTransitionError(RuntimeError):
    """Raised when ``save_transition`` cannot apply a CAS update."""


def _row_to_research_run(row: ResearchRunRow) -> ResearchRun:
    return ResearchRun(
        run_id=row.run_id,
        case_id=row.case_id,
        evidence_pack_id=row.evidence_pack_id,
        runner_key=row.runner_key,
        playbook_key=row.playbook_key,
        status=ResearchRunStatus(row.status),
        attempt=row.attempt,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_summary=row.error_summary,
        evidence_bundle_id=row.evidence_bundle_id,
    )


class SqlAlchemyResearchResultRepository:
    """Persistence for the immutable :class:`ResearchResult` (PR-5.5).

    Owns ``analytics.research_results``. The natural unique constraint
    on ``run_id`` is the final concurrency guard for the
    one-immutable-result-per-run invariant; the repository honours it
    by:

    - Inserting a fresh row when no row exists for ``run_id``.
    - Returning the existing row when its payload matches the input
      (idempotent replay of a duplicate callback).
    - Raising :class:`ResearchResultConflictError` when an existing
      row for ``run_id`` carries a different payload - the run has
      already published a result and the new payload cannot replace
      it.

    The ``risks`` / ``evidence_ids`` JSONB columns are stored as
    ordered lists and mapped back to ``tuple[str, ...]`` on the read
    path so the domain invariant (``ResearchResult`` requires
    tuples of non-blank strings) is preserved end-to-end.
    """

    _PAYLOAD_FIELDS: tuple[str, ...] = (
        "evidence_pack_id",
        "evidence_bundle_id",
        "conclusion",
        "risks",
        "evidence_ids",
        "report_markdown",
        "model_key",
        "model_version",
        "playbook_version",
        "adapter_version",
    )

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, result: ResearchResult) -> ResearchResult:
        existing = self._find_by_run_id(result.run_id)
        if existing is not None:
            self._ensure_payload_matches(existing, result)
            return _row_to_research_result(existing)
        row = ResearchResultRow(
            result_id=result.result_id,
            run_id=result.run_id,
            evidence_pack_id=result.evidence_pack_id,
            evidence_bundle_id=result.evidence_bundle_id,
            conclusion=result.conclusion,
            risks=list(result.risks),
            evidence_ids=list(result.evidence_ids),
            report_markdown=result.report_markdown,
            model_key=result.model_key,
            model_version=result.model_version,
            playbook_version=result.playbook_version,
            adapter_version=result.adapter_version,
            created_at=result.created_at,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            if not _is_run_id_unique_violation(exc):
                raise
            self._session.expire_all()
            existing_after_race = self._find_by_run_id(result.run_id)
            if existing_after_race is None:
                raise RuntimeError(
                    f"ResearchResult insert for run_id {result.run_id!s} "
                    "collided on uq_research_results_run_id but the "
                    "subsequent read found no row; this indicates a "
                    "session/transaction misconfiguration"
                ) from exc
            self._ensure_payload_matches(existing_after_race, result)
            return _row_to_research_result(existing_after_race)
        return result

    def get_by_id(self, result_id: UUID) -> ResearchResult | None:
        row = self._session.get(ResearchResultRow, result_id)
        return _row_to_research_result(row) if row is not None else None

    def get_by_run_id(self, run_id: UUID) -> ResearchResult | None:
        row = self._find_by_run_id(run_id)
        return _row_to_research_result(row) if row is not None else None

    def _find_by_run_id(self, run_id: UUID) -> ResearchResultRow | None:
        return self._session.scalars(
            select(ResearchResultRow)
            .where(ResearchResultRow.run_id == run_id)
            .limit(1)
        ).first()

    def _ensure_payload_matches(
        self,
        existing: ResearchResultRow,
        incoming: ResearchResult,
    ) -> None:
        for field_name in self._PAYLOAD_FIELDS:
            existing_value = getattr(existing, field_name)
            incoming_value = getattr(incoming, field_name)
            if field_name in ("risks", "evidence_ids"):
                if list(existing_value or []) != list(incoming_value):
                    raise ResearchResultConflictError(
                        f"ResearchResult for run_id {incoming.run_id!s} "
                        f"conflicts on {field_name}: existing="
                        f"{list(existing_value or [])}, incoming="
                        f"{list(incoming_value)}"
                    )
                continue
            if existing_value != incoming_value:
                raise ResearchResultConflictError(
                    f"ResearchResult for run_id {incoming.run_id!s} "
                    f"conflicts on {field_name}: existing={existing_value!r}, "
                    f"incoming={incoming_value!r}"
                )


class ResearchResultConflictError(RuntimeError):
    """Raised when ``add`` finds a result for ``run_id`` with a different payload."""


_UNIQUE_VIOLATION_SQLSTATES = {"23505"}


def _is_run_id_unique_violation(exc: IntegrityError) -> bool:
    """Return True iff ``exc`` is a unique-constraint violation on ``run_id``.

    The :class:`sqlalchemy.exc.IntegrityError` is the only safe way to
    detect the ``uq_research_results_run_id`` race; we read the
    underlying psycopg ``diag`` / ``pgcode`` to keep the check narrow.
    Other integrity violations (NOT NULL, FK, CHECK, ...) must keep
    bubbling so the application layer keeps the loud failure it has
    today.
    """

    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate not in _UNIQUE_VIOLATION_SQLSTATES:
        return False
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None) if diag is not None else None
    if constraint_name:
        return constraint_name == "uq_research_results_run_id"
    message = str(orig).lower()
    return "uq_research_results_run_id" in message


def _row_to_research_result(row: ResearchResultRow) -> ResearchResult:
    return ResearchResult(
        result_id=row.result_id,
        run_id=row.run_id,
        evidence_pack_id=row.evidence_pack_id,
        evidence_bundle_id=row.evidence_bundle_id,
        conclusion=row.conclusion,
        risks=tuple(row.risks or ()),
        evidence_ids=tuple(row.evidence_ids or ()),
        report_markdown=row.report_markdown,
        model_key=row.model_key,
        model_version=row.model_version,
        playbook_version=row.playbook_version,
        adapter_version=row.adapter_version,
        created_at=row.created_at,
    )


class SqlAlchemyEvidencePackRepository:
    """Phase 2B persistence closure for :class:`EvidencePack`.

    The repository owns ``analytics.research_evidence_packs`` and
    honours the immutability contract: there is no ``update`` /
    ``delete`` surface because the evidence-pack is a durable
    audit-grade artefact. The natural idempotency key is the
    deterministic ``content_hash`` (see
    :func:`invest_domain.research.canonical.compute_pack_hash`); the
    database-level ``UNIQUE (instrument_id, as_of_date, schema_version,
    factor_set_version, content_hash)`` constraint is the final
    concurrency guard.

    The :meth:`add` path uses ``ON CONFLICT (content_hash) DO NOTHING``
    so a re-collect of the same business content never produces a
    duplicate row. When the insert is a no-op the repository refetches
    the existing row by ``content_hash`` and returns the canonical
    :class:`EvidencePack` so callers always see the storage-assigned
    ``pack_id`` / ``generated_at``.

    ``CaseContext.case_id`` is wired through the
    ``research_case_id`` foreign key on the row: when the input pack
    carries a non-null ``case_id`` it must be UUID-compatible, and the
    resulting UUID is stored as ``research_case_id``. The database FK
    is authoritative on the read path so a corrupt
    payload/column mismatch fails closed in
    :func:`invest_storage.evidence_pack_codec.row_to_evidence_pack` instead of silently normalizing.

    Runtime metadata fields (``workspace_path``, ``e2a_request_id``,
    ``e2a_session_id``, ``generated_at``) are explicitly excluded from
    the persisted JSONB payload so they cannot leak across the
    immutable audit boundary; the storage layer re-attaches the
    row-level ``pack_id`` and ``created_at`` (as ``generated_at``) on
    the read path.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, pack: EvidencePack) -> EvidencePack:
        """Persist ``pack`` idempotently and return the canonical view.

        A re-collect of the same business content returns the
        pre-existing row instead of producing a duplicate. ``pack_id``
        and ``generated_at`` are always taken from the database row so
        the returned value carries the same storage-assigned identity
        regardless of whether the call performed the INSERT or hit the
        idempotency guard.

        The natural idempotency key is the deterministic ``content_hash``;
        the database-level
        ``UNIQUE (instrument_id, as_of_date, schema_version,
        factor_set_version, content_hash)`` plus the
        ``UNIQUE (content_hash)`` constraint enforced by migration
        ``20260807_0013`` are the concurrency guards. The
        ``ON CONFLICT (content_hash) DO NOTHING`` clause lets the INSERT
        silently no-op when the row already exists so a re-collect never
        surfaces an :class:`sqlalchemy.exc.IntegrityError`.
        """

        if not isinstance(pack, EvidencePack):
            raise TypeError(
                "SqlAlchemyEvidencePackRepository.add expects an EvidencePack, "
                f"got {type(pack).__name__}"
            )
        payload = evidence_pack_to_payload(pack)
        research_case_id = coerce_optional_uuid(
            pack.case.case_id, field_name="CaseContext.case_id"
        )
        row_values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "instrument_id": pack.instrument.instrument_id.value,
            "as_of_date": pack.case.as_of_date,
            "schema_version": pack.schema_version,
            "factor_set_key": pack.factor_set.key,
            "factor_set_version": pack.factor_set.version,
            "freshness_status": pack.data_quality.freshness_status.value,
            "quality_status": pack.data_quality.quality_status.value,
            "content_hash": pack.pack_hash,
            "payload": payload,
            "research_case_id": research_case_id,
        }
        statement = (
            insert(ResearchEvidencePackRow)
            .values(**row_values)
            .on_conflict_do_nothing(
                index_elements=[ResearchEvidencePackRow.content_hash],
            )
            .returning(ResearchEvidencePackRow.id)
        )
        self._session.execute(statement)
        self._session.flush()
        existing = self._find_by_content_hash(pack.pack_hash)
        if existing is None:
            raise RuntimeError(
                "research_evidence_packs insert succeeded but the row "
                "was not found on the subsequent read; this indicates "
                "a session/transaction misconfiguration"
            )
        if existing.case.case_id != research_case_id:
            raise ValueError(
                "research_case_id mismatch: existing row is bound to "
                f"{existing.case.case_id}, requested {research_case_id}"
            )
        return existing

    def get_by_id(self, pack_id: UUID) -> EvidencePack | None:
        """Return the persisted pack with ``pack_id`` or ``None``."""

        row = self._session.get(ResearchEvidencePackRow, pack_id)
        return row_to_evidence_pack(row) if row is not None else None

    def get_by_content_hash(self, content_hash: str) -> EvidencePack | None:
        """Return the persisted pack carrying ``content_hash`` or ``None``."""

        return self._find_by_content_hash(content_hash)

    def list_by_case(self, case_id: UUID) -> list[EvidencePack]:
        """Return every pack bound to ``case_id`` in deterministic order.

        Ordered by ``created_at`` ascending then ``id`` ascending so the
        result is stable across replay.
        """

        rows = self._session.scalars(
            select(ResearchEvidencePackRow)
            .where(ResearchEvidencePackRow.research_case_id == case_id)
            .order_by(
                ResearchEvidencePackRow.created_at.asc(),
                ResearchEvidencePackRow.id.asc(),
            )
        ).all()
        return [row_to_evidence_pack(row) for row in rows]

    def list_by_instrument(
        self,
        instrument_id: UUID | InstrumentId,
        as_of_date: date | None = None,
    ) -> list[EvidencePack]:
        """Return every pack for ``instrument_id`` in deterministic order.

        When ``as_of_date`` is provided the result is restricted to the
        single ``as_of_date`` and ordered by ``created_at`` ascending
        then ``id`` ascending; otherwise the result spans every
        ``as_of_date`` and is ordered by ``as_of_date`` ascending,
        ``created_at`` ascending, ``id`` ascending.
        """

        raw_id = (
            instrument_id.value
            if isinstance(instrument_id, InstrumentId)
            else instrument_id
        )
        stmt = select(ResearchEvidencePackRow).where(
            ResearchEvidencePackRow.instrument_id == raw_id
        )
        if as_of_date is not None:
            stmt = stmt.where(ResearchEvidencePackRow.as_of_date == as_of_date)
            stmt = stmt.order_by(
                ResearchEvidencePackRow.created_at.asc(),
                ResearchEvidencePackRow.id.asc(),
            )
        else:
            stmt = stmt.order_by(
                ResearchEvidencePackRow.as_of_date.asc(),
                ResearchEvidencePackRow.created_at.asc(),
                ResearchEvidencePackRow.id.asc(),
            )
        rows = self._session.scalars(stmt).all()
        return [row_to_evidence_pack(row) for row in rows]

    def _find_by_content_hash(self, content_hash: str) -> EvidencePack | None:
        if not isinstance(content_hash, str) or len(content_hash) != 64:
            return None
        row = self._session.scalars(
            select(ResearchEvidencePackRow)
            .where(ResearchEvidencePackRow.content_hash == content_hash)
            .limit(1)
        ).first()
        return row_to_evidence_pack(row) if row is not None else None


def _context_item_to_row(item: ContextItem, pack_id: UUID) -> dict[str, Any]:
    value: Any = item.value
    if item.value_type is ContextValueType.DECIMAL and isinstance(value, Decimal):
        value = str(value)
    elif item.value_type is ContextValueType.DATE and isinstance(value, date):
        value = value.isoformat()
    return {
        "id": uuid.uuid4(),
        "pack_id": pack_id,
        "context_type": item.context_type,
        "key": item.key,
        "value_type": item.value_type.value,
        "value": value,
        "evidence_refs": list(item.evidence_refs),
        "source_provider": item.source_provider,
        "source_dataset": item.source_dataset,
        "source_batch_id": item.source_batch_id,
        "source_revision": item.source_revision,
        "observed_at": item.observed_at,
        "quality_status": item.quality_status.value,
        "confidence_score": item.confidence_score,
        "item_hash": item.item_hash,
    }


def _context_value_from_json(value: Any, value_type: str) -> Any:
    if value is None:
        return None
    if value_type == ContextValueType.DECIMAL.value:
        return Decimal(str(value))
    if value_type == ContextValueType.DATE.value:
        return date.fromisoformat(str(value))
    return value


def _normalise_bar(
    bar: NewDailyBar | DailyBar,
) -> tuple[UUID, date, Adjust, dict[str, Any]]:
    """Reduce the input ``bar`` to a canonical ``(id, date, adjust, payload)`` tuple.

    The repository accepts either the domain :class:`DailyBar` (full
    validation already done) or a transport-shape :class:`NewDailyBar`
    straight from the application service. The ``payload`` is the
    keyword-argument shape that the row builder consumes.
    """

    if isinstance(bar, DailyBar):
        return (
            bar.instrument_id.value,
            bar.trade_date,
            bar.adjustment,
            {
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "prev_close": bar.prev_close,
                "volume": bar.volume,
                "amount": bar.amount,
                "trading_status": bar.trading_status.value,
                "source_provider": bar.source.provider_key,
                "source_batch_id": bar.source.source_batch_id,
                "observed_at": bar.source.observed_at,
                "row_hash": bar.compute_row_hash(),
            },
        )
    if isinstance(bar, NewDailyBar):
        return (
            bar.instrument_id,
            bar.trade_date,
            bar.adjustment,
            {
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "prev_close": bar.prev_close,
                "volume": bar.volume,
                "amount": bar.amount,
                "trading_status": bar.trading_status.value,
                "source_provider": bar.source_provider,
                "source_batch_id": bar.source_batch_id,
                "observed_at": bar.observed_at,
                "row_hash": bar.row_hash,
            },
        )
    raise TypeError(
        "upsert_many accepts invest_domain.market_data.models.DailyBar or "
        "invest_storage.repositories.NewDailyBar, "
        f"got {type(bar).__name__}"
    )


def _row_to_stored_daily_bar(row: DailyBarRow) -> StoredDailyBar:
    return StoredDailyBar(
        id=row.id,
        instrument_id=row.instrument_id,
        trade_date=row.trade_date,
        open=_as_decimal(row.open),
        high=_as_decimal(row.high),
        low=_as_decimal(row.low),
        close=_as_decimal(row.close),
        prev_close=_as_decimal(row.prev_close),
        volume=_as_decimal(row.volume),
        amount=_as_decimal(row.amount),
        adjustment=row.adjustment,
        trading_status=row.trading_status,
        source_provider=row.source_provider,
        source_batch_id=row.source_batch_id,
        observed_at=row.observed_at,
        revision=row.revision,
        row_hash=row.row_hash,
        created_at=row.created_at,
    )


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _excluded_set() -> dict[str, Any]:
    excluded = insert(InstrumentRow).excluded
    return {
        "symbol": excluded.symbol,
        "exchange": excluded.exchange,
        "name": excluded.name,
        "instrument_type": excluded.instrument_type,
        "currency": excluded.currency,
        "list_date": excluded.list_date,
        "delist_date": excluded.delist_date,
        "status": excluded.status,
        "underlying_index": excluded.underlying_index,
        "category": excluded.category,
        "provider_symbol_map": excluded.provider_symbol_map,
        "valid_from": excluded.valid_from,
        "valid_to": excluded.valid_to,
        "is_active": excluded.is_active,
    }


def _row_to_instrument(row: InstrumentRow) -> Instrument:
    return Instrument(
        symbol=row.symbol,
        name=row.name,
        exchange=row.exchange,
        instrument_type=InstrumentType(row.instrument_type),
        is_active=row.is_active,
        instrument_id=InstrumentId(row.id) if row.id is not None else None,
        currency=Currency(row.currency) if row.currency else Currency.CNY,
        list_date=_as_date(row.list_date),
        delist_date=_as_date(row.delist_date),
        status=InstrumentStatus(row.status) if row.status else InstrumentStatus.UNKNOWN,
        underlying_index=row.underlying_index,
        category=row.category,
        provider_symbol_map=dict(row.provider_symbol_map or {}),
        valid_from=_as_date(row.valid_from),
        valid_to=_as_date(row.valid_to),
    )


class InputSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, snapshot: InputSnapshot) -> InputSnapshot:
        statement = (
            insert(InputSnapshotRow)
            .values(
                id=snapshot.id,
                snapshot_date=snapshot.snapshot_date,
                instrument_ids=[str(value) for value in snapshot.instrument_ids],
                content_hash=snapshot.content_hash,
                row_count=snapshot.row_count,
                created_at=snapshot.created_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_input_snapshots_date_hash",
            )
            .returning(InputSnapshotRow.id)
        )
        inserted_id = self._session.execute(statement).scalar_one_or_none()
        if inserted_id is not None:
            return snapshot

        existing = self.get_by_date_and_hash(
            snapshot.snapshot_date,
            snapshot.content_hash,
        )
        if existing is None:
            raise RuntimeError(
                "input snapshot insert conflicted but the existing row was not found"
            )
        return existing

    def get_by_date_and_hash(
        self,
        snapshot_date: date,
        content_hash: str,
    ) -> InputSnapshot | None:
        stmt = (
            select(InputSnapshotRow)
            .where(
                InputSnapshotRow.snapshot_date == snapshot_date,
                InputSnapshotRow.content_hash == content_hash,
            )
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_input_snapshot(row) if row is not None else None

    def list_by_date(self, snapshot_date: date) -> list[InputSnapshot]:
        rows = self._session.scalars(
            select(InputSnapshotRow)
            .where(InputSnapshotRow.snapshot_date == snapshot_date)
            .order_by(
                InputSnapshotRow.created_at.asc(),
                InputSnapshotRow.id.asc(),
            )
        ).all()
        return [_row_to_input_snapshot(row) for row in rows]


def _row_to_input_snapshot(row: InputSnapshotRow) -> InputSnapshot:
    return InputSnapshot(
        id=row.id,
        snapshot_date=row.snapshot_date,
        instrument_ids=tuple(
            value if isinstance(value, UUID) else UUID(str(value)) for value in row.instrument_ids
        ),
        content_hash=row.content_hash,
        row_count=row.row_count,
        created_at=row.created_at,
    )


class SqlAlchemyPipelineRunRepository:
    """Read/write access to ``ops.pipeline_runs``.

    The repository never commits: it only mutates the session, and the
    surrounding :class:`invest_storage.unit_of_work.SqlAlchemyUnitOfWork`
    owns the transaction boundary. All public methods return the
    domain-side :class:`invest_domain.pipeline.PipelineRun` rather than
    the SQLAlchemy ORM row so callers can stay free of storage
    machinery.

    The repository treats :meth:`start` as the transition into the
    ``running`` state regardless of the input status; the application
    layer is expected to hand in a fully-formed :class:`PipelineRun`
    and rely on the repository to assign the storage-side identity and
    the lifecycle timestamps.
    """

    _START_STATUS = PipelineRunStatus.RUNNING.value

    def __init__(self, session: Session) -> None:
        self._session = session

    def start(self, run: PipelineRun) -> PipelineRun:
        """Insert a new ``pipeline_runs`` row in the ``running`` state.

        The input ``run`` is taken as the canonical payload for
        ``job_key``, ``trigger_type``, ``algorithm_version`` and ``started_at``;
        ``status`` is overwritten with ``"running"`` and a fresh UUID is
        generated in Python. ``error_summary`` is reset to ``None`` so
        a re-used domain value cannot leak a stale failure message into
        a brand-new run.

        Returns the persisted :class:`PipelineRun` carrying the
        assigned UUID and the server-generated ``created_at`` /
        ``updated_at`` timestamps.
        """

        row = PipelineRunRow(
            id=uuid.uuid4(),
            dagster_run_id=run.dagster_run_id,
            job_key=run.job_key,
            partition_key=run.partition_key,
            trigger_type=run.trigger_type,
            algorithm_version=run.algorithm_version,
            config_snapshot=run.config_snapshot or {},
            status=self._START_STATUS,
            started_at=run.started_at,
            finished_at=None,
            error_summary=None,
        )
        self._session.add(row)
        self._session.flush()
        return _row_to_pipeline_run(row)

    def mark_succeeded(self, run_id: UUID, *, finished_at: datetime) -> PipelineRun:
        """Transition a run into the ``succeeded`` terminal state.

        Updates ``status='succeeded'`` and ``finished_at``; ``error_summary``
        is reset to ``None`` so a previous transient failure is not
        carried forward.

        Idempotent: when the row is already in the ``succeeded`` state
        the call returns the existing record without re-writing
        ``finished_at`` so a duplicate ``mark_succeeded`` (e.g. a retry
        by the CLI after the original succeeded row has already been
        persisted) does not corrupt the audit history.
        """

        row = self._session.get(PipelineRunRow, run_id)
        if row is None:
            raise LookupError(f"PipelineRun {run_id!s} not found; cannot mark succeeded")
        if row.status == PipelineRunStatus.SUCCEEDED.value:
            return _row_to_pipeline_run(row)
        row.status = PipelineRunStatus.SUCCEEDED.value
        row.finished_at = finished_at
        row.error_summary = None
        self._session.flush()
        return _row_to_pipeline_run(row)

    def mark_failed(self, run_id: UUID, *, error: str, finished_at: datetime) -> PipelineRun:
        """Transition a run into the ``failed`` terminal state.

        Updates ``status='failed'``, ``finished_at`` and ``error_summary``.
        Raises :class:`ValueError` when ``error`` is empty so the
        repository never writes a meaningless failure record.

        Sticky success: when the row is already in the ``succeeded``
        state the call refuses to downgrade it and raises
        :class:`ValueError`. Callers (e.g. the manual personal CLI)
        must check :meth:`get_blocking_by_job_and_partition` before
        opening a new run so this branch is unreachable in practice,
        but the safety net is preserved so a buggy caller cannot
        silently rewrite a successful audit row as a failure.
        """

        if not isinstance(error, str) or not error.strip():
            raise ValueError(
                "SqlAlchemyPipelineRunRepository.mark_failed requires a non-empty error message"
            )
        row = self._session.get(PipelineRunRow, run_id)
        if row is None:
            raise LookupError(f"PipelineRun {run_id!s} not found; cannot mark failed")
        if row.status == PipelineRunStatus.SUCCEEDED.value:
            raise ValueError(
                f"PipelineRun {run_id!s} is already in 'succeeded' state; "
                "refusing to downgrade to 'failed' (a retry that fails must "
                "open a brand-new ops.pipeline_runs row instead of "
                "overwriting the existing succeeded record)"
            )
        row.status = PipelineRunStatus.FAILED.value
        row.finished_at = finished_at
        row.error_summary = error
        self._session.flush()
        return _row_to_pipeline_run(row)

    def get_blocking_by_job_and_partition(
        self,
        *,
        job_key: str,
        partition_key: str | None,
    ) -> PipelineRun | None:
        """Lock the logical run key and return any non-retryable run."""

        if not isinstance(job_key, str) or not job_key.strip():
            raise ValueError("get_blocking_by_job_and_partition requires a non-empty job_key")
        lock_material = (f"{len(job_key)}:{job_key}:{partition_key!r}").encode()
        lock_key = int.from_bytes(
            hashlib.blake2b(lock_material, digest_size=8).digest(),
            byteorder="big",
            signed=True,
        )
        self._session.execute(select(func.pg_advisory_xact_lock(lock_key)))
        blocking_statuses = (
            PipelineRunStatus.QUEUED.value,
            PipelineRunStatus.RUNNING.value,
            PipelineRunStatus.SUCCEEDED.value,
        )
        stmt = (
            select(PipelineRunRow)
            .where(
                PipelineRunRow.job_key == job_key,
                PipelineRunRow.partition_key == partition_key,
                PipelineRunRow.status.in_(blocking_statuses),
            )
            .order_by(
                PipelineRunRow.started_at.desc(),
                PipelineRunRow.id.asc(),
            )
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_pipeline_run(row) if row is not None else None

    def get_by_id(self, run_id: UUID) -> PipelineRun | None:
        """Return the run for ``run_id`` or ``None`` if absent."""

        row = self._session.get(PipelineRunRow, run_id)
        return _row_to_pipeline_run(row) if row is not None else None

    def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[PipelineRun]:
        """Return runs ordered by ``started_at`` descending.

        The descending ``started_at`` order matches the dashboard use
        case where the most recent run must come first; ties on
        ``started_at`` (e.g. two runs scheduled for the same instant)
        are broken by ``id`` so the result is stable.
        """

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        stmt = (
            select(PipelineRunRow)
            .order_by(
                PipelineRunRow.started_at.desc(),
                PipelineRunRow.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = self._session.scalars(stmt).all()
        return [_row_to_pipeline_run(row) for row in rows]

    def list_by_job_key(
        self, job_key: str, *, limit: int = 50, offset: int = 0
    ) -> list[PipelineRun]:
        """Return one job's runs ordered by ``started_at`` descending."""

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        stmt = (
            select(PipelineRunRow)
            .where(PipelineRunRow.job_key == job_key)
            .order_by(
                PipelineRunRow.started_at.desc(),
                PipelineRunRow.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = self._session.scalars(stmt).all()
        return [_row_to_pipeline_run(row) for row in rows]

    def count_by_job_key(self, job_key: str) -> int:
        """Return the number of runs for ``job_key``."""

        stmt = select(func.count(PipelineRunRow.id)).where(PipelineRunRow.job_key == job_key)
        return int(self._session.scalar(stmt) or 0)

    def count_by_status(self, status: str) -> int:
        """Return the number of runs in the given ``status``.

        ``status`` is taken as a raw string so callers can drive the
        count with the canonical lowercase vocabulary without having
        to construct a :class:`PipelineRunStatus`. An unknown value
        yields zero rather than raising so the repository can be
        probed safely from operational dashboards.
        """

        stmt = select(PipelineRunRow.id).where(PipelineRunRow.status == status)
        return len(self._session.scalars(stmt).all())


def _row_to_pipeline_run(row: PipelineRunRow) -> PipelineRun:
    return PipelineRun(
        id=row.id,
        dagster_run_id=row.dagster_run_id,
        job_key=row.job_key,
        partition_key=row.partition_key,
        trigger_type=row.trigger_type,
        algorithm_version=row.algorithm_version,
        config_snapshot=dict(row.config_snapshot or {}),
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_summary=row.error_summary,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_stored_request(row: ProviderRequestRow) -> StoredProviderRequest:
    return StoredProviderRequest(
        id=row.id,
        provider_key=row.provider_key,
        dataset_key=row.dataset_key,
        request_key=row.request_key,
        request_params=dict(row.request_params or {}),
        requested_by_run_id=row.requested_by_run_id,
        status=row.status,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _row_to_stored_attempt(row: ProviderAttemptRow) -> StoredProviderAttempt:
    return StoredProviderAttempt(
        id=row.id,
        provider_request_id=row.provider_request_id,
        attempt_no=row.attempt_no,
        provider_request_id_text=row.provider_request_id_text,
        started_at=row.started_at,
        finished_at=row.finished_at,
        status=row.status,
        http_status=row.http_status,
        error_stage=row.error_stage,
        error_code=row.error_code,
        error_message=row.error_message,
        response_payload_sha256=row.response_payload_sha256,
        response_payload_json=row.response_payload_json,
        response_payload_uri=row.response_payload_uri,
        created_at=row.created_at,
    )


def _row_to_stored_batch(row: RawProviderBatchRow) -> StoredProviderBatch:
    return StoredProviderBatch(
        id=row.id,
        provider_request_id=row.provider_request_id,
        provider_attempt_id=row.provider_attempt_id,
        provider_key=row.provider_key,
        dataset_key=row.dataset_key,
        record_count=row.record_count,
        payload_sha256=row.payload_sha256,
        warnings=list(row.warnings or []),
        status=row.status,
        created_at=row.created_at,
    )


class SqlAlchemyCandidatePoolRunRepository:
    """Read/write access to ``analytics.candidate_pool_runs``.

    The repository owns persistence but never the state-machine
    semantics: every transition flows through the domain method
    :meth:`invest_domain.candidate_pool.models.CandidatePoolRun.transition_to`
    so that illegal ``CALCULATED -> PUBLISHED`` etc. attempts are
    rejected by the domain, not the database. The repository only
    translates the resulting :class:`CandidatePoolRun` into a row update.

    The natural unique key
    ``(trade_date, algorithm_key, algorithm_version, parameter_hash,
    input_snapshot_id)`` is enforced by the database; duplicate inserts
    surface as :class:`sqlalchemy.exc.IntegrityError`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        run: CandidatePoolRun,
        *,
        quality_summary: dict[str, Any] | None = None,
    ) -> CandidatePoolRun:
        """Persist a brand-new ``calculated`` run.

        The input ``run`` must already be in the ``CALCULATED`` state;
        :meth:`transition_status` is the only path to the terminal
        states. ``quality_summary`` is an opaque JSONB blob for the
        storage layer; the domain ``CandidatePoolRun`` does not carry
        it, so it is supplied here out-of-band. ``started_at`` defaults
        to ``run.created_at`` so the two timestamps stay aligned when
        the application does not pass an explicit value.
        """

        if run.status is not CandidatePoolStatus.CALCULATED:
            raise ValueError(
                "SqlAlchemyCandidatePoolRunRepository.add requires the run to "
                f"be in CALCULATED state, got {run.status.value!r}"
            )
        row = CandidatePoolRunRow(
            id=run.id,
            trade_date=run.trade_date,
            algorithm_key=run.algorithm_key,
            algorithm_version=run.algorithm_version,
            parameter_set_key=run.parameter_set_key,
            parameter_hash=run.parameter_hash,
            input_snapshot_id=run.input_snapshot_id,
            input_row_count=run.input_row_count,
            included_count=run.included_count,
            status=run.status.value,
            started_at=run.created_at,
            finished_at=run.finished_at,
            published_at=run.published_at,
            rejected_at=run.rejected_at,
            rejection_reason=run.rejection_reason,
            quality_summary=dict(quality_summary) if quality_summary else {},
        )
        self._session.add(row)
        self._session.flush()
        return _row_to_candidate_pool_run(row)

    def get_by_id(self, run_id: UUID) -> CandidatePoolRun | None:
        """Return the run with ``run_id`` or ``None`` if absent."""

        row = self._session.get(CandidatePoolRunRow, run_id)
        return _row_to_candidate_pool_run(row) if row is not None else None

    def get_by_natural_key(
        self,
        *,
        trade_date: date,
        algorithm_key: str,
        algorithm_version: str,
        parameter_hash: str,
        input_snapshot_id: UUID,
    ) -> CandidatePoolRun | None:
        """Return the run identified by the ADR-0008 natural unique key.

        The natural key
        ``(trade_date, algorithm_key, algorithm_version, parameter_hash,
        input_snapshot_id)`` is enforced by the database unique constraint
        ``uq_candidate_pool_runs_natural_key``; at most one row can match.
        This lookup is the idempotent entry point used by the application
        service when the same business calculation is rerun so the existing
        ``PUBLISHED`` run can be returned instead of triggering a duplicate
        insert.
        """

        stmt = (
            select(CandidatePoolRunRow)
            .where(
                CandidatePoolRunRow.trade_date == trade_date,
                CandidatePoolRunRow.algorithm_key == algorithm_key,
                CandidatePoolRunRow.algorithm_version == algorithm_version,
                CandidatePoolRunRow.parameter_hash == parameter_hash,
                CandidatePoolRunRow.input_snapshot_id == input_snapshot_id,
            )
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_candidate_pool_run(row) if row is not None else None

    def list_by_status(
        self,
        status: CandidatePoolStatus | str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[CandidatePoolRun]:
        """Return runs in ``status`` ordered by ``trade_date`` desc then ``id`` asc.

        The descending ``trade_date`` order matches the dashboard use
        case where the most recent trade-day must come first. An
        unknown ``status`` value yields an empty result rather than
        raising so the repository can be probed safely.
        """

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        status_value = status.value if isinstance(status, CandidatePoolStatus) else str(status)
        stmt = (
            select(CandidatePoolRunRow)
            .where(CandidatePoolRunRow.status == status_value)
            .order_by(
                CandidatePoolRunRow.trade_date.desc(),
                CandidatePoolRunRow.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = self._session.scalars(stmt).all()
        return [_row_to_candidate_pool_run(row) for row in rows]

    def list_by_trade_date(
        self,
        trade_date: date,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[CandidatePoolRun]:
        """Return runs for ``trade_date`` ordered by ``created_at`` desc then ``id`` asc.

        The descending ``created_at`` order surfaces the latest run
        for the trade-day first; ties on ``created_at`` (e.g. two
        runs scheduled for the same instant) are broken by ``id`` so
        the result is stable.
        """

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        stmt = (
            select(CandidatePoolRunRow)
            .where(CandidatePoolRunRow.trade_date == trade_date)
            .order_by(
                CandidatePoolRunRow.created_at.desc(),
                CandidatePoolRunRow.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = self._session.scalars(stmt).all()
        return [_row_to_candidate_pool_run(row) for row in rows]

    def transition_status(
        self,
        run_id: UUID,
        new_status: CandidatePoolStatus,
        *,
        at: datetime | None = None,
        rejection_reason: str | None = None,
    ) -> CandidatePoolRun:
        """Persist a state-machine transition.

        The current row is loaded, the domain
        :meth:`CandidatePoolRun.transition_to` is invoked to enforce
        the legal transition graph, and the resulting
        :class:`CandidatePoolRun` is written back. ``at`` is the
        timezone-aware UTC timestamp for terminal-state transitions
        (``PUBLISHED`` / ``REJECTED``); ``rejection_reason`` is required
        by the domain invariant when transitioning to ``REJECTED``.
        """

        row = self._session.get(CandidatePoolRunRow, run_id)
        if row is None:
            raise LookupError(f"CandidatePoolRun {run_id!s} not found; cannot transition status")
        current = _row_to_candidate_pool_run(row)
        transitioned = current.transition_to(new_status, at=at, rejection_reason=rejection_reason)
        row.status = transitioned.status.value
        row.published_at = transitioned.published_at
        row.rejected_at = transitioned.rejected_at
        row.rejection_reason = transitioned.rejection_reason
        if transitioned.finished_at is not None:
            row.finished_at = transitioned.finished_at
        elif new_status is CandidatePoolStatus.VALIDATED:
            row.finished_at = at if at is not None else datetime.now(tz=UTC)
        self._session.flush()
        return _row_to_candidate_pool_run(row)


class SqlAlchemyCandidatePoolItemRepository:
    """Read/write access to ``analytics.candidate_pool_items``.

    One row per ``(run_id, instrument_id)`` pair; the composite primary
    key is enforced by the database. Items are persisted in bulk via
    :meth:`bulk_add` so a full result set is written with a single
    ``INSERT`` round-trip.

    The JSONB columns ``metrics``, ``rule_results`` and
    ``exclusion_reasons`` are JSON-encoded using the
    :mod:`invest_storage.repositories` helpers so the storage layer
    stays free of domain-specific value objects.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def bulk_add(
        self,
        run_id: UUID,
        items: Sequence[CandidatePoolItem],
    ) -> int:
        """Persist every ``items`` entry against ``run_id``.

        Returns the number of rows actually inserted. The database
        rejects duplicate ``(run_id, instrument_id)`` pairs with
        :class:`sqlalchemy.exc.IntegrityError` so the caller can rely
        on a single, deterministic bulk-insert contract.
        """

        if not items:
            return 0
        rows = [
            CandidatePoolItemRow(
                id=uuid.uuid4(),
                run_id=run_id,
                instrument_id=item.instrument_id.value,
                included=item.included,
                rank=item.rank,
                total_score=item.total_score,
                metrics=_metrics_to_json(item.metrics),
                rule_results=[_rule_outcome_to_json(r) for r in item.rule_results],
                exclusion_reasons=[_exclusion_reason_to_json(r) for r in item.exclusion_reasons],
            )
            for item in items
        ]
        self._session.add_all(rows)
        self._session.flush()
        return len(rows)

    def list_by_run_id(
        self,
        run_id: UUID,
        *,
        limit: int = 10_000,
        offset: int = 0,
    ) -> Sequence[CandidatePoolItem]:
        """Return the items for ``run_id`` ordered by ``included`` desc then ``rank`` asc.

        Included items (rank > 0) come first, ordered by ascending
        rank; excluded items follow in ``created_at`` ascending order.
        The composite primary key ``(run_id, instrument_id)`` is the
        natural tiebreaker for excluded items where no rank is set.
        """

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        stmt = (
            select(CandidatePoolItemRow)
            .where(CandidatePoolItemRow.run_id == run_id)
            .order_by(
                CandidatePoolItemRow.included.desc(),
                CandidatePoolItemRow.rank.asc().nulls_last(),
                CandidatePoolItemRow.instrument_id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = self._session.scalars(stmt).all()
        return [_row_to_candidate_pool_item(row) for row in rows]


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    raise TypeError(f"expected date or None, got {type(value).__name__}")


def _currency_value(value: Currency) -> str:
    return value.value if isinstance(value, Currency) else str(value)


def _status_value(value: InstrumentStatus) -> str:
    return value.value if isinstance(value, InstrumentStatus) else str(value)


def _provider_symbol_map(value: dict[str, str] | None) -> dict[str, str]:
    return dict(value) if value else {}


def _row_to_candidate_pool_run(row: CandidatePoolRunRow) -> CandidatePoolRun:
    return CandidatePoolRun(
        id=row.id,
        trade_date=row.trade_date,
        algorithm_key=row.algorithm_key,
        algorithm_version=row.algorithm_version,
        parameter_set_key=row.parameter_set_key,
        parameter_hash=row.parameter_hash,
        input_snapshot_id=row.input_snapshot_id,
        input_row_count=row.input_row_count,
        included_count=row.included_count,
        status=CandidatePoolStatus(row.status),
        created_at=row.started_at,
        finished_at=row.finished_at,
        published_at=row.published_at,
        rejected_at=row.rejected_at,
        rejection_reason=row.rejection_reason,
    )


def _row_to_candidate_pool_item(row: CandidatePoolItemRow) -> CandidatePoolItem:
    metrics = _metrics_from_json(row.metrics)
    rule_results = tuple(_rule_outcome_from_json(entry) for entry in (row.rule_results or []))
    exclusion_reasons = tuple(
        _exclusion_reason_from_json(entry) for entry in (row.exclusion_reasons or [])
    )
    return CandidatePoolItem(
        instrument_id=InstrumentId(row.instrument_id),
        included=row.included,
        rank=row.rank,
        total_score=(Decimal(row.total_score) if row.total_score is not None else None),
        metrics=metrics,
        rule_results=rule_results,
        exclusion_reasons=exclusion_reasons,
    )


def _metrics_to_json(metrics: Any) -> dict[str, str]:
    """Encode ``metrics`` (Mapping[str, Decimal]) as JSONB-compatible dict[str, str].

    Decimals are serialised as strings to preserve precision through
    JSON; the JSON loader parses them back with
    :func:`_metrics_from_json`.
    """

    if not metrics:
        return {}
    result: dict[str, str] = {}
    for key, value in dict(metrics).items():
        if isinstance(value, Decimal):
            result[str(key)] = format(value, "f")
        else:
            result[str(key)] = str(value)
    return result


def _metrics_from_json(value: Any) -> dict[str, Decimal]:
    """Decode a JSONB ``metrics`` blob into Mapping[str, Decimal]."""

    if not value:
        return {}
    return {str(key): Decimal(str(entry)) for key, entry in dict(value).items()}


def _rule_outcome_to_json(outcome: RuleOutcome) -> dict[str, Any]:
    """Encode a :class:`RuleOutcome` as a JSONB-compatible dict."""

    payload: dict[str, Any] = {
        "rule_key": outcome.rule_key,
        "passed": outcome.passed,
        "severity": outcome.severity.value,
    }
    if outcome.value is not None:
        payload["value"] = format(outcome.value, "f")
    if outcome.threshold is not None:
        payload["threshold"] = format(outcome.threshold, "f")
    if outcome.message is not None:
        payload["message"] = outcome.message
    return payload


def _rule_outcome_from_json(value: Any) -> RuleOutcome:
    """Decode a JSONB-encoded rule outcome into a :class:`RuleOutcome`."""

    if not isinstance(value, dict):
        raise TypeError(f"rule_results entry must be a dict, got {type(value).__name__}")
    rule_key = value.get("rule_key")
    if not rule_key:
        raise ValueError("rule_results entry missing non-empty 'rule_key'")
    passed = bool(value.get("passed"))
    severity = RuleSeverity(str(value.get("severity", RuleSeverity.ERROR.value)))
    raw_value = value.get("value")
    raw_threshold = value.get("threshold")
    return RuleOutcome(
        rule_key=str(rule_key),
        passed=passed,
        severity=severity,
        value=Decimal(str(raw_value)) if raw_value is not None else None,
        threshold=Decimal(str(raw_threshold)) if raw_threshold is not None else None,
        message=value.get("message"),
    )


def _exclusion_reason_to_json(reason: ExclusionReason) -> dict[str, str]:
    return {"code": reason.code, "message": reason.message}


def _exclusion_reason_from_json(value: Any) -> ExclusionReason:
    if not isinstance(value, dict):
        raise TypeError(f"exclusion_reasons entry must be a dict, got {type(value).__name__}")
    code = value.get("code")
    message = value.get("message")
    if not code:
        raise ValueError("exclusion_reasons entry missing non-empty 'code'")
    if not message:
        raise ValueError("exclusion_reasons entry missing non-empty 'message'")
    return ExclusionReason(code=str(code), message=str(message))


class SqlAlchemyEtfProfileRepository:
    """Read/write access to ``core.etf_profiles``.

    Stage DC-2 introduces a 1-1 ``core.etf_profiles`` table keyed by
    ``instrument_id`` (which is also the foreign key to
    ``core.instruments.id``). The repository owns the upsert-by-id
    idempotency contract: a re-write of the same profile overwrites
    every column except ``created_at`` and returns the freshly-mapped
    domain :class:`invest_domain.etf_profile.models.EtfProfile`. New
    profiles are inserted when no row exists yet.

    Callers MUST run the domain validator
    (:class:`invest_domain.etf_profile.models.EtfProfile.__post_init__`)
    on every input through the dataclass itself; the storage layer
    re-asserts the same defensive CHECK constraints as a last line of
    defence but never performs its own domain validation.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, profile: EtfProfile) -> EtfProfile:
        """Idempotent write keyed by ``profile.instrument_id``.

        When a row for ``instrument_id`` already exists the call
        rewrites every mutable column (``manager``, ``benchmark_index``,
        ``category``, ``inception_date``, ``fund_type``,
        ``management_fee``, ``custody_fee``, ``aum``, ``shares`` and
        ``updated_at``) without touching ``created_at``. When no row
        exists yet the call INSERTs one with the database-default
        ``created_at`` / ``updated_at``.

        The unique constraint is the primary-key uniqueness on
        ``instrument_id`` itself; an application that races two upserts
        on the same id will see one INSERT and one UPDATE after the
        loser replays through ``ON CONFLICT``.
        """

        values = {
            "instrument_id": profile.instrument_id,
            "manager": profile.manager,
            "benchmark_index": profile.benchmark_index,
            "category": profile.category,
            "inception_date": profile.inception_date,
            "fund_type": profile.fund_type,
            "management_fee": profile.management_fee,
            "custody_fee": profile.custody_fee,
            "aum": profile.aum,
            "shares": profile.shares,
        }
        excluded = insert(EtfProfileRow).excluded
        statement = insert(EtfProfileRow).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[EtfProfileRow.instrument_id],
            set_={
                "manager": excluded.manager,
                "benchmark_index": excluded.benchmark_index,
                "category": excluded.category,
                "inception_date": excluded.inception_date,
                "fund_type": excluded.fund_type,
                "management_fee": excluded.management_fee,
                "custody_fee": excluded.custody_fee,
                "aum": excluded.aum,
                "shares": excluded.shares,
                "updated_at": func.now(),
            },
        )
        self._session.execute(statement)
        self._session.flush()
        stored = self.get_by_id(profile.instrument_id)
        if stored is None:
            raise RuntimeError(
                "etf_profiles upsert succeeded but the row was not "
                "found on the subsequent read; this indicates a "
                "session/transaction misconfiguration"
            )
        return stored

    def get_by_id(self, instrument_id: UUID | InstrumentId) -> EtfProfile | None:
        raw_id = instrument_id.value if isinstance(instrument_id, InstrumentId) else instrument_id
        row = self._session.get(EtfProfileRow, raw_id)
        return _row_to_etf_profile(row) if row is not None else None

    def list_by_manager(
        self,
        manager: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EtfProfile]:
        return self._list_filtered(
            filters=[EtfProfileRow.manager == manager],
            limit=limit,
            offset=offset,
        )

    def list_by_category(
        self,
        category: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EtfProfile]:
        return self._list_filtered(
            filters=[EtfProfileRow.category == category],
            limit=limit,
            offset=offset,
        )

    def list_by_fund_type(
        self,
        fund_type: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EtfProfile]:
        return self._list_filtered(
            filters=[EtfProfileRow.fund_type == fund_type],
            limit=limit,
            offset=offset,
        )

    def list_all(self, *, limit: int = 100, offset: int = 0) -> list[EtfProfile]:
        return self._list_filtered(filters=[], limit=limit, offset=offset)

    def count_all(self) -> int:
        stmt = select(func.count(EtfProfileRow.instrument_id))
        return int(self._session.scalar(stmt) or 0)

    def _list_filtered(
        self,
        *,
        filters: list[Any],
        limit: int,
        offset: int,
    ) -> list[EtfProfile]:
        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        stmt = (
            select(EtfProfileRow)
            .where(*filters)
            .order_by(EtfProfileRow.instrument_id.asc())
            .limit(limit)
            .offset(offset)
        )
        rows = self._session.scalars(stmt).all()
        return [_row_to_etf_profile(row) for row in rows]


def _row_to_etf_profile(row: EtfProfileRow) -> EtfProfile:
    return EtfProfile(
        instrument_id=row.instrument_id,
        manager=row.manager,
        benchmark_index=row.benchmark_index,
        category=row.category,
        inception_date=_as_date(row.inception_date),
        fund_type=row.fund_type,
        management_fee=_as_decimal(row.management_fee),
        custody_fee=_as_decimal(row.custody_fee),
        aum=_as_decimal(row.aum),
        shares=_as_decimal(row.shares),
    )


class SqlAlchemyEtfProfileFieldRepository:
    """Read/write access to ``analytics.etf_profile_fields``.

    ``PR-ETF-PROFILE-04`` introduces the persistent record of every
    :class:`invest_domain.etf_profile.models.FieldEvidence`
    observation. The repository owns the natural-key idempotency
    contract: ``content_hash`` is the deterministic digest of the
    business content so a re-collect of the same observation from the
    same provider / revision is a no-op while a different
    provider / revision (different ``content_hash``) is stored as a
    coexisting row, preserving the full evidence history per the
    PR-ETF-PROFILE-01 conflict rules.

    Three write paths are exposed:

    - :meth:`add` — INSERT with ``ON CONFLICT (content_hash) DO
      NOTHING``; returns the persisted
      :class:`invest_domain.etf_profile.models.FieldEvidence` (or the
      existing one when the hash is already present).
    - :meth:`upsert` — INSERT-or-no-op on ``content_hash``; the
      repository never rewrites a row that already carries the same
      business content.

    Read paths mirror the application-service access patterns:

    - :meth:`get_by_instrument` — every evidence row for one
      ``instrument_id`` ordered by ``created_at`` ascending.
    - :meth:`get_by_instrument_field` — every evidence row for
      ``(instrument_id, field_key)`` ordered by ``created_at``
      ascending (the read surface that the conflict-aware resolver
      uses to compare two providers' observations of the same field).

    The instrument FK is enforced by the database; an application
    that references an unknown ``instrument_id`` gets
    :class:`sqlalchemy.exc.IntegrityError` from the engine.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, evidence: FieldEvidence) -> FieldEvidence:
        """Persist ``evidence`` and return the canonical domain object.

        Uses ``INSERT ... ON CONFLICT (content_hash) DO NOTHING`` so the
        unique constraint on ``content_hash`` is the idempotency guard.
        When the insert returns the new row id the repository refetches
        the row by ``content_hash`` and maps it back to a
        :class:`FieldEvidence`; when the insert is a no-op the
        repository fetches the existing row by ``content_hash`` and
        returns it instead. A ``RuntimeError`` is raised when the
        conflict path loses the existing row (defensive contract so a
        silent disappearance cannot be papered over).
        """

        payload = _evidence_to_row(evidence)
        statement = (
            insert(EtfProfileFieldRow)
            .values(**payload)
            .on_conflict_do_nothing(
                index_elements=[EtfProfileFieldRow.content_hash],
            )
            .returning(EtfProfileFieldRow.id)
        )
        inserted_id = self._session.execute(statement).scalar_one_or_none()
        self._session.flush()
        if inserted_id is not None:
            stored = self._find_by_content_hash(evidence.content_hash)
            if stored is None:
                raise RuntimeError(
                    "etf_profile_fields insert succeeded but the "
                    "row was not found on the subsequent read; this "
                    "indicates a session/transaction misconfiguration"
                )
            return stored

        existing = self._find_by_content_hash(evidence.content_hash)
        if existing is None:
            raise RuntimeError(
                "etf_profile_fields insert conflicted but the "
                "existing row was not found by content_hash"
            )
        return existing

    def upsert(self, evidence: FieldEvidence) -> FieldEvidence:
        """No-op when ``content_hash`` already exists; otherwise INSERT.

        The repository never rewrites a row that already carries the
        same business content: when the conflict-target is matched the
        existing row is returned without a write. This is the
        "additive" idempotency contract defined by PR-ETF-PROFILE-01
        (preserve all evidence history; a duplicate observation is a
        no-op).
        """

        existing = self._find_by_content_hash(evidence.content_hash)
        if existing is not None:
            return existing
        return self.add(evidence)

    def get_by_instrument(self, instrument_id: UUID | InstrumentId) -> list[FieldEvidence]:
        """Return every evidence row for ``instrument_id`` ordered by ``created_at``.

        The ``created_at`` ascending order matches the conflict-aware
        resolver's expectation: the oldest surviving observation comes
        first so the resolver can choose the most recent in a single
        pass.
        """

        raw_id = instrument_id.value if isinstance(instrument_id, InstrumentId) else instrument_id
        stmt = (
            select(EtfProfileFieldRow)
            .where(EtfProfileFieldRow.instrument_id == raw_id)
            .order_by(
                EtfProfileFieldRow.created_at.asc(),
                EtfProfileFieldRow.id.asc(),
            )
        )
        rows = self._session.scalars(stmt).all()
        return [_row_to_field_evidence(row) for row in rows]

    def get_by_instrument_field(
        self,
        instrument_id: UUID | InstrumentId,
        field_key: FieldKey,
    ) -> list[FieldEvidence]:
        """Return every evidence row for ``(instrument_id, field_key)``.

        Ordered by ``created_at`` ascending so the resolver can pick
        the freshest observation and surface any conflict rows
        alongside it. The (instrument_id, field_key) index makes the
        access O(log n) on the lookup columns.
        """

        raw_id = instrument_id.value if isinstance(instrument_id, InstrumentId) else instrument_id
        stmt = (
            select(EtfProfileFieldRow)
            .where(
                EtfProfileFieldRow.instrument_id == raw_id,
                EtfProfileFieldRow.field_key == field_key.value,
            )
            .order_by(
                EtfProfileFieldRow.created_at.asc(),
                EtfProfileFieldRow.id.asc(),
            )
        )
        rows = self._session.scalars(stmt).all()
        return [_row_to_field_evidence(row) for row in rows]

    def _find_by_content_hash(self, content_hash: str) -> FieldEvidence | None:
        stmt = (
            select(EtfProfileFieldRow)
            .where(EtfProfileFieldRow.content_hash == content_hash)
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_field_evidence(row) if row is not None else None


def _evidence_to_row(evidence: FieldEvidence) -> dict[str, Any]:
    """Translate a :class:`FieldEvidence` into a ``values`` dict for INSERT.

    The shape mirrors the :class:`EtfProfileFieldRow` column layout:
    the ``value`` is routed to the column that matches ``value_type``
    and the other two value columns stay ``NULL``. The CHECK
    constraints guard against any mismatch between ``value_type`` and
    the populated column.
    """

    text_value: str | None = None
    numeric_value: Decimal | None = None
    date_value: date | None = None
    if evidence.value_type is FieldValueType.TEXT and isinstance(evidence.value, str):
        text_value = evidence.value
    elif evidence.value_type is FieldValueType.DECIMAL and isinstance(evidence.value, Decimal):
        numeric_value = evidence.value
    elif evidence.value_type is FieldValueType.DATE and isinstance(evidence.value, date):
        date_value = evidence.value

    return {
        "instrument_id": evidence.instrument_id,
        "field_key": evidence.field_key.value,
        "value_type": evidence.value_type.value,
        "field_value_text": text_value,
        "field_value_numeric": numeric_value,
        "field_value_date": date_value,
        "source_provider": evidence.source.provider_key,
        "source_dataset": evidence.source.dataset_key,
        "observed_at": evidence.source.observed_at,
        "source_batch_id": evidence.source.source_batch_id,
        "source_revision": evidence.source.revision,
        "quality_status": evidence.quality_status.value,
        "confidence_score": evidence.confidence_score,
        "content_hash": evidence.content_hash,
    }


def _row_to_field_evidence(row: EtfProfileFieldRow) -> FieldEvidence:
    """Translate an ORM row into the domain :class:`FieldEvidence`."""

    value_type = FieldValueType(row.value_type)
    if value_type is FieldValueType.TEXT:
        value: str | Decimal | date | None = row.field_value_text
    elif value_type is FieldValueType.DECIMAL:
        value = _as_decimal(row.field_value_numeric)
    elif value_type is FieldValueType.DATE:
        value = _as_date(row.field_value_date)
    else:
        raise ValueError(f"unsupported value_type: {row.value_type!r}")
    source = FieldEvidenceSource(
        provider_key=row.source_provider,
        dataset_key=row.source_dataset,
        observed_at=row.observed_at,
        source_batch_id=row.source_batch_id,
        revision=row.source_revision,
    )
    confidence_score = _as_decimal(row.confidence_score)
    if confidence_score is None:
        raise ValueError("etf_profile_fields.confidence_score must not be NULL")
    return FieldEvidence(
        instrument_id=row.instrument_id,
        field_key=FieldKey(row.field_key),
        value=value,
        value_type=value_type,
        source=source,
        quality_status=QualityStatus(row.quality_status),
        confidence_score=confidence_score,
        content_hash=row.content_hash,
        created_at=row.created_at,
    )


@dataclass(frozen=True, slots=True)
class StoredIndexProfile:
    """Domain-side view of a persisted ``core.index_profiles`` row.

    Stage DC-3 introduces ``core.index_profiles`` (migration
    ``20260806_0011_dc3_exposure``) as the persistent record of every
    :class:`invest_domain.exposure.models.IndexProfile` observation.
    The domain dataclass carries no ``id`` field - the index profile
    is a content-only value object and the storage layer owns the
    synthetic primary key. ``StoredIndexProfile`` carries both the
    synthetic ``id`` (profile row PK) and the stable ``index_id`` FK
    to :class:`IndexIdentityRow` so application code can verify the
    FK chain without a second round-trip.

    ``index_id`` is the stable identity UUID from ``core.indexes`` that
    all FK-bearing tables (``index_constituent_snapshots``,
    ``etf_index_mappings``) reference; multiple profile revisions share
    the same ``index_id`` for the same underlying market index.

    ``revision`` mirrors the domain observation revision: the same
    index can have multiple rows with the same ``index_code`` and
    different ``content_hash`` / ``revision`` pairs so the history is
    preserved. ``created_at`` is the server-generated audit timestamp.
    """

    id: UUID
    index_id: UUID
    index_code: str
    index_name: str
    provenance: ExposureProvenance
    category: str | None
    as_of_date: date | None
    source_provider: str
    source_dataset: str
    source_batch_id: UUID | None
    source_revision: int
    confidence: Decimal
    revision: int
    content_hash: str
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StoredEtfIndexMapping:
    """Domain-side view of a persisted ``core.etf_index_mappings`` row.

    The :class:`invest_domain.exposure.models.EtfIndexMapping` domain
    dataclass is content-only: it carries the business keys
    (``etf_id``, ``index_id``, ``effective_from``, ``effective_to``)
    and the observation provenance but no synthetic identity. The
    storage layer mints a UUID ``id`` on INSERT; ``StoredEtfIndexMapping``
    carries that id so a downstream reader can re-link the mapping to
    its parent profile rows.
    """

    id: UUID
    etf_id: UUID
    index_id: UUID
    effective_from: date
    effective_to: date | None
    observed_at: datetime
    provenance: ExposureProvenance
    source_provider: str
    source_dataset: str
    source_batch_id: UUID | None
    source_revision: int
    confidence: Decimal
    revision: int
    content_hash: str
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StoredIndexIdentity:
    """Domain-side view of a persisted ``core.indexes`` row.

    Stage DC-3 introduces ``core.indexes`` (migration
    ``20260806_0011_dc3_exposure``) as the canonical store of every
    known market index. ``index_code`` is the natural business key
    (e.g. ``"000300.SH"``) enforced unique at the database boundary;
    the synthetic ``id`` (UUID) is the stable internal identifier that
    :class:`IndexProfileRow`, :class:`IndexConstituentSnapshotRow` and
    :class:`EtfIndexMappingRow` all FK back to.
    """

    id: UUID
    index_code: str
    index_name: str
    category: str | None
    first_observed_at: datetime
    last_observed_at: datetime
    created_at: datetime | None = None


class SqlAlchemyIndexIdentityRepository:
    """Read/write access to ``core.indexes``.

    The identity table is the canonical join target for all index
    observations. ``index_code`` is the natural business key enforced
    unique at the database boundary; the synthetic ``id`` (UUID) is the
    stable internal identifier threaded through profile and snapshot
    writes.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self, *, index_code: str, index_name: str, category: str | None = None
    ) -> StoredIndexIdentity:
        """Idempotent get-or-create by ``index_code``.

        Uses ``INSERT ... ON CONFLICT (index_code) DO NOTHING RETURNING id``
        to atomically attempt insertion; when a conflict is detected the
        existing row is fetched and returned. This guarantees that the
        returned :class:`StoredIndexIdentity` carries the stable ``id`` that
        all FK-bearing tables (``index_profiles``, ``etf_index_mappings``,
        ``index_constituent_snapshots``) reference.

        Validation: ``index_code`` and ``index_name`` must be non-empty
        after whitespace stripping; violations raise ``ValueError``.
        """
        if not index_code or not index_code.strip():
            raise ValueError("index_code must be non-empty")
        if not index_name or not index_name.strip():
            raise ValueError("index_name must be non-empty")

        now = datetime.now(tz=UTC)
        index_code = index_code.strip()
        index_name = index_name.strip()
        row_id = uuid.uuid4()

        stmt = (
            insert(IndexIdentityRow)
            .values(
                id=row_id,
                index_code=index_code,
                index_name=index_name,
                category=category,
                first_observed_at=now,
                last_observed_at=now,
            )
            .on_conflict_do_nothing(index_elements=["index_code"])
            .returning(IndexIdentityRow.id)
        )
        returned_id = self._session.execute(stmt).scalar_one_or_none()
        self._session.flush()

        if returned_id is not None:
            row = self._session.get(IndexIdentityRow, returned_id)
            return _row_to_stored_index_identity(row)

        existing = self.get_by_index_code(index_code)
        if existing is None:
            raise RuntimeError(
                "INSERT ON CONFLICT DO NOTHING returned no rows yet "
                "get_by_index_code found no existing identity; "
                "possible transaction isolation issue"
            )
        return existing

    def get_by_id(self, identity_id: UUID) -> StoredIndexIdentity | None:
        row = self._session.get(IndexIdentityRow, identity_id)
        return _row_to_stored_index_identity(row) if row is not None else None

    def get_by_index_code(self, index_code: str) -> StoredIndexIdentity | None:
        stmt = (
            select(IndexIdentityRow)
            .where(IndexIdentityRow.index_code == index_code)
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_stored_index_identity(row) if row is not None else None

    def list_by_index_code(
        self, index_code: str, *, limit: int = 100, offset: int = 0
    ) -> list[StoredIndexIdentity]:
        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        rows = self._session.scalars(
            select(IndexIdentityRow)
            .where(IndexIdentityRow.index_code == index_code)
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_stored_index_identity(row) for row in rows]


def _row_to_stored_index_identity(row: IndexIdentityRow) -> StoredIndexIdentity:
    return StoredIndexIdentity(
        id=row.id,
        index_code=row.index_code,
        index_name=row.index_name,
        category=row.category,
        first_observed_at=row.first_observed_at,
        last_observed_at=row.last_observed_at,
        created_at=row.created_at,
    )


class SqlAlchemyIndexProfileRepository:
    """Read/write access to ``core.index_profiles``.

    Stage DC-3 introduces the persistent record of every
    :class:`invest_domain.exposure.models.IndexProfile` observation.
    Two write paths are exposed:

    - :meth:`add` - INSERT with ``ON CONFLICT (content_hash) DO NOTHING``;
      returns the freshly-minted :class:`StoredIndexProfile` (or the
      pre-existing one when the hash is already present).
    - :meth:`upsert` - INSERT-or-no-op on ``content_hash``; never
      rewrites a row that already carries the same business content.

    The repository owns the synthetic ``id`` (profile row PK) and the
    ``index_id`` (stable FK to :class:`IndexIdentityRow`). Multiple
    profile revisions for the same underlying market index share the
    same ``index_id``. The application service MUST pass the same
    ``index_id`` (obtained from :meth:`SqlAlchemyIndexIdentityRepository.add`)
    to both :meth:`add` and :meth:`SqlAlchemyEtfIndexMappingRepository.upsert`
    so the ``core.etf_index_mappings.index_id`` FK chain stays closed;
    the invariant is verified by
    :class:`tests.storage.test_exposure_repositories_mock.IndexProfile
    RepositoryTests.test_index_id_matches_mapping_index_id`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, profile: IndexProfile, index_id: UUID) -> StoredIndexProfile:
        """Persist ``profile`` and return the stored domain object.

        Uses ``INSERT ... ON CONFLICT (content_hash) DO NOTHING`` so the
        unique constraint on ``content_hash`` is the idempotency guard.
        When the insert returns the new row id the repository
        refetches the row by ``content_hash`` and maps it back to a
        :class:`StoredIndexProfile`; when the insert is a no-op the
        repository fetches the existing row by ``content_hash`` and
        returns it instead. A :class:`RuntimeError` is raised when the
        conflict path loses the existing row so a silent disappearance
        cannot be papered over.

        ``index_id`` is the stable UUID of the :class:`IndexIdentityRow`
        this profile observation belongs to; the caller obtains it from
        :meth:`SqlAlchemyIndexIdentityRepository.add` (the idempotent
        get-or-create entry point) before calling this method.
        """

        if not isinstance(profile, IndexProfile):
            raise TypeError(
                "SqlAlchemyIndexProfileRepository.add expects an IndexProfile, "
                f"got {type(profile).__name__}"
            )
        statement = (
            insert(IndexProfileRow)
            .values(**_index_profile_to_row(profile, new_id=uuid.uuid4(), index_id=index_id))
            .on_conflict_do_nothing(
                index_elements=[IndexProfileRow.content_hash],
            )
            .returning(IndexProfileRow.id)
        )
        inserted_id = self._session.execute(statement).scalar_one_or_none()
        self._session.flush()
        stored = self._find_by_content_hash(profile.content_hash)
        if stored is None:
            raise RuntimeError(
                "index_profiles insert succeeded but the row was not "
                "found on the subsequent read; this indicates a "
                "session/transaction misconfiguration"
            )
        if inserted_id is None:
            return stored
        if stored.id != inserted_id:
            return StoredIndexProfile(
                id=inserted_id,
                index_id=stored.index_id,
                index_code=stored.index_code,
                index_name=stored.index_name,
                provenance=stored.provenance,
                category=stored.category,
                as_of_date=stored.as_of_date,
                source_provider=stored.source_provider,
                source_dataset=stored.source_dataset,
                source_batch_id=stored.source_batch_id,
                source_revision=stored.source_revision,
                confidence=stored.confidence,
                revision=stored.revision,
                content_hash=stored.content_hash,
                created_at=stored.created_at,
            )
        return stored

    def upsert(self, profile: IndexProfile, index_id: UUID) -> StoredIndexProfile:
        """No-op when ``content_hash`` already exists; otherwise INSERT.

        The repository never rewrites a row that already carries the
        same business content. This matches the PR-EXPOSURE-03
        idempotency contract: re-collects of the same observation
        return the previously-minted ``StoredIndexProfile.index_id`` so a
        downstream :class:`EtfIndexMappingRow.index_id` write can
        reuse the same UUID.
        """

        existing = self._find_by_content_hash(profile.content_hash)
        if existing is not None:
            return existing
        return self.add(profile, index_id)

    def get_by_id(self, profile_id: UUID) -> StoredIndexProfile | None:
        """Return the persisted profile with ``profile_id`` or ``None``."""

        row = self._session.get(IndexProfileRow, profile_id)
        return _row_to_stored_index_profile(row) if row is not None else None

    def find_by_content_hash(self, content_hash: str) -> StoredIndexProfile | None:
        """Return the persisted profile carrying ``content_hash`` or ``None``."""

        return self._find_by_content_hash(content_hash)

    def list_by_index_id(
        self,
        index_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoredIndexProfile]:
        """Return every persisted profile for ``index_id`` ordered by revision desc.

        The descending ``revision`` order surfaces the latest business
        observation first; ties on ``revision`` are broken by ``id`` so
        the result is stable.
        """

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        rows = self._session.scalars(
            select(IndexProfileRow)
            .where(IndexProfileRow.index_id == index_id)
            .order_by(
                IndexProfileRow.revision.desc(),
                IndexProfileRow.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_stored_index_profile(row) for row in rows]

    def list_by_provider(
        self,
        provider_key: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoredIndexProfile]:
        """Return every persisted profile whose ``source_provider`` matches.

        Useful for an operational "what did we collect from this
        provider?" dashboard - the storage layer projects
        ``(source_provider, source_dataset)`` straight from the
        provenance columns.
        """

        if not isinstance(provider_key, str) or not provider_key.strip():
            raise ValueError("list_by_provider requires a non-empty provider_key")
        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        rows = self._session.scalars(
            select(IndexProfileRow)
            .where(IndexProfileRow.source_provider == provider_key)
            .order_by(
                IndexProfileRow.revision.desc(),
                IndexProfileRow.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_stored_index_profile(row) for row in rows]

    def _find_by_content_hash(self, content_hash: str) -> StoredIndexProfile | None:
        stmt = (
            select(IndexProfileRow)
            .where(IndexProfileRow.content_hash == content_hash)
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_stored_index_profile(row) if row is not None else None


class SqlAlchemyIndexConstituentSnapshotRepository:
    """Read/write access to ``core.index_constituent_snapshots`` and children.

    Stage DC-3 introduces the persistent record of every
    :class:`invest_domain.exposure.models.IndexConstituentSnapshot`
    observation. Snapshots are immutable per ADR-0006 §3:
    ``add`` rejects an INSERT with the same ``content_hash`` and
    returns the existing snapshot instead, preserving the natural
    idempotency contract.

    Children rows (:class:`IndexConstituentRow`) are written in the
    same transaction as the parent snapshot so the read path can
    reassemble a fully-populated :class:`IndexConstituentSnapshot`
    in a single pass.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, snapshot: IndexConstituentSnapshot, index_id: UUID) -> IndexConstituentSnapshot:
        """Persist ``snapshot`` and its constituent children; return the input.

        Uses ``INSERT ... ON CONFLICT (content_hash) DO NOTHING`` for
        the parent row; on conflict the repository fetches the
        existing snapshot by ``content_hash`` and returns it unchanged.
        Child rows are inserted only on the fresh path so an
        idempotent re-collect never produces duplicate
        ``(snapshot_id, stock_code)`` pairs.

        ``index_id`` is the UUID of the :class:`IndexIdentityRow` this
        snapshot belongs to; the caller obtains it from
        :meth:`SqlAlchemyIndexIdentityRepository.get_by_index_code` before
        calling this method.
        """

        if not isinstance(snapshot, IndexConstituentSnapshot):
            raise TypeError(
                "SqlAlchemyIndexConstituentSnapshotRepository.add expects an "
                f"IndexConstituentSnapshot, got {type(snapshot).__name__}"
            )
        parent_values = _index_constituent_snapshot_to_row(snapshot, index_id=index_id)
        statement = (
            insert(IndexConstituentSnapshotRow)
            .values(**parent_values)
            .on_conflict_do_nothing(
                index_elements=[IndexConstituentSnapshotRow.content_hash],
            )
            .returning(IndexConstituentSnapshotRow.id)
        )
        inserted_id = self._session.execute(statement).scalar_one_or_none()
        self._session.flush()
        if inserted_id is None:
            existing = self._find_by_content_hash(snapshot.content_hash)
            if existing is None:
                raise RuntimeError(
                    "index_constituent_snapshots insert conflicted but the "
                    "existing row was not found by content_hash"
                )
            return existing
        if inserted_id != snapshot.id:
            return self.get_by_id(inserted_id) or snapshot
        self._bulk_add_children(
            inserted_id,
            snapshot.constituents,
            snapshot.provenance.revision,
        )
        return snapshot

    def get_by_id(self, snapshot_id: UUID) -> IndexConstituentSnapshot | None:
        """Return the snapshot with ``snapshot_id`` reconstructed with its constituents.

        The ``(snapshot_id)`` lookup is keyed on the parent's PRIMARY
        KEY; the constituent children are fetched in a single
        follow-up query and sorted by ``stock_code`` so the returned
        domain object matches the validator's invariant.
        """

        row = self._session.get(IndexConstituentSnapshotRow, snapshot_id)
        if row is None:
            return None
        return self._row_to_snapshot(row)

    def find_by_content_hash(
        self, content_hash: str
    ) -> IndexConstituentSnapshot | None:
        """Return the snapshot carrying ``content_hash`` or ``None``."""

        return self._find_by_content_hash(content_hash)

    def list_by_index_id(
        self,
        index_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IndexConstituentSnapshot]:
        """Return every snapshot for ``index_id`` ordered by ``as_of_date`` desc.

        The descending ``as_of_date`` order surfaces the most recent
        composition first; the secondary ``revision`` desc surface
        stale-history audits that need to see all known revisions.
        """

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        rows = self._session.scalars(
            select(IndexConstituentSnapshotRow)
            .where(IndexConstituentSnapshotRow.index_id == index_id)
            .order_by(
                IndexConstituentSnapshotRow.as_of_date.desc(),
                IndexConstituentSnapshotRow.revision.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return [self._row_to_snapshot(row) for row in rows]

    def _bulk_add_children(
        self,
        snapshot_id: UUID,
        constituents: tuple[IndexConstituent, ...],
        revision: int,
    ) -> None:
        if not constituents:
            return
        rows = [
            IndexConstituentRow(
                id=uuid.uuid4(),
                snapshot_id=snapshot_id,
                stock_code=item.stock_code,
                weight=item.weight,
                industry=item.industry,
                revision=revision,
            )
            for item in constituents
        ]
        self._session.add_all(rows)
        self._session.flush()

    def _row_to_snapshot(self, row: IndexConstituentSnapshotRow) -> IndexConstituentSnapshot:
        child_rows = self._session.scalars(
            select(IndexConstituentRow)
            .where(IndexConstituentRow.snapshot_id == row.id)
            .order_by(IndexConstituentRow.stock_code.asc())
        ).all()
        constituents = tuple(
            IndexConstituent(
                stock_code=child.stock_code,
                weight=_as_decimal(child.weight),
                industry=child.industry,
            )
            for child in child_rows
        )
        return IndexConstituentSnapshot.create(
            index_code=row.index_identity.index_code,
            as_of_date=row.as_of_date,
            observed_at=row.observed_at,
            constituents=constituents,
            provenance=_exposure_prov_from_row(
                source_provider=row.source_provider,
                source_dataset=row.source_dataset,
                observed_at=row.observed_at,
                source_batch_id=row.source_batch_id,
                source_revision=row.source_revision,
                confidence=row.confidence,
            ),
            id_factory=lambda: row.id,
            now_factory=lambda: row.created_at or row.observed_at,
        )

    def _find_by_content_hash(
        self, content_hash: str
    ) -> IndexConstituentSnapshot | None:
        stmt = (
            select(IndexConstituentSnapshotRow)
            .where(IndexConstituentSnapshotRow.content_hash == content_hash)
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return self._row_to_snapshot(row) if row is not None else None


class SqlAlchemyEtfIndexMappingRepository:
    """Read/write access to ``core.etf_index_mappings``.

    The natural idempotency key is ``content_hash``; the
    ``(etf_id, index_id, effective_from, revision)`` UNIQUE constraint
    is the version-key guard. The repository mints a synthetic ``id``
    on INSERT (the domain dataclass is content-only) and threads it
    through to the returned :class:`StoredEtfIndexMapping` so a
    downstream reader can re-link the mapping to its parent profile
    rows.

    The ``index_id`` FK references
    :class:`core.index_profiles.id` so callers MUST persist the
    profile row first and reuse its minted UUID - the storage layer
    enforces the referential integrity at the database boundary.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, mapping: EtfIndexMapping) -> StoredEtfIndexMapping:
        """Persist ``mapping`` and return the stored domain object."""

        if not isinstance(mapping, EtfIndexMapping):
            raise TypeError(
                "SqlAlchemyEtfIndexMappingRepository.add expects an EtfIndexMapping, "
                f"got {type(mapping).__name__}"
            )
        statement = (
            insert(EtfIndexMappingRow)
            .values(**_etf_index_mapping_to_row(mapping, new_id=uuid.uuid4()))
            .on_conflict_do_nothing(
                index_elements=[EtfIndexMappingRow.content_hash],
            )
            .returning(EtfIndexMappingRow.id)
        )
        inserted_id = self._session.execute(statement).scalar_one_or_none()
        self._session.flush()
        stored = self._find_by_content_hash(mapping.content_hash)
        if stored is None:
            raise RuntimeError(
                "etf_index_mappings insert succeeded but the row was not "
                "found on the subsequent read; this indicates a "
                "session/transaction misconfiguration"
            )
        if inserted_id is None or inserted_id == stored.id:
            return stored
        return StoredEtfIndexMapping(
            id=inserted_id,
            etf_id=stored.etf_id,
            index_id=stored.index_id,
            effective_from=stored.effective_from,
            effective_to=stored.effective_to,
            observed_at=stored.observed_at,
            provenance=stored.provenance,
            source_provider=stored.source_provider,
            source_dataset=stored.source_dataset,
            source_batch_id=stored.source_batch_id,
            source_revision=stored.source_revision,
            confidence=stored.confidence,
            revision=stored.revision,
            content_hash=stored.content_hash,
            created_at=stored.created_at,
        )

    def upsert(self, mapping: EtfIndexMapping) -> StoredEtfIndexMapping:
        """No-op when ``content_hash`` already exists; otherwise INSERT."""

        existing = self._find_by_content_hash(mapping.content_hash)
        if existing is not None:
            return existing
        return self.add(mapping)

    def get_by_id(self, mapping_id: UUID) -> StoredEtfIndexMapping | None:
        row = self._session.get(EtfIndexMappingRow, mapping_id)
        return _row_to_stored_etf_index_mapping(row) if row is not None else None

    def list_by_etf_id(
        self,
        etf_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoredEtfIndexMapping]:
        """Return every mapping for ``etf_id`` ordered by ``effective_from`` desc."""

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        rows = self._session.scalars(
            select(EtfIndexMappingRow)
            .where(EtfIndexMappingRow.etf_id == etf_id)
            .order_by(
                EtfIndexMappingRow.effective_from.desc(),
                EtfIndexMappingRow.revision.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_stored_etf_index_mapping(row) for row in rows]

    def list_by_index_id(
        self,
        index_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoredEtfIndexMapping]:
        """Return every mapping pointing at ``index_id`` ordered by ``effective_from`` desc."""

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        rows = self._session.scalars(
            select(EtfIndexMappingRow)
            .where(EtfIndexMappingRow.index_id == index_id)
            .order_by(
                EtfIndexMappingRow.effective_from.desc(),
                EtfIndexMappingRow.revision.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_stored_etf_index_mapping(row) for row in rows]

    def _find_by_content_hash(
        self, content_hash: str
    ) -> StoredEtfIndexMapping | None:
        stmt = (
            select(EtfIndexMappingRow)
            .where(EtfIndexMappingRow.content_hash == content_hash)
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_stored_etf_index_mapping(row) if row is not None else None


class SqlAlchemyEtfHoldingSnapshotRepository:
    """Read/write access to ``core.etf_holding_snapshots`` and children.

    Mirrors the snapshot pattern of
    :class:`SqlAlchemyIndexConstituentSnapshotRepository`: the parent
    ``etf_holding_snapshots`` row carries the natural idempotency key
    on ``content_hash`` and the child ``etf_holdings`` rows FK back
    with ``ON DELETE CASCADE``.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, snapshot: EtfHoldingSnapshot) -> EtfHoldingSnapshot:
        """Persist ``snapshot`` and its holdings; return the input.

        Idempotent on ``content_hash``: a re-collect of the same
        business content returns the existing snapshot unchanged.
        """

        if not isinstance(snapshot, EtfHoldingSnapshot):
            raise TypeError(
                "SqlAlchemyEtfHoldingSnapshotRepository.add expects an "
                f"EtfHoldingSnapshot, got {type(snapshot).__name__}"
            )
        parent_values = _etf_holding_snapshot_to_row(snapshot)
        statement = (
            insert(EtfHoldingSnapshotRow)
            .values(**parent_values)
            .on_conflict_do_nothing(
                index_elements=[EtfHoldingSnapshotRow.content_hash],
            )
            .returning(EtfHoldingSnapshotRow.id)
        )
        inserted_id = self._session.execute(statement).scalar_one_or_none()
        self._session.flush()
        if inserted_id is None:
            existing = self._find_by_content_hash(snapshot.content_hash)
            if existing is None:
                raise RuntimeError(
                    "etf_holding_snapshots insert conflicted but the "
                    "existing row was not found by content_hash"
                )
            return existing
        if inserted_id != snapshot.id:
            return self.get_by_id(inserted_id) or snapshot
        self._bulk_add_children(
            inserted_id,
            snapshot.holdings,
            snapshot.provenance.revision,
        )
        return snapshot

    def get_by_id(self, snapshot_id: UUID) -> EtfHoldingSnapshot | None:
        row = self._session.get(EtfHoldingSnapshotRow, snapshot_id)
        if row is None:
            return None
        return self._row_to_snapshot(row)

    def find_by_content_hash(
        self, content_hash: str
    ) -> EtfHoldingSnapshot | None:
        return self._find_by_content_hash(content_hash)

    def list_by_etf_id(
        self,
        etf_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EtfHoldingSnapshot]:
        """Return every snapshot for ``etf_id`` ordered by ``as_of_date`` desc."""

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        rows = self._session.scalars(
            select(EtfHoldingSnapshotRow)
            .where(EtfHoldingSnapshotRow.etf_id == etf_id)
            .order_by(
                EtfHoldingSnapshotRow.as_of_date.desc(),
                EtfHoldingSnapshotRow.revision.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return [self._row_to_snapshot(row) for row in rows]

    def _bulk_add_children(
        self,
        snapshot_id: UUID,
        holdings: tuple[EtfHolding, ...],
        revision: int,
    ) -> None:
        if not holdings:
            return
        rows = [
            EtfHoldingRow(
                id=uuid.uuid4(),
                snapshot_id=snapshot_id,
                stock_code=item.stock_code,
                weight=item.weight,
                industry=item.industry,
                revision=revision,
            )
            for item in holdings
        ]
        self._session.add_all(rows)
        self._session.flush()

    def _row_to_snapshot(self, row: EtfHoldingSnapshotRow) -> EtfHoldingSnapshot:
        child_rows = self._session.scalars(
            select(EtfHoldingRow)
            .where(EtfHoldingRow.snapshot_id == row.id)
            .order_by(EtfHoldingRow.stock_code.asc())
        ).all()
        holdings = tuple(
            EtfHolding(
                stock_code=child.stock_code,
                weight=_as_decimal(child.weight),
                industry=child.industry,
            )
            for child in child_rows
        )
        return EtfHoldingSnapshot.create(
            etf_id=row.etf_id,
            as_of_date=row.as_of_date,
            observed_at=row.observed_at,
            holdings=holdings,
            provenance=_exposure_prov_from_row(
                source_provider=row.source_provider,
                source_dataset=row.source_dataset,
                observed_at=row.observed_at,
                source_batch_id=row.source_batch_id,
                source_revision=row.source_revision,
                confidence=row.confidence,
            ),
            id_factory=lambda: row.id,
            now_factory=lambda: row.created_at or row.observed_at,
        )

    def _find_by_content_hash(
        self, content_hash: str
    ) -> EtfHoldingSnapshot | None:
        stmt = (
            select(EtfHoldingSnapshotRow)
            .where(EtfHoldingSnapshotRow.content_hash == content_hash)
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return self._row_to_snapshot(row) if row is not None else None


def _index_profile_to_row(profile: IndexProfile, *, new_id: UUID, index_id: UUID) -> dict[str, Any]:
    """Translate an :class:`IndexProfile` into a ``values`` dict for INSERT.

    Mirrors the :class:`IndexProfileRow` column layout and pins the
    synthetic ``id`` from the storage layer and the ``index_id`` FK to
    :class:`IndexIdentityRow`; the application service is expected to
    thread the returned :class:`StoredIndexProfile.index_id` into the
    ``EtfIndexMapping.index_id`` slot of the follow-up write.
    """

    return {
        "id": new_id,
        "index_id": index_id,
        "index_name": profile.index_name,
        "category": profile.category,
        "as_of_date": profile.as_of_date,
        "source_provider": profile.provenance.provider_key,
        "source_dataset": profile.provenance.dataset_key,
        "observed_at": profile.provenance.observed_at,
        "source_batch_id": profile.provenance.source_batch_id,
        "source_revision": profile.provenance.revision,
        "confidence": profile.provenance.confidence,
        "revision": profile.provenance.revision,
        "content_hash": profile.content_hash,
    }


def _etf_index_mapping_to_row(
    mapping: EtfIndexMapping, *, new_id: UUID
) -> dict[str, Any]:
    return {
        "id": new_id,
        "etf_id": mapping.etf_id,
        "index_id": mapping.index_id,
        "effective_from": mapping.effective_from,
        "effective_to": mapping.effective_to,
        "observed_at": mapping.observed_at,
        "source_provider": mapping.provenance.provider_key,
        "source_dataset": mapping.provenance.dataset_key,
        "source_batch_id": mapping.provenance.source_batch_id,
        "source_revision": mapping.provenance.revision,
        "confidence": mapping.provenance.confidence,
        "revision": mapping.provenance.revision,
        "content_hash": mapping.content_hash,
    }


def _index_constituent_snapshot_to_row(
    snapshot: IndexConstituentSnapshot, *, index_id: UUID
) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "index_id": index_id,
        "as_of_date": snapshot.as_of_date,
        "source_provider": snapshot.provenance.provider_key,
        "source_dataset": snapshot.provenance.dataset_key,
        "observed_at": snapshot.provenance.observed_at,
        "source_batch_id": snapshot.provenance.source_batch_id,
        "source_revision": snapshot.provenance.revision,
        "confidence": snapshot.provenance.confidence,
        "revision": snapshot.provenance.revision,
        "content_hash": snapshot.content_hash,
        "created_at": snapshot.created_at,
    }


def _etf_holding_snapshot_to_row(snapshot: EtfHoldingSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "etf_id": snapshot.etf_id,
        "as_of_date": snapshot.as_of_date,
        "source_provider": snapshot.provenance.provider_key,
        "source_dataset": snapshot.provenance.dataset_key,
        "observed_at": snapshot.provenance.observed_at,
        "source_batch_id": snapshot.provenance.source_batch_id,
        "source_revision": snapshot.provenance.revision,
        "confidence": snapshot.provenance.confidence,
        "revision": snapshot.provenance.revision,
        "content_hash": snapshot.content_hash,
        "created_at": snapshot.created_at,
    }


def _exposure_prov_from_row(
    *,
    source_provider: str,
    source_dataset: str,
    observed_at: datetime,
    source_batch_id: UUID | None,
    source_revision: int,
    confidence: Any,
) -> ExposureProvenance:
    """Reconstruct an :class:`ExposureProvenance` from the row columns."""

    return ExposureProvenance(
        provider_key=source_provider,
        dataset_key=source_dataset,
        observed_at=observed_at,
        source_batch_id=source_batch_id,
        revision=source_revision,
        confidence=_as_decimal(confidence) or Decimal("1"),
    )


def _row_to_stored_index_profile(
    row: IndexProfileRow,
) -> StoredIndexProfile:
    return StoredIndexProfile(
        id=row.id,
        index_id=row.index_id,
        index_code=row.index_identity.index_code,
        index_name=row.index_name,
        provenance=_exposure_prov_from_row(
            source_provider=row.source_provider,
            source_dataset=row.source_dataset,
            observed_at=row.observed_at,
            source_batch_id=row.source_batch_id,
            source_revision=row.source_revision,
            confidence=row.confidence,
        ),
        category=row.category,
        as_of_date=_as_date(row.as_of_date),
        source_provider=row.source_provider,
        source_dataset=row.source_dataset,
        source_batch_id=row.source_batch_id,
        source_revision=row.source_revision,
        confidence=_as_decimal(row.confidence) or Decimal("1"),
        revision=row.revision,
        content_hash=row.content_hash,
        created_at=row.created_at,
    )


def _row_to_stored_etf_index_mapping(
    row: EtfIndexMappingRow,
) -> StoredEtfIndexMapping:
    return StoredEtfIndexMapping(
        id=row.id,
        etf_id=row.etf_id,
        index_id=row.index_id,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        observed_at=row.observed_at,
        provenance=_exposure_prov_from_row(
            source_provider=row.source_provider,
            source_dataset=row.source_dataset,
            observed_at=row.observed_at,
            source_batch_id=row.source_batch_id,
            source_revision=row.source_revision,
            confidence=row.confidence,
        ),
        source_provider=row.source_provider,
        source_dataset=row.source_dataset,
        source_batch_id=row.source_batch_id,
        source_revision=row.source_revision,
        confidence=_as_decimal(row.confidence) or Decimal("1"),
        revision=row.revision,
        content_hash=row.content_hash,
        created_at=row.created_at,
    )


class SqlAlchemyDataFreshnessReader:
    """Read-only adapter that powers the ``/api/v1/data-freshness`` slice.

    The endpoint needs a small handful of "fresh, partial, stale, missing,
    failed" inputs sourced from five different tables; expressing every
    one through a dedicated domain repository would either widen those
    repositories past their natural read surface or duplicate
    repository state (snapshot / run / pipeline_run all already live
    behind their own readers) just to expose one tiny aggregate
    query. Instead the freshness reader is a thin SQLAlchemy adapter
    that runs the same raw ``text()`` queries the pre-PR-08 router did
    and returns the rows as the dataclasses declared in
    :mod:`invest_api.application.data_freshness`. The application layer
    depends only on the :class:`DataFreshnessReader` ``Protocol``; this
    concrete class is wired in by the dependency factory.

    The class intentionally stays read-only and stateless w.r.t. its
    session - ``execute`` never mutates ORM state and never flushes -
    so it can be constructed against the FastAPI-provided session and
    share the transaction lifetime the rest of the HTTP handlers use.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_snapshot_for_trade_date(self, trade_date: date):
        """Return the most recent snapshot for ``trade_date`` or ``None``.

        See :class:`invest_api.application.data_freshness.InputSnapshotRow`
        for the typed read-side shape. The return type is intentionally
        not annotated so the storage layer stays decoupled from the
        HTTP-side application dataclass; the application :class:`Protocol`
        check happens at the call site.
        """

        row = self._session.execute(
            text(
                """
                SELECT id, instrument_ids, row_count
                FROM analytics.input_snapshots
                WHERE snapshot_date = :trade_date
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"trade_date": trade_date},
        ).first()
        if row is None:
            return None
        raw_ids = row[1]
        instrument_ids: list[str] = (
            list(raw_ids) if isinstance(raw_ids, (list, tuple)) else []
        )
        return _DataFreshnessInputSnapshotRow(
            id=row[0],
            instrument_ids=tuple(instrument_ids),
            row_count=int(row[2]),
        )

    def get_latest_published_candidate_pool_run(self):
        """Return the most recent ``PUBLISHED`` candidate-pool run or ``None``.

        See :class:`invest_api.application.data_freshness.PublishedCandidatePoolRunRow`
        for the typed read-side shape; the return type is intentionally
        not annotated so the storage layer stays decoupled from the
        HTTP-side application dataclass.
        """

        row = self._session.execute(
            text(
                """
                SELECT id, trade_date, input_row_count
                FROM analytics.candidate_pool_runs
                WHERE status = 'published'
                ORDER BY trade_date DESC, created_at DESC
                LIMIT 1
                """
            )
        ).first()
        if row is None:
            return None
        return _DataFreshnessPublishedRunRow(
            id=row[0],
            trade_date=row[1],
            input_row_count=int(row[2]),
        )

    def count_included_items_for_run(self, run_id: UUID) -> int:
        """Return the number of ``included = true`` items for ``run_id``."""

        return int(
            self._session.execute(
                text(
                    """
                    SELECT count(*) FROM analytics.candidate_pool_items
                    WHERE run_id = :run_id AND included = true
                    """
                ),
                {"run_id": run_id},
            ).scalar_one()
        )

    def count_daily_bars_for_snapshot(
        self, trade_date: date, instrument_ids: tuple[str, ...]
    ) -> int:
        """Return the distinct daily-bar count for ``trade_date`` scoped to the snapshot.

        ``instrument_ids`` is the JSON-shaped list from the matching
        input snapshot; it is cast to ``uuid[]`` before the ``ANY``
        comparison so PostgreSQL keeps the existing index path.
        """

        if not instrument_ids:
            return 0
        return int(
            self._session.execute(
                text(
                    """
                    SELECT count(DISTINCT instrument_id) FROM core.daily_bars
                    WHERE trade_date = :trade_date
                      AND instrument_id = ANY(CAST(:ids AS uuid[]))
                    """
                ),
                {"trade_date": trade_date, "ids": list(instrument_ids)},
            ).scalar_one()
        )

    def count_daily_bars_for_published_run(
        self, trade_date: date, run_id: UUID
    ) -> int:
        """Return the distinct daily-bar count scoped to the published run's items.

        Membership comes from ``analytics.candidate_pool_items`` for the
        most recently published run so the count remains scoped to the
        personal universe even when no same-day snapshot exists.
        """

        return int(
            self._session.execute(
                text(
                    """
                    SELECT count(DISTINCT db.instrument_id)
                    FROM core.daily_bars db
                    WHERE db.trade_date = :trade_date
                      AND db.instrument_id IN (
                          SELECT instrument_id
                          FROM analytics.candidate_pool_items
                          WHERE run_id = :run_id
                      )
                    """
                ),
                {"trade_date": trade_date, "run_id": run_id},
            ).scalar_one()
        )

    def get_latest_pipeline_run_for_partition(
        self, *, job_key: str, partition_key: str
    ):
        """Return the latest pipeline run for ``(job_key, partition_key)`` or ``None``.

        See :class:`invest_api.application.data_freshness.PipelineRunRow`
        for the typed read-side shape; the return type is intentionally
        not annotated so the storage layer stays decoupled from the
        HTTP-side application dataclass.
        """

        row = self._session.execute(
            text(
                """
                SELECT id, status FROM ops.pipeline_runs
                WHERE job_key = :job_key AND partition_key = :partition_key
                ORDER BY started_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                """
            ),
            {"job_key": job_key, "partition_key": partition_key},
        ).first()
        if row is None:
            return None
        return _DataFreshnessPipelineRunRow(id=row[0], status=row[1])


@dataclass(frozen=True, slots=True)
class _DataFreshnessInputSnapshotRow:
    """Internal ``analytics.input_snapshots`` row shape for the freshness reader.

    Mirrors :class:`invest_api.application.data_freshness.InputSnapshotRow`
    structurally so the application :class:`typing.Protocol` check
    passes; declared here (instead of imported from the API package) so
    the storage layer never has to depend on the HTTP layer.
    """

    id: UUID
    instrument_ids: tuple[str, ...]
    row_count: int


@dataclass(frozen=True, slots=True)
class _DataFreshnessPublishedRunRow:
    """Internal candidate-pool run row shape for the freshness reader.

    Mirrors
    :class:`invest_api.application.data_freshness.PublishedCandidatePoolRunRow`
    structurally so the application :class:`typing.Protocol` check passes.
    """

    id: UUID
    trade_date: date
    input_row_count: int


@dataclass(frozen=True, slots=True)
class _DataFreshnessPipelineRunRow:
    """Internal ``ops.pipeline_runs`` row shape for the freshness reader.

    Mirrors :class:`invest_api.application.data_freshness.PipelineRunRow`
    structurally so the application :class:`typing.Protocol` check
    passes.
    """

    id: UUID
    status: str | None


class SqlAlchemyMarketObservationSnapshotRepository:
    """Persistence for ``analytics.market_observation_snapshots`` (Stage 4B Phase 2).

    Owns the parent/child pair ``analytics.market_observation_snapshots``
    / ``analytics.market_observations``. Snapshots are immutable:

    - :meth:`add` is idempotent on ``content_hash`` (the database
      ``UNIQUE`` constraint is the final guard; the repository uses
      ``ON CONFLICT DO NOTHING`` and returns the pre-existing row on
      conflict so a same-input re-run is a no-op instead of an error).
    - Children are inserted in the same transaction as the parent and
      re-read on every domain-side round-trip so callers always receive
      a fully-populated
      :class:`invest_domain.analytics.market_observations.
      MarketObservationSnapshot`.
    - There is no update / delete surface.

    Read paths: :meth:`get_by_id` (storage PK),
    :meth:`get_by_content_hash` (natural idempotency key) and
    :meth:`list_by_date` (``as_of_date`` ascending-created order).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, snapshot: MarketObservationSnapshot) -> MarketObservationSnapshot:
        statement = (
            insert(MarketObservationSnapshotRow)
            .values(
                id=uuid.uuid4(),
                snapshot_id=snapshot.snapshot_id,
                input_snapshot_id=UUID(str(snapshot.input_snapshot_id)),
                as_of_date=snapshot.as_of_date,
                algorithm_version=snapshot.algorithm_version,
                scope_type=snapshot.scope_type,
                scope_key=snapshot.scope_key,
                quality_status=snapshot.quality_status.value,
                freshness_status=snapshot.freshness_status.value,
                content_hash=snapshot.content_hash,
            )
            .on_conflict_do_nothing(
                constraint="uq_market_observation_snapshots_content_hash",
            )
            .returning(MarketObservationSnapshotRow.id)
        )
        inserted_id = self._session.execute(statement).scalar_one_or_none()
        if inserted_id is None:
            existing = self.get_by_content_hash(snapshot.content_hash)
            if existing is None:
                raise RuntimeError(
                    "market observation snapshot insert conflicted but the "
                    "existing row was not found"
                )
            return existing
        for observation in snapshot.observations:
            self._session.execute(
                insert(MarketObservationRow).values(
                    **_market_observation_to_row(observation, inserted_id)
                )
            )
        self._session.flush()
        return snapshot

    def get_by_id(self, snapshot_row_id: UUID) -> MarketObservationSnapshot | None:
        row = self._session.get(MarketObservationSnapshotRow, snapshot_row_id)
        return self._row_to_snapshot(row) if row is not None else None

    def get_by_content_hash(self, content_hash: str) -> MarketObservationSnapshot | None:
        row = self._session.scalars(
            select(MarketObservationSnapshotRow)
            .where(MarketObservationSnapshotRow.content_hash == content_hash)
            .limit(1)
        ).first()
        return self._row_to_snapshot(row) if row is not None else None

    def list_by_date(self, as_of_date: date) -> list[MarketObservationSnapshot]:
        rows = self._session.scalars(
            select(MarketObservationSnapshotRow)
            .where(MarketObservationSnapshotRow.as_of_date == as_of_date)
            .order_by(
                MarketObservationSnapshotRow.created_at.asc(),
                MarketObservationSnapshotRow.id.asc(),
            )
        ).all()
        return [self._row_to_snapshot(row) for row in rows]

    def _row_to_snapshot(self, row: MarketObservationSnapshotRow) -> MarketObservationSnapshot:
        item_rows = self._session.scalars(
            select(MarketObservationRow)
            .where(MarketObservationRow.snapshot_id == row.id)
            .order_by(MarketObservationRow.observation_key.asc())
        ).all()
        observations = tuple(_row_to_market_observation(item) for item in item_rows)
        return MarketObservationSnapshot(
            input_snapshot_id=row.input_snapshot_id,
            as_of_date=row.as_of_date,
            observations=observations,
            algorithm_version=row.algorithm_version,
            scope_type=row.scope_type,
            scope_key=row.scope_key,
            quality_status=QualityStatus(row.quality_status),
            freshness_status=FreshnessStatus(row.freshness_status),
            content_hash=row.content_hash,
            snapshot_id=row.snapshot_id,
        )


def _market_observation_to_row(
    observation: MarketObservation,
    snapshot_row_id: UUID,
) -> dict[str, Any]:
    value_numeric: Decimal | None = None
    value_text: str | None = None
    if isinstance(observation.value, Decimal):
        value_numeric = observation.value
    elif isinstance(observation.value, str):
        value_text = observation.value
    return {
        "id": uuid.uuid4(),
        "snapshot_id": snapshot_row_id,
        "observation_key": observation.observation_key,
        "value_numeric": value_numeric,
        "value_text": value_text,
        "unit": observation.unit,
        "observed_date": observation.observed_date,
        "source_kind": observation.source_kind,
        "source_ref": observation.source_ref,
        "quality_status": observation.quality_status.value,
        "item_hash": observation.item_hash,
    }


def _row_to_market_observation(row: MarketObservationRow) -> MarketObservation:
    value: Decimal | str | None
    if row.value_numeric is not None:
        value = row.value_numeric
    elif row.value_text is not None:
        value = row.value_text
    else:
        value = None
    return MarketObservation(
        observation_key=row.observation_key,
        value=value,
        unit=row.unit,
        observed_date=row.observed_date,
        source_kind=row.source_kind,
        source_ref=row.source_ref,
        quality_status=QualityStatus(row.quality_status),
        item_hash=row.item_hash,
    )


class SqlAlchemyResearchEvidenceBundleRepository:
    """Persistence for :class:`ResearchEvidenceBundle` (Stage 4B Phase 3).

    Owns ``analytics.research_evidence_bundles`` and honours the
    immutability contract: there is no ``update`` / ``delete``
    surface because the bundle is an audit-grade identity record.
    The natural idempotency key is the deterministic
    ``bundle_hash`` enforced by the database-level
    ``uq_research_evidence_bundles_bundle_hash`` unique constraint.

    Per Stage 4B Phase 3 plan, a changed market snapshot set for the
    same ``(research_case_id, evidence_pack_id)`` pair MUST create a
    new bundle identity so the full audit history is preserved;
    there is no ``UNIQUE (research_case_id, evidence_pack_id)``
    constraint. :meth:`get_by_case_and_pack` therefore returns the
    newest bundle (``created_at DESC``, tie-break ``bundle_id DESC``)
    so callers see a deterministic "current" record; the full history
    remains addressable via :meth:`list_by_case` or by the synthetic
    ``bundle_id``.

    :meth:`add` uses ``ON CONFLICT (bundle_hash) DO NOTHING`` so a
    re-build of the same bundle content never produces a duplicate
    row. When the insert is a no-op the repository refetches the
    existing row by ``bundle_hash`` and returns the canonical
    :class:`ResearchEvidenceBundle` so callers always see the
    storage-assigned identity.

    The ``market_snapshot_ids`` / ``market_snapshot_hashes`` /
    ``market_snapshot_dates`` JSONB arrays are the only evidence the
    bundle row carries for the Analytics-owned snapshots; the
    application layer is responsible for handing the full
    :class:`MarketObservationSnapshot` to
    :func:`invest_domain.research.evidence_bundle.build_projection`
    so the projection can be regenerated from the canonical sources.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, bundle: ResearchEvidenceBundle) -> ResearchEvidenceBundle:
        if not isinstance(bundle, ResearchEvidenceBundle):
            raise TypeError(
                "SqlAlchemyResearchEvidenceBundleRepository.add expects a "
                f"ResearchEvidenceBundle, got {type(bundle).__name__}"
            )
        statement = (
            insert(ResearchEvidenceBundleRow)
            .values(
                bundle_id=bundle.bundle_id,
                research_case_id=bundle.research_case_id,
                evidence_pack_id=bundle.evidence_pack_id,
                evidence_pack_hash=bundle.evidence_pack_hash,
                as_of_date=bundle.as_of_date,
                market_snapshot_ids=[
                    item.snapshot_id for item in bundle.market_snapshot_refs
                ],
                market_snapshot_hashes=[
                    item.content_hash for item in bundle.market_snapshot_refs
                ],
                market_snapshot_dates=[
                    item.as_of_date.isoformat()
                    for item in bundle.market_snapshot_refs
                ],
                schema_version=bundle.schema_version,
                bundle_hash=bundle.bundle_hash,
                created_at=bundle.created_at,
            )
            .on_conflict_do_nothing(
                index_elements=[ResearchEvidenceBundleRow.bundle_hash],
            )
            .returning(ResearchEvidenceBundleRow.bundle_id)
        )
        self._session.execute(statement)
        self._session.flush()
        existing = self._find_by_bundle_hash(bundle.bundle_hash)
        if existing is None:
            raise RuntimeError(
                "research_evidence_bundles insert succeeded but the row "
                "was not found on the subsequent read; this indicates "
                "a session/transaction misconfiguration"
            )
        return existing

    def get_by_id(self, bundle_id: UUID) -> ResearchEvidenceBundle | None:
        row = self._session.get(ResearchEvidenceBundleRow, bundle_id)
        return _row_to_research_evidence_bundle(row) if row is not None else None

    def get_by_bundle_hash(
        self, bundle_hash: str
    ) -> ResearchEvidenceBundle | None:
        return self._find_by_bundle_hash(bundle_hash)

    def get_by_case_and_pack(
        self, *, research_case_id: UUID, evidence_pack_id: UUID
    ) -> ResearchEvidenceBundle | None:
        """Return the newest bundle for a ``(case, pack)`` pair, or ``None``.

        A ``(research_case_id, evidence_pack_id)`` pair may legitimately
        have multiple bundles coexisting — every changed market
        snapshot set creates a fresh ``bundle_hash`` and therefore a
        fresh bundle row (see plan §4B Phase 3). This helper returns
        the deterministic "current" record ordered by
        ``created_at DESC`` with ``bundle_id DESC`` as the tie-break
        so two bundles stamped at the same instant still resolve
        deterministically. The full history is addressable via
        :meth:`list_by_case` or by ``bundle_id``.
        """

        row = self._session.scalars(
            select(ResearchEvidenceBundleRow)
            .where(
                ResearchEvidenceBundleRow.research_case_id == research_case_id,
                ResearchEvidenceBundleRow.evidence_pack_id == evidence_pack_id,
            )
            .order_by(
                ResearchEvidenceBundleRow.created_at.desc(),
                ResearchEvidenceBundleRow.bundle_id.desc(),
            )
            .limit(1)
        ).first()
        return _row_to_research_evidence_bundle(row) if row is not None else None

    def list_by_case(
        self, research_case_id: UUID
    ) -> list[ResearchEvidenceBundle]:
        rows = self._session.scalars(
            select(ResearchEvidenceBundleRow)
            .where(ResearchEvidenceBundleRow.research_case_id == research_case_id)
            .order_by(
                ResearchEvidenceBundleRow.created_at.asc(),
                ResearchEvidenceBundleRow.bundle_id.asc(),
            )
        ).all()
        return [_row_to_research_evidence_bundle(row) for row in rows]

    def _find_by_bundle_hash(
        self, bundle_hash: str
    ) -> ResearchEvidenceBundle | None:
        if (
            not isinstance(bundle_hash, str)
            or len(bundle_hash) != 64
        ):
            return None
        row = self._session.scalars(
            select(ResearchEvidenceBundleRow)
            .where(ResearchEvidenceBundleRow.bundle_hash == bundle_hash)
            .limit(1)
        ).first()
        return _row_to_research_evidence_bundle(row) if row is not None else None


def _row_to_research_evidence_bundle(
    row: ResearchEvidenceBundleRow,
) -> ResearchEvidenceBundle:
    snapshot_ids = [str(item) for item in (row.market_snapshot_ids or [])]
    snapshot_hashes = [str(item) for item in (row.market_snapshot_hashes or [])]
    snapshot_dates = [
        date.fromisoformat(str(item)) for item in (row.market_snapshot_dates or [])
    ]
    refs = tuple(
        MarketSnapshotRef(
            snapshot_id=snapshot_id,
            content_hash=content_hash,
            as_of_date=snapshot_date,
        )
        for snapshot_id, content_hash, snapshot_date in zip(
            snapshot_ids, snapshot_hashes, snapshot_dates, strict=True
        )
    )
    return ResearchEvidenceBundle(
        bundle_id=row.bundle_id,
        research_case_id=row.research_case_id,
        evidence_pack_id=row.evidence_pack_id,
        evidence_pack_hash=row.evidence_pack_hash,
        market_snapshot_refs=refs,
        schema_version=row.schema_version,
        bundle_hash=row.bundle_hash,
        created_at=row.created_at,
        as_of_date=row.as_of_date,
    )


class ResearchEvidenceBundleTransitionError(RuntimeError):
    """Raised when ``add`` cannot honour the bundle uniqueness contract."""
